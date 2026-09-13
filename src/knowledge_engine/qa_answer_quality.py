from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from .errors import ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

# Retained only for compatibility/debug callers. Production capture uses the
# semantic evaluator's canonical rubric from qa_answer_quality_evaluator.py.
ANSWER_QUALITY_RUBRIC_VERSION = "ANSWER_QUALITY_HEURISTIC_LEGACY_v0"
ANSWER_QUALITY_PASS_THRESHOLD = 85
QA_INDEX_SCHEMA = "knowledge-engine-answer-quality-index/v1"
QA_EVENT_SCHEMA = "knowledge-engine-answer-quality-event/v1"
QA_FAILURE_TRACE_SCHEMA = "knowledge-engine-answer-quality-failure-trace/v1"
QA_EXPORT_SCHEMA = "knowledge-engine-answer-quality-export/v1"
QA_EXPORT_RECORD_SCHEMA = "knowledge-engine-answer-quality-export-record/v1"
QA_INDEX_KEY = "admin/qa/index-v1.json"
QA_MAX_EVENTS = 20_000
QA_RETENTION_DAYS = 120
QA_MAX_CLUSTER_VARIANTS = 12
QA_MAX_SAMPLE_TRACES = 5
QA_WRITE_RETRIES = 5
QA_UNKNOWN_COUNTRY = "ZZ"
QA_CAPTURE_PATHS = {"/v1/ask", "/api/m26/query"}

LIFECYCLE_STATES = {
    "NEW",
    "EXPORTED",
    "IN_REPAIR",
    "RESOLVED",
    "VERIFIED",
    "REOPENED",
    "IGNORED",
}
_ALLOWED_TRANSITIONS = {
    "NEW": {"EXPORTED", "IGNORED"},
    "REOPENED": {"EXPORTED", "IGNORED"},
    "EXPORTED": {"IN_REPAIR", "IGNORED"},
    "IN_REPAIR": {"RESOLVED", "IGNORED"},
    "RESOLVED": {"VERIFIED", "IN_REPAIR", "IGNORED"},
    "VERIFIED": {"REOPENED"},
    "IGNORED": {"NEW", "REOPENED"},
}
_REDACTED_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "secret_access_key",
    "x-api-key",
}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}

_CAPTURE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qa-capture")
_CAPTURE_SLOTS = threading.BoundedSemaphore(value=128)


class LifecycleUpdate(BaseModel):
    state: str
    reason: str | None = Field(default=None, max_length=500)
    resolved_by_release: str | None = Field(default=None, max_length=256)


