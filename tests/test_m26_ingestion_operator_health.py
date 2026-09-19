from __future__ import annotations

from knowledge_engine import m26_ingestion_operator_health as operator_health_module
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


def _built_health(
    *,
    active_status: str = "healthy",
    source_status: str = "current",
    candidate_status: str = "unknown",
    candidate_issues: list[str] | None = None,
    running_jobs: list[dict[str, object]] | None = None,
) -> ReadObservation:
    candidate_issues = candidate_issues or []
    issues = list(candidate_issues)
    return ReadObservation(
        availability="available",
        source="sqlite_ingestion_health_authority",
        freshness="live",
        observed_at="2026-09-19T01:00:00Z",
        data={
            "schema_version": "m26-index-health/v2",
            "overall_status": "unknown" if candidate_issues else "healthy",
            "active_production_index": {
                "status": active_status,
                "issues": [] if active_status == "healthy" else ["ACTIVE_ISSUE"],
                "vector_lexical_parity": "proven" if active_status == "healthy" else "mismatch",
            },
            "candidate_index": {
                "status": candidate_status,
                "issues": candidate_issues,
            },
            "source_state": {
                "status": source_status,
                "issues": [] if source_status == "current" else ["SOURCE_ISSUE"],
                "diff_vs_active": {
                    "added": [],
                    "changed": [],
                    "removed": [],
                    "unchanged": ["article-a", "article-b"],
                },
            },
            "jobs": {
                "running": running_jobs or [],
                "last_successful": None,
                "last_failed": None,
                "retryable_failed_count": 0,
            },
            "promotion_readiness": {
                "status": "blocked" if candidate_issues else "not_ready",
                "candidate_only": True,
                "active_pointer_authorized": False,
                "blockers": candidate_issues,
            },
            "issues": issues,
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
    # Independent source-drift evidence may already make the overall state degraded.
    # Missing audit evidence must never erase that stronger signal or become healthy.
    assert health.data["overall_status"] != "healthy"


def test_historical_candidate_mismatch_does_not_pollute_operator_health(monkeypatch):
    built = _built_health(
        candidate_status="unknown",
        candidate_issues=["INDEX_CANDIDATE_PARITY_MISMATCH"],
    )
    monkeypatch.setattr(operator_health_module, "build_index_health", lambda _observation: built)

    health = build_operator_index_health(_observation())

    assert health.data["overall_status"] == "healthy"
    assert health.data["active_production_index"]["status"] == "healthy"
    assert health.data["source_state"]["status"] == "current"
    assert health.data["candidate_index"]["status"] == "unknown"
    assert "INDEX_CANDIDATE_PARITY_MISMATCH" in health.data["candidate_index"]["issues"]
    assert "INDEX_CANDIDATE_PARITY_MISMATCH" in health.data["issues"]


def test_genuine_active_degradation_still_fails_closed(monkeypatch):
    built = _built_health(active_status="degraded", candidate_status="absent")
    monkeypatch.setattr(operator_health_module, "build_index_health", lambda _observation: built)

    health = build_operator_index_health(_observation())

    assert health.data["overall_status"] == "degraded"


def test_genuine_source_drift_still_fails_closed(monkeypatch):
    built = _built_health(source_status="drifted", candidate_status="absent")
    monkeypatch.setattr(operator_health_module, "build_index_health", lambda _observation: built)

    health = build_operator_index_health(_observation())

    assert health.data["overall_status"] == "degraded"


def test_missing_active_audit_evidence_still_fails_closed_when_base_is_green(monkeypatch):
    built = _built_health(candidate_status="absent")
    monkeypatch.setattr(operator_health_module, "build_index_health", lambda _observation: built)

    health = build_operator_index_health(_observation(with_audit=False))

    assert health.data["overall_status"] == "unknown"
    assert health.data["active_production_index"]["status"] == "unknown"
    assert "INDEX_HEALTH_AUDIT_EVIDENCE_UNAVAILABLE" in health.data["issues"]


def test_running_candidate_remains_observable_without_downgrading_active_health(monkeypatch):
    running = [{"job_id": "job-running", "status": "RUNNING", "phase": "candidate_write"}]
    built = _built_health(
        candidate_status="building",
        candidate_issues=[],
        running_jobs=running,
    )
    monkeypatch.setattr(operator_health_module, "build_index_health", lambda _observation: built)

    health = build_operator_index_health(_observation())

    assert health.data["overall_status"] == "healthy"
    assert health.data["candidate_index"]["status"] == "building"
    assert health.data["jobs"]["running"] == running
