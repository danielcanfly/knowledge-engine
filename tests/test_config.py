from __future__ import annotations

import pytest

from knowledge_engine.config import Settings
from knowledge_engine.errors import ConfigurationError


def test_production_rejects_disabled_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    with pytest.raises(ConfigurationError, match="forbidden"):
        Settings.from_env()


def test_r2_rejects_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "r2")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.r2.dev")
    monkeypatch.setenv("R2_BUCKET", "llm-wiki-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    with pytest.raises(ConfigurationError, match="S3 API endpoint"):
        Settings.from_env()


def test_supabase_settings_accept_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "supabase_jwt")
    monkeypatch.setenv("JWT_ISSUER", "https://project.supabase.co/auth/v1")
    monkeypatch.setenv(
        "JWT_JWKS_URL",
        "https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setenv("JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    settings = Settings.from_env()
    assert settings.jwt_default_audiences == ("public", "internal")


def test_environment_values_are_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", " production\n")
    monkeypatch.setenv("AUTH_MODE", " supabase_jwt\n")
    monkeypatch.setenv(
        "JWT_ISSUER",
        " https://project.supabase.co/auth/v1/\n",
    )
    monkeypatch.setenv(
        "JWT_JWKS_URL",
        " https://project.supabase.co/auth/v1/.well-known/jwks.json/\n",
    )
    monkeypatch.setenv("JWT_AUDIENCE", " authenticated\n")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", " r2\n")
    monkeypatch.setenv(
        "R2_ENDPOINT_URL",
        " https://account.r2.cloudflarestorage.com/\n",
    )
    monkeypatch.setenv("R2_BUCKET", " llm-wiki-bucket\n")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", " key\n")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", " secret\n")

    settings = Settings.from_env()

    assert settings.jwt_issuer == "https://project.supabase.co/auth/v1"
    assert (
        settings.jwt_jwks_url
        == "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )
    assert settings.r2_endpoint_url == "https://account.r2.cloudflarestorage.com"
    assert settings.r2_bucket == "llm-wiki-bucket"
