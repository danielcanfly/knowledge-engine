from __future__ import annotations

import asyncio
import contextlib
import json
import os
import queue
import time
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import m26_public_api as public_api
from .m26_multilingual_language_envelope import (
    AnswerLanguage,
    detect_input_language,
    requested_answer_language,
)
from .m26_multilingual_runtime import (
    MultilingualRuntimeDependencies,
    MultilingualRuntimeResult,
    run_track2_multilingual_request,
)

TRACK2_PUBLIC_HEALTH_SCHEMA = "danielcanfly-track2-multilingual-health/v1"
TRACK2_PUBLIC_REQUEST_SCHEMA = "danielcanfly-track2-multilingual-answer-request/v1"
TRACK2_EVENT_SCHEMA_VERSION = public_api.EVENT_SCHEMA_VERSION
TRACK2_REAUTHORIZED_START_SHA = "73b4c49db112f3673d154306da8acc566bae9bd6"
TRACK1_BASE_SHA = "dbbe645b40817b2c5cec1ac215e25628cbdc4199"
ALLOWED_ANSWER_LANGUAGES = {"auto", "en", "zh-TW"}
ALLOWED_FIELDS = {"question", "answer_language"}
FORBIDDEN_SELECTION_FIELDS = {
    "provider",
    "model",
    "reviewer_model",
    "verifier_model",
    "dense_backend",
    "retrieval_mode",
    "thresholds",
    "repair_count",
}

Track2Runner = Callable[..., MultilingualRuntimeResult]


