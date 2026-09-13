from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from .m26_admin_contract import AdminAPIError, redact
from .m26_admin_control_plane import (
    actor_from,
    append_audit_event,
    build_audit_event,
    request_id_from,
    require_capability,
)

QA_CAPABILITY_EVENTS = "qa.events.read"
QA_CAPABILITY_DETAIL = "qa.event.read"
QA_CAPABILITY_EXPORT = "qa.export_markdown"
QA_OUTCOMES = frozenset(
    {
        "refusal",
        "abstain",
        "retrieval_failure",
        "no_citation",
        "fallback",
        "provider_error",
        "slow",
    }
)

_HEADER_LINE_RE = re.compile(
    r"(?im)^(?P<indent>\s*)(?P<name>authorization|cookie|set-cookie|"
    r"cf-access-jwt-assertion|x-api-key)\s*:\s*.*$"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<name>api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"password|secret)\s*[:=]\s*(?P<value>[^\s,;]+)"
)


@dataclass(frozen=True)
class QaReadResult:
    availability: str
    reason_code: str | None
    detail: str | None
    provenance_source: str
    data: Any = None
    observed_at: str | None = None
    freshness: str = "unknown"
    resource_identity: Mapping[str, Any] | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if self.availability not in {"available", "partial", "unavailable"}:
            raise ValueError("invalid QA availability")
        if self.freshness not in {
            "live",
            "near_live",
            "delayed",
            "snapshot",
            "stale",
            "unknown",
        }:
            raise ValueError("invalid QA freshness")
        if self.availability == "unavailable" and self.data is not None:
            raise ValueError("unavailable QA results must not fabricate data")


class QaEventSource(Protocol):
    def list_events(self, *, event_class: str | None, release_id: str | None) -> QaReadResult: ...

    def get_event(self, trace_id: str) -> QaReadResult: ...


class UnavailableQaEventSource:
    """Fail closed until a durable/queryable QA event source is qualified."""

    def _result(self) -> QaReadResult:
        return QaReadResult(
            availability="unavailable",
            reason_code="QA_EVENT_SOURCE_UNAVAILABLE",
            detail="No durable queryable QA event source is configured for this runtime.",
            provenance_source="qa_event_source",
            data=None,
            observed_at=None,
            freshness="unknown",
        )

    def list_events(self, *, event_class: str | None, release_id: str | None) -> QaReadResult:
        return self._result()

    def get_event(self, trace_id: str) -> QaReadResult:
        return self._result()


class InMemoryQaEventSource:
    """Deterministic read-only fixture/reference adapter; never installed by default."""

    def __init__(
        self,
        events: Iterable[Mapping[str, Any]],
        *,
        observed_at: str,
        source: str = "qa_fixture",
        freshness: str = "snapshot",
    ) -> None:
        normalized = [redact_qa_value(dict(event)) for event in events]
        self._events = tuple(normalized)
        self._by_trace = {
            str(event["trace_id"]): event
            for event in normalized
            if isinstance(event, Mapping) and event.get("trace_id")
        }
        self._observed_at = observed_at
        self._source = source
        self._freshness = freshness
        self._digest = hashlib.sha256(
            json.dumps(
                normalized,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _result(self, data: Any) -> QaReadResult:
        return QaReadResult(
            availability="available",
            reason_code=None,
            detail=None,
            provenance_source=self._source,
            data=data,
            observed_at=self._observed_at,
            freshness=self._freshness,
            resource_identity={"kind": "qa_event_fixture"},
            evidence_digest=self._digest,
        )

    def list_events(self, *, event_class: str | None, release_id: str | None) -> QaReadResult:
        rows = [
            event
            for event in self._events
            if (event_class is None or event.get("outcome") == event_class)
            and (release_id is None or event.get("release_id") == release_id)
        ]
        return self._result({"events": rows})

    def get_event(self, trace_id: str) -> QaReadResult:
        event = self._by_trace.get(trace_id)
        if event is None:
            return QaReadResult(
                availability="unavailable",
                reason_code="QA_TRACE_NOT_OBSERVED",
                detail="The requested trace is not present in the qualified QA source.",
                provenance_source=self._source,
                data=None,
                observed_at=self._observed_at,
                freshness=self._freshness,
                resource_identity={"kind": "qa_event_fixture"},
                evidence_digest=self._digest,
            )
        return self._result({"event": event})


class QaExportRequest(BaseModel):
    trace_ids: list[str] = Field(min_length=1, max_length=100)


def redact_qa_text(value: str) -> str:
    value = _HEADER_LINE_RE.sub(
        lambda match: f"{match.group('indent')}{match.group('name')}: [REDACTED]",
        value,
    )
    value = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('name')}=[REDACTED]",
        value,
    )
    redacted = redact(value)
    return str(redacted)


def redact_qa_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_qa_text(value)
    if isinstance(value, Mapping):
        safe = redact(value)
        return {str(key): redact_qa_value(item) for key, item in safe.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_qa_value(item) for item in value]
    return redact(value)


def qa_envelope(request: Request, result: QaReadResult) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": {
            "status": result.availability,
            "reason_code": result.reason_code,
            "detail": result.detail,
        },
        "provenance": {
            "source": result.provenance_source,
            "resource_identity": redact_qa_value(result.resource_identity),
            "evidence_digest": result.evidence_digest,
            "source_observed_at": result.observed_at,
        },
        "observed_at": result.observed_at,
        "freshness": result.freshness,
        "data": (None if result.availability == "unavailable" else redact_qa_value(result.data)),
    }


def _qa_source(request: Request) -> QaEventSource:
    source = getattr(request.app.state, "admin_qa_event_source", None)
    if source is None:
        return UnavailableQaEventSource()
    return source


