from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_TRACE_BUFFER: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "m26_sealed_kernel_trace_buffer",
    default=None,
)


def sha256_json(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


@contextmanager
def request_trace() -> Iterator[list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    token = _TRACE_BUFFER.set(events)
    try:
        yield events
    finally:
        _TRACE_BUFFER.reset(token)


def export_trace() -> list[dict[str, Any]]:
    events = _TRACE_BUFFER.get()
    return [dict(event) for event in events or []]


def trace(event: str, **fields: Any) -> None:
    try:
        events = _TRACE_BUFFER.get()
        if events is None:
            return
        events.append(
            {
                "event": str(event),
                "monotonic_ns": time.monotonic_ns(),
                **_sanitize_mapping(fields),
            }
        )
    except Exception:
        return


def payload_fingerprint(payload: Any) -> dict[str, Any]:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes_utf8": len(text.encode("utf-8")),
    }


def response_fingerprint(response: Mapping[str, Any] | None) -> dict[str, Any]:
    if response is None:
        return {"present": False, "text_len": 0, "text_sha256": ""}
    text = str(response.get("text", response.get("provider_text", "")))
    return {
        "present": True,
        "text_len": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "stop_reason": str(response.get("stop_reason") or response.get("finish_reason") or ""),
        "call_class": str(response.get("call_class", "")),
    }


def evidence_summary(evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [
        str(item.get("evidence_id", ""))
        for item in evidence
        if isinstance(item, Mapping) and str(item.get("evidence_id", ""))
    ]
    return {
        "count": len(evidence),
        "id_hashes": [hashlib.sha256(item.encode("utf-8")).hexdigest() for item in ids],
    }


def candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    claims = candidate.get("claims", [])
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        claims = []
    answer_text = str(candidate.get("answer_text", ""))
    return {
        "status": str(candidate.get("status", "")),
        "answer_len": len(answer_text),
        "answer_sha256": hashlib.sha256(answer_text.encode("utf-8")).hexdigest(),
        "claim_count": len(claims),
        "selected_evidence_count": len(candidate.get("selected_evidence_ids", []) or []),
        "unanswered_dimension_count": len(candidate.get("unanswered_dimensions", []) or []),
    }


def review_summary(review: Mapping[str, Any]) -> dict[str, Any]:
    judgments = review.get("claim_judgments", [])
    if not isinstance(judgments, Sequence) or isinstance(judgments, (str, bytes)):
        judgments = []
    coverage = review.get("visible_coverage")
    return {
        "schema_version": str(review.get("schema_version", "")),
        "claim_judgment_count": len(judgments),
        "visible_coverage_verdict": (
            str(coverage.get("verdict", "")) if isinstance(coverage, Mapping) else ""
        ),
    }


def exception_summary(
    exc: BaseException,
    *,
    started_ns: int | None = None,
) -> dict[str, Any]:
    message = " ".join(str(exc).split())
    message = re.sub(r"https?://\S+", "[REDACTED]", message)
    cause = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    cause_name = type(cause).__name__ if cause is not None else ""
    http_status = _exception_http_status(exc, message)
    summary = {
        "exception_class": type(exc).__name__,
        "exception_message_code": message,
        "chained_exception_class": cause_name,
        "retry_exhausted": _exception_retry_exhausted(message, cause_name),
        "http_status": http_status,
    }
    if started_ns is not None:
        summary["elapsed_ms"] = max(0, int((time.monotonic_ns() - started_ns) / 1_000_000))
    return summary


def _exception_http_status(exc: BaseException, message: str) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) if response is not None else None
    if isinstance(status_code, int):
        return status_code
    match = re.search(r"\bprovider HTTP (\d{3})\b", message)
    if match:
        return int(match.group(1))
    return None


def _exception_retry_exhausted(message: str, chained_exception_class: str) -> bool:
    if "provider retry exhaustion" in message.casefold():
        return True
    return chained_exception_class in {
        "TimeoutException",
        "ReadTimeout",
        "WriteTimeout",
        "ConnectTimeout",
        "PoolTimeout",
        "NetworkError",
    }


def _sanitize_mapping(fields: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        name = str(key)
        lowered = name.casefold()
        if any(
            secret in lowered
            for secret in ("token", "secret", "authorization", "cookie", "jwt", "key")
        ):
            continue
        safe[name] = _sanitize_value(value)
    return safe


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value]
    return str(value)
