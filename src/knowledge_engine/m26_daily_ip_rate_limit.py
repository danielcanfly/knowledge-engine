from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request

OWNER_BYPASS_HEADER = "x-m26-owner-bypass"
DEFAULT_DAILY_LIMIT = 10
DEFAULT_DAY_TZ = "UTC"
DEFAULT_DEV_IP_HASH_SECRET = "m26-local-dev-rate-limit-secret"
RETENTION_DAYS = 14


class M26DailyRateLimitConfigError(ValueError):
    """Fail-closed configuration error for public Ask Archive rate limiting."""


@dataclass(frozen=True)
class DailyRateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after_seconds: int
    bypassed: bool = False
    scope: str = "ip-day"

    @property
    def reset_header(self) -> str:
        return self.reset_at.isoformat().replace("+00:00", "Z")

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "X-M26-RateLimit-Limit": str(self.limit),
            "X-M26-RateLimit-Remaining": str(max(self.remaining, 0)),
            "X-M26-RateLimit-Reset": str(max(self.retry_after_seconds, 1)),
            "X-M26-RateLimit-Reset-At": self.reset_header,
            "X-M26-RateLimit-Scope": self.scope,
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(self.retry_after_seconds, 1))
        return headers

    @property
    def exceeded_body(self) -> dict[str, Any]:
        return {
            "error": "daily_rate_limit_exceeded",
            "message": "Daily question limit reached.",
            "quota": {
                "scope": self.scope,
                "limit": self.limit,
                "remaining": 0,
                "reset_at": self.reset_header,
                "reset_in_seconds": max(self.retry_after_seconds, 1),
            },
        }


@dataclass(frozen=True)
class DailyRateLimitConfig:
    limit: int
    db_path: Path
    day_tz: ZoneInfo
    ip_hash_secret: str
    owner_bypass_token_sha256: str

    @classmethod
    def from_env(cls) -> DailyRateLimitConfig:
        raw_limit = os.environ.get("M26_ASK_DAILY_IP_LIMIT", str(DEFAULT_DAILY_LIMIT)).strip()
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise M26DailyRateLimitConfigError("M26_ASK_DAILY_IP_LIMIT must be an integer") from exc
        if limit <= 0:
            raise M26DailyRateLimitConfigError("M26_ASK_DAILY_IP_LIMIT must be greater than zero")

        app_env = os.environ.get("APP_ENV", "").strip().lower()
        raw_db_path = os.environ.get("M26_ASK_RATE_LIMIT_DB_PATH", "").strip()
        if not raw_db_path and app_env == "production":
            raise M26DailyRateLimitConfigError("M26_ASK_RATE_LIMIT_DB_PATH required in production")
        db_path = Path(raw_db_path) if raw_db_path else _temporary_dev_db_path()

        day_tz_name = os.environ.get("M26_ASK_RATE_LIMIT_DAY_TZ", DEFAULT_DAY_TZ).strip()
        try:
            day_tz = ZoneInfo(day_tz_name or DEFAULT_DAY_TZ)
        except ZoneInfoNotFoundError as exc:
            raise M26DailyRateLimitConfigError("M26_ASK_RATE_LIMIT_DAY_TZ is invalid") from exc

        ip_hash_secret = os.environ.get("M26_ASK_RATE_LIMIT_IP_HASH_SECRET", "").strip()
        if not ip_hash_secret:
            if app_env == "production":
                raise M26DailyRateLimitConfigError(
                    "M26_ASK_RATE_LIMIT_IP_HASH_SECRET required in production"
                )
            ip_hash_secret = DEFAULT_DEV_IP_HASH_SECRET

        owner_digest = os.environ.get("M26_ASK_OWNER_BYPASS_TOKEN_SHA256", "").strip().lower()
        if owner_digest and not _is_sha256_hex(owner_digest):
            raise M26DailyRateLimitConfigError(
                "M26_ASK_OWNER_BYPASS_TOKEN_SHA256 must be a SHA-256 hex digest"
            )

        return cls(
            limit=limit,
            db_path=db_path,
            day_tz=day_tz,
            ip_hash_secret=ip_hash_secret,
            owner_bypass_token_sha256=owner_digest,
        )


