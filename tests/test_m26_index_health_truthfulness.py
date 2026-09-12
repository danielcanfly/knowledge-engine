from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminActor, AdminAPIError
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_ingestion import install_admin_ingestion_routes
from knowledge_engine.m26_admin_ingestion_core import ReadObservation
from knowledge_engine.m26_admin_ingestion_sync import build_index_health
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    build_sqlite_ingestion_adapter,
    candidate_manifest_observer_from_store,
    dynamic_source_observer_from_path,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes


def _documents(count: int = 2) -> list[dict[str, str]]:
    return [
        {
            "document_id": f"article-{index:03d}",
            "digest": hashlib.sha256(str(index).encode()).hexdigest(),
        }
        for index in range(count)
    ]


def _source(
    documents: list[dict[str, str]] | None = None, *, identity: str = "s" * 64
) -> dict[str, Any]:
    rows = documents if documents is not None else _documents()
    return {
        "source_revision": "git:" + "1" * 40,
        "source_identity_digest": identity,
        "documents": rows,
    }


def _active(
    documents: list[dict[str, str]] | None = None,
    *,
    lexical: int | None = 2,
    vector: int | None = 2,
    parity_basis: str | None = "manifest_counts",
) -> dict[str, Any]:
    rows = documents if documents is not None else _documents()
    return {
        "release_id": "active-release",
        "production_manifest_key": "releases/active-release/promotion/production-manifest.json",
        "production_manifest_sha256": "a" * 64,
        "manifest_key": "releases/active-release/manifest.json",
        "manifest_sha256": "b" * 64,
        "source_revision": "1" * 40,
        "document_digests": {row["document_id"]: row["digest"] for row in rows},
        "document_count": len(rows),
        "lexical_chunk_count": lexical,
        "vector_chunk_count": vector,
        "parity_basis": parity_basis,
        "qdrant_collection": "m26_blog_active_release",
    }


def _candidate_job(*, status: str = "SUCCEEDED", identity: str = "s" * 64) -> dict[str, Any]:
    receipt = {
        "schema_version": "m26-ingestion-candidate-write-receipt/v1",
        "status": "candidate_release_finalized",
        "release_id": "candidate-release",
        "manifest_key": "releases/candidate-release/manifest.json",
        "manifest_sha256": "c" * 64,
        "qdrant_collection": "m26_blog_candidate_release",
        "lexical_document_count": 2,
        "semantic_document_count": 2,
        "vector": {
            "point_count": 2,
            "section_id_count": 2,
            "detail": {"full_readback": True},
        },
        "authority": {"candidate_only": True, "production_pointer_writes": 0},
    }
    return {
        "job_id": "syncjob-candidate",
        "operation_id": "admop-candidate",
        "status": status,
        "phase": "finalize" if status == "SUCCEEDED" else "scan",
        "progress": 100 if status == "SUCCEEDED" else 20,
        "attempt": 1,
        "plan_id": "syncplan-candidate",
        "plan_digest": "d" * 64,
        "source_revision": "git:" + "1" * 40,
        "source_identity_digest": identity,
        "candidate_release_id": "candidate-release" if status == "SUCCEEDED" else None,
        "candidate_manifest_key": receipt["manifest_key"] if status == "SUCCEEDED" else None,
        "candidate_manifest_sha256": receipt["manifest_sha256"] if status == "SUCCEEDED" else None,
        "result": receipt if status == "SUCCEEDED" else None,
        "error_code": "INJECTED_FAILURE" if status == "FAILED" else None,
        "created_at": "2026-09-09T00:00:00Z",
        "updated_at": "2026-09-09T00:01:00Z",
        "completed_at": "2026-09-09T00:01:00Z" if status in {"SUCCEEDED", "FAILED"} else None,
    }


