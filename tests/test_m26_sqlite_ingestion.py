from __future__ import annotations

# Contract fixtures intentionally keep request/evidence literals compact.
# ruff: noqa: E501
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import (
    AdminActor,
    AdminAPIError,
    IdempotencyCoordinator,
    StatefulIdempotencyRecord,
    utc_now,
)
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_ingestion import install_admin_ingestion_routes
from knowledge_engine.m26_admin_ingestion_sync import SyncBlogRequest, build_sync_plan
from knowledge_engine.m26_ingestion_candidate_writer import CandidateVectorVerification
from knowledge_engine.m26_jobs_rollback_api import install_jobs_rollback_routes
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    build_sqlite_ingestion_adapter,
    candidate_executor_from_primitives,
    dynamic_source_observer_from_path,
)
from knowledge_engine.storage import FileObjectStore


class Authenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid":
            raise AdminAPIError(status_code=403, code="AUTH_INVALID", message="invalid")
        return AdminActor("owner", "owner", None, "human", "issuer", ("aud",))


class Capabilities:
    def get_capability(self, capability_id: str) -> object:
        return type(
            "Gate",
            (),
            {"effective_state": "enabled", "mutation_authorized": True, "reason_code": "TEST"},
        )()


class Audit:
    def append(self, event: object) -> None:
        del event


def _lease(ledger: SQLiteIngestionLedger, key: str = "sqlite-key-000001"):
    return IdempotencyCoordinator(ledger).begin_stateful(
        actor_id="owner",
        method="POST",
        path="/v1/admin/ingestion/sync",
        idempotency_key=key,
        request_payload={"confirmation": False, "expected_plan_digest": None},
    )


def _observers(source: dict[str, object], active: dict[str, object]):
    return (
        lambda: dict(source),
        lambda: dict(active),
    )