class QaRepository:
    def __init__(self, store: ObjectStore, *, prefix: str = "admin/qa") -> None:
        self.store = store
        self.prefix = prefix.strip("/")
        self.index_key = f"{self.prefix}/index-v1.json"

    def _empty_index(self) -> dict[str, Any]:
        return {
            "schema_version": QA_INDEX_SCHEMA,
            "revision": 0,
            "updated_at": _iso_now(),
            "events": {},
            "clusters": {},
            "exports": {},
        }

    def _load(self) -> tuple[dict[str, Any], str | None]:
        metadata = self.store.head(self.index_key)
        if metadata is None:
            return self._empty_index(), None
        payload = json.loads(self.store.get(self.index_key).decode("utf-8"))
        if payload.get("schema_version") != QA_INDEX_SCHEMA:
            raise ValueError("unsupported QA index schema")
        return payload, metadata.etag

    def _put_index(self, payload: Mapping[str, Any], etag: str | None) -> None:
        body = _json_bytes(payload)
        self.store.put(
            self.index_key,
            body,
            content_type="application/json",
            sha256=sha256_bytes(body),
            expected_etag=etag,
            only_if_absent=etag is None,
        )

    def _mutate(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        last_exc: Exception | None = None
        for _ in range(QA_WRITE_RETRIES):
            index, etag = self._load()
            working = deepcopy(index)
            result = mutator(working)
            working["revision"] = int(index.get("revision", 0)) + 1
            working["updated_at"] = _iso_now()
            try:
                self._put_index(working, etag)
                return result
            except ReleaseConflictError as exc:
                last_exc = exc
        raise ReleaseConflictError("QA index CAS retries exhausted") from last_exc

    def record_answer(
        self,
        *,
        question: str,
        response: Mapping[str, Any],
        latency_ms: int,
        country: str = QA_UNKNOWN_COUNTRY,
        trace: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        now = timestamp or _iso_now()
        evaluation = evaluate_answer_quality(question=question, response=response)
        event_id = _event_id(response, question, now)
        release_identity = _release_identity(response)
        index_identity = _index_identity(response)
        event = {
            "schema_version": QA_EVENT_SCHEMA,
            "event_id": event_id,
            "timestamp": now,
            "question": " ".join(question.split()),
            "score": evaluation["score"],
            "result": evaluation["result"],
            "latency_ms": max(0, int(latency_ms)),
            "country": _normalize_country(country),
            "release_identity": release_identity,
            "index_identity": index_identity,
            "evaluator": {
                "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
                "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
                "criteria": evaluation["criteria"],
                "hard_fail_reasons": evaluation["hard_fail_reasons"],
            },
            "dedupe_identity": _dedupe_identity(question, response),
            "trace_id": str(response.get("trace_id") or response.get("request_id") or event_id),
            "failure_class": evaluation.get("failure_class"),
            "failure_signature": evaluation.get("failure_signature"),
            "cluster_id": None,
            "failure_trace_key": None,
            "suggested_questions": {
                "eligible": evaluation["result"] == "pass",
                "evaluation_status": "not_evaluated",
                "rubric": "SUGGESTED_QUESTIONS_OWNER_RUBRIC",
                "threshold": 85,
                "production_published": False,
            },
        }

        if evaluation["result"] == "fail":
            failure_trace = _build_failure_trace(
                event=event,
                response=response,
                trace=trace,
                evaluation=evaluation,
            )
            trace_key = f"{self.prefix}/failures/{event_id}.json"
            event["failure_trace_key"] = trace_key
            body = _json_bytes(failure_trace)
            try:
                self.store.put(
                    trace_key,
                    body,
                    content_type="application/json",
                    sha256=sha256_bytes(body),
                    only_if_absent=True,
                )
            except ReleaseConflictError:
                pass

        def apply(index: dict[str, Any]) -> dict[str, Any]:
            events = index.setdefault("events", {})
            clusters = index.setdefault("clusters", {})
            if event_id in events:
                return dict(events[event_id])
            stored_event = dict(event)
            if evaluation["result"] == "fail":
                cluster_id = _cluster_id(question, evaluation)
                stored_event["cluster_id"] = cluster_id
                cluster = clusters.get(cluster_id)
                if cluster is None:
                    cluster = {
                        "cluster_id": cluster_id,
                        "representative_question": stored_event["question"],
                        "variants": [stored_event["question"]],
                        "count": 0,
                        "first_seen": now,
                        "last_seen": now,
                        "failure_stage": evaluation["failure_stage"],
                        "failure_signature": evaluation["failure_signature"],
                        "failure_class": evaluation["failure_class"],
                        "sample_trace_ids": [],
                        "lifecycle": "NEW",
                        "version": 1,
                        "export_history": [],
                        "resolved_by_release": None,
                        "last_seen_release": release_identity,
                        "ignored_reason": None,
                    }
                    clusters[cluster_id] = cluster
                elif cluster.get("lifecycle") == "VERIFIED":
                    cluster["lifecycle"] = "REOPENED"
                    cluster["version"] = int(cluster.get("version", 1)) + 1
                    cluster["resolved_by_release"] = None
                cluster["count"] = int(cluster.get("count", 0)) + 1
                cluster["last_seen"] = now
                cluster["last_seen_release"] = release_identity
                variants = list(cluster.get("variants", []))
                if stored_event["question"] not in variants:
                    variants.append(stored_event["question"])
                cluster["variants"] = variants[-QA_MAX_CLUSTER_VARIANTS:]
                sample_ids = list(cluster.get("sample_trace_ids", []))
                if stored_event["trace_id"] not in sample_ids:
                    sample_ids.append(stored_event["trace_id"])
                cluster["sample_trace_ids"] = sample_ids[-QA_MAX_SAMPLE_TRACES:]
            events[event_id] = stored_event
            _trim_events(index, now)
            return stored_event

        return self._mutate(apply)

    def list_events(
        self,
        *,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
        result: str | None = None,
        country: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        index, _ = self._load()
        start, end = _resolve_range(range_name, from_ts, to_ts)
        items = [
            dict(event)
            for event in index.get("events", {}).values()
            if _in_range(str(event.get("timestamp", "")), start, end)
        ]
        if result:
            items = [item for item in items if item.get("result") == result]
        if country is not None:
            normalized_country = _normalize_country_filter(country)
            items = [item for item in items if item.get("country") == normalized_country]
        items.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        offset = _decode_cursor(cursor)
        page = items[offset : offset + limit]
        next_cursor = _encode_cursor(offset + limit) if offset + limit < len(items) else None
        return {
            "items": page,
            "next_cursor": next_cursor,
            "total": len(items),
            "range": range_name,
        }

    def get_event(self, event_id: str) -> dict[str, Any]:
        index, _ = self._load()
        event = index.get("events", {}).get(event_id)
        if event is None:
            raise KeyError(event_id)
        detail = dict(event)
        trace_key = event.get("failure_trace_key")
        if trace_key:
            try:
                detail["failure_trace"] = json.loads(self.store.get(str(trace_key)).decode("utf-8"))
            except FileNotFoundError:
                detail["failure_trace"] = {"unavailable": True, "trace_key": trace_key}
        return detail

    def summary(
        self,
        *,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> dict[str, Any]:
        page = self.list_events(
            range_name=range_name,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=QA_MAX_EVENTS,
        )
        items = page["items"]
        scored = [item for item in items if isinstance(item.get("score"), (int, float))]
        passed = [item for item in scored if item.get("result") == "pass"]
        failed = [item for item in scored if item.get("result") == "fail"]
        latencies = sorted(int(item.get("latency_ms", 0)) for item in items)
        return {
            "queries": len(items),
            "pass_rate": round((len(passed) / len(scored) * 100), 1) if scored else 0.0,
            "avg_score": round(sum(float(item["score"]) for item in scored) / len(scored), 1)
            if scored
            else 0.0,
            "failed": len(failed),
            "median_latency_ms": int(median(latencies)) if latencies else 0,
            "p95_latency_ms": _percentile(latencies, 0.95),
            "quality_series": _quality_series(items),
            "latency_series": _latency_series(items),
            "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
            "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
        }

    def list_clusters(self, *, lifecycle: str | None = None) -> list[dict[str, Any]]:
        index, _ = self._load()
        clusters = [dict(item) for item in index.get("clusters", {}).values()]
        if lifecycle:
            lifecycle = lifecycle.upper()
            clusters = [item for item in clusters if item.get("lifecycle") == lifecycle]
        clusters.sort(key=lambda item: str(item.get("last_seen", "")), reverse=True)
        return clusters

    def transition_cluster(
        self,
        cluster_id: str,
        *,
        state: str,
        reason: str | None = None,
        resolved_by_release: str | None = None,
    ) -> dict[str, Any]:
        target = state.upper()
        if target not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {state}")

        def apply(index: dict[str, Any]) -> dict[str, Any]:
            cluster = index.setdefault("clusters", {}).get(cluster_id)
            if cluster is None:
                raise KeyError(cluster_id)
            current = str(cluster.get("lifecycle", "NEW"))
            if target == current:
                return dict(cluster)
            if target not in _ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"invalid lifecycle transition: {current} -> {target}")
            if target == "IGNORED" and not reason:
                raise ValueError("IGNORED requires a reason")
            if target == "VERIFIED" and not (
                resolved_by_release or cluster.get("resolved_by_release")
            ):
                raise ValueError("VERIFIED requires resolved_by_release")
            cluster["lifecycle"] = target
            if reason:
                cluster["ignored_reason"] = (
                    reason if target == "IGNORED" else cluster.get("ignored_reason")
                )
            if resolved_by_release:
                cluster["resolved_by_release"] = resolved_by_release
            return dict(cluster)

        return self._mutate(apply)

    def export_new_failures(self) -> dict[str, Any]:
        prepared: dict[str, Any] = {}

        def apply(index: dict[str, Any]) -> dict[str, Any]:
            clusters = index.setdefault("clusters", {})
            eligible = [
                cluster
                for cluster in clusters.values()
                if cluster.get("lifecycle") in {"NEW", "REOPENED"}
            ]
            eligible.sort(key=lambda item: str(item.get("cluster_id", "")))
            if not eligible:
                prepared.update({"created": False, "reason": "NO_NEW_FAILURES"})
                return dict(prepared)
            membership = [
                f"{item['cluster_id']}:{int(item.get('version', 1))}" for item in eligible
            ]
            digest = hashlib.sha256("\n".join(membership).encode("utf-8")).hexdigest()[:20]
            batch_id = f"aqx_{digest}"
            export_key = f"{self.prefix}/exports/{batch_id}.jsonl"
            records = []
            for cluster in eligible:
                records.append(
                    {
                        "schema_version": QA_EXPORT_RECORD_SCHEMA,
                        "batch_id": batch_id,
                        "cluster_id": cluster["cluster_id"],
                        "cluster_version": int(cluster.get("version", 1)),
                        "representative_question": cluster["representative_question"],
                        "variants": list(cluster.get("variants", [])),
                        "count": int(cluster.get("count", 0)),
                        "first_seen": cluster.get("first_seen"),
                        "last_seen": cluster.get("last_seen"),
                        "failure_stage": cluster.get("failure_stage"),
                        "failure_class": cluster.get("failure_class"),
                        "failure_signature": cluster.get("failure_signature"),
                        "sample_trace_ids": list(cluster.get("sample_trace_ids", []))[
                            :QA_MAX_SAMPLE_TRACES
                        ],
                        "resolved_by_release": cluster.get("resolved_by_release"),
                    }
                )
            jsonl = "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
            )
            body = jsonl.encode("utf-8")
            try:
                self.store.put(
                    export_key,
                    body,
                    content_type="application/x-ndjson",
                    sha256=sha256_bytes(body),
                    only_if_absent=True,
                )
            except ReleaseConflictError:
                existing = self.store.get(export_key)
                if existing != body:
                    raise
            created_at = _iso_now()
            for cluster in eligible:
                history = list(cluster.get("export_history", []))
                history.append(
                    {
                        "batch_id": batch_id,
                        "cluster_version": int(cluster.get("version", 1)),
                        "exported_at": created_at,
                    }
                )
                cluster["export_history"] = history[-20:]
                cluster["lifecycle"] = "EXPORTED"
            export_meta = {
                "schema_version": QA_EXPORT_SCHEMA,
                "batch_id": batch_id,
                "created_at": created_at,
                "cluster_count": len(eligible),
                "membership": membership,
                "object_key": export_key,
                "sha256": sha256_bytes(body),
            }
            index.setdefault("exports", {})[batch_id] = export_meta
            prepared.update({"created": True, **export_meta, "jsonl": jsonl})
            return dict(prepared)

        return self._mutate(apply)


def evaluate_answer_quality(*, question: str, response: Mapping[str, Any]) -> dict[str, Any]:
    del question
    answer = str(response.get("answer_text") or response.get("answer") or "").strip()
    status_value = str(response.get("terminal_status") or response.get("status") or "").casefold()
    citations = _as_list(response.get("citations"))
    selected_evidence = _as_list(response.get("selected_evidence"))
    source_cards = _as_list(response.get("source_cards")) or _as_list(response.get("sources"))
    integrity = response.get("integrity") if isinstance(response.get("integrity"), Mapping) else {}
    unsupported = int(integrity.get("unsupported_accepted_claims", 0) or 0)
    material_support = bool(integrity.get("material_claim_support_verified", True))
    locator_valid = bool(integrity.get("citation_locator_valid", True))
    safe_abstention = bool(response.get("safe_abstention", False)) or status_value in {
        "not_found",
        "abstain",
        "safe_abstain",
    }
    reason_codes = [str(item) for item in _as_list(response.get("reason_codes"))]

    directness = 15 if answer and not safe_abstention else (5 if safe_abstention else 0)
    correctness = 25 if material_support and unsupported == 0 else 0
    evidence_coverage = 15 if (selected_evidence or citations or source_cards) else 0
    completeness = (
        15 if answer and len(answer) >= 80 and not safe_abstention else (8 if answer else 0)
    )
    citation_support = (
        15 if citations and locator_valid else (8 if source_cards and locator_valid else 0)
    )
    safety = 15 if unsupported == 0 and material_support and locator_valid else 0

    hard_fail_reasons: list[str] = []
    if not answer and not safe_abstention:
        hard_fail_reasons.append("EMPTY_ANSWER")
    if any(marker in status_value for marker in ("error", "invalid", "failed")):
        hard_fail_reasons.append("RUNTIME_OR_PROVIDER_FAILURE")
    if unsupported > 0:
        hard_fail_reasons.append("UNSUPPORTED_ACCEPTED_CLAIMS")
    if not material_support:
        hard_fail_reasons.append("MATERIAL_CLAIM_SUPPORT_UNVERIFIED")
    if not locator_valid:
        hard_fail_reasons.append("CITATION_LOCATOR_INVALID")
    if answer and not safe_abstention and not (citations or source_cards or selected_evidence):
        hard_fail_reasons.append("ANSWER_WITHOUT_MEANINGFUL_EVIDENCE")
    if (
        safe_abstention
        and not reason_codes
        and status_value not in {"not_found", "abstain", "safe_abstain"}
    ):
        hard_fail_reasons.append("UNEXPLAINED_ABSTENTION")

    score = directness + correctness + evidence_coverage + completeness + citation_support + safety
    if hard_fail_reasons:
        score = min(score, ANSWER_QUALITY_PASS_THRESHOLD - 1)
    score = max(0, min(100, int(score)))
    result = "pass" if score >= ANSWER_QUALITY_PASS_THRESHOLD and not hard_fail_reasons else "fail"
    failure_stage, failure_class = _failure_stage_and_class(
        hard_fail_reasons=hard_fail_reasons,
        status_value=status_value,
        response=response,
    )
    failure_signature = None
    if result == "fail":
        signature_payload = {
            "stage": failure_stage,
            "class": failure_class,
            "reasons": sorted(hard_fail_reasons or reason_codes or [status_value or "UNKNOWN"]),
        }
        failure_signature = hashlib.sha256(_json_bytes(signature_payload)).hexdigest()[:24]
    return {
        "score": score,
        "result": result,
        "criteria": {
            "directness_intent": {"score": directness, "max": 15},
            "correctness_grounding": {"score": correctness, "max": 25},
            "evidence_coverage": {"score": evidence_coverage, "max": 15},
            "completeness_facets": {"score": completeness, "max": 15},
            "citation_support": {"score": citation_support, "max": 15},
            "hallucination_abstention_safety": {"score": safety, "max": 15},
        },
        "hard_fail_reasons": sorted(set(hard_fail_reasons)),
        "failure_stage": failure_stage,
        "failure_class": failure_class,
        "failure_signature": failure_signature,
    }


def submit_answer_capture(
    repository_provider: Callable[[], Any],
    *,
    question: str,
    response: Mapping[str, Any],
    latency_ms: int,
    country: str,
    trace: Mapping[str, Any] | None = None,
    evaluator: Any | None = None,
) -> bool:
    # Capture is synchronous and compact; only semantic evaluation is queued.
    # This guarantees queue pressure cannot erase the underlying query event.
    repository = repository_provider()
    event = repository.record_answer(
        question=question,
        response=response,
        latency_ms=latency_ms,
        country=country,
        trace=trace,
    )
    if not _CAPTURE_SLOTS.acquire(blocking=False):
        repository.mark_not_evaluated(event["event_id"], reason_code="EVALUATION_QUEUE_SATURATED")
        return False

    def task() -> None:
        try:
            from .qa_answer_quality_evaluator import UnavailableAnswerQualityEvaluator

            repository.evaluate_event(
                event["event_id"],
                evaluator=evaluator or UnavailableAnswerQualityEvaluator(),
                answer_payload=response,
                forensic_trace=trace,
            )
        except Exception:
            repository.mark_not_evaluated(event["event_id"], reason_code="CAPTURE_EVALUATION_ERROR")
        finally:
            _CAPTURE_SLOTS.release()

    try:
        _CAPTURE_POOL.submit(task)
    except RuntimeError:
        repository.mark_not_evaluated(event["event_id"], reason_code="EVALUATION_QUEUE_UNAVAILABLE")
        _CAPTURE_SLOTS.release()
        return False
    return True


def register_qa_answer_quality_routes(
    app: FastAPI,
    *,
    store_provider: Callable[[], ObjectStore],
    principal_dependency: Callable[..., Any],
) -> Callable[[], QaRepository]:
    def repository() -> QaRepository:
        return QaRepository(store_provider())

    def admin_guard(principal: Any = Depends(principal_dependency)) -> Any:
        audiences = set(getattr(principal, "audiences", set()))
        if "internal" not in audiences:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="internal access required"
            )
        return principal

    @app.get("/v1/admin/qa/events")
    def qa_events(
        range_name: str = Query(default="24h", alias="range"),
        from_ts: str | None = Query(default=None, alias="from"),
        to_ts: str | None = Query(default=None, alias="to"),
        result: str | None = None,
        country: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        cursor: str | None = None,
        _principal: Any = Depends(admin_guard),
    ) -> dict[str, Any]:
        try:
            return repository().list_events(
                range_name=range_name,
                from_ts=from_ts,
                to_ts=to_ts,
                result=result,
                country=country,
                limit=limit,
                cursor=cursor,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    @app.get("/v1/admin/qa/events/{event_id}")
    def qa_event_detail(event_id: str, _principal: Any = Depends(admin_guard)) -> dict[str, Any]:
        try:
            return repository().get_event(event_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="QA event not found"
            ) from exc

    @app.get("/v1/admin/qa/summary")
    def qa_summary(
        range_name: str = Query(default="24h", alias="range"),
        from_ts: str | None = Query(default=None, alias="from"),
        to_ts: str | None = Query(default=None, alias="to"),
        _principal: Any = Depends(admin_guard),
    ) -> dict[str, Any]:
        try:
            return repository().summary(range_name=range_name, from_ts=from_ts, to_ts=to_ts)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    @app.get("/v1/admin/qa/clusters")
    def qa_clusters(
        lifecycle: str | None = None,
        _principal: Any = Depends(admin_guard),
    ) -> dict[str, Any]:
        return {"items": repository().list_clusters(lifecycle=lifecycle)}

    @app.post("/v1/admin/qa/clusters/{cluster_id}/lifecycle")
    def qa_cluster_lifecycle(
        cluster_id: str,
        update: LifecycleUpdate,
        _principal: Any = Depends(admin_guard),
    ) -> dict[str, Any]:
        try:
            return repository().transition_cluster(
                cluster_id,
                state=update.state,
                reason=update.reason,
                resolved_by_release=update.resolved_by_release,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="QA cluster not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post("/v1/admin/qa/export/jsonl")
    def qa_export_jsonl(_principal: Any = Depends(admin_guard)) -> Response:
        result = repository().export_new_failures()
        if not result.get("created"):
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return Response(
            content=str(result["jsonl"]),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="{result["batch_id"]}.jsonl"',
                "X-QA-Export-Batch": str(result["batch_id"]),
                "X-QA-Export-SHA256": str(result["sha256"]),
            },
        )

    return repository


def _build_failure_trace(
    *,
    event: Mapping[str, Any],
    response: Mapping[str, Any],
    trace: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    raw_trace = dict(trace or {})
    return _redact(
        {
            "schema_version": QA_FAILURE_TRACE_SCHEMA,
            "event_id": event["event_id"],
            "trace_id": event["trace_id"],
            "timestamp": event["timestamp"],
            "question": event["question"],
            "country": event["country"],
            "release_identity": event["release_identity"],
            "index_identity": event["index_identity"],
            "provider_path": response.get("provider_routing")
            or raw_trace.get("provider_routing")
            or {},
            "retrieval": response.get("retrieval") or raw_trace.get("retrieval") or {},
            "selected_evidence": response.get("selected_evidence")
            or raw_trace.get("selected_evidence")
            or [],
            "synthesis_validation": {
                "semantic_closure": response.get("semantic_closure")
                or raw_trace.get("semantic_closure")
                or {},
                "reason_codes": response.get("reason_codes") or raw_trace.get("reason_codes") or [],
                "safe_abstention": response.get("safe_abstention"),
                "answer": response.get("answer_text") or response.get("answer"),
                "citations": response.get("citations") or [],
            },
            "evaluation": {
                "score": evaluation["score"],
                "criteria": evaluation["criteria"],
                "hard_fail_reasons": evaluation["hard_fail_reasons"],
                "failure_stage": evaluation["failure_stage"],
                "failure_class": evaluation["failure_class"],
                "failure_signature": evaluation["failure_signature"],
                "rubric_version": evaluation.get(
                    "rubric_version", ANSWER_QUALITY_RUBRIC_VERSION
                ),
                "evaluator_provider": evaluation.get("evaluator_provider"),
                "evaluator_model": evaluation.get("evaluator_model"),
                "evaluator_version": evaluation.get("evaluator_version"),
                "failure_intent": evaluation.get("failure_intent"),
                "cluster_match_method": evaluation.get("cluster_match_method"),
                "cluster_identity_version": evaluation.get("cluster_identity_version"),
            },
            "timing": raw_trace.get("timing") or {"total_ms": event["latency_ms"]},
            "raw_runtime_trace": raw_trace,
        }
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        redacted = {item.replace("-", "_") for item in _REDACTED_KEYS}
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in redacted or any(
                marker in normalized
                for marker in ("secret", "password", "authorization", "cookie", "api_key")
            ):
                clean[str(key)] = "[REDACTED]"
            else:
                clean[str(key)] = _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _event_id(response: Mapping[str, Any], question: str, timestamp: str) -> str:
    request_identity = str(response.get("trace_id") or response.get("request_id") or "")
    material = f"{timestamp}\n{request_identity}\n{' '.join(question.split())}"
    return f"qa_{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _dedupe_identity(question: str, response: Mapping[str, Any]) -> str:
    payload = {
        "question": " ".join(question.casefold().split()),
        "release": _release_identity(response),
        "index": _index_identity(response),
    }
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _release_identity(response: Mapping[str, Any]) -> dict[str, Any]:
    canonical = (
        response.get("canonical_runtime")
        if isinstance(response.get("canonical_runtime"), Mapping)
        else {}
    )
    identities = (
        response.get("identities") if isinstance(response.get("identities"), Mapping) else {}
    )
    return {
        "release_id": response.get("release_id") or identities.get("production_release_id"),
        "build_sha": canonical.get("build_sha"),
        "runtime_schema": canonical.get("schema_version") or response.get("schema_version"),
    }


def _index_identity(response: Mapping[str, Any]) -> dict[str, Any]:
    identities = (
        response.get("identities") if isinstance(response.get("identities"), Mapping) else {}
    )
    return {
        "manifest_sha256": identities.get("production_manifest_sha256"),
        "pointer_digest": identities.get("production_pointer_digest"),
        "resolved_gate_sha256": identities.get("resolved_gate_self_sha256"),
    }


def _question_family(question: str) -> str:
    tokens = re.findall(r"[\w\u3400-\u9fff]+", question.casefold(), flags=re.UNICODE)
    content = sorted({token for token in tokens if token not in _STOPWORDS and len(token) > 1})
    if not content:
        content = tokens[:12]
    return " ".join(content[:24])


def _cluster_id(question: str, evaluation: Mapping[str, Any]) -> str:
    payload = {
        "question_family": _question_family(question),
        "failure_stage": evaluation.get("failure_stage"),
        "failure_signature": evaluation.get("failure_signature"),
    }
    return f"aqc_{hashlib.sha256(_json_bytes(payload)).hexdigest()[:20]}"


def _failure_stage_and_class(
    *,
    hard_fail_reasons: list[str],
    status_value: str,
    response: Mapping[str, Any],
) -> tuple[str, str]:
    reasons = set(hard_fail_reasons)
    if "RUNTIME_OR_PROVIDER_FAILURE" in reasons:
        provider = (
            response.get("provider_routing")
            if isinstance(response.get("provider_routing"), Mapping)
            else {}
        )
        if provider:
            return "provider", "provider_contract_or_capacity"
        return "runtime", "runtime_failure"
    if reasons & {"UNSUPPORTED_ACCEPTED_CLAIMS", "MATERIAL_CLAIM_SUPPORT_UNVERIFIED"}:
        return "validation", "grounding_integrity"
    if reasons & {"CITATION_LOCATOR_INVALID", "ANSWER_WITHOUT_MEANINGFUL_EVIDENCE"}:
        return "retrieval_evidence", "evidence_or_citation_gap"
    if "UNEXPLAINED_ABSTENTION" in reasons or "abstain" in status_value:
        return "abstention", "inappropriate_or_unexplained_abstention"
    if "EMPTY_ANSWER" in reasons:
        return "synthesis", "empty_or_unusable_answer"
    return "answer_quality", "quality_below_threshold"


def _trim_events(index: dict[str, Any], now: str) -> None:
    events = index.setdefault("events", {})
    cutoff = _parse_ts(now) - timedelta(days=QA_RETENTION_DAYS)
    expired = [
        event_id
        for event_id, event in events.items()
        if _parse_ts(str(event.get("timestamp"))) < cutoff
    ]
    for event_id in expired:
        events.pop(event_id, None)
    if len(events) <= QA_MAX_EVENTS:
        return
    ordered = sorted(events.items(), key=lambda item: str(item[1].get("timestamp", "")))
    for event_id, _ in ordered[: len(events) - QA_MAX_EVENTS]:
        events.pop(event_id, None)


def _resolve_range(
    range_name: str,
    from_ts: str | None,
    to_ts: str | None,
) -> tuple[datetime, datetime]:
    end = _parse_ts(to_ts) if to_ts else datetime.now(timezone.utc)
    if range_name == "custom":
        if not from_ts:
            raise ValueError("custom range requires from")
        return _parse_ts(from_ts), end
    delta = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }.get(range_name)
    if delta is None:
        raise ValueError(f"unsupported range: {range_name}")
    return end - delta, end


def _in_range(value: str, start: datetime, end: datetime) -> bool:
    try:
        timestamp = _parse_ts(value)
    except (TypeError, ValueError):
        return False
    return start <= timestamp <= end


def _parse_ts(value: str | None) -> datetime:
    if not value:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _quality_series(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        key = str(item.get("timestamp", ""))[:10]
        buckets.setdefault(key, []).append(item)
    series = []
    for key in sorted(buckets):
        bucket = [item for item in buckets[key] if isinstance(item.get("score"), (int, float))]
        if not bucket:
            continue
        passed = sum(1 for item in bucket if item.get("result") == "pass")
        series.append(
            {
                "date": key,
                "avg_score": round(sum(float(item["score"]) for item in bucket) / len(bucket), 1),
                "pass_rate": round(passed / len(bucket) * 100, 1),
            }
        )
    return series


def _latency_series(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[int]] = {}
    for item in items:
        key = str(item.get("timestamp", ""))[:10]
        buckets.setdefault(key, []).append(max(0, int(item.get("latency_ms", 0))))
    return [
        {
            "date": key,
            "median_ms": int(median(sorted(values))) if values else 0,
            "p95_ms": _percentile(sorted(values), 0.95),
        }
        for key, values in sorted(buckets.items())
    ]


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return values[low]
    weighted = values[low] + (values[high] - values[low]) * (position - low)
    return int(round(weighted))


def _normalize_country(value: str | None) -> str:
    country = str(value or QA_UNKNOWN_COUNTRY).strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else QA_UNKNOWN_COUNTRY


def _normalize_country_filter(value: str) -> str:
    country = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("country must be a two-letter code or ZZ for unknown")
    return country


def _encode_cursor(offset: int) -> str:
    return f"o{offset}"


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    if not re.fullmatch(r"o\d+", cursor):
        raise ValueError("invalid cursor")
    return int(cursor[1:])


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []
