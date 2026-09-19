from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

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
