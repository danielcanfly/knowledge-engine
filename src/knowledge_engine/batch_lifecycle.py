from __future__ import annotations

from .batch_spec import STATES
from .errors import IntegrityError

NEXT_ACTION = {
    "planned": "open_source_review",
    "source_reviewed": "run_source_validation",
    "source_validated": "build_candidate",
    "candidate_built": "run_runtime_acceptance",
    "runtime_accepted": "commit_production_request_spec",
    "request_spec_committed": "review_production_promotion",
    "production_promoted": "run_idempotent_replay_and_close",
    "closed": "start_next_batch",
}

if set(NEXT_ACTION) != set(STATES):
    raise RuntimeError("batch lifecycle next-action map is incomplete")


def next_action(lifecycle_state: str) -> str:
    try:
        return NEXT_ACTION[lifecycle_state]
    except KeyError as exc:
        raise IntegrityError(
            f"unknown lifecycle state for next action: {lifecycle_state}"
        ) from exc
