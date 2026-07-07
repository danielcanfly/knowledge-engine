from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.scale_readiness import run_scale_readiness

RELEASE_ID = "20260707T010203Z-abcdef123456"
MANIFEST = "d" * 64


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _spec(batch_id: str, source_path: str) -> dict:
    return {
        "schema_version": "governed-batch-spec/v2",
        "batch_id": batch_id,
        "title": "Readiness proof",
        "lifecycle_state": "planned",
        "source": {
            "repository": "danielcanfly/knowledge-source",
            "paths": [source_path],
            "sha": None,
        },
        "builder_sha": "b" * 40,
        "foundation_sha": "c" * 40,
        "candidate": {"channel": None, "release_id": None, "manifest_sha256": None},
        "production_request": {"operation_id": None, "request_path": None},
        "acceptance": {
            "public_query": "What is the readiness proof?",
            "expected_public_status": "answered",
            "expected_citation_url": "https://example.invalid/readiness-proof",
            "acl_query": "boundary readiness proof",
            "expected_acl_status": "not_found",
            "raw_fallback_allowed": False,
        },
    }


def _prepare(root: Path, *, overlap: bool = False) -> None:
    batch_ids = ["m7-001-readiness-proof", "m7-002-readiness-proof"]
    paths = ["bundle/concepts/one.md", "bundle/concepts/one.md" if overlap else "bundle/concepts/two.md"]  # noqa: E501
    entries = []
    for batch_id, source_path in zip(batch_ids, paths, strict=True):
        spec_path = f"governed_batches/{batch_id}.json"
        _write(root / spec_path, _spec(batch_id, source_path))
        entries.append(
            {
                "batch_id": batch_id,
                "spec_path": spec_path,
                "lifecycle_state": "planned",
                "candidate_channel": None,
                "operation_id": None,
                "request_path": None,
            }
        )
    _write(
        root / "governed_batches/registry.json",
        {"schema_version": "governed-batch-registry/v1", "batches": entries},
    )
    _write(
        root / "production-pointer.json",
        {"release_id": RELEASE_ID, "manifest_sha256": MANIFEST},
    )
    _write(
        root / "workflow-health.json",
        {
            "ci": "success",
            "r2_release_integration": "success",
            "replay_rollback": "success",
            "ledger_open": True,
        },
    )


def test_scale_readiness_passes_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare(tmp_path)
    result = run_scale_readiness(
        production_pointer_path=Path("production-pointer.json"),
        expected_release_id=RELEASE_ID,
        expected_manifest_sha256=MANIFEST,
        workflow_health_path=Path("workflow-health.json"),
    )
    assert result["status"] == "ready_for_governed_dry_run"
    assert result["contracts"]["batch_count"] == 2
    assert result["mutations_performed"] == []


def test_scale_readiness_rejects_scope_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare(tmp_path, overlap=True)
    with pytest.raises(IntegrityError, match="Source path overlap"):
        run_scale_readiness(
            production_pointer_path=Path("production-pointer.json"),
            expected_release_id=RELEASE_ID,
            expected_manifest_sha256=MANIFEST,
            workflow_health_path=Path("workflow-health.json"),
        )


def test_scale_readiness_rejects_pointer_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _prepare(tmp_path)
    with pytest.raises(IntegrityError, match="production pointer drift"):
        run_scale_readiness(
            production_pointer_path=Path("production-pointer.json"),
            expected_release_id="20260707T010203Z-000000000000",
            expected_manifest_sha256=MANIFEST,
            workflow_health_path=Path("workflow-health.json"),
        )
