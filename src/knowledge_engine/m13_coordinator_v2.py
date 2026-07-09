from __future__ import annotations

from typing import Any

from .m13_candidate_coordinator import (
    acquire_candidate_slot,
    candidate_status,
    recover_expired_candidate_slots,
    release_candidate_slot,
)
from .m13_coordination_common import (
    CANDIDATE_HEAD_KEY,
    COORDINATOR_SCHEMA,
    PRODUCTION_LEASE_KEY,
    CandidateSlot,
    CommitAuthorization,
    M13CoordinatorError,
    ProductionLease,
    ProductionMutationPermit,
)
from .m13_production_commit import (
    authorize_production_commit,
    complete_production_mutation,
    validate_commit_authorization,
)
from .m13_production_lease import (
    abort_production_lease,
    acquire_production_lease,
    production_status,
    recover_expired_production_lease,
    renew_production_lease,
)
from .m13_production_permit import (
    issue_production_mutation_permit,
    transition_batch_to_promoting,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore

__all__ = [
    "CANDIDATE_HEAD_KEY",
    "COORDINATOR_SCHEMA",
    "PRODUCTION_LEASE_KEY",
    "CandidateSlot",
    "CommitAuthorization",
    "M13CoordinatorError",
    "ProductionLease",
    "ProductionMutationPermit",
    "abort_production_lease",
    "acquire_candidate_slot",
    "acquire_production_lease",
    "authorize_production_commit",
    "complete_production_mutation",
    "coordinator_status",
    "issue_production_mutation_permit",
    "recover_expired_candidate_slots",
    "recover_expired_production_lease",
    "release_candidate_slot",
    "renew_production_lease",
    "transition_batch_to_promoting",
    "validate_commit_authorization",
]


def coordinator_status(
    store: ObjectStore,
    *,
    candidate_capacity: int = 2,
) -> dict[str, Any]:
    return {
        "schema_version": f"{COORDINATOR_SCHEMA}/status",
        "candidate": candidate_status(store, capacity=candidate_capacity),
        "production": production_status(store),
        "governance": GOVERNANCE_NO_WRITE,
    }
