from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import Principal
from .config import Settings

logger = logging.getLogger("knowledge-engine.public-security")

PUBLIC_API_PATHS = {
    "/v1/ask",
    "/v1/ask/stream",
    "/v1/ask/capabilities",
}
PUBLIC_ASSET_PATHS = {"/ask", "/embed/ask.js"}
PUBLIC_PATHS = PUBLIC_API_PATHS | PUBLIC_ASSET_PATHS
PUBLIC_POST_PATHS = {"/v1/ask", "/v1/ask/stream"}


@dataclass(frozen=True)
class PublicControlError(Exception):
    status_code: int
    code: str
    message: str
    retry_after: int | None = None


@dataclass(frozen=True)
class PublicRequestIdentity:
    principal: Principal
    client_key: str


@dataclass
class _Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> int | None:
        current = time.monotonic() if now is None else now
        with self._lock:
            window = self._windows.get(key)
            if window is None or current - window.started_at >= self.window_seconds:
                self._windows[key] = _Window(started_at=current, count=1)
                self._prune(current)
                return None
            if window.count >= self.limit:
                remaining = self.window_seconds - (current - window.started_at)
                return max(1, math.ceil(remaining))
            window.count += 1
            return None

    def _prune(self, now: float) -> None:
        if len(self._windows) <= 4096:
            return
        expired = [
            key
            for key, window in self._windows.items()
            if now - window.started_at >= self.window_seconds
        ]
        for key in expired:
            self._windows.pop(key, None)


class PublicExecutionGate:
    def __init__(self, max_concurrent: int, timeout_seconds: float) -> None:
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="public-ask",
        )

    def execute(self, operation: Callable[[], Any]) -> Any:
        if not self._slots.acquire(blocking=False):
            raise PublicControlError(
                status_code=429,
                code="PUBLIC-QUERY-OVERLOADED",
                message="public query capacity is temporarily exhausted",
                retry_after=1,
            )
        future: Future[Any] = self._executor.submit(operation)
        release_here = True
        try:
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            release_here = False
            future.add_done_callback(self._release_after_completion)
            raise PublicControlError(
                status_code=504,
                code="PUBLIC-QUERY-TIMEOUT",
                message="public query exceeded the execution time limit",
                retry_after=1,
            ) from exc
        finally:
            if release_here:
                self._slots.release()

    def _release_after_completion(self, _: Future[Any]) -> None:
        self._slots.release()


class PublicAbuseController:
    def __init__(self, settings: Settings) -> None:
        self.rate_limiter = FixedWindowRateLimiter(
            settings.public_rate_limit_requests,
            settings.public_rate_limit_window_seconds,
        )
        self.execution_gate = PublicExecutionGate(
            settings.public_max_concurrent_requests,
            settings.public_request_timeout_seconds,
        )

    def admit(self, client_key: str) -> None:
        retry_after = self.rate_limiter.check(client_key)
        if retry_after is not None:
            raise PublicControlError(
                status_code=429,
                code="PUBLIC-QUERY-RATE-LIMITED",
                message="public query rate limit exceeded",
                retry_after=retry_after,
            )

    def execute(self, operation: Callable[[], Any]) -> Any:
        return self.execution_gate.execute(operation)


def public_client_key(principal: Principal, client_host: str | None) -> str:
    identity = (
        f"subject:{principal.subject}"
        if principal.authenticated
        else f"anonymous:{client_host or 'unknown'}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def public_rejection_telemetry(
    *,
    reason: str,
    path: str,
    authenticated: bool | None,
    status_code: int,
) -> None:
    route_class = "ask" if path in PUBLIC_POST_PATHS else "public_surface"
    logger.warning(
        "public_request_rejected reason=%s route_class=%s authenticated=%s status=%s",
        reason,
        route_class,
        authenticated,
        status_code,
    )


def _headers(scope: Scope) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in scope.get("headers", [])}


def _decode_header(headers: dict[bytes, bytes], name: bytes) -> str | None:
    value = headers.get(name)
    if value is None:
        return None
    return value.decode("latin-1").strip()


def _request_origin(scope: Scope, headers: dict[bytes, bytes]) -> str:
    host = _decode_header(headers, b"host")
    if not host:
        server = scope.get("server")
        if isinstance(server, tuple) and len(server) == 2:
            host = f"{server[0]}:{server[1]}"
        else:
            host = ""
    return f"{scope.get('scheme', 'http')}://{host}".rstrip("/")


