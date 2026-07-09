from __future__ import annotations

from . import m13_registry as registry
from .m13_contracts import M13BatchRecord, ProductionIdentity
from .m13_lifecycle_common import (
    ELIGIBLE_ABANDON_STATES,
    LIFECYCLE_SCHEMA,
    M13LifecycleError,
    LifecycleMutationResult,
    assert_candidate_channel_available,
    assert_expected_production,
    assert_no_active_production_lease,
    batch_registration,
    batch_update,
    digest,
    ensure_batch_version,
    ensure_head_version,
    last_event,
    mutation_result,
    require_utc,
    supersession_closure,
    write_artifacts,
    write_head,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore


def supersede_batches(
    store: ObjectStore,
    *,
    new_record: M13BatchRecord,
    expected_batch_versions: dict[str, int],
    rationale: str,
    actor: str,
    occurred_at: str,
    observed_production: ProductionIdentity,
    expected_registry_version: int,
) -> LifecycleMutationResult:
    target_ids = tuple(new_record.supersedes_batch_ids)
    if new_record.state != "planned" or not target_ids:
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_INVALID",
            "superseding batch must be planned and name target batches",
        )
    if target_ids != tuple(sorted(set(target_ids))):
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_NONCANONICAL",
            "supersedes_batch_ids must be unique and sorted",
        )
    if set(expected_batch_versions) != set(target_ids):
        raise M13LifecycleError(
            "M13_LIFECYCLE_EXPECTED_VERSIONS_INVALID",
            "expected batch versions must match superseded batches",
        )
    if not actor or not rationale.strip():
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_INVALID",
            "actor and rationale are required",
        )
    require_utc(occurred_at, "occurred_at")
    head, etag = registry._load_head(store)
    target_pairs = {
        batch_id: registry._load_batch_snapshot(store, head, batch_id)
        for batch_id in target_ids
    }
    identity = {
        "schema_version": f"{LIFECYCLE_SCHEMA}/supersede-request",
        "new_record": new_record.to_identity(),
        "expected_batch_versions": {
            key: expected_batch_versions[key] for key in sorted(expected_batch_versions)
        },
        "rationale": rationale,
        "actor": actor,
        "occurred_at": occurred_at,
        "observed_production": observed_production.to_identity(),
        "expected_registry_version": expected_registry_version,
    }
    action_id = digest(identity, "mlife")
    evidence_key = f"m13/v2/lifecycle/supersessions/{action_id}.json"
    existing_new = head["batches"].get(new_record.batch_id)
    if existing_new is not None:
        new_snapshot, existing_record = registry._load_batch_snapshot(
            store,
            head,
            new_record.batch_id,
        )
        target_replays = all(
            pair[1].state == "abandoned"
            and last_event(store, pair[0]).get("request_id") == action_id
            for pair in target_pairs.values()
        )
        if (
            existing_record.to_identity() == new_record.to_identity()
            and last_event(store, new_snapshot).get("request_id") == action_id
            and target_replays
        ):
            records = (existing_record, *(pair[1] for pair in target_pairs.values()))
            return mutation_result(
                action_id=action_id,
                action="supersede",
                registry_version=head["registry_version"],
                records=records,
                snapshot_keys={
                    record.batch_id: head["batches"][record.batch_id]["snapshot_key"]
                    for record in records
                },
                event_keys={
                    existing_record.batch_id: new_snapshot["event_keys"][-1],
                    **{
                        batch_id: pair[0]["event_keys"][-1]
                        for batch_id, pair in target_pairs.items()
                    },
                },
                evidence_key=evidence_key,
                idempotent=True,
            )
        raise M13LifecycleError(
            "M13_LIFECYCLE_BATCH_IDENTITY_COLLISION",
            "superseding batch identity is already registered differently",
        )
    ensure_head_version(head, expected_registry_version)
    assert_no_active_production_lease(store)
    assert_expected_production(new_record, observed_production)
    assert_candidate_channel_available(store, head, new_record)
    if new_record.batch_id in target_ids:
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_CYCLE",
            "batch cannot supersede itself",
        )
    if new_record.batch_id in supersession_closure(store, head, target_ids):
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_CYCLE",
            "supersession graph would contain a cycle",
        )
    target_records: list[M13BatchRecord] = []
    for batch_id in target_ids:
        snapshot, record = target_pairs[batch_id]
        ensure_batch_version(snapshot, expected_batch_versions[batch_id], batch_id)
        assert_expected_production(record, observed_production)
        if record.state not in ELIGIBLE_ABANDON_STATES:
            raise M13LifecycleError(
                "M13_LIFECYCLE_SUPERSEDE_STATE_INVALID",
                "target batch cannot be superseded",
                batch_id=batch_id,
                state=record.state,
            )
        if record.seed.source_repository != new_record.seed.source_repository:
            raise M13LifecycleError(
                "M13_LIFECYCLE_SOURCE_REPOSITORY_MISMATCH",
                "superseding batches must share the source repository",
            )
        target_records.append(record)
    registry_version = head["registry_version"] + 1
    new_artifact = batch_registration(
        record=new_record,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        event_type="batch_registered_superseding",
    )
    target_artifacts = tuple(
        batch_update(
            record=record,
            snapshot=target_pairs[record.batch_id][0],
            registry_version=registry_version,
            action_id=action_id,
            actor=actor,
            occurred_at=occurred_at,
            target_state="abandoned",
            event_type="batch_superseded",
        )
        for record in target_records
    )
    all_artifacts = (new_artifact, *target_artifacts)
    evidence = {
        **identity,
        "schema_version": f"{LIFECYCLE_SCHEMA}/supersession",
        "action_id": action_id,
        "new_batch_id": new_record.batch_id,
        "superseded_batch_ids": list(target_ids),
        "governance": GOVERNANCE_NO_WRITE,
        "physical_delete_permitted": False,
    }
    idempotent = write_artifacts(
        store,
        evidence_key=evidence_key,
        evidence=evidence,
        batch_artifacts=all_artifacts,
    )
    batches = dict(head["batches"])
    event_keys: dict[str, str] = {}
    snapshot_keys: dict[str, str] = {}
    resulting_records: list[M13BatchRecord] = []
    for _, snapshot, event_key, snapshot_key in all_artifacts:
        record = registry._record_from_identity(snapshot["record"])
        batches[record.batch_id] = registry._summary(snapshot_key, snapshot)
        event_keys[record.batch_id] = event_key
        snapshot_keys[record.batch_id] = snapshot_key
        resulting_records.append(record)
    write_head(
        store,
        etag=etag,
        head={
            **head,
            "registry_version": registry_version,
            "updated_at": occurred_at,
            "batches": batches,
        },
    )
    return mutation_result(
        action_id=action_id,
        action="supersede",
        registry_version=registry_version,
        records=tuple(resulting_records),
        snapshot_keys=snapshot_keys,
        event_keys=event_keys,
        evidence_key=evidence_key,
        idempotent=idempotent,
    )