def create_app(
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    quota_ledger: public_api.PublicQuotaLedger | None = None,
    runtime_dependencies: MultilingualRuntimeDependencies | None = None,
    track2_runner: Track2Runner = run_track2_multilingual_request,
) -> FastAPI:
    app_root = (root or Path(os.environ.get("KNOWLEDGE_ENGINE_ROOT", "."))).resolve()
    resolved_gate_path = gate_path or Path(
        os.environ.get("M26_PA7_GATE_PATH", public_api.DEFAULT_GATE_PATH.as_posix())
    )
    if not resolved_gate_path.is_absolute():
        resolved_gate_path = app_root / resolved_gate_path
    ledger = quota_ledger or public_api.PublicQuotaLedger(
        Path(
            os.environ.get(
                "M26_TRACK2_PUBLIC_QUOTA_DB",
                "/tmp/knowledge-engine-track2-public-api/quota.sqlite3",
            )
        )
    )
    dependencies = runtime_dependencies or MultilingualRuntimeDependencies()
    app = FastAPI(title="M26 Track 2 Multilingual Public Answers API", version="1.0.0")
    app.state.track2_public_root = app_root
    app.state.track2_public_gate_path = resolved_gate_path
    app.state.track2_public_quota_ledger = ledger
    app.state.track2_runtime_dependencies = dependencies

    @app.get("/v1/health")
    async def health(request: Request) -> JSONResponse:
        request_id = public_api._request_id()  # noqa: SLF001
        origin = public_api._request_origin(request)  # noqa: SLF001
        candidate_sha = os.environ.get(
            "M26_TRACK2_CANDIDATE_SHA",
            TRACK2_REAUTHORIZED_START_SHA,
        )
        return JSONResponse(
            {
                "schema_version": TRACK2_PUBLIC_HEALTH_SCHEMA,
                "status": "ok",
                "request_id": request_id,
                "track": 2,
                "multilingual": True,
                "candidate_sha": candidate_sha,
                "reauthorized_start_sha": TRACK2_REAUTHORIZED_START_SHA,
                "base_sha": TRACK1_BASE_SHA,
                "production_mutated": False,
                "production_multilingual_enabled": False,
                "answers_url": "/v1/answers",
                "limits": public_api._limits_dto(),  # noqa: SLF001
            },
            headers=public_api._response_headers(origin=origin),  # noqa: SLF001
        )

    @app.options("/v1/answers")
    async def answers_options(request: Request) -> Response:
        origin = public_api._request_origin(request)  # noqa: SLF001
        if not public_api._origin_allowed(origin):  # noqa: SLF001
            return public_api._problem_response(  # noqa: SLF001
                public_api.Problem(
                    status.HTTP_403_FORBIDDEN,
                    "PUBLIC_ADMISSION_DENIED",
                    "Origin is not allowed",
                    "This browser origin is not allowed to call the public answer API.",
                ),
                request_id=public_api._request_id(),  # noqa: SLF001
                origin=None,
            )
        return Response(
            status_code=204,
            headers=public_api._preflight_headers(origin=origin),  # noqa: SLF001
        )

    @app.post("/v1/answers")
    async def answers(request: Request) -> Response:
        request_id = public_api._request_id()  # noqa: SLF001
        origin = public_api._request_origin(request)  # noqa: SLF001
        if not public_api._origin_allowed(origin):  # noqa: SLF001
            return public_api._problem_response(  # noqa: SLF001
                public_api.Problem(
                    status.HTTP_403_FORBIDDEN,
                    "PUBLIC_ADMISSION_DENIED",
                    "Origin is not allowed",
                    "This browser origin is not allowed to call the public answer API.",
                ),
                request_id=request_id,
                origin=None,
            )
        problem = public_api._readiness_problem(request_id, require_owner=True)  # noqa: SLF001
        if problem is not None:
            return public_api._problem_response(problem, request_id=request_id, origin=origin)  # noqa: SLF001
        parsed, problem = _parse_track2_public_request(await request.body())
        if problem is not None:
            return public_api._problem_response(problem, request_id=request_id, origin=origin)  # noqa: SLF001
        assert parsed is not None
        detected = detect_input_language(parsed["question"])
        requested = requested_answer_language(
            detected_input_language=detected,
            answer_language=parsed["answer_language"],  # type: ignore[arg-type]
        )
        ip_key = public_api._pseudonymous_ip_key(  # noqa: SLF001
            request,
            now=public_api.datetime.now(public_api.UTC),
        )
        provider_problem = public_api._provider_guard_problem()  # noqa: SLF001
        if provider_problem is not None:
            return public_api._problem_response(  # noqa: SLF001
                provider_problem,
                request_id=request_id,
                origin=origin,
            )
        fallback_problem = ledger.fallback_budget_available()
        if fallback_problem is not None and public_api._fallback_expected():  # noqa: SLF001
            return public_api._problem_response(  # noqa: SLF001
                fallback_problem,
                request_id=request_id,
                origin=origin,
            )
        admission_problem = ledger.admit(ip_key=ip_key)
        if admission_problem is not None:
            return public_api._problem_response(  # noqa: SLF001
                admission_problem,
                request_id=request_id,
                origin=origin,
            )
        admission = public_api.Admission(
            request_id=request_id,
            ip_key=ip_key,
            quota_day=public_api.datetime.now(public_api.UTC).strftime("%Y-%m-%d"),
            fallback_day=public_api.datetime.now(public_api.UTC).strftime("%Y-%m-%d"),
            accepted_at=public_api._utc_now(),  # noqa: SLF001
        )
        if detected == "en" and requested == "en":
            return StreamingResponse(
                public_api._answer_event_stream(  # noqa: SLF001
                    request=request,
                    question=parsed["question"],
                    admission=admission,
                    ledger=ledger,
                    app_root=app_root,
                    gate_path=resolved_gate_path,
                ),
                media_type="text/event-stream; charset=utf-8",
                headers=public_api._stream_headers(origin=origin),  # noqa: SLF001
            )
        return StreamingResponse(
            _track2_answer_event_stream(
                request=request,
                question=parsed["question"],
                answer_language=parsed["answer_language"],  # type: ignore[arg-type]
                admission=admission,
                ledger=ledger,
                dependencies=dependencies,
                track2_runner=track2_runner,
            ),
            media_type="text/event-stream; charset=utf-8",
            headers=public_api._stream_headers(origin=origin),  # noqa: SLF001
        )

    return app