def _normalized_origin(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def is_public_origin_allowed(
    origin: str | None,
    *,
    request_origin: str,
    allowed_origins: tuple[str, ...],
) -> bool:
    if origin is None:
        return True
    normalized = _normalized_origin(origin)
    if normalized is None:
        return False
    allowed = {_normalized_origin(item) for item in allowed_origins}
    return normalized == _normalized_origin(request_origin) or normalized in allowed


def public_error_payload(code: str, message: str) -> bytes:
    return json.dumps(
        {
            "detail": {
                "schema_version": "knowledge-engine-public-query/v1/error",
                "code": code,
                "message": message,
                "request_id": None,
            }
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def public_security_headers(path: str) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (
            b"permissions-policy",
            b"camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        ),
    ]
    if path == "/ask":
        headers.append((b"cross-origin-opener-policy", b"same-origin"))
    if path == "/embed/ask.js":
        headers.append((b"cross-origin-resource-policy", b"cross-origin"))
    return headers


def _cors_headers(origin: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"access-control-allow-origin", origin.encode("latin-1")),
        (b"access-control-allow-credentials", b"false"),
        (b"vary", b"Origin"),
    ]


async def _send_error(
    send: Send,
    *,
    status_code: int,
    code: str,
    message: str,
    path: str,
    retry_after: int | None = None,
    cors_origin: str | None = None,
) -> None:
    body = public_error_payload(code, message)
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        *public_security_headers(path),
    ]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode("ascii")))
    if cors_origin is not None:
        headers.extend(_cors_headers(cors_origin))
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class PublicEdgeSecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        settings_provider: Callable[[], Settings],
    ) -> None:
        self.app = app
        self.settings_provider = settings_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if path not in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        settings = self.settings_provider()
        headers = _headers(scope)
        origin = _decode_header(headers, b"origin")
        request_origin = _request_origin(scope, headers)
        allowed = is_public_origin_allowed(
            origin,
            request_origin=request_origin,
            allowed_origins=settings.public_allowed_origins,
        )
        if not allowed:
            public_rejection_telemetry(
                reason="origin",
                path=path,
                authenticated=None,
                status_code=403,
            )
            await _send_error(
                send,
                status_code=403,
                code="PUBLIC-ORIGIN-403",
                message="request origin is not allowed",
                path=path,
            )
            return
        cors_origin = origin if origin is not None else None
        method = str(scope.get("method") or "GET").upper()
        if method == "OPTIONS" and path in PUBLIC_API_PATHS:
            response_headers = [
                (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                (
                    b"access-control-allow-headers",
                    b"authorization, content-type",
                ),
                (b"access-control-max-age", b"300"),
                (b"content-length", b"0"),
                *public_security_headers(path),
            ]
            if cors_origin is not None:
                response_headers.extend(_cors_headers(cors_origin))
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": response_headers,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return
        if method == "POST" and path in PUBLIC_POST_PATHS:
            content_length = _decode_header(headers, b"content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = settings.public_max_body_bytes + 1
                if declared_size > settings.public_max_body_bytes:
                    public_rejection_telemetry(
                        reason="body_size",
                        path=path,
                        authenticated=None,
                        status_code=413,
                    )
                    await _send_error(
                        send,
                        status_code=413,
                        code="PUBLIC-QUERY-BODY-TOO-LARGE",
                        message="public query request body is too large",
                        path=path,
                        cors_origin=cors_origin,
                    )
                    return
            receive = self._limited_receive(
                receive,
                settings.public_max_body_bytes,
            )
        response_started = False

        async def secure_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_headers = list(message.get("headers", []))
                existing = {name.lower() for name, _ in response_headers}
                for name, value in public_security_headers(path):
                    if name not in existing:
                        response_headers.append((name, value))
                if cors_origin is not None:
                    for name, value in _cors_headers(cors_origin):
                        if name not in existing:
                            response_headers.append((name, value))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, secure_send)
        except _BodyTooLarge:
            if response_started:
                raise
            public_rejection_telemetry(
                reason="body_size",
                path=path,
                authenticated=None,
                status_code=413,
            )
            await _send_error(
                send,
                status_code=413,
                code="PUBLIC-QUERY-BODY-TOO-LARGE",
                message="public query request body is too large",
                path=path,
                cors_origin=cors_origin,
            )

    @staticmethod
    def _limited_receive(receive: Receive, limit: int) -> Receive:
        total = 0

        async def limited() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise _BodyTooLarge
            return message

        return limited


class _BodyTooLarge(Exception):
    pass