def _candidate_manifest(documents: list[dict[str, str]] | None = None) -> dict[str, Any]:
    job = _candidate_job()
    return {
        "verified": True,
        "manifest_key": job["candidate_manifest_key"],
        "manifest_sha256": job["candidate_manifest_sha256"],
        "manifest": {
            "schema_version": "knowledge-engine-release/v1",
            "release_id": "candidate-release",
            "status": "candidate",
            "qdrant_collection": "m26_blog_candidate_release",
            "counts": {"lexical_documents": 2, "semantic_documents": 2},
            "authority": {
                "candidate_only": True,
                "production_pointer_authorized": False,
            },
        },
        "document_digests": {
            row["document_id"]: row["digest"] for row in (documents or _documents())
        },
    }


def _health(
    *,
    active: dict[str, Any] | None = None,
    active_error: dict[str, str] | None = None,
    source: dict[str, Any] | None = None,
    source_error: dict[str, str] | None = None,
    jobs: list[dict[str, Any]] | None = None,
    candidate_job: dict[str, Any] | None = None,
    candidate_manifest: dict[str, Any] | None = None,
    candidate_error: dict[str, str] | None = None,
    missing_seams: list[str] | None = None,
    finalization_authorized: bool = False,
) -> dict[str, Any]:
    observation = ReadObservation(
        availability="partial" if active_error or source_error or candidate_error else "available",
        data={
            "schema_version": "m26-index-health-evidence/v1",
            "active": _active() if active is None and active_error is None else active,
            "active_error": active_error,
            "source": _source() if source is None and source_error is None else source,
            "source_error": source_error,
            "jobs": jobs or [],
            "candidate_job": candidate_job,
            "candidate_manifest": candidate_manifest,
            "candidate_manifest_error": candidate_error,
            "missing_seams": missing_seams or [],
            "finalization_authorized": finalization_authorized,
        },
        source="truth-fixture",
        observed_at="2026-09-09T00:02:00Z",
        freshness="live",
        resource_identity={"fixture": "truth"},
    )
    return build_index_health(observation).data


@pytest.mark.parametrize(
    ("active", "active_error", "status", "parity", "issue"),
    [
        (_active(), None, "healthy", "proven", None),
        (None, {"reason_code": "ACTIVE_DOWN"}, "unavailable", "unproven", "ACTIVE_DOWN"),
        (
            _active(lexical=None, vector=None, parity_basis=None),
            None,
            "unknown",
            "unproven",
            "INDEX_DUAL_STORE_COUNTS_UNPROVEN",
        ),
        (_active(lexical=2, vector=3), None, "degraded", "mismatch", "INDEX_CHUNK_COUNT_MISMATCH"),
    ],
)
def test_active_production_truth_never_upgrades_missing_or_mismatched_evidence(
    active: dict[str, Any] | None,
    active_error: dict[str, str] | None,
    status: str,
    parity: str,
    issue: str | None,
) -> None:
    health = _health(active=active, active_error=active_error)
    observed = health["active_production_index"]
    assert observed["status"] == status
    assert observed["vector_lexical_parity"] == parity
    assert (issue in observed["issues"]) if issue else observed["issues"] == []
    if status != "healthy":
        assert health["overall_status"] != "healthy"


def test_matching_counts_without_active_immutable_identity_remain_unknown() -> None:
    active = _active()
    active["production_manifest_sha256"] = None
    health = _health(active=active)
    assert health["active_production_index"]["status"] == "unknown"
    assert "INDEX_ACTIVE_IDENTITY_UNPROVEN" in health["active_production_index"]["issues"]
    assert health["overall_status"] != "healthy"


@pytest.mark.parametrize(
    ("job", "status"),
    [
        (None, "absent"),
        (_candidate_job(status="RUNNING"), "building"),
        (_candidate_job(status="FAILED"), "failed"),
    ],
)
def test_candidate_absent_building_and_failed_are_distinct_from_active(
    job: dict[str, Any] | None, status: str
) -> None:
    health = _health(jobs=[job] if job else [], candidate_job=job)
    candidate = health["candidate_index"]
    assert candidate["status"] == status
    assert candidate["is_active"] is False
    assert health["promotion_readiness"]["active_pointer_authorized"] is False


