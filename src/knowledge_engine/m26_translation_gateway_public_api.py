from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from .m26_ask_api import (
    BACKEND_TOKEN_HEADER,
    DEFAULT_GATE_PATH,
    OWNER_HASH_HEADER,
    _authorize_backend_request,
    _http_error,
    validate_query_request,
)
from .m26_google_translation_provider import (
    GoogleTranslationLLMProvider,
    TranslationProvider,
    TranslationProviderConfig,
)
from .m26_translation_gateway import (
    TRANSLATION_GATEWAY_SCHEMA,
    TranslationGatewayError,
    run_owner_translation_gateway_for_web,
)

ALLOWED_FIELDS = {"question"}
MAX_BODY_BYTES = 4096


def _default_provider_factory() -> TranslationProvider:
    return GoogleTranslationLLMProvider(TranslationProviderConfig.from_env())


def _app_translation_provider(app: FastAPI) -> TranslationProvider:
    provider = getattr(app.state, "translation_provider", None)
    if provider is not None:
        return provider
    with app.state.translation_provider_lock:
        provider = getattr(app.state, "translation_provider", None)
        if provider is None:
            provider = app.state.translation_provider_factory()
            app.state.translation_provider = provider
        return provider


@asynccontextmanager
async def _lifespan(app: FastAPI) -> Any:
    try:
        yield
    finally:
        provider = getattr(app.state, "translation_provider", None)
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def create_app(
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    translation_provider: TranslationProvider | None = None,
    provider_factory: Callable[[], TranslationProvider] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="M26 Translation-In Gateway Staging API",
        version="1.0.0",
        lifespan=_lifespan,
    )
    app.state.root = root or Path.cwd()
    app.state.gate_path = gate_path or Path(
        os.environ.get("M26_PA7_GATE_PATH", DEFAULT_GATE_PATH.as_posix())
    )
    app.state.translation_provider = translation_provider
    app.state.translation_provider_factory = provider_factory or _default_provider_factory
    app.state.translation_provider_lock = threading.Lock()

    @app.get("/v1/translation-gateway/health")
    async def health() -> dict[str, Any]:
        return {
            "schema_version": TRANSLATION_GATEWAY_SCHEMA,
            "status": "ok",
            "contract": {
                "answer_language": "en",
                "phase": "translation-in-only",
                "language_scope": ["en", "zh-TW", "mixed zh-TW/English"],
                "semantic_qualification_status": "external_heldout_required",
            },
        }

    @app.post("/v1/translation-gateway/query")
    async def query(request: Request) -> dict[str, Any]:
        owner_hash = _authorize_backend_request(request)
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise _http_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "M26_TG_BODY_TOO_LARGE")
        try:
            payload = await request.json()
        except Exception as exc:
            raise _http_error(status.HTTP_400_BAD_REQUEST, "M26_TG_INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise _http_error(status.HTTP_400_BAD_REQUEST, "M26_TG_REQUEST_NOT_JSON_OBJECT")
        unknown = set(payload) - ALLOWED_FIELDS
        if unknown:
            raise _http_error(status.HTTP_400_BAD_REQUEST, "M26_TG_REQUEST_FIELD_DENIED")
        try:
            validate_query_request(payload)
            return run_owner_translation_gateway_for_web(
                root=app.state.root,
                gate_path=app.state.gate_path,
                request_payload=payload,
                owner_subject_hash=owner_hash,
                provider=_app_translation_provider(app),
                correlation_id=str(uuid.uuid4()),
            )
        except TranslationGatewayError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": exc.reason_code,
                    "message": "M26 translation gateway failed closed before sealed runtime",
                    "observability": exc.failure.observability,
                },
            ) from exc

    return app


app = create_app()


__all__ = [
    "ALLOWED_FIELDS",
    "BACKEND_TOKEN_HEADER",
    "OWNER_HASH_HEADER",
    "app",
    "create_app",
]
