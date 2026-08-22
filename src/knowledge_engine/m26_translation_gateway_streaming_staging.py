from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from . import m26_public_api as public_api
from . import m26_public_api_execution_truth as execution_truth
from .m26_ask_api import M26AskApiError, _authorize_backend_request, validate_query_request
from .m26_translation_gateway import TRANSLATION_GATEWAY_SCHEMA, run_translation_gateway

# Importing execution_truth installs the already-accepted staging-only provider/runtime
# observability adapters on public_api. Reuse that exact app and add only the integration
# transport below. No semantic-core function is replaced here.
app = execution_truth.app

ALLOWED_FIELDS = {"question"}
MAX_BODY_BYTES = 4096


class _EdgeAuthenticatedQuotaAdapter:
    """No-op quota hooks for the separately authenticated edge-to-backend lane.

    Browser admission/rate limiting remains an edge concern on this path. The sealed
    answer stream calls only record_fallback() and release() on the quota object.
    """

    def record_fallback(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def release(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


_EDGE_QUOTA = _EdgeAuthenticatedQuotaAdapter()


def _integration_headers(request_id: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Request-Id": request_id,
    }


def _json_error(status_code: int, code: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "m26-translation-stream-error/v1",
            "status": "error",
            "code": code,
            "request_id": request_id,
        },
        status_code=status_code,
        headers=_integration_headers(request_id),
    )


@app.get("/v1/translation-gateway/health")
async def translation_gateway_health() -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": TRANSLATION_GATEWAY_SCHEMA,
            "status": "ok",
            "answers_url": "/v1/translation-gateway/answers",
            "contract": {
                "answer_language": "en",
                "phase": "translation-in-only",
                "language_scope": ["en", "zh-TW", "mixed zh-TW/English"],
                "sse_schema": public_api.EVENT_SCHEMA_VERSION,
            },
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/v1/translation-gateway/answers")
async def translation_gateway_answers(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _authorize_backend_request(request)
    except Exception:
        # Preserve the existing sanitized backend-auth HTTP exception contract.
        raise

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _json_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "M26_TG_BODY_TOO_LARGE",
            request_id,
        )
    try:
        payload = json.loads(body)
    except Exception:
        return _json_error(status.HTTP_400_BAD_REQUEST, "M26_TG_INVALID_JSON", request_id)
    if not isinstance(payload, dict):
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "M26_TG_REQUEST_NOT_JSON_OBJECT",
            request_id,
        )
    if set(payload) - ALLOWED_FIELDS:
        return _json_error(
            status.HTTP_400_BAD_REQUEST,
            "M26_TG_REQUEST_FIELD_DENIED",
            request_id,
        )
    try:
        question = validate_query_request(payload)
    except M26AskApiError as exc:
        return _json_error(status.HTTP_400_BAD_REQUEST, exc.reason_code, request_id)

    # The downstream callback is intentionally identity-only: it captures the exact
    # English question that the already-qualified Translation Gateway authorizes for
    # the sealed M26 runtime. English therefore bypasses translation exactly, while
    # zh-TW/mixed inputs pass through the existing protected-span + invariant gate.
    translated = run_translation_gateway(
        question=question,
        downstream=lambda value: {"translated_question_en": value},
        provider=None,
        correlation_id=request_id,
    )
    if not translated.ok:
        return JSONResponse(
            {
                "schema_version": "m26-translation-stream-error/v1",
                "status": "error",
                "code": translated.failure_code,
                "request_id": request_id,
                "translation_gateway": translated.observability,
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers=_integration_headers(request_id),
        )

    now = datetime.now(UTC)
    admission = public_api.Admission(
        request_id=request_id,
        ip_key="edge-authenticated",
        quota_day=now.strftime("%Y-%m-%d"),
        fallback_day=now.strftime("%Y-%m-%d"),
        accepted_at=now.isoformat().replace("+00:00", "Z"),
    )
    return StreamingResponse(
        public_api._answer_event_stream(
            request=request,
            question=translated.translated_question_en,
            admission=admission,
            ledger=_EDGE_QUOTA,  # type: ignore[arg-type]
            app_root=app.state.public_root,
            gate_path=app.state.public_gate_path,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers=_integration_headers(request_id),
    )


__all__ = ["app"]
