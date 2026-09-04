from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .m26_admin_auth import AccessJWTAuthenticator, AdminAccessSettings, LazyAccessJWTAuthenticator
from .m26_admin_contract import (
    ACCESS_ASSERTION_HEADER,
    ADMIN_CAPABILITY_STATES,
    ADMIN_PREFIX,
    DEFAULT_CONSOLE_ORIGIN,
    DEFAULT_STATE_CHANGING_ROUTES,
    AdminActor,
    AdminAPIError,
    AdminConfigurationError,
    AuditEvent,
    CapabilityGate,
    DefaultCapabilityProvider,
    IdempotencyCoordinator,
    InMemoryAuditSink,
    InMemoryIdempotencyStore,
    UnavailableAuditSink,
    UnavailableIdempotencyStore,
    build_audit_event,
    new_request_id,
    redact,
    utc_now,
    validate_idempotency_key,
)

_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_ALLOWED_HEADERS = frozenset({"accept", "content-type", "idempotency-key", "x-client-request-id"})
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AdminMutationRegistry:
    def __init__(self) -> None:
        self.rules: list[tuple[str, re.Pattern[str]]] = []

    def register(self, method: str, path_template: str) -> None:
        escaped = re.escape(path_template)
        pattern = re.compile("^" + re.sub(r"\\\{[^{}]+\\\}", "[^/]+", escaped) + "$")
        if not any(m == method.upper() and p.pattern == pattern.pattern for m, p in self.rules):
            self.rules.append((method.upper(), pattern))

    def is_state_changing(self, method: str, path: str) -> bool:
        return any(m == method.upper() and p.fullmatch(path) for m, p in self.rules)


def request_id_from(request: Request) -> str:
    return getattr(request.state, "admin_request_id", None) or new_request_id()


def actor_from(request: Request) -> AdminActor:
    actor = getattr(request.state, "admin_actor", None)
    if not isinstance(actor, AdminActor):
        raise AdminAPIError(
            status_code=500,
            code="ADMIN_ACTOR_CONTEXT_MISSING",
            message="Admin actor context is unavailable",
        )
    return actor


def envelope(
    request: Request,
    data: Any,
    *,
    source: str,
    freshness: str = "unknown",
    observed_at: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "observed_at": observed_at or utc_now(),
        "source": source,
        "freshness": freshness,
        "data": redact(data),
    }


def require_capability(
    request: Request, capability_id: str, *, mutation: bool = False
) -> CapabilityGate:
    provider = getattr(request.app.state, "admin_capability_provider", None)
    gate = provider.get_capability(capability_id) if provider else None
    if gate is None:
        raise AdminAPIError(
            status_code=409,
            code="ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
            message="Capability has not been qualified",
            details={"capability_id": capability_id, "state": "unavailable"},
        )
    if gate.state != "enabled" and (mutation or gate.state != "read_only"):
        raise AdminAPIError(
            status_code=409,
            code=gate.reason_code or "ADMIN_CAPABILITY_DISABLED",
            message="Capability is not available for this action",
            details={"capability_id": capability_id, "state": gate.state},
        )
    return gate


def append_audit_event(request: Request, event: AuditEvent) -> None:
    sink = getattr(request.app.state, "admin_audit_sink", None)
    if sink is None:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_AUDIT_SINK_UNAVAILABLE",
            message="A durable admin audit sink is not configured",
        )
    sink.append(event)


def _error_response(request_id: str, error: AdminAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        headers={"Cache-Control": "no-store", "X-Request-Id": request_id},
        content={
            "request_id": request_id,
            "observed_at": utc_now(),
            "error": {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": redact(error.details),
            },
        },
    )


def _scope_headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").casefold(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _cors(origin: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"access-control-allow-origin", origin.encode()),
        (b"access-control-allow-credentials", b"true"),
        (b"vary", b"Origin"),
    ]


class AdminControlPlaneMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticator: Any,
        console_origin: str,
        mutation_registry: AdminMutationRegistry,
    ) -> None:
        self.app = app
        self.authenticator = authenticator
        self.console_origin = console_origin
        self.mutation_registry = mutation_registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith(ADMIN_PREFIX):
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()
        headers = _scope_headers(scope)
        scope.setdefault("state", {})["admin_request_id"] = request_id
        method = str(scope.get("method", "GET")).upper()
        origin = headers.get("origin")
        if method == "OPTIONS":
            await self._preflight(request_id, origin, headers)(scope, receive, send)
            return
        if origin is not None and origin.rstrip("/") != self.console_origin:
            await _error_response(
                request_id,
                AdminAPIError(
                    status_code=403,
                    code="ADMIN_ORIGIN_DENIED",
                    message="Admin browser origin is not allowed",
                ),
            )(scope, receive, send)
            return
        try:
            actor = self.authenticator.authenticate(headers.get(ACCESS_ASSERTION_HEADER))
            scope["state"]["admin_actor"] = actor
            if method in _MUTATING:
                if actor.actor_type != "service" and origin != self.console_origin:
                    raise AdminAPIError(
                        status_code=403,
                        code="ADMIN_MUTATION_ORIGIN_REQUIRED",
                        message="Owner browser mutations require frozen console origin",
                    )
                content_type = headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                if content_type != "application/json":
                    raise AdminAPIError(
                        status_code=415,
                        code="ADMIN_JSON_REQUIRED",
                        message="Admin mutations require application/json",
                    )
                if self.mutation_registry.is_state_changing(method, str(scope.get("path", ""))):
                    validate_idempotency_key(headers.get("idempotency-key"))
        except AdminAPIError as exc:
            response = _error_response(request_id, exc)
            if origin == self.console_origin:
                response.raw_headers.extend(_cors(self.console_origin))
            await response(scope, receive, send)
            return

        async def admin_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                raw += [(b"x-request-id", request_id.encode()), (b"cache-control", b"no-store")]
                if origin == self.console_origin:
                    raw += _cors(self.console_origin)
                message["headers"] = raw
            await send(message)

        await self.app(scope, receive, admin_send)

    def _preflight(
        self, request_id: str, origin: str | None, headers: Mapping[str, str]
    ) -> Response:
        if origin is None or origin.rstrip("/") != self.console_origin:
            return _error_response(
                request_id,
                AdminAPIError(
                    status_code=403,
                    code="ADMIN_ORIGIN_DENIED",
                    message="Admin browser origin is not allowed",
                ),
            )
        method = headers.get("access-control-request-method", "").upper()
        requested = {
            item.strip().casefold()
            for item in headers.get("access-control-request-headers", "").split(",")
            if item.strip()
        }
        if method not in _ALLOWED_METHODS:
            return _error_response(
                request_id,
                AdminAPIError(
                    status_code=403,
                    code="ADMIN_CORS_METHOD_DENIED",
                    message="Requested admin method is not allowed",
                ),
            )
        if not requested.issubset(_ALLOWED_HEADERS):
            return _error_response(
                request_id,
                AdminAPIError(
                    status_code=403,
                    code="ADMIN_CORS_HEADER_DENIED",
                    message="Requested admin headers are not allowed",
                ),
            )
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": self.console_origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": ", ".join(sorted(_ALLOWED_METHODS)),
                "Access-Control-Allow-Headers": ", ".join(sorted(_ALLOWED_HEADERS)),
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
                "Cache-Control": "no-store",
                "X-Request-Id": request_id,
            },
        )


