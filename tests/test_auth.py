from __future__ import annotations

from pathlib import Path

from knowledge_engine.auth import Authenticator
from knowledge_engine.config import Settings


def test_disabled_auth_uses_configured_audiences() -> None:
    settings = Settings(
        app_env="test",
        auth_mode="disabled",
        jwt_issuer=None,
        jwt_jwks_url=None,
        jwt_audience=None,
        jwt_default_audiences=("public", "internal"),
        object_store_backend="filesystem",
        filesystem_store_root=Path(".artifacts/store"),
        r2_endpoint_url=None,
        r2_bucket=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_region="auto",
        channel="staging",
        cache_dir=Path(".artifacts/cache"),
        log_level="INFO",
    )
    principal = Authenticator(settings).authenticate(None)
    assert principal.subject == "development-user"
    assert principal.audiences == frozenset({"public", "internal"})
