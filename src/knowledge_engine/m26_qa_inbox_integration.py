from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .m26_admin_contract import AdminAPIError
from .m26_admin_control_plane import require_capability
from .m26_admin_qa import (
    QA_CAPABILITY_DETAIL,
    QA_CAPABILITY_EVENTS,
    QA_CAPABILITY_EXPORT,
    QaReadResult,
    install_admin_qa,
)
from .qa_answer_quality import (
    _normalize_country,
    _normalize_country_filter,
    submit_answer_capture,
)
from .qa_answer_quality_evaluator import (
    AnswerQualitySemanticEvaluator,
    ProviderAnswerQualityEvaluator,
    UnavailableAnswerQualityEvaluator,
)
from .qa_answer_quality_sqlite import SqliteQaRepository
from .storage import create_object_store

QA_INBOX_PREFIX = "/v1/admin/qa/inbox"
QA_MAX_CAPTURE_BYTES = 2_000_000
QA_COUNTRY_TRUST_ENV = "M26_QA_TRUST_CLOUDFLARE_COUNTRY"


class QaLifecycleRequest(BaseModel):
    state: str = Field(min_length=2, max_length=32)
    reason: str | None = Field(default=None, max_length=500)
    resolved_by_release: str | None = Field(default=None, max_length=256)


class QaExportRequest(BaseModel):
    mode: Literal["new", "selected", "current_filter"] = "new"
    include_previously_exported: bool = False
    event_ids: list[str] = Field(default_factory=list, max_length=500)
    cluster_ids: list[str] = Field(default_factory=list, max_length=500)
    range_name: str = Field(default="24h", max_length=16)
    from_ts: str | None = Field(default=None, max_length=64)
    to_ts: str | None = Field(default=None, max_length=64)
    search: str | None = Field(default=None, max_length=500)
    result: str | None = Field(default=None, max_length=32)
    evaluation_status: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=8)
    lifecycle: str | None = Field(default=None, max_length=32)


@lru_cache(maxsize=1)
def qa_repository_from_env() -> SqliteQaRepository:
    return SqliteQaRepository(create_object_store(Settings.from_env()))


@lru_cache(maxsize=1)
def qa_evaluator_from_env() -> AnswerQualitySemanticEvaluator:
    """Reuse the qualified M26 reviewer client and fail closed when unconfigured."""
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        return UnavailableAnswerQualityEvaluator()
    from .m26_pa5_v8_live import MODEL, MiniMaxClient

    client = MiniMaxClient(api_key, max_calls=20_000, max_cost=Decimal("100"))
    return ProviderAnswerQualityEvaluator(
        client,
        provider_name="minimax",
        model=MODEL,
    )


class RepositoryQaEventSource:
    """Compatibility adapter for the pre-P0 QA list/detail endpoints."""

    def __init__(self, repository_provider: Callable[[], SqliteQaRepository]) -> None:
        self._repository_provider = repository_provider

    def list_events(self, *, event_class: str | None, release_id: str | None) -> QaReadResult:
        page = self._repository_provider().list_events(range_name="90d", limit=500)
        rows = [_legacy_event(row) for row in page["items"]]
        if event_class:
            rows = [row for row in rows if row.get("outcome") == event_class]
        if release_id:
            rows = [row for row in rows if row.get("release_id") == release_id]
        return QaReadResult(
            availability="available",
            reason_code=None,
            detail=None,
            provenance_source="answer_quality_inbox",
            data={"events": rows},
            observed_at=None,
            freshness="near_live",
            resource_identity={"kind": "qa_answer_quality_index", "schema": "v1"},
        )

    def get_event(self, trace_id: str) -> QaReadResult:
        repository = self._repository_provider()
        page = repository.list_events(range_name="90d", limit=500)
        event = next(
            (
                row
                for row in page["items"]
                if str(row.get("trace_id")) == trace_id or str(row.get("event_id")) == trace_id
            ),
            None,
        )
        if event is None:
            return QaReadResult(
                availability="unavailable",
                reason_code="QA_TRACE_NOT_OBSERVED",
                detail="The requested QA event is not present in the durable inbox.",
                provenance_source="answer_quality_inbox",
                data=None,
                observed_at=None,
                freshness="near_live",
            )
        detail = repository.get_event(str(event["event_id"]))
        return QaReadResult(
            availability="available",
            reason_code=None,
            detail=None,
            provenance_source="answer_quality_inbox",
            data={"event": _legacy_event(detail)},
            observed_at=str(detail.get("timestamp") or "") or None,
            freshness="near_live",
            resource_identity={"kind": "qa_answer_quality_event", "event_id": detail["event_id"]},
        )