def _router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["AdminFoundation"])

    @router.get("/session", operation_id="getAdminSession")
    async def session(request: Request) -> dict[str, Any]:
        return envelope(
            request,
            {
                "actor": actor_from(request).safe_payload(),
                "auth": {
                    "provider": "cloudflare_access",
                    "backend_validation": "required",
                    "cookie_is_authority": False,
                },
            },
            source="admin_control_plane",
            freshness="live",
        )

    @router.get("/capabilities", operation_id="getAdminCapabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        provider = request.app.state.admin_capability_provider
        return envelope(
            request,
            {
                "states": sorted(ADMIN_CAPABILITY_STATES),
                "capabilities": [item.to_payload() for item in provider.list_capabilities()],
                "default_when_missing": {
                    "state": "unavailable",
                    "reason_code": "ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
                },
            },
            source="capability_gate",
            freshness="unknown",
        )

    return router


async def _admin_error_handler(request: Request, exc: AdminAPIError) -> JSONResponse:
    return _error_response(request_id_from(request), exc)


async def _validation_handler(request: Request, exc: RequestValidationError) -> Response:
    if request.url.path.startswith(ADMIN_PREFIX):
        return _error_response(
            request_id_from(request),
            AdminAPIError(
                status_code=422,
                code="ADMIN_REQUEST_VALIDATION_FAILED",
                message="Admin request validation failed",
                details={"errors": exc.errors()},
            ),
        )
    return await request_validation_exception_handler(request, exc)


async def _http_handler(request: Request, exc: StarletteHTTPException) -> Response:
    if request.url.path.startswith(ADMIN_PREFIX):
        detail = exc.detail if isinstance(exc.detail, Mapping) else {}
        return _error_response(
            request_id_from(request),
            AdminAPIError(
                status_code=exc.status_code,
                code=str(detail.get("code") or "ADMIN_HTTP_ERROR"),
                message=str(detail.get("message") or "Admin request failed"),
            ),
        )
    return await http_exception_handler(request, exc)


def install_admin_control_plane(
    app: FastAPI,
    *,
    authenticator: Any | None = None,
    console_origin: str = DEFAULT_CONSOLE_ORIGIN,
    capability_provider: Any | None = None,
    audit_sink: Any | None = None,
    idempotency_store: Any | None = None,
) -> FastAPI:
    if getattr(app.state, "admin_control_plane_installed", False):
        return app
    if console_origin.rstrip("/") != DEFAULT_CONSOLE_ORIGIN:
        raise AdminConfigurationError("Admin console origin is frozen")
    app.state.admin_capability_provider = capability_provider or DefaultCapabilityProvider()
    app.state.admin_audit_sink = audit_sink or UnavailableAuditSink()
    store = idempotency_store or UnavailableIdempotencyStore()
    app.state.admin_idempotency_store = store
    app.state.admin_idempotency = IdempotencyCoordinator(store)
    registry = AdminMutationRegistry()
    for method, path in DEFAULT_STATE_CHANGING_ROUTES:
        registry.register(method, path)
    app.state.admin_mutation_registry = registry
    app.include_router(_router())
    app.add_exception_handler(AdminAPIError, _admin_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_middleware(
        AdminControlPlaneMiddleware,
        authenticator=authenticator or LazyAccessJWTAuthenticator(),
        console_origin=DEFAULT_CONSOLE_ORIGIN,
        mutation_registry=registry,
    )
    app.state.admin_control_plane_installed = True
    return app


__all__ = [
    "ACCESS_ASSERTION_HEADER",
    "ADMIN_CAPABILITY_STATES",
    "ADMIN_PREFIX",
    "AdminAPIError",
    "AdminAccessSettings",
    "AdminActor",
    "AdminConfigurationError",
    "AdminMutationRegistry",
    "AccessJWTAuthenticator",
    "AuditEvent",
    "CapabilityGate",
    "DEFAULT_CONSOLE_ORIGIN",
    "DEFAULT_STATE_CHANGING_ROUTES",
    "IdempotencyCoordinator",
    "InMemoryAuditSink",
    "InMemoryIdempotencyStore",
    "append_audit_event",
    "build_audit_event",
    "envelope",
    "install_admin_control_plane",
    "redact",
    "require_capability",
    "validate_idempotency_key",
]
