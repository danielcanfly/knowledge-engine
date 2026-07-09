from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .auth import Authenticator, Principal, authorization_header
from .config import Settings
from .errors import AuthorizationError, IntegrityError, KnowledgeEngineError
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
    )


@lru_cache(maxsize=1)
def get_authenticator() -> Authenticator:
    return Authenticator(get_settings())


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


app = FastAPI(title="Knowledge Engine", version="0.5.0")


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


def _execute_public_ask(
    request: PublicAskRequest,
    principal: Principal,
) -> PublicAskResponse:
    if request.audience not in principal.audiences:
        detail = PublicErrorDetail(
            code="PUBLIC-QUERY-403",
            message=f"audience is not authorized: {request.audience}",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail.model_dump(),
        )
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


@app.get(
    "/v1/ask/capabilities",
    response_model=PublicInterfaceCapabilities,
)
def ask_capabilities() -> PublicInterfaceCapabilities:
    return public_interface_capabilities()


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
    return Response(
        public_ask_widget_javascript(),
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post(
    "/v1/ask",
    response_model=PublicAskResponse,
    responses={
        403: {"model": PublicErrorResponse},
        503: {"model": PublicErrorResponse},
    },
)
def ask(
    request: PublicAskRequest,
    principal: Principal = Depends(get_principal),
) -> PublicAskResponse:
    return _execute_public_ask(request, principal)


@app.post(
    "/v1/ask/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Deterministic public answer event stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        403: {"model": PublicErrorResponse},
        503: {"model": PublicErrorResponse},
    },
)
def ask_stream(
    request: PublicAskRequest,
    principal: Principal = Depends(get_principal),
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