def test_sqlite_restart_and_wal_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ingestion.sqlite3"
    first = SQLiteIngestionLedger(path)
    now = utc_now()
    record = StatefulIdempotencyRecord("scope", "fp", "hash", "op", "IN_PROGRESS", 1, now, now)
    first.put_stateful_if_absent(record)
    reopened = SQLiteIngestionLedger(path)
    assert reopened.get_stateful("scope", "fp") == record
    assert reopened._connect().execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_same_key_conflict_and_independent_connection_duplicate_suppression(tmp_path: Path) -> None:
    path = tmp_path / "ingestion.sqlite3"
    first = SQLiteIngestionLedger(path)
    second = SQLiteIngestionLedger(path)
    coordinator_a = IdempotencyCoordinator(first)
    coordinator_b = IdempotencyCoordinator(second)
    leases = []
    errors = []

    def begin(coordinator: IdempotencyCoordinator) -> None:
        try:
            leases.append(
                coordinator.begin_stateful(
                    actor_id="owner",
                    method="POST",
                    path="/sync",
                    idempotency_key="duplicate-key-000001",
                    request_payload={"x": 1},
                )
            )
        except AdminAPIError as exc:
            errors.append(exc.code)

    threads = [
        threading.Thread(target=begin, args=(coordinator,))
        for coordinator in (coordinator_a, coordinator_b)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(leases) == 1
    assert errors == ["ADMIN_IDEMPOTENCY_IN_PROGRESS"]
    with pytest.raises(AdminAPIError, match="different request"):
        coordinator_a.begin_stateful(
            actor_id="owner",
            method="POST",
            path="/sync",
            idempotency_key="duplicate-key-000001",
            request_payload={"x": 2},
        )


def test_expired_running_lease_recovers_and_failed_retry_increments_once(tmp_path: Path) -> None:
    path = tmp_path / "ingestion.sqlite3"
    ledger = SQLiteIngestionLedger(path, lease_seconds=10)
    lease = _lease(ledger)
    ledger.create_job(
        {
            "job_id": "job-lease",
            "operation_id": lease.operation_id,
            "actor_scope": lease.scope,
            "idempotency_fingerprint": lease.key_fingerprint,
            "request_hash": lease.request_hash,
        }
    )
    ledger.claim_job("job-lease", owner=lease.operation_id, now=100.0, attempt=lease.attempt)
    assert ledger.recover_expired(now=111.0) == 1
    failed = ledger.get_job("job-lease")
    assert failed and failed["status"] == "FAILED"
    assert ledger.get_stateful(lease.scope, lease.key_fingerprint).state == "FAILED"
    retry = ledger.retry_failed_job("job-lease", owner="retry-owner", now=200.0)
    assert retry["status"] == "RUNNING" and retry["attempt"] == 2
    with pytest.raises(AdminAPIError, match="FAILED"):
        ledger.retry_failed_job("job-lease", owner="another", now=200.0)


def test_concurrent_failed_retry_serializes_across_independent_connections(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ingestion.sqlite3"
    ledger = SQLiteIngestionLedger(path)
    lease = _lease(ledger, "retry-key-000001")
    ledger.create_job(
        {
            "job_id": "job-retry",
            "operation_id": lease.operation_id,
            "actor_scope": lease.scope,
            "idempotency_fingerprint": lease.key_fingerprint,
            "request_hash": lease.request_hash,
        }
    )
    ledger.claim_job("job-retry", owner=lease.operation_id, now=0.0, attempt=1)
    ledger.complete_terminal(
        lease,
        job_id="job-retry",
        success=False,
        error={"code": "VECTOR_FAILED", "detail": "failed"},
    )
    first = SQLiteIngestionLedger(path)
    second = SQLiteIngestionLedger(path)
    results: list[object] = []

    def retry(owner: str) -> None:
        try:
            connection = first if owner == "a" else second
            results.append(connection.retry_failed_job("job-retry", owner=owner, now=100.0))
        except AdminAPIError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=retry, args=(owner,)) for owner in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(isinstance(result, dict) for result in results) == 1
    assert ledger.get_job("job-retry")["attempt"] == 2


def test_observer_failure_creates_visible_failed_job_before_substantive_work(
    tmp_path: Path,
) -> None:
    ledger = SQLiteIngestionLedger(tmp_path / "observer-failure.sqlite3")
    lease = _lease(ledger, "observer-failure-key1")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: (_ for _ in ()).throw(
            AdminAPIError(
                status_code=503,
                code="SOURCE_READ_FAILED",
                message="source unavailable",
            )
        ),
        active_manifest_observer=lambda: {},
    )
    with pytest.raises(AdminAPIError, match="source unavailable"):
        adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    jobs = adapter.list_jobs().data["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "FAILED"
    assert jobs[0]["error_code"] == "SOURCE_READ_FAILED"
    observed = adapter.get_job(jobs[0]["job_id"])
    assert observed.availability == "available"
    assert observed.data["status"] == "FAILED"


def test_active_observer_failure_creates_visible_failed_job(tmp_path: Path) -> None:
    ledger = SQLiteIngestionLedger(tmp_path / "active-observer-failure.sqlite3")
    lease = _lease(ledger, "active-observer-fail1")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: {
            "source_revision": "dynamic",
            "documents": [{"document_id": "a", "digest": "a"}],
        },
        active_manifest_observer=lambda: (_ for _ in ()).throw(
            AdminAPIError(
                status_code=503,
                code="ACTIVE_READ_FAILED",
                message="active unavailable",
            )
        ),
    )
    with pytest.raises(AdminAPIError, match="active unavailable"):
        adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    assert ledger.list_jobs()[0]["error_code"] == "ACTIVE_READ_FAILED"


def test_plan_failure_creates_visible_failed_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = SQLiteIngestionLedger(tmp_path / "plan-failure.sqlite3")
    lease = _lease(ledger, "plan-failure-key1")

    def fail_plan(**_kwargs: object) -> dict[str, object]:
        raise AdminAPIError(status_code=503, code="PLAN_BUILD_FAILED", message="plan failed")

    monkeypatch.setattr("knowledge_engine.m26_sqlite_ingestion.build_sync_plan", fail_plan)
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: {
            "source_revision": "dynamic",
            "documents": [{"document_id": "a", "digest": "a"}],
        },
        active_manifest_observer=lambda: {
            "manifest_key": "active",
            "manifest_sha256": "a" * 64,
            "document_digests": {},
        },
    )
    with pytest.raises(AdminAPIError, match="plan failed"):
        adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    assert ledger.list_jobs()[0]["error_code"] == "PLAN_BUILD_FAILED"


