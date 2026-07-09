from __future__ import annotations

from dataclasses import replace
from typing import Any

from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import OPERATION_ID_RE, ProductionIdentity
from .m13_coordination_common import (
    COORDINATOR_SCHEMA,
    PRODUCTION_LEASE_KEY,
    M13CoordinatorError,
    ProductionLease,
    cas_write,
    digest,
    lease_value,
    load_production_lease,
    parse_utc,
    registry_preconditions,
    require_current_lease,
    validate_window,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore


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
    validate_window(acquired_at, expires_at)
    snapshot, record, _, _ = registry_preconditions(
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
    lease_id = digest(identity, "mlease")
    current, etag = load_production_lease(store)
    if current is not None and current.lease_id == lease_id:
        return replace(current, idempotent=True)
    if current is not None and current.state in {
        "active",
        "permit_issued",
        "commit_authorized",
    }:
        now = parse_utc(acquired_at, "acquired_at")
        expiry = parse_utc(current.expires_at, "expires_at")
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
                "expired commit authorization requires manual reconciliation",
            )
        raise M13CoordinatorError(
            "M13_PRODUCTION_RECOVERY_REQUIRED",
            "expired production lease must be explicitly recovered",
        )
    generation = 1 if current is None else current.generation + 1
    fencing_token = digest(
        {
            "generation": generation,
            "lease_id": lease_id,
            "previous_lease_id": current.lease_id if current else None,
        },
        "mfence",
    )
    acquisition_key = f"m13/v2/concurrency/production/acquisitions/{lease_id}.json"
    acquisition = {
        **identity,
        "schema_version": f"{COORDINATOR_SCHEMA}/production-acquisition",
        "lease_id": lease_id,
        "generation": generation,
        "fencing_token": fencing_token,
        "acquisition_key": acquisition_key,
        "governance": GOVERNANCE_NO_WRITE,
    }
    idempotent = put_immutable(store, acquisition_key, json_bytes(acquisition))
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
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(lease),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return lease


def renew_production_lease(
    store: ObjectStore,
    *,
    lease_id: str,
    holder_id: str,
    fencing_token: str,
    renewed_at: str,
    expires_at: str,
) -> ProductionLease:
    current, etag = require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=renewed_at,
        allowed_states={"active", "permit_issued"},
    )
    if parse_utc(expires_at, "expires_at") <= parse_utc(current.expires_at, "expires_at"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_RENEWAL_INVALID", "renewal must extend the lease"
        )
    renewal_id = digest(
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
    renewal_key = f"m13/v2/concurrency/production/renewals/{renewal_id}.json"
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
    idempotent = put_immutable(store, renewal_key, json_bytes(renewal))
    renewed = replace(
        current,
        expires_at=expires_at,
        renewed_at=renewed_at,
        updated_at=renewed_at,
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(renewed),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return renewed


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
    current, etag = require_current_lease(
        store,
        lease_id=lease_id,
        holder_id=holder_id,
        fencing_token=fencing_token,
        now=released_at,
        allowed_states={"active", "permit_issued"},
    )
    release_id = digest(
        {
            "lease_id": current.lease_id,
            "generation": current.generation,
            "holder_id": holder_id,
            "released_at": released_at,
            "reason": reason,
        },
        "mrelease",
    )
    release_key = f"m13/v2/concurrency/production/releases/{release_id}.json"
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
    idempotent = put_immutable(store, release_key, json_bytes(artifact))
    released = replace(
        current,
        state="released",
        release_key=release_key,
        updated_at=released_at,
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(released),
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
    now = parse_utc(recovered_at, "recovered_at")
    if not actor or not reason.strip():
        raise M13CoordinatorError(
            "M13_PRODUCTION_RECOVERY_INVALID", "actor and reason are required"
        )
    current, etag = load_production_lease(store)
    if current is None or etag is None:
        raise M13CoordinatorError("M13_PRODUCTION_LEASE_MISSING", "lease is missing")
    if current.state in {"released", "recovered"}:
        return replace(current, idempotent=True)
    if now <= parse_utc(current.expires_at, "expires_at"):
        raise M13CoordinatorError(
            "M13_PRODUCTION_LEASE_NOT_EXPIRED", "unexpired lease cannot be recovered"
        )
    if current.state == "commit_authorized":
        raise M13CoordinatorError(
            "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED",
            "commit-authorized lease requires manual reconciliation",
        )
    recovery_id = digest(
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
    recovery_key = f"m13/v2/concurrency/production/recoveries/{recovery_id}.json"
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
    idempotent = put_immutable(store, recovery_key, json_bytes(artifact))
    recovered = replace(
        current,
        state="recovered",
        recovery_key=recovery_key,
        updated_at=recovered_at,
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(recovered),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return recovered


def production_status(store: ObjectStore) -> dict[str, Any] | None:
    lease, _ = load_production_lease(store)
    return lease.to_dict() if lease else None
