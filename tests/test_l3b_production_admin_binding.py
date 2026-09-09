from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import (
    AdminConfigurationError,
    AuditEvent,
    IdempotencyRecord,
)
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
    install_admin_control_plane,
    require_capability,
)
from knowledge_engine.m26_admin_production import (
    ADMIN_CONTROL_DB_ENV,
    L3B_ADMIN_QUALIFIED_ENV,
    L3B_CAPABILITY_IDS,
    L3B_SUGGESTED_QUESTIONS_PUBLISH_BLOCKED_REASON,
    QualifiedL3BCapabilityProvider,
    SqliteAdminControlStore,
    production_admin_runtime_from_env,
)
from knowledge_engine.m26_admin_settings import install_admin_settings


def test_qualified_provider_exposes_only_l3b_capabilities() -> None:
    provider = QualifiedL3BCapabilityProvider()
    gates = provider.list_capabilities()
    assert [gate.capability_id for gate in gates] == sorted(L3B_CAPABILITY_IDS)
    assert {gate.capability_id: gate.state for gate in gates} == {
        "qa.event.read": "read_only",
        "qa.events.read": "read_only",
        "qa.export_markdown": "read_only",
        "suggested_questions.publish": "disabled",
    }
    assert all(gate.source == "l3b_production_qualification" for gate in gates)
    assert provider.get_capability("ingestion.execute") is None
    assert provider.get_capability("index.activate") is None


def test_production_provider_emits_canonical_read_evidence_and_blocks_publish() -> None:
    provider = QualifiedL3BCapabilityProvider()

    for capability_id in ("qa.events.read", "qa.event.read"):
        payload = provider.get_capability(capability_id).to_payload()
        assert payload["qualification_status"] == "qualified"
        assert payload["effective_state"] == "read_only"
        assert payload["mutation_authorized"] is False

    publish = provider.get_capability("suggested_questions.publish").to_payload()
    assert publish["qualification_status"] == "blocked_authority"
    assert publish["effective_state"] == "unavailable"
    assert publish["mutation_authorized"] is False
    assert publish["reason_code"] == L3B_SUGGESTED_QUESTIONS_PUBLISH_BLOCKED_REASON


class _Authenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid-assertion":
            raise AdminAPIError(status_code=403, code="INVALID", message="invalid")
        return AdminActor(
            actor_id="owner",
            subject="owner",
            email="owner@example.com",
            actor_type="human",
            issuer="https://team.cloudflareaccess.com",
            audience=("aud",),
        )


def test_production_provider_settings_projection_is_readable_and_mutation_safe() -> None:
    app = FastAPI()
    provider = QualifiedL3BCapabilityProvider()
    install_admin_control_plane(app, authenticator=_Authenticator(), capability_provider=provider)
    install_admin_settings(app)
    response = TestClient(app).get(
        "/v1/admin/settings",
        headers={
            "origin": "https://console.danielcanfly.com",
            ACCESS_ASSERTION_HEADER: "valid-assertion",
        },
    )
    assert response.status_code == 200
    capabilities = {
        item["capability_id"]: item for item in response.json()["data"]["capabilities"]
    }
    for capability_id in ("qa.events.read", "qa.event.read"):
        assert capabilities[capability_id]["qualification_status"] == "qualified"
        assert capabilities[capability_id]["effective_state"] == "read_only"
        assert capabilities[capability_id]["mutation_authorized"] is False
    publish = capabilities["suggested_questions.publish"]
    assert publish["effective_state"] == "unavailable"
    assert publish["mutation_authorized"] is False


def test_production_provider_direct_read_gate_allows_reads_but_mutations_fail_closed() -> None:
    app = FastAPI()
    provider = QualifiedL3BCapabilityProvider()
    install_admin_control_plane(app, capability_provider=provider)
    request = type("Request", (), {"app": app})()

    assert require_capability(request, "qa.events.read").state == "read_only"
    with pytest.raises(AdminAPIError) as export_error:
        require_capability(request, "qa.export_markdown", mutation=True)
    assert export_error.value.status_code == 409
    with pytest.raises(AdminAPIError) as publish_error:
        require_capability(request, "suggested_questions.publish", mutation=True)
    assert publish_error.value.status_code == 409


def test_production_binding_is_explicit_and_fails_closed_without_durable_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(L3B_ADMIN_QUALIFIED_ENV, raising=False)
    monkeypatch.delenv(ADMIN_CONTROL_DB_ENV, raising=False)
    assert production_admin_runtime_from_env() is None

    monkeypatch.setenv(L3B_ADMIN_QUALIFIED_ENV, "true")
    with pytest.raises(AdminConfigurationError, match="durable control DB path"):
        production_admin_runtime_from_env()


def test_sqlite_admin_control_store_is_durable_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "admin-control.sqlite3"
    store = SqliteAdminControlStore(db_path)
    event = AuditEvent(
        event_id="admevt_l3b_test",
        observed_at="2026-09-09T00:00:00Z",
        actor_id="cfaccess:owner",
        actor_type="human",
        action="suggested_questions.promotion.preview.accepted",
        object_type="suggested_questions_promotion",
        object_id="preview-1",
        request_id="admreq_test",
        operation_id="admop_test",
        outcome="accepted",
        reason_code="SUGGESTED_QUESTIONS_PREVIEW_READY",
        metadata={"token": "never-store-me"},
    )
    store.append(event)
    record = IdempotencyRecord(
        scope="cfaccess:owner|POST|/v1/admin/suggested-questions/promotions/preview",
        key_fingerprint="fingerprint",
        request_hash="request-hash",
        operation_id="admop_test",
        created_at="2026-09-09T00:00:00Z",
    )
    assert store.put_if_absent(record) == record

    reopened = SqliteAdminControlStore(db_path)
    assert reopened.audit_count() == 1
    assert reopened.get(record.scope, record.key_fingerprint) == record

    challenger = IdempotencyRecord(
        scope=record.scope,
        key_fingerprint=record.key_fingerprint,
        request_hash="different-request-hash",
        operation_id="different-operation",
        created_at="2026-09-09T00:01:00Z",
    )
    assert reopened.put_if_absent(challenger) == record


def test_explicit_binding_materializes_durable_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "bound.sqlite3"
    monkeypatch.setenv(L3B_ADMIN_QUALIFIED_ENV, "true")
    monkeypatch.setenv(ADMIN_CONTROL_DB_ENV, str(db_path))
    runtime = production_admin_runtime_from_env()
    assert runtime is not None
    assert runtime.store.db_path == db_path.resolve()
    capabilities = [gate.capability_id for gate in runtime.capability_provider.list_capabilities()]
    assert capabilities == sorted(L3B_CAPABILITY_IDS)
