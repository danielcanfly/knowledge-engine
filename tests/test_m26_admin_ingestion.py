from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from knowledge_engine import m26_admin_ingestion as ingestion_module
from knowledge_engine.m26_admin_contract import AdminAPIError
from knowledge_engine.m26_admin_ingestion import (
    ConfirmJobRequest,
    DryRunRequest,
    InMemoryIngestionAdapter,
    UnavailableIngestionAdapter,
    _require_mutation_capability,
    build_dry_run_plan,
)
from knowledge_engine.m26_admin_ingestion_sync import SyncBlogRequest


def _digest(char: str) -> str:
    return char * 64


def test_dry_run_digest_is_deterministic_for_same_semantic_inputs() -> None:
    documents_a = [
        {"document_id": "b", "digest": _digest("b")},
        {"document_id": "a", "digest": _digest("a")},
    ]
    documents_b = list(reversed(documents_a))
    first = build_dry_run_plan(
        source_revision="source-1",
        documents=documents_a,
        active_document_digests={"b": _digest("c")},
        scope="explicit_documents",
        document_ids=["b", "a", "b"],
    )
    second = build_dry_run_plan(
        source_revision="source-1",
        documents=documents_b,
        active_document_digests={"b": _digest("c")},
        scope="explicit_documents",
        document_ids=["a", "b"],
    )
    assert first == second
    assert len(first["dry_run_digest"]) == 64
    assert first["plan"]["activation"] == "separate_explicit_action_required"


def test_stale_source_revision_fails_closed_on_confirmation() -> None:
    adapter = InMemoryIngestionAdapter(
        source_revision="source-1",
        documents=[{"document_id": "a", "digest": _digest("a")}],
    )
    adapter.create_dry_run(
        "admop_dryrun",
        DryRunRequest(scope="single_document", document_ids=["a"]),
    )
    dry_run = adapter.jobs[-1]
    adapter.source_revision = "source-2"

    with pytest.raises(AdminAPIError) as caught:
        adapter.confirm_job(
            "admop_confirm",
            ConfirmJobRequest(
                dry_run_id=str(dry_run["dry_run_id"]),
                dry_run_digest=str(dry_run["dry_run_digest"]),
                confirmation=True,
            ),
        )

    assert caught.value.status_code == 409
    assert caught.value.code == "ADMIN_INGESTION_SOURCE_REVISION_CHANGED"
    assert adapter.confirmed_job_ids == []


def test_index_audit_is_evidence_only_with_zero_repair_and_write_attempts() -> None:
    adapter = InMemoryIngestionAdapter(
        source_revision="source-1",
        documents=[{"document_id": "a", "digest": _digest("a")}],
    )
    adapter.start_audit("admop_audit")
    observation = adapter.list_audits()

    assert observation.data["write_attempts"] == 0
    assert observation.data["repair_attempts"] == 0
    assert observation.data["audits"][0]["write_attempts"] == 0
    assert observation.data["audits"][0]["repair_attempts"] == 0


def test_confirmed_job_does_not_implicitly_activate_candidate() -> None:
    adapter = InMemoryIngestionAdapter(
        source_revision="source-1",
        documents=[{"document_id": "a", "digest": _digest("a")}],
    )
    adapter.create_dry_run(
        "admop_dryrun",
        DryRunRequest(scope="single_document", document_ids=["a"]),
    )
    dry_run = adapter.jobs[-1]
    adapter.confirm_job(
        "admop_confirm",
        ConfirmJobRequest(
            dry_run_id=str(dry_run["dry_run_id"]),
            dry_run_digest=str(dry_run["dry_run_digest"]),
            confirmation=True,
        ),
    )

    confirmed = adapter.jobs[-1]
    assert confirmed["status"] == "queued"
    assert confirmed["candidate_activation"] == "not_requested"


def test_unqualified_production_adapter_is_explicitly_unavailable() -> None:
    observation = UnavailableIngestionAdapter().current_index()
    assert observation.availability == "unavailable"
    assert observation.data is None
    assert observation.reason_code == "ADMIN_INGESTION_ADAPTER_UNQUALIFIED"


def test_legacy_enabled_state_cannot_authorize_mutation_without_canonical_mapping() -> None:
    legacy_gate = SimpleNamespace(
        state="enabled",
        reason_code="LEGACY_ENABLED",
    )
    provider = SimpleNamespace(get_capability=lambda _capability_id: legacy_gate)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(admin_capability_provider=provider),
        )
    )

    with pytest.raises(AdminAPIError) as caught:
        _require_mutation_capability(request, "ingestion.job.confirm")

    assert caught.value.status_code == 409
    assert caught.value.code == "ADMIN_CAPABILITY_CANONICAL_MAPPING_REQUIRED"
    assert caught.value.details["effective_state"] == "unavailable"
    assert caught.value.details["mutation_authorized"] is False


def _route_endpoint(operation_id: str):
    return next(
        route.endpoint
        for route in ingestion_module._router().routes
        if getattr(route, "operation_id", None) == operation_id
    )