def test_failed_destructive_retry_replays_confirmation_and_plan_digest(tmp_path: Path) -> None:
    ledger = SQLiteIngestionLedger(tmp_path / "retry-payload.sqlite3")
    source = {"source_revision": "r1", "documents": [{"document_id": "new", "digest": "n"}]}
    active = {
        "manifest_key": "m1",
        "manifest_sha256": "msha1",
        "document_digests": {"old": "o"},
    }
    calls: list[dict[str, object]] = []

    def executor(
        _operation: str, request: SyncBlogRequest, _progress: object, context: dict[str, object]
    ):
        calls.append({"request": request.model_dump(), "plan": context["plan"]})
        if len(calls) == 1:
            raise RuntimeError("vector failed")
        return {"candidate_release_id": "candidate"}

    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=lambda: active,
        candidate_executor=executor,
    )
    plan = build_sync_plan(
        source_revision="r1",
        documents=source["documents"],
        active_document_digests=active["document_digests"],
    )
    request = SyncBlogRequest(confirmation=True, expected_plan_digest=plan["plan_digest"])
    lease = IdempotencyCoordinator(ledger).begin_stateful(
        actor_id="owner",
        method="POST",
        path="/sync",
        idempotency_key="destructive-retry-key2",
        request_payload=request.model_dump(),
    )
    with pytest.raises(RuntimeError):
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)
    job_id = "syncjob_" + lease.operation_id.removeprefix("admop_")
    failed = ledger.get_job(job_id)
    assert failed and failed["status"] == "FAILED"
    assert failed["request_payload"] == request.model_dump()
    result = adapter.retry_job(job_id, owner="retry-request")
    assert result["status"] == "SUCCEEDED"
    assert calls[1]["request"] == request.model_dump()
    assert calls[1]["plan"]["plan_digest"] == plan["plan_digest"]


def test_failed_stale_plan_retry_preserves_stale_digest_and_fails_again(tmp_path: Path) -> None:
    ledger = SQLiteIngestionLedger(tmp_path / "stale-retry.sqlite3")
    source = {"source_revision": "r1", "documents": []}
    active = {
        "manifest_key": "m1",
        "manifest_sha256": "msha1",
        "document_digests": {"removed": "old"},
    }
    request = SyncBlogRequest(confirmation=True, expected_plan_digest="f" * 64)
    lease = IdempotencyCoordinator(ledger).begin_stateful(
        actor_id="owner",
        method="POST",
        path="/sync",
        idempotency_key="stale-retry-key001",
        request_payload=request.model_dump(),
    )
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=lambda: active,
        candidate_executor=lambda *_args: pytest.fail("stale plan must not execute"),
    )
    with pytest.raises(AdminAPIError) as first:
        adapter.sync_blog_with_lease(lease.operation_id, request, lease)
    assert first.value.code == "ADMIN_INGESTION_STALE_PLAN"
    job_id = "syncjob_" + lease.operation_id.removeprefix("admop_")
    with pytest.raises(AdminAPIError) as retry:
        adapter.retry_job(job_id, owner="retry-owner")
    assert retry.value.code == "ADMIN_INGESTION_STALE_PLAN"
    failed = ledger.get_job(job_id)
    assert failed and failed["status"] == "FAILED" and failed["attempt"] == 2
    assert failed["request_payload"]["expected_plan_digest"] == "f" * 64


def test_dynamic_source_observer_and_runtime_factory_accept_181_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "blog-repository"
    content_root = source_root / "src/content/blog"
    content_root.mkdir(parents=True)
    for index in range(181):
        article = content_root / f"article-{index}"
        article.mkdir()
        (article / "en.md").write_text(f"# {index}\n", encoding="utf-8")
    observed = dynamic_source_observer_from_path(source_root)()
    assert len(observed["documents"]) == 181
    assert observed["source_identity_digest"]
    assert observed["documents"][-1]["document_id"].startswith("daniel_blog_en__")
    assert observed["documents"][-1]["origin_path"].startswith("src/content/blog/")
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "factory.sqlite3"))
    monkeypatch.setenv("M26_SOURCE_ROOT", str(source_root))
    adapter = build_sqlite_ingestion_adapter(
        active_manifest_observer=lambda: {
            "manifest_key": "active",
            "manifest_sha256": "a" * 64,
            "document_digests": {},
        },
        candidate_executor=lambda *_args: {"candidate_release_id": "candidate"},
    )
    assert adapter is not None and adapter.source_observer is not None
    assert len(adapter.source_observer()["documents"]) == 181


