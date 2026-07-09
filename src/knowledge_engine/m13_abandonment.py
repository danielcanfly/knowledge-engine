from __future__ import annotations

from . import m13_registry as registry
from .m13_contracts import BATCH_ID_RE, ProductionIdentity
from .m13_lifecycle_common import (
    LIFECYCLE_SCHEMA,
    AbandonmentReason,
    ELIGIBLE_ABANDON_STATES,
    M13LifecycleError,
    LifecycleMutationResult,
    assert_expected_production,
    assert_no_active_production_lease,
    batch_update,
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


def abandon_batch(
    store: ObjectStore,
    *,
    batch_id: str,
    reason: AbandonmentReason,
    rationale: str,
    actor: str,
    occurred_at: str,
    observed_production: ProductionIdentity,
    expected_registry_version: int,
    expected_batch_version: int,
) -> LifecycleMutationResult:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise M13LifecycleError("M13_LIFECYCLE_BATCH_INVALID", "batch_id is invalid")
    if not actor or not rationale.strip():
        raise M13LifecycleError(
            "M13_LIFECYCLE_ABANDONMENT_INVALID",
            "actor and rationale are required",
        )
    require_utc(occurred_at, "occurred_at")
    head, etag = registry._load_head(store)
    snapshot, record = registry._load_batch_snapshot(store, head, batch_id)
    identity = {
        "schema_version": f"{LIFECYCLE_SCHEMA}/abandon-request",
        "batch_id": batch_id,
        "reason": reason,
        "rationale": rationale,
        "actor": actor,
        "occurred_at": occurred_at,
        "observed_production": observed_production.to_identity(),
        "expected_registry_version": expected_registry_version,
        "expected_batch_version": expected_batch_version,
    }
    action_id = digest(identity, "mlife")
    evidence_key = f"m13/v2/lifecycle/abandonments/{action_id}.json"
    final_event = last_event(store, snapshot)
    if record.state == "abandoned" and final_event.get("request_id") == action_id:
        return mutation_result(
            action_id=action_id,
            action="abandon",
            registry_version=head["registry_version"],
            records=(record,),
            snapshot_keys={batch_id: head["batches"][batch_id]["snapshot_key"]},
            event_keys={batch_id: snapshot["event_keys"][-1]},
            evidence_key=evidence_key,
            idempotent=True,
        )
    ensure_head_version(head, expected_registry_version)
    ensure_batch_version(snapshot, expected_batch_version, batch_id)
    assert_no_active_production_lease(store)
    assert_expected_production(record, observed_production)
    if record.state not in ELIGIBLE_ABANDON_STATES:
        raise M13LifecycleError(
            "M13_LIFECYCLE_ABANDON_STATE_INVALID",
            "batch state cannot be abandoned",
            batch_id=batch_id,
            state=record.state,
        )
    registry_version = head["registry_version"] + 1
    artifact = batch_update(
        record=record,
        snapshot=snapshot,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        target_state="abandoned",
        event_type="batch_abandoned",
    )
    event, next_snapshot, event_key, snapshot_key = artifact
    next_record = registry._record_from_identity(next_snapshot["record"])
    evidence = {
        **identity,
        "schema_version": f"{LIFECYCLE_SCHEMA}/abandonment",
        "action_id": action_id,
        "from_state": record.state,
        "to_state": "abandoned",
        "candidate_channel": record.candidate_channel,
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
    batches[batch_id] = registry._summary(snapshot_key, next_snapshot)
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
        action="abandon",
        registry_version=registry_version,
        records=(next_record,),
        snapshot_keys={batch_id: snapshot_key},
        event_keys={batch_id: event_key},
        evidence_key=evidence_key,
        idempotent=idempotent,
    )
