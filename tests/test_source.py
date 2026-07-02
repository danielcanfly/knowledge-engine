from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.source import build_source_release, checkout_source


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_source(root: Path, *, policy_value: str = "reviewed") -> str:
    (root / "bundle/concepts").mkdir(parents=True, exist_ok=True)
    (root / "provenance").mkdir(parents=True, exist_ok=True)
    (root / "policy").mkdir(parents=True, exist_ok=True)
    (root / "bundle/index.md").write_text(
        "# Knowledge Source\n\n- [Compiler](concepts/compiler.md)\n",
        encoding="utf-8",
    )
    (root / "bundle/concepts/compiler.md").write_text(
        """---
type: Concept
title: Source Compiler
description: Builds exact reviewed source commits.
timestamp: 2026-07-02T08:00:00Z
x-kos-id: ko_01JXYZ123456789ABCDEFGHJKM
x-kos-status: published
x-kos-audience: internal
x-kos-confidence: 0.98
x-kos-provenance: provenance/compiler.json
x-kos-review:
  status: approved
  reviewer: daniel
  reviewed_at: 2026-07-02T08:00:00Z
---
# Source Compiler

The Builder verifies an exact source commit before compilation.
""",
        encoding="utf-8",
    )
    (root / "provenance/compiler.json").write_text(
        json.dumps(
            {
                "subject": {"concept_id": "concepts/compiler"},
                "sources": [
                    {
                        "source_id": "source_m3_contract",
                        "uri": "https://github.com/danielcanfly/knowledge-os-foundation/issues/3",
                        "retrieved_at": "2026-07-02T08:00:00Z",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "policy/source-policy.json").write_text(
        json.dumps({"status": policy_value}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", f"source: {policy_value}")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def source_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.name", "Knowledge Source Test")
    _git(root, "config", "user.email", "source@example.invalid")
    sha = _commit_source(root)
    return root, sha


def test_build_source_release_is_exact_and_reproducible(
    tmp_path: Path, source_repo: tuple[Path, str]
) -> None:
    root, sha = source_repo
    release_time = datetime(2026, 7, 2, 8, 30, tzinfo=UTC)

    first, first_snapshot = build_source_release(
        repository_url=str(root),
        repository="danielcanfly/knowledge-source",
        source_commit_sha=sha,
        foundation_commit_sha="d" * 40,
        work_root=tmp_path / "first",
        release_time=release_time,
    )
    second, second_snapshot = build_source_release(
        repository_url=str(root),
        repository="danielcanfly/knowledge-source",
        source_commit_sha=sha,
        foundation_commit_sha="d" * 40,
        work_root=tmp_path / "second",
        release_time=release_time,
    )

    assert first.release_id == second.release_id
    assert first_snapshot == second_snapshot
    assert first.manifest == second.manifest
    assert first.manifest["source"]["commit_sha"] == sha
    assert first.manifest["source"]["snapshot_sha256"] == first_snapshot[
        "content_sha256"
    ]
    assert any(
        item["kind"] == "source_snapshot" for item in first.manifest["artifacts"]
    )
    assert (
        first.release_root / "artifacts/source-snapshot.json"
    ).read_bytes() == (
        second.release_root / "artifacts/source-snapshot.json"
    ).read_bytes()


def test_source_policy_change_changes_release_identity(
    tmp_path: Path, source_repo: tuple[Path, str]
) -> None:
    root, first_sha = source_repo
    release_time = datetime(2026, 7, 2, 8, 30, tzinfo=UTC)
    first, first_snapshot = build_source_release(
        repository_url=str(root),
        repository="danielcanfly/knowledge-source",
        source_commit_sha=first_sha,
        foundation_commit_sha="d" * 40,
        work_root=tmp_path / "first",
        release_time=release_time,
    )

    second_sha = _commit_source(root, policy_value="approved")
    second, second_snapshot = build_source_release(
        repository_url=str(root),
        repository="danielcanfly/knowledge-source",
        source_commit_sha=second_sha,
        foundation_commit_sha="d" * 40,
        work_root=tmp_path / "second",
        release_time=release_time,
    )

    assert first_snapshot["content_sha256"] != second_snapshot["content_sha256"]
    assert first.release_id != second.release_id


def test_checkout_rejects_non_exact_source_sha(
    tmp_path: Path, source_repo: tuple[Path, str]
) -> None:
    root, sha = source_repo
    with pytest.raises(IntegrityError, match="exact 40-character"):
        checkout_source(
            repository_url=str(root),
            repository="danielcanfly/knowledge-source",
            commit_sha=sha[:12],
            checkout_root=tmp_path / "checkout",
        )
