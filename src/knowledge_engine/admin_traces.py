from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

ADMIN_TRACE_LIST_SCHEMA = "knowledge-engine-admin-query-traces-list/v1"
ADMIN_TRACE_DETAIL_SCHEMA = "knowledge-engine-admin-query-trace-detail/v1"
MAX_TRACE_RECORDS = 200

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{33,}\b")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitized_question(value: str, *, maximum: int = 160) -> str:
    normalized = _CONTROL.sub(" ", str(value or ""))
    normalized = _EMAIL.sub("[email]", normalized)
    normalized = _URL.sub("[url]", normalized)
    normalized = _LONG_TOKEN.sub("[redacted]", normalized)
    normalized = " ".join(normalized.split())
    return normalized[:maximum] if normalized else "[empty]"


def _string_list(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:160] for item in value[:limit] if item is not None]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _source_identities(response: Mapping[str, Any]) -> list[str]:
    retrieval = _mapping(response.get("retrieval"))
    identities = _string_list(retrieval.get("distinct_source_identities"), limit=12)
    if identities:
        return identities
    sources = response.get("sources")
    if not isinstance(sources, list):
        return []
    values: list[str] = []
    for source in sources[:12]:
        if not isinstance(source, Mapping):
            continue
        identity = source.get("source_identity") or source.get("source_id")
        if identity:
            values.append(str(identity)[:160])
    return values


def _graph_selected_count(response: Mapping[str, Any]) -> int:
    relationship = _mapping(response.get("relationship_summary"))
    graph_count = _int(relationship.get("selected_graph_edge_count"))
    if graph_count:
        return graph_count
    retrieval = _mapping(response.get("retrieval"))
    mode_summary = _mapping(retrieval.get("mode_summary"))
    type_counts = _mapping(mode_summary.get("selected_evidence_type_counts"))
    return _int(type_counts.get("graph_edge"))


def _trace_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": record["trace_id"],
        "observed_at": record["observed_at"],
        "question_sha256": record["question_sha256"],
        "sanitized_question": record["sanitized_question"],
        "status": record["status"],
        "terminal_status": record["terminal_status"],
        "model": record["model"],
        "latency_ms": record["latency_ms"],
        "selected_source_count": record["selected_source_count"],
        "used_source_count": record["used_source_count"],
        "graph_selected_count": record["graph_selected_count"],
        "citation_count": record["citation_count"],
        "safe_abstention": record["safe_abstention"],
        "feedback": record["feedback"],
    }


def sanitized_trace_record(
    *,
    query: str,
    response: Mapping[str, Any],
    observed_at: str | None = None,
) -> dict[str, Any]:
    retrieval = _mapping(response.get("retrieval"))
    accounting = _mapping(response.get("accounting"))
    semantic_closure = _mapping(response.get("semantic_closure"))
    verification = _mapping(response.get("multi_evidence_verification"))
    mode_summary = _mapping(retrieval.get("mode_summary"))
    citations = response.get("citations")
    sources = response.get("sources")
    reason_codes = _string_list(response.get("reason_codes"), limit=24)
    trace_id = str(response.get("trace_id") or f"trace_{sha256_text(query)[:32]}")
    question_sha = str(response.get("question_sha256") or sha256_text(query))
    source_identities = _source_identities(response)
    provider_calls = _int(accounting.get("provider_call_count"))
    record = {
        "schema_version": ADMIN_TRACE_DETAIL_SCHEMA,
        "trace_id": trace_id,
        "observed_at": observed_at or datetime.now(UTC).isoformat(),
        "route": str(response.get("route") or "/api/v1/ask"),
        "question_sha256": question_sha,
        "sanitized_question": sanitized_question(query),
        "status": str(response.get("status") or "unknown"),
        "terminal_status": str(response.get("terminal_status") or ""),
        "model": "bounded-provider" if provider_calls else "retrieval-only",
        "latency_ms": _int(accounting.get("latency_ms")),
        "selected_source_count": _int(retrieval.get("distinct_source_count")),
        "used_source_count": len(sources) if isinstance(sources, list) else 0,
        "graph_selected_count": _graph_selected_count(response),
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "safe_abstention": bool(response.get("safe_abstention", True)),
        "feedback": "not_collected",
        "detail": {
            "intent": str(mode_summary.get("intent_class") or "unknown"),
            "channels": sorted(_mapping(retrieval.get("candidate_count_by_channel"))),
            "candidate_count_by_channel": _mapping(
                retrieval.get("candidate_count_by_channel")
            ),
            "selected_evidence_count": _int(retrieval.get("selected_evidence_count")),
            "selected_evidence_returned": bool(
                retrieval.get("selected_evidence_returned", False)
            ),
            "selected_source_identities": source_identities,
            "used_source_identities": source_identities[:8],
            "graph_hops": _string_list(
                _mapping(semantic_closure.get("endpoint_proof")).get("supporting_edges"),
                limit=12,
            ),
            "provider_attempts": provider_calls,
            "verifier_result": {
                "safe_abstention": bool(response.get("safe_abstention", True)),
                "reason_codes": reason_codes,
                "verification_status": str(
                    verification.get("status")
                    or verification.get("verification_status")
                    or response.get("terminal_status")
                    or ""
                ),
            },
            "final_answer": {
                "answer_sha256": sha256_text(str(response.get("answer_text") or "")),
                "answer_length": len(str(response.get("answer_text") or "")),
                "text_exposed": False,
            },
        },
        "privacy": {
            "raw_query_text_recorded": False,
            "raw_answer_text_recorded": False,
            "selected_evidence_text_recorded": False,
            "provider_secret_recorded": False,
            "owner_secret_recorded": False,
            "raw_provider_response_recorded": False,
        },
        "mutations": {
            "writes_performed": 0,
            "production_pointer_mutations": 0,
            "qdrant_write_operations": 0,
            "r2_write_operations": 0,
        },
    }
    return record


class AdminTraceRecorder:
    def __init__(self, *, max_records: int = MAX_TRACE_RECORDS) -> None:
        self.max_records = max_records
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def record_public_ask(self, *, query: str, response: Mapping[str, Any]) -> None:
        record = sanitized_trace_record(query=query, response=response)
        with self._lock:
            self._records[record["trace_id"]] = record
            self._records.move_to_end(record["trace_id"])
            while len(self._records) > self.max_records:
                self._records.popitem(last=False)

    def list(self, *, limit: int = 50) -> dict[str, Any]:
        bounded_limit = min(100, max(1, int(limit)))
        with self._lock:
            records = list(reversed(self._records.values()))[:bounded_limit]
        return {
            "schema_version": ADMIN_TRACE_LIST_SCHEMA,
            "read_only": True,
            "trace_count": len(records),
            "traces": [_trace_summary(record) for record in records],
            "privacy": {
                "raw_query_text_returned": False,
                "raw_answer_text_returned": False,
                "selected_evidence_text_returned": False,
                "provider_secret_returned": False,
            },
            "mutations": {"writes_performed": 0},
        }

    def get(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(trace_id)
            if record is None:
                return None
            return dict(record)
