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
from knowledge_engine.m26_admin_ingestion_sync import SyncBlogRequest
from knowledge_engine.m26_jobs_rollback_api import install_jobs_rollback_routes
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
)


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


def test_concurrent_failed_retry_serializes_to_one_attempt(tmp_path: Path) -> None:
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
    results: list[object] = []

    def retry(owner: str) -> None:
        try:
            results.append(ledger.retry_failed_job("job-retry", owner=owner, now=100.0))
        except AdminAPIError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=retry, args=(owner,)) for owner in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(isinstance(result, dict) for result in results) == 1
    assert ledger.get_job("job-retry")["attempt"] == 2


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