def test_runtime_factory_without_all_execution_seams_is_explicit_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "read-only.sqlite3"))
    adapter = build_sqlite_ingestion_adapter(
        source_observer=lambda: {"source_revision": "r", "documents": []},
        active_manifest_observer=lambda: {"document_digests": {}},
    )
    assert adapter is not None
    assert adapter.reason_code == "ADMIN_INGESTION_RUNTIME_SEAMS_UNQUALIFIED"
    assert adapter.list_jobs().availability == "available"
    assert not hasattr(adapter, "sync_blog")

    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=Authenticator(),
        capability_provider=Capabilities(),
        audit_sink=Audit(),
        idempotency_store=adapter.ledger,
    )
    install_admin_ingestion_routes(app, adapter=adapter, include_job_reads=True)
    response = TestClient(app).post(
        "/v1/admin/ingestion/sync",
        headers={
            "origin": "https://console.danielcanfly.com",
            "cf-access-jwt-assertion": "valid",
            "idempotency-key": "read-only-boundary1",
        },
        json={},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == adapter.reason_code
    assert adapter.ledger.list_jobs() == []


def test_candidate_executor_seam_reuses_writer_and_manifest_last(tmp_path: Path) -> None:
    events: list[str] = []

    class Store(FileObjectStore):
        def put(self, key: str, data: bytes, **kwargs: object):
            events.append(key)
            return super().put(key, data, **kwargs)

    class Vector:
        def materialize_and_verify(
            self, *, collection_name: str, release_id: str, semantic_documents: object
        ) -> CandidateVectorVerification:
            events.append("qdrant:" + collection_name)
            return CandidateVectorVerification(
                collection_name=collection_name,
                release_id=release_id,
                point_count=1,
                section_ids=("section-a",),
            )

    def json_bytes(value: object) -> bytes:
        import json

        return (json.dumps(value, sort_keys=True) + "\n").encode()

    artifacts = {
        "graph": json_bytes({"nodes": []}),
        "graph_v2": json_bytes({"nodes": []}),
        "lexical_index": json_bytes({"documents": [{"section_id": "section-a"}]}),
        "provenance": json_bytes({"records": []}),
        "semantic_inputs": json_bytes(
            {"documents": [{"section_id": "section-a", "text": "text", "payload": {}}]}
        ),
    }
    executor = candidate_executor_from_primitives(
        store=Store(tmp_path / "objects"),
        vector_materializer=Vector(),
        artifact_builder=lambda _context: {
            "release_id": "candidate-runtime-001",
            "engine_commit_sha": "d" * 40,
            "source_commit_sha": "a" * 40,
            "source_repository_head_sha": "b" * 40,
            "admission_sha256": "c" * 64,
            "source_count": 1,
            "artifact_bytes": artifacts,
            "created_at": "2026-09-09T00:00:00Z",
        },
    )
    receipt = executor("op", SyncBlogRequest(), lambda *_args: None, {})
    assert receipt["status"] == "candidate_release_finalized"
    assert events[-1] == "releases/candidate-runtime-001/manifest.json"
    assert "qdrant:m26_blog_candidate_runtime_001" in events


def test_dynamic_source_and_active_drift_fail_before_executor(tmp_path: Path) -> None:
    source = {"source_revision": "r1", "documents": [{"document_id": "a", "digest": "a"}]}
    active = {"manifest_key": "m1", "manifest_sha256": "msha1", "document_digests": {}}
    calls = 0

    def observer() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {**source, "source_revision": "r2"} if calls == 2 else dict(source)

    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    lease = _lease(ledger, "drift-key-000001")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=observer,
        active_manifest_observer=lambda: active,
        candidate_executor=lambda *_args: pytest.fail("candidate executor must not run"),
    )
    with pytest.raises(AdminAPIError, match="changed"):
        adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    assert (
        ledger.get_job("syncjob_" + lease.operation_id.removeprefix("admop_"))["status"] == "FAILED"
    )


def test_dynamic_source_accepts_181st_article_and_removed_requires_confirmation(
    tmp_path: Path,
) -> None:
    source = {
        "source_revision": "r181",
        "documents": [
            {"document_id": f"article-{index}", "digest": f"digest-{index}"} for index in range(181)
        ],
    }
    active = {
        "manifest_key": "m180",
        "manifest_sha256": "msha180",
        "document_digests": {f"article-{index}": f"digest-{index}" for index in range(180)},
    }
    contexts: list[dict[str, object]] = []
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    lease = _lease(ledger, "article-181-key001")

    def executor(
        _operation: str,
        _request: object,
        _progress: object,
        context: dict[str, object],
    ) -> dict[str, object]:
        contexts.append(context)
        return {"candidate_release_id": "candidate-181"}

    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=lambda: active,
        candidate_executor=executor,
    )
    result = adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    assert result["status"] == "SUCCEEDED"
    assert len(contexts[0]["source"]["documents"]) == 181

    removed_ledger = SQLiteIngestionLedger(tmp_path / "removed.sqlite3")
    removed_lease = _lease(removed_ledger, "removed-key-000001")
    removed_adapter = SQLiteIngestionAdapter(
        removed_ledger,
        source_observer=lambda: {"source_revision": "r182", "documents": source["documents"][:-1]},
        active_manifest_observer=lambda: {
            **active,
            "document_digests": {
                **active["document_digests"],
                "article-180": "digest-180",
            },
        },
        candidate_executor=lambda *_args: pytest.fail("remove must require confirmation"),
    )
    with pytest.raises(AdminAPIError, match="confirmation"):
        removed_adapter.sync_blog_with_lease(
            removed_lease.operation_id, SyncBlogRequest(), removed_lease
        )


