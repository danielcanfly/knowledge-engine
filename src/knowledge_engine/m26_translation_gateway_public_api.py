from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections.abc import Callable, Mapping
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization", OWNER_HASH_HEADER],
        expose_headers=["X-Request-Id"],
        max_age=600,
    )

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

    @app.get("/v1/answers/health")
    async def public_health(request: Request) -> dict[str, Any]:
        return _public_health_payload(base_url=_origin_base_url(request))

    @app.post("/v1/answers")
    async def public_answers(request: Request) -> StreamingResponse:
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
        validate_query_request(payload)
        correlation_id = str(uuid.uuid4())
        base_url = _origin_base_url(request)
        stream = _answer_event_stream(
            app=app,
            base_url=base_url,
            payload=payload,
            correlation_id=correlation_id,
        )
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
            },
        )

    return app
def _allowed_origins() -> list[str]:
    configured = os.environ.get("M26_PUBLIC_ALLOWED_ORIGINS", "").strip()
    if not configured:
        return [
            "https://staging.danielcanfly.com",
            "https://www.danielcanfly.com",
            "https://danielcanfly.com",
            "http://localhost:4321",
            "http://127.0.0.1:4321",
        ]
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or [
        "https://staging.danielcanfly.com",
        "https://www.danielcanfly.com",
        "https://danielcanfly.com",
        "http://localhost:4321",
        "http://127.0.0.1:4321",
    ]


def _origin_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _public_health_payload(*, base_url: str) -> dict[str, Any]:
    return {
        "schema_version": TRANSLATION_GATEWAY_SCHEMA,
        "ok": True,
        "status": "ok",
        "surface": {
            "canonical_answers_url": f"{base_url}/v1/answers",
            "canonical_health_url": f"{base_url}/v1/answers/health",
            "future_production_answers_url": "https://api.danielcanfly.com/v1/answers",
            "internal_owner_backend_url": "https://m24-internal.danielcanfly.com",
            "legacy_translation_gateway_url": f"{base_url}/v1/translation-gateway/query",
            "legacy_translation_gateway_health_url": f"{base_url}/v1/translation-gateway/health",
            "legacy_api_rag_surface_canonical": False,
        },
        "contract": {
            "answer_language": "en",
            "phase": "translation-in-with-sse",
            "semantic_qualification_status": "external_heldout_required",
            "legacy_api_rag_surface": {
                "canonical": False,
                "retired": True,
            },
        },
    }


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


async def _answer_event_stream(
    *,
    app: FastAPI,
    base_url: str,
    payload: dict[str, Any],
    correlation_id: str,
):
    question = validate_query_request(payload)
    question_sha256 = sha256_value(question)
    owner_hash = _server_side_owner_hash()
    meta = {
        "schema_version": "m26-answers-sse-meta/v1",
        "status": "accepted",
        "route": "/v1/answers",
        "correlation_id": correlation_id,
        "question_sha256": question_sha256,
        "surface": {
            "canonical_answers_url": f"{base_url}/v1/answers",
            "canonical_health_url": f"{base_url}/v1/answers/health",
            "future_production_answers_url": "https://api.danielcanfly.com/v1/answers",
            "internal_owner_backend_url": "https://m24-internal.danielcanfly.com",
            "legacy_api_rag_surface_canonical": False,
        },
    }
    yield _sse_event("meta", meta)
    seen: list[str] = ["translation_in"]
    yield _sse_event("progress", {"stage": "translation_in", "stages": list(seen)})
    try:
        result = await asyncio.to_thread(
            _resolve_answer,
            app=app,
            payload={"question": question},
            owner_hash=owner_hash,
            correlation_id=correlation_id,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        yield _sse_event(
            "error",
            {
                "status": "error",
                "detail": detail,
                "correlation_id": correlation_id,
            },
        )
        return
    except Exception as exc:
        yield _sse_event(
            "error",
            {
                "status": "error",
                "detail": {"message": str(exc)},
                "correlation_id": correlation_id,
            },
        )
        return
    stages = _sse_stages_for_response(result)
    for stage in stages:
        if stage and stage not in seen:
            seen.append(stage)
            yield _sse_event(
                "progress",
                {
                    "stage": stage,
                    "stages": list(seen),
                    "provider": _infer_provider(result),
                },
            )
    yield _sse_event("answer", result)
    yield _sse_event("done", {"status": "ok", "correlation_id": correlation_id})


def _sse_event(event: str, payload: Mapping[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    for line in data.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _sse_stages_for_response(response: Mapping[str, Any]) -> list[str]:
    stages: list[str] = []
    translation = response.get("translation_gateway")
    if isinstance(translation, Mapping):
        if translation.get("translation_applied") is True:
            stages.append("translation_in")
        if translation.get("invariant_check_result") == "pass":
            stages.append("translation_verified")
    runtime = response.get("runtime_observability")
    if isinstance(runtime, Mapping):
        for stage in runtime.get("stage_timings", []):
            if not isinstance(stage, Mapping):
                continue
            value = str(stage.get("stage", stage.get("name", ""))).strip()
            if not value:
                continue
            normalized = value.lower()
            if "retrieval" in normalized:
                stages.append("retrieval")
            elif "parent" in normalized or "compress" in normalized or "reorder" in normalized:
                stages.append("organizing")
            elif "synthesis" in normalized or "generate" in normalized or "answer" in normalized:
                stages.append("synthesis")
            elif "citation" in normalized or "verify" in normalized or "check" in normalized:
                stages.append("citation_check")
            elif "retry" in normalized or "repair" in normalized:
                stages.append("reflect_retry")
            else:
                stages.append(value)
    if not stages:
        stages.append("synthesis")
    return stages


def _infer_provider(response: Mapping[str, Any]) -> str | None:
    candidates = [
        response.get("provider_identity"),
        response.get("model_identity"),
        response.get("answer_source"),
    ]
    translation = response.get("translation_gateway")
    if isinstance(translation, Mapping):
        candidates.extend(
            [
                translation.get("provider"),
                translation.get("model_resource"),
            ]
        )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip().lower()
        if not normalized:
            continue
        if "minimax" in normalized or normalized == "mini" or "m3" in normalized:
            return "minimax"
        if "cloud" in normalized:
            return "cloudflare"
    return None


def _resolve_answer(
    *,
    app: FastAPI,
    payload: dict[str, Any],
    owner_hash: str,
    correlation_id: str,
) -> dict[str, Any]:
    try:
        return run_owner_translation_gateway_for_web(
            root=app.state.root,
            gate_path=app.state.gate_path,
            request_payload=payload,
            owner_subject_hash=owner_hash,
            public_request=True,
            correlation_id=correlation_id,
        )
    except TranslationGatewayError as exc:
        raise _translation_gateway_http_error(exc.failure) from exc


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