def test_verified_successful_candidate_is_ready_for_review_but_never_active() -> None:
    job = _candidate_job()
    health = _health(jobs=[job], candidate_job=job, candidate_manifest=_candidate_manifest())
    candidate = health["candidate_index"]
    assert candidate["status"] == "ready"
    assert candidate["vector_lexical_parity"] == "proven"
    assert candidate["is_active"] is False
    assert health["promotion_readiness"] == {
        "status": "ready_for_review",
        "candidate_only": True,
        "active_pointer_authorized": False,
        "blockers": [],
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, "candidate_ready"),
        ("FINALIZATION_READY", "finalization_ready"),
        ("FINALIZATION_BLOCKED", "finalization_blocked"),
        ("ACTIVE_SUCCESSOR", "active_successor"),
    ],
)
def test_index_health_distinguishes_finalization_truth_states(
    state: str | None,
    expected: str,
) -> None:
    job = _candidate_job(status="FAILED" if state == "FINALIZATION_BLOCKED" else "SUCCEEDED")
    job["finalization_state"] = state
    if state == "FINALIZATION_BLOCKED":
        job["candidate_release_id"] = "candidate-release"
        job["candidate_manifest_key"] = "releases/candidate-release/manifest.json"
        job["candidate_manifest_sha256"] = "c" * 64
        job["candidate_receipt"] = _candidate_job()["result"]
    active = _active()
    if state == "ACTIVE_SUCCESSOR":
        active["release_id"] = "candidate-release"
    health = _health(
        active=active,
        jobs=[job],
        candidate_job=job,
        candidate_manifest=_candidate_manifest(),
        finalization_authorized=True,
    )
    assert health["finalization"]["status"] == expected
    assert health["finalization"]["public_production_traffic_authorized"] is False


def test_index_health_finalization_unknown_is_explicit() -> None:
    health = _health(finalization_authorized=True)
    assert health["finalization"]["status"] == "unknown"


def test_source_equal_to_active_is_current_with_deterministic_noop_diff() -> None:
    health = _health()
    source = health["source_state"]
    assert source["status"] == "current"
    assert source["diff_vs_active"] == {
        "added": [],
        "changed": [],
        "removed": [],
        "unchanged": ["article-000", "article-001"],
    }
    assert source["requires_confirmation"] is False
    assert len(source["plan_digest_vs_active"]) == 64
    assert health["overall_status"] == "healthy"


@pytest.mark.parametrize("failure", ["missing_manifest", "unproven_parity", "mismatch"])
def test_success_does_not_imply_candidate_readiness_without_manifest_and_parity(
    failure: str,
) -> None:
    job = _candidate_job()
    manifest = _candidate_manifest()
    error = None
    if failure == "missing_manifest":
        manifest = None
        error = {"reason_code": "CANDIDATE_MANIFEST_MISSING"}
    elif failure == "unproven_parity":
        job["result"]["vector"] = {}
    else:
        job["result"]["vector"]["point_count"] = 3
    health = _health(
        jobs=[job],
        candidate_job=job,
        candidate_manifest=manifest,
        candidate_error=error,
    )
    assert health["candidate_index"]["status"] == "unknown"
    assert health["candidate_index"]["vector_lexical_parity"] != "proven"
    assert health["promotion_readiness"]["status"] == "blocked"


def test_candidate_manifest_cannot_claim_production_authority() -> None:
    job = _candidate_job()
    manifest = _candidate_manifest()
    manifest["manifest"]["authority"]["production_pointer_authorized"] = True
    health = _health(jobs=[job], candidate_job=job, candidate_manifest=manifest)
    assert health["candidate_index"]["status"] == "unknown"
    assert "INDEX_CANDIDATE_AUTHORITY_UNPROVEN" in health["candidate_index"]["issues"]
    assert health["candidate_index"]["is_active"] is False
    assert health["promotion_readiness"]["active_pointer_authorized"] is False


