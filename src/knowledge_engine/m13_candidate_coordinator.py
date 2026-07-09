from __future__ import annotations

from typing import Any

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import M13OperationRequest
from .m13_coordination_common import (
    CANDIDATE_HEAD_KEY,
    COORDINATOR_SCHEMA,
    SLOT_ID_RE,
    CandidateSlot,
    M13CoordinatorError,
    cas_write,
    digest,
    load_json,
    parse_utc,
    validate_window,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes


def _empty_head(capacity: int) -> dict[str, Any]:
    return {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-head",
        "head_version": 0,
        "capacity": capacity,
        "updated_at": None,
        "active": {},
    }


def _load_head(
    store: ObjectStore,
    *,
    capacity: int,
) -> tuple[dict[str, Any], str | None]:
    if not 1 <= capacity <= 32:
        raise M13CoordinatorError(
            "M13_CANDIDATE_CAPACITY_INVALID", "capacity must be between 1 and 32"
        )
    metadata = store.head(CANDIDATE_HEAD_KEY)
    if metadata is None:
        return _empty_head(capacity), None
    head = load_json(store, CANDIDATE_HEAD_KEY, "candidate concurrency head")
    if head.get("schema_version") != f"{COORDINATOR_SCHEMA}/candidate-head":
        raise M13CoordinatorError("M13_CANDIDATE_HEAD_INVALID", "head schema is invalid")
    if head.get("capacity") != capacity:
        raise M13CoordinatorError(
            "M13_CANDIDATE_CAPACITY_MISMATCH",
            "capacity differs from initialized head",
            expected=head.get("capacity"),
            observed=capacity,
        )
    if not isinstance(head.get("head_version"), int) or head["head_version"] < 0:
        raise M13CoordinatorError("M13_CANDIDATE_HEAD_INVALID", "head version is invalid")
    if not isinstance(head.get("active"), dict):
        raise M13CoordinatorError("M13_CANDIDATE_HEAD_INVALID", "active slots are invalid")
    return head, metadata.etag


def acquire_candidate_slot(
    store: ObjectStore,
    *,
    request: M13OperationRequest,
    holder_id: str,
    acquired_at: str,
    expires_at: str,
    capacity: int = 2,
) -> CandidateSlot:
    if request.kind != "candidate_build" or not request.planning_only:
        raise M13CoordinatorError(
            "M13_CANDIDATE_REQUEST_INVALID",
            "slot requires a planning-only candidate_build request",
        )
    if request.requires_production_slot:
        raise M13CoordinatorError(
            "M13_CANDIDATE_REQUEST_INVALID", "candidate build cannot require production slot"
        )
    if not holder_id:
        raise M13CoordinatorError("M13_COORD_HOLDER_REQUIRED", "holder_id is required")
    validate_window(acquired_at, expires_at)
    snapshot = registry.get_batch(store, request.batch_id)
    record = registry._record_from_identity(snapshot["record"])
    if record.state != "reviewing_source":
        raise M13CoordinatorError(
            "M13_CANDIDATE_BATCH_STATE_INVALID",
            "candidate admission requires reviewing_source state",
            state=record.state,
        )
    if request.expected_previous_production.production != record.seed.production:
        raise M13CoordinatorError(
            "M13_CANDIDATE_PRODUCTION_IDENTITY_MISMATCH",
            "request production identity differs from batch seed",
        )
    identity = {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-request",
        "operation": request.to_identity(),
        "holder_id": holder_id,
        "acquired_at": acquired_at,
        "expires_at": expires_at,
    }
    slot_id = digest(identity, "mcslot")
    request_sha256 = sha256_bytes(json_bytes(identity))
    head, etag = _load_head(store, capacity=capacity)
    for number, summary in head["active"].items():
        if isinstance(summary, dict) and summary.get("slot_id") == slot_id:
            artifact_key = summary.get("artifact_key")
            if not isinstance(artifact_key, str):
                raise M13CoordinatorError(
                    "M13_CANDIDATE_HEAD_INVALID", "artifact key is invalid"
                )
            artifact = load_json(store, artifact_key, "candidate slot artifact")
            if artifact.get("request_sha256") != request_sha256:
                raise M13CoordinatorError(
                    "M13_CANDIDATE_SLOT_COLLISION", "slot replay diverged"
                )
            return CandidateSlot(
                slot_id=slot_id,
                slot_number=int(number),
                batch_id=request.batch_id,
                operation_id=request.operation_id(),
                holder_id=holder_id,
                acquired_at=acquired_at,
                expires_at=expires_at,
                request_sha256=request_sha256,
                artifact_key=artifact_key,
                head_version=head["head_version"],
                idempotent=True,
            )
    if len(head["active"]) >= capacity:
        raise M13CoordinatorError(
            "M13_CANDIDATE_CAPACITY_EXHAUSTED", "all candidate slots are occupied"
        )
    occupied = {int(number) for number in head["active"]}
    slot_number = next(number for number in range(1, capacity + 1) if number not in occupied)
    artifact_key = f"m13/v2/concurrency/candidate/leases/{slot_id}.json"
    artifact = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-lease",
        "slot_id": slot_id,
        "slot_number": slot_number,
        "batch_id": request.batch_id,
        "operation_id": request.operation_id(),
        "request_sha256": request_sha256,
        "artifact_key": artifact_key,
        "governance": GOVERNANCE_NO_WRITE,
    }
    idempotent = put_immutable(store, artifact_key, json_bytes(artifact))
    new_head = {
        **head,
        "head_version": head["head_version"] + 1,
        "updated_at": acquired_at,
        "active": {
            **head["active"],
            str(slot_number): {
                "slot_id": slot_id,
                "batch_id": request.batch_id,
                "operation_id": request.operation_id(),
                "holder_id": holder_id,
                "expires_at": expires_at,
                "artifact_key": artifact_key,
            },
        },
    }
    cas_write(
        store,
        key=CANDIDATE_HEAD_KEY,
        value=new_head,
        expected_etag=etag,
        conflict_code="M13_CANDIDATE_HEAD_CONFLICT",
    )
    return CandidateSlot(
        slot_id=slot_id,
        slot_number=slot_number,
        batch_id=request.batch_id,
        operation_id=request.operation_id(),
        holder_id=holder_id,
        acquired_at=acquired_at,
        expires_at=expires_at,
        request_sha256=request_sha256,
        artifact_key=artifact_key,
        head_version=new_head["head_version"],
        idempotent=idempotent,
    )


