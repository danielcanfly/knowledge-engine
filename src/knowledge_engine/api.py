from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import Authenticator, Principal, authorization_header
from .config import Settings
from .errors import AuthorizationError, IntegrityError, KnowledgeEngineError
from .m14_feedback import FeedbackIntake
from .m14_feedback_contracts import PublicFeedbackReceipt, PublicFeedbackRequest
from .m14_feedback_widget import enable_feedback_widget_javascript
from .m14_interfaces import (
    PublicInterfaceCapabilities,
    normalize_interface_locale,
    public_ask_widget_javascript,
    public_interface_capabilities,
    public_interface_sse_events,
    standalone_ask_html,
)
from .m14_public_contracts import (
    PublicAskRequest,
    PublicAskResponse,
    PublicErrorDetail,
    PublicErrorResponse,
    public_response_from_runtime,
)
from .m14_security import (
    PublicAbuseController,
    PublicControlError,
    PublicEdgeSecurityMiddleware,
    PublicRequestIdentity,
    public_client_key,
    public_rejection_telemetry,
)
from .m14_security_contracts import (
    PublicProductCapabilities,
    harden_public_widget_javascript,
    public_product_capabilities,
)
from .m19_graph_api import (
    MAX_NEIGHBORHOOD_EDGES,
    MAX_NEIGHBORHOOD_NODES,
    MAX_OVERVIEW_EDGES,
    MAX_OVERVIEW_NODES,
    MAX_SEARCH_RESULTS,
    GraphApiLimitError,
    GraphApiNotFoundError,
    GraphApiRequestError,
    GraphApiUnavailableError,
    ReadOnlyGraphService,
)
from .runtime import Runtime
from .storage import create_object_store

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("knowledge-engine")


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    max_results: int = Field(default=10, ge=1, le=20)


class RefreshRequest(BaseModel):
    expected_release_id: str = Field(min_length=1, max_length=128)
    expected_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RefreshResponse(BaseModel):
    release_id: str
    manifest_sha256: str
    loaded_at: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache(maxsize=1)
def get_runtime() -> Runtime:
    settings = get_settings()
    return Runtime(
        create_object_store(settings),
        settings.cache_dir,
        settings.channel,
        relation_aware_expansion_enabled=(
            settings.relation_aware_expansion_enabled
        ),
    )


@lru_cache(maxsize=1)
def get_authenticator() -> Authenticator:
    return Authenticator(get_settings())


@lru_cache(maxsize=1)
def get_public_abuse_controller() -> PublicAbuseController:
    return PublicAbuseController(get_settings())


@lru_cache(maxsize=1)
def get_feedback_intake() -> FeedbackIntake:
    return FeedbackIntake(get_runtime().store)


def get_principal(
    authorization: str | None = Depends(authorization_header),
) -> Principal:
    try:
        return get_authenticator().authenticate(authorization)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "RUNTIME-003", "message": str(exc)},
        ) from exc


def get_public_principal(
    request: Request,
    authorization: str | None = Depends(authorization_header),
) -> Principal:
    try:
        return get_authenticator().authenticate_public(authorization)
    except AuthorizationError as exc:
        public_rejection_telemetry(
            reason="authentication",
            path=request.url.path,
            authenticated=False,
            status_code=401,
        )
        detail = PublicErrorDetail(
            code="PUBLIC-AUTH-401",
            message="public authentication is required or invalid",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail.model_dump(),
        ) from exc


def _raise_public_control_error(
    error: PublicControlError,
    *,
    path: str,
    authenticated: bool,
) -> None:
    public_rejection_telemetry(
        reason=error.code,
        path=path,
        authenticated=authenticated,
        status_code=error.status_code,
    )
    headers = (
        {"Retry-After": str(error.retry_after)}
        if error.retry_after is not None
        else None
    )
    detail = PublicErrorDetail(code=error.code, message=error.message)
    raise HTTPException(
        status_code=error.status_code,
        detail=detail.model_dump(),
        headers=headers,
    )


def get_public_request_identity(
    request: Request,
    principal: Principal = Depends(get_public_principal),
) -> PublicRequestIdentity:
    identity = PublicRequestIdentity(
        principal=principal,
        client_key=public_client_key(
            principal,
            request.client.host if request.client is not None else None,
        ),
    )
    try:
        get_public_abuse_controller().admit(identity.client_key)
    except PublicControlError as exc:
        _raise_public_control_error(
            exc,
            path=request.url.path,
            authenticated=principal.authenticated,
        )
    return identity


def _execute_with_public_controls(
    operation: Callable[[], Any],
    *,
    identity: PublicRequestIdentity,
    path: str,
) -> Any:
    try:
        return get_public_abuse_controller().execute(operation)
    except PublicControlError as exc:
        _raise_public_control_error(
            exc,
            path=path,
            authenticated=identity.principal.authenticated,
        )


app = FastAPI(title="Knowledge Engine", version="0.7.0")
app.add_middleware(PublicEdgeSecurityMiddleware, settings_provider=get_settings)