@pytest.mark.parametrize("change", ["added_181st", "changed", "removed"])
def test_source_diff_is_dynamic_and_preserves_destructive_confirmation_truth(change: str) -> None:
    active_documents = _documents(180 if change == "added_181st" else 2)
    source_documents = [dict(item) for item in active_documents]
    if change == "added_181st":
        source_documents.append({"document_id": "article-180", "digest": "e" * 64})
    elif change == "changed":
        source_documents[0]["digest"] = "f" * 64
    else:
        source_documents.pop()
    health = _health(
        active=_active(
            active_documents, lexical=len(active_documents), vector=len(active_documents)
        ),
        source=_source(source_documents),
    )
    state = health["source_state"]
    assert state["status"] == "drifted"
    assert state["document_count"] == len(source_documents)
    assert state["diff_vs_active"]["added"] == (["article-180"] if change == "added_181st" else [])
    assert state["diff_vs_active"]["changed"] == (["article-000"] if change == "changed" else [])
    assert state["diff_vs_active"]["removed"] == (["article-001"] if change == "removed" else [])
    assert state["requires_confirmation"] is (change == "removed")
    assert len(state["plan_digest_vs_active"]) == 64


def test_stale_candidate_and_source_observer_failure_are_explicit() -> None:
    stale_job = _candidate_job(identity="c" * 64)
    stale_documents = _documents()
    stale_documents[0]["digest"] = "f" * 64
    stale = _health(
        jobs=[stale_job],
        candidate_job=stale_job,
        candidate_manifest=_candidate_manifest(stale_documents),
    )
    assert stale["source_state"]["status"] == "drifted"
    assert "INDEX_CANDIDATE_SOURCE_STALE" in stale["source_state"]["issues"]
    assert stale["promotion_readiness"]["status"] == "blocked"

    unavailable = _health(source=None, source_error={"reason_code": "SOURCE_DOWN"})
    assert unavailable["source_state"]["status"] == "unavailable"
    assert unavailable["overall_status"] == "unavailable"


def _insert_job(
    ledger: SQLiteIngestionLedger,
    job_id: str,
    status: str,
    timestamp: str,
) -> None:
    ledger.create_job(
        {
            "job_id": job_id,
            "operation_id": "op-" + job_id,
            "actor_scope": "scope-" + job_id,
            "status": status,
            "created_at": timestamp,
            "attempt": 1,
        }
    )
    with ledger._connect() as db:
        db.execute(
            "UPDATE ingestion_jobs SET updated_at=?, completed_at=?, error_code=? WHERE job_id=?",
            (
                timestamp,
                timestamp if status in {"SUCCEEDED", "FAILED"} else None,
                "RETRYABLE" if status == "FAILED" else None,
                job_id,
            ),
        )


def test_durable_job_health_survives_reopen_and_orders_ties_deterministically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.sqlite3"
    ledger = SQLiteIngestionLedger(path)
    _insert_job(ledger, "running", "RUNNING", "2026-09-09T00:03:00Z")
    _insert_job(ledger, "success", "SUCCEEDED", "2026-09-09T00:02:00Z")
    _insert_job(ledger, "failed-b", "FAILED", "2026-09-09T00:01:00Z")
    _insert_job(ledger, "failed-a", "FAILED", "2026-09-09T00:01:00Z")
    reopened = SQLiteIngestionAdapter(
        SQLiteIngestionLedger(path),
        source_observer=lambda: _source(),
        active_manifest_observer=lambda: _active(),
    )
    health = build_index_health(reopened.current_index()).data
    assert [job["job_id"] for job in health["jobs"]["running"]] == ["running"]
    assert health["jobs"]["last_successful"]["job_id"] == "success"
    assert health["jobs"]["last_failed"]["job_id"] == "failed-a"
    assert health["jobs"]["retryable_failed_count"] == 2
    assert [job["job_id"] for job in reopened.ledger.list_jobs()][-2:] == ["failed-a", "failed-b"]


class _Authenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid":
            raise AdminAPIError(status_code=403, code="AUTH_INVALID", message="invalid")
        return AdminActor("owner", "owner", None, "human", "issuer", ("aud",))


