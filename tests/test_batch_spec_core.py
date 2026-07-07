from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.batch_spec import load_batch_spec, validate_transition
from knowledge_engine.errors import IntegrityError


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _payload(state: str = "planned") -> dict:
    source_sha = None if state == "planned" else "a" * 40
    candidate = {"channel": None, "release_id": None, "manifest_sha256": None}
    production = {"operation_id": None, "request_path": None}
    if state in {"candidate_built", "runtime_accepted", "request_spec_committed"}:
        candidate = {
            "channel": f"candidate-source-{'a' * 40}",
            "release_id": "20260707T010203Z-abcdef123456",
            "manifest_sha256": "d" * 64,
        }
    if state == "request_spec_committed":
        production = {
            "operation_id": "m7-001-schema-proof-001",
            "request_path": "production_promotions/m7-001-schema-proof.json",
        }
    return {
        "schema_version": "governed-batch-spec/v2",
        "batch_id": "m7-001-schema-proof",
        "title": "Schema proof batch",
        "lifecycle_state": state,
        "source": {
            "repository": "danielcanfly/knowledge-source",
            "paths": ["bundle/concepts/schema-proof.md"],
            "sha": source_sha,
        },
        "builder_sha": "b" * 40,
        "foundation_sha": "c" * 40,
        "candidate": candidate,
        "production_request": production,
        "acceptance": {
            "public_query": "What is the schema proof?",
            "expected_public_status": "answered",
            "expected_citation_url": "https://example.invalid/schema-proof",
            "acl_query": "restricted schema proof",
            "expected_acl_status": "not_found",
            "raw_fallback_allowed": False,
        },
    }


def test_batch_spec_lifecycle_requirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = Path("governed_batches/m7-001-schema-proof.json")
    for state in ("planned", "candidate_built", "request_spec_committed"):
        _write(path, _payload(state))
        assert load_batch_spec(path).lifecycle_state == state


def test_batch_spec_rejects_unsafe_fallback_and_skipped_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = Path("governed_batches/m7-001-schema-proof.json")
    payload = _payload()
    payload["acceptance"]["raw_fallback_allowed"] = True
    _write(path, payload)
    with pytest.raises(IntegrityError, match="raw_fallback_allowed"):
        load_batch_spec(path)

    validate_transition("planned", "source_reviewed")
    with pytest.raises(IntegrityError, match="illegal lifecycle transition"):
        validate_transition("planned", "candidate_built")