def _parse_track2_public_request(
    body: bytes,
) -> tuple[dict[str, str] | None, public_api.Problem | None]:
    if len(body) > public_api.MAX_BODY_BYTES:
        return None, public_api.Problem(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "REQUEST_BODY_TOO_LARGE",
            "Request body is too large",
            "The request body exceeds the public API size limit.",
        )
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_JSON",
            "Invalid JSON",
            "The request body must be valid JSON.",
        )
    if not isinstance(value, Mapping):
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "REQUEST_NOT_OBJECT",
            "Request must be an object",
            "The request body must be a JSON object.",
        )
    forbidden = sorted(set(value) & FORBIDDEN_SELECTION_FIELDS)
    if forbidden:
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "PROVIDER_SELECTION_FORBIDDEN",
            "Provider selection is forbidden",
            "The Track 2 staging API does not accept provider, model, "
            "retrieval, threshold, or repair selection.",
        )
    extra = sorted(set(value) - ALLOWED_FIELDS)
    if extra:
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "UNSUPPORTED_FIELD",
            "Unsupported request field",
            "The Track 2 staging API accepts only question and answer_language.",
        )
    question = value.get("question")
    if not isinstance(question, str):
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "QUESTION_MISSING",
            "Question is missing",
            "The request body must include a question string.",
        )
    normalized = " ".join(question.strip().split())
    if not normalized:
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "QUESTION_EMPTY",
            "Question is empty",
            "Please enter a question.",
        )
    if len(normalized) > public_api.MAX_QUERY_CHARS:
        return None, public_api.Problem(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "QUESTION_TOO_LONG",
            "Question is too long",
            "The question exceeds the public API character limit.",
        )
    answer_language = value.get("answer_language", "auto")
    if answer_language not in ALLOWED_ANSWER_LANGUAGES:
        return None, public_api.Problem(
            status.HTTP_400_BAD_REQUEST,
            "ANSWER_LANGUAGE_INVALID",
            "Answer language is invalid",
            "answer_language must be auto, en, or zh-TW.",
        )
    return {
        "question": normalized,
        "answer_language": str(answer_language),
    }, None