class _Capabilities:
    def get_capability(self, _capability_id: str) -> object:
        return type(
            "Gate",
            (),
            {"effective_state": "enabled", "mutation_authorized": True, "reason_code": "TEST"},
        )()


class _Audit:
    def append(self, _event: object) -> None:
        return None


def test_index_health_endpoint_preserves_read_envelope_and_stable_v2_schema(
    tmp_path: Path,
) -> None:
    adapter = SQLiteIngestionAdapter(
        SQLiteIngestionLedger(tmp_path / "endpoint.sqlite3"),
        source_observer=lambda: _source(),
        active_manifest_observer=lambda: _active(),
    )
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=_Authenticator(),
        capability_provider=_Capabilities(),
        audit_sink=_Audit(),
        idempotency_store=adapter.ledger,
    )
    install_admin_ingestion_routes(app, adapter=adapter)
    response = TestClient(app).get(
        "/v1/admin/index/health",
        headers={
            "origin": "https://console.danielcanfly.com",
            "cf-access-jwt-assertion": "valid",
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["availability"]["status"] == "available"
    assert payload["provenance"]["source"] == "sqlite_ingestion_health_authority"
    assert payload["observed_at"] and payload["freshness"] == "live"
    assert payload["data"]["schema_version"] == "m26-index-health/v2"
    assert payload["data"]["mode"] == "candidate_only"


def test_runtime_missing_execution_seam_keeps_reads_but_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "read-authority.sqlite3"))
    adapter = build_sqlite_ingestion_adapter(
        source_observer=lambda: _source(),
        active_manifest_observer=lambda: _active(),
    )
    assert adapter is not None and not hasattr(adapter, "sync_blog")
    health = build_index_health(adapter.current_index())
    assert health.availability == "partial"
    assert health.data["active_production_index"]["status"] == "healthy"
    assert health.data["source_state"]["status"] == "current"
    assert health.data["overall_status"] == "degraded"
    assert health.data["promotion_readiness"]["active_pointer_authorized"] is False
    assert "INDEX_RUNTIME_SEAM_UNQUALIFIED:candidate_executor" in health.data["issues"]


def test_candidate_manifest_readback_is_exact_and_read_only(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "objects")
    release_id = "candidate-release"
    source_bytes = json.dumps({"documents": _documents()}, sort_keys=True).encode()
    source_key = f"releases/{release_id}/artifacts/source_documents.json"
    store.put(source_key, source_bytes, content_type="application/json", only_if_absent=True)
    manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "artifacts": [
            {"kind": "source_documents", "key": source_key, "sha256": sha256_bytes(source_bytes)}
        ],
        "counts": {"lexical_documents": 2, "semantic_documents": 2},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_key = f"releases/{release_id}/manifest.json"
    store.put(manifest_key, manifest_bytes, content_type="application/json", only_if_absent=True)
    before = sorted(
        path.relative_to(store.root).as_posix() for path in store.root.rglob("*") if path.is_file()
    )

    observed = candidate_manifest_observer_from_store(store)(
        manifest_key, sha256_bytes(manifest_bytes)
    )

    after = sorted(
        path.relative_to(store.root).as_posix() for path in store.root.rglob("*") if path.is_file()
    )
    assert observed["verified"] is True
    assert observed["document_digests"] == {
        row["document_id"]: row["digest"] for row in _documents()
    }
    assert before == after
    with pytest.raises(AdminAPIError, match="could not be verified"):
        candidate_manifest_observer_from_store(store)(manifest_key, "f" * 64)


def test_dynamic_source_observer_has_no_frozen_corpus_count(tmp_path: Path) -> None:
    root = tmp_path / "source"
    for index in range(181):
        path = root / "src/content/blog" / f"article-{index:03d}" / "en.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Article {index}\n", encoding="utf-8")
    observed = dynamic_source_observer_from_path(root)()
    assert len(observed["documents"]) == 181
    assert observed["documents"][-1]["document_id"] == "daniel_blog_en__article-180"
