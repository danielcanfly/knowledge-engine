from __future__ import annotations

from dataclasses import replace

from . import m13_registry as registry
from .compiler_contract_v1 import json_bytes, put_immutable
from .m13_contracts import ProductionIdentity, assert_expected_previous_production
from .m13_coordination_common import (
    AUTHORIZATION_ID_RE,
    COORDINATOR_SCHEMA,
    PRODUCTION_LEASE_KEY,
    CommitAuthorization,
    M13CoordinatorError,
    ProductionLease,
    ProductionMutationPermit,
    authorization_from_lease,
    cas_write,
    digest,
    lease_value,
    load_json,
    require_current_lease,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore


def authorize_production_commit(
    store: ObjectStore,
    *,
    permit: ProductionMutationPermit,
    holder_id: str,
    authorized_at: str,
    observed_production: ProductionIdentity,
) -> CommitAuthorization:
    current, etag = require_current_lease(
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
            "M13_PRODUCTION_BATCH_STATE_INVALID", "batch must be promoting"
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
    authorization_id = digest(identity, "mauth")
    authorization_key = f"m13/v2/concurrency/production/authorizations/{authorization_id}.json"
    if current.state == "commit_authorized":
        if (
            current.authorization_id != authorization_id
            or current.authorization_key != authorization_key
        ):
            raise M13CoordinatorError(
                "M13_PRODUCTION_COMMIT_ALREADY_AUTHORIZED",
                "lease has a different commit authorization",
            )
        return authorization_from_lease(
            current,
            authorized_at=authorized_at,
            authorization_id=authorization_id,
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
    idempotent = put_immutable(store, authorization_key, json_bytes(artifact))
    updated = replace(
        current,
        state="commit_authorized",
        authorization_id=authorization_id,
        authorization_key=authorization_key,
        updated_at=authorized_at,
        idempotent=idempotent,
    )
    cas_write(
        store,
        key=PRODUCTION_LEASE_KEY,
        value=lease_value(updated),
        expected_etag=etag,
        conflict_code="M13_PRODUCTION_LEASE_CONFLICT",
    )
    return authorization_from_lease(
        updated,
        authorized_at=authorized_at,
        authorization_id=authorization_id,
        authorization_key=authorization_key,
        idempotent=idempotent,
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
    current, _ = require_current_lease(
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
    artifact = load_json(store, authorization.authorization_key, "commit authorization")
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
    current, etag = require_current_lease(
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
            "M13_PRODUCTION_RESULT_UNCHANGED", "resulting production must differ"
        )
    completion_id = digest(
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
    completion_key = f"m13/v2/concurrency/production/completions/{completion_id}.json"
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
    idempotent = put_immutable(store, completion_key, json_bytes(artifact))
    released = replace(
        current,
        state="released",
        completion_key=completion_key,
        updated_at=completed_at,
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
