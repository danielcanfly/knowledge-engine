from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .errors import IntegrityError, ReleaseConflictError
from .m13_contracts import (
    OPERATION_ID_RE,
    M13OperationRequest,
    ProductionIdentity,
    assert_expected_previous_production,
    stable_json_bytes,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes

COORDINATOR_SCHEMA = "knowledge-engine-m13-coordinator/v1"
CANDIDATE_HEAD_KEY = "m13/v1/concurrency/candidate/head.json"
PRODUCTION_LEASE_KEY = "m13/v1/concurrency/production/lease.json"
LEASE_ID_RE = re.compile(r"^mlease_[a-f0-9]{32}$")
SLOT_ID_RE = re.compile(r"^mcslot_[a-f0-9]{32}$")
PERMIT_ID_RE = re.compile(r"^mpermit_[a-f0-9]{32}$")
AUTHORIZATION_ID_RE = re.compile(r"^mauth_[a-f0-9]{32}$")

ProductionLeaseState = Literal[
    "active",
    "permit_issued",
    "commit_authorized",
    "released",
    "recovered",
]


class M13CoordinatorError(IntegrityError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class CandidateSlot:
    slot_id: str
    slot_number: int
    batch_id: str
    operation_id: str
    holder_id: str
    acquired_at: str
    expires_at: str
    request_sha256: str
    artifact_key: str
    head_version: int
    idempotent: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductionLease:
    lease_id: str
    generation: int
    fencing_token: str
    state: ProductionLeaseState
    batch_id: str
    operation_id: str
    holder_id: str
    candidate_channel: str
    expected_registry_version: int
    expected_batch_version: int
    expected_previous_production: ProductionIdentity
    acquired_at: str
    expires_at: str
    acquisition_key: str
    permit_id: str | None = None
    permit_key: str | None = None
    authorization_id: str | None = None
    authorization_key: str | None = None
    completion_key: str | None = None
    release_key: str | None = None
    recovery_key: str | None = None
    renewed_at: str | None = None
    updated_at: str | None = None
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["expected_previous_production"] = self.expected_previous_production.to_identity()
        return value


@dataclass(frozen=True)
class ProductionMutationPermit:
    permit_id: str
    lease_id: str
    generation: int
    fencing_token: str
    batch_id: str
    operation_id: str
    holder_id: str
    expected_registry_version: int
    expected_batch_version: int
    expected_previous_production: ProductionIdentity
    issued_at: str
    expires_at: str
    permit_key: str
    idempotent: bool

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["expected_previous_production"] = self.expected_previous_production.to_identity()
        return value


@dataclass(frozen=True)
class CommitAuthorization:
    authorization_id: str
    permit_id: str
    lease_id: str
    generation: int
    fencing_token: str
    batch_id: str
    operation_id: str
    holder_id: str
    expected_previous_production: ProductionIdentity
    authorized_at: str
    expires_at: str
    authorization_key: str
    idempotent: bool

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["expected_previous_production"] = self.expected_previous_production.to_identity()
        return value


def _digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def _parse_utc(value: str, field_name: str) -> datetime:
    if not value.endswith("Z"):
        raise M13CoordinatorError("M13_COORD_TIME_INVALID", f"{field_name} must end with Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_COORD_TIME_INVALID", f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise M13CoordinatorError("M13_COORD_TIME_INVALID", f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_window(start: str, end: str) -> None:
    if _parse_utc(end, "expires_at") <= _parse_utc(start, "acquired_at"):
        raise M13CoordinatorError(
            "M13_COORD_WINDOW_INVALID", "expires_at must be after acquired_at"
        )


def _load_json(store: ObjectStore, key: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(store.get(key))
    except FileNotFoundError as exc:
        raise M13CoordinatorError("M13_COORD_OBJECT_MISSING", f"{label} is missing", key=key) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M13CoordinatorError(
            "M13_COORD_OBJECT_INVALID", f"{label} is invalid JSON", key=key
        ) from exc
    if not isinstance(value, dict):
        raise M13CoordinatorError("M13_COORD_OBJECT_INVALID", f"{label} must be an object")
    return value


def _cas_write(
    store: ObjectStore,
    *,
    key: str,
    value: dict[str, Any],
    expected_etag: str | None,
    conflict_code: str,
) -> None:
    data = json_bytes(value)
    try:
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=sha256_bytes(data),
            expected_etag=expected_etag,
            only_if_absent=expected_etag is None,
        )
    except ReleaseConflictError as exc:
        raise M13CoordinatorError(
            conflict_code,
            "compare-and-swap failed",
            key=key,
            expected_etag=expected_etag,
        ) from exc


def _empty_candidate_head(capacity: int) -> dict[str, Any]:
    return {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-head",
        "head_version": 0,
        "capacity": capacity,
        "updated_at": None,
        "active": {},
    }


def _load_candidate_head(
    store: ObjectStore,
    *,
    capacity: int,
) -> tuple[dict[str, Any], str | None]:
    if not 1 <= capacity <= 32:
        raise M13CoordinatorError(
            "M13_CANDIDATE_CAPACITY_INVALID", "candidate capacity must be between 1 and 32"
        )
    metadata = store.head(CANDIDATE_HEAD_KEY)
    if metadata is None:
        return _empty_candidate_head(capacity), None
    head = _load_json(store, CANDIDATE_HEAD_KEY, "candidate concurrency head")
    if head.get("schema_version") != f"{COORDINATOR_SCHEMA}/candidate-head":
        raise M13CoordinatorError(
            "M13_CANDIDATE_HEAD_INVALID", "candidate head schema is invalid"
        )
    if head.get("capacity") != capacity:
        raise M13CoordinatorError(
            "M13_CANDIDATE_CAPACITY_MISMATCH",
            "candidate capacity differs from initialized head",
            expected=head.get("capacity"),
            observed=capacity,
        )
    if not isinstance(head.get("head_version"), int) or head["head_version"] < 0:
        raise M13CoordinatorError(
            "M13_CANDIDATE_HEAD_INVALID", "candidate head version is invalid"
        )
    if not isinstance(head.get("active"), dict):
        raise M13CoordinatorError(
            "M13_CANDIDATE_HEAD_INVALID", "candidate active slots must be an object"
        )
    return head, metadata.etag


def _candidate_request_identity(
    *,
    request: M13OperationRequest,
    holder_id: str,
    acquired_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-request",
        "operation": request.to_identity(),
        "holder_id": holder_id,
        "acquired_at": acquired_at,
        "expires_at": expires_at,
    }


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
            "candidate slot requires a planning-only candidate_build request",
        )
    if request.requires_production_slot:
        raise M13CoordinatorError(
            "M13_CANDIDATE_REQUEST_INVALID", "candidate build cannot require production slot"
        )
    if not holder_id:
        raise M13CoordinatorError("M13_COORD_HOLDER_REQUIRED", "holder_id is required")
    _validate_window(acquired_at, expires_at)
    snapshot = registry.get_batch(store, request.batch_id)
    record = registry._record_from_identity(snapshot["record"])
    if record.state != "reviewing_source":
        raise M13CoordinatorError(
            "M13_CANDIDATE_BATCH_STATE_INVALID",
            "candidate build admission requires reviewing_source state",
            state=record.state,
        )
    if request.expected_previous_production.production != record.seed.production:
        raise M13CoordinatorError(
            "M13_CANDIDATE_PRODUCTION_IDENTITY_MISMATCH",
            "candidate request expected previous production differs from batch seed",
        )

    head, etag = _load_candidate_head(store, capacity=capacity)
    identity = _candidate_request_identity(
        request=request,
        holder_id=holder_id,
        acquired_at=acquired_at,
        expires_at=expires_at,
    )
    request_sha256 = sha256_bytes(stable_json_bytes(identity))
    slot_id = _digest(identity, "mcslot")
    for slot_number, summary in head["active"].items():
        if isinstance(summary, dict) and summary.get("slot_id") == slot_id:
            artifact_key = summary.get("artifact_key")
            if not isinstance(artifact_key, str):
                raise M13CoordinatorError(
                    "M13_CANDIDATE_HEAD_INVALID", "candidate artifact key is invalid"
                )
            artifact = _load_json(store, artifact_key, "candidate slot artifact")
            if artifact.get("request_sha256") != request_sha256:
                raise M13CoordinatorError(
                    "M13_CANDIDATE_SLOT_COLLISION", "candidate slot replay diverged"
                )
            return CandidateSlot(
                slot_id=slot_id,
                slot_number=int(slot_number),
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
            "M13_CANDIDATE_CAPACITY_EXHAUSTED",
            "all candidate build slots are occupied",
            capacity=capacity,
        )
    occupied = {int(value) for value in head["active"]}
    slot_number = next(number for number in range(1, capacity + 1) if number not in occupied)
    artifact_key = f"m13/v1/concurrency/candidate/leases/{slot_id}.json"
    artifact = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-lease",
        "slot_id": slot_id,
        "slot_number": slot_number,
        "operation_id": request.operation_id(),
        "batch_id": request.batch_id,
        "request_sha256": request_sha256,
        "artifact_key": artifact_key,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, artifact_key, json_bytes(artifact))
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
    _cas_write(
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
        idempotent=artifact_idempotent,
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
    _parse_utc(released_at, "released_at")
    head, etag = _load_candidate_head(store, capacity=capacity)
    match = next(
        (
            (number, summary)
            for number, summary in head["active"].items()
            if isinstance(summary, dict) and summary.get("slot_id") == slot_id
        ),
        None,
    )
    release_key = f"m13/v1/concurrency/candidate/releases/{slot_id}.json"
    if match is None:
        if store.head(release_key) is not None:
            release = _load_json(store, release_key, "candidate release artifact")
            if release.get("holder_id") != holder_id:
                raise M13CoordinatorError(
                    "M13_CANDIDATE_HOLDER_MISMATCH", "candidate release holder differs"
                )
            return {**release, "idempotent": True}
        raise M13CoordinatorError("M13_CANDIDATE_SLOT_NOT_ACTIVE", "candidate slot is not active")
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
    artifact_idempotent = put_immutable(store, release_key, json_bytes(release))
    active = dict(head["active"])
    del active[slot_number]
    new_head = {
        **head,
        "head_version": head["head_version"] + 1,
        "updated_at": released_at,
        "active": active,
    }
    _cas_write(
        store,
        key=CANDIDATE_HEAD_KEY,
        value=new_head,
        expected_etag=etag,
        conflict_code="M13_CANDIDATE_HEAD_CONFLICT",
    )
    return {**release, "head_version": new_head["head_version"], "idempotent": artifact_idempotent}


def recover_expired_candidate_slots(
    store: ObjectStore,
    *,
    recovered_at: str,
    actor: str,
    capacity: int = 2,
) -> dict[str, Any]:
    now = _parse_utc(recovered_at, "recovered_at")
    if not actor:
        raise M13CoordinatorError("M13_COORD_ACTOR_REQUIRED", "actor is required")
    head, etag = _load_candidate_head(store, capacity=capacity)
    expired = [
        (number, summary)
        for number, summary in head["active"].items()
        if isinstance(summary, dict)
        and isinstance(summary.get("expires_at"), str)
        and _parse_utc(summary["expires_at"], "expires_at") < now
    ]
    if not expired:
        return {
            "schema_version": f"{COORDINATOR_SCHEMA}/candidate-recovery",
            "recovered_at": recovered_at,
            "actor": actor,
            "recovered_slot_ids": [],
            "head_version": head["head_version"],
            "idempotent": True,
        }
    identity = {
        "recovered_at": recovered_at,
        "actor": actor,
        "base_head_version": head["head_version"],
        "slot_ids": sorted(str(summary["slot_id"]) for _, summary in expired),
    }
    recovery_id = _digest(identity, "mcrecover")
    recovery_key = f"m13/v1/concurrency/candidate/recoveries/{recovery_id}.json"
    artifact = {
        "schema_version": f"{COORDINATOR_SCHEMA}/candidate-recovery",
        **identity,
        "recovery_id": recovery_id,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, recovery_key, json_bytes(artifact))
    active = dict(head["active"])
    for number, _ in expired:
        del active[number]
    new_head = {
        **head,
        "head_version": head["head_version"] + 1,
        "updated_at": recovered_at,
        "active": active,
    }
    _cas_write(
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
        "idempotent": artifact_idempotent,
    }


def _production_from_value(value: Any) -> ProductionIdentity:
    if not isinstance(value, dict):
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_INVALID", "expected previous production is invalid"
        )
    try:
        return ProductionIdentity(
            release_id=str(value["release_id"]),
            manifest_sha256=str(value["manifest_sha256"]),
            pointer_sha256=str(value["pointer_sha256"]),
        )
    except (KeyError, ValueError) as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_INVALID", "expected previous production is invalid"
        ) from exc


def _lease_from_value(value: dict[str, Any], *, idempotent: bool = False) -> ProductionLease:
    state = value.get("state")
    if state not in {"active", "permit_issued", "commit_authorized", "released", "recovered"}:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "lease state is invalid")
    try:
        lease = ProductionLease(
            lease_id=str(value["lease_id"]),
            generation=int(value["generation"]),
            fencing_token=str(value["fencing_token"]),
            state=state,
            batch_id=str(value["batch_id"]),
            operation_id=str(value["operation_id"]),
            holder_id=str(value["holder_id"]),
            candidate_channel=str(value["candidate_channel"]),
            expected_registry_version=int(value["expected_registry_version"]),
            expected_batch_version=int(value["expected_batch_version"]),
            expected_previous_production=_production_from_value(
                value["expected_previous_production"]
            ),
            acquired_at=str(value["acquired_at"]),
            expires_at=str(value["expires_at"]),
            acquisition_key=str(value["acquisition_key"]),
            permit_id=value.get("permit_id"),
            permit_key=value.get("permit_key"),
            authorization_id=value.get("authorization_id"),
            authorization_key=value.get("authorization_key"),
            completion_key=value.get("completion_key"),
            release_key=value.get("release_key"),
            recovery_key=value.get("recovery_key"),
            renewed_at=value.get("renewed_at"),
            updated_at=value.get("updated_at"),
            idempotent=idempotent,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_INVALID", "lease object is invalid"
        ) from exc
    if not LEASE_ID_RE.fullmatch(lease.lease_id):
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "lease_id is invalid")
    if not OPERATION_ID_RE.fullmatch(lease.operation_id):
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "operation_id is invalid")
    if lease.generation < 1:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "generation is invalid")
    _validate_window(lease.acquired_at, lease.expires_at)
    return lease