def release_candidate_slot(
    store: ObjectStore,
    *,
    slot_id: str,
    holder_id: str,
    released_at: str,
    reason: str,
    capacity: int = 2,
) -> dict[str, Any]:
    if not SLOT_ID_RE.fullmatch(slot_id):
        raise M13CoordinatorError("M13_CANDIDATE_SLOT_INVALID", "slot_id is invalid")
    if not holder_id or not reason.strip():
        raise M13CoordinatorError(
            "M13_CANDIDATE_RELEASE_INVALID", "holder_id and reason are required"
        )
    parse_utc(released_at, "released_at")
    head, etag = _load_head(store, capacity=capacity)
    match = next(
        (
            (number, summary)
            for number, summary in head["active"].items()
            if isinstance(summary, dict) and summary.get("slot_id") == slot_id
        ),
        None,
    )
    release_key = f"m13/v2/concurrency/candidate/releases/{slot_id}.json"
    if match is None:
        if store.head(release_key) is None:
            raise M13CoordinatorError(
                "M13_CANDIDATE_SLOT_NOT_ACTIVE", "candidate slot is not active"
            )
        release = load_json(store, release_key, "candidate release artifact")
        if release.get("holder_id") != holder_id:
            raise M13CoordinatorError(
                "M13_CANDIDATE_HOLDER_MISMATCH", "release holder differs"
            )
        return {**release, "idempotent": True}
    slot_number, summary = match
    if summary.get("holder_id") != holder_id:
        raise M13CoordinatorError(
            "M13_CANDIDATE_HOLDER_MISMATCH", "candidate slot holder differs"
        )
    release = {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-release",
        "slot_id": slot_id,
        "slot_number": int(slot_number),
        "holder_id": holder_id,
        "batch_id": summary.get("batch_id"),
        "operation_id": summary.get("operation_id"),
        "released_at": released_at,
        "reason": reason,
        "governance": GOVERNANCE_NO_WRITE,
    }
    idempotent = put_immutable(store, release_key, json_bytes(release))
    active = dict(head["active"])
    del active[slot_number]
    new_head = {
        **head,
        "head_version": head["head_version"] + 1,
        "updated_at": released_at,
        "active": active,
    }
    cas_write(
        store,
        key=CANDIDATE_HEAD_KEY,
        value=new_head,
        expected_etag=etag,
        conflict_code="M13_CANDIDATE_HEAD_CONFLICT",
    )
    return {
        **release,
        "head_version": new_head["head_version"],
        "idempotent": idempotent,
    }


def recover_expired_candidate_slots(
    store: ObjectStore,
    *,
    recovered_at: str,
    actor: str,
    capacity: int = 2,
) -> dict[str, Any]:
    now = parse_utc(recovered_at, "recovered_at")
    if not actor:
        raise M13CoordinatorError("M13_COORD_ACTOR_REQUIRED", "actor is required")
    head, etag = _load_head(store, capacity=capacity)
    expired = [
        (number, summary)
        for number, summary in head["active"].items()
        if isinstance(summary, dict)
        and isinstance(summary.get("expires_at"), str)
        and parse_utc(summary["expires_at"], "expires_at") < now
    ]
    if not expired:
        return {
            "schema_version": f"{COORDINATOR_SCHEMA}/candidate-recovery",
            "recovered_at": recovered_at,
            "actor": actor,
            "slot_ids": [],
            "head_version": head["head_version"],
            "idempotent": True,
        }
    identity = {
        "recovered_at": recovered_at,
        "actor": actor,
        "base_head_version": head["head_version"],
        "slot_ids": sorted(str(summary["slot_id"]) for _, summary in expired),
    }
    recovery_id = digest(identity, "mcrecover")
    recovery_key = f"m13/v2/concurrency/candidate/recoveries/{recovery_id}.json"
    artifact = {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-recovery",
        **identity,
        "recovery_id": recovery_id,
        "governance": GOVERNANCE_NO_WRITE,
    }
    idempotent = put_immutable(store, recovery_key, json_bytes(artifact))
    active = dict(head["active"])
    for number, _ in expired:
        del active[number]
    new_head = {
        **head,
        "head_version": head["head_version"] + 1,
        "updated_at": recovered_at,
        "active": active,
    }
    cas_write(
        store,
        key=CANDIDATE_HEAD_KEY,
        value=new_head,
        expected_etag=etag,
        conflict_code="M13_CANDIDATE_HEAD_CONFLICT",
    )
    return {
        **artifact,
        "recovery_key": recovery_key,
        "head_version": new_head["head_version"],
        "idempotent": idempotent,
    }


def candidate_status(store: ObjectStore, *, capacity: int = 2) -> dict[str, Any]:
    head, _ = _load_head(store, capacity=capacity)
    return {
        "head_version": head["head_version"],
        "capacity": head["capacity"],
        "active_count": len(head["active"]),
        "active": head["active"],
    }
