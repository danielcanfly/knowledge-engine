from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import m23_operator_request_bus as subject


def _request(base: str, nonce: str) -> dict:
    value = {
        "schema_version": subject.REQUEST_SCHEMA,
        "request_id": "r3-8-post-delete-recovery-001",
        "command_type": "r3_8_post_delete_recovery",
        "authorization_path": (
            "operator_authorizations/m23/r3-8/"
            "post-delete-recovery-29521901629-v3.json"
        ),
        "nonce": nonce,
        "expected_base_sha": base,
        "status_issue_number": 565,
    }
    value["request_sha256"] = subject.canonical_sha256(value)
    return value


def test_validate_request_requires_canonical_digest_and_base(tmp_path: Path) -> None:
    base = "a" * 40
    value = _request(base, "b" * 64)
    path = tmp_path / f"{value['request_id']}.json"
    path.write_text(subject.canonical_json(value) + "\n", encoding="utf-8")
    assert subject.validate_request(path, expected_base_sha=base)["request_sha256"] == (
        value["request_sha256"]
    )

    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(subject.OperatorRequestError, match="request_not_canonical"):
        subject.validate_request(path, expected_base_sha=base)


def test_validate_request_rejects_path_id_or_authority_drift(tmp_path: Path) -> None:
    base = "a" * 40
    value = _request(base, "b" * 64)
    path = tmp_path / "wrong-name.json"
    path.write_text(subject.canonical_json(value) + "\n", encoding="utf-8")
    with pytest.raises(subject.OperatorRequestError, match="request_id_path_mismatch"):
        subject.validate_request(path, expected_base_sha=base)

    path = tmp_path / f"{value['request_id']}.json"
    value["status_issue_number"] = 999
    unsigned = dict(value)
    unsigned.pop("request_sha256")
    value["request_sha256"] = subject.canonical_sha256(unsigned)
    path.write_text(subject.canonical_json(value) + "\n", encoding="utf-8")
    with pytest.raises(subject.OperatorRequestError, match="request_status_issue"):
        subject.validate_request(path, expected_base_sha=base)


def test_find_single_added_request_accepts_only_one_addition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            "A\toperator_requests/m23/r3-8/"
            "r3-8-post-delete-recovery-001.json\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **k: completed)
    assert subject.find_single_added_request(tmp_path, "a" * 40, "b" * 40).endswith(
        "r3-8-post-delete-recovery-001.json"
    )

    completed.stdout += "M\toperator_requests/m23/r3-8/old.json\n"
    with pytest.raises(subject.OperatorRequestError, match="request_diff_count"):
        subject.find_single_added_request(tmp_path, "a" * 40, "b" * 40)


def test_source_rejects_arbitrary_execution_surfaces() -> None:
    text = Path(subject.__file__).read_text(encoding="utf-8")
    assert 'REQUEST_ROOT = "operator_requests/m23/"' in text
    assert 'ALLOWED_COMMAND_TYPES = {"r3_8_post_delete_recovery"}' in text
    for forbidden in (
        "shell_command",
        "workflow_name",
        "client.post(",
        "wrangler delete",
        "wrangler deploy",
        "QDRANT_URL",
        "R2_ACCESS_KEY_ID",
    ):
        assert forbidden not in text
