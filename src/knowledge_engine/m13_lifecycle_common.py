from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, cast

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import (
    BatchState,
    M13BatchRecord,
    ProductionIdentity,
    assert_expected_previous_production,
    stable_json_bytes,
)
from .m13_coordination_common import load_production_lease
from .storage import ObjectStore

LIFECYCLE_SCHEMA = "knowledge-engine-m13-lifecycle/v2"
AbandonmentReason = Literal[
    "operator_cancelled",
    "failed_review",
    "stale_source",
    "superseded",
    "rebuild_requested",
]
ELIGIBLE_ABANDON_STATES = frozenset(
    {"planned", "reviewing_source", "candidate_ready", "awaiting_production_slot"}
)
REBUILD_SOURCE_STATES = frozenset({"abandoned", "rejected"})


class M13LifecycleError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class LifecycleMutationResult:
    action_id: str
    action: str
    registry_version: int
    batch_ids: tuple[str, ...]
    states: dict[str, str]
    snapshot_keys: dict[str, str]
    event_keys: dict[str, str]
    evidence_key: str
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BatchArtifacts = tuple[dict[str, Any], dict[str, Any], str, str]


def digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def require_utc(value: str, field_name: str) -> None:
    try:
        registry._require_utc(value, field_name)
    except registry.M13RegistryError as exc:
        raise M13LifecycleError(exc.code, exc.message, **exc.context) from exc


def assert_no_active_production_lease(store: ObjectStore) -> None:
    lease, _ = load_production_lease(store)
    if lease is not None and lease.state in {
        "active",
        "permit_issued",
        "commit_authorized",
    }:
        raise M13LifecycleError(
            "M13_LIFECYCLE_PRODUCTION_LEASE_ACTIVE",
            "lifecycle mutation is blocked while production lease is active",
            lease_id=lease.lease_id,
            batch_id=lease.batch_id,
            state=lease.state,
        )