def _md_inline(value: Any) -> str:
    if value is None:
        return "Unavailable"
    text = redact_qa_text(str(value)).replace("\r", " ").replace("\n", " ")
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _indented(value: Any) -> str:
    if value is None:
        return "    Unavailable"
    if isinstance(value, str):
        text = redact_qa_text(value)
    else:
        text = json.dumps(
            redact_qa_value(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
    return "\n".join(f"    {line}" for line in text.splitlines()) or "    Unavailable"


def build_qa_markdown(events: Sequence[Mapping[str, Any]]) -> str:
    """Build byte-stable Markdown from observed events; no generated timestamp."""

    lines = [
        "# M26 QA Review Export",
        "",
        "> Redacted owner-only repair packet. Authentication material is never exported.",
        "",
    ]
    for event in events:
        safe = redact_qa_value(dict(event))
        trace_id = _md_inline(safe.get("trace_id"))
        lines.extend(
            [
                f"## Trace {trace_id}",
                "",
                f"- Outcome: {_md_inline(safe.get('outcome'))}",
                f"- Observed: {_md_inline(safe.get('timestamp') or safe.get('observed_at'))}",
                f"- Release: {_md_inline(safe.get('release_id'))}",
                f"- Provider: {_md_inline(safe.get('provider'))}",
                f"- Fallback: {_md_inline(safe.get('fallback'))}",
                f"- Retrieval status: {_md_inline(safe.get('retrieval_status'))}",
                f"- Citation count: {_md_inline(safe.get('citation_count'))}",
                f"- Latency ms: {_md_inline(safe.get('latency_ms'))}",
                f"- Reason code: {_md_inline(safe.get('reason_code'))}",
                "",
                "### Question",
                "",
                _indented(safe.get("question")),
                "",
                "### Answer",
                "",
                _indented(safe.get("answer")),
                "",
                "### Trace evidence",
                "",
                _indented(
                    {
                        "timeline": safe.get("timeline"),
                        "retrieval": safe.get("retrieval"),
                        "citations": safe.get("citations"),
                        "provider_context": safe.get("provider_context"),
                    }
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _router() -> APIRouter:
    router = APIRouter(prefix="/v1/admin/qa", tags=["QA"])

    @router.get("/events", operation_id="listQaEvents")
    async def list_events(
        request: Request,
        event_class: str | None = Query(default=None, alias="class"),
        release_id: str | None = None,
    ) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_EVENTS)
        result = _qa_source(request).list_events(
            event_class=event_class,
            release_id=release_id,
        )
        return qa_envelope(request, result)

    @router.get("/events/{trace_id}", operation_id="getQaEvent")
    async def get_event(request: Request, trace_id: str) -> dict[str, Any]:
        require_capability(request, QA_CAPABILITY_DETAIL)
        result = _qa_source(request).get_event(trace_id)
        return qa_envelope(request, result)

    @router.post("/export-markdown", operation_id="exportQaMarkdown")
    async def export_markdown(request: Request, payload: QaExportRequest) -> PlainTextResponse:
        require_capability(request, QA_CAPABILITY_EXPORT)
        source = _qa_source(request)
        events: list[Mapping[str, Any]] = []
        for trace_id in sorted(set(payload.trace_ids)):
            result = source.get_event(trace_id)
            if result.availability != "available" or result.data is None:
                raise AdminAPIError(
                    status_code=409,
                    code=result.reason_code or "QA_EXPORT_SOURCE_UNAVAILABLE",
                    message="Every selected trace must be observed before export.",
                    details={
                        "trace_id": trace_id,
                        "availability": result.availability,
                    },
                )
            body = result.data if isinstance(result.data, Mapping) else {}
            event = body.get("event")
            if not isinstance(event, Mapping):
                raise AdminAPIError(
                    status_code=409,
                    code="QA_TRACE_PAYLOAD_INVALID",
                    message="Selected trace does not contain exportable event evidence.",
                    details={"trace_id": trace_id},
                )
            events.append(event)

        markdown = build_qa_markdown(events)
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        trace_ids_digest = hashlib.sha256(
            json.dumps(sorted(set(payload.trace_ids)), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        append_audit_event(
            request,
            build_audit_event(
                actor=actor_from(request),
                action="qa.export_markdown",
                object_type="qa_review_packet",
                object_id=digest,
                request_id=request_id_from(request),
                operation_id=None,
                outcome="succeeded",
                reason_code="QA_EXPORT_REDACTED",
                metadata={
                    "trace_count": len(events),
                    "trace_ids_sha256": trace_ids_digest,
                    "artifact_sha256": digest,
                },
            ),
        )
        return PlainTextResponse(
            markdown,
            media_type="text/markdown",
            headers={
                "X-QA-Export-SHA256": digest,
                "Content-Disposition": 'attachment; filename="m26-qa-review.md"',
            },
        )

    return router


def install_admin_qa(app: FastAPI, *, source: QaEventSource | None = None) -> FastAPI:
    if getattr(app.state, "admin_qa_installed", False):
        if source is not None:
            app.state.admin_qa_event_source = source
        return app
    app.state.admin_qa_event_source = source or UnavailableQaEventSource()
    app.include_router(_router())
    app.state.admin_qa_installed = True
    return app


__all__ = [
    "InMemoryQaEventSource",
    "QA_CAPABILITY_DETAIL",
    "QA_CAPABILITY_EVENTS",
    "QA_CAPABILITY_EXPORT",
    "QA_OUTCOMES",
    "QaEventSource",
    "QaReadResult",
    "UnavailableQaEventSource",
    "build_qa_markdown",
    "install_admin_qa",
    "qa_envelope",
    "redact_qa_text",
    "redact_qa_value",
]