@app.get("/v1/health")
def health() -> dict:
    runtime = get_runtime()
    try:
        active = runtime.ensure_loaded()
    except (KnowledgeEngineError, FileNotFoundError) as exc:
        logger.warning("active release is not ready: %s", exc)
        return {
            "status": "starting",
            "release_id": None,
            "channel": runtime.channel,
        }
    return {
        "status": "healthy",
        "release_id": active.release_id,
        "manifest_sha256": active.manifest_sha256,
        "channel": runtime.channel,
    }


@app.get("/v1/releases/current")
def current_release(principal: Principal = Depends(get_principal)) -> dict:
    del principal
    try:
        active = get_runtime().ensure_loaded()
    except (KnowledgeEngineError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RUNTIME-001", "message": str(exc)},
        ) from exc
    return {
        "release_id": active.release_id,
        "manifest_sha256": active.manifest_sha256,
        "loaded_at": active.loaded_at,
    }


@app.post("/v1/releases/refresh", response_model=RefreshResponse)
def refresh_release(
    request: RefreshRequest,
    principal: Principal = Depends(get_principal),
) -> RefreshResponse:
    if "internal" not in principal.audiences:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "RUNTIME-003", "message": "internal access required"},
        )
    try:
        active = get_runtime().refresh(
            expected_release_id=request.expected_release_id,
            expected_manifest_sha256=request.expected_manifest_sha256,
        )
    except (IntegrityError, FileNotFoundError) as exc:
        logger.exception("release refresh failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RUNTIME-009", "message": str(exc)},
        ) from exc
    return RefreshResponse(
        release_id=active.release_id,
        manifest_sha256=active.manifest_sha256,
        loaded_at=active.loaded_at,
    )


@app.post("/v1/query")
def query(
    request: QueryRequest,
    principal: Principal = Depends(get_principal),
) -> dict:
    try:
        return get_runtime().query(
            request.query,
            set(principal.audiences),
            limit=request.max_results,
        )
    except IntegrityError as exc:
        logger.exception("query failed integrity check")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RUNTIME-002", "message": str(exc)},
        ) from exc


def _graph_service(principal: Principal) -> ReadOnlyGraphService:
    try:
        active = get_runtime().ensure_loaded()
        return ReadOnlyGraphService(active, set(principal.audiences))
    except (IntegrityError, FileNotFoundError) as exc:
        logger.exception("graph API release failed integrity validation")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "GRAPH-API-503", "message": "graph release is unavailable"},
        ) from exc


def _execute_graph(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return operation()
    except GraphApiNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GRAPH-API-404", "message": str(exc)},
        ) from exc
    except GraphApiUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "GRAPH-API-409", "message": str(exc)},
        ) from exc
    except GraphApiRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "GRAPH-API-422", "message": str(exc)},
        ) from exc
    except GraphApiLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "GRAPH-API-503", "message": str(exc)},
        ) from exc
    except IntegrityError as exc:
        logger.exception("graph API integrity check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "GRAPH-API-503", "message": "graph payload is unavailable"},
        ) from exc


