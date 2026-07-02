from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.candidate import run_source_candidate_gate
from knowledge_engine.errors import IntegrityError
from knowledge_engine.storage import FileObjectStore, sha256_bytes


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "knowledge-source"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "Candidate Gate Test")
    _git(root, "config", "user.email", "candidate@example.invalid")

    (root / "bundle/concepts").mkdir(parents=True)
    (root / "provenance").mkdir()
    (root / "registry").mkdir()
    (root / "policy").mkdir()
    (root / "bundle/index.md").write_text(
        "# Candidate Source\n\n- [Delivery control](concepts/delivery-control.md)\n",
        encoding="utf-8",
    )
    (root / "bundle/concepts/delivery-control.md").write_text(
        """---
type: Concept
title: Candidate delivery control
description: Defines an internal phrase for candidate ACL acceptance.
timestamp: 2026-07-02T10:00:00Z
x-kos-id: ko_01JXYZ123456789ABCDEFGHJKM
x-kos-status: published
x-kos-audience: internal
x-kos-confidence: 0.99
x-kos-provenance: provenance/delivery-control.json
x-kos-review:
  review_id: review_delivery_control
  status: approved
---
# Candidate delivery control

The quartz lantern protocol proves candidate retrieval, citations, and ACL denial.
""",
        encoding="utf-8",
    )
    (root / "provenance/delivery-control.json").write_text(
        json.dumps(
            {
                "subject": {
                    "concept_id": "concepts/delivery-control",
                    "x_kos_id": "ko_01JXYZ123456789ABCDEFGHJKM",
                },
                "sources": [
                    {
                        "source_id": "source_m3",
                        "locator": "M3 acceptance contract",
                        "retrieved_at": "2026-07-02T10:00:00Z",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "registry/sources.json").write_text(
        '{"sources":[{"source_id":"source_m3","status":"active"}]}\n',
        encoding="utf-8",
    )
    (root / "registry/reviews.json").write_text(
        '{"reviews":[{"review_id":"review_delivery_control","status":"approved"}]}\n',
        encoding="utf-8",
    )
    (root / "policy/source-policy.json").write_text(
        '{"allowed_audiences":["public","internal"]}\n',
        encoding="utf-8",
    )
    (root / "policy/promotion-policy.json").write_text(
        '{"direct_source_to_production":false}\n',
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "source: add internal candidate control")
    return root, _git(root, "rev-parse", "HEAD")


def test_candidate_gate_is_reproducible_and_preserves_production(
    tmp_path: Path,
) -> None:
    source_root, source_sha = _source_repo(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    production_pointer = b'{"channel":"production","release_id":"stable"}\n'
    store.put(
        "channels/production.json",
        production_pointer,
        content_type="application/json",
        sha256=sha256_bytes(production_pointer),
        only_if_absent=True,
    )

    result = run_source_candidate_gate(
        store=store,
        repository_url=str(source_root),
        repository="danielcanfly/knowledge-source",
        source_commit_sha=source_sha,
        foundation_commit_sha="d" * 40,
        channel=f"candidate-source-{source_sha[:12]}",
        release_time=datetime(2026, 7, 2, 10, 15, tzinfo=UTC),
        query="quartz lantern protocol",
        work_root=tmp_path / "work",
    )

    assert result.reproducibility_passed is True
    assert result.production_pointer_unchanged is True
    assert result.internal_status == "answered"
    assert result.internal_result_count >= 1
    assert result.internal_citation_count >= 1
    assert result.public_status == "not_found"
    assert result.public_result_count == 0
    assert result.public_acl_filtered_count >= 1
    assert store.get("channels/production.json") == production_pointer
    assert store.head(f"channels/{result.channel}.json") is not None


def test_candidate_gate_refuses_production_channel(tmp_path: Path) -> None:
    source_root, source_sha = _source_repo(tmp_path)
    store = FileObjectStore(tmp_path / "store")

    with pytest.raises(IntegrityError, match="candidate-source"):
        run_source_candidate_gate(
            store=store,
            repository_url=str(source_root),
            repository="danielcanfly/knowledge-source",
            source_commit_sha=source_sha,
            foundation_commit_sha="d" * 40,
            channel="production",
            release_time=datetime(2026, 7, 2, 10, 15, tzinfo=UTC),
            query="quartz lantern protocol",
            work_root=tmp_path / "work",
        )
