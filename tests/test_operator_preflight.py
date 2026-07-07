from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine import operator_preflight
from knowledge_engine.errors import IntegrityError


def _write(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload) + "\n"
    path.write_text(text, encoding="utf-8")


def _prepare(root: Path, input_name: str = "request_path") -> Path:
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
                "acl_query": "boundary preflight proof",
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
    workflow = (
        "name: Promotion\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        f"      {input_name}:\n"
        "        required: true\n"
        "permissions:\n"
        "  contents: read\n"
    )
    _write(root / ".github/workflows/m5-production-promotion.yml", workflow)
    return spec_path


def test_preflight_reports_next_action_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(operator_preflight, "_git_is_clean", lambda root: True)
    spec_path = _prepare(tmp_path)
    result = operator_preflight.run_operator_preflight(
        spec_path=spec_path,
        root=tmp_path,
        required_env=["REQUIRED_TOKEN"],
        environ={"REQUIRED_TOKEN": "present"},
    )
    assert result["status"] == "ready"
    assert result["next_action"] == "open_source_review"
    assert result["production_workflow_inputs"] == ["request_path"]
    assert result["mutations_performed"] == []


def test_preflight_rejects_boundary_and_environment_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(operator_preflight, "_git_is_clean", lambda root: True)
    spec_path = _prepare(tmp_path, input_name="release_id")
    with pytest.raises(IntegrityError, match="inputs must be exactly"):
        operator_preflight.run_operator_preflight(spec_path=spec_path, root=tmp_path)
    _prepare(tmp_path)
    with pytest.raises(IntegrityError, match="environment variables are missing"):
        operator_preflight.run_operator_preflight(
            spec_path=spec_path,
            root=tmp_path,
            required_env=["REQUIRED_TOKEN"],
            environ={},
        )
