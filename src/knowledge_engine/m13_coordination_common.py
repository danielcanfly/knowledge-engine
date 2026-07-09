from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes
from .errors import IntegrityError, ReleaseConflictError
from .m13_contracts import OPERATION_ID_RE, ProductionIdentity, stable_json_bytes
from .storage import ObjectStore, sha256_bytes

COORDINATOR_SCHEMA = "knowledge-engine-m13-coordinator/v2"
CANDIDATE_HEAD_KEY = "m13/v2/concurrency/candidate/head.json"
PRODUCTION_LEASE_KEY = "m13/v2/concurrency/production/lease.json"
LEASE_ID_RE = re.compile(r"^mlease_[a-f0-9]{32}$")
SLOT_ID_RE = re.compile(r"^mcslot_[a-f0-9]{32}$")
PERMIT_ID_RE = re.compile(r"^mpermit_[a-f0-9]{32}$")
AUTHORIZATION_ID_RE = re.compile(r"^mauth_[a-f0-9]{32}$")
FENCING_TOKEN_RE = re.compile(r"^mfence_[a-f0-9]{32}$")

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
    idempotent: bool = False

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
    idempotent: bool = False

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
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["expected_previous_production"] = self.expected_previous_production.to_identity()
        return value


def digest(value: dict[str, Any], prefix: str) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]}"


def parse_utc(value: str, field_name: str) -> datetime:
    if not value.endswith("Z"):
        raise M13CoordinatorError("M13_COORD_TIME_INVALID", f"{field_name} must end with Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_COORD_TIME_INVALID", f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise M13CoordinatorError("M13_COORD_TIME_INVALID", f"{field_name} must be aware")
    return parsed.astimezone(UTC)


def validate_window(start: str, end: str) -> None:
    if parse_utc(end, "expires_at") <= parse_utc(start, "acquired_at"):
        raise M13CoordinatorError(
            "M13_COORD_WINDOW_INVALID", "expires_at must be after acquired_at"
        )


def load_json(store: ObjectStore, key: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(store.get(key))
    except FileNotFoundError as exc:
        raise M13CoordinatorError(
            "M13_COORD_OBJECT_MISSING", f"{label} is missing", key=key
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M13CoordinatorError(
            "M13_COORD_OBJECT_INVALID", f"{label} is invalid JSON", key=key
        ) from exc
    if not isinstance(value, dict):
        raise M13CoordinatorError("M13_COORD_OBJECT_INVALID", f"{label} must be an object")
    return value


def cas_write(
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


def production_from_value(value: Any) -> ProductionIdentity:
    if not isinstance(value, dict):
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_INVALID", "production identity is invalid"
        )
    try:
        return ProductionIdentity(
            release_id=str(value["release_id"]),
            manifest_sha256=str(value["manifest_sha256"]),
            pointer_sha256=str(value["pointer_sha256"]),
        )
    except (KeyError, ValueError) as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_INVALID", "production identity is invalid"
        ) from exc


def lease_from_value(value: dict[str, Any], *, idempotent: bool = False) -> ProductionLease:
    raw_state = value.get("state")
    allowed = {"active", "permit_issued", "commit_authorized", "released", "recovered"}
    if raw_state not in allowed:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "lease state is invalid")
    try:
        lease = ProductionLease(
            lease_id=str(value["lease_id"]),
            generation=int(value["generation"]),
            fencing_token=str(value["fencing_token"]),
            state=cast(ProductionLeaseState, raw_state),
            batch_id=str(value["batch_id"]),
            operation_id=str(value["operation_id"]),
            holder_id=str(value["holder_id"]),
            candidate_channel=str(value["candidate_channel"]),
            expected_registry_version=int(value["expected_registry_version"]),
            expected_batch_version=int(value["expected_batch_version"]),
            expected_previous_production=production_from_value(
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
    if not FENCING_TOKEN_RE.fullmatch(lease.fencing_token):
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "fencing token is invalid")
    if lease.generation < 1:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "generation is invalid")
    validate_window(lease.acquired_at, lease.expires_at)
    return lease


def load_production_lease(
    store: ObjectStore,
) -> tuple[ProductionLease | None, str | None]:
    metadata = store.head(PRODUCTION_LEASE_KEY)
    if metadata is None:
        return None, None
    value = load_json(store, PRODUCTION_LEASE_KEY, "production lease")
    if value.get("schema_version") != f"{COORDINATOR_SCHEMA}/production-lease":
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_INVALID", "lease schema is invalid")
    return lease_from_value(value), metadata.etag


def lease_value(lease: ProductionLease) -> dict[str, Any]:
    value = lease.to_dict()
    value.pop("idempotent", None)
    return {"schema_version": f"{COORDINATOR_SCHEMA}/production-lease", **value}


def registry_preconditions(
    store: ObjectStore,
    *,
    batch_id: str,
    expected_registry_version: int,
    expected_batch_version: int,
    observed_production: ProductionIdentity,
    required_state: str,
) -> tuple[dict[str, Any], Any, dict[str, Any], str | None]:
    head, etag = registry._load_head(store)
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
            "batch is not in the required state",
            expected=required_state,
            observed=record.state,
        )
    if record.candidate_channel is None:
        raise M13CoordinatorError(
            "M13_PRODUCTION_CANDIDATE_MISSING", "candidate channel is missing"
        )
    if not registry._completed_operation(snapshot, "release_comparison"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_COMPARISON_MISSING", "release comparison is missing"
        )
    try:
        from .m13_contracts import assert_expected_previous_production

        assert_expected_previous_production(
            expected=record.seed.production,
            observed=observed_production,
        )
    except ValueError as exc:
        raise M13CoordinatorError(
            "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE",
            "observed production differs from expected previous",
        ) from exc
    return snapshot, record, head, etag


