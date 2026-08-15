from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .m26_ask_api import DEFAULT_GATE_PATH, build_health_dto, run_owner_query_for_web
from .m26_cloudflare_provider_router import (
    CLOUDFLARE_MODEL,
    CLOUDFLARE_PROVIDER,
    MINIMAX_MODEL,
    MINIMAX_PROVIDER,
    provider_status_dto,
)
from .m26_pa7_arbitrary_query_runtime import MAX_QUERY_CHARS, PA7ArbitraryQueryError

EVENT_SCHEMA_VERSION = "danielcanfly-answers-events/v1"
PROBLEM_TYPE_BASE = "https://api-staging.danielcanfly.com/problems/"
MAX_BODY_BYTES = 4096
HEARTBEAT_SECONDS = 10
HARD_DEADLINE_SECONDS = 90
PER_IP_DAILY_LIMIT = 10
BURST_PER_MINUTE_LIMIT = 2
ACTIVE_PER_IP_LIMIT = 1
GLOBAL_ACTIVE_LIMIT = 3
GLOBAL_DAILY_LIMIT = 50
FALLBACK_DAILY_LIMIT = 10
PUBLIC_REQUEST_SCHEMA = "danielcanfly-answers-request/v1"
PUBLIC_HEALTH_SCHEMA = "danielcanfly-answers-health/v1"

ALLOWED_FIELDS = {"question"}
FORBIDDEN_SELECTION_FIELDS = {"provider", "model"}
DEFAULT_ALLOWED_ORIGINS = (
    "https://danielcanfly.com",
    "https://www.danielcanfly.com",
    "https://api-staging.danielcanfly.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
DEFAULT_TRUSTED_PROXY_CIDRS = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
)


@dataclass(frozen=True)
class Problem:
    status_code: int
    code: str
    title: str
    detail: str
    retryable: bool = False
    retry_after_seconds: int | None = None
    reset_at: str | None = None


@dataclass(frozen=True)
class Admission:
    request_id: str
    ip_key: str
    quota_day: str
    fallback_day: str
    accepted_at: str


class PublicQuotaLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_counts (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    window TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (scope, key, window)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS active_counts (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (scope, key)
                )
                """
            )

    def admit(self, *, ip_key: str, now: datetime | None = None) -> Problem | None:
        current = now or datetime.now(UTC)
        day = current.strftime("%Y-%m-%d")
        minute = current.strftime("%Y-%m-%dT%H:%M")
        reset_at = _next_utc_midnight(current)
        retry_after = _seconds_until_next_minute(current)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                checks = (
                    (
                        "ip_daily",
                        ip_key,
                        day,
                        PER_IP_DAILY_LIMIT,
                        "DAILY_IP_LIMIT_EXCEEDED",
                        reset_at,
                        None,
                    ),
                    (
                        "ip_burst",
                        ip_key,
                        minute,
                        BURST_PER_MINUTE_LIMIT,
                        "BURST_RATE_LIMIT_EXCEEDED",
                        None,
                        retry_after,
                    ),
                    (
                        "global_daily",
                        "global",
                        day,
                        GLOBAL_DAILY_LIMIT,
                        "GLOBAL_DAILY_LIMIT_REACHED",
                        reset_at,
                        None,
                    ),
                )
                for scope, key, window, limit, code, limit_reset, retry in checks:
                    if self._count(db, scope, key, window) >= limit:
                        db.execute("ROLLBACK")
                        return Problem(
                            status.HTTP_429_TOO_MANY_REQUESTS,
                            code,
                            "Request limit reached",
                            _limit_detail(code),
                            retryable=True,
                            retry_after_seconds=retry,
                            reset_at=limit_reset,
                        )
                if self._active(db, "ip_active", ip_key) >= ACTIVE_PER_IP_LIMIT:
                    db.execute("ROLLBACK")
                    return Problem(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "ACTIVE_IP_REQUEST_LIMIT_EXCEEDED",
                        "Another request is active",
                        "Only one active answer request is allowed for this client.",
                        retryable=True,
                        retry_after_seconds=1,
                    )
                if self._active(db, "global_active", "global") >= GLOBAL_ACTIVE_LIMIT:
                    db.execute("ROLLBACK")
                    return Problem(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "GLOBAL_CONCURRENCY_LIMIT_EXCEEDED",
                        "Service is busy",
                        "The staging answer service is at its active request limit.",
                        retryable=True,
                        retry_after_seconds=1,
                    )
                for scope, key, window, *_ in checks:
                    self._increment_count(db, scope, key, window)
                self._increment_active(db, "ip_active", ip_key)
                self._increment_active(db, "global_active", "global")
                db.execute("COMMIT")
                return None
            except Exception:
                db.execute("ROLLBACK")
                raise

    def release(self, *, ip_key: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                self._decrement_active(db, "ip_active", ip_key)
                self._decrement_active(db, "global_active", "global")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def fallback_budget_available(self, *, now: datetime | None = None) -> Problem | None:
        current = now or datetime.now(UTC)
        day = current.strftime("%Y-%m-%d")
        if self.count("fallback_daily", "global", day) >= FALLBACK_DAILY_LIMIT:
            return Problem(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "FALLBACK_DAILY_LIMIT_REACHED",
                "Fallback budget reached",
                "The staging MiniMax fallback closure budget is exhausted for today.",
                retryable=True,
                reset_at=_next_utc_midnight(current),
            )
        return None

    def record_fallback(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        with self._lock, self._connect() as db:
            self._increment_count(db, "fallback_daily", "global", current.strftime("%Y-%m-%d"))

    def count(self, scope: str, key: str, window: str) -> int:
        with self._connect() as db:
            return self._count(db, scope, key, window)

    @staticmethod
    def _count(db: sqlite3.Connection, scope: str, key: str, window: str) -> int:
        row = db.execute(
            "SELECT count FROM quota_counts WHERE scope = ? AND key = ? AND window = ?",
            (scope, key, window),
        ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _active(db: sqlite3.Connection, scope: str, key: str) -> int:
        row = db.execute(
            "SELECT count FROM active_counts WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _increment_count(db: sqlite3.Connection, scope: str, key: str, window: str) -> None:
        db.execute(
            """
            INSERT INTO quota_counts(scope, key, window, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(scope, key, window)
            DO UPDATE SET count = count + 1
            """,
            (scope, key, window),
        )

    @staticmethod
    def _increment_active(db: sqlite3.Connection, scope: str, key: str) -> None:
        db.execute(
            """
            INSERT INTO active_counts(scope, key, count)
            VALUES (?, ?, 1)
            ON CONFLICT(scope, key)
            DO UPDATE SET count = count + 1
            """,
            (scope, key),
        )

    @staticmethod
    def _decrement_active(db: sqlite3.Connection, scope: str, key: str) -> None:
        db.execute(
            """
            UPDATE active_counts
            SET count = MAX(count - 1, 0)
            WHERE scope = ? AND key = ?
            """,
            (scope, key),
        )


def create_app(
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    quota_ledger: PublicQuotaLedger | None = None,
) -> FastAPI:
    app_root = (root or Path(os.environ.get("KNOWLEDGE_ENGINE_ROOT", "."))).resolve()
    resolved_gate_path = gate_path or Path(
        os.environ.get("M26_PA7_GATE_PATH", DEFAULT_GATE_PATH.as_posix())
    )
    if not resolved_gate_path.is_absolute():
        resolved_gate_path = app_root / resolved_gate_path
    ledger = quota_ledger or PublicQuotaLedger(
        Path(
            os.environ.get("M26_PUBLIC_QUOTA_DB", "/tmp/knowledge-engine-public-api/quota.sqlite3")
        )
    )
    app = FastAPI(title="M26 Public Answers API", version="1.0.0")
    app.state.public_root = app_root
    app.state.public_gate_path = resolved_gate_path
    app.state.public_quota_ledger = ledger

    @app.get("/v1/health")
    async def health(request: Request) -> JSONResponse:
        request_id = _request_id()
        problem = _readiness_problem(request_id, require_owner=False)
        if problem is not None:
            return _problem_response(
                problem, request_id=request_id, origin=_request_origin(request)
            )
        try:
            internal = build_health_dto(root=app_root, gate_path=resolved_gate_path)
        except Exception:
            problem = Problem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SERVICE_NOT_READY",
                "Service is not ready",
                "The staging M26 runtime is not ready.",
                retryable=True,
            )
            return _problem_response(
                problem, request_id=request_id, origin=_request_origin(request)
            )
        return JSONResponse(
            {
                "schema_version": PUBLIC_HEALTH_SCHEMA,
                "status": "ok",
                "request_id": request_id,
                "answers_url": "/v1/answers",
                "backend": {
                    "build_sha": internal.get("canonical_runtime", {}).get("build_sha", ""),
                    "entrypoint": internal.get("canonical_runtime", {}).get("entrypoint", ""),
                },
                "limits": _limits_dto(),
            },
            headers=_response_headers(origin=_request_origin(request)),
        )

    @app.options("/v1/answers")
    async def answers_options(request: Request) -> Response:
        origin = _request_origin(request)
        if not _origin_allowed(origin):
            return _problem_response(
                Problem(
                    status.HTTP_403_FORBIDDEN,
                    "PUBLIC_ADMISSION_DENIED",
                    "Origin is not allowed",
                    "This browser origin is not allowed to call the public answer API.",
                ),
                request_id=_request_id(),
                origin=None,
            )
        return Response(status_code=204, headers=_preflight_headers(origin=origin))

    @app.post("/v1/answers")
    async def answers(request: Request) -> Response:
        request_id = _request_id()
        origin = _request_origin(request)
        if not _origin_allowed(origin):
            return _problem_response(
                Problem(
                    status.HTTP_403_FORBIDDEN,
                    "PUBLIC_ADMISSION_DENIED",
                    "Origin is not allowed",
                    "This browser origin is not allowed to call the public answer API.",
                ),
                request_id=request_id,
                origin=None,
            )
        problem = _readiness_problem(request_id, require_owner=True)
        if problem is not None:
            return _problem_response(problem, request_id=request_id, origin=origin)
        body = await request.body()
        parsed, problem = _parse_public_request(body)
        if problem is not None:
            return _problem_response(problem, request_id=request_id, origin=origin)
        assert parsed is not None
        language_problem = _language_problem(parsed["question"])
        if language_problem is not None:
            return _problem_response(language_problem, request_id=request_id, origin=origin)
        ip_key = _pseudonymous_ip_key(request, now=datetime.now(UTC))
        provider_problem = _provider_guard_problem()
        if provider_problem is not None:
            return _problem_response(provider_problem, request_id=request_id, origin=origin)
        fallback_problem = ledger.fallback_budget_available()
        if fallback_problem is not None and _fallback_expected():
            return _problem_response(fallback_problem, request_id=request_id, origin=origin)
        admission_problem = ledger.admit(ip_key=ip_key)
        if admission_problem is not None:
            return _problem_response(admission_problem, request_id=request_id, origin=origin)
        admission = Admission(
            request_id=request_id,
            ip_key=ip_key,
            quota_day=datetime.now(UTC).strftime("%Y-%m-%d"),
            fallback_day=datetime.now(UTC).strftime("%Y-%m-%d"),
            accepted_at=_utc_now(),
        )
        return StreamingResponse(
            _answer_event_stream(
                request=request,
                question=parsed["question"],
                admission=admission,
                ledger=ledger,
                app_root=app_root,
                gate_path=resolved_gate_path,
            ),
            media_type="text/event-stream; charset=utf-8",
            headers=_stream_headers(origin=origin),
        )

    return app


def _parse_public_request(body: bytes) -> tuple[dict[str, str] | None, Problem | None]:
    if len(body) > MAX_BODY_BYTES:
        return None, Problem(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "REQUEST_BODY_TOO_LARGE",
            "Request body is too large",
            "The request body exceeds the public API size limit.",
        )
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_JSON",
            "Invalid JSON",
            "The request body must be valid JSON.",
        )
    if not isinstance(value, Mapping):
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "REQUEST_NOT_OBJECT",
            "Request must be an object",
            "The request body must be a JSON object.",
        )
    extra = sorted(set(value) - ALLOWED_FIELDS)
    forbidden = sorted(set(value) & FORBIDDEN_SELECTION_FIELDS)
    if forbidden:
        code = "PROVIDER_SELECTION_FORBIDDEN"
        if forbidden == ["model"]:
            detail = "The public API reports provider/model but does not accept model selection."
        else:
            detail = "The public API reports provider/model but does not accept provider selection."
        return None, Problem(
            status.HTTP_400_BAD_REQUEST, code, "Provider selection is forbidden", detail
        )
    if extra:
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "UNSUPPORTED_FIELD",
            "Unsupported request field",
            "The public API accepts only the question field.",
        )
    if "question" not in value:
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "QUESTION_MISSING",
            "Question is missing",
            "The request body must include a question string.",
        )
    question = value.get("question")
    if not isinstance(question, str):
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "QUESTION_MISSING",
            "Question is missing",
            "The request body must include a question string.",
        )
    normalized = " ".join(question.strip().split())
    if not normalized:
        return None, Problem(
            status.HTTP_400_BAD_REQUEST,
            "QUESTION_EMPTY",
            "Question is empty",
            "Please enter an English question.",
        )
    if len(normalized) > MAX_QUERY_CHARS:
        return None, Problem(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "QUESTION_TOO_LONG",
            "Question is too long",
            "The question exceeds the public API character limit.",
        )
    return {"question": normalized}, None


def _language_problem(question: str) -> Problem | None:
    for char in question:
        if not char.isalpha():
            continue
        if _is_latin_letter(char):
            continue
        return Problem(
            status.HTTP_400_BAD_REQUEST,
            "INPUT_LANGUAGE_NOT_SUPPORTED",
            "Language is not supported",
            "Public API V1 accepts English/Latin-script questions only.",
        )
    return None


def _is_latin_letter(char: str) -> bool:
    try:
        return "LATIN" in unicodedata.name(char)
    except ValueError:
        return False


async def _answer_event_stream(
    *,
    request: Request,
    question: str,
    admission: Admission,
    ledger: PublicQuotaLedger,
    app_root: Path,
    gate_path: Path,
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
            "schema_version": EVENT_SCHEMA_VERSION,
            "seq": seq,
            "request_id": admission.request_id,
            "type": event_type,
            "created_at": _utc_now(),
            **fields,
        }
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        return f"id: {seq}\nevent: {event_type}\ndata: {payload}\n\n"

    def sink(event: Mapping[str, Any]) -> None:
        event_queue.put(_sanitize_runtime_event(event))

    async def worker() -> None:
        try:
            dto = await asyncio.to_thread(
                run_owner_query_for_web,
                root=app_root,
                gate_path=gate_path,
                request_payload={"question": question},
                owner_subject_hash=os.environ["KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"],
                event_sink=sink,
            )
            event_queue.put({"type": "_dto", "dto": dto})
        except Exception as exc:
            event_queue.put({"type": "_error", "error": exc})
        finally:
            event_queue.put(done)

    task = asyncio.create_task(worker())
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    yield emit("request.accepted", accepted_at=admission.accepted_at, limits=_limits_dto())
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
            if time.monotonic() - started >= HARD_DEADLINE_SECONDS:
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
                    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                await asyncio.sleep(0.05)
                continue
            if item is done:
                break
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "_dto":
                dto = dict(item.get("dto") if isinstance(item.get("dto"), Mapping) else {})
                for event in _model_events_from_dto(dto):
                    yield emit(str(event.pop("type")), **event)
                terminal = _terminal_event_from_dto(dto)
                if terminal["type"] == "answer.completed" and _uses_fallback(dto):
                    ledger.record_fallback()
                yield emit(str(terminal.pop("type")), **terminal)
                terminal_sent = True
                continue
            if item.get("type") == "_error":
                error = item.get("error")
                code = (
                    str(error.reason_code)
                    if isinstance(error, PA7ArbitraryQueryError)
                    else "INTERNAL_RUNTIME_FAILED"
                )
                yield emit(
                    "answer.failed",
                    code=_public_failure_code(code),
                    detail=_failure_detail(code),
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


def _sanitize_runtime_event(event: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "type",
        "stage",
        "status",
        "attempt",
        "role",
        "provider",
        "model",
        "latency_ms",
        "fallback_used",
        "fallback_reason",
        "reason_codes",
        "terminal_status",
        "selected_evidence_count",
    }
    return {key: value for key, value in event.items() if key in allowed_keys}


def _model_events_from_dto(dto: Mapping[str, Any]) -> list[dict[str, Any]]:
    provider_routing = _mapping(dto.get("provider_routing"))
    attempts = [
        item for item in provider_routing.get("provider_attempts", []) if isinstance(item, Mapping)
    ]
    if not attempts:
        attempts = [
            {
                "provider": provider_routing.get("closure_provider_final") or CLOUDFLARE_PROVIDER,
                "model": CLOUDFLARE_MODEL,
                "call_class": "closure",
                "latency_ms": None,
            }
        ]
    events: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        call_class = str(attempt.get("call_class", ""))
        role = "semantic_reviewer" if "semantic" in call_class else "closure"
        provider = str(
            attempt.get("provider")
            or (
                MINIMAX_PROVIDER
                if role == "semantic_reviewer"
                else provider_routing.get("closure_provider_final")
            )
            or "unknown"
        )
        model = str(
            attempt.get("model")
            or (MINIMAX_MODEL if provider == MINIMAX_PROVIDER else CLOUDFLARE_MODEL)
        )
        events.append(
            {
                "type": "model.started",
                "role": role,
                "provider": provider,
                "model": model,
                "attempt": index,
                "fallback_used": bool(provider_routing.get("fallback_used")),
                "fallback_reason": str(provider_routing.get("fallback_reason", "")),
            }
        )
        events.append(
            {
                "type": "model.completed",
                "role": role,
                "provider": provider,
                "model": model,
                "attempt": index,
                "status": "completed",
                "latency_ms": attempt.get("latency_ms"),
                "fallback_used": bool(provider_routing.get("fallback_used")),
                "fallback_reason": str(provider_routing.get("fallback_reason", "")),
            }
        )
    if not any(event.get("role") == "semantic_reviewer" for event in events):
        events.append(
            {
                "type": "model.completed",
                "role": "semantic_reviewer",
                "provider": MINIMAX_PROVIDER,
                "model": MINIMAX_MODEL,
                "attempt": 1,
                "status": "observed_or_not_required",
            }
        )
    return events


def _terminal_event_from_dto(dto: Mapping[str, Any]) -> dict[str, Any]:
    status_value = str(dto.get("status", ""))
    safe_abstention = bool(dto.get("safe_abstention", False))
    if safe_abstention or status_value.endswith("safe_abstention"):
        return {
            "type": "answer.abstained",
            "code": _public_abstention_code(dto.get("reason_codes")),
            "detail": _abstention_detail(dto.get("reason_codes")),
            "retryable": False,
            "provider_routing": _public_provider_routing(dto),
        }
    if status_value in {"owner_only_cited_answer", "owner_only_partial_answer", "partial"}:
        event_type = (
            "answer.partial" if status_value != "owner_only_cited_answer" else "answer.completed"
        )
        return {
            "type": event_type,
            "answer": str(dto.get("answer_text", "")),
            "citations": _public_citations(dto.get("citations")),
            "sources": _public_sources(dto.get("sources")),
            "claims": _public_claims(dto.get("answer_claims")),
            "provider_routing": _public_provider_routing(dto),
        }
    return {
        "type": "answer.failed",
        "code": "INTERNAL_RUNTIME_FAILED",
        "detail": "The runtime did not return a publishable public terminal status.",
        "retryable": True,
        "provider_routing": _public_provider_routing(dto),
    }


def _public_citations(value: Any) -> list[dict[str, Any]]:
    result = []
    for citation in value if isinstance(value, list) else []:
        if not isinstance(citation, Mapping):
            continue
        result.append(
            {
                "citation_id": citation.get("citation_id"),
                "claim_id": citation.get("claim_id"),
                "source_identity": citation.get("source_identity"),
                "section_id": citation.get("section_id"),
                "concept_id": citation.get("concept_id"),
                "release_id": citation.get("release_id"),
                "runtime_owned_locator": bool(citation.get("runtime_owned_locator")),
            }
        )
    return result


def _public_sources(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "source_identity": item.get("source_identity"),
            "source_id": item.get("source_id"),
            "section_ids": item.get("section_ids", []),
            "concept_ids": item.get("concept_ids", []),
            "citation_numbers": item.get("citation_numbers", []),
        }
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, Mapping)
    ]


def _public_claims(value: Any) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": item.get("claim_id"),
            "claim_role": item.get("claim_role"),
            "citation_ids": item.get("citation_ids", []),
            "support_ref_count": item.get("support_ref_count", 0),
        }
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, Mapping)
    ]


def _public_provider_routing(dto: Mapping[str, Any]) -> dict[str, Any]:
    routing = _mapping(dto.get("provider_routing"))
    return {
        "closure_provider": routing.get("closure_provider_final")
        or routing.get("closure_provider_initial")
        or "",
        "closure_provider_initial": routing.get("closure_provider_initial") or "",
        "semantic_reviewer": MINIMAX_PROVIDER,
        "semantic_reviewer_model": MINIMAX_MODEL,
        "fallback_used": bool(routing.get("fallback_used")),
        "fallback_reason": str(routing.get("fallback_reason", "")),
    }


def _readiness_problem(request_id: str, *, require_owner: bool) -> Problem | None:
    del request_id
    missing = []
    if require_owner and not os.environ.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"):
        missing.append("owner identity")
    if not os.environ.get("M26_PUBLIC_IP_HMAC_SECRET"):
        missing.append("public HMAC secret")
    if missing:
        return Problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_NOT_READY",
            "Service is not ready",
            "The public answer service is missing required staging configuration.",
            retryable=True,
        )
    return None


def _provider_guard_problem() -> Problem | None:
    if os.environ.get("M26_PUBLIC_PROVIDER_BUDGET_GUARD_ACTIVE", "").lower() == "true":
        return Problem(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "PROVIDER_BUDGET_GUARD_ACTIVE",
            "Provider budget guard is active",
            "The public answer service is temporarily paused by a provider budget guard.",
            retryable=True,
            retry_after_seconds=60,
        )
    return None


def _fallback_expected() -> bool:
    if os.environ.get("M26_PUBLIC_FORCE_FALLBACK_EXPECTED", "").lower() == "true":
        return True
    status_dto = provider_status_dto()
    return str(status_dto.get("active_route", "")).lower() == MINIMAX_PROVIDER


def _uses_fallback(dto: Mapping[str, Any]) -> bool:
    return bool(_mapping(dto.get("provider_routing")).get("fallback_used"))


def _problem_response(problem: Problem, *, request_id: str, origin: str | None) -> JSONResponse:
    body = {
        "type": PROBLEM_TYPE_BASE + problem.code,
        "title": problem.title,
        "status": problem.status_code,
        "code": problem.code,
        "detail": problem.detail,
        "request_id": request_id,
        "retryable": problem.retryable,
    }
    if problem.retry_after_seconds is not None:
        body["retry_after_seconds"] = problem.retry_after_seconds
    if problem.reset_at is not None:
        body["reset_at"] = problem.reset_at
    headers = _response_headers(origin=origin)
    if problem.retry_after_seconds is not None:
        headers["Retry-After"] = str(problem.retry_after_seconds)
    return JSONResponse(
        body,
        status_code=problem.status_code,
        media_type="application/problem+json",
        headers=headers,
    )


def _request_origin(request: Request) -> str | None:
    return request.headers.get("origin")


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    return origin in set(_allowed_origins())


def _allowed_origins() -> tuple[str, ...]:
    raw = os.environ.get("M26_PUBLIC_ALLOWED_ORIGINS", "")
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    return tuple(item.strip().rstrip("/") for item in raw.split(",") if item.strip())


def _response_headers(*, origin: str | None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Vary": "Origin",
    }
    if origin is not None and _origin_allowed(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "false"
    return headers


def _preflight_headers(*, origin: str | None) -> dict[str, str]:
    headers = _response_headers(origin=origin)
    headers.update(
        {
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Max-Age": "300",
        }
    )
    return headers


def _stream_headers(*, origin: str | None) -> dict[str, str]:
    headers = _response_headers(origin=origin)
    headers.update(
        {
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
    return headers


def _pseudonymous_ip_key(request: Request, *, now: datetime) -> str:
    raw_ip = _authoritative_client_ip(request)
    day = now.strftime("%Y-%m-%d")
    secret = os.environ["M26_PUBLIC_IP_HMAC_SECRET"].encode("utf-8")
    digest = hmac.new(secret, f"{day}:{raw_ip}".encode(), hashlib.sha256).hexdigest()
    return f"ipday_{day}_{digest}"


def _authoritative_client_ip(request: Request) -> str:
    remote = request.client.host if request.client is not None else ""
    if _trusted_proxy(remote) and request.headers.get("cf-connecting-ip"):
        try:
            return str(ipaddress.ip_address(request.headers["cf-connecting-ip"].strip()))
        except ValueError:
            return "unknown"
    try:
        return str(ipaddress.ip_address(remote or "127.0.0.1"))
    except ValueError:
        return "unknown"


def _trusted_proxy(remote: str) -> bool:
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def _trusted_proxy_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.environ.get("M26_PUBLIC_TRUSTED_PROXY_CIDRS", "")
    cidrs = [item.strip() for item in raw.split(",") if item.strip()] or list(
        DEFAULT_TRUSTED_PROXY_CIDRS
    )
    return [ipaddress.ip_network(item, strict=False) for item in cidrs]


def _limits_dto() -> dict[str, int]:
    return {
        "per_ip_daily": PER_IP_DAILY_LIMIT,
        "burst_per_minute": BURST_PER_MINUTE_LIMIT,
        "active_per_ip": ACTIVE_PER_IP_LIMIT,
        "global_active": GLOBAL_ACTIVE_LIMIT,
        "global_daily": GLOBAL_DAILY_LIMIT,
        "minimax_fallback_daily": FALLBACK_DAILY_LIMIT,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "hard_deadline_seconds": HARD_DEADLINE_SECONDS,
    }


def _public_failure_code(code: str) -> str:
    mapping = {
        "PROVIDER_CONFIGURATION_MISSING": "CLOSURE_PROVIDERS_UNAVAILABLE",
        "PROVIDER_CALL_FAILED": "CLOSURE_PROVIDERS_UNAVAILABLE",
        "PA7_REMOTE_DENSE_CONFIG_MISSING": "RETRIEVAL_RUNTIME_FAILED",
    }
    return mapping.get(
        code, code if code in _post_stream_failure_codes() else "INTERNAL_RUNTIME_FAILED"
    )


def _post_stream_failure_codes() -> set[str]:
    return {
        "RETRIEVAL_RUNTIME_FAILED",
        "CLOSURE_PROVIDERS_UNAVAILABLE",
        "SEMANTIC_REVIEWER_UNAVAILABLE",
        "ANSWER_TIMEOUT",
        "STREAM_PROTOCOL_FAILED",
        "INTERNAL_RUNTIME_FAILED",
    }


def _failure_detail(code: str) -> str:
    public = _public_failure_code(code)
    details = {
        "RETRIEVAL_RUNTIME_FAILED": "The retrieval runtime failed before answer verification.",
        "CLOSURE_PROVIDERS_UNAVAILABLE": (
            "The answer closure providers are temporarily unavailable."
        ),
        "SEMANTIC_REVIEWER_UNAVAILABLE": "The semantic reviewer is temporarily unavailable.",
        "ANSWER_TIMEOUT": "The answer exceeded the public staging deadline.",
        "STREAM_PROTOCOL_FAILED": "The stream failed before a valid terminal answer event.",
    }
    return details.get(public, "The answer runtime failed.")


def _public_abstention_code(codes: Any) -> str:
    allowed = {
        "INSUFFICIENT_EVIDENCE",
        "LOW_RETRIEVAL_SUPPORT",
        "PROMPT_INJECTION_OR_PRIVACY_RISK",
        "QUESTION_UNDERSPECIFIED",
        "VERIFICATION_COULD_NOT_AUTHORIZE_ANSWER",
    }
    values = {str(item) for item in codes} if isinstance(codes, list) else set()
    if "LOW_RETRIEVAL_SUPPORT" in values:
        return "LOW_RETRIEVAL_SUPPORT"
    if "PROMPT_INJECTION_OR_PRIVACY_RISK" in values:
        return "PROMPT_INJECTION_OR_PRIVACY_RISK"
    if "QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED" in values:
        return "QUESTION_UNDERSPECIFIED"
    if "NO_AUTHORIZED_PRODUCTION_EVIDENCE" in values or "INSUFFICIENT_SUPPORT" in values:
        return "INSUFFICIENT_EVIDENCE"
    return next(iter(values & allowed), "VERIFICATION_COULD_NOT_AUTHORIZE_ANSWER")


def _abstention_detail(codes: Any) -> str:
    code = _public_abstention_code(codes)
    details = {
        "INSUFFICIENT_EVIDENCE": (
            "The service could not find enough verified public evidence to answer safely."
        ),
        "LOW_RETRIEVAL_SUPPORT": "The retrieved evidence did not support a safe public answer.",
        "PROMPT_INJECTION_OR_PRIVACY_RISK": (
            "The question was rejected by the privacy and prompt-injection safety boundary."
        ),
        "QUESTION_UNDERSPECIFIED": (
            "The question needs more detail before it can be answered safely."
        ),
        "VERIFICATION_COULD_NOT_AUTHORIZE_ANSWER": (
            "The verifier could not authorize a public answer."
        ),
    }
    return details[code]


def _limit_detail(code: str) -> str:
    return {
        "DAILY_IP_LIMIT_EXCEEDED": "This client has reached the accepted-answer daily limit.",
        "BURST_RATE_LIMIT_EXCEEDED": (
            "Too many accepted admissions were made in the current minute."
        ),
        "GLOBAL_DAILY_LIMIT_REACHED": (
            "The staging service has reached its global accepted-answer daily limit."
        ),
    }.get(code, "A launch limit was reached.")


def _next_utc_midnight(now: datetime) -> str:
    current = now.astimezone(UTC)
    tomorrow = current.date() + timedelta(days=1)
    reset = datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)
    return reset.isoformat().replace("+00:00", "Z")


def _seconds_until_next_minute(now: datetime) -> int:
    current = now.astimezone(UTC)
    return max(1, 60 - current.second)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _request_id() -> str:
    return "req_" + uuid.uuid4().hex


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


app = create_app()
