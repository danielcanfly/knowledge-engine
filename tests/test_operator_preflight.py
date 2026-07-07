from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine import operator_preflight


def _write(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _prepare(root: Path, workflow_input: str = "request_path") -> Path:
    batch_id = "m7-001-preflight-proof"
    spec_path = Path(f"governed_batches/{batch_id}.json")
    _write(
        root / spec_path,
        {
            "schema_version": "governed-batch-spec/v2",
            "batch_id": batch_id,
            "title": "Preflight proof",
            "lifecycle_state": "planned",
            "source": {
                "repository": "danielcanfly/knowledge-source",
                "paths": ["bundle/concepts/preflight-proof.md"],
                "sha": None,
            },
            "builder_sha": "b" * 40,
            "foundation_sha": "c" * 40,
            "candidate": {
                "channel": None,
                "release_id": None,
                "manifest_sha256": None,
            },
            "production_request": {"operation_id": None, "request_path": None},
            "acceptance": {
                "public_query": "What is the preflight proof?",
                "expected_public_status": "answered",
                "expected_citation_url": "https://example.invalid/preflight-proof",
                "acl_query": "restricted preflight proof",
                "expected_acl_status": "not_found",
                "raw_fallback_allowed": False,
            },
        },
    )
    _write(
        root / "governed_batches/registry.json",
        {
            "schema_version": "governed-batch-registry/v1",
            "batches": [
                {
                    "batch_id": batch_id,
                    "spec_path": str(spec_path),
                    "lifecycle_state": "planned",
                    "candidate_channel": None,
                    "operation_id": None,
                    "request_path": None,
                }
            ],
        },
    )
    _write(
        root / ".github/workflows/m5-production-promotion.yml",
        "name: Promotion\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        f"      {workflow_input}:\n"
        "        required: true\n"
        "permissions:\n"
        "  contents: read\n",
    )
    return spec_path


def test_preflight_is_non_mutating_and_reports_next_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(operator_preflight, "_git_is_clean", lambda root: True)
    spec_path = _prepare(tmp_path)

    result = operator_preflight.run_operator_preflight(
        spec_path=spec_path,
        root=tmp_path,
        required_env=["SOURCE_READ_TOKEN"],
        environ={"SOURCE_READ_TOKEN": "present"},
    )

    assert result["status"] == "ready"
    assert result["next_action"] == "open_source_review"
    assert result["production_workflow_inputs"] == ["request_path"]
    assert result["mutations_performed"] == []


def test_preflight_rejects_extra_workflow_input_and_missing_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(operator_preflight, "_git_is_clean", lambda root: True)
    spec_path = _prepare(tmp_path, workflow_input="release_id")
    with pytest.raises(IntegrityError, match="inputs must be exactly"):
        operator_preflight.run_operator_preflight(spec_path=spec_path, root=tmp_path)

    _prepare(tmp_path)
    with pytest.raises(IntegrityError, match="environment variables are missing"):
        operator_preflight.run_operator_preflight(
            spec_path=spec_path,
            root=tmp_path,
            required_env=["SOURCE_READ_TOKEN"],
            environ={},
        )