def _read_request(adapter):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(m26_ingestion_adapter=adapter)),
        state=SimpleNamespace(admin_request_id="admreq_test"),
    )


def test_sync_route_accepts_before_heavy_execution(monkeypatch) -> None:
    heavy_calls: list[str] = []
    coordinator_calls: list[str] = []

    class Adapter:
        def preview_sync_plan(self):
            return {
                "plan_id": "plan-async",
                "plan_digest": "a" * 64,
                "plan": {
                    "requires_confirmation": False,
                    "manifest_diff": {
                        "added": ["new"],
                        "changed": [],
                        "removed": [],
                        "unchanged": [],
                    },
                },
            }

        def sync_blog(self, operation_id: str, _body: object):
            heavy_calls.append(operation_id)
            return {"status": "succeeded"}

    adapter = Adapter()
    coordinator = SimpleNamespace(
        succeed_stateful=lambda lease: coordinator_calls.append(lease.operation_id),
        fail_stateful=lambda lease: None,
    )
    lease = SimpleNamespace(
        replayed=False,
        operation_id="admop_async",
        scope="owner|POST|/v1/admin/ingestion/sync",
        key_fingerprint="f" * 64,
        request_hash="r" * 64,
        attempt=1,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                m26_ingestion_adapter=adapter,
                admin_idempotency=coordinator,
            )
        ),
        state=SimpleNamespace(admin_request_id="admreq_async"),
        method="POST",
        url=SimpleNamespace(path="/v1/admin/ingestion/sync"),
        headers={"idempotency-key": "async-key"},
    )

    monkeypatch.setattr(ingestion_module, "_require_mutation_capability", lambda *_: None)
    monkeypatch.setattr(ingestion_module, "_begin_stateful_operation", lambda *_: lease)
    monkeypatch.setattr(ingestion_module, "_audit", lambda *_: None)

    async def immediate_threadpool(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(ingestion_module, "run_in_threadpool", immediate_threadpool)

    background = BackgroundTasks()
    response = asyncio.run(
        _route_endpoint("syncBlog")(request, SyncBlogRequest(), background)
    )

    assert response["status"] == "accepted"
    assert response["operation_id"] == "admop_async"
    assert heavy_calls == []
    assert len(background.tasks) == 1

    asyncio.run(background())

    assert heavy_calls == ["admop_async"]
    assert coordinator_calls == ["admop_async"]


def test_index_current_offloads_blocking_adapter_read(monkeypatch) -> None:
    adapter = UnavailableIngestionAdapter()
    calls: list[object] = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        calls.append(fn)
        return fn(*args, **kwargs)

    monkeypatch.setattr(ingestion_module, "run_in_threadpool", fake_run_in_threadpool)
    response = asyncio.run(_route_endpoint("getCurrentIndex")(_read_request(adapter)))

    assert calls == [adapter.current_index]
    assert response["availability"]["status"] == "unavailable"


def test_index_health_offloads_blocking_adapter_read(monkeypatch) -> None:
    adapter = UnavailableIngestionAdapter()
    calls: list[object] = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        calls.append(fn)
        return fn(*args, **kwargs)

    monkeypatch.setattr(ingestion_module, "run_in_threadpool", fake_run_in_threadpool)
    response = asyncio.run(_route_endpoint("getIndexHealth")(_read_request(adapter)))

    assert calls == [adapter.current_index]
    assert response["availability"]["status"] == "unavailable"


def test_manual_history_cleanup_is_explicit_and_offloaded(monkeypatch) -> None:
    cleanup_calls: list[str] = []

    class Adapter:
        def cleanup_old_history(self):
            cleanup_calls.append("cleanup")
            return {
                "schema_version": "m26-ingestion-job-cleanup/v1",
                "scope": "ingestion_terminal_history_only",
                "deleted_jobs": 27,
                "deleted_idempotency_records": 27,
            }

    adapter = Adapter()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(m26_ingestion_adapter=adapter)),
        state=SimpleNamespace(admin_request_id="admreq_cleanup"),
        method="POST",
        url=SimpleNamespace(path="/v1/admin/ingestion/history/cleanup"),
        headers={"idempotency-key": "cleanup-key"},
    )
    monkeypatch.setattr(ingestion_module, "_require_mutation_capability", lambda *_: None)
    monkeypatch.setattr(
        ingestion_module,
        "_begin_operation",
        lambda *_: ("admop_cleanup", False),
    )
    monkeypatch.setattr(ingestion_module, "_audit", lambda *_: None)

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(ingestion_module, "run_in_threadpool", fake_run_in_threadpool)
    response = asyncio.run(_route_endpoint("cleanupIngestionHistory")(request))

    assert cleanup_calls == ["cleanup"]
    assert response["status"] == "accepted"
    assert response["operation_id"] == "admop_cleanup"
    assert response["result"]["deleted_jobs"] == 27
