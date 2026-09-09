from pathlib import Path

import pytest

from knowledge_engine.m26_admin_contract import (
    AdminConfigurationError,
    AuditEvent,
    IdempotencyRecord,
)
from knowledge_engine.m26_admin_production import (
    ADMIN_CONTROL_DB_ENV,
    L3B_ADMIN_QUALIFIED_ENV,
    L3B_CAPABILITY_IDS,
    QualifiedL3BCapabilityProvider,
    SqliteAdminControlStore,
    production_admin_runtime_from_env,
)


def test_qualified_provider_exposes_only_l3b_capabilities() -> None:
    provider = QualifiedL3BCapabilityProvider()
    gates = provider.list_capabilities()
    assert [gate.capability_id for gate in gates] == sorted(L3B_CAPABILITY_IDS)
    assert all(gate.state == "enabled" for gate in gates)
    assert all(gate.source == "l3b_production_qualification" for gate in gates)
    assert provider.get_capability("ingestion.execute") is None
    assert provider.get_capability("index.activate") is None


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
    assert [gate.capability_id for gate in runtime.capability_provider.list_capabilities()] == sorted(
        L3B_CAPABILITY_IDS
    )
