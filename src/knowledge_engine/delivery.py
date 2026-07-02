from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import IntegrityError


def verify_source_validation_run(
    payload: dict[str, Any],
    *,
    source_repository: str,
    source_sha: str,
    validation_run_id: str,
) -> None:
    if str(payload.get("id")) != str(validation_run_id):
        raise IntegrityError("source validation run ID mismatch")
    repository = payload.get("repository")
    if not isinstance(repository, dict) or repository.get("full_name") != source_repository:
        raise IntegrityError("source validation run repository mismatch")
    expected = {
        "name": "Validate Knowledge Source",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": source_sha,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise IntegrityError(
                f"source validation run {key} mismatch: "
                f"expected {value!r}, got {payload.get(key)!r}"
            )


def verify_source_delivery_policy(
    policy_path: Path,
    *,
    builder_ref: str,
    foundation_ref: str,
    candidate_channel: str,
    acceptance_query: str,
) -> None:
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"invalid source promotion policy: {exc}") from exc
    if not isinstance(policy, dict):
        raise IntegrityError("source promotion policy must be an object")

    expected = {
        "builder_ref": builder_ref,
        "automation_ref": builder_ref,
        "foundation_ref": foundation_ref,
        "candidate_acceptance_query": acceptance_query,
        "direct_source_to_production": False,
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            raise IntegrityError(
                f"source promotion policy {key} mismatch: "
                f"expected {value!r}, got {policy.get(key)!r}"
            )

    prefix = str(policy.get("candidate_channel_prefix", ""))
    if not prefix or not candidate_channel.startswith(prefix):
        raise IntegrityError(
            "candidate channel does not match source promotion policy prefix"
        )
    if candidate_channel == str(policy.get("production_channel", "production")):
        raise IntegrityError("candidate channel cannot equal production channel")
