from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from .compiler_contract_v1 import json_bytes, put_immutable
from .errors import IntegrityError, ReleaseConflictError
from .m13_contracts import (
    BATCH_ID_RE,
    TERMINAL_BATCH_STATES,
    BatchState,
    ExpectedPreviousProduction,
    M13BatchRecord,
    M13BatchSeed,
    M13OperationRequest,
    M13OperationResult,
    OperationKind,
    ProductionIdentity,
    assert_expected_previous_production,
    stable_json_bytes,
    validate_batch_transition,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes

REGISTRY_SCHEMA = "knowledge-engine-m13-registry/v1"
REGISTRY_HEAD_KEY = "m13/v1/registry/head.json"


class M13RegistryError(IntegrityError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class RegistryMutationResult:
    batch_id: str
    registry_version: int
    batch_version: int
    state: BatchState
    snapshot_key: str
    event_key: str | None
    idempotent: bool
    operation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LifecyclePlan:
    plan_id: str
    batch_id: str
    batch_version: int
    state: BatchState
    ready: bool
    terminal: bool
    stale_expected_previous: bool
    next_action: str | None
    target_state: BatchState | None
    operation_kind: OperationKind | None
    blockers: tuple[str, ...]
    operation_request: M13OperationRequest | None
    governance: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.operation_request is not None:
            value["operation_request"] = self.operation_request.to_identity()
            value["operation_id"] = self.operation_request.operation_id()
        else:
            value["operation_request"] = None
            value["operation_id"] = None
        return value


def _digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def _batch_prefix(batch_id: str) -> str:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise M13RegistryError("M13_BATCH_ID_INVALID", "batch_id is invalid")
    return f"m13/v1/batches/{batch_id}"


def _load_json(store: ObjectStore, key: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(store.get(key))
    except FileNotFoundError as exc:
        raise M13RegistryError("M13_OBJECT_MISSING", f"{label} is missing", key=key) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M13RegistryError("M13_OBJECT_INVALID", f"{label} is invalid JSON", key=key) from exc
    if not isinstance(value, dict):
        raise M13RegistryError("M13_OBJECT_INVALID", f"{label} must be an object", key=key)
    return value


def _empty_head() -> dict[str, Any]:
    return {
        "schema_version": f"{REGISTRY_SCHEMA}/head",
        "registry_version": 0,
        "updated_at": None,
        "batches": {},
    }


def _load_head(store: ObjectStore) -> tuple[dict[str, Any], str | None]:
    metadata = store.head(REGISTRY_HEAD_KEY)
    if metadata is None:
        return _empty_head(), None
    head = _load_json(store, REGISTRY_HEAD_KEY, "registry head")
    if head.get("schema_version") != f"{REGISTRY_SCHEMA}/head":
        raise M13RegistryError("M13_REGISTRY_SCHEMA_INVALID", "registry head schema is invalid")
    if not isinstance(head.get("registry_version"), int) or head["registry_version"] < 0:
        raise M13RegistryError("M13_REGISTRY_VERSION_INVALID", "registry version is invalid")
    if not isinstance(head.get("batches"), dict):
        raise M13RegistryError("M13_REGISTRY_HEAD_INVALID", "registry batches must be an object")
    return head, metadata.etag


def _write_head(
    store: ObjectStore,
    *,
    current_etag: str | None,
    head: dict[str, Any],
) -> None:
    data = json_bytes(head)
    try:
        store.put(
            REGISTRY_HEAD_KEY,
            data,
            content_type="application/json",
            sha256=sha256_bytes(data),
            expected_etag=current_etag,
            only_if_absent=current_etag is None,
        )
    except ReleaseConflictError as exc:
        raise M13RegistryError(
            "M13_REGISTRY_CONFLICT",
            "registry head compare-and-swap failed",
            expected_etag=current_etag,
        ) from exc


def _production_from(value: Any) -> ProductionIdentity:
    if not isinstance(value, dict):
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "production identity is invalid")
    try:
        return ProductionIdentity(
            release_id=str(value["release_id"]),
            manifest_sha256=str(value["manifest_sha256"]),
            pointer_sha256=str(value["pointer_sha256"]),
        )
    except (KeyError, ValueError) as exc:
        raise M13RegistryError(
            "M13_BATCH_SNAPSHOT_INVALID", "production identity is invalid"
        ) from exc


def _record_from_identity(value: Any) -> M13BatchRecord:
    if not isinstance(value, dict):
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "batch record is invalid")
    seed_value = value.get("seed")
    if not isinstance(seed_value, dict):
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "batch seed is invalid")
    try:
        seed = M13BatchSeed(
            source_repository=str(seed_value["source_repository"]),
            source_commit_sha=str(seed_value["source_commit_sha"]),
            production=_production_from(seed_value["production"]),
            requested_by=str(seed_value["requested_by"]),
            requested_at=str(seed_value["requested_at"]),
            purpose=str(seed_value["purpose"]),
            review_ids=tuple(str(item) for item in seed_value.get("review_ids", [])),
        )
        return M13BatchRecord(
            batch_id=str(value["batch_id"]),
            state=str(value["state"]),  # type: ignore[arg-type]
            seed=seed,
            candidate_channel=(
                str(value["candidate_channel"])
                if value.get("candidate_channel") is not None
                else None
            ),
            supersedes_batch_ids=tuple(
                str(item) for item in value.get("supersedes_batch_ids", [])
            ),
            rebuilt_from_batch_id=(
                str(value["rebuilt_from_batch_id"])
                if value.get("rebuilt_from_batch_id") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "batch record is invalid") from exc


def _event_hash(event: dict[str, Any]) -> str:
    payload = dict(event)
    payload.pop("event_sha256", None)
    return sha256_bytes(stable_json_bytes(payload))


def verify_registry_event(event: dict[str, Any]) -> bool:
    expected = event.get("event_sha256")
    return isinstance(expected, str) and expected == _event_hash(event)


def _event(
    *,
    batch_id: str,
    batch_version: int,
    event_type: str,
    occurred_at: str,
    actor: str,
    from_state: BatchState | None,
    to_state: BatchState,
    previous_event_hash: str | None,
    request_id: str,
    snapshot_key: str,
    operation_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": f"{REGISTRY_SCHEMA}/event",
        "batch_id": batch_id,
        "batch_version": batch_version,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor": actor,
        "from_state": from_state,
        "to_state": to_state,
        "previous_event_hash": previous_event_hash,
        "request_id": request_id,
        "snapshot_key": snapshot_key,
        "operation_id": operation_id,
        "mutations_performed": ["m13_registry_artifact_write"],
        "canonical_source_write_permitted": False,
        "production_write_permitted": False,
        "permanent_ledger_append_permitted": False,
    }
    return {**payload, "event_sha256": _event_hash(payload)}


def _snapshot(
    *,
    record: M13BatchRecord,
    batch_version: int,
    registry_version: int,
    updated_at: str,
    event_keys: list[str],
    operation_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": f"{REGISTRY_SCHEMA}/batch-snapshot",
        "batch_id": record.batch_id,
        "batch_version": batch_version,
        "registry_version": registry_version,
        "updated_at": updated_at,
        "record": record.to_identity(),
        "event_keys": event_keys,
        "operation_ids": operation_ids,
        "current_event_hash": None,
        "governance": GOVERNANCE_NO_WRITE,
    }


def _summary(snapshot_key: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    record = snapshot["record"]
    return {
        "batch_id": snapshot["batch_id"],
        "batch_version": snapshot["batch_version"],
        "state": record["state"],
        "candidate_channel": record["candidate_channel"],
        "source_commit_sha": record["seed"]["source_commit_sha"],
        "expected_previous_production": record["seed"]["production"],
        "snapshot_key": snapshot_key,
        "current_event_hash": snapshot["current_event_hash"],
        "event_count": len(snapshot["event_keys"]),
        "operation_count": len(snapshot["operation_ids"]),
        "terminal": record["terminal"],
        "updated_at": snapshot["updated_at"],
    }


def _validate_snapshot_chain(store: ObjectStore, snapshot: dict[str, Any]) -> None:
    event_keys = snapshot.get("event_keys")
    if not isinstance(event_keys, list) or not event_keys:
        raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event chain is missing")
    previous: str | None = None
    for index, key in enumerate(event_keys, 1):
        if not isinstance(key, str):
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event key is invalid")
        event = _load_json(store, key, "registry event")
        if not verify_registry_event(event):
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event hash is invalid", key=key)
        if event.get("batch_id") != snapshot.get("batch_id"):
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event batch identity mismatch")
        if event.get("batch_version") != index:
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event version is not adjacent")
        if event.get("previous_event_hash") != previous:
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event chain is not adjacent")
        event_hash = event.get("event_sha256")
        if not isinstance(event_hash, str) or not key.endswith(f"-{event_hash}.json"):
            raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "event key/hash mismatch")
        previous = event_hash
    if snapshot.get("current_event_hash") != previous:
        raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "snapshot current event hash mismatch")
    if snapshot.get("batch_version") != len(event_keys):
        raise M13RegistryError("M13_EVENT_CHAIN_INVALID", "snapshot batch version mismatch")