def require_current_lease(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    now: str,
    allowed_states: set[ProductionLeaseState],
) -> tuple[ProductionLease, str]:
    current, etag = load_production_lease(store)
    if current is None or etag is None:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_MISSING", "lease is missing")
    if current.lease_id != lease_id:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_STALE", "lease_id is stale")
    if current.holder_id != holder_id:
        raise M13CoordinatorError("M13_PRODUCTION_HOLDER_MISMATCH", "holder differs")
    if current.fencing_token != fencing_token:
        raise M13CoordinatorError("M13_PRODUCTION_FENCE_STALE", "fencing token is stale")
    if current.state not in allowed_states:
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_STATE_INVALID", "lease state is not allowed"
        )
    if parse_utc(now, "now") > parse_utc(current.expires_at, "expires_at"):
        if current.state == "commit_authorized":
            raise M13CoordinatorError(
                "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED",
                "commit-authorized lease expired",
            )
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_EXPIRED", "lease expired")
    return current, etag


def permit_from_lease(
    lease: ProductionLease,
    *,
    issued_at: str,
    permit_id: str,
    permit_key: str,
    idempotent: bool,
) -> ProductionMutationPermit:
    return ProductionMutationPermit(
        permit_id=permit_id,
        lease_id=lease.lease_id,
        generation=lease.generation,
        fencing_token=lease.fencing_token,
        batch_id=lease.batch_id,
        operation_id=lease.operation_id,
        holder_id=lease.holder_id,
        expected_registry_version=lease.expected_registry_version,
        expected_batch_version=lease.expected_batch_version,
        expected_previous_production=lease.expected_previous_production,
        issued_at=issued_at,
        expires_at=lease.expires_at,
        permit_key=permit_key,
        idempotent=idempotent,
    )


def authorization_from_lease(
    lease: ProductionLease,
    *,
    authorized_at: str,
    authorization_id: str,
    authorization_key: str,
    idempotent: bool,
) -> CommitAuthorization:
    if lease.permit_id is None:
        raise M13CoordinatorError("M13_PRODUCTION_PERMIT_MISSING", "permit is missing")
    return CommitAuthorization(
        authorization_id=authorization_id,
        permit_id=lease.permit_id,
        lease_id=lease.lease_id,
        generation=lease.generation,
        fencing_token=lease.fencing_token,
        batch_id=lease.batch_id,
        operation_id=lease.operation_id,
        holder_id=lease.holder_id,
        expected_previous_production=lease.expected_previous_production,
        authorized_at=authorized_at,
        expires_at=lease.expires_at,
        authorization_key=authorization_key,
        idempotent=idempotent,
    )