def _load_production_lease(
    store: ObjectStore,
) -> tuple[ProductionLease | None, str | None, dict[str, Any] | None]:
    metadata = store.head(PRODUCTION_LEASE_KEY)
    if metadata is None:
        return None, None, None
    value = _load_json(store, PRODUCTION_LEASE_KEY, "production lease")
    if value.get("schema_version") != f"{COORDINATOR_SCHEMA}/production-lease":
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "lease schema is invalid")
    return _lease_from_value(value), metadata.etag, value


def _lease_value(lease: ProductionLease) -> dict[str, Any]:
    value = lease.to_dict()
    value.pop("idempotent", None)
    return {"schema_version": f"{COORDINATOR_SCHEMA}/production-lease", **value}


def _validate_registry_for_production(
    store: ObjectStore,
    *,
    batch_id: str,
    expected_registry_version: int,
    expected_batch_version: int,
    observed_production: ProductionIdentity,
    required_state: str,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    head, _ = registry._load_head(store)
    snapshot, record = registry._load_batch_snapshot(store, head, batch_id)
    if head["registry_version"] != expected_registry_version:
        raise M13CoordinatorError(
            "M13_PRODUCTION_REGISTRY_VERSION_STALE",
            "expected registry version is stale",
            expected=expected_registry_version,
            observed=head["registry_version"],
        )
    if snapshot["batch_version"] != expected_batch_version:
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_VERSION_STALE",
            "expected batch version is stale",
            expected=expected_batch_version,
            observed=snapshot["batch_version"],
        )
    if record.state != required_state:
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_STATE_INVALID",
            "batch is not in the required production state",
            expected=required_state,
            observed=record.state,
        )
    if record.candidate_channel is None:
        raise M13CoordinatorError(
            "M13_PRODUCTION_CANDIDATE_MISSING", "batch candidate channel is missing"
        )
    if not registry._completed_operation(snapshot, "release_comparison"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_COMPARISON_MISSING",
            "completed release comparison evidence is required",
        )
    try:
        assert_expected_previous_production(
            expected=record.seed.production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE",
            "observed production differs from batch expected previous production",
        ) from exc
    return snapshot, record, head