def _load_batch_snapshot(
    store: ObjectStore,
    head: dict[str, Any],
    batch_id: str,
) -> tuple[dict[str, Any], M13BatchRecord]:
    summary = head["batches"].get(batch_id)
    if not isinstance(summary, dict):
        raise M13RegistryError("M13_BATCH_NOT_FOUND", "batch is not registered", batch_id=batch_id)
    snapshot_key = summary.get("snapshot_key")
    if not isinstance(snapshot_key, str):
        raise M13RegistryError("M13_REGISTRY_HEAD_INVALID", "batch snapshot key is invalid")
    snapshot = _load_json(store, snapshot_key, "batch snapshot")
    _validate_snapshot_chain(store, snapshot)
    record = _record_from_identity(snapshot.get("record"))
    if record.batch_id != batch_id:
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "batch identity mismatch")
    if summary != _summary(snapshot_key, snapshot):
        raise M13RegistryError("M13_REGISTRY_HEAD_INVALID", "batch summary does not match snapshot")
    return snapshot, record


def register_batch(
    store: ObjectStore,
    record: M13BatchRecord,
    *,
    actor: str,
    registered_at: str,
) -> RegistryMutationResult:
    if record.state != "planned":
        raise M13RegistryError("M13_REGISTER_STATE_INVALID", "new batch must start as planned")
    if not actor:
        raise M13RegistryError("M13_ACTOR_REQUIRED", "actor is required")
    head, etag = _load_head(store)
    existing = head["batches"].get(record.batch_id)
    if existing is not None:
        snapshot, existing_record = _load_batch_snapshot(store, head, record.batch_id)
        if existing_record.to_identity() != record.to_identity():
            raise M13RegistryError(
                "M13_BATCH_IDENTITY_COLLISION",
                "registered batch has divergent identity",
                batch_id=record.batch_id,
            )
        return RegistryMutationResult(
            batch_id=record.batch_id,
            registry_version=head["registry_version"],
            batch_version=snapshot["batch_version"],
            state=record.state,
            snapshot_key=existing["snapshot_key"],
            event_key=snapshot["event_keys"][-1],
            idempotent=True,
        )

    registry_version = head["registry_version"] + 1
    batch_version = 1
    request_id = _digest(
        {
            "action": "register",
            "record": record.to_identity(),
            "actor": actor,
            "registered_at": registered_at,
        },
        "mregreq",
    )
    prefix = _batch_prefix(record.batch_id)
    provisional = _snapshot(
        record=record,
        batch_version=batch_version,
        registry_version=registry_version,
        updated_at=registered_at,
        event_keys=[],
        operation_ids=[],
    )
    snapshot_digest = sha256_bytes(json_bytes(provisional))
    snapshot_key = f"{prefix}/snapshots/{batch_version:06d}-{snapshot_digest}.json"
    event = _event(
        batch_id=record.batch_id,
        batch_version=batch_version,
        event_type="batch_registered",
        occurred_at=registered_at,
        actor=actor,
        from_state=None,
        to_state=record.state,
        previous_event_hash=None,
        request_id=request_id,
        snapshot_key=snapshot_key,
    )
    event_key = f"{prefix}/events/{batch_version:06d}-{event['event_sha256']}.json"
    snapshot = {
        **provisional,
        "event_keys": [event_key],
        "current_event_hash": event["event_sha256"],
    }
    snapshot_digest = sha256_bytes(json_bytes(snapshot))
    snapshot_key = f"{prefix}/snapshots/{batch_version:06d}-{snapshot_digest}.json"
    event = {**event, "snapshot_key": snapshot_key}
    event["event_sha256"] = _event_hash(event)
    event_key = f"{prefix}/events/{batch_version:06d}-{event['event_sha256']}.json"
    snapshot["event_keys"] = [event_key]
    snapshot["current_event_hash"] = event["event_sha256"]

    states = [
        put_immutable(store, event_key, json_bytes(event)),
        put_immutable(store, snapshot_key, json_bytes(snapshot)),
    ]
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": registered_at,
        "batches": {**head["batches"], record.batch_id: _summary(snapshot_key, snapshot)},
    }
    _write_head(store, current_etag=etag, head=new_head)
    return RegistryMutationResult(
        batch_id=record.batch_id,
        registry_version=registry_version,
        batch_version=batch_version,
        state=record.state,
        snapshot_key=snapshot_key,
        event_key=event_key,
        idempotent=all(states),
    )


