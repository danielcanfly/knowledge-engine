from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.delivery import (
    verify_source_delivery_policy,
    verify_source_validation_run,
)
from knowledge_engine.errors import IntegrityError

SOURCE_REPOSITORY = "danielcanfly/knowledge-source"
SOURCE_SHA = "a" * 40
BUILDER_SHA = "b" * 40
FOUNDATION_SHA = "d" * 40
VALIDATION_RUN_ID = "28590000000"
CHANNEL = f"candidate-source-{SOURCE_SHA}"
QUERY = "quartz lantern protocol"


def _run_payload() -> dict:
    return {
        "id": int(VALIDATION_RUN_ID),
        "name": "Validate Knowledge Source",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": SOURCE_SHA,
        "repository": {"full_name": SOURCE_REPOSITORY},
    }


def _policy(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "builder_ref": BUILDER_SHA,
                "automation_ref": BUILDER_SHA,
                "foundation_ref": FOUNDATION_SHA,
                "candidate_channel_prefix": "candidate-source-",
                "candidate_acceptance_query": QUERY,
                "production_channel": "production",
                "direct_source_to_production": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_source_validation_run_accepts_exact_success() -> None:
    verify_source_validation_run(
        _run_payload(),
        source_repository=SOURCE_REPOSITORY,
        source_sha=SOURCE_SHA,
        validation_run_id=VALIDATION_RUN_ID,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conclusion", "failure"),
        ("event", "pull_request"),
        ("head_branch", "feature"),
        ("head_sha", "c" * 40),
    ],
)
def test_source_validation_run_rejects_mismatch(field: str, value: str) -> None:
    payload = _run_payload()
    payload[field] = value

    with pytest.raises(IntegrityError, match=field):
        verify_source_validation_run(
            payload,
            source_repository=SOURCE_REPOSITORY,
            source_sha=SOURCE_SHA,
            validation_run_id=VALIDATION_RUN_ID,
        )


def test_source_delivery_policy_accepts_exact_pins(tmp_path: Path) -> None:
    verify_source_delivery_policy(
        _policy(tmp_path / "promotion-policy.json"),
        builder_ref=BUILDER_SHA,
        foundation_ref=FOUNDATION_SHA,
        candidate_channel=CHANNEL,
        acceptance_query=QUERY,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("builder_ref", "c" * 40),
        ("automation_ref", "c" * 40),
        ("foundation_ref", "c" * 40),
        ("candidate_acceptance_query", "wrong query"),
        ("direct_source_to_production", True),
    ],
)
def test_source_delivery_policy_rejects_drift(
    tmp_path: Path,
    field: str,
    value: str | bool,
) -> None:
    path = _policy(tmp_path / "promotion-policy.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(IntegrityError, match=field):
        verify_source_delivery_policy(
            path,
            builder_ref=BUILDER_SHA,
            foundation_ref=FOUNDATION_SHA,
            candidate_channel=CHANNEL,
            acceptance_query=QUERY,
        )
