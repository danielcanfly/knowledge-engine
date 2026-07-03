from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from .auth import Authenticator, Principal, authorization_header
from .config import Settings
from .errors import AuthorizationError, IntegrityError, KnowledgeEngineError
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


app = FastAPI(title="Knowledge Engine", version="0.3.0")


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
