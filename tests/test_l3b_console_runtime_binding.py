import importlib

from knowledge_engine.m26_admin_production import L3B_CAPABILITY_IDS, SqliteAdminControlStore


def test_console_app_binds_only_qualified_l3b_controls_when_explicitly_enabled(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("M26_L3B_ADMIN_QUALIFIED", "true")
    monkeypatch.setenv("M26_ADMIN_CONTROL_DB_PATH", str(tmp_path / "admin-control.sqlite3"))

    import knowledge_engine.m26_console_api as console_api

    console_api = importlib.reload(console_api)
    app = console_api.app
    provider = app.state.admin_capability_provider
    assert [gate.capability_id for gate in provider.list_capabilities()] == sorted(
        L3B_CAPABILITY_IDS
    )
    assert isinstance(app.state.admin_audit_sink, SqliteAdminControlStore)
    assert app.state.admin_audit_sink is app.state.admin_idempotency_store
    paths = set(app.openapi()["paths"])
    assert "/v1/answers/health" in paths
    assert "/v1/admin/qa/inbox/events" in paths
    assert "/v1/admin/qa/inbox/summary" in paths
    assert "/v1/admin/suggested-questions/promotions/preview" in paths
    assert "/v1/admin/suggested-questions/promotions/{promotion_id}/publish" in paths


def test_console_app_remains_fail_closed_without_explicit_production_binding(
    monkeypatch,
) -> None:
    monkeypatch.delenv("M26_L3B_ADMIN_QUALIFIED", raising=False)
    monkeypatch.delenv("M26_ADMIN_CONTROL_DB_PATH", raising=False)

    import knowledge_engine.m26_console_api as console_api

    console_api = importlib.reload(console_api)
    app = console_api.app
    assert app.state.admin_capability_provider.list_capabilities() == []
