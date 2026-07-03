from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from knowledge_engine.errors import IntegrityError
from knowledge_engine.resolution import _verify_source
from knowledge_engine.review import (
    ReviewDecisionRequest,
    SourcePackageRequest,
    materialize_source_package,
    record_review_decision,
)
from knowledge_engine.storage import FileObjectStore

CAPTURE = "capture_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SYNTHESIS = "syn_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RESOLUTION = "res_cccccccccccccccccccccccccccccccc"
CLAIM = "Every approved claim keeps exact evidence provenance."


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _source(tmp_path: Path, existing: bool = False) -> tuple[Path, str, str]:
    root = tmp_path / "source"
    for name in ("bundle/concepts", "provenance", "registry", "policy"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "bundle/index.md").write_text("# Source\n", encoding="utf-8")
    sources: list[dict] = []
    reviews: list[dict] = []
    if existing:
        (root / "bundle/concepts/existing.md").write_text(
            "---\n"
            "type: Concept\n"
            "title: Existing concept\n"
            "description: Existing governed knowledge.\n"
            "timestamp: 2026-07-03T00:00:00Z\n"
            "x-kos-id: ko_01JTEST0000000000000000000\n"
            "x-kos-status: published\n"
            "x-kos-audience: internal\n"
            "x-kos-confidence: 0.9\n"
            "x-kos-provenance: provenance/existing.json\n"
            "x-kos-review:\n"
            "  review_id: review_existing\n"
            "  status: approved\n"
            "---\n# Existing concept\n\nExisting governed knowledge.\n",
            encoding="utf-8",
        )
        (root / "provenance/existing.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "subject": {
                        "concept_id": "concepts/existing",
                        "x_kos_id": "ko_01JTEST0000000000000000000",
                    },
                    "sources": [
                        {
                            "source_id": "source_existing",
                            "uri": "urn:existing",
                            "retrieved_at": "2026-07-03T00:00:00Z",
                        }
                    ],
                    "method": "manual",
                    "confidence": 0.9,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        sources.append(
            {
                "source_id": "source_existing",
                "title": "Existing",
                "uri": "urn:existing",
                "kind": "markdown",
                "trust": "reviewed",
                "status": "active",
                "audience": "internal",
                "owner": "test",
                "license": "test-only",
                "content_sha256": "1" * 64,
            }
        )
        reviews.append(
            {
                "review_id": "review_existing",
                "concept_id": "concepts/existing",
                "reviewer": "reviewer",
                "reviewed_at": "2026-07-03T00:00:00Z",
                "status": "approved",
                "approved_audience": "internal",
                "notes": "Existing review.",
            }
        )
    (root / "registry/sources.json").write_text(
        json.dumps({"schema_version": "1.0", "sources": sources}) + "\n",
        encoding="utf-8",
    )
    (root / "registry/reviews.json").write_text(
        json.dumps({"schema_version": "1.0", "reviews": reviews}) + "\n",
        encoding="utf-8",
    )
    (root / "policy/source-policy.json").write_text("{}\n", encoding="utf-8")
    (root / "policy/promotion-policy.json").write_text("{}\n", encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    sha = _git(root, "rev-parse", "HEAD")
    _, snapshot = _verify_source(root, sha)
    return root, sha, snapshot


def _put(store: FileObjectStore, key: str, value: dict) -> None:
    store.put(key, (json.dumps(value) + "\n").encode(), content_type="application/json")


def _seed(
    store: FileObjectStore,
    sha: str,
    snapshot: str,
    *,
    action: str = "create",
    status: str = "pending_human_review",
    audience: str = "internal",
) -> None:
    _put(
        store,
        f"raw/captures/{CAPTURE}.json",
        {
            "capture_id": CAPTURE,
            "request": {
                "source_id": "source_review_test",
                "source_uri": "urn:review:test",
                "title": "Reviewed source",
                "kind": "markdown",
                "audience": audience,
                "retrieved_at": "2026-07-03T10:20:00Z",
                "owner": "test-owner",
                "license": "test-only",
            },
            "raw_blob_key": "raw/blob",
            "raw_sha256": "2" * 64,
            "normalized_key": "normalized/doc.md",
            "normalized_sha256": "3" * 64,
            "canonical_write_permitted": False,
        },
    )
    _put(
        store,
        f"review/syntheses/{SYNTHESIS}/synthesis-record.json",
        {
            "synthesis_id": SYNTHESIS,
            "capture_id": CAPTURE,
            "status": "pending_human_review",
            "canonical_write_permitted": False,
        },
    )
    claim = {
        "claim_id": "claim_review_test",
        "text": CLAIM,
        "evidence": [{"start_char": 0, "end_char": len(CLAIM), "quote": CLAIM}],
    }
    _put(
        store,
        f"review/syntheses/{SYNTHESIS}/model-output.json",
        {
            "title": "Reviewed knowledge concept",
            "summary": "A human-reviewed evidence-bound concept.",
            "claims": [claim],
        },
    )
    _put(
        store,
        f"review/syntheses/{SYNTHESIS}/draft/claim-provenance.json",
        {"synthesis_id": SYNTHESIS, "capture_id": CAPTURE, "claims": [claim]},
    )
    targets = ["concepts/existing"] if action in {"update", "alias", "merge"} else []
    _put(
        store,
        f"review/resolutions/{RESOLUTION}/resolution-record.json",
        {
            "resolution_id": RESOLUTION,
            "request": {
                "source_commit_sha": sha,
                "source_repository": "danielcanfly/knowledge-source",
            },
            "source_snapshot_sha256": snapshot,
            "action": action,
            "status": status,
            "canonical_write_permitted": False,
        },
    )
    _put(
        store,
        f"review/resolutions/{RESOLUTION}/proposed-action.json",
        {
            "resolution_id": RESOLUTION,
            "synthesis_id": SYNTHESIS,
            "action": action,
            "status": status,
            "target_concept_ids": targets,
            "effective_audience": audience,
            "canonical_write_permitted": False,
        },
    )
    candidates = (
        [{"concept_id": "concepts/existing", "path": "bundle/concepts/existing.md"}]
        if targets
        else []
    )
    _put(
        store,
        f"review/resolutions/{RESOLUTION}/candidate-index.json",
        {"resolution_id": RESOLUTION, "candidates": candidates},
    )


def _decide(tmp_path: Path, store: FileObjectStore, audience: str = "internal"):
    return record_review_decision(
        store=store,
        request=ReviewDecisionRequest(
            resolution_id=RESOLUTION,
            decision="approved",
            reviewer="human-reviewer",
            reviewed_at="2026-07-03T10:22:00Z",
            notes="Reviewed evidence, claims, resolution, and audience.",
            approved_audience=audience,
        ),
        output_dir=tmp_path / "decision",
    )


def _package(tmp_path: Path, store: FileObjectStore, decision_id: str, root: Path, sha: str):
    return materialize_source_package(
        store=store,
        request=SourcePackageRequest(
            decision_id=decision_id,
            source_repository="danielcanfly/knowledge-source",
            source_commit_sha=sha,
            package_version="source-package-v1",
            actor="package-builder",
            packaged_at="2026-07-03T10:23:00Z",
        ),
        source_root=root,
        output_dir=tmp_path / "package",
    )


def test_approval_replay_and_create_package(tmp_path: Path) -> None:
    root, sha, snapshot = _source(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    _seed(store, sha, snapshot)
    first = _decide(tmp_path, store)
    second = _decide(tmp_path, store)
    package = _package(tmp_path, store, first.decision_id, root, sha)

    assert first.source_package_permitted is True
    assert first.idempotent is False
    assert second.idempotent is True
    assert package.source_file_count == 4
    assert package.direct_apply_permitted is False
    assert _git(root, "status", "--porcelain") == ""
    concept = tmp_path / "package/payload/bundle/concepts/reviewed-knowledge-concept.md"
    text = concept.read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    metadata = yaml.safe_load(text[4:end])
    assert metadata["x-kos-status"] == "published"
    assert metadata["x-kos-review"]["status"] == "approved"
    assert CLAIM in text


def test_conflict_security_and_acl_downgrade_are_blocked(tmp_path: Path) -> None:
    for index, (action, status, audience, approved) in enumerate(
        [
            ("conflict", "pending_conflict_review", "internal", "internal"),
            ("create", "pending_security_review", "restricted", "restricted"),
            ("create", "pending_human_review", "restricted", "public"),
        ]
    ):
        case = tmp_path / str(index)
        case.mkdir()
        root, sha, snapshot = _source(case)
        store = FileObjectStore(case / "store")
        _seed(store, sha, snapshot, action=action, status=status, audience=audience)
        message = "only pending_human_review" if status != "pending_human_review" else "cannot downgrade"
        with pytest.raises(IntegrityError, match=message):
            _decide(case, store, approved)


def test_update_and_alias_preserve_existing_kos_identity(tmp_path: Path) -> None:
    for action in ("update", "alias"):
        case = tmp_path / action
        case.mkdir()
        root, sha, snapshot = _source(case, existing=True)
        store = FileObjectStore(case / "store")
        _seed(store, sha, snapshot, action=action)
        decision = _decide(case, store)
        _package(case, store, decision.decision_id, root, sha)
        text = (case / "package/payload/bundle/concepts/existing.md").read_text()
        end = text.find("\n---\n", 4)
        metadata = yaml.safe_load(text[4:end])
        assert metadata["x-kos-id"] == "ko_01JTEST0000000000000000000"
        if action == "alias":
            assert "Reviewed knowledge concept" in metadata["aliases"]
        else:
            assert CLAIM in text


def test_rejected_decision_and_dirty_source_cannot_package(tmp_path: Path) -> None:
    root, sha, snapshot = _source(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    _seed(store, sha, snapshot)
    rejected = record_review_decision(
        store=store,
        request=ReviewDecisionRequest(
            resolution_id=RESOLUTION,
            decision="rejected",
            reviewer="human-reviewer",
            reviewed_at="2026-07-03T10:22:00Z",
            notes="Rejected after evidence review.",
        ),
        output_dir=tmp_path / "rejected",
    )
    with pytest.raises(IntegrityError, match="only approved decisions"):
        _package(tmp_path, store, rejected.decision_id, root, sha)

    approved = _decide(tmp_path, store)
    (root / "bundle/index.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="source checkout is dirty"):
        _package(tmp_path, store, approved.decision_id, root, sha)
