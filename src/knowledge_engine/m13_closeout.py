from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from typing import Any

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .errors import IntegrityError
from .m13_contracts import (
    BATCH_ID_RE,
    ExpectedPreviousProduction,
    M13OperationRequest,
    M13OperationResult,
    ProductionIdentity,
    stable_json_bytes,
)
from .m13_coordination_common import load_json, load_production_lease
from .m13_operator import load_production_identity
from .m13_retention import RetentionArtifact
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes

CLOSEOUT_SCHEMA = "knowledge-engine-m13-closeout/v1"
CLOSEOUT_ID_RE = re.compile(r"^mclose_[a-f0-9]{32}$")
LEDGER_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/#-]{2,180}$")


class M13CloseoutError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class CloseoutResult:
    closeout_id: str
    batch_id: str
    operation_id: str
    registry_version: int
    batch_version: int
    state: str
    evidence_key: str
    operation_key: str
    event_key: str
    snapshot_key: str
    resulting_production: ProductionIdentity
    ledger_references: tuple[str, ...]
    evidence_sha256: str
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["resulting_production"] = self.resulting_production.to_identity()
        return {
            "schema_version": f"{CLOSEOUT_SCHEMA}/result",
            **value,
            "governance": dict(GOVERNANCE_NO_WRITE),
        }

    def retention_artifact(self, *, closed_at: str) -> RetentionArtifact:
        return RetentionArtifact(
            key=self.evidence_key,
            artifact_class="evidence",
            created_at=closed_at,
            sha256=self.evidence_sha256,
            batch_id=self.batch_id,
            release_id=self.resulting_production.release_id,
            reference_ids=(
                self.closeout_id,
                self.operation_id,
                *self.ledger_references,
            ),
        )


def _digest(value: dict[str, Any], prefix: str) -> str:
    digest = hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _validate_ledger_references(values: tuple[str, ...]) -> tuple[str, ...]:
    if not values or len(values) != len(set(values)):
        raise M13CloseoutError(
            "M13_CLOSEOUT_LEDGER_REFERENCES_INVALID",
            "unique ledger references are required",
        )
    for value in values:
        if not LEDGER_REFERENCE_RE.fullmatch(value):
            raise M13CloseoutError(
                "M13_CLOSEOUT_LEDGER_REFERENCES_INVALID",
                "ledger reference is invalid",
                ledger_reference=value,
            )
    return tuple(sorted(values))


def _production_from_value(value: Any, field_name: str) -> ProductionIdentity:
    if not isinstance(value, dict):
        raise M13CloseoutError(
            "M13_CLOSEOUT_COMPLETION_INVALID",
            f"{field_name} is invalid",
        )
    try:
        return ProductionIdentity(
            release_id=str(value["release_id"]),
            manifest_sha256=str(value["manifest_sha256"]),
            pointer_sha256=str(value["pointer_sha256"]),
        )
    except (KeyError, ValueError) as exc:
        raise M13CloseoutError(
            "M13_CLOSEOUT_COMPLETION_INVALID",
            f"{field_name} is invalid",
        ) from exc


def _promotion_summary(
    snapshot: dict[str, Any],
    *,
    operation_id: str,
) -> dict[str, Any]:
    matches = [
        summary
        for summary in snapshot["operation_summaries"]
        if summary.get("operation_id") == operation_id
        and summary.get("kind") == "production_promotion"
    ]
    if len(matches) != 1:
        raise M13CloseoutError(
            "M13_CLOSEOUT_PROMOTION_SUMMARY_INVALID",
            "one production promotion summary is required",
            operation_id=operation_id,
        )
    summary = matches[0]
    if summary.get("state") not in {"running", "completed"}:
        raise M13CloseoutError(
            "M13_CLOSEOUT_PROMOTION_STATE_INVALID",
            "production promotion summary has an invalid state",
            state=summary.get("state"),
        )
    return summary