def test_active_manifest_drift_fails_before_candidate_work(tmp_path: Path) -> None:
    source = {"source_revision": "r1", "documents": [{"document_id": "a", "digest": "a"}]}
    active = {"manifest_key": "m1", "manifest_sha256": "msha1", "document_digests": {}}
    active_calls = 0

    def active_observer() -> dict[str, object]:
        nonlocal active_calls
        active_calls += 1
        return {**active, "manifest_sha256": "msha2"} if active_calls == 2 else dict(active)

    ledger = SQLiteIngestionLedger(tmp_path / "active-drift.sqlite3")
    lease = _lease(ledger, "active-drift-key01")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=active_observer,
        candidate_executor=lambda *_args: pytest.fail("active drift must close before work"),
    )
    with pytest.raises(AdminAPIError, match="changed"):
        adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)


def test_noop_and_success_replay_do_zero_candidate_work(tmp_path: Path) -> None:
    source = {"source_revision": "r1", "documents": [{"document_id": "a", "digest": "a"}]}
    active = {"manifest_key": "m1", "manifest_sha256": "msha1", "document_digests": {"a": "a"}}
    calls = 0

    def executor(*_args: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"candidate_manifest_sha256": "candidate"}

    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=lambda: active,
        candidate_executor=executor,
    )
    lease = _lease(ledger, "noop-key-0000001")
    result = adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease)
    assert result["status"] == "SUCCEEDED" and result["result"]["status"] == "noop"
    assert calls == 0
    assert adapter.sync_blog_with_lease(lease.operation_id, SyncBlogRequest(), lease) == result
    assert calls == 0


def test_route_and_p09_reads_share_sqlite_authority_and_retry_route(tmp_path: Path) -> None:
    source = {"source_revision": "r1", "documents": [{"document_id": "a", "digest": "a"}]}
    active = {"manifest_key": "m1", "manifest_sha256": "msha1", "document_digests": {}}
    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=lambda: source,
        active_manifest_observer=lambda: active,
        candidate_executor=lambda *_args: {"ok": True},
    )
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=Authenticator(),
        capability_provider=Capabilities(),
        audit_sink=Audit(),
        idempotency_store=ledger,
    )
    install_admin_ingestion_routes(app, adapter=adapter, include_job_reads=True)
    install_jobs_rollback_routes(
        app, evidence_provider=adapter.as_p09_provider(), include_job_reads=False
    )
    client = TestClient(app)
    headers = {
        "origin": "https://console.danielcanfly.com",
        "cf-access-jwt-assertion": "valid",
        "idempotency-key": "route-key-000001",
    }
    response = client.post("/v1/admin/ingestion/sync", headers=headers, json={})
    assert response.status_code == 202
    job_id = response.json()["result"]["job_id"]
    observed = client.get(
        "/v1/admin/ingestion/jobs/" + job_id,
        headers={**headers, "idempotency-key": "read-key-000001"},
    )
    assert (
        observed.status_code == 200
        and observed.json()["provenance"]["source"] == "sqlite_ingestion_ledger"
    )


def test_unqualified_observer_fails_idempotency_closed(tmp_path: Path) -> None:
    import hashlib

    ledger = SQLiteIngestionLedger(tmp_path / "ingestion.sqlite3")
    adapter = SQLiteIngestionAdapter(ledger)
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=Authenticator(),
        capability_provider=Capabilities(),
        audit_sink=Audit(),
        idempotency_store=ledger,
    )
    install_admin_ingestion_routes(app, adapter=adapter, include_job_reads=True)
    client = TestClient(app)
    headers = {
        "origin": "https://console.danielcanfly.com",
        "cf-access-jwt-assertion": "valid",
        "idempotency-key": "unqualified-key001",
    }
    response = client.post("/v1/admin/ingestion/sync", headers=headers, json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ADMIN_INGESTION_OBSERVER_UNQUALIFIED"
    state = ledger.get_stateful(
        "owner|POST|/v1/admin/ingestion/sync",
        hashlib.sha256(headers["idempotency-key"].encode()).hexdigest(),
    )
    assert state and state.state == "FAILED"
