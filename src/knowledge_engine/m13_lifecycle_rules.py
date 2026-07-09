from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .errors import ReleaseConflictError
from .m13_contracts import (
    BATCH_ID_RE,
    TERMINAL_BATCH_STATES,
    M13BatchRecord,
    ProductionIdentity,
    assert_expected_previous_production,
    stable_json_bytes,
)
from .m13_coordination_common import load_production_lease
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore

LIFECYCLE_SCHEMA = "knowledge-engine-m13-lifecycle/v1"
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


def _digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def _require_utc(value: str, field_name: str) -> None:
    try:
        registry._require_utc(value, field_name)
    except registry.M13RegistryError as exc:
        raise M13LifecycleError(exc.code, exc.message, **exc.context) from exc


def _assert_no_active_production_lease(store: ObjectStore) -> None:
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


def _assert_expected_production(
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


def _last_event(store: ObjectStore, snapshot: dict[str, Any]) -> dict[str, Any]:
    return registry._load_json(store, snapshot["event_keys"][-1], "last registry event")


def _candidate_channel_owner(
    store: ObjectStore,
    head: dict[str, Any],
    candidate_channel: str,
    *,
    exclude_batch_ids: frozenset[str] = frozenset(),
) -> str | None:
    for batch_id in sorted(head["batches"]):
        if batch_id in exclude_batch_ids:
            continue
        _, record = registry._load_batch_snapshot(store, head, batch_id)
        if record.candidate_channel == candidate_channel:
            return batch_id
    return None


def _assert_candidate_channel_available(
    store: ObjectStore,
    head: dict[str, Any],
    record: M13BatchRecord,
) -> None:
    if record.candidate_channel is None:
        return
    owner = _candidate_channel_owner(store, head, record.candidate_channel)
    if owner is not None:
        raise M13LifecycleError(
            "M13_LIFECYCLE_CANDIDATE_CHANNEL_REUSED",
            "candidate channel is already registered",
            candidate_channel=record.candidate_channel,
            owner_batch_id=owner,
        )


def _supersession_closure(
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
        summary = head["batches"].get(batch_id)
        if summary is None:
            continue
        _, record = registry._load_batch_snapshot(store, head, batch_id)
        pending.extend(record.supersedes_batch_ids)
        if record.rebuilt_from_batch_id is not None:
            pending.append(record.rebuilt_from_batch_id)
    return frozenset(seen)


def _ensure_head_version(head: dict[str, Any], expected_registry_version: int) -> None:
    if head["registry_version"] != expected_registry_version:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )


def _ensure_batch_version(
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


def _write_head(
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


def _batch_update(
    *,
    record: M13BatchRecord,
    snapshot: dict[str, Any],
    registry_version: int,
    action_id: str,
    actor: str,
    occurred_at: str,
    target_state: str,
    event_type: str,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
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


def _batch_registration(
    *,
    record: M13BatchRecord,
    registry_version: int,
    action_id: str,
    actor: str,
    occurred_at: str,
    event_type: str,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
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


def _write_artifacts(
    store: ObjectStore,
    *,
    evidence_key: str,
    evidence: dict[str, Any],
    batch_artifacts: tuple[tuple[dict[str, Any], dict[str, Any], str, str], ...],
) -> bool:
    states = [put_immutable(store, evidence_key, json_bytes(evidence))]
    for event, snapshot, event_key, snapshot_key in batch_artifacts:
        states.append(put_immutable(store, event_key, json_bytes(event)))
        states.append(put_immutable(store, snapshot_key, json_bytes(snapshot)))
    return all(states)


def _result(
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
        states={record.batch_id: record.state for record in records},
        snapshot_keys=snapshot_keys,
        event_keys=event_keys,
        evidence_key=evidence_key,
        idempotent=idempotent,
    )


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
    _require_utc(occurred_at, "occurred_at")
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
    action_id = _digest(identity, "mlife")
    last_event = _last_event(store, snapshot)
    evidence_key = f"m13/v1/lifecycle/abandonments/{action_id}.json"
    if record.state == "abandoned" and last_event.get("request_id") == action_id:
        return _result(
            action_id=action_id,
            action="abandon",
            registry_version=head["registry_version"],
            records=(record,),
            snapshot_keys={batch_id: head["batches"][batch_id]["snapshot_key"]},
            event_keys={batch_id: snapshot["event_keys"][-1]},
            evidence_key=evidence_key,
            idempotent=True,
        )
    _ensure_head_version(head, expected_registry_version)
    _ensure_batch_version(snapshot, expected_batch_version, batch_id)
    _assert_no_active_production_lease(store)
    _assert_expected_production(record, observed_production)
    if record.state not in ELIGIBLE_ABANDON_STATES:
        raise M13LifecycleError(
            "M13_LIFECYCLE_ABANDON_STATE_INVALID",
            "batch state cannot be abandoned",
            batch_id=batch_id,
            state=record.state,
        )
    registry_version = head["registry_version"] + 1
    event, next_snapshot, event_key, snapshot_key = _batch_update(
        record=record,
        snapshot=snapshot,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        target_state="abandoned",
        event_type="batch_abandoned",
    )
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
    idempotent = _write_artifacts(
        store,
        evidence_key=evidence_key,
        evidence=evidence,
        batch_artifacts=((event, next_snapshot, event_key, snapshot_key),),
    )
    batches = dict(head["batches"])
    batches[batch_id] = registry._summary(snapshot_key, next_snapshot)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": occurred_at,
        "batches": batches,
    }
    _write_head(store, etag=etag, head=new_head)
    return _result(
        action_id=action_id,
        action="abandon",
        registry_version=registry_version,
        records=(next_record,),
        snapshot_keys={batch_id: snapshot_key},
        event_keys={batch_id: event_key},
        evidence_key=evidence_key,
        idempotent=idempotent,
    )


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
            "M13_LIFECYCLE_SUPERSESSION_INVALID", "actor and rationale are required"
        )
    _require_utc(occurred_at, "occurred_at")
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
    action_id = _digest(identity, "mlife")
    evidence_key = f"m13/v1/lifecycle/supersessions/{action_id}.json"
    existing_new = head["batches"].get(new_record.batch_id)
    if existing_new is not None:
        new_snapshot, existing_record = registry._load_batch_snapshot(
            store, head, new_record.batch_id
        )
        target_replays = all(
            pair[1].state == "abandoned"
            and _last_event(store, pair[0]).get("request_id") == action_id
            for pair in target_pairs.values()
        )
        if (
            existing_record.to_identity() == new_record.to_identity()
            and _last_event(store, new_snapshot).get("request_id") == action_id
            and target_replays
        ):
            records = (existing_record, *(pair[1] for pair in target_pairs.values()))
            return _result(
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
    _ensure_head_version(head, expected_registry_version)
    _assert_no_active_production_lease(store)
    _assert_expected_production(new_record, observed_production)
    _assert_candidate_channel_available(store, head, new_record)
    if new_record.batch_id in target_ids:
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_CYCLE", "batch cannot supersede itself"
        )
    closure = _supersession_closure(store, head, target_ids)
    if new_record.batch_id in closure:
        raise M13LifecycleError(
            "M13_LIFECYCLE_SUPERSESSION_CYCLE",
            "supersession graph would contain a cycle",
        )
    target_records: list[M13BatchRecord] = []
    for batch_id in target_ids:
        snapshot, record = target_pairs[batch_id]
        _ensure_batch_version(snapshot, expected_batch_versions[batch_id], batch_id)
        _assert_expected_production(record, observed_production)
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
    new_artifact = _batch_registration(
        record=new_record,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        event_type="batch_registered_superseding",
    )
    target_artifacts = tuple(
        _batch_update(
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
    idempotent = _write_artifacts(
        store,
        evidence_key=evidence_key,
        evidence=evidence,
        batch_artifacts=all_artifacts,
    )
    batches = dict(head["batches"])
    event_keys: dict[str, str] = {}
    snapshot_keys: dict[str, str] = {}
    resulting_records: list[M13BatchRecord] = []
    for event, snapshot, event_key, snapshot_key in all_artifacts:
        record = registry._record_from_identity(snapshot["record"])
        batches[record.batch_id] = registry._summary(snapshot_key, snapshot)
        event_keys[record.batch_id] = event_key
        snapshot_keys[record.batch_id] = snapshot_key
        resulting_records.append(record)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": occurred_at,
        "batches": batches,
    }
    _write_head(store, etag=etag, head=new_head)
    return _result(
        action_id=action_id,
        action="supersede",
        registry_version=registry_version,
        records=tuple(resulting_records),
        snapshot_keys=snapshot_keys,
        event_keys=event_keys,
        evidence_key=evidence_key,
        idempotent=idempotent,
    )


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
            "M13_LIFECYCLE_REBUILD_INVALID", "actor and rationale are required"
        )
    _require_utc(occurred_at, "occurred_at")
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
    action_id = _digest(identity, "mlife")
    evidence_key = f"m13/v1/lifecycle/rebuilds/{action_id}.json"
    existing = head["batches"].get(new_record.batch_id)
    if existing is not None:
        snapshot, record = registry._load_batch_snapshot(store, head, new_record.batch_id)
        if (
            record.to_identity() == new_record.to_identity()
            and _last_event(store, snapshot).get("request_id") == action_id
        ):
            return _result(
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
    _ensure_head_version(head, expected_registry_version)
    _ensure_batch_version(
        ancestor_snapshot,
        expected_ancestor_batch_version,
        ancestor_id,
    )
    _assert_no_active_production_lease(store)
    _assert_expected_production(ancestor, observed_production)
    _assert_expected_production(new_record, observed_production)
    _assert_candidate_channel_available(store, head, new_record)
    if ancestor.state not in REBUILD_SOURCE_STATES:
        raise M13LifecycleError(
            "M13_LIFECYCLE_REBUILD_ANCESTOR_STATE_INVALID",
            "rebuild ancestor must be abandoned or rejected",
            state=ancestor.state,
        )
    if ancestor.candidate_channel is None or not registry._completed_operation(
        ancestor_snapshot, "candidate_build"
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
    event, snapshot, event_key, snapshot_key = _batch_registration(
        record=new_record,
        registry_version=registry_version,
        action_id=action_id,
        actor=actor,
        occurred_at=occurred_at,
        event_type="batch_registered_rebuild",
    )
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
    idempotent = _write_artifacts(
        store,
        evidence_key=evidence_key,
        evidence=evidence,
        batch_artifacts=((event, snapshot, event_key, snapshot_key),),
    )
    batches = dict(head["batches"])
    batches[new_record.batch_id] = registry._summary(snapshot_key, snapshot)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": occurred_at,
        "batches": batches,
    }
    _write_head(store, etag=etag, head=new_head)
    return _result(
        action_id=action_id,
        action="rebuild",
        registry_version=registry_version,
        records=(new_record,),
        snapshot_keys={new_record.batch_id: snapshot_key},
        event_keys={new_record.batch_id: event_key},
        evidence_key=evidence_key,
        idempotent=idempotent,
    )


def assert_no_physical_deletion_surface() -> None:
    if hasattr(ObjectStore, "delete"):
        return
    raise ReleaseConflictError("object store protocol is missing expected delete method")