def _closeout_operation(
    *,
    batch_id: str,
    actor: str,
    closed_at: str,
    expected_previous: ProductionIdentity,
    evidence_key: str,
    completion_key: str,
    ledger_references: tuple[str, ...],
) -> M13OperationResult:
    request = M13OperationRequest(
        kind="closeout",
        batch_id=batch_id,
        requested_by=actor,
        requested_at=closed_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=expected_previous,
            checked_at=closed_at,
        ),
        artifact_names=(evidence_key,),
        planning_only=True,
        requires_production_slot=False,
    )
    refs = (evidence_key, completion_key, *ledger_references)
    return M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=closed_at,
        evidence_refs=refs,
    )


def _replay_result(
    store: ObjectStore,
    *,
    closeout_id: str,
    evidence_key: str,
    evidence_bytes: bytes,
    operation: M13OperationResult,
    operation_key: str,
    head: dict[str, Any],
    snapshot: dict[str, Any],
    record: Any,
    resulting_production: ProductionIdentity,
    ledger_references: tuple[str, ...],
) -> CloseoutResult | None:
    if record.state != "closed":
        return None
    event_key = snapshot["event_keys"][-1]
    event = load_json(store, event_key, "closeout event")
    if event.get("request_id") != closeout_id:
        return None
    if store.head(evidence_key) is None or store.get(evidence_key) != evidence_bytes:
        raise M13CloseoutError(
            "M13_CLOSEOUT_IDENTITY_COLLISION",
            "closeout evidence has divergent bytes",
            closeout_id=closeout_id,
        )
    operation_bytes = json_bytes(operation.to_identity())
    if store.head(operation_key) is None or store.get(operation_key) != operation_bytes:
        raise M13CloseoutError(
            "M13_CLOSEOUT_IDENTITY_COLLISION",
            "closeout operation has divergent bytes",
            operation_id=operation.operation_id,
        )
    return CloseoutResult(
        closeout_id=closeout_id,
        batch_id=record.batch_id,
        operation_id=operation.operation_id,
        registry_version=head["registry_version"],
        batch_version=snapshot["batch_version"],
        state="closed",
        evidence_key=evidence_key,
        operation_key=operation_key,
        event_key=event_key,
        snapshot_key=head["batches"][record.batch_id]["snapshot_key"],
        resulting_production=resulting_production,
        ledger_references=ledger_references,
        evidence_sha256=sha256_bytes(evidence_bytes),
        idempotent=True,
    )


