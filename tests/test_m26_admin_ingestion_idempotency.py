from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import (
    AdminActor,
    AdminAPIError,
    IdempotencyCoordinator,
    InMemoryAuditSink,
    InMemoryIdempotencyStore,
)
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_ingestion import install_admin_ingestion_routes
from knowledge_engine.m26_admin_ingestion_sync import DeterministicSyncIngestionAdapter

OWNER = AdminActor(
    actor_id="cfaccess:owner",
    subject="owner-sub",
    email="owner@example.com",
    actor_type="human",
    issuer="https://team.cloudflareaccess.com",
    audience=("aud-1",),
)


class FakeAuthenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid-assertion":
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACCESS_ASSERTION_INVALID",
                message="invalid",
            )
        return OWNER


class MutationCapabilities:
    def list_capabilities(self) -> list[object]:
        return []

    def get_capability(self, capability_id: str) -> object:
        return SimpleNamespace(
            capability_id=capability_id,
            effective_state="enabled",
            mutation_authorized=True,
            reason_code="TEST_MUTATION_ENABLED",
        )


class FailOnceSyncAdapter:
    def __init__(self) -> None:
        self.attempts = 0
        self.operation_ids: list[str] = []

    def sync_blog(self, operation_id: str, _request: object) -> dict[str, object]:
        self.attempts += 1
        self.operation_ids.append(operation_id)
        if self.attempts == 1:
            raise AdminAPIError(
                status_code=503,
                code="TEST_TRANSIENT_SYNC_FAILURE",
                message="transient",
                retryable=True,
            )
        return {
            "status": "succeeded",
            "operation_id": operation_id,
            "production_write_attempts": 0,
        }


def _headers(key: str = "stateful-key-0001") -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        "cf-access-jwt-assertion": "valid-assertion",
        "content-type": "application/json",
        "idempotency-key": key,
    }


def _make_app(adapter: object) -> tuple[FastAPI, InMemoryIdempotencyStore]:
    store = InMemoryIdempotencyStore()
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=MutationCapabilities(),
        audit_sink=InMemoryAuditSink(),
        idempotency_store=store,
    )
    install_admin_ingestion_routes(app, adapter=adapter)
    return app, store


def test_stateful_coordinator_only_replays_after_success() -> None:
    coordinator = IdempotencyCoordinator(InMemoryIdempotencyStore())
    kwargs = {
        "actor_id": "actor",
        "method": "POST",
        "path": "/v1/admin/ingestion/sync",
        "idempotency_key": "stateful-key-0001",
        "request_payload": {"confirmation": False},
    }

    first = coordinator.begin_stateful(**kwargs)
    assert first.replayed is False
    assert first.attempt == 1

    with pytest.raises(AdminAPIError) as concurrent:
        coordinator.begin_stateful(**kwargs)
    assert concurrent.value.code == "ADMIN_IDEMPOTENCY_IN_PROGRESS"
    assert concurrent.value.retryable is True

    coordinator.fail_stateful(first)
    retry = coordinator.begin_stateful(**kwargs)
    assert retry.replayed is False
    assert retry.operation_id == first.operation_id
    assert retry.attempt == 2

    coordinator.succeed_stateful(retry)
    replay = coordinator.begin_stateful(**kwargs)
    assert replay.replayed is True
    assert replay.operation_id == first.operation_id
    assert replay.attempt == 2

    with pytest.raises(AdminAPIError) as conflict:
        coordinator.begin_stateful(
            **{**kwargs, "request_payload": {"confirmation": True}}
        )
    assert conflict.value.code == "ADMIN_IDEMPOTENCY_CONFLICT"


def test_sync_route_retries_failed_attempt_and_only_then_replays() -> None:
    adapter = FailOnceSyncAdapter()
    app, store = _make_app(adapter)
    client = TestClient(app)

    first = client.post("/v1/admin/ingestion/sync", headers=_headers(), json={})
    assert first.status_code == 503
    assert first.json()["error"]["code"] == "TEST_TRANSIENT_SYNC_FAILURE"
    record = next(iter(store.stateful_records.values()))
    assert record.state == "FAILED"
    assert record.attempt == 1

    second = client.post("/v1/admin/ingestion/sync", headers=_headers(), json={})
    assert second.status_code == 202
    assert second.json()["replayed"] is False
    assert second.json()["operation_id"] == record.operation_id
    assert adapter.attempts == 2
    succeeded = next(iter(store.stateful_records.values()))
    assert succeeded.state == "SUCCEEDED"
    assert succeeded.attempt == 2

    third = client.post("/v1/admin/ingestion/sync", headers=_headers(), json={})
    assert third.status_code == 202
    assert third.json()["replayed"] is True
    assert third.json()["operation_id"] == record.operation_id
    assert adapter.attempts == 2
    assert adapter.operation_ids == [record.operation_id, record.operation_id]


def test_destructive_preview_does_not_consume_idempotency_key_as_success() -> None:
    adapter = DeterministicSyncIngestionAdapter(
        source_revision="source-1",
        documents=[],
        active_document_digests={"old": "a" * 64},
    )
    app, store = _make_app(adapter)
    client = TestClient(app)

    first = client.post("/v1/admin/ingestion/sync", headers=_headers(), json={})
    assert first.status_code == 409
    assert first.json()["error"]["code"] == (
        "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED"
    )
    first_record = next(iter(store.stateful_records.values()))
    assert first_record.state == "FAILED"
    assert first_record.attempt == 1

    second = client.post("/v1/admin/ingestion/sync", headers=_headers(), json={})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == (
        "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED"
    )
    second_record = next(iter(store.stateful_records.values()))
    assert second_record.state == "FAILED"
    assert second_record.attempt == 2
    assert second_record.operation_id == first_record.operation_id
    assert adapter.jobs == []