def transition_batch(
    store: ObjectStore,
    *,
    batch_id: str,
    target_state: BatchState,
    actor: str,
    occurred_at: str,
    expected_registry_version: int,
    expected_batch_version: int,
    candidate_channel: str | None = None,
) -> RegistryMutationResult:
    head, etag = _load_head(store)
    snapshot, record = _load_batch_snapshot(store, head, batch_id)
    request_identity = {
        "action": "transition",
        "batch_id": batch_id,
        "from_batch_version": expected_batch_version,
        "target_state": target_state,
        "candidate_channel": candidate_channel,
        "actor": actor,
        "occurred_at": occurred_at,
    }
    request_id = _digest(request_identity, "mregreq")
    last_event = _load_json(store, snapshot["event_keys"][-1], "last registry event")
    if (
        snapshot["batch_version"] == expected_batch_version + 1
        and last_event.get("request_id") == request_id
        and record.state == target_state
    ):
        return RegistryMutationResult(
            batch_id=batch_id,
            registry_version=head["registry_version"],
            batch_version=snapshot["batch_version"],
            state=record.state,
            snapshot_key=head["batches"][batch_id]["snapshot_key"],
            event_key=snapshot["event_keys"][-1],
            idempotent=True,
        )
    if head["registry_version"] != expected_registry_version:
        raise M13RegistryError(
            "M13_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )
    if snapshot["batch_version"] != expected_batch_version:
        raise M13RegistryError(
            "M13_BATCH_VERSION_STALE",
            "expected batch version is stale",
            expected=expected_batch_version,
            observed=snapshot["batch_version"],
        )
    try:
        validate_batch_transition(record.state, target_state)
    except ValueError as exc:
        raise M13RegistryError(
            "M13_BATCH_TRANSITION_INVALID",
            "batch transition is invalid",
            current_state=record.state,
            target_state=target_state,
        ) from exc
    if record.state in TERMINAL_BATCH_STATES:
        raise M13RegistryError("M13_BATCH_TERMINAL", "terminal batch cannot transition")
    if candidate_channel is not None and record.candidate_channel not in {None, candidate_channel}:
        raise M13RegistryError(
            "M13_CANDIDATE_CHANNEL_IMMUTABLE",
            "candidate channel cannot be changed",
        )
    next_channel = candidate_channel or record.candidate_channel
    next_record = replace(record, state=target_state, candidate_channel=next_channel)

    registry_version = head["registry_version"] + 1
    batch_version = snapshot["batch_version"] + 1
    prefix = _batch_prefix(batch_id)
    provisional = _snapshot(
        record=next_record,
        batch_version=batch_version,
        registry_version=registry_version,
        updated_at=occurred_at,
        event_keys=list(snapshot["event_keys"]),
        operation_ids=list(snapshot["operation_ids"]),
    )
    provisional_digest = sha256_bytes(json_bytes(provisional))
    snapshot_key = f"{prefix}/snapshots/{batch_version:06d}-{provisional_digest}.json"
    event = _event(
        batch_id=batch_id,
        batch_version=batch_version,
        event_type="batch_transitioned",
        occurred_at=occurred_at,
        actor=actor,
        from_state=record.state,
        to_state=target_state,
        previous_event_hash=snapshot["current_event_hash"],
        request_id=request_id,
        snapshot_key=snapshot_key,
    )
    event_key = f"{prefix}/events/{batch_version:06d}-{event['event_sha256']}.json"
    next_snapshot = {
        **provisional,
        "event_keys": [*snapshot["event_keys"], event_key],
        "current_event_hash": event["event_sha256"],
    }
    final_digest = sha256_bytes(json_bytes(next_snapshot))
    snapshot_key = f"{prefix}/snapshots/{batch_version:06d}-{final_digest}.json"
    event = {**event, "snapshot_key": snapshot_key}
    event["event_sha256"] = _event_hash(event)
    event_key = f"{prefix}/events/{batch_version:06d}-{event['event_sha256']}.json"
    next_snapshot["event_keys"][-1] = event_key
    next_snapshot["current_event_hash"] = event["event_sha256"]

    states = [
        put_immutable(store, event_key, json_bytes(event)),
        put_immutable(store, snapshot_key, json_bytes(next_snapshot)),
    ]
    batches = dict(head["batches"])
    batches[batch_id] = _summary(snapshot_key, next_snapshot)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": occurred_at,
        "batches": batches,
    }
    _write_head(store, current_etag=etag, head=new_head)
    return RegistryMutationResult(
        batch_id=batch_id,
        registry_version=registry_version,
        batch_version=batch_version,
        state=target_state,
        snapshot_key=snapshot_key,
        event_key=event_key,
        idempotent=all(states),
    )