def close_batch(
    store: ObjectStore,
    *,
    batch_id: str,
    actor: str,
    closed_at: str,
    observed_production: ProductionIdentity,
    ledger_references: tuple[str, ...],
    expected_registry_version: int,
    expected_batch_version: int,
) -> CloseoutResult:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise M13CloseoutError(
            "M13_CLOSEOUT_BATCH_INVALID",
            "batch_id is invalid",
        )
    if not actor.strip():
        raise M13CloseoutError(
            "M13_CLOSEOUT_ACTOR_REQUIRED",
            "actor is required",
        )
    ledger_references = _validate_ledger_references(ledger_references)
    actual_production, _ = load_production_identity(store)
    if actual_production != observed_production:
        raise M13CloseoutError(
            "M13_CLOSEOUT_PRODUCTION_STALE",
            "observed production differs from the exact production pointer",
        )

    head, head_etag = registry._load_head(store)
    snapshot, record = registry._load_batch_snapshot(store, head, batch_id)
    lease, _ = load_production_lease(store)
    if lease is None or lease.batch_id != batch_id:
        raise M13CloseoutError(
            "M13_CLOSEOUT_LEASE_MISSING",
            "current production lease does not belong to the batch",
        )
    if lease.state != "released" or lease.completion_key is None:
        raise M13CloseoutError(
            "M13_CLOSEOUT_LEASE_NOT_RELEASED",
            "production lease must be released with completion evidence",
            lease_state=lease.state,
        )
    completion_bytes = store.get(lease.completion_key)
    completion = load_json(store, lease.completion_key, "production completion")
    if completion.get("batch_id") != batch_id:
        raise M13CloseoutError(
            "M13_CLOSEOUT_COMPLETION_INVALID",
            "completion batch identity does not match",
        )
    if completion.get("operation_id") != lease.operation_id:
        raise M13CloseoutError(
            "M13_CLOSEOUT_COMPLETION_INVALID",
            "completion operation identity does not match lease",
        )
    resulting_production = _production_from_value(
        completion.get("resulting_production"),
        "resulting_production",
    )
    expected_previous = _production_from_value(
        completion.get("expected_previous_production"),
        "expected_previous_production",
    )
    if resulting_production != observed_production:
        raise M13CloseoutError(
            "M13_CLOSEOUT_RESULTING_PRODUCTION_MISMATCH",
            "completion result differs from production",
        )
    if expected_previous != record.seed.production:
        raise M13CloseoutError(
            "M13_CLOSEOUT_EXPECTED_PREVIOUS_MISMATCH",
            "completion expected previous differs from batch seed",
        )
    if resulting_production == expected_previous:
        raise M13CloseoutError(
            "M13_CLOSEOUT_PRODUCTION_UNCHANGED",
            "closeout requires a changed production identity",
        )
    if not registry._completed_operation(snapshot, "release_comparison"):
        raise M13CloseoutError(
            "M13_CLOSEOUT_COMPARISON_MISSING",
            "completed release comparison evidence is required",
        )
    _promotion_summary(snapshot, operation_id=lease.operation_id)

    identity = {
        "schema_version": f"{CLOSEOUT_SCHEMA}/identity",
        "batch_id": batch_id,
        "actor": actor,
        "closed_at": closed_at,
        "expected_registry_version": expected_registry_version,
        "expected_batch_version": expected_batch_version,
        "lease_id": lease.lease_id,
        "lease_generation": lease.generation,
        "promotion_operation_id": lease.operation_id,
        "completion_key": lease.completion_key,
        "completion_sha256": sha256_bytes(completion_bytes),
        "expected_previous_production": expected_previous.to_identity(),
        "resulting_production": resulting_production.to_identity(),
        "ledger_references": list(ledger_references),
    }
    closeout_id = _digest(identity, "mclose")
    if not CLOSEOUT_ID_RE.fullmatch(closeout_id):
        raise M13CloseoutError(
            "M13_CLOSEOUT_ID_INVALID",
            "derived closeout identity is invalid",
        )
    evidence_key = f"m13/v2/closeouts/{closeout_id}.json"
    operation = _closeout_operation(
        batch_id=batch_id,
        actor=actor,
        closed_at=closed_at,
        expected_previous=expected_previous,
        evidence_key=evidence_key,
        completion_key=lease.completion_key,
        ledger_references=ledger_references,
    )
    operation_key = (
        f"{registry._batch_prefix(batch_id)}/operations/"
        f"{operation.operation_id}/result.json"
    )
    evidence = {
        **identity,
        "schema_version": f"{CLOSEOUT_SCHEMA}/evidence",
        "closeout_id": closeout_id,
        "closeout_operation_id": operation.operation_id,
        "closeout_operation_key": operation_key,
        "promotion_state_required": "running_or_completed",
        "governance": dict(GOVERNANCE_NO_WRITE),
        "source_write_performed": False,
        "production_write_performed": False,
        "rollback_performed": False,
        "ledger_append_performed": False,
    }
    evidence_bytes = json_bytes(evidence)

    replay = _replay_result(
        store,
        closeout_id=closeout_id,
        evidence_key=evidence_key,
        evidence_bytes=evidence_bytes,
        operation=operation,
        operation_key=operation_key,
        head=head,
        snapshot=snapshot,
        record=record,
        resulting_production=resulting_production,
        ledger_references=ledger_references,
    )
    if replay is not None:
        return replay

    if head["registry_version"] != expected_registry_version:
        raise M13CloseoutError(
            "M13_CLOSEOUT_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )
    if snapshot["batch_version"] != expected_batch_version:
        raise M13CloseoutError(
            "M13_CLOSEOUT_BATCH_VERSION_STALE",
            "expected batch version is stale",
            expected=expected_batch_version,
            observed=snapshot["batch_version"],
        )
    if record.state != "promoting":
        raise M13CloseoutError(
            "M13_CLOSEOUT_STATE_INVALID",
            "batch must be promoting before closeout",
            state=record.state,
        )

    registry_version = head["registry_version"] + 1
    batch_version = snapshot["batch_version"] + 1
    snapshot_key = (
        f"{registry._batch_prefix(batch_id)}/snapshots/"
        f"{batch_version:06d}-closeout-{closeout_id}.json"
    )
    event = registry._event(
        batch_id=batch_id,
        batch_version=batch_version,
        event_type="batch_closed",
        occurred_at=closed_at,
        actor=actor,
        from_state="promoting",
        to_state="closed",
        previous_event_hash=snapshot["current_event_hash"],
        request_id=closeout_id,
        snapshot_key=snapshot_key,
    )
    event_key = (
        f"{registry._batch_prefix(batch_id)}/events/"
        f"{batch_version:06d}-{event['event_sha256']}.json"
    )
    next_record = replace(record, state="closed")
    summaries = [
        summary
        for summary in snapshot["operation_summaries"]
        if summary.get("operation_id")
        not in {lease.operation_id, operation.operation_id}
    ]
    summaries.extend(
        [
            {
                "operation_id": lease.operation_id,
                "kind": "production_promotion",
                "state": "completed",
                "result_at": closed_at,
                "evidence_count": len(completion.get("evidence_refs", [])) + 1,
                "operation_key": lease.completion_key,
            },
            {
                "operation_id": operation.operation_id,
                "kind": "closeout",
                "state": "completed",
                "result_at": closed_at,
                "evidence_count": len(operation.evidence_refs),
                "operation_key": operation_key,
            },
        ]
    )
    next_snapshot = registry._snapshot(
        record=next_record,
        batch_version=batch_version,
        registry_version=registry_version,
        updated_at=closed_at,
        event_keys=[*snapshot["event_keys"], event_key],
        operation_summaries=sorted(
            summaries,
            key=lambda item: item["operation_id"],
        ),
        current_event_hash=event["event_sha256"],
    )

    try:
        states = [
            put_immutable(store, evidence_key, evidence_bytes),
            put_immutable(store, operation_key, json_bytes(operation.to_identity())),
            put_immutable(store, event_key, json_bytes(event)),
            put_immutable(store, snapshot_key, json_bytes(next_snapshot)),
        ]
    except IntegrityError as exc:
        raise M13CloseoutError(
            "M13_CLOSEOUT_IDENTITY_COLLISION",
            "closeout immutable artifact collision",
            closeout_id=closeout_id,
        ) from exc

    batches = dict(head["batches"])
    batches[batch_id] = registry._summary(snapshot_key, next_snapshot)
    next_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": closed_at,
        "batches": batches,
    }
    try:
        registry._write_head(
            store,
            current_etag=head_etag,
            head=next_head,
        )
    except registry.M13RegistryError as exc:
        replay_head, _ = registry._load_head(store)
        replay_snapshot, replay_record = registry._load_batch_snapshot(
            store,
            replay_head,
            batch_id,
        )
        replay_result = _replay_result(
            store,
            closeout_id=closeout_id,
            evidence_key=evidence_key,
            evidence_bytes=evidence_bytes,
            operation=operation,
            operation_key=operation_key,
            head=replay_head,
            snapshot=replay_snapshot,
            record=replay_record,
            resulting_production=resulting_production,
            ledger_references=ledger_references,
        )
        if replay_result is not None:
            return replay_result
        raise M13CloseoutError(
            "M13_CLOSEOUT_REGISTRY_CONFLICT",
            "registry changed during closeout",
        ) from exc

    return CloseoutResult(
        closeout_id=closeout_id,
        batch_id=batch_id,
        operation_id=operation.operation_id,
        registry_version=registry_version,
        batch_version=batch_version,
        state="closed",
        evidence_key=evidence_key,
        operation_key=operation_key,
        event_key=event_key,
        snapshot_key=snapshot_key,
        resulting_production=resulting_production,
        ledger_references=ledger_references,
        evidence_sha256=sha256_bytes(evidence_bytes),
        idempotent=all(states),
    )
