from __future__ import annotations

import pytest

from knowledge_engine.m26_admin_contract import AdminAPIError
from knowledge_engine.m26_admin_ingestion_core import ReadObservation
from knowledge_engine.m26_admin_ingestion_sync import (
    DeterministicSyncIngestionAdapter,
    SyncBlogRequest,
    build_index_health,
    build_sync_plan,
    require_sync_adapter,
)


def _digest(char: str) -> str:
    return char * 64


def test_sync_plan_is_deterministic_and_classifies_full_manifest_diff() -> None:
    documents = [
        {"document_id": "added", "digest": _digest("a")},
        {"document_id": "changed", "digest": _digest("b")},
        {"document_id": "same", "digest": _digest("c")},
    ]
    active = {
        "changed": _digest("d"),
        "same": _digest("c"),
        "removed": _digest("e"),
    }

    first = build_sync_plan(
        source_revision="source-42",
        documents=documents,
        active_document_digests=active,
    )
    second = build_sync_plan(
        source_revision="source-42",
        documents=list(reversed(documents)),
        active_document_digests=dict(reversed(list(active.items()))),
    )

    assert first == second
    assert first["plan"]["manifest_diff"] == {
        "added": ["added"],
        "changed": ["changed"],
        "removed": ["removed"],
        "unchanged": ["same"],
    }
    assert first["plan"]["requires_confirmation"] is True
    assert first["plan"]["verification"] == "vector_lexical_parity_required_before_finalize"


def test_add_only_sync_is_one_click_and_idempotent_at_manifest_level() -> None:
    adapter = DeterministicSyncIngestionAdapter(
        source_revision="source-1",
        documents=[{"document_id": "a", "digest": _digest("a")}],
        vector_chunk_ids=["a:0"],
        lexical_chunk_ids=["a:0"],
    )

    first = adapter.sync_blog("admop_first", SyncBlogRequest())
    second = adapter.sync_blog("admop_second", SyncBlogRequest())

    assert first["manifest_diff"]["added"] == ["a"]
    assert first["verification"]["id_parity"] is True
    assert second["manifest_diff"] == {
        "added": [],
        "changed": [],
        "removed": [],
        "unchanged": ["a"],
    }


def test_removed_or_unpublished_document_requires_digest_pinned_confirmation() -> None:
    adapter = DeterministicSyncIngestionAdapter(
        source_revision="source-2",
        documents=[],
        active_document_digests={"old": _digest("f")},
    )

    with pytest.raises(AdminAPIError) as preview:
        adapter.sync_blog("admop_remove", SyncBlogRequest())

    assert preview.value.status_code == 409
    assert preview.value.code == "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED"
    assert adapter.active_document_digests == {"old": _digest("f")}
    plan_digest = preview.value.details["plan_digest"]

    with pytest.raises(AdminAPIError) as unpinned:
        adapter.sync_blog("admop_remove_unpinned", SyncBlogRequest(confirmation=True))

    assert unpinned.value.status_code == 409
    assert unpinned.value.code == "ADMIN_INGESTION_PLAN_DIGEST_REQUIRED"
    assert adapter.active_document_digests == {"old": _digest("f")}

    result = adapter.sync_blog(
        "admop_remove_confirmed",
        SyncBlogRequest(confirmation=True, expected_plan_digest=plan_digest),
    )
    assert result["manifest_diff"]["removed"] == ["old"]
    assert result["plan_digest"] == plan_digest
    assert adapter.active_document_digests == {}


