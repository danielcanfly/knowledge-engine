from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.batch_registry import load_batch_registry, validate_batch_registry
from knowledge_engine.errors import IntegrityError


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _spec() -> dict:
    return {
        "schema_version": "governed-batch-spec/v2",
        "batch_id": "m7-001-schema-proof",
        "title": "Schema proof batch",
        "lifecycle_state": "planned",
        "source": {
            "repository": "danielcanfly/knowledge-source",
            "paths": ["bundle/concepts/schema-proof.md"],
            "sha": None,
        },
        "builder_sha": "b" * 40,
        "foundation_sha": "c" * 40,
        "candidate": {"channel": None, "release_id": None, "manifest_sha256": None},
        "production_request": {"operation_id": None, "request_path": None},
        "acceptance": {
            "public_query": "What is the schema proof?",
            "expected_public_status": "answered",
            "expected_citation_url": "https://example.invalid/schema-proof",
            "acl_query": "restricted schema proof",
            "expected_acl_status": "not_found",
            "raw_fallback_allowed": False,
        },
    }


def _entry() -> dict:
    return {
        "batch_id": "m7-001-schema-proof",
        "spec_path": "governed_batches/m7-001-schema-proof.json",
        "lifecycle_state": "planned",
        "candidate_channel": None,
        "operation_id": None,
        "request_path": None,
    }


def test_registry_validates_registered_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(Path("governed_batches/m7-001-schema-proof.json"), _spec())
    _write(
        Path("governed_batches/registry.json"),
        {"schema_version": "governed-batch-registry/v1", "batches": [_entry()]},
    )
    result = validate_batch_registry(load_batch_registry())
    assert result["status"] == "valid"
    assert result["batch_count"] == 1


def test_registry_rejects_duplicate_operation_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    first = {**_entry(), "operation_id": "shared-operation"}
    second = {
        **first,
        "batch_id": "m7-002-schema-proof",
        "spec_path": "governed_batches/m7-002-schema-proof.json",
    }
    _write(
        Path("governed_batches/registry.json"),
        {
            "schema_version": "governed-batch-registry/v1",
            "batches": [first, second],
        },
    )
    with pytest.raises(IntegrityError, match="duplicate operation_id"):
        load_batch_registry()
