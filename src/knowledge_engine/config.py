from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError


def _normalize_env_value(name: str, raw: str) -> str:
    value = raw.strip()
    prefix = f"{name}="
    if value.startswith(prefix):
        value = value[len(prefix) :].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = _normalize_env_value(name, raw)
    return value or default


def _required(name: str) -> str:
    value = _env(name)
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str
    auth_mode: str
    jwt_issuer: str | None
    jwt_jwks_url: str | None
    jwt_audience: str | None
    jwt_default_audiences: tuple[str, ...]
    object_store_backend: str
    filesystem_store_root: Path
    r2_endpoint_url: str | None
    r2_bucket: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None
    r2_region: str
    channel: str
    cache_dir: Path
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        app_env = (_env("APP_ENV", "development") or "development").lower()
        auth_mode = (_env("AUTH_MODE", "disabled") or "disabled").lower()
        backend = (_env("OBJECT_STORE_BACKEND", "r2") or "r2").lower()
        default_audiences = _csv(
            _env("JWT_DEFAULT_AUDIENCES", "public,internal") or "public,internal"
        )
        settings = cls(
            app_env=app_env,
            auth_mode=auth_mode,
            jwt_issuer=_env("JWT_ISSUER"),
            jwt_jwks_url=_env("JWT_JWKS_URL"),
            jwt_audience=_env("JWT_AUDIENCE"),
            jwt_default_audiences=default_audiences,
            object_store_backend=backend,
            filesystem_store_root=Path(
                _env("FILESYSTEM_STORE_ROOT", ".artifacts/store")
                or ".artifacts/store"
            ).expanduser(),
            r2_endpoint_url=_env("R2_ENDPOINT_URL"),
            r2_bucket=_env("R2_BUCKET"),
            r2_access_key_id=_env("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
            r2_region=_env("R2_REGION", "auto") or "auto",
            channel=_env("KNOWLEDGE_CHANNEL", "production") or "production",
            cache_dir=Path(
                _env("CACHE_DIR", ".artifacts/cache") or ".artifacts/cache"
            ).expanduser(),
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.app_env not in {"development", "test", "staging", "production"}:
            raise ConfigurationError(f"unsupported APP_ENV: {self.app_env}")
        if self.auth_mode not in {"disabled", "supabase_jwt"}:
            raise ConfigurationError(f"unsupported AUTH_MODE: {self.auth_mode}")
        if self.app_env == "production" and self.auth_mode == "disabled":
            raise ConfigurationError("AUTH_MODE=disabled is forbidden in production")
        if self.auth_mode == "supabase_jwt":
            for name, value in {
                "JWT_ISSUER": self.jwt_issuer,
                "JWT_JWKS_URL": self.jwt_jwks_url,
                "JWT_AUDIENCE": self.jwt_audience,
            }.items():
                if not value:
                    raise ConfigurationError(f"{name} is required for supabase_jwt")
            issuer = urlparse(self.jwt_issuer or "")
            jwks = urlparse(self.jwt_jwks_url or "")
            if issuer.scheme != "https" or jwks.scheme != "https":
                raise ConfigurationError("JWT issuer and JWKS URL must use HTTPS")
        if self.object_store_backend not in {"filesystem", "r2"}:
            raise ConfigurationError(
                f"unsupported OBJECT_STORE_BACKEND: {self.object_store_backend}"
            )
        if self.object_store_backend == "r2":
            for name, value in {
                "R2_ENDPOINT_URL": self.r2_endpoint_url,
                "R2_BUCKET": self.r2_bucket,
                "R2_ACCESS_KEY_ID": self.r2_access_key_id,
                "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
            }.items():
                if not value:
                    raise ConfigurationError(f"{name} is required for R2")
            endpoint = urlparse(self.r2_endpoint_url or "")
            if endpoint.scheme != "https" or not endpoint.netloc.endswith(
                "r2.cloudflarestorage.com"
            ):
                raise ConfigurationError(
                    "R2_ENDPOINT_URL must be the S3 API endpoint, not r2.dev or a custom domain"
                )
        allowed = {"public", "internal", "confidential", "restricted"}
        if not self.jwt_default_audiences or not set(
            self.jwt_default_audiences
        ).issubset(allowed):
            raise ConfigurationError("JWT_DEFAULT_AUDIENCES contains invalid values")
