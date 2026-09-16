from __future__ import annotations

from knowledge_engine.m26_admin_ingestion_core import ReadObservation
from knowledge_engine.m26_ingestion_operator_health import build_operator_index_health


def _observation(*, with_audit: bool = True) -> ReadObservation:
    audit = (
        {
            "schema_version": "m26-index-health-audit/v1",
            "status": "healthy",
            "release_id": "release-active",
            "orphan_chunks": 0,
            "duplicate_chunks": 0,
            "malformed_metadata": 0,
            "embedding_mismatch": 0,
            "missing_vectors": 0,
            "chunk_order_mismatch": 0,
            "active_manifest_consistent": True,
            "vector_lexical_parity": "proven",
            "retrieval_smoke": "passed",
            "public_ask_successor_evidence": "passed",
            "issues": [],
        }
        if with_audit
        else None
    )
    active = {
        "release_id": "release-active",
        "manifest_key": "releases/release-active/manifest.json",
        "manifest_sha256": "a" * 64,
        "production_manifest_key": "releases/release-active/production.json",
        "production_manifest_sha256": "b" * 64,
        "source_revision": "c" * 40,
        "qdrant_collection": "collection-active",
        "document_count": 2,
        "document_digests": {"article-a": "d" * 64, "article-b": "e" * 64},
        "lexical_chunk_count": 4,
        "vector_chunk_count": 4,
        "parity_basis": "manifest_counts",
    }
    if audit is not None:
        active["health_audit"] = audit
    return ReadObservation(
        availability="available",
        source="sqlite_ingestion_health_authority",
        freshness="live",
        observed_at="2026-09-16T12:00:00Z",
        data={
            "schema_version": "m26-index-health-evidence/v1",
            "active": active,
            "active_error": None,
            "source": {
                "source_revision": "git:" + "f" * 40,
                "source_identity_digest": "1" * 64,
                "documents": [
                    {"document_id": "article-a", "digest": "d" * 64},
                    {"document_id": "article-b", "digest": "9" * 64},
                    {"document_id": "article-c", "digest": "8" * 64},
                ],
            },
            "source_error": None,
            "jobs": [],
            "candidate_job": None,
            "candidate_manifest": None,
            "candidate_manifest_error": None,
            "missing_seams": [],
            "finalization_authorized": False,
            "finalization_mode": "blocked",
            "production_activation_authorized": False,
        },
    )


def test_projects_real_operator_health_counts_from_qualified_evidence():
    health = build_operator_index_health(_observation())

    active = health.data["active_production_index"]
    source = health.data["source_state"]

    assert active["orphan_chunks"] == 0
    assert active["duplicate_chunks"] == 0
    assert active["malformed_metadata"] == 0
    assert active["embedding_mismatch"] == 0
    assert active["missing_vectors"] == 0
    assert active["chunk_order_mismatch"] == 0
    assert active["active_manifest_consistent"] is True
    assert active["retrieval_smoke"] == "passed"
    assert active["public_ask_successor_evidence"] == "passed"
    assert active["vector_lexical_parity"] == "proven"
    assert source["missing_articles"] == 1
    assert source["stale_sources"] == 1


def test_missing_audit_evidence_never_becomes_fake_zero_health():
    health = build_operator_index_health(_observation(with_audit=False))

    active = health.data["active_production_index"]
    assert active["orphan_chunks"] is None
    assert active["duplicate_chunks"] is None
    assert active["malformed_metadata"] is None
    assert active["embedding_mismatch"] is None
    assert "INDEX_HEALTH_AUDIT_EVIDENCE_UNAVAILABLE" in active["issues"]
    assert health.data["overall_status"] == "unknown"
