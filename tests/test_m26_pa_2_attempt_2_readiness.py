from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-2-attempt-2-readiness.yml"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate_and_verify(name: str, schema_name: str) -> dict[str, object]:
    value = json.loads((PILOT / name).read_text(encoding="utf-8"))
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert errors == []
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert hashlib.sha256(canonical_bytes(candidate)).hexdigest() == expected
    return value


def test_attempt_1_failure_is_strict_and_zero_operation() -> None:
    value = validate_and_verify(
        "pa2-live-attempt-1-failure.json",
        "pa2-live-attempt-failure-v1.schema.json",
    )
    assert value["self_sha256"] == (
        "9724218f4cebbd82d6d35093d913d5105f2098343194e1a2c10748323301c6f5"
    )
    assert all(count == 0 for count in value["operations"].values())
    assert value["failure"]["before_data_plane_execution"] is True
    assert value["disposition"]["rerun_authorized"] is False
    assert value["disposition"]["pa3_unlocked"] is False


def test_attempt_2_is_blocked_and_non_authorizing() -> None:
    value = validate_and_verify(
        "pa2-attempt-2-readiness.json",
        "pa2-attempt-2-readiness-v1.schema.json",
    )
    assert value["self_sha256"] == (
        "0bf622ea104ecde8f808aa80f827ad4c4ec98f972c1786818934666b3b63f6fe"
    )
    assert value["authorized"] is False
    assert value["triggerable"] is False
    assert all(authority is False for authority in value["authority"].values())
    assert value["required_secret_names"] == [
        "R2_ACCESS_KEY_ID_READ",
        "R2_SECRET_ACCESS_KEY_READ",
        "QDRANT_READ_ONLY_API_KEY",
    ]


def test_attempt_2_requires_new_run_not_rerun() -> None:
    value = json.loads(
        (PILOT / "pa2-attempt-2-readiness.json").read_text(encoding="utf-8")
    )
    future = value["future_exact_run"]
    assert future["logical_attempt"] == 2
    assert future["github_run_attempt_expected"] == 1
    assert future["new_authorization_and_main_push_required"] is True
    assert future["rerun_of_attempt_1_forbidden"] is True


def test_readiness_workflow_has_no_secret_or_live_surface() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "secrets." not in text
    assert "environment: m23-r3-diagnostic" not in text
    assert "push:" not in text
    for forbidden in (
        "R2_ACCESS_KEY_ID_READ: ${{",
        "QDRANT_READ_ONLY_API_KEY: ${{",
        "workflow_dispatch",
        "put_object",
        "upsert",
        "rerun",
    ):
        assert forbidden not in text