async def _track2_answer_event_stream(
    *,
    request: Request,
    question: str,
    answer_language: AnswerLanguage,
    admission: public_api.Admission,
    ledger: public_api.PublicQuotaLedger,
    dependencies: MultilingualRuntimeDependencies,
    track2_runner: Track2Runner,
) -> AsyncIterator[str]:
    seq = 0
    terminal_sent = False
    event_queue: queue.Queue[Mapping[str, Any] | object] = queue.Queue()
    done = object()
    started = time.monotonic()

    def emit(event_type: str, **fields: Any) -> str:
        nonlocal seq
        seq += 1
        event = {
            "schema_version": TRACK2_EVENT_SCHEMA_VERSION,
            "seq": seq,
            "request_id": admission.request_id,
            "type": event_type,
            "created_at": public_api._utc_now(),  # noqa: SLF001
            **fields,
        }
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        return f"id: {seq}\nevent: {event_type}\ndata: {payload}\n\n"

    def sink(event: Mapping[str, Any]) -> None:
        event_queue.put(_sanitize_track2_event(event))

    async def worker() -> None:
        try:
            result = await asyncio.to_thread(
                track2_runner,
                question=question,
                answer_language=answer_language,
                dependencies=dependencies,
                event_sink=sink,
                trace_id=admission.request_id,
            )
            event_queue.put({"type": "_result", "result": result})
        except Exception as exc:
            event_queue.put({"type": "_error", "error": exc})
        finally:
            event_queue.put(done)

    task = asyncio.create_task(worker())
    next_heartbeat = time.monotonic() + public_api.HEARTBEAT_SECONDS
    yield emit(
        "request.accepted",
        accepted_at=admission.accepted_at,
        limits=public_api._limits_dto(),  # noqa: SLF001
    )
    try:
        while True:
            if await request.is_disconnected():
                yield emit(
                    "answer.cancelled",
                    code="CLIENT_DISCONNECTED",
                    detail="The client disconnected before the answer stream completed.",
                    retryable=True,
                )
                terminal_sent = True
                task.cancel()
                break
            if time.monotonic() - started >= public_api.HARD_DEADLINE_SECONDS:
                yield emit(
                    "answer.failed",
                    code="ANSWER_TIMEOUT",
                    detail="The answer exceeded the 90 second staging deadline.",
                    retryable=True,
                )
                terminal_sent = True
                task.cancel()
                break
            try:
                item = event_queue.get_nowait()
            except queue.Empty:
                if time.monotonic() >= next_heartbeat:
                    yield ": heartbeat\n\n"
                    next_heartbeat = time.monotonic() + public_api.HEARTBEAT_SECONDS
                await asyncio.sleep(0.05)
                continue
            if item is done:
                break
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "_result":
                result = item.get("result")
                if isinstance(result, MultilingualRuntimeResult):
                    terminal = _terminal_event_from_track2_result(result)
                else:
                    terminal = _track2_failure_terminal(
                        "TRACK2_RUNTIME_INVALID",
                        "Track 2 runtime returned an invalid result.",
                    )
                yield emit(str(terminal.pop("type")), **terminal)
                terminal_sent = True
                continue
            if item.get("type") == "_error":
                yield emit(
                    "answer.failed",
                    code="TRACK2_RUNTIME_FAILED",
                    detail="The Track 2 staging runtime failed before publication.",
                    retryable=True,
                )
                terminal_sent = True
                continue
            event_type = str(item.get("type", "stage.completed"))
            fields = {key: value for key, value in item.items() if key != "type"}
            yield emit(event_type, **fields)
    finally:
        ledger.release(ip_key=admission.ip_key)
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    if not terminal_sent:
        yield emit(
            "answer.failed",
            code="STREAM_PROTOCOL_FAILED",
            detail="The answer stream ended before a terminal answer event was produced.",
            retryable=True,
        )


def _terminal_event_from_track2_result(result: MultilingualRuntimeResult) -> dict[str, Any]:
    if result.status == "failed":
        return _track2_failure_terminal(
            result.failure_code or "TRACK2_RUNTIME_FAILED",
            result.failure_detail or "The Track 2 staging runtime failed.",
        )
    payload: dict[str, Any] = {
        "type": result.terminal_event_type,
        "answer_text": result.answer_text,
        "citations": list(result.citations),
        "answer_claims": list(result.answer_claims),
        "requested_answer_language": result.requested_answer_language,
        "detected_input_language": result.detected_input_language,
        "final_visible_language": result.final_visible_language,
        "canonical_claim_count": result.canonical_claim_count,
        "canonical_dropped_claim_count": result.canonical_dropped_claim_count,
        "visible_claim_count": result.visible_claim_count,
        "language_dropped_claim_count": result.language_dropped_claim_count,
        "unsupported_accepted_claims": result.unsupported_accepted_claims,
        "citation_locator_valid": result.citation_locator_valid,
        "material_claim_support_verified": result.material_claim_support_verified,
        "reason_codes": list(result.reason_codes),
        "telemetry": dict(result.telemetry),
    }
    if result.status == "abstained":
        payload["code"] = result.failure_code or "TRACK2_LANGUAGE_ABSTAINED"
        payload["detail"] = (
            result.failure_detail or "No verified requested-language answer survived."
        )
        payload["retryable"] = False
        payload["answer_text"] = ""
    return payload


def _track2_failure_terminal(code: str, detail: str) -> dict[str, Any]:
    return {
        "type": "answer.failed",
        "code": code,
        "detail": detail,
        "retryable": True,
    }


def _sanitize_track2_event(event: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "type",
        "stage",
        "status",
        "attempt",
        "role",
        "provider",
        "model",
        "latency_ms",
        "error_class",
        "detected_input_language",
        "requested_answer_language",
        "candidate_union_count",
        "selected_evidence_count",
    }
    return {key: value for key, value in event.items() if key in allowed_keys}


app = create_app()
