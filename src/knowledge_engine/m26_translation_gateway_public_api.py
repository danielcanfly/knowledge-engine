from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

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
    TranslationProviderError,
)
from .m26_retrieval_envelope import sha256_value
from .m26_translation_gateway import (
    TRANSLATION_GATEWAY_SCHEMA,
    TranslationGatewayError,
    TranslationGatewayFailure,
    run_owner_translation_gateway_for_web,
)

ALLOWED_FIELDS = {"question"}
MAX_BODY_BYTES = 4096
PUBLIC_ALLOWED_ORIGINS = [
    "https://staging.danielcanfly.com",
    "https://danielcanfly.com",
    "https://www.danielcanfly.com",
    "http://localhost:4321",
    "http://127.0.0.1:4321",
]


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
        title="M26 Answers Public API",
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_public_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
        expose_headers=["X-Request-Id"],
        max_age=600,
    )

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, Any]:
        return _public_health_payload()

    @app.post("/v1/answers")
    async def public_answers(request: Request) -> StreamingResponse:
        payload = await _read_payload(request)
        validate_query_request(payload)
        correlation_id = str(uuid.uuid4())
        stream = _answer_event_stream(
            app=app,
            payload=payload,
            owner_hash=_server_side_owner_hash(),
            correlation_id=correlation_id,
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
                "X-Request-Id": correlation_id,
            },
        )

    @app.get("/v1/translation-gateway/health")
    async def legacy_health(request: Request) -> dict[str, Any]:
        _authorize_backend_request(request)
        payload = _public_health_payload()
        payload["legacy_route"] = "/v1/translation-gateway/health"
        return payload

    @app.post("/v1/translation-gateway/query")
    async def legacy_query(request: Request) -> dict[str, Any]:
        owner_hash = _authorize_backend_request(request)
        payload = await _read_payload(request)
        try:
            validate_query_request(payload)
            provider = _app_translation_provider(app)
            return run_owner_translation_gateway_for_web(
                root=app.state.root,
                gate_path=app.state.gate_path,
                request_payload=payload,
                owner_subject_hash=owner_hash,
                provider=provider,
                correlation_id=str(uuid.uuid4()),
            )
        except TranslationProviderError as exc:
            raise _translation_gateway_http_error(
                TranslationGatewayFailure(
                    reason_code=exc.reason_code,
                    message="translation provider configuration failed",
                    observability={
                        "schema_version": TRANSLATION_GATEWAY_SCHEMA,
                        "gateway_failure_code": exc.reason_code,
                    },
                )
            ) from exc
        except TranslationGatewayError as exc:
            raise _translation_gateway_http_error(exc.failure) from exc

    return app


async def _read_payload(request: Request) -> dict[str, Any]:
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
    return payload


def _public_allowed_origins() -> list[str]:
    configured = os.environ.get("M26_PUBLIC_ALLOWED_ORIGINS", "").strip()
    if not configured:
        return list(PUBLIC_ALLOWED_ORIGINS)
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or list(PUBLIC_ALLOWED_ORIGINS)


def _public_health_payload() -> dict[str, Any]:
    return {
        "schema_version": TRANSLATION_GATEWAY_SCHEMA,
        "ok": True,
        "status": "ok",
        "surface": "/v1/answers",
        "canonical_host": "api-staging.danielcanfly.com",
        "production_host": "api.danielcanfly.com",
        "internal_owner_host": "m24-internal.danielcanfly.com",
        "transport": "text/event-stream",
        "legacy_namespace": "/api/rag/*",
        "legacy_namespace_status": "retired_compatibility_not_canonical",
        "legacy_api_rag_surface_canonical": False,
        "urls": {
            "canonical_answers_url": "https://api-staging.danielcanfly.com/v1/answers",
            "canonical_health_url": "https://api-staging.danielcanfly.com/v1/answers/health",
            "future_production_answers_url": "https://api.danielcanfly.com/v1/answers",
            "internal_owner_backend_url": "https://m24-internal.danielcanfly.com",
        },
        "legacy_routes": {
            "translation_gateway_query": "/v1/translation-gateway/query",
            "translation_gateway_health": "/v1/translation-gateway/health",
            "canonical": False,
        },
        "contract": {
            "answer_language": "en",
            "phase": "translation-in-with-sse",
            "language_scope": ["en", "zh-TW", "mixed zh-TW/English"],
            "semantic_qualification_status": "external_heldout_required",
            "legacy_api_rag_surface": {
                "canonical": False,
                "retired": True,
            },
        },
    }