def acquire_production_lease(
    store: ObjectStore,
    *,
    batch_id: str,
    operation_id: str,
    holder_id: str,
    acquired_at: str,
    expires_at: str,
    observed_production: ProductionIdentity,
    expected_registry_version: int,
    expected_batch_version: int,
) -> ProductionLease:
    if not OPERATION_ID_RE.fullmatch(operation_id):
        raise M13CoordinatorError("M13_PRODUCTION_OPERATION_INVALID", "operation_id is invalid")
    if not holder_id:
        raise M13CoordinatorError("M13_COORD_HOLDER_REQUIRED", "holder_id is required")
    _validate_window(acquired_at, expires_at)
    snapshot, record, _ = _validate_registry_for_production(
        store,
        batch_id=batch_id,
        expected_registry_version=expected_registry_version,
        expected_batch_version=expected_batch_version,
        observed_production=observed_production,
        required_state="awaiting_production_slot",
    )
    identity = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-acquire-request",
        "batch_id": batch_id,
        "operation_id": operation_id,
        "holder_id": holder_id,
        "candidate_channel": record.candidate_channel,
        "expected_registry_version": expected_registry_version,
        "expected_batch_version": expected_batch_version,
        "expected_previous_production": record.seed.production.to_identity(),
        "acquired_at": acquired_at,
        "expires_at": expires_at,
        "snapshot_event_hash": snapshot["current_event_hash"],
    }
    lease_id = _digest(identity, "mlease")
    current, etag, _ = _load_production_lease(store)
    if current is not None and current.lease_id == lease_id:
        return ProductionLease(**{**asdict(current), "idempotent": True})
    if current is not None and current.state in {
        "active",
        "permit_issued",
        "commit_authorized",
    }:
        now = _parse_utc(acquired_at, "acquired_at")
        expiry = _parse_utc(current.expires_at, "expires_at")
        if now <= expiry:
            raise M13CoordinatorError(
                "M13_PRODUCTION_LEASE_BUSY",
                "another production mutation lease is active",
                lease_id=current.lease_id,
                batch_id=current.batch_id,
            )
        if current.state == "commit_authorized":
            raise M13CoordinatorError(
                "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED",
                "expired commit-authorized lease requires manual reconciliation",
                lease_id=current.lease_id,
            )
        raise M13CoordinatorError(
            "M13_PRODUCTION_RECOVERY_REQUIRED",
            "expired production lease must be explicitly recovered",
            lease_id=current.lease_id,
        )
    generation = 1 if current is None else current.generation + 1
    fencing_token = _digest(
        {
            "generation": generation,
            "lease_id": lease_id,
            "previous_lease_id": current.lease_id if current else None,
        },
        "mfence",
    )
    acquisition_key = f"m13/v1/concurrency/production/acquisitions/{lease_id}.json"
    acquisition = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/production-acquisition",
        "lease_id": lease_id,
        "generation": generation,
        "fencing_token": fencing_token,
        "acquisition_key": acquisition_key,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, acquisition_key, json_bytes(acquisition))
    lease = ProductionLease(
        lease_id=lease_id,
        generation=generation,
        fencing_token=fencing_token,
        state="active",
        batch_id=batch_id,
        operation_id=operation_id,
        holder_id=holder_id,
        candidate_channel=str(record.candidate_channel),
        expected_registry_version=expected_registry_version,
        expected_batch_version=expected_batch_version,
        expected_previous_production=record.seed.production,
        acquired_at=acquired_at,
        expires_at=expires_at,
        acquisition_key=acquisition_key,
        updated_at=acquired_at,
        idempotent=artifact_idempotent,
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(lease),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return lease


def _require_current_lease(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    now: str,
    allowed_states: set[ProductionLeaseState],
) -> tuple[ProductionLease, str, dict[str, Any]]:
    current, etag, raw = _load_production_lease(store)
    if current is None or etag is None or raw is None:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_MISSING", "production lease is missing")
    if current.lease_id != lease_id:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_STALE", "lease_id is stale")
    if current.holder_id != holder_id:
        raise M13CoordinatorError("M13_PRODUCTION_HOLDER_MISMATCH", "lease holder differs")
    if current.fencing_token != fencing_token:
        raise M13CoordinatorError("M13_PRODUCTION_FENCE_STALE", "fencing token is stale")
    if current.state not in allowed_states:
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_STATE_INVALID",
            "lease is not in an allowed state",
            state=current.state,
        )
    if _parse_utc(now, "now") > _parse_utc(current.expires_at, "expires_at"):
        if current.state == "commit_authorized":
            raise M13CoordinatorError(
                "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED",
                "commit-authorized lease expired",
            )
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_EXPIRED", "production lease expired")
    return current, etag, raw


def renew_production_lease(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    renewed_at: str,
    expires_at: str,
) -> ProductionLease:
    current, etag, _ = _require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=renewed_at,
        allowed_states={"active", "permit_issued"},
    )
    if _parse_utc(expires_at, "expires_at") <= _parse_utc(current.expires_at, "expires_at"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_RENEWAL_INVALID", "renewal must extend the lease"
        )
    renewal_id = _digest(
        {
            "lease_id": lease_id,
            "generation": current.generation,
            "holder_id": holder_id,
            "renewed_at": renewed_at,
            "previous_expires_at": current.expires_at,
            "expires_at": expires_at,
        },
        "mrenew",
    )
    renewal_key = f"m13/v1/concurrency/production/renewals/{renewal_id}.json"
    renewal = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-renewal",
        "renewal_id": renewal_id,
        "lease_id": lease_id,
        "generation": current.generation,
        "fencing_token": fencing_token,
        "holder_id": holder_id,
        "renewed_at": renewed_at,
        "previous_expires_at": current.expires_at,
        "expires_at": expires_at,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, renewal_key, json_bytes(renewal))
    renewed = ProductionLease(
        **{
            **asdict(current),
            "expires_at": expires_at,
            "renewed_at": renewed_at,
            "updated_at": renewed_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(renewed),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return renewed


def issue_production_mutation_permit(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    issued_at: str,
    observed_production: ProductionIdentity,
) -> ProductionMutationPermit:
    current, etag, _ = _require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=issued_at,
        allowed_states={"active", "permit_issued"},
    )
    snapshot, record, _ = _validate_registry_for_production(
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
    permit_id = _digest(identity, "mpermit")
    permit_key = f"m13/v1/concurrency/production/permits/{permit_id}.json"
    if current.state == "permit_issued":
        if current.permit_id != permit_id or current.permit_key != permit_key:
            raise M13CoordinatorError(
                "M13_PRODUCTION_PERMIT_ALREADY_ISSUED",
                "lease already has a different permit",
            )
        artifact = _load_json(store, permit_key, "production permit")
        if artifact.get("permit_id") != permit_id:
            raise M13CoordinatorError(
                "M13_PRODUCTION_PERMIT_INVALID", "permit replay diverged"
            )
        return ProductionMutationPermit(
            permit_id=permit_id,
            lease_id=current.lease_id,
            generation=current.generation,
            fencing_token=current.fencing_token,
            batch_id=current.batch_id,
            operation_id=current.operation_id,
            holder_id=current.holder_id,
            expected_registry_version=current.expected_registry_version,
            expected_batch_version=current.expected_batch_version,
            expected_previous_production=current.expected_previous_production,
            issued_at=issued_at,
            expires_at=current.expires_at,
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
    artifact_idempotent = put_immutable(store, permit_key, json_bytes(artifact))
    updated = ProductionLease(
        **{
            **asdict(current),
            "state": "permit_issued",
            "permit_id": permit_id,
            "permit_key": permit_key,
            "updated_at": issued_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(updated),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return ProductionMutationPermit(
        permit_id=permit_id,
        lease_id=current.lease_id,
        generation=current.generation,
        fencing_token=current.fencing_token,
        batch_id=current.batch_id,
        operation_id=current.operation_id,
        holder_id=current.holder_id,
        expected_registry_version=current.expected_registry_version,
        expected_batch_version=current.expected_batch_version,
        expected_previous_production=current.expected_previous_production,
        issued_at=issued_at,
        expires_at=current.expires_at,
        permit_key=permit_key,
        idempotent=artifact_idempotent,
    )


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
    current, lease_etag, _ = _require_current_lease(
        store,
        lease_id=permit.lease_id,
        holder_id=permit.holder_id,
        fencing_token=permit.fencing_token,
        now=occurred_at,
        allowed_states={"permit_issued"},
    )
    if current.permit_id != permit.permit_id or current.permit_key != permit.permit_key:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_STALE", "permit is not current")
    artifact = _load_json(store, permit.permit_key, "production permit")
    if artifact.get("permit_id") != permit.permit_id:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_INVALID", "permit artifact mismatch")
    snapshot, record, head = _validate_registry_for_production(
        store,
        batch_id=permit.batch_id,
        expected_registry_version=permit.expected_registry_version,
        expected_batch_version=permit.expected_batch_version,
        observed_production=observed_production,
        required_state="awaiting_production_slot",
    )
    if current.operation_id != permit.operation_id or current.batch_id != permit.batch_id:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_STALE", "permit identity differs from lease")
    request_id = permit.permit_id
    batch_version = snapshot["batch_version"] + 1
    registry_version = head["registry_version"] + 1
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
        request_id=request_id,
        snapshot_key=snapshot_key,
    )
    event_key = (
        f"{registry._batch_prefix(permit.batch_id)}/events/"
        f"{batch_version:06d}-{event['event_sha256']}.json"
    )
    next_record = registry.replace(record, state="promoting")
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
        registry._write_head(store, current_etag=registry._load_head(store)[1], head=new_head)
    except registry.M13RegistryError as exc:
        current_snapshot = registry.get_batch(store, permit.batch_id)
        current_record = registry._record_from_identity(current_snapshot["record"])
        last_event = _load_json(store, current_snapshot["event_keys"][-1], "last registry event")
        if current_record.state == "promoting" and last_event.get("request_id") == permit.permit_id:
            return registry.RegistryMutationResult(
                batch_id=permit.batch_id,
                registry_version=registry.registry_status(store)["registry_version"],
                batch_version=current_snapshot["batch_version"],
                state="promoting",
                snapshot_key=registry._load_head(store)[0]["batches"][permit.batch_id]["snapshot_key"],
                event_key=current_snapshot["event_keys"][-1],
                idempotent=True,
                operation_id=permit.operation_id,
            )
        raise M13CoordinatorError(
            "M13_PRODUCTION_REGISTRY_CONFLICT", "registry changed during promotion transition"
        ) from exc
    refreshed, refreshed_etag, _ = _load_production_lease(store)
    if refreshed is None or refreshed_etag is None or refreshed.lease_id != current.lease_id:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_STALE", "lease changed during transition")
    marker_id = _digest(
        {
            "permit_id": permit.permit_id,
            "registry_version": registry_version,
            "batch_version": batch_version,
            "event_key": event_key,
        },
        "mtransition",
    )
    marker_key = f"m13/v1/concurrency/production/transitions/{marker_id}.json"
    marker = {
        "schema_version": f"{COORDINATOR_SCHEMA}/promotion-transition",
        "marker_id": marker_id,
        "permit_id": permit.permit_id,
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
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
    _ = lease_etag
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


def authorize_production_commit(
    store: ObjectStore,
    *,
    permit: ProductionMutationPermit,
    holder_id: str,
    authorized_at: str,
    observed_production: ProductionIdentity,
) -> CommitAuthorization:
    current, etag, _ = _require_current_lease(
        store,
        lease_id=permit.lease_id,
        holder_id=holder_id,
        fencing_token=permit.fencing_token,
        now=authorized_at,
        allowed_states={"permit_issued", "commit_authorized"},
    )
    if current.permit_id != permit.permit_id or current.permit_key != permit.permit_key:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_STALE", "permit is not current")
    head, _ = registry._load_head(store)
    snapshot, record = registry._load_batch_snapshot(store, head, permit.batch_id)
    if record.state != "promoting":
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_STATE_INVALID", "batch must be promoting before commit"
        )
    if snapshot["batch_version"] != permit.expected_batch_version + 1:
        raise M13CoordinatorError(
            "M13_PRODUCTION_BATCH_VERSION_STALE", "promoting batch version is unexpected"
        )
    try:
        assert_expected_previous_production(
            expected=current.expected_previous_production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE",
            "production changed before commit authorization",
        ) from exc
    identity = {
        "schema_version": f"{COORDINATOR_SCHEMA}/commit-authorization-request",
        "permit_id": permit.permit_id,
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
        "batch_id": current.batch_id,
        "operation_id": current.operation_id,
        "holder_id": holder_id,
        "expected_previous_production": observed_production.to_identity(),
        "authorized_at": authorized_at,
        "expires_at": current.expires_at,
        "registry_event_hash": snapshot["current_event_hash"],
    }
    authorization_id = _digest(identity, "mauth")
    authorization_key = (
        f"m13/v1/concurrency/production/authorizations/{authorization_id}.json"
    )
    if current.state == "commit_authorized":
        if (
            current.authorization_id != authorization_id
            or current.authorization_key != authorization_key
        ):
            raise M13CoordinatorError(
                "M13_PRODUCTION_COMMIT_ALREADY_AUTHORIZED",
                "lease already has a different commit authorization",
            )
        return CommitAuthorization(
            authorization_id=authorization_id,
            permit_id=permit.permit_id,
            lease_id=current.lease_id,
            generation=current.generation,
            fencing_token=current.fencing_token,
            batch_id=current.batch_id,
            operation_id=current.operation_id,
            holder_id=holder_id,
            expected_previous_production=current.expected_previous_production,
            authorized_at=authorized_at,
            expires_at=current.expires_at,
            authorization_key=authorization_key,
            idempotent=True,
        )
    artifact = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/commit-authorization",
        "authorization_id": authorization_id,
        "authorization_key": authorization_key,
        "governance": {
            **GOVERNANCE_NO_WRITE,
            "release_write_permitted": True,
            "production_write_permitted": True,
            "permanent_ledger_append_permitted": True,
        },
    }
    artifact_idempotent = put_immutable(store, authorization_key, json_bytes(artifact))
    updated = ProductionLease(
        **{
            **asdict(current),
            "state": "commit_authorized",
            "authorization_id": authorization_id,
            "authorization_key": authorization_key,
            "updated_at": authorized_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(updated),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return CommitAuthorization(
        authorization_id=authorization_id,
        permit_id=permit.permit_id,
        lease_id=current.lease_id,
        generation=current.generation,
        fencing_token=current.fencing_token,
        batch_id=current.batch_id,
        operation_id=current.operation_id,
        holder_id=holder_id,
        expected_previous_production=current.expected_previous_production,
        authorized_at=authorized_at,
        expires_at=current.expires_at,
        authorization_key=authorization_key,
        idempotent=artifact_idempotent,
    )


def validate_commit_authorization(
    store: ObjectStore,
    *,
    authorization: CommitAuthorization,
    holder_id: str,
    checked_at: str,
    observed_production: ProductionIdentity,
) -> None:
    if not AUTHORIZATION_ID_RE.fullmatch(authorization.authorization_id):
        raise M13CoordinatorError(
            "M13_PRODUCTION_AUTHORIZATION_INVALID", "authorization_id is invalid"
        )
    current, _, _ = _require_current_lease(
        store,
        lease_id=authorization.lease_id,
        holder_id=holder_id,
        fencing_token=authorization.fencing_token,
        now=checked_at,
        allowed_states={"commit_authorized"},
    )
    if (
        current.authorization_id != authorization.authorization_id
        or current.authorization_key != authorization.authorization_key
    ):
        raise M13CoordinatorError(
            "M13_PRODUCTION_AUTHORIZATION_STALE", "authorization is not current"
        )
    artifact = _load_json(store, authorization.authorization_key, "commit authorization")
    if artifact.get("authorization_id") != authorization.authorization_id:
        raise M13CoordinatorError(
            "M13_PRODUCTION_AUTHORIZATION_INVALID", "authorization artifact mismatch"
        )
    try:
        assert_expected_previous_production(
            expected=current.expected_previous_production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE",
            "production changed after commit authorization",
        ) from exc


def complete_production_mutation(
    store: ObjectStore,
    *,
    authorization: CommitAuthorization,
    holder_id: str,
    completed_at: str,
    resulting_production: ProductionIdentity,
    evidence_refs: tuple[str, ...],
) -> ProductionLease:
    current, etag, _ = _require_current_lease(
        store,
        lease_id=authorization.lease_id,
        holder_id=holder_id,
        fencing_token=authorization.fencing_token,
        now=completed_at,
        allowed_states={"commit_authorized"},
    )
    if current.authorization_id != authorization.authorization_id:
        raise M13CoordinatorError(
            "M13_PRODUCTION_AUTHORIZATION_STALE", "authorization is not current"
        )
    if not evidence_refs or len(evidence_refs) != len(set(evidence_refs)):
        raise M13CoordinatorError(
            "M13_PRODUCTION_COMPLETION_EVIDENCE_INVALID",
            "unique completion evidence references are required",
        )
    if resulting_production == current.expected_previous_production:
        raise M13CoordinatorError(
            "M13_PRODUCTION_RESULT_UNCHANGED",
            "resulting production identity must differ from expected previous",
        )
    completion_id = _digest(
        {
            "authorization_id": authorization.authorization_id,
            "lease_id": current.lease_id,
            "generation": current.generation,
            "batch_id": current.batch_id,
            "operation_id": current.operation_id,
            "completed_at": completed_at,
            "expected_previous_production": current.expected_previous_production.to_identity(),
            "resulting_production": resulting_production.to_identity(),
            "evidence_refs": list(evidence_refs),
        },
        "mcomplete",
    )
    completion_key = f"m13/v1/concurrency/production/completions/{completion_id}.json"
    artifact = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-completion",
        "completion_id": completion_id,
        "authorization_id": authorization.authorization_id,
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
        "batch_id": current.batch_id,
        "operation_id": current.operation_id,
        "holder_id": holder_id,
        "completed_at": completed_at,
        "expected_previous_production": current.expected_previous_production.to_identity(),
        "resulting_production": resulting_production.to_identity(),
        "evidence_refs": list(evidence_refs),
        "governance": {
            **GOVERNANCE_NO_WRITE,
            "release_write_permitted": True,
            "production_write_permitted": True,
            "permanent_ledger_append_permitted": True,
        },
    }
    artifact_idempotent = put_immutable(store, completion_key, json_bytes(artifact))
    released = ProductionLease(
        **{
            **asdict(current),
            "state": "released",
            "completion_key": completion_key,
            "updated_at": completed_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(released),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return released


def abort_production_lease(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    released_at: str,
    reason: str,
) -> ProductionLease:
    if not reason.strip():
        raise M13CoordinatorError("M13_PRODUCTION_ABORT_INVALID", "reason is required")
    current, etag, _ = _require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=released_at,
        allowed_states={"active", "permit_issued"},
    )
    release_id = _digest(
        {
            "lease_id": current.lease_id,
            "generation": current.generation,
            "holder_id": holder_id,
            "released_at": released_at,
            "reason": reason,
        },
        "mrelease",
    )
    release_key = f"m13/v1/concurrency/production/releases/{release_id}.json"
    artifact = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-release",
        "release_id": release_id,
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
        "batch_id": current.batch_id,
        "operation_id": current.operation_id,
        "holder_id": holder_id,
        "released_at": released_at,
        "reason": reason,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, release_key, json_bytes(artifact))
    released = ProductionLease(
        **{
            **asdict(current),
            "state": "released",
            "release_key": release_key,
            "updated_at": released_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(released),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return released


def recover_expired_production_lease(
    store: ObjectStore,
    *,
    recovered_at: str,
    actor: str,
    reason: str,
) -> ProductionLease:
    now = _parse_utc(recovered_at, "recovered_at")
    if not actor or not reason.strip():
        raise M13CoordinatorError(
            "M13_PRODUCTION_RECOVERY_INVALID", "actor and reason are required"
        )
    current, etag, _ = _load_production_lease(store)
    if current is None or etag is None:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_MISSING", "production lease is missing")
    if current.state in {"released", "recovered"}:
        return ProductionLease(**{**asdict(current), "idempotent": True})
    if now <= _parse_utc(current.expires_at, "expires_at"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_NOT_EXPIRED", "unexpired lease cannot be recovered"
        )
    if current.state == "commit_authorized":
        raise M13CoordinatorError(
            "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED",
            "commit-authorized lease requires manual reconciliation",
        )
    recovery_id = _digest(
        {
            "lease_id": current.lease_id,
            "generation": current.generation,
            "fencing_token": current.fencing_token,
            "batch_id": current.batch_id,
            "operation_id": current.operation_id,
            "actor": actor,
            "recovered_at": recovered_at,
            "reason": reason,
        },
        "mprecover",
    )
    recovery_key = f"m13/v1/concurrency/production/recoveries/{recovery_id}.json"
    artifact = {
        "schema_version": f"{COORDINATOR_SCHEMA}/production-recovery",
        "recovery_id": recovery_id,
        "lease_id": current.lease_id,
        "generation": current.generation,
        "fencing_token": current.fencing_token,
        "batch_id": current.batch_id,
        "operation_id": current.operation_id,
        "actor": actor,
        "recovered_at": recovered_at,
        "reason": reason,
        "governance": GOVERNANCE_NO_WRITE,
    }
    artifact_idempotent = put_immutable(store, recovery_key, json_bytes(artifact))
    recovered = ProductionLease(
        **{
            **asdict(current),
            "state": "recovered",
            "recovery_key": recovery_key,
            "updated_at": recovered_at,
            "idempotent": artifact_idempotent,
        }
    )
    _cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=_lease_value(recovered),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return recovered


def coordinator_status(store: ObjectStore, *, candidate_capacity: int = 2) -> dict[str, Any]:
    candidate_head, _ = _load_candidate_head(store, capacity=candidate_capacity)
    production, _, _ = _load_production_lease(store)
    return {
        "schema_version": f"{COORDINATOR_SCHEMA}/status",
        "candidate": {
            "head_version": candidate_head["head_version"],
            "capacity": candidate_head["capacity"],
            "active_count": len(candidate_head["active"]),
            "active": candidate_head["active"],
        },
        "production": production.to_dict() if production else None,
        "governance": GOVERNANCE_NO_WRITE,
    }
