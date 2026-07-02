from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .errors import ConfigurationError


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str, *, strip_trailing_slash: bool = False) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    if strip_trailing_slash:
        value = value.rstrip("/")
    return value or None


def _issuer_from_jwks(jwks_url: str | None) -> str | None:
    if not jwks_url:
        return None
    parsed = urlparse(jwks_url)
    suffix = "/.well-known/jwks.json"
    path = parsed.path.rstrip("/")
    if not path.endswith(suffix):
        return None
    issuer_path = path[: -len(suffix)]
    return urlunparse((parsed.scheme, parsed.netloc, issuer_path, "", "", ""))


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
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        auth_mode = os.getenv("AUTH_MODE", "disabled").strip().lower()
        backend = os.getenv("OBJECT_STORE_BACKEND", "r2").strip().lower()
        default_audiences = _csv(
            os.getenv("JWT_DEFAULT_AUDIENCES", "public,internal")
        )
        jwt_jwks_url = _optional_env("JWT_JWKS_URL", strip_trailing_slash=True)
        settings = cls(
            app_env=app_env,
            auth_mode=auth_mode,
            jwt_issuer=_issuer_from_jwks(jwt_jwks_url),
            jwt_jwks_url=jwt_jwks_url,
            jwt_audience=_optional_env("JWT_AUDIENCE"),
            jwt_default_audiences=default_audiences,
            object_store_backend=backend,
            filesystem_store_root=Path(
                os.getenv("FILESYSTEM_STORE_ROOT", ".artifacts/store").strip()
            ).expanduser(),
            r2_endpoint_url=_optional_env(
                "R2_ENDPOINT_URL", strip_trailing_slash=True
            ),
            r2_bucket=_optional_env("R2_BUCKET"),
            r2_access_key_id=_optional_env("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=_optional_env("R2_SECRET_ACCESS_KEY"),
            r2_region=os.getenv("R2_REGION", "auto").strip(),
            channel=os.getenv("KNOWLEDGE_CHANNEL", "production").strip(),
            cache_dir=Path(
                os.getenv("CACHE_DIR", ".artifacts/cache").strip()
            ).expanduser(),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
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
                "JWT_JWKS_URL": self.jwt_jwks_url,
                "JWT_AUDIENCE": self.jwt_audience,
            }.items():
                if not value:
                    raise ConfigurationError(f"{name} is required for supabase_jwt")
            jwks = urlparse(self.jwt_jwks_url or "")
            if jwks.scheme != "https":
                raise ConfigurationError("JWT JWKS URL must use HTTPS")
            if jwks.path.rstrip("/") != "/auth/v1/.well-known/jwks.json":
                raise ConfigurationError(
                    "JWT_JWKS_URL must end with /auth/v1/.well-known/jwks.json"
                )
            if not self.jwt_issuer:
                raise ConfigurationError("JWT issuer could not be derived from JWT_JWKS_URL")
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
