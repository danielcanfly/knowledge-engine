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


def test_assignment_style_r2_values_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "'APP_ENV test'")
    monkeypatch.setenv("AUTH_MODE", '"AUTH_MODE:disabled"')
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "OBJECT_STORE_BACKEND=r2")
    monkeypatch.setenv(
        "R2_ENDPOINT_URL",
        (
            '"R2_ENDPOINT_URL https://abc.r2.cloudflarestorage.com/'
            'llm-wiki-bucket"'
        ),
    )
    monkeypatch.setenv("R2_BUCKET", "R2_BUCKET=llm-wiki-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID:access-value")
    monkeypatch.setenv(
        "R2_SECRET_ACCESS_KEY",
        "'R2_SECRET_ACCESS_KEY secret-value'",
    )

    settings = Settings.from_env()

    assert settings.r2_endpoint_url == "https://abc.r2.cloudflarestorage.com"
    assert settings.r2_bucket == "llm-wiki-bucket"
    assert settings.r2_access_key_id == "access-value"
    assert settings.r2_secret_access_key == "secret-value"


def test_r2_rejects_unrelated_endpoint_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "r2")
    monkeypatch.setenv(
        "R2_ENDPOINT_URL",
        "https://abc.r2.cloudflarestorage.com/not-the-bucket",
    )
    monkeypatch.setenv("R2_BUCKET", "llm-wiki-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access-value")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret-value")
    with pytest.raises(ConfigurationError, match="must not include a bucket path"):
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