class QaAnswerCaptureMiddleware:
    """Fail-open observer for the canonical public /v1/answers SSE surface."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        repository_provider: Callable[[], SqliteQaRepository],
        evaluator_provider: Callable[[], AnswerQualitySemanticEvaluator],
    ) -> None:
        self.app = app
        self.repository_provider = repository_provider
        self.evaluator_provider = evaluator_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("path") != "/v1/answers"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                await self.app(scope, _single_message_then_receive(message, receive), send)
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
            if len(body) > 16_384:
                await self.app(scope, _body_replay_receive(bytes(body), receive), send)
                return

        response_body = bytearray()
        response_content_type = ""
        response_status = 0

        async def capture_send(message: Message) -> None:
            nonlocal response_content_type, response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status", 0))
                headers = {
                    key.decode("latin-1").casefold(): value.decode("latin-1")
                    for key, value in message.get("headers", [])
                }
                response_content_type = headers.get("content-type", "")
            elif message.get("type") == "http.response.body":
                chunk = message.get("body", b"")
                if len(response_body) < QA_MAX_CAPTURE_BYTES:
                    remaining = QA_MAX_CAPTURE_BYTES - len(response_body)
                    response_body.extend(chunk[:remaining])
                if not message.get("more_body", False):
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    await send(message)
                    self._submit(
                        scope=scope,
                        request_body=bytes(body),
                        response_status=response_status,
                        response_content_type=response_content_type,
                        response_body=bytes(response_body),
                        latency_ms=latency_ms,
                    )
                    return
            await send(message)

        await self.app(scope, _body_replay_receive(bytes(body), receive), capture_send)

    def _submit(
        self,
        *,
        scope: Scope,
        request_body: bytes,
        response_status: int,
        response_content_type: str,
        response_body: bytes,
        latency_ms: int,
    ) -> None:
        if response_status != 200 or "text/event-stream" not in response_content_type.casefold():
            return
        try:
            request_payload = json.loads(request_body.decode("utf-8"))
            question = str(request_payload.get("question") or "").strip()
            if not question:
                return
            events = _parse_sse(response_body.decode("utf-8", errors="replace"))
            answer = next((payload for name, payload in reversed(events) if name == "answer"), None)
            error = next((payload for name, payload in reversed(events) if name == "error"), None)
            correlation_id = _correlation_id(events)
            if not isinstance(answer, Mapping):
                answer = {
                    "request_id": correlation_id,
                    "status": "error" if error else "degraded",
                    "answer_text": "",
                    "reason_codes": _error_reason_codes(error),
                }
            normalized_answer = dict(answer)
            normalized_answer.setdefault("request_id", correlation_id)
            from .m26_public_api import consume_qa_internal_context

            normalized_answer.update(consume_qa_internal_context(correlation_id))
            if error and "reason_codes" not in normalized_answer:
                normalized_answer["reason_codes"] = _error_reason_codes(error)
            trace = {
                "correlation_id": correlation_id,
                "provider_events": [
                    payload
                    for name, payload in events
                    if name
                    in {"model_started", "model_completed", "stage_started", "stage_completed"}
                ],
                "sse_terminal": error or {"status": "ok"},
                "timing": {"total_ms": latency_ms},
            }
            submit_answer_capture(
                self.repository_provider,
                question=question,
                response=normalized_answer,
                latency_ms=latency_ms,
                country=_trusted_country(scope),
                trace=trace,
                evaluator=self.evaluator_provider(),
            )
        except Exception:
            return


def _body_replay_receive(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def _single_message_then_receive(first: Message, receive: Receive) -> Receive:
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return first
        return await receive()

    return replay


def _trusted_country(scope: Scope) -> str:
    if os.environ.get(QA_COUNTRY_TRUST_ENV, "").strip().casefold() not in {"1", "true", "yes"}:
        return "ZZ"
    headers = {
        key.decode("latin-1").casefold(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }
    if not headers.get("cf-ray"):
        return "ZZ"
    return _normalize_country(headers.get("cf-ipcountry"))


def _parse_sse(value: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in value.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            events.append((name, dict(payload)))
    return events


def _correlation_id(events: list[tuple[str, dict[str, Any]]]) -> str:
    for _, payload in events:
        candidate = payload.get("correlation_id") or payload.get("request_id")
        if candidate:
            return str(candidate)
    return "qa-correlation-unavailable"


def _error_reason_codes(error: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(error, Mapping):
        return []
    detail = error.get("detail")
    if isinstance(detail, Mapping):
        code = detail.get("code")
        if code:
            return [str(code)]
    status_value = error.get("status")
    return [str(status_value)] if status_value else ["PUBLIC_ANSWER_ERROR"]


def _legacy_event(event: Mapping[str, Any]) -> dict[str, Any]:
    release = (
        event.get("release_identity") if isinstance(event.get("release_identity"), Mapping) else {}
    )
    failure_trace = (
        event.get("failure_trace") if isinstance(event.get("failure_trace"), Mapping) else {}
    )
    synthesis = (
        failure_trace.get("synthesis_validation")
        if isinstance(failure_trace.get("synthesis_validation"), Mapping)
        else {}
    )
    citations = synthesis.get("citations", [])
    return {
        "trace_id": event.get("trace_id"),
        "timestamp": event.get("timestamp"),
        "release_id": release.get("release_id"),
        "outcome": event.get("failure_class") or event.get("result"),
        "question": event.get("question"),
        "answer": synthesis.get("answer"),
        "provider": None,
        "fallback": None,
        "retrieval_status": event.get("failure_class"),
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "latency_ms": event.get("latency_ms"),
        "reason_code": event.get("failure_signature"),
        "qa": event,
    }


def _inbox_router(repository_provider: Callable[[], SqliteQaRepository]) -> APIRouter:
    router = APIRouter(prefix=QA_INBOX_PREFIX, tags=["QAInbox"])

    @router.get("/events", operation_id="listQaInboxEvents")
    async def list_inbox_events(
        request: Request,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
        search: str | None = None,
        result: str | None = None,
        evaluation_status: str | None = None,
        country: str | None = None,
        lifecycle: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_EVENTS)
        try:
            normalized_country = (
                _normalize_country_filter(country) if country is not None else None
            )
        except ValueError as exc:
            raise AdminAPIError(
                status_code=422,
                code="QA_COUNTRY_INVALID",
                message=str(exc),
            ) from exc
        try:
            data = repository_provider().list_events(
                range_name=range_name,
                from_ts=from_ts,
                to_ts=to_ts,
                search=search,
                result=result,
                evaluation_status=evaluation_status,
                country=normalized_country,
                lifecycle=lifecycle,
                limit=max(1, min(limit, 500)),
                cursor=cursor,
            )
        except ValueError as exc:
            raise AdminAPIError(
                status_code=422,
                code="QA_RANGE_INVALID",
                message=str(exc),
            ) from exc
        return {"data": data}

    @router.get("/events/{event_id}", operation_id="getQaInboxEvent")
    async def get_inbox_event(request: Request, event_id: str) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_DETAIL)
        try:
            return {"data": repository_provider().get_event(event_id)}
        except KeyError as exc:
            raise AdminAPIError(
                status_code=404,
                code="QA_EVENT_NOT_FOUND",
                message="QA event not found",
            ) from exc

    @router.get("/summary", operation_id="getQaInboxSummary")
    async def get_inbox_summary(
        request: Request,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_EVENTS)
        try:
            return {
                "data": repository_provider().summary(
                    range_name=range_name,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
            }
        except ValueError as exc:
            raise AdminAPIError(
                status_code=422,
                code="QA_RANGE_INVALID",
                message=str(exc),
            ) from exc

    @router.get("/clusters", operation_id="listQaFailureClusters")
    async def list_clusters(request: Request, lifecycle: str | None = None) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_EVENTS)
        return {"data": {"items": repository_provider().list_clusters(lifecycle=lifecycle)}}

    @router.post(
        "/clusters/{cluster_id}/lifecycle",
        operation_id="updateQaFailureClusterLifecycle",
    )
    async def update_lifecycle(
        request: Request,
        cluster_id: str,
        payload: QaLifecycleRequest,
    ) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_EXPORT, mutation=True)
        try:
            cluster = repository_provider().transition_cluster(
                cluster_id,
                state=payload.state,
                reason=payload.reason,
                resolved_by_release=payload.resolved_by_release,
            )
        except KeyError as exc:
            raise AdminAPIError(
                status_code=404,
                code="QA_CLUSTER_NOT_FOUND",
                message="QA cluster not found",
            ) from exc
        except ValueError as exc:
            raise AdminAPIError(
                status_code=409,
                code="QA_LIFECYCLE_INVALID",
                message=str(exc),
            ) from exc
        return {"data": cluster}

    @router.post(
        "/export-jsonl",
        operation_id="exportQaNewFailuresJsonl",
        responses={
            200: {
                "headers": {
                    "X-QA-Export-Mode": {
                        "description": "Applied export mode.",
                        "schema": {
                            "type": "string",
                            "enum": ["new", "selected", "current_filter"],
                        },
                    },
                    "X-QA-Export-Reused": {
                        "description": "Whether an existing export batch was reused.",
                        "schema": {"type": "string", "enum": ["true", "false"]},
                    },
                }
            }
        },
    )
    async def export_jsonl(request: Request, payload: QaExportRequest) -> Response:
        require_capability(request, QA_CAPABILITY_EXPORT, mutation=True)
        repository = repository_provider()
        try:
            filter_fields_set = any(
                (
                    payload.from_ts,
                    payload.to_ts,
                    payload.search,
                    payload.result,
                    payload.evaluation_status,
                    payload.country,
                    payload.lifecycle,
                )
            ) or payload.range_name != "24h"
            selection_fields_set = bool(payload.event_ids or payload.cluster_ids)
            if payload.mode == "new":
                if payload.include_previously_exported:
                    raise ValueError(
                        "include_previously_exported is not valid for primary new-failures export"
                    )
                if selection_fields_set or filter_fields_set:
                    raise ValueError(
                        "new export does not accept selection/filter fields; use selected or current_filter"
                    )
                result = repository.export_new_failures()
            elif payload.mode == "selected":
                if payload.include_previously_exported or filter_fields_set:
                    raise ValueError("selected export accepts only event_ids/cluster_ids")
                result = repository.export_selected_failures(
                    event_ids=payload.event_ids,
                    cluster_ids=payload.cluster_ids,
                )
            else:
                if payload.include_previously_exported or selection_fields_set:
                    raise ValueError("current_filter export accepts filters, not selected IDs")
                result = repository.export_filtered_failures(
                    range_name=payload.range_name,
                    from_ts=payload.from_ts,
                    to_ts=payload.to_ts,
                    search=payload.search,
                    result=payload.result,
                    evaluation_status=payload.evaluation_status,
                    country=payload.country,
                    lifecycle=payload.lifecycle,
                )
        except ValueError as exc:
            raise AdminAPIError(
                status_code=422,
                code="QA_EXPORT_REQUEST_INVALID",
                message=str(exc),
            ) from exc
        if "jsonl" not in result:
            return Response(status_code=204)
        return Response(
            content=str(result["jsonl"]),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{result["batch_id"]}.jsonl"',
                "X-QA-Export-Batch": str(result["batch_id"]),
                "X-QA-Export-SHA256": str(result["sha256"]),
                "X-QA-Export-Mode": str(result.get("mode") or "new"),
                "X-QA-Export-Reused": "true" if result.get("reused") else "false",
            },
        )

    return router


def install_qa_inbox(
    app: FastAPI,
    *,
    repository_provider: Callable[[], SqliteQaRepository] = qa_repository_from_env,
    evaluator_provider: Callable[[], AnswerQualitySemanticEvaluator] = qa_evaluator_from_env,
) -> FastAPI:
    if getattr(app.state, "qa_answer_quality_inbox_installed", False):
        return app
    install_admin_qa(app, source=RepositoryQaEventSource(repository_provider))
    app.include_router(_inbox_router(repository_provider))
    registry = getattr(app.state, "admin_mutation_registry", None)
    if registry is not None:
        registry.register("POST", f"{QA_INBOX_PREFIX}/clusters/{{cluster_id}}/lifecycle")
        registry.register("POST", f"{QA_INBOX_PREFIX}/export-jsonl")
    app.add_middleware(
        QaAnswerCaptureMiddleware,
        repository_provider=repository_provider,
        evaluator_provider=evaluator_provider,
    )
    app.state.qa_answer_quality_inbox_installed = True
    return app


__all__ = [
    "QA_COUNTRY_TRUST_ENV",
    "QA_INBOX_PREFIX",
    "QaAnswerCaptureMiddleware",
    "RepositoryQaEventSource",
    "install_qa_inbox",
    "qa_evaluator_from_env",
    "qa_repository_from_env",
]
