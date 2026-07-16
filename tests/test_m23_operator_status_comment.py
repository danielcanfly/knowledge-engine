from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import m23_operator_status_comment as subject


def test_accepted_status_is_canonical_and_non_command() -> None:
    body = subject.build_status(
        phase="accepted",
        run_id="29599999999",
        command_type="r3_8_post_delete_recovery",
        expected_head="a" * 40,
        authorization_sha256="b" * 64,
    )
    assert body.startswith(subject.STATUS_PREFIX)
    assert not body.startswith(subject.COMMAND_PREFIX)
    payload = json.loads(body[len(subject.STATUS_PREFIX) :])
    assert payload["phase"] == "accepted"
    assert payload["run_id"] == "29599999999"
    assert payload["run_url"].endswith("/actions/runs/29599999999")
    assert payload["blockers_cleared"] is False
    assert "exit_code" not in payload


def test_final_status_binds_exit_and_artifact() -> None:
    body = subject.build_status(
        phase="final",
        run_id="29599999999",
        command_type="r3_8_post_delete_recovery",
        expected_head="a" * 40,
        authorization_sha256="b" * 64,
        exit_code="0",
        artifact_name="m23-7-r3-8-13-post-delete-recovery-29599999999",
    )
    payload = json.loads(body[len(subject.STATUS_PREFIX) :])
    assert payload["phase"] == "final"
    assert payload["exit_code"] == 0
    assert payload["artifact_name"] == (
        "m23-7-r3-8-13-post-delete-recovery-29599999999"
    )
    assert payload["worker_delete_replayed"] is False
    assert payload["qdrant_access_dispatched"] is False
    assert payload["r2_access_dispatched"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "other"),
        ("run_id", "not-a-run"),
        ("command_type", "../../shell"),
        ("expected_head", "A" * 40),
        ("authorization_sha256", "x" * 64),
    ],
)
def test_status_rejects_unbounded_identity(field: str, value: str) -> None:
    kwargs = {
        "phase": "accepted",
        "run_id": "29599999999",
        "command_type": "r3_8_post_delete_recovery",
        "expected_head": "a" * 40,
        "authorization_sha256": "b" * 64,
    }
    kwargs[field] = value
    with pytest.raises(subject.OperatorStatusError):
        subject.build_status(**kwargs)


def test_final_status_rejects_invalid_exit_or_artifact() -> None:
    with pytest.raises(subject.OperatorStatusError, match="final_status_exit_code"):
        subject.build_status(
            phase="final",
            run_id="29599999999",
            command_type="r3_8_post_delete_recovery",
            expected_head="a" * 40,
            authorization_sha256="b" * 64,
            exit_code="1",
            artifact_name="valid-artifact",
        )
    with pytest.raises(subject.OperatorStatusError, match="final_status_artifact"):
        subject.build_status(
            phase="final",
            run_id="29599999999",
            command_type="r3_8_post_delete_recovery",
            expected_head="a" * 40,
            authorization_sha256="b" * 64,
            exit_code="0",
            artifact_name="../../escape",
        )


def test_source_has_fixed_repository_issue_and_status_prefix() -> None:
    text = Path(subject.__file__).read_text(encoding="utf-8")
    assert 'REPOSITORY = "danielcanfly/knowledge-engine"' in text
    assert "BUS_ISSUE_NUMBER = 565" in text
    assert 'STATUS_PREFIX = "M23_OPERATOR_STATUS "' in text
    assert 'COMMAND_PREFIX = "M23_OPERATOR_COMMAND "' in text
    assert "issues/{issue}" not in text
    assert "api_url" not in text
