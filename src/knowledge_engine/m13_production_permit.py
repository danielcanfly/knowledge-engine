from __future__ import annotations

from dataclasses import replace

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import ProductionIdentity, assert_expected_previous_production
from .m13_coordination_common import (
    COORDINATOR_SCHEMA,
    PERMIT_ID_RE,
    PRODUCTION_LEASE_KEY,
    M13CoordinatorError,
    ProductionMutationPermit,
    cas_write,
    digest,
    lease_value,
    load_json,
    permit_from_lease,
    registry_preconditions,
    require_current_lease,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore


def issue_production_mutation_permit(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    issued_at: str,
    observed_production: ProductionIdentity,
) -> ProductionMutationPermit:
    current, etag = require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=issued_at,
        allowed_states={"active", "permit_issued"},
    )
    snapshot, record, _, _ = registry_preconditions(
        store,
        batch_id=current.batch_id,
        expected_registry_version=current.expected_registry_version,
        expected_batch_version=current.expected_batch_version,
        observed_production=observed_production,
        required_state="awaiting_production_slot",
    )
    identity = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-permit-request",
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
        "batch_id": current.batch_id,
        "operation_id": current.operation_id,
        "holder_id": current.holder_id,
        "expected_registry_version": current.expected_registry_version,
        "expected_batch_version": current.expected_batch_version,
        "expected_previous_production": current.expected_previous_production.to_identity(),
        "snapshot_event_hash": snapshot["current_event_hash"],
        "candidate_channel": record.candidate_channel,
        "issued_at": issued_at,
        "expires_at": current.expires_at,
    }
    permit_id = digest(identity, "mpermit")
    permit_key = f"m13/v2/concurrency/production/permits/{permit_id}.json"
    if current.state == "permit_issued":
        if current.permit_id != permit_id or current.permit_key != permit_key:
            raise M13CoordinatorError(
                "M13_PRODUCTION_PERMIT_ALREADY_ISSUED", "lease has a different permit"
            )
        artifact = load_json(store, permit_key, "production permit")
        if artifact.get("permit_id") != permit_id:
            raise M13CoordinatorError("M13_PRODUCTION_PERMIT_INVALID", "permit diverged")
        return permit_from_lease(
            current,
            issued_at=issued_at,
            permit_id=permit_id,
            permit_key=permit_key,
            idempotent=True,
        )
    artifact = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/production-permit",
        "permit_id": permit_id,
        "permit_key": permit_key,
        "governance": {
            **GOVERNANCE_NO_WRITE,
            "release_write_permitted": True,
            "production_write_permitted": True,
            "permanent_ledger_append_permitted": True,
        },
    }
    idempotent = put_immutable(store, permit_key, json_bytes(artifact))
    updated = replace(
        current,
        state="permit_issued",
        permit_id=permit_id,
        permit_key=permit_key,
        updated_at=issued_at,
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(updated),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return permit_from_lease(
        updated,
        issued_at=issued_at,
        permit_id=permit_id,
        permit_key=permit_key,
        idempotent=idempotent,
    )


def _transition_marker(
    store: ObjectStore,
    *,
    permit: ProductionMutationPermit,
    registry_version: int,
    batch_version: int,
    event_key: str,
    snapshot_key: str,
    occurred_at: str,
) -> str:
    marker_id = digest(
        {
            "permit_id": permit.permit_id,
            "registry_version": registry_version,
            "batch_version": batch_version,
            "event_key": event_key,
            "snapshot_key": snapshot_key,
        },
        "mtransition",
    )
    marker_key = f"m13/v2/concurrency/production/transitions/{marker_id}.json"
    marker = {
        "schema_version": f"{COORDINATOR_SCHEMA}/promotion-transition",
        "marker_id": marker_id,
        "permit_id": permit.permit_id,
        "lease_id": permit.lease_id,
        "generation": permit.generation,
        "fencing_token": permit.fencing_token,
        "batch_id": permit.batch_id,
        "operation_id": permit.operation_id,
        "registry_version": registry_version,
        "batch_version": batch_version,
        "event_key": event_key,
        "snapshot_key": snapshot_key,
        "occurred_at": occurred_at,
        "governance": GOVERNANCE_NO_WRITE,
    }
    put_immutable(store, marker_key, json_bytes(marker))
    return marker_key


def transition_batch_to_promoting(
    store: ObjectStore,
    *,
    permit: ProductionMutationPermit,
    actor: str,
    occurred_at: str,
    observed_production: ProductionIdentity,
) -> registry.RegistryMutationResult:
    if not PERMIT_ID_RE.fullmatch(permit.permit_id):
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_INVALID", "permit_id is invalid")
    current, _ = require_current_lease(
        store,
        lease_id=permit.lease_id,
        holder_id=permit.holder_id,
        fencing_token=permit.fencing_token,
        now=occurred_at,
        allowed_states={"permit_issued"},
    )
    if current.permit_id != permit.permit_id or current.permit_key != permit.permit_key:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_STALE", "permit is not current")
    artifact = load_json(store, permit.permit_key, "production permit")
    if artifact.get("permit_id") != permit.permit_id:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_INVALID", "permit artifact mismatch")

    head, head_etag = registry._load_head(store)
    snapshot, record = registry._load_batch_snapshot(store, head, permit.batch_id)
    last_event = load_json(store, snapshot["event_keys"][-1], "last registry event")
    if record.state == "promoting" and last_event.get("request_id") == permit.permit_id:
        snapshot_key = head["batches"][permit.batch_id]["snapshot_key"]
        _transition_marker(
            store,
            permit=permit,
            registry_version=head["registry_version"],
            batch_version=snapshot["batch_version"],
            event_key=snapshot["event_keys"][-1],
            snapshot_key=snapshot_key,
            occurred_at=occurred_at,
        )
        return registry.RegistryMutationResult(
            batch_id=permit.batch_id,
            registry_version=head["registry_version"],
            batch_version=snapshot["batch_version"],
            state="promoting",
            snapshot_key=snapshot_key,
            event_key=snapshot["event_keys"][-1],
            idempotent=True,
            operation_id=permit.operation_id,
        )
    if head["registry_version"] != permit.expected_registry_version:
        raise M13CoordinatorError(
            "M13_PRODUCTION_REGISTRY_VERSION_STALE", "registry version changed"
        )
    if snapshot["batch_version"] != permit.expected_batch_version:
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_VERSION_STALE", "batch version changed"
        )
    if record.state != "awaiting_production_slot":
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_STATE_INVALID", "batch is not awaiting production"
        )
    if record.candidate_channel is None or not registry._completed_operation(
        snapshot, "release_comparison"
    ):
        raise M13CoordinatorError(
            "M13_PRODUCTION_PRECONDITION_INVALID", "candidate or comparison is missing"
        )
    try:
        assert_expected_previous_production(
            expected=record.seed.production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE", "production changed before transition"
        ) from exc
    if current.operation_id != permit.operation_id or current.batch_id != permit.batch_id:
        raise M13CoordinatorError(
            "M13_PRODUCTION_PERMIT_STALE", "permit identity differs from lease"
        )

    registry_version = head["registry_version"] + 1
    batch_version = snapshot["batch_version"] + 1
    snapshot_key = (
        f"{registry._batch_prefix(permit.batch_id)}/snapshots/"
        f"{batch_version:06d}-{permit.permit_id}.json"
    )
    event = registry._event(
        batch_id=permit.batch_id,
        batch_version=batch_version,
        event_type="coordinator_authorized_transition",
        occurred_at=occurred_at,
        actor=actor,
        from_state="awaiting_production_slot",
        to_state="promoting",
        previous_event_hash=snapshot["current_event_hash"],
        request_id=permit.permit_id,
        snapshot_key=snapshot_key,
    )
    event_key = (
        f"{registry._batch_prefix(permit.batch_id)}/events/"
        f"{batch_version:06d}-{event['event_sha256']}.json"
    )
    next_record = replace(record, state="promoting")
    promotion_summary = {
        "operation_id": permit.operation_id,
        "kind": "production_promotion",
        "state": "running",
        "result_at": occurred_at,
        "evidence_count": 2,
        "operation_key": permit.permit_key,
    }
    summaries = [
        summary
        for summary in snapshot["operation_summaries"]
        if summary.get("operation_id") != permit.operation_id
    ]
    summaries.append(promotion_summary)
    next_snapshot = registry._snapshot(
        record=next_record,
        batch_version=batch_version,
        registry_version=registry_version,
        updated_at=occurred_at,
        event_keys=[*snapshot["event_keys"], event_key],
        operation_summaries=sorted(summaries, key=lambda item: item["operation_id"]),
        current_event_hash=event["event_sha256"],
    )
    event_idempotent = put_immutable(store, event_key, json_bytes(event))
    snapshot_idempotent = put_immutable(store, snapshot_key, json_bytes(next_snapshot))
    batches = dict(head["batches"])
    batches[permit.batch_id] = registry._summary(snapshot_key, next_snapshot)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": occurred_at,
        "batches": batches,
    }
    try:
        registry._write_head(store, current_etag=head_etag, head=new_head)
    except registry.M13RegistryError as exc:
        replay_head, _ = registry._load_head(store)
        replay_snapshot, replay_record = registry._load_batch_snapshot(
            store, replay_head, permit.batch_id
        )
        replay_event = load_json(
            store, replay_snapshot["event_keys"][-1], "last registry event"
        )
        replay_matches = (
            replay_record.state == "promoting"
            and replay_event.get("request_id") == permit.permit_id
        )
        if replay_matches:
            replay_snapshot_key = replay_head["batches"][permit.batch_id]["snapshot_key"]
            _transition_marker(
                store,
                permit=permit,
                registry_version=replay_head["registry_version"],
                batch_version=replay_snapshot["batch_version"],
                event_key=replay_snapshot["event_keys"][-1],
                snapshot_key=replay_snapshot_key,
                occurred_at=occurred_at,
            )
            return registry.RegistryMutationResult(
                batch_id=permit.batch_id,
                registry_version=replay_head["registry_version"],
                batch_version=replay_snapshot["batch_version"],
                state="promoting",
                snapshot_key=replay_snapshot_key,
                event_key=replay_snapshot["event_keys"][-1],
                idempotent=True,
                operation_id=permit.operation_id,
            )
        raise M13CoordinatorError(
            "M13_PRODUCTION_REGISTRY_CONFLICT", "registry changed during transition"
        ) from exc
    _transition_marker(
        store,
        permit=permit,
        registry_version=registry_version,
        batch_version=batch_version,
        event_key=event_key,
        snapshot_key=snapshot_key,
        occurred_at=occurred_at,
    )
    return registry.RegistryMutationResult(
        batch_id=permit.batch_id,
        registry_version=registry_version,
        batch_version=batch_version,
        state="promoting",
        snapshot_key=snapshot_key,
        event_key=event_key,
        idempotent=event_idempotent and snapshot_idempotent,
        operation_id=permit.operation_id,
    )
