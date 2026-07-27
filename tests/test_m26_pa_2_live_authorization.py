from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = ROOT / "pilot" / "m26" / "m26-pa-2-live-authorization.json"
SCHEMA = ROOT / "schemas" / "m26-pa-2-live-authorization-v1.schema.json"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-live-read-evidence.yml"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_live_authorization_is_strict_and_self_digested() -> None:
    value = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []
    expected = value["self_sha256"]
    value["self_sha256"] = ""
    assert hashlib.sha256(canonical_bytes(value)).hexdigest() == expected
    assert expected == "76730d76b56652914603b9226653257c8fbcdfb10e30c8a78f9167d1c64b6f77"


def test_authorization_binds_exact_implementation_and_attempt() -> None:
    value = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    assert value["implementation"] == {
        "issue_number": 1186,
        "pull_request_number": 1187,
        "head_sha": "11db7672f0a24c4531ac0203ca89e2c4d0a6e975",
        "merge_sha": "ecad7b2bfb2e6d472bf0ed76d2e0adc818124dd9",
        "required_ancestor": True,
    }
    assert value["execution"]["environment"] == "m23-r3-diagnostic"
    assert value["execution"]["run_attempt"] == 1
    assert value["execution"]["trigger_marker"] == "[m26.pa2-live-authorized]"
    assert value["acceptance_requires_independent_reconciliation"] is True


def test_authorization_is_read_only_and_non_accepting() -> None:
    value = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    assert value["read_surface"]["r2_operations"] == ["get"]
    assert value["read_surface"]["qdrant_operations"] == ["count", "scroll"]
    assert value["read_surface"]["vectors"] is False
    assert value["read_surface"]["raw_source_body_reads"] is False
    assert all(flag is False for flag in value["denied_authority"].values())
    assert value["denied_authority"]["stage_acceptance"] is False


def test_workflow_is_exact_attempt_one_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "environment: m23-r3-diagnostic" in text
    assert "test \"$GITHUB_RUN_ATTEMPT\" = '1'" in text
    assert "[m26.pa2-live-authorized]" in text
    assert "workflow_dispatch" not in text
    assert "QDRANT_READ_ONLY_API_KEY" in text
    assert "R2_ACCESS_KEY_ID_READ" in text
    assert "R2_SECRET_ACCESS_KEY_READ" in text
    assert "_WRITE" not in text
    for forbidden in (
        "put_object",
        "delete_object",
        "upsert",
        "wrangler",
        "curl -X",
        "production_pointer_mutation = True",
    ):
        assert forbidden not in text


def test_workflow_secret_surface_matches_authorization() -> None:
    value = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in value["secret_names"]:
        assert f"secrets.{name}" in text
    assert text.count("${{ secrets.") == len(value["secret_names"])