def assert_expected_production(
    record: M13BatchRecord,
    observed_production: ProductionIdentity,
) -> None:
    try:
        assert_expected_previous_production(
            expected=record.seed.production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13LifecycleError(
            "M13_LIFECYCLE_EXPECTED_PREVIOUS_STALE",
            "observed production differs from batch expected previous production",
            batch_id=record.batch_id,
        ) from exc


def last_event(store: ObjectStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    return registry._load_json(store, snapshot["event_keys"][-1], "last registry event")


def candidate_channel_owner(
    store: ObjectStore,
    head: dict[str, Any],
    candidate_channel: str,
) -> str | None:
    for batch_id in sorted(head["batches"]):
        _, record = registry._load_batch_snapshot(store, head, batch_id)
        if record.candidate_channel == candidate_channel:
            return batch_id
    return None


def assert_candidate_channel_available(
    store: ObjectStore,
    head: dict[str, Any],
    record: M13BatchRecord,
) -> None:
    if record.candidate_channel is None:
        return
    owner = candidate_channel_owner(store, head, record.candidate_channel)
    if owner is not None:
        raise M13LifecycleError(
            "M13_LIFECYCLE_CANDIDATE_CHANNEL_REUSED",
            "candidate channel is already registered",
            candidate_channel=record.candidate_channel,
            owner_batch_id=owner,
        )


def supersession_closure(
    store: ObjectStore,
    head: dict[str, Any],
    start_batch_ids: tuple[str, ...],
) -> frozenset[str]:
    seen: set[str] = set()
    pending = list(start_batch_ids)
    while pending:
        batch_id = pending.pop()
        if batch_id in seen:
            continue
        seen.add(batch_id)
        if head["batches"].get(batch_id) is None:
            continue
        _, record = registry._load_batch_snapshot(store, head, batch_id)
        pending.extend(record.supersedes_batch_ids)
        if record.rebuilt_from_batch_id is not None:
            pending.append(record.rebuilt_from_batch_id)
    return frozenset(seen)


def ensure_head_version(head: dict[str, Any], expected_registry_version: int) -> None:
    if head["registry_version"] != expected_registry_version:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )


def ensure_batch_version(
    snapshot: dict[str, Any],
    expected_batch_version: int,
    batch_id: str,
) -> None:
    if snapshot["batch_version"] != expected_batch_version:
        raise M13LifecycleError(
            "M13_LIFECYCLE_BATCH_VERSION_STALE",
            "expected batch version is stale",
            batch_id=batch_id,
            expected=expected_batch_version,
            observed=snapshot["batch_version"],
        )


def write_head(
    store: ObjectStore,
    *,
    etag: str | None,
    head: dict[str, Any],
) -> None:
    try:
        registry._write_head(store, current_etag=etag, head=head)
    except registry.M13RegistryError as exc:
        if exc.code == "M13_REGISTRY_CONFLICT":
            raise M13LifecycleError(
                "M13_LIFECYCLE_REGISTRY_CONFLICT",
                "registry changed during lifecycle mutation",
            ) from exc
        raise M13LifecycleError(exc.code, exc.message, **exc.context) from exc


def batch_update(
    *,
    record: M13BatchRecord,
    snapshot: dict[str, Any],
    registry_version: int,
    action_id: str,
    actor: str,
    occurred_at: str,
    target_state: BatchState,
    event_type: str,
) -> BatchArtifacts:
    next_record = replace(record, state=target_state)
    batch_version = snapshot["batch_version"] + 1
    prefix = registry._batch_prefix(record.batch_id)
    snapshot_key = f"{prefix}/snapshots/{batch_version:06d}-{action_id}.json"
    event = registry._event(
        batch_id=record.batch_id,
        batch_version=batch_version,
        event_type=event_type,
        occurred_at=occurred_at,
        actor=actor,
        from_state=record.state,
        to_state=next_record.state,
        previous_event_hash=snapshot["current_event_hash"],
        request_id=action_id,
        snapshot_key=snapshot_key,
    )
    event_key = f"{prefix}/events/{batch_version:06d}-{event['event_sha256']}.json"
    next_snapshot = registry._snapshot(
        record=next_record,
        batch_version=batch_version,
        registry_version=registry_version,
        updated_at=occurred_at,
        event_keys=[*snapshot["event_keys"], event_key],
        operation_summaries=list(snapshot["operation_summaries"]),
        current_event_hash=event["event_sha256"],
    )
    return event, next_snapshot, event_key, snapshot_key


def batch_registration(
    *,
    record: M13BatchRecord,
    registry_version: int,
    action_id: str,
    actor: str,
    occurred_at: str,
    event_type: str,
) -> BatchArtifacts:
    prefix = registry._batch_prefix(record.batch_id)
    snapshot_key = f"{prefix}/snapshots/000001-{action_id}.json"
    event = registry._event(
        batch_id=record.batch_id,
        batch_version=1,
        event_type=event_type,
        occurred_at=occurred_at,
        actor=actor,
        from_state=None,
        to_state=record.state,
        previous_event_hash=None,
        request_id=action_id,
        snapshot_key=snapshot_key,
    )
    event_key = f"{prefix}/events/000001-{event['event_sha256']}.json"
    snapshot = registry._snapshot(
        record=record,
        batch_version=1,
        registry_version=registry_version,
        updated_at=occurred_at,
        event_keys=[event_key],
        operation_summaries=[],
        current_event_hash=event["event_sha256"],
    )
    return event, snapshot, event_key, snapshot_key


def write_artifacts(
    store: ObjectStore,
    *,
    evidence_key: str,
    evidence: dict[str, Any],
    batch_artifacts: tuple[BatchArtifacts, ...],
) -> bool:
    states = [put_immutable(store, evidence_key, json_bytes(evidence))]
    for event, snapshot, event_key, snapshot_key in batch_artifacts:
        states.append(put_immutable(store, event_key, json_bytes(event)))
        states.append(put_immutable(store, snapshot_key, json_bytes(snapshot)))
    return all(states)


def mutation_result(
    *,
    action_id: str,
    action: str,
    registry_version: int,
    records: tuple[M13BatchRecord, ...],
    snapshot_keys: dict[str, str],
    event_keys: dict[str, str],
    evidence_key: str,
    idempotent: bool,
) -> LifecycleMutationResult:
    return LifecycleMutationResult(
        action_id=action_id,
        action=action,
        registry_version=registry_version,
        batch_ids=tuple(sorted(record.batch_id for record in records)),
        states={record.batch_id: cast(str, record.state) for record in records},
        snapshot_keys=snapshot_keys,
        event_keys=event_keys,
        evidence_key=evidence_key,
        idempotent=idempotent,
    )