@app.get("/v1/graph/capabilities")
def graph_capabilities(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(service.capabilities)


@app.get("/v1/graph/release")
def graph_release(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(service.release)


@app.get("/v1/graph/search")
def graph_search(
    q: str = Query(min_length=1, max_length=200),
    tags: list[str] = Query(default=[]),
    types: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=MAX_SEARCH_RESULTS),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(
        lambda: service.search(query=q, tags=tags, types=types, limit=limit)
    )


@app.get("/v1/graph/node/{concept_id:path}")
def graph_node(
    concept_id: str,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(lambda: service.node(concept_id))


@app.get("/v1/graph/neighborhood/{concept_id:path}")
def graph_neighborhood(
    concept_id: str,
    depth: int = Query(default=1, ge=1, le=1),
    relation_types: list[str] = Query(default=[]),
    max_nodes: int = Query(default=50, ge=1, le=MAX_NEIGHBORHOOD_NODES),
    max_edges: int = Query(default=100, ge=1, le=MAX_NEIGHBORHOOD_EDGES),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(
        lambda: service.neighborhood(
            concept_id,
            depth=depth,
            relation_types=relation_types,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
    )


@app.get("/v1/graph/overview")
def graph_overview(
    cluster_level: str = Query(default="none", max_length=40),
    max_nodes: int = Query(default=200, ge=1, le=MAX_OVERVIEW_NODES),
    max_edges: int = Query(default=400, ge=1, le=MAX_OVERVIEW_EDGES),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    service = _graph_service(principal)
    return _execute_graph(
        lambda: service.overview(
            cluster_level=cluster_level,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
    )


def _authorize_public_audience(audience: str, principal: Principal) -> None:
    if audience != "public" and not principal.authenticated:
        detail = PublicErrorDetail(
            code="PUBLIC-QUERY-403",
            message="authenticated audience authorization is required",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail.model_dump(),
        )
    if audience not in principal.audiences:
        detail = PublicErrorDetail(
            code="PUBLIC-QUERY-403",
            message=f"audience is not authorized: {audience}",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail.model_dump(),
        )


def _execute_public_ask(
    request: PublicAskRequest,
    principal: Principal,
) -> PublicAskResponse:
    _authorize_public_audience(request.audience, principal)
    try:
        runtime_result = get_runtime().query(
            request.query,
            {request.audience},
            limit=request.max_results,
        )
        return public_response_from_runtime(
            runtime_result,
            query=request.query,
            max_results=request.max_results,
            audience=request.audience,
        )
    except (IntegrityError, FileNotFoundError) as exc:
        logger.exception("public ask failed integrity check")
        detail = PublicErrorDetail(
            code="PUBLIC-QUERY-503",
            message="current knowledge release is unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail.model_dump(),
        ) from exc


def ask_capabilities() -> PublicInterfaceCapabilities:
    return public_interface_capabilities()


@app.get(
    "/v1/ask/capabilities",
    response_model=PublicProductCapabilities,
)
def ask_capabilities_endpoint() -> PublicProductCapabilities:
    return public_product_capabilities(get_settings())


@app.get("/ask", response_class=HTMLResponse, include_in_schema=False)
def ask_page(lang: str | None = None) -> HTMLResponse:
    locale = normalize_interface_locale(lang)
    return HTMLResponse(
        standalone_ask_html(locale),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; font-src 'none'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/embed/ask.js", include_in_schema=False)
def ask_widget_script() -> Response:
    script = harden_public_widget_javascript(public_ask_widget_javascript())
    script = enable_feedback_widget_javascript(script)
    return Response(
        script,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


def ask(
    request: PublicAskRequest,
    principal: Principal,
) -> PublicAskResponse:
    return _execute_public_ask(request, principal)


@app.post(
    "/v1/ask",
    response_model=PublicAskResponse,
    responses={
        401: {"model": PublicErrorResponse},
        403: {"model": PublicErrorResponse},
        413: {"model": PublicErrorResponse},
        429: {"model": PublicErrorResponse},
        503: {"model": PublicErrorResponse},
        504: {"model": PublicErrorResponse},
    },
)
def ask_endpoint(
    request: PublicAskRequest,
    identity: PublicRequestIdentity = Depends(get_public_request_identity),
) -> PublicAskResponse:
    return _execute_with_public_controls(
        lambda: ask(request, identity.principal),
        identity=identity,
        path="/v1/ask",
    )


def ask_stream(
    request: PublicAskRequest,
    principal: Principal,
) -> StreamingResponse:
    response = _execute_public_ask(request, principal)
    return StreamingResponse(
        public_interface_sse_events(response),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(
    "/v1/ask/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Deterministic public answer event stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        401: {"model": PublicErrorResponse},
        403: {"model": PublicErrorResponse},
        413: {"model": PublicErrorResponse},
        429: {"model": PublicErrorResponse},
        503: {"model": PublicErrorResponse},
        504: {"model": PublicErrorResponse},
    },
)
def ask_stream_endpoint(
    request: PublicAskRequest,
    identity: PublicRequestIdentity = Depends(get_public_request_identity),
) -> StreamingResponse:
    return _execute_with_public_controls(
        lambda: ask_stream(request, identity.principal),
        identity=identity,
        path="/v1/ask/stream",
    )


def feedback(
    request: PublicFeedbackRequest,
    identity: PublicRequestIdentity,
) -> PublicFeedbackReceipt:
    _authorize_public_audience(request.audience, identity.principal)
    try:
        return get_feedback_intake().submit(
            request,
            client_key=identity.client_key,
            authenticated=identity.principal.authenticated,
        )
    except ValueError as exc:
        detail = PublicErrorDetail(
            code="PUBLIC-FEEDBACK-422",
            message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail.model_dump(),
        ) from exc
    except (IntegrityError, FileNotFoundError) as exc:
        logger.exception("public feedback intake failed")
        detail = PublicErrorDetail(
            code="PUBLIC-FEEDBACK-503",
            message="feedback intake is temporarily unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail.model_dump(),
        ) from exc


@app.post(
    "/v1/feedback",
    response_model=PublicFeedbackReceipt,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": PublicErrorResponse},
        403: {"model": PublicErrorResponse},
        413: {"model": PublicErrorResponse},
        422: {"model": PublicErrorResponse},
        429: {"model": PublicErrorResponse},
        503: {"model": PublicErrorResponse},
        504: {"model": PublicErrorResponse},
    },
)
def feedback_endpoint(
    request: PublicFeedbackRequest,
    identity: PublicRequestIdentity = Depends(get_public_request_identity),
) -> PublicFeedbackReceipt:
    return _execute_with_public_controls(
        lambda: feedback(request, identity),
        identity=identity,
        path="/v1/feedback",
    )
