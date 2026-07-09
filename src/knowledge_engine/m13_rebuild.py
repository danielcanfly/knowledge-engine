from __future__ import annotations

from . import m13_registry as registry
from .m13_contracts import M13BatchRecord, ProductionIdentity
from .m13_lifecycle_common import (
    LIFECYCLE_SCHEMA,
    REBUILD_SOURCE_STATES,
    M13LifecycleError,
    LifecycleMutationResult,
    assert_candidate_channel_available,
    assert_expected_production,
    assert_no_active_production_lease,
    batch_registration,
    digest,
    ensure_batch_version,
    ensure_head_version,
    last_event,
    mutation_result,
    require_utc,
    write_artifacts,
    write_head,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore


def register_rebuild_batch(
    store: ObjectStore,
    *,
    new_record: M13BatchRecord,
    rationale: str,
    actor: str,
    occurred_at: str,
    observed_production: ProductionIdentity,
    expected_registry_version: int,
    expected_ancestor_batch_version: int,
) -> LifecycleMutationResult:
    ancestor_id = new_record.rebuilt_from_batch_id
    if new_record.state != "planned" or ancestor_id is None:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_INVALID",
            "rebuild batch must be planned and name rebuilt_from_batch_id",
        )
    if new_record.supersedes_batch_ids != (ancestor_id,):
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_LINEAGE_INVALID",
            "rebuild batch must supersede exactly its direct ancestor",
        )
    if new_record.candidate_channel is None:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_CHANNEL_REQUIRED",
            "rebuild batch must reserve a new candidate channel",
        )
    if not actor or not rationale.strip():
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_INVALID",
            "actor and rationale are required",
        )
    require_utc(occurred_at, "occurred_at")
    head, etag = registry._load_head(store)
    ancestor_snapshot, ancestor = registry._load_batch_snapshot(store, head, ancestor_id)
    identity = {
        "schema_version": f"{LIFECYCLE_SCHEMA}/rebuild-request",
        "new_record": new_record.to_identity(),
        "ancestor_batch_id": ancestor_id,
        "expected_ancestor_batch_version": expected_ancestor_batch_version,
        "rationale": rationale,
        "actor": actor,
        "occurred_at": occurred_at,
        "observed_production": observed_production.to_identity(),
        "expected_registry_version": expected_registry_version,
    }
    action_id = digest(identity, "mlife")
    evidence_key = f"m13/v2/lifecycle/rebuilds/{action_id}.json"
    existing = head["batches"].get(new_record.batch_id)
    if existing is not None:
        snapshot, record = registry._load_batch_snapshot(store, head, new_record.batch_id)
        if (
            record.to_identity() == new_record.to_identity()
            and last_event(store, snapshot).get("request_id") == action_id
        ):
            return mutation_result(
                action_id=action_id,
                action="rebuild",
                registry_version=head["registry_version"],
                records=(record,),
                snapshot_keys={new_record.batch_id: existing["snapshot_key"]},
                event_keys={new_record.batch_id: snapshot["event_keys"][-1]},
                evidence_key=evidence_key,
                idempotent=True,
            )
        raise M13LifecycleError(
            "M13_LIFECYCLE_BATCH_IDENTITY_COLLISION",
            "rebuild batch identity is already registered differently",
        )
    ensure_head_version(head, expected_registry_version)
    ensure_batch_version(
        ancestor_snapshot,
        expected_ancestor_batch_version,
        ancestor_id,
    )
    assert_no_active_production_lease(store)
    assert_expected_production(ancestor, observed_production)
    assert_expected_production(new_record, observed_production)
    assert_candidate_channel_available(store, head, new_record)
    if ancestor.state not in REBUILD_SOURCE_STATES:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_ANCESTOR_STATE_INVALID",
            "rebuild ancestor must be abandoned or rejected",
            state=ancestor.state,
        )
    if ancestor.candidate_channel is None or not registry._completed_operation(
        ancestor_snapshot,
        "candidate_build",
    ):
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_ANCESTOR_EVIDENCE_MISSING",
            "rebuild ancestor must have candidate build evidence and a channel",
        )
    if new_record.candidate_channel == ancestor.candidate_channel:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_CHANNEL_REUSED",
            "rebuild candidate channel must differ from ancestor",
        )
    if (
        new_record.seed.source_repository != ancestor.seed.source_repository
        or new_record.seed.source_commit_sha != ancestor.seed.source_commit_sha
        or new_record.seed.production != ancestor.seed.production
    ):
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_ORIGIN_MISMATCH",
            "rebuild must preserve source and production origin",
        )
    if new_record.batch_id == ancestor.batch_id:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_IDENTITY_REUSED",
            "rebuild must have a distinct batch identity",
        )
    registry_version = head["registry_version"] + 1
    artifact = batch_registration(
        record=new_record,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        event_type="batch_registered_rebuild",
    )
    event, snapshot, event_key, snapshot_key = artifact
    evidence = {
        **identity,
        "schema_version": f"{LIFECYCLE_SCHEMA}/rebuild",
        "action_id": action_id,
        "ancestor_candidate_channel": ancestor.candidate_channel,
        "reserved_candidate_channel": new_record.candidate_channel,
        "event_key": event_key,
        "snapshot_key": snapshot_key,
        "governance": GOVERNANCE_NO_WRITE,
        "physical_delete_permitted": False,
    }
    idempotent = write_artifacts(
        store,
        evidence_key=evidence_key,
        evidence=evidence,
        batch_artifacts=(artifact,),
    )
    batches = dict(head["batches"])
    batches[new_record.batch_id] = registry._summary(snapshot_key, snapshot)
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
        action="rebuild",
        registry_version=registry_version,
        records=(new_record,),
        snapshot_keys={new_record.batch_id: snapshot_key},
        event_keys={new_record.batch_id: event_key},
        evidence_key=evidence_key,
        idempotent=idempotent,
    )