def record_operation_result(
    store: ObjectStore,
    result: M13OperationResult,
    *,
    expected_registry_version: int,
) -> RegistryMutationResult:
    head, etag = _load_head(store)
    snapshot, record = _load_batch_snapshot(store, head, result.request.batch_id)
    if head["registry_version"] != expected_registry_version:
        raise M13RegistryError(
            "M13_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )
    operation_id = result.operation_id
    prefix = _batch_prefix(record.batch_id)
    operation_key = f"{prefix}/operations/{operation_id}/result.json"
    data = json_bytes(result.to_identity())
    existing = store.head(operation_key)
    if operation_id in snapshot["operation_ids"]:
        if existing is None or store.get(operation_key) != data:
            raise M13RegistryError(
                "M13_OPERATION_IDENTITY_COLLISION",
                "recorded operation has divergent identity",
                operation_id=operation_id,
            )
        return RegistryMutationResult(
            batch_id=record.batch_id,
            registry_version=head["registry_version"],
            batch_version=snapshot["batch_version"],
            state=record.state,
            snapshot_key=head["batches"][record.batch_id]["snapshot_key"],
            event_key=None,
            idempotent=True,
            operation_id=operation_id,
        )
    try:
        operation_idempotent = put_immutable(store, operation_key, data)
    except IntegrityError as exc:
        raise M13RegistryError(
            "M13_OPERATION_IDENTITY_COLLISION",
            "operation object already exists with different bytes",
            operation_id=operation_id,
        ) from exc

    registry_version = head["registry_version"] + 1
    next_snapshot = {
        **snapshot,
        "registry_version": registry_version,
        "updated_at": result.result_at,
        "operation_ids": sorted([*snapshot["operation_ids"], operation_id]),
    }
    batch_version = snapshot["batch_version"]
    snapshot_digest = sha256_bytes(json_bytes(next_snapshot))
    snapshot_key = (
        f"{prefix}/snapshots/{batch_version:06d}-ops-{snapshot_digest}.json"
    )
    snapshot_idempotent = put_immutable(store, snapshot_key, json_bytes(next_snapshot))
    batches = dict(head["batches"])
    batches[record.batch_id] = _summary(snapshot_key, next_snapshot)
    new_head = {
        **head,
        "registry_version": registry_version,
        "updated_at": result.result_at,
        "batches": batches,
    }
    _write_head(store, current_etag=etag, head=new_head)
    return RegistryMutationResult(
        batch_id=record.batch_id,
        registry_version=registry_version,
        batch_version=batch_version,
        state=record.state,
        snapshot_key=snapshot_key,
        event_key=None,
        idempotent=operation_idempotent and snapshot_idempotent,
        operation_id=operation_id,
    )


def get_batch(store: ObjectStore, batch_id: str) -> dict[str, Any]:
    head, _ = _load_head(store)
    snapshot, _ = _load_batch_snapshot(store, head, batch_id)
    return snapshot


def list_batches(store: ObjectStore, *, states: set[BatchState] | None = None) -> list[dict[str, Any]]:
    head, _ = _load_head(store)
    summaries = [dict(value) for _, value in sorted(head["batches"].items())]
    if states is not None:
        summaries = [summary for summary in summaries if summary["state"] in states]
    return summaries


def registry_status(store: ObjectStore) -> dict[str, Any]:
    head, _ = _load_head(store)
    counts: dict[str, int] = {}
    for summary in head["batches"].values():
        state = str(summary["state"])
        counts[state] = counts.get(state, 0) + 1
    return {
        "schema_version": f"{REGISTRY_SCHEMA}/status",
        "registry_version": head["registry_version"],
        "batch_count": len(head["batches"]),
        "state_counts": dict(sorted(counts.items())),
        "updated_at": head["updated_at"],
        "governance": GOVERNANCE_NO_WRITE,
    }


def plan_batch_lifecycle(
    *,
    snapshot: dict[str, Any],
    observed_production: ProductionIdentity,
    actor: str,
    planned_at: str,
) -> LifecyclePlan:
    record = _record_from_identity(snapshot.get("record"))
    batch_version = snapshot.get("batch_version")
    if not isinstance(batch_version, int) or batch_version < 1:
        raise M13RegistryError("M13_BATCH_SNAPSHOT_INVALID", "batch version is invalid")
    blockers: list[str] = []
    stale = False
    try:
        assert_expected_previous_production(
            expected=record.seed.production,
            observed=observed_production,
        )
    except ValueError:
        stale = True
        blockers.append("expected_previous_production_stale")

    next_action: str | None = None
    target_state: BatchState | None = None
    operation_kind: OperationKind | None = None
    request: M13OperationRequest | None = None
    terminal = record.state in TERMINAL_BATCH_STATES

    if terminal:
        blockers.append("batch_terminal")
    elif record.state == "planned":
        next_action = "begin_source_review"
        target_state = "reviewing_source"
        operation_kind = "source_review"
    elif record.state == "reviewing_source":
        if not record.seed.review_ids:
            blockers.append("review_evidence_missing")
        next_action = "build_candidate"
        target_state = "candidate_ready"
        operation_kind = "candidate_build"
    elif record.state == "candidate_ready":
        if record.candidate_channel is None:
            blockers.append("candidate_channel_missing")
        next_action = "compare_candidate_release"
        target_state = "awaiting_production_slot"
        operation_kind = "release_comparison"
    elif record.state == "awaiting_production_slot":
        next_action = "acquire_production_slot"
        target_state = "promoting"
        operation_kind = "production_promotion"
        blockers.append("m13_3_coordinator_required")
    elif record.state == "promoting":
        next_action = "await_promotion_result"
        target_state = "closed"
        operation_kind = "closeout"
        blockers.append("production_mutation_in_progress")

    if operation_kind is not None and operation_kind not in {
        "production_promotion",
        "rollback",
    }:
        request = M13OperationRequest(
            kind=operation_kind,
            batch_id=record.batch_id,
            requested_by=actor,
            requested_at=planned_at,
            expected_previous_production=ExpectedPreviousProduction(
                production=record.seed.production,
                checked_at=planned_at,
            ),
            artifact_names=(f"m13/plans/{record.batch_id}/{operation_kind}.json",),
            planning_only=True,
            requires_production_slot=False,
        )
    ready = bool(next_action) and not blockers
    identity = {
        "batch_id": record.batch_id,
        "batch_version": batch_version,
        "state": record.state,
        "observed_production": observed_production.to_identity(),
        "planned_at": planned_at,
        "actor": actor,
        "next_action": next_action,
        "target_state": target_state,
        "operation_kind": operation_kind,
        "blockers": sorted(blockers),
        "operation_id": request.operation_id() if request else None,
    }
    return LifecyclePlan(
        plan_id=_digest(identity, "mplan"),
        batch_id=record.batch_id,
        batch_version=batch_version,
        state=record.state,
        ready=ready,
        terminal=terminal,
        stale_expected_previous=stale,
        next_action=next_action,
        target_state=target_state,
        operation_kind=operation_kind,
        blockers=tuple(sorted(blockers)),
        operation_request=request,
        governance=dict(GOVERNANCE_NO_WRITE),
    )