def test_destructive_confirmation_fails_closed_when_plan_changes_after_preview() -> None:
    adapter = DeterministicSyncIngestionAdapter(
        source_revision="source-3",
        documents=[],
        active_document_digests={"old": _digest("a")},
    )

    with pytest.raises(AdminAPIError) as preview:
        adapter.sync_blog("admop_preview", SyncBlogRequest())
    reviewed_digest = preview.value.details["plan_digest"]

    # Simulate a fresh active-index observation changing between preview and
    # confirmation. The second call must re-plan and refuse the stale approval.
    adapter.active_document_digests = {
        "old": _digest("a"),
        "newly_active": _digest("b"),
    }
    before = dict(adapter.active_document_digests)

    with pytest.raises(AdminAPIError) as stale:
        adapter.sync_blog(
            "admop_stale_confirm",
            SyncBlogRequest(
                confirmation=True,
                expected_plan_digest=reviewed_digest,
            ),
        )

    assert stale.value.status_code == 409
    assert stale.value.code == "ADMIN_INGESTION_STALE_PLAN"
    assert stale.value.details["expected_plan_digest"] == reviewed_digest
    assert stale.value.details["current_plan_digest"] != reviewed_digest
    assert adapter.active_document_digests == before
    assert adapter.jobs == []


def test_source_revision_change_also_invalidates_destructive_confirmation() -> None:
    adapter = DeterministicSyncIngestionAdapter(
        source_revision="source-before",
        documents=[],
        active_document_digests={"old": _digest("c")},
    )

    with pytest.raises(AdminAPIError) as preview:
        adapter.sync_blog("admop_preview_revision", SyncBlogRequest())
    reviewed_digest = preview.value.details["plan_digest"]

    adapter.source_revision = "source-after"

    with pytest.raises(AdminAPIError) as stale:
        adapter.sync_blog(
            "admop_stale_revision",
            SyncBlogRequest(
                confirmation=True,
                expected_plan_digest=reviewed_digest,
            ),
        )

    assert stale.value.code == "ADMIN_INGESTION_STALE_PLAN"
    assert adapter.active_document_digests == {"old": _digest("c")}
    assert adapter.jobs == []


def test_index_health_never_calls_unknown_dual_store_evidence_healthy() -> None:
    observation = ReadObservation(
        availability="available",
        data={"source_revision": "source-1", "document_count": 2},
        source="fixture",
    )

    health = build_index_health(observation)

    assert health.data["status"] == "unknown"
    assert "INDEX_DUAL_STORE_COUNTS_UNPROVEN" in health.data["issues"]
    assert "INDEX_ID_PARITY_UNPROVEN" in health.data["issues"]
    assert health.data["vector_lexical_parity"] is False


def test_index_health_requires_count_and_id_parity_for_healthy() -> None:
    observation = ReadObservation(
        availability="available",
        data={
            "source_revision": "source-1",
            "document_count": 1,
            "vector_chunk_count": 2,
            "lexical_chunk_count": 2,
            "vector_chunk_ids": ["a:0", "a:1"],
            "lexical_chunk_ids": ["a:1", "a:0"],
        },
        source="fixture",
    )

    health = build_index_health(observation)

    assert health.data["status"] == "healthy"
    assert health.data["vector_lexical_parity"] is True
    assert health.data["issues"] == []


def test_index_health_marks_mismatch_degraded() -> None:
    observation = ReadObservation(
        availability="available",
        data={
            "source_revision": "source-1",
            "document_count": 1,
            "vector_chunk_count": 2,
            "lexical_chunk_count": 1,
            "vector_chunk_ids": ["a:0", "a:1"],
            "lexical_chunk_ids": ["a:0"],
        },
        source="fixture",
    )

    health = build_index_health(observation)

    assert health.data["status"] == "degraded"
    assert "INDEX_CHUNK_COUNT_MISMATCH" in health.data["issues"]
    assert "INDEX_ID_PARITY_MISMATCH" in health.data["issues"]


def test_one_click_route_fails_closed_when_adapter_has_no_sync_actuator() -> None:
    with pytest.raises(AdminAPIError) as caught:
        require_sync_adapter(object())

    assert caught.value.status_code == 503
    assert caught.value.code == "ADMIN_INGESTION_SYNC_ADAPTER_UNQUALIFIED"
