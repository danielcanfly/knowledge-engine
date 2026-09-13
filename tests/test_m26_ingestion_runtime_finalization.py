from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge_engine.m26_admin_ingestion import CAP_INGESTION_JOB_CONFIRM
from knowledge_engine.m26_ingestion_finalization import ProductionIngestionFinalizer
from knowledge_engine.m26_ingestion_runtime import (
    CombinedCapabilityProvider,
    _production_authority_missing,
    build_runtime_ingestion_adapter_from_env,
)
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    SQLiteIngestionReadAuthority,
)


def _clear_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "M26_INGESTION_ENABLED",
        "M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED",
        "M26_INGESTION_OWNER_AUTHORIZATION",
        "M26_INGESTION_ASK_PROBE_QUESTION",
        "M26_INGESTION_STATE_DB",
        "M26_QUERY_BUILD_SHA",
        "M26_SOURCE_ROOT",
        "KNOWLEDGE_SOURCE_READ_TOKEN",
        "M26_SOURCE_REPOSITORY",
        "M26_SOURCE_REF",
        "OBJECT_STORE_BACKEND",
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "QDRANT_API_KEY_READ",
        "QDRANT_READ_ONLY_API_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_disabled_runtime_is_read_only_without_constructing_mutation_primitives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("M26_INGESTION_STATE_DB", "/tmp/f8-runtime-gate.sqlite3")

    import knowledge_engine.m26_ingestion_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "create_object_store",
        lambda _settings: (_ for _ in ()).throw(AssertionError("store must not construct")),
    )
    monkeypatch.setattr(
        runtime,
        "ProductionIngestionFinalizer",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("finalizer must not construct")),
    )

    adapter = build_runtime_ingestion_adapter_from_env()

    assert isinstance(adapter, SQLiteIngestionReadAuthority)
    assert not hasattr(adapter, "sync_blog")
    assert adapter.current_index().data["production_activation_authorized"] is False


def test_partial_production_authority_names_missing_keys_without_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "ingestion.sqlite3"))
    monkeypatch.setenv("M26_QUERY_BUILD_SHA", "not-a-sha")

    missing = _production_authority_missing()
    assert "M26_INGESTION_OWNER_AUTHORIZATION" in missing
    assert "M26_QUERY_BUILD_SHA" in missing
    assert "not-a-sha" not in " ".join(missing)
    adapter = build_runtime_ingestion_adapter_from_env()
    assert isinstance(adapter, SQLiteIngestionReadAuthority)
    assert adapter.current_index().data["production_activation_authorized"] is False


def test_read_credential_must_be_distinct_from_candidate_write_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_OWNER_AUTHORIZATION", "owner")
    monkeypatch.setenv("M26_INGESTION_ASK_PROBE_QUESTION", "probe")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "ingestion.sqlite3"))
    monkeypatch.setenv("M26_QUERY_BUILD_SHA", "a" * 40)
    monkeypatch.setenv("M26_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "r2")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example.test")
    monkeypatch.setenv("QDRANT_API_KEY", "same")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "same")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "token")

    assert "QDRANT_READ_CREDENTIAL_DISTINCT" in _production_authority_missing()


def test_production_executor_without_self_check_evidence_is_not_authorized(
    tmp_path: Path,
) -> None:
    class FakeProductionExecutor:
        mode = "production_activation"

    adapter = SQLiteIngestionAdapter(
        SQLiteIngestionLedger(tmp_path / "missing-evidence.sqlite3"),
        finalization_executor=FakeProductionExecutor(),
        finalization_mode="production_activation",
    )

    evidence = adapter.current_index().data

    assert evidence["finalization_authorized"] is False
    assert evidence["production_activation_authorized"] is False


def test_invalid_qdrant_url_returns_read_only_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_OWNER_AUTHORIZATION", "owner")
    monkeypatch.setenv("M26_INGESTION_ASK_PROBE_QUESTION", "probe")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "ingestion.sqlite3"))
    monkeypatch.setenv("M26_QUERY_BUILD_SHA", "a" * 40)
    monkeypatch.setenv("M26_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "r2")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("QDRANT_URL", "http://invalid.example.test")
    monkeypatch.setenv("QDRANT_API_KEY", "write")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "read")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "token")

    adapter = build_runtime_ingestion_adapter_from_env(
        settings_factory=lambda: SimpleNamespace(
            object_store_backend="r2",
            r2_endpoint_url="https://account.r2.cloudflarestorage.com",
            r2_bucket="bucket",
            r2_region="auto",
        ),
        store_override=object(),
    )
    assert isinstance(adapter, SQLiteIngestionReadAuthority)
    assert adapter.current_index().data["production_activation_authorized"] is False


def test_complete_injected_authority_composes_production_finalizer_and_capability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("M26_INGESTION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED", "true")
    monkeypatch.setenv("M26_INGESTION_OWNER_AUTHORIZATION", "owner")
    monkeypatch.setenv("M26_INGESTION_ASK_PROBE_QUESTION", "probe")
    monkeypatch.setenv("M26_INGESTION_STATE_DB", str(tmp_path / "ingestion.sqlite3"))
    monkeypatch.setenv("M26_QUERY_BUILD_SHA", "a" * 40)
    monkeypatch.setenv("M26_SOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "r2")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example.test")
    monkeypatch.setenv("QDRANT_API_KEY", "write")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "read")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "token")

    settings = SimpleNamespace(
        object_store_backend="r2",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="bucket",
        r2_region="auto",
    )

    class Source:
        def observe(self):
            return {
                "source_revision": "git:" + "b" * 40,
                "source_identity_digest": "c" * 64,
                "documents": [{"document_id": "doc", "digest": "d" * 64}],
            }

        def artifact_builder(self, _engine_sha):
            return lambda _context: {}

    monkeypatch.setattr(
        ProductionIngestionFinalizer,
        "self_check",
        lambda _self: {
            "production_activation_authorized": True,
            "schema_version": "test",
        },
    )
    adapter = build_runtime_ingestion_adapter_from_env(
        source_override=Source(),
        store_override=object(),
        qdrant_observer_override=object(),
        dense_channel_override=object(),
        settings_factory=lambda: settings,
        materializer_factory=lambda **_kwargs: object(),
    )

    assert adapter.finalization_mode == "production_activation"
    assert isinstance(adapter.finalization_executor, ProductionIngestionFinalizer)
    gate = CombinedCapabilityProvider(
        SimpleNamespace(
            list_capabilities=lambda: [],
            get_capability=lambda _capability_id: None,
        ),
        adapter,
    ).get_capability(CAP_INGESTION_JOB_CONFIRM)
    assert gate is not None
    assert gate.reason_code == "F8_PRODUCTION_FINALIZATION_QUALIFIED"
