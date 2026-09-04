from __future__ import annotations

import pytest

from knowledge_engine.m26_admin_contract import AdminAPIError
from knowledge_engine.m26_admin_corpus import CorpusReadService, reconcile_corpus


def snapshot(*, sources=None, artifacts=None, vectors=None, active="release-2", warnings=None):
    return {
        "sources": sources or [],
        "artifacts": artifacts or [],
        "vectors": vectors or [],
        "active_release_marker": active,
        "warnings": warnings or [],
    }


def test_corpus_happy_path_preserves_source_and_active_release_identity():
    rows = reconcile_corpus(snapshot(
        sources=[{"source_id": "s1", "source_path": "posts/a.md", "canonical_url": "https://example/a", "source_revision": "r2"}],
        artifacts=[{"source_id": "s1", "artifact_markdown": "r2/a.md", "embedding_text": "r2/a.txt", "manifest_record": "m:s1", "release_marker": "release-2", "source_revision": "r2", "materialized_at": "2026-09-04T00:00:00Z"}],
        vectors=[{"source_id": "s1", "vector_presence": True, "vector_backend": "qdrant", "release_marker": "release-2", "indexed_at": "2026-09-04T00:01:00Z"}],
    ))
    assert rows == [{
        "source_id": "s1", "source_path": "posts/a.md", "canonical_url": "https://example/a", "source_revision": "r2",
        "artifact_markdown": "r2/a.md", "embedding_text": "r2/a.txt", "metadata_json": None, "manifest_record": "m:s1",
        "vector_backend": "qdrant", "vector_presence": True, "active_release_marker": "release-2",
        "materialized_at": "2026-09-04T00:00:00Z", "indexed_at": "2026-09-04T00:01:00Z",
        "missing": [], "stale": False, "reasons": [],
    }]


def test_missing_semantic_payload_is_materialize_failure_not_vector_success():
    row = reconcile_corpus(snapshot(
        sources=[{"source_id": "s1", "source_path": "posts/a.md"}],
        artifacts=[{"source_id": "s1", "artifact_markdown": "a.md", "manifest_record": "m:s1", "release_marker": "release-2"}],
        vectors=[{"source_id": "s1", "vector_presence": True, "release_marker": "release-2"}],
    ))[0]
    assert "embedding_text" in row["missing"]
    assert "CORPUS_MATERIALIZE_SEMANTIC_PAYLOAD_MISSING" in row["reasons"]
    assert row["vector_presence"] is True


def test_release_mismatch_is_stale_and_explainable():
    row = reconcile_corpus(snapshot(
        sources=[{"source_id": "s1", "source_path": "posts/a.md"}],
        artifacts=[{"source_id": "s1", "artifact_markdown": "a.md", "embedding_text": "a.txt", "manifest_record": "m:s1", "release_marker": "release-1"}],
        vectors=[{"source_id": "s1", "vector_presence": True, "release_marker": "release-1"}],
    ))[0]
    assert row["stale"] is True
    assert "CORPUS_ACTIVE_RELEASE_MISMATCH" in row["reasons"]


def test_deleted_source_leaves_explicit_orphan_identity():
    row = reconcile_corpus(snapshot(
        artifacts=[{"source_id": "deleted", "source_path": "posts/deleted.md", "artifact_markdown": "deleted.md", "embedding_text": "deleted.txt", "manifest_record": "m:deleted"}],
        vectors=[{"source_id": "deleted", "vector_presence": True}],
    ))[0]
    assert "source" in row["missing"]
    assert "CORPUS_ORPHANED_ARTIFACT" in row["reasons"]


def test_duplicate_slug_is_visible_for_both_source_rows():
    rows = reconcile_corpus(snapshot(sources=[
        {"source_id": "old", "source_path": "posts/a.md"},
        {"source_id": "new", "source_path": "drafts/a.md"},
    ]))
    assert all("CORPUS_DUPLICATE_SLUG" in row["reasons"] for row in rows)


def test_rename_does_not_silently_collapse_old_artifact_into_new_source():
    rows = reconcile_corpus(snapshot(
        sources=[{"source_id": "new", "source_path": "posts/new-name.md"}],
        artifacts=[{"source_id": "old", "source_path": "posts/old-name.md", "artifact_markdown": "old.md", "embedding_text": "old.txt", "manifest_record": "m:old"}],
    ))
    assert {row["source_id"] for row in rows} == {"new", "old"}
    old = next(row for row in rows if row["source_id"] == "old")
    assert "CORPUS_ORPHANED_ARTIFACT" in old["reasons"]


class BoomAdapter:
    def read(self, *, task_id=None):
        raise RuntimeError("r2 down")


class MalformedAdapter:
    def read(self, *, task_id=None):
        return []


def test_adapter_failure_is_unavailable_not_empty_success():
    with pytest.raises(AdminAPIError) as exc:
        CorpusReadService(BoomAdapter()).list()
    assert exc.value.status_code == 503
    assert exc.value.code == "ADMIN_CORPUS_ADAPTER_FAILURE"


def test_malformed_adapter_is_unavailable_not_empty_success():
    with pytest.raises(AdminAPIError) as exc:
        CorpusReadService(MalformedAdapter()).list()
    assert exc.value.status_code == 503
    assert exc.value.code == "ADMIN_CORPUS_ADAPTER_MALFORMED"