class SQLiteDailyIPRateLimiter:
    def __init__(self, config: DailyRateLimitConfig) -> None:
        self.config = config
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def from_env(cls) -> SQLiteDailyIPRateLimiter:
        return cls(DailyRateLimitConfig.from_env())

    def check_request(self, request: Request) -> DailyRateLimitDecision:
        now = _now_utc()
        reset_at = _next_reset(now, self.config.day_tz)
        retry_after = max(1, int((reset_at - now).total_seconds()))
        if self._owner_bypass_matches(request):
            return DailyRateLimitDecision(
                allowed=True,
                limit=self.config.limit,
                remaining=self.config.limit,
                reset_at=reset_at,
                retry_after_seconds=retry_after,
                bypassed=True,
            )

        client_ip = _client_ip(request)
        day_key = _day_key(now, self.config.day_tz)
        ip_key = _hmac_ip_key(client_ip, secret=self.config.ip_hash_secret)
        count = self._increment(day_key=day_key, ip_key=ip_key, now=now)
        allowed = count <= self.config.limit
        return DailyRateLimitDecision(
            allowed=allowed,
            limit=self.config.limit,
            remaining=max(self.config.limit - count, 0),
            reset_at=reset_at,
            retry_after_seconds=retry_after,
        )

    def _owner_bypass_matches(self, request: Request) -> bool:
        expected_digest = self.config.owner_bypass_token_sha256
        if not expected_digest:
            return False
        supplied = request.headers.get(OWNER_BYPASS_HEADER, "")
        if not supplied:
            return False
        supplied_digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
        return hmac.compare_digest(supplied_digest, expected_digest)

    def _increment(self, *, day_key: str, ip_key: str, now: datetime) -> int:
        with sqlite3.connect(self.config.db_path.as_posix(), timeout=5) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO m26_ask_daily_ip_counts(day_key, ip_key, request_count, updated_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(day_key, ip_key) DO UPDATE SET
                    request_count = request_count + 1,
                    updated_at = excluded.updated_at
                """,
                (day_key, ip_key, now.isoformat()),
            )
            row = connection.execute(
                """
                SELECT request_count
                FROM m26_ask_daily_ip_counts
                WHERE day_key = ? AND ip_key = ?
                """,
                (day_key, ip_key),
            ).fetchone()
            cutoff = _day_key(now - timedelta(days=RETENTION_DAYS), self.config.day_tz)
            connection.execute(
                "DELETE FROM m26_ask_daily_ip_counts WHERE day_key < ?",
                (cutoff,),
            )
            connection.commit()
        return int(row[0])

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.config.db_path.as_posix(), timeout=5) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS m26_ask_daily_ip_counts (
                    day_key TEXT NOT NULL,
                    ip_key TEXT NOT NULL,
                    request_count INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (day_key, ip_key)
                )
                """
            )
            connection.commit()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _temporary_dev_db_path() -> Path:
    file_name = f"m26-ask-rate-limits-{os.getpid()}-{uuid.uuid4().hex}.sqlite3"
    return Path(tempfile.gettempdir()) / file_name


def _day_key(now: datetime, day_tz: ZoneInfo) -> str:
    return now.astimezone(day_tz).date().isoformat()


def _next_reset(now: datetime, day_tz: ZoneInfo) -> datetime:
    local = now.astimezone(day_tz)
    next_day = local.date() + timedelta(days=1)
    reset_local = datetime.combine(next_day, datetime.min.time(), tzinfo=day_tz)
    return reset_local.astimezone(UTC)


def _client_ip(request: Request) -> ipaddress._BaseAddress:
    candidates = [
        request.headers.get("cf-connecting-ip", ""),
        getattr(request.client, "host", "") if request.client else "",
    ]
    for candidate in candidates:
        value = candidate.strip()
        if not value:
            continue
        try:
            return ipaddress.ip_address(value)
        except ValueError:
            continue
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    if app_env in {"", "development", "test", "testing", "staging"}:
        return ipaddress.ip_address((127 << 24) + 1)
    raise M26DailyRateLimitConfigError("unable to determine valid client IP")


def _hmac_ip_key(client_ip: ipaddress._BaseAddress, *, secret: str) -> str:
    normalized = client_ip.compressed.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), normalized, hashlib.sha256).hexdigest()


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