async def _answer_event_stream(
    *,
    app: FastAPI,
    payload: dict[str, Any],
    owner_hash: str,
    correlation_id: str,
) -> AsyncIterator[str]:
    question = validate_query_request(payload)
    yield _sse_event(
        "meta",
        {
            "schema_version": "m26-answers-sse-meta/v1",
            "status": "accepted",
            "route": "/v1/answers",
            "transport": "text/event-stream",
            "correlation_id": correlation_id,
            "question_sha256": sha256_value(question),
            "surface": "/v1/answers",
            "canonical_answers_url": "https://api-staging.danielcanfly.com/v1/answers",
            "legacy_api_rag_surface_canonical": False,
        },
    )
    yield _sse_event(
        "progress",
        {
            "stage": "translation_in",
            "stages": ["translation_in"],
            "correlation_id": correlation_id,
        },
    )
    try:
        result = await asyncio.to_thread(
            _resolve_public_answer,
            app=app,
            payload={"question": question},
            owner_hash=owner_hash,
            correlation_id=correlation_id,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, Mapping) else {"message": str(exc.detail)}
        yield _sse_event("error", {"status": "error", "detail": detail})
        return
    except Exception as exc:
        yield _sse_event("error", {"status": "error", "detail": {"message": str(exc)}})
        return

    for stage in _stages_from_answer(result):
        yield _sse_event(
            "progress",
            {
                "stage": stage,
                "stages": [stage],
                "provider": _infer_provider(result),
                "correlation_id": correlation_id,
            },
        )
    yield _sse_event("answer", result)
    yield _sse_event("done", {"status": "ok", "correlation_id": correlation_id})


def _resolve_public_answer(
    *,
    app: FastAPI,
    payload: dict[str, Any],
    owner_hash: str,
    correlation_id: str,
) -> dict[str, Any]:
    try:
        provider = _app_translation_provider(app)
        return run_owner_translation_gateway_for_web(
            root=app.state.root,
            gate_path=app.state.gate_path,
            request_payload=payload,
            owner_subject_hash=owner_hash,
            provider=provider,
            public_request=True,
            correlation_id=correlation_id,
        )
    except TranslationProviderError as exc:
        raise _translation_gateway_http_error(
            TranslationGatewayFailure(
                reason_code=exc.reason_code,
                message="translation provider configuration failed",
                observability={
                    "schema_version": TRANSLATION_GATEWAY_SCHEMA,
                    "gateway_failure_code": exc.reason_code,
                },
            )
        ) from exc
    except TranslationGatewayError as exc:
        raise _translation_gateway_http_error(exc.failure) from exc


def _sse_event(event: str, payload: Mapping[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    for line in data.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _stages_from_answer(response: Mapping[str, Any]) -> list[str]:
    stages: list[str] = []
    translation = response.get("translation_gateway")
    if isinstance(translation, Mapping):
        if translation.get("translation_applied") is True:
            stages.append("translation_verified")
        if translation.get("invariant_check_result") == "pass":
            stages.append("invariant_check")
    runtime = response.get("runtime_observability")
    if isinstance(runtime, Mapping):
        for stage in runtime.get("stage_timings", []):
            if not isinstance(stage, Mapping):
                continue
            value = str(stage.get("stage", stage.get("name", ""))).strip()
            if value:
                stages.append(value)
    return stages or ["sealed_m26_runtime"]


def _infer_provider(response: Mapping[str, Any]) -> str | None:
    candidates = [
        response.get("provider_identity"),
        response.get("model_identity"),
        response.get("answer_source"),
    ]
    translation = response.get("translation_gateway")
    if isinstance(translation, Mapping):
        candidates.extend([translation.get("provider"), translation.get("model_resource")])
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip().lower()
        if "minimax" in normalized or "m3" in normalized:
            return "minimax"
        if "cloud" in normalized:
            return "cloudflare"
        if "google" in normalized or "translation" in normalized:
            return "google"
    return None


def _server_side_owner_hash() -> str:
    for name in (
        "STAGING_M26_OWNER_SUBJECT_HASH",
        "KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH",
        "M26_OWNER_SUBJECT_HASH",
    ):
        value = os.environ.get(name, "").strip().lower()
        if value:
            return value
    raise _http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "M26_PUBLIC_OWNER_HASH_UNCONFIGURED")


def _translation_gateway_http_error(failure: TranslationGatewayFailure) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": failure.reason_code,
            "message": "M26 translation gateway failed closed before sealed runtime",
            "observability": failure.observability,
        },
    )


app = create_app()


__all__ = [
    "ALLOWED_FIELDS",
    "BACKEND_TOKEN_HEADER",
    "OWNER_HASH_HEADER",
    "app",
    "create_app",
]
