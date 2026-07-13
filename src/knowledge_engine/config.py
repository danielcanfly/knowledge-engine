from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .errors import ConfigurationError


def _normalize_env_value(name: str, raw: str) -> str:
    value = raw.strip()
    for _ in range(4):
        changed = False
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
            changed = True
        if value.startswith(name):
            suffix = value[len(name) :]
            if suffix and (suffix[0] in "=:" or suffix[0].isspace()):
                value = suffix.lstrip(" \t=:")
                changed = True
        if not changed:
            break
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


def _bool(name: str, default: bool) -> bool:
    raw = (_env(name, "true" if default else "false") or "").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _int(name: str, default: int) -> int:
    raw = _env(name, str(default)) or str(default)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    raw = _env(name, str(default)) or str(default)
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _normalize_r2_endpoint(endpoint: str | None, bucket: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    if bucket and path == f"/{bucket}":
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    return endpoint.rstrip("/")


def _validate_public_origin(origin: str, *, app_env: str) -> None:
    if origin == "*":
        raise ConfigurationError("PUBLIC_ALLOWED_ORIGINS must not contain wildcard origins")
    parsed = urlparse(origin)
    if parsed.username or parsed.password:
        raise ConfigurationError("PUBLIC_ALLOWED_ORIGINS must not contain credentials")
    if not parsed.scheme or not parsed.netloc:
        raise ConfigurationError("PUBLIC_ALLOWED_ORIGINS must contain absolute origins")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConfigurationError(
            "PUBLIC_ALLOWED_ORIGINS entries must not contain paths, queries, or fragments"
        )
    if app_env in {"staging", "production"} and parsed.scheme != "https":
        raise ConfigurationError(
            "PUBLIC_ALLOWED_ORIGINS must use HTTPS in staging and production"
        )
    if parsed.scheme not in {"http", "https"}:
        raise ConfigurationError("PUBLIC_ALLOWED_ORIGINS must use HTTP or HTTPS")


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
    relation_aware_expansion_enabled: bool = False
    public_anonymous_enabled: bool = True
    public_allowed_origins: tuple[str, ...] = ()
    public_rate_limit_requests: int = 30
    public_rate_limit_window_seconds: int = 60
    public_max_body_bytes: int = 16384
    public_request_timeout_seconds: float = 15.0
    public_max_concurrent_requests: int = 8

    @classmethod
    def from_env(cls) -> Settings:
        app_env = (_env("APP_ENV", "development") or "development").lower()
        auth_mode = (_env("AUTH_MODE", "disabled") or "disabled").lower()
        backend = (_env("OBJECT_STORE_BACKEND", "r2") or "r2").lower()
        default_audiences = _csv(
            _env("JWT_DEFAULT_AUDIENCES", "public,internal") or "public,internal"
        )
        r2_bucket = _env("R2_BUCKET")
        r2_endpoint_url = _normalize_r2_endpoint(
            _env("R2_ENDPOINT_URL"),
            r2_bucket,
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
            r2_endpoint_url=r2_endpoint_url,
            r2_bucket=r2_bucket,
            r2_access_key_id=_env("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=_env("R2_SECRET_ACCESS_KEY"),
            r2_region=_env("R2_REGION", "auto") or "auto",
            channel=_env("KNOWLEDGE_CHANNEL", "production") or "production",
            cache_dir=Path(
                _env("CACHE_DIR", ".artifacts/cache") or ".artifacts/cache"
            ).expanduser(),
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            relation_aware_expansion_enabled=_bool(
                "RELATION_AWARE_EXPANSION_ENABLED",
                False,
            ),
            public_anonymous_enabled=_bool("PUBLIC_ANONYMOUS_ENABLED", True),
            public_allowed_origins=_csv(_env("PUBLIC_ALLOWED_ORIGINS", "") or ""),
            public_rate_limit_requests=_int("PUBLIC_RATE_LIMIT_REQUESTS", 30),
            public_rate_limit_window_seconds=_int(
                "PUBLIC_RATE_LIMIT_WINDOW_SECONDS",
                60,
            ),
            public_max_body_bytes=_int("PUBLIC_MAX_BODY_BYTES", 16384),
            public_request_timeout_seconds=_float(
                "PUBLIC_REQUEST_TIMEOUT_SECONDS",
                15.0,
            ),
            public_max_concurrent_requests=_int(
                "PUBLIC_MAX_CONCURRENT_REQUESTS",
                8,
            ),
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
            if endpoint.path not in {"", "/"} or endpoint.query or endpoint.fragment:
                raise ConfigurationError(
                    "R2_ENDPOINT_URL must not include a bucket path, query, or fragment"
                )
        allowed = {"public", "internal", "confidential", "restricted"}
        if not self.jwt_default_audiences or not set(
            self.jwt_default_audiences
        ).issubset(allowed):
            raise ConfigurationError("JWT_DEFAULT_AUDIENCES contains invalid values")
        if len(set(self.public_allowed_origins)) != len(self.public_allowed_origins):
            raise ConfigurationError("PUBLIC_ALLOWED_ORIGINS contains duplicates")
        for origin in self.public_allowed_origins:
            _validate_public_origin(origin, app_env=self.app_env)
        bounded_integers = {
            "PUBLIC_RATE_LIMIT_REQUESTS": (
                self.public_rate_limit_requests,
                1,
                10000,
            ),
            "PUBLIC_RATE_LIMIT_WINDOW_SECONDS": (
                self.public_rate_limit_window_seconds,
                1,
                3600,
            ),
            "PUBLIC_MAX_BODY_BYTES": (self.public_max_body_bytes, 1024, 1048576),
            "PUBLIC_MAX_CONCURRENT_REQUESTS": (
                self.public_max_concurrent_requests,
                1,
                256,
            ),
        }
        for name, (value, minimum, maximum) in bounded_integers.items():
            if not minimum <= value <= maximum:
                raise ConfigurationError(
                    f"{name} must be between {minimum} and {maximum}"
                )
        if not 0.1 <= self.public_request_timeout_seconds <= 120.0:
            raise ConfigurationError(
                "PUBLIC_REQUEST_TIMEOUT_SECONDS must be between 0.1 and 120"
            )
