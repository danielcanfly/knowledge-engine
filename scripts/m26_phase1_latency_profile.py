from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_ask_api import DEFAULT_GATE_PATH, run_owner_query_for_web
from knowledge_engine.m26_pa5_v8_live import MiniMaxClient
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256


ANSWER_SOURCE = "provider_verified_runtime_bound_semantic_closure"
PARTIAL_SOURCE = "provider_verified_runtime_bound_partial_semantic_closure"
SEMANTIC_CALLS = {
    "aq_semantic_closure",
    "aq_semantic_closure_repair",
    "aq_claim_semantic_entailment",
}
PRE_REVIEW_CLOSURE_CALLS = {
    "aq_semantic_closure",
    "aq_semantic_closure_repair",
}
ALLOWED_PRE_REVIEW_FAILURE_ENUMS = {
    "MISSING_STRUCTURED_CLAIMS",
    "MISSING_CLAIM_ID",
    "MISSING_ANSWER_ANCHOR",
    "AMBIGUOUS_ANSWER_ANCHOR",
    "INVALID_CLAIM_TYPE",
    "MISSING_EVIDENCE_LABELS",
    "UNKNOWN_EVIDENCE_LABELS",
    "EVIDENCE_BINDING_FAILED",
    "BOUNDED_PUBLICATION_FAILED",
    "OTHER_PRE_REVIEW_FAILURE",
}


class Phase1Profiler:
    def __init__(self) -> None:
        self.stage_timings: list[dict[str, Any]] = []
        self.provider_calls: list[dict[str, Any]] = []
        self.pre_review_traces: list[dict[str, Any]] = []

    def observe_stage(
        self,
        stage: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        started = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            self.stage_timings.append(
                {
                    "stage": stage,
                    "elapsed_ms": _elapsed_ms(started),
                    "error_type": type(exc).__name__,
                }
            )
            raise
        self.stage_timings.append(
            {"stage": stage, "elapsed_ms": _elapsed_ms(started)}
        )
        return result

    def begin_pre_review_attempt(self, call_class: str) -> None:
        self.pre_review_traces.append(
            {
                "call_class": call_class,
                "closure_parse_success": False,
                "parsed_claim_count": 0,
                "parsed_claim_id_count": 0,
                "answer_anchor_count": 0,
                "unique_anchored_claim_id_count": 0,
                "pre_review_stage_reached": "provider_returned",
                "pre_review_failure_enum": "",
                "failing_claim_id": "",
                "answer_sentence_count": 0,
                "multi_anchor_sentence_count": 0,
                "max_anchors_per_sentence": 0,
                "reviewer_blocked_claims": [],
            }
        )

    def active_pre_review_trace(self) -> dict[str, Any] | None:
        for trace in reversed(self.pre_review_traces):
            stage = str(trace.get("pre_review_stage_reached", ""))
            if stage != "semantic_reviewer_reached" and not trace.get(
                "pre_review_failure_enum"
            ):
                return trace
        return self.pre_review_traces[-1] if self.pre_review_traces else None


class ObservedProvider:
    def __init__(self, inner: Any, profiler: Phase1Profiler) -> None:
        self.inner = inner
        self.profiler = profiler

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = dict(self.inner.call(payload, call_class))
        except Exception as exc:
            self.profiler.provider_calls.append(
                {
                    "call_class": call_class,
                    "elapsed_ms": _elapsed_ms(started),
                    "error_type": type(exc).__name__,
                    "payload_bytes": _payload_bytes(payload),
                }
            )
            raise
        usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
        elapsed_ms = _elapsed_ms(started)
        provider_latency_ms = int(result.get("latency_ms", elapsed_ms))
        self.profiler.provider_calls.append(
            {
                "call_class": call_class,
                "elapsed_ms": elapsed_ms,
                "provider_latency_ms": provider_latency_ms,
                "transport_overhead_ms": elapsed_ms - provider_latency_ms,
                "network_attempt": int(result.get("network_attempt", 1) or 1),
                "payload_bytes": _payload_bytes(payload),
                "input_tokens": _usage_int(usage, "input_tokens", "prompt_tokens"),
                "output_tokens": _usage_int(usage, "output_tokens", "completion_tokens"),
                "total_tokens": _usage_int(usage, "total_tokens"),
                "cache_creation_input_tokens": _usage_int(
                    usage,
                    "cache_creation_input_tokens",
                    "cache_creation_tokens",
                ),
                "cache_read_input_tokens": _usage_int(
                    usage,
                    "cache_read_input_tokens",
                    "cache_read_tokens",
                ),
                "stop_reason": str(
                    result.get("stop_reason") or result.get("finish_reason") or ""
                ),
                "provider_text_char_count": len(
                    str(result.get("text", result.get("provider_text", "")))
                ),
            }
        )
        if call_class in PRE_REVIEW_CLOSURE_CALLS:
            self.profiler.begin_pre_review_attempt(call_class)
        return result


class ObservedDenseChannel:
    def __init__(self, inner: Any, profiler: Phase1Profiler) -> None:
        self.inner = inner
        self.profiler = profiler

    def search(self, *args: Any, **kwargs: Any) -> Any:
        return self.profiler.observe_stage(
            "dense_retrieval",
            self.inner.search,
            *args,
            **kwargs,
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _payload_bytes(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def _usage_int(usage: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _sanitized_reason_codes(exc: BaseException) -> list[str]:
    codes: list[str] = []
    code = getattr(exc, "code", None)
    if code:
        codes.append(str(code))
    text = str(exc)
    codes.extend(
        re.findall(
            r"M26-PA7-ME-\d+|SEMANTIC_[A-Z0-9_]+|PA7_[A-Z0-9_]+|[A-Z][A-Z0-9_]{3,}",
            text,
        )
    )
    if not codes:
        codes.append(type(exc).__name__)
    return list(dict.fromkeys(str(item) for item in codes if str(item)))


def _sanitized_traceback(exc: BaseException) -> list[dict[str, Any]]:
    if exc.__traceback__ is None:
        return []
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__):
        frames.append(
            {
                "file": Path(frame.filename).name,
                "line": int(frame.lineno),
                "function": str(frame.name),
            }
        )
    return frames[-12:]


def _error_receipt(
    *,
    exc: BaseException,
    case: Mapping[str, Any] | None,
    stage_reached: str,
    provider_call_count: int,
    repair_attempted: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "m26-latency-phase1-sanitized-error/v1",
        "case_id": str(case.get("case_id", "")) if isinstance(case, Mapping) else "",
        "expected": str(case.get("expected", "")) if isinstance(case, Mapping) else "",
        "exception_class": type(exc).__name__,
        "reason_codes": _sanitized_reason_codes(exc),
        "stage_reached": stage_reached,
        "provider_call_count": provider_call_count,
        "repair_attempted": repair_attempted,
        "sanitized_traceback": _sanitized_traceback(exc),
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_evidence_recorded": False,
        "raw_prompts_recorded": False,
        "raw_provider_text_recorded": False,
    }


def _public_pre_review_traces(
    traces: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for trace in traces:
        item = dict(trace)
        item.pop("_claim_boundary_metadata", None)
        public.append(item)
    return public


def _percentile(values: Sequence[int | float], q: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    floor = math.floor(position)
    ceil = math.ceil(position)
    if floor == ceil:
        return ordered[floor]
    return ordered[floor] * (ceil - position) + ordered[ceil] * (position - floor)


def _summary(values: Sequence[int | float]) -> dict[str, float]:
    vals = [float(item) for item in values]
    if not vals:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0}
    return {
        "mean_ms": round(sum(vals) / len(vals), 2),
        "median_ms": round(_percentile(vals, 0.5), 2),
        "p95_ms": round(_percentile(vals, 0.95), 2),
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("questions", payload)
    if not isinstance(rows, list):
        raise SystemExit("R3 questions must be a list")
    return [dict(item) for item in rows]


def _selected_cases(cases: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    del limit
    return [
        dict(case)
        for case in cases
        if str(case.get("case_id")) == "R3-Q01"
    ][:1]


def _stage_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_stage: dict[str, list[int]] = defaultdict(list)
    totals = [int(row.get("total_latency_ms", 0)) for row in rows]
    total_mean = sum(totals) / len(totals) if totals else 0
    for row in rows:
        for timing in row.get("stage_timings", []):
            if isinstance(timing, Mapping):
                by_stage[str(timing.get("stage", ""))].append(
                    int(timing.get("elapsed_ms", 0))
                )
    pareto = []
    for stage, values in by_stage.items():
        stats = _summary(values)
        pareto.append(
            {
                "stage": stage,
                **stats,
                "pct_total": round(stats["mean_ms"] / total_mean * 100, 2)
                if total_mean
                else 0.0,
            }
        )
    return sorted(pareto, key=lambda item: item["mean_ms"], reverse=True)


def _provider_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_class: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    total_mean = (
        sum(int(row.get("total_latency_ms", 0)) for row in rows) / len(rows)
        if rows
        else 0
    )
    for row in rows:
        for call in row.get("provider_calls", []):
            if isinstance(call, Mapping):
                by_class[str(call.get("call_class", ""))].append(call)
    pareto = []
    for call_class, calls in by_class.items():
        elapsed = [int(call.get("elapsed_ms", 0)) for call in calls]
        stats = _summary(elapsed)
        pareto.append(
            {
                "stage": call_class,
                "call_count": len(calls),
                **stats,
                "pct_total": round(stats["mean_ms"] / total_mean * 100, 2)
                if total_mean
                else 0.0,
                "provider_latency_mean_ms": round(
                    sum(int(call.get("provider_latency_ms", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "transport_overhead_mean_ms": round(
                    sum(int(call.get("transport_overhead_ms", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "input_tokens_mean": round(
                    sum(int(call.get("input_tokens", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "output_tokens_mean": round(
                    sum(int(call.get("output_tokens", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "cache_creation_input_tokens_mean": round(
                    sum(int(call.get("cache_creation_input_tokens", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "cache_read_input_tokens_mean": round(
                    sum(int(call.get("cache_read_input_tokens", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "payload_bytes_mean": round(
                    sum(int(call.get("payload_bytes", 0)) for call in calls)
                    / len(calls),
                    2,
                ),
                "network_attempt_max": max(
                    int(call.get("network_attempt", 0)) for call in calls
                ),
            }
        )
    return sorted(pareto, key=lambda item: item["mean_ms"], reverse=True)


def _histograms(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    repair_trigger = Counter()
    first_review = Counter()
    for row in rows:
        verification = row.get("multi_evidence_verification", {})
        if isinstance(verification, Mapping):
            for item in verification.get("repair_trigger", []):
                repair_trigger[str(item)] += 1
            for item in verification.get("verification_failure_codes_by_attempt", []):
                first_review[str(item)] += 1
    return {
        "repair_trigger": dict(sorted(repair_trigger.items())),
        "first_review_failure_code": dict(sorted(first_review.items())),
    }


def _claim_id_counts(claims: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    parsed_claim_count = len(claims)
    parsed_claim_id_count = len(
        [
            claim
            for claim in claims
            if isinstance(claim, Mapping) and str(claim.get("claim_id", "")).strip()
        ]
    )
    return parsed_claim_count, parsed_claim_id_count


def _anchor_counts(answer: str) -> tuple[int, int]:
    anchors = [str(item) for item in legacy.CLAIM_ANCHOR_RE.findall(str(answer))]
    return len(anchors), len(set(anchors))


def _answer_sentence_anchor_stats(answer: str) -> dict[str, Any]:
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?。])\s+", str(answer).strip())
        if item.strip()
    ]
    anchor_counts = [
        len(legacy.CLAIM_ANCHOR_RE.findall(sentence)) for sentence in sentences
    ]
    return {
        "answer_sentence_count": len(sentences),
        "multi_anchor_sentence_count": len(
            [count for count in anchor_counts if count > 1]
        ),
        "max_anchors_per_sentence": max(anchor_counts) if anchor_counts else 0,
    }


def _anchors_in_claim_sentence(*, answer: str, claim_id: str) -> int:
    anchor = f"[[{claim_id}]]"
    for sentence in [
        item.strip()
        for item in re.split(r"(?<=[.!?。])\s+", str(answer).strip())
        if item.strip()
    ]:
        if anchor in sentence:
            return len(legacy.CLAIM_ANCHOR_RE.findall(sentence))
    return 0


def _claim_boundary_metadata(candidate: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    answer = str(candidate.get("answer_text", ""))
    claims = [
        dict(claim)
        for claim in legacy._list(candidate.get("claims"), "structural trace claims")
        if isinstance(claim, Mapping)
    ]
    surface_sha_counts = Counter(
        canonical_sha256(str(claim.get("surface_text", ""))) for claim in claims
    )
    metadata: dict[str, dict[str, Any]] = {}
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        surface = str(claim.get("surface_text", ""))
        surface_sha = canonical_sha256(surface)
        if claim_id:
            metadata[claim_id] = {
                "claim_id": claim_id,
                "anchors_in_bound_sentence": _anchors_in_claim_sentence(
                    answer=answer,
                    claim_id=claim_id,
                ),
                "bound_surface_char_count": len(surface),
                "bound_surface_sha256": surface_sha,
                "same_bound_surface_claim_count": int(
                    surface_sha_counts.get(surface_sha, 0)
                ),
            }
    return metadata


def _set_pre_review_failure(
    trace: dict[str, Any] | None,
    failure_enum: str,
    *,
    failing_claim_id: str = "",
) -> None:
    if trace is None:
        return
    if failure_enum not in ALLOWED_PRE_REVIEW_FAILURE_ENUMS:
        failure_enum = "OTHER_PRE_REVIEW_FAILURE"
    trace["pre_review_failure_enum"] = failure_enum
    if failing_claim_id:
        trace["failing_claim_id"] = failing_claim_id


def _classify_pre_review_inputs(
    *,
    answer: str,
    claims: Sequence[Mapping[str, Any]] | None,
    label_map: Mapping[str, Mapping[str, Any]],
    snippet_map: Mapping[str, str],
) -> tuple[str, str]:
    source_claims = list(claims or [])
    if not source_claims:
        return "MISSING_STRUCTURED_CLAIMS", ""
    for raw_claim in source_claims:
        claim = dict(raw_claim)
        claim_id = str(claim.get("claim_id") or "").strip()
        if not claim_id:
            return "MISSING_CLAIM_ID", ""
        spans = runtime._answer_spans_for_claim(answer=answer, claim_id=claim_id)
        if not spans:
            return "MISSING_ANSWER_ANCHOR", claim_id
        if len(spans) > 1:
            return "AMBIGUOUS_ANSWER_ANCHOR", claim_id
        claim_type = str(claim.get("claim_type") or "").strip()
        if claim_type not in {
            "EVIDENCE_FACT",
            "EVIDENCE_SYNTHESIS",
            "MODEL_EXPLANATION",
        }:
            return "INVALID_CLAIM_TYPE", claim_id
        raw_evidence_labels = claim.get("evidence_labels", [])
        if raw_evidence_labels is None:
            raw_evidence_labels = []
        if not isinstance(raw_evidence_labels, list):
            return "MISSING_EVIDENCE_LABELS", claim_id
        evidence_labels = [str(label) for label in raw_evidence_labels if str(label)]
        if claim_type == "MODEL_EXPLANATION":
            continue
        if not evidence_labels:
            return "MISSING_EVIDENCE_LABELS", claim_id
        unknown_labels = [label for label in evidence_labels if label not in label_map]
        if unknown_labels:
            return "UNKNOWN_EVIDENCE_LABELS", claim_id
        for label in evidence_labels:
            item = label_map[label]
            evidence_id = str(item.get("evidence_id", ""))
            quote = snippet_map.get(evidence_id) or legacy._first_exact_evidence_quote(
                str(item.get("passage_text", "")), max_chars=360
            )
            if not quote:
                return "EVIDENCE_BINDING_FAILED", claim_id
    return "", ""


def _classify_pre_review_exception(exc: BaseException) -> str:
    text = str(exc)
    if "structured claims required" in text:
        return "MISSING_STRUCTURED_CLAIMS"
    if "missing claim_id" in text:
        return "MISSING_CLAIM_ID"
    if "ambiguous answer anchors" in text:
        return "AMBIGUOUS_ANSWER_ANCHOR"
    if "missing answer anchor" in text or "missing provider-authored answer span" in text:
        return "MISSING_ANSWER_ANCHOR"
    if "invalid claim_type" in text:
        return "INVALID_CLAIM_TYPE"
    if "invalid claim-local evidence labels" in text or "missing claim-local evidence labels" in text:
        return "MISSING_EVIDENCE_LABELS"
    if "unknown evidence labels" in text:
        return "UNKNOWN_EVIDENCE_LABELS"
    if "could not bind provider prose to evidence" in text:
        return "EVIDENCE_BINDING_FAILED"
    return "OTHER_PRE_REVIEW_FAILURE"


def _semantic_review_verdict_summary(
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    review = verification.get("semantic_review", {})
    if not isinstance(review, Mapping):
        return {
            "claim_judgment_count": 0,
            "claim_verdict_counts": {},
            "coverage_verdict": "",
            "evidence_id_reference_count": 0,
        }
    verdicts = Counter()
    evidence_ref_count = 0
    judgments = review.get("claim_judgments", [])
    if isinstance(judgments, Sequence) and not isinstance(judgments, (str, bytes)):
        for judgment in judgments:
            if not isinstance(judgment, Mapping):
                continue
            verdicts[str(judgment.get("verdict", ""))] += 1
            evidence_ids = judgment.get("evidence_ids", [])
            if isinstance(evidence_ids, Sequence) and not isinstance(
                evidence_ids, (str, bytes)
            ):
                evidence_ref_count += len(evidence_ids)
    coverage = review.get("visible_coverage", {})
    coverage_verdict = (
        str(coverage.get("verdict", "")) if isinstance(coverage, Mapping) else ""
    )
    return {
        "claim_judgment_count": sum(verdicts.values()),
        "claim_verdict_counts": dict(sorted(verdicts.items())),
        "coverage_verdict": coverage_verdict,
        "evidence_id_reference_count": evidence_ref_count,
    }


def _semantic_review_verdict_totals(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    claim_verdicts = Counter()
    coverage_verdicts = Counter()
    judgment_count = 0
    evidence_ref_count = 0
    for row in rows:
        summary = row.get("semantic_review_verdict_summary", {})
        if not isinstance(summary, Mapping):
            continue
        judgment_count += int(summary.get("claim_judgment_count", 0))
        evidence_ref_count += int(summary.get("evidence_id_reference_count", 0))
        for verdict, count in dict(summary.get("claim_verdict_counts", {})).items():
            claim_verdicts[str(verdict)] += int(count)
        coverage_verdict = str(summary.get("coverage_verdict", ""))
        if coverage_verdict:
            coverage_verdicts[coverage_verdict] += 1
    return {
        "claim_judgment_count": judgment_count,
        "claim_verdict_counts": dict(sorted(claim_verdicts.items())),
        "coverage_verdict_counts": dict(sorted(coverage_verdicts.items())),
        "evidence_id_reference_count": evidence_ref_count,
    }


def _pre_review_trace_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failure_enums = Counter()
    stage_counts = Counter()
    attempt_count = 0
    reviewer_reached_count = 0
    reviewer_blocked_claim_count = 0
    reviewer_blocked_shared_boundary_count = 0
    for row in rows:
        for trace in row.get("pre_review_traces", []):
            if not isinstance(trace, Mapping):
                continue
            attempt_count += 1
            stage = str(trace.get("pre_review_stage_reached", ""))
            if stage:
                stage_counts[stage] += 1
            if stage == "semantic_reviewer_reached":
                reviewer_reached_count += 1
            failure_enum = str(trace.get("pre_review_failure_enum", ""))
            if failure_enum:
                failure_enums[failure_enum] += 1
            for blocked_claim in trace.get("reviewer_blocked_claims", []):
                if not isinstance(blocked_claim, Mapping):
                    continue
                reviewer_blocked_claim_count += 1
                if (
                    int(blocked_claim.get("anchors_in_bound_sentence", 0)) > 1
                    or int(blocked_claim.get("same_bound_surface_claim_count", 0)) > 1
                ):
                    reviewer_blocked_shared_boundary_count += 1
    return {
        "attempt_count": attempt_count,
        "reviewer_reached_count": reviewer_reached_count,
        "failure_enum_counts": dict(sorted(failure_enums.items())),
        "stage_reached_counts": dict(sorted(stage_counts.items())),
        "reviewer_blocked_claim_count": reviewer_blocked_claim_count,
        "reviewer_blocked_shared_boundary_count": (
            reviewer_blocked_shared_boundary_count
        ),
    }


def _install_stage_wrappers(profiler: Phase1Profiler) -> Callable[[], None]:
    original_bundle = runtime.load_production_answer_bundle
    original_lexical = runtime.retrieve_wiki_first
    original_select = legacy._select_evidence
    original_requirements = runtime._semantic_requirements
    original_strengthen = runtime._strengthen_evidence
    original_synthesize = runtime._synthesize_and_verify
    original_response = runtime._response_from_verification
    original_parse_compact = runtime._parse_compact_provider_result
    original_runtime_bound = runtime._runtime_bound_candidate
    original_bounded_publication = runtime._bounded_publication_candidate
    original_semantic_review = runtime._call_semantic_entailment_review
    original_review_blocking = runtime._semantic_review_blocking_failures

    runtime.load_production_answer_bundle = lambda *a, **kw: profiler.observe_stage(
        "production_bundle_load_and_gate", original_bundle, *a, **kw
    )
    runtime.retrieve_wiki_first = lambda *a, **kw: profiler.observe_stage(
        "lexical_retrieval", original_lexical, *a, **kw
    )
    legacy._select_evidence = lambda *a, **kw: profiler.observe_stage(
        "evidence_selection", original_select, *a, **kw
    )
    runtime._semantic_requirements = lambda *a, **kw: profiler.observe_stage(
        "semantic_requirement_derivation", original_requirements, *a, **kw
    )
    runtime._strengthen_evidence = lambda *a, **kw: profiler.observe_stage(
        "semantic_evidence_strengthening", original_strengthen, *a, **kw
    )
    runtime._synthesize_and_verify = lambda *a, **kw: profiler.observe_stage(
        "semantic_synthesis_review_and_local_verification",
        original_synthesize,
        *a,
        **kw,
    )
    runtime._response_from_verification = lambda *a, **kw: profiler.observe_stage(
        "final_citation_and_response_dto", original_response, *a, **kw
    )

    def parse_compact_with_trace(text: str) -> dict[str, Any]:
        trace = profiler.active_pre_review_trace()
        if trace is not None:
            trace["pre_review_stage_reached"] = "closure_parse"
        try:
            parsed = original_parse_compact(text)
        except ValueError as exc:
            _set_pre_review_failure(trace, "OTHER_PRE_REVIEW_FAILURE")
            raise
        if trace is not None:
            claims = runtime._parsed_provider_claims(parsed)
            answer = runtime._normalize_compact_provider_visible_answer(
                runtime._parsed_provider_answer_text(parsed)
            )
            parsed_claim_count, parsed_claim_id_count = _claim_id_counts(claims)
            answer_anchor_count, unique_anchored_claim_id_count = _anchor_counts(answer)
            trace.update(
                {
                    "closure_parse_success": True,
                    "parsed_claim_count": parsed_claim_count,
                    "parsed_claim_id_count": parsed_claim_id_count,
                    "answer_anchor_count": answer_anchor_count,
                    "unique_anchored_claim_id_count": unique_anchored_claim_id_count,
                }
            )
        return parsed

    def runtime_bound_with_trace(*args: Any, **kwargs: Any) -> dict[str, Any]:
        trace = profiler.active_pre_review_trace()
        if trace is not None:
            trace["pre_review_stage_reached"] = "runtime_bound_candidate"
        failure_enum, failing_claim_id = _classify_pre_review_inputs(
            answer=str(kwargs.get("answer", "")),
            claims=kwargs.get("claims"),
            label_map=kwargs.get("label_map", {}),
            snippet_map=kwargs.get("snippet_map", {}),
        )
        try:
            candidate = original_runtime_bound(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            _set_pre_review_failure(
                trace,
                failure_enum or _classify_pre_review_exception(exc),
                failing_claim_id=failing_claim_id,
            )
            raise
        if trace is not None:
            trace["pre_review_stage_reached"] = "runtime_bound_candidate_success"
            trace.update(
                _answer_sentence_anchor_stats(str(candidate.get("answer_text", "")))
            )
            trace["_claim_boundary_metadata"] = _claim_boundary_metadata(candidate)
        return candidate

    def bounded_publication_with_trace(*args: Any, **kwargs: Any) -> Any:
        trace = profiler.active_pre_review_trace()
        if trace is not None:
            trace["pre_review_stage_reached"] = "bounded_publication"
        try:
            result = original_bounded_publication(*args, **kwargs)
        except Exception:
            _set_pre_review_failure(trace, "BOUNDED_PUBLICATION_FAILED")
            raise
        if trace is not None:
            trace["pre_review_stage_reached"] = "bounded_publication_success"
        return result

    def semantic_review_with_trace(*args: Any, **kwargs: Any) -> Any:
        trace = profiler.active_pre_review_trace()
        if trace is not None:
            trace["pre_review_stage_reached"] = "semantic_reviewer_reached"
        return original_semantic_review(*args, **kwargs)

    def review_blocking_with_trace(review: Mapping[str, Any]) -> list[str]:
        failures = original_review_blocking(review)
        trace = profiler.active_pre_review_trace()
        if trace is not None:
            boundary_by_claim = trace.get("_claim_boundary_metadata", {})
            blocked_claims: list[dict[str, Any]] = []
            if isinstance(boundary_by_claim, Mapping):
                for failure in failures:
                    text = str(failure)
                    if not text.startswith("SEMANTIC_REVIEW_BLOCKED:"):
                        continue
                    parts = text.split(":")
                    claim_id = parts[1] if len(parts) > 1 else ""
                    metadata = boundary_by_claim.get(claim_id)
                    if isinstance(metadata, Mapping):
                        blocked_claims.append(dict(metadata))
            trace["reviewer_blocked_claims"] = blocked_claims
        return failures

    runtime._parse_compact_provider_result = parse_compact_with_trace
    runtime._runtime_bound_candidate = runtime_bound_with_trace
    runtime._bounded_publication_candidate = bounded_publication_with_trace
    runtime._call_semantic_entailment_review = semantic_review_with_trace
    runtime._semantic_review_blocking_failures = review_blocking_with_trace

    def restore() -> None:
        runtime.load_production_answer_bundle = original_bundle
        runtime.retrieve_wiki_first = original_lexical
        legacy._select_evidence = original_select
        runtime._semantic_requirements = original_requirements
        runtime._strengthen_evidence = original_strengthen
        runtime._synthesize_and_verify = original_synthesize
        runtime._response_from_verification = original_response
        runtime._parse_compact_provider_result = original_parse_compact
        runtime._runtime_bound_candidate = original_runtime_bound
        runtime._bounded_publication_candidate = original_bounded_publication
        runtime._call_semantic_entailment_review = original_semantic_review
        runtime._semantic_review_blocking_failures = original_review_blocking

    return restore


def _run_case(
    *,
    root: Path,
    gate_path: Path,
    case: Mapping[str, Any],
    owner_subject_hash: str,
    provider_client: Any,
    dense_channel: Any,
    require_remote_dense: bool,
) -> dict[str, Any]:
    profiler = Phase1Profiler()
    restore = _install_stage_wrappers(profiler)
    started = time.monotonic()
    try:
        response = run_owner_query_for_web(
            root=root,
            gate_path=gate_path,
            request_payload={"question": str(case.get("question", ""))},
            owner_subject_hash=owner_subject_hash,
            provider_client=ObservedProvider(provider_client, profiler),
            dense_channel=ObservedDenseChannel(dense_channel, profiler),
            require_remote_dense=require_remote_dense,
            max_cost=Decimal("0.25"),
        )
    except Exception as exc:
        stage_reached = (
            str(profiler.stage_timings[-1].get("stage", "request_dispatch"))
            if profiler.stage_timings
            else "request_dispatch"
        )
        provider_call_count = len(
            [
                call
                for call in profiler.provider_calls
                if call.get("call_class") in SEMANTIC_CALLS
            ]
        )
        repair_attempted = any(
            call.get("call_class") == "aq_semantic_closure_repair"
            for call in profiler.provider_calls
        )
        receipt = _error_receipt(
            exc=exc,
            case=case,
            stage_reached=stage_reached,
            provider_call_count=provider_call_count,
            repair_attempted=repair_attempted,
        )
        return {
            "case_id": str(case.get("case_id", "")),
            "class": str(case.get("class", "")),
            "expected": str(case.get("expected", "")),
            "question_sha256": canonical_sha256(str(case.get("question", ""))),
            "status": "diagnostic_exception",
            "terminal_status": "diagnostic_exception",
            "safe_abstention": True,
            "answer_source": "diagnostic_exception",
            "total_latency_ms": _elapsed_ms(started),
            "provider_call_count": provider_call_count,
            "repair_attempted": repair_attempted,
            "selected_evidence_count": 0,
            "claim_count": 0,
            "citation_count": 0,
            "unsupported_accepted_claims": 0,
            "provider_contract": "",
            "natural_answer_fallback_used": False,
            "stage_timings": profiler.stage_timings,
            "provider_calls": profiler.provider_calls,
            "pre_review_traces": _public_pre_review_traces(
                profiler.pre_review_traces
            ),
            "provider_attempt_telemetry_count": 0,
            "multi_evidence_verification": {
                "repair_trigger": [],
                "verification_failure_codes_by_attempt": receipt["reason_codes"],
            },
            "semantic_review_verdict_summary": {
                "claim_judgment_count": 0,
                "claim_verdict_counts": {},
                "coverage_verdict": "",
                "evidence_id_reference_count": 0,
            },
            "diagnostic_failure": True,
            "diagnostic_failure_receipt": receipt,
        }
    finally:
        restore()
    total_latency_ms = _elapsed_ms(started)
    verification = response.get("multi_evidence_verification", {})
    provider_attempts = (
        verification.get("provider_attempt_telemetry", [])
        if isinstance(verification, Mapping)
        else []
    )
    return {
        "case_id": str(case.get("case_id", "")),
        "class": str(case.get("class", "")),
        "expected": str(case.get("expected", "")),
        "question_sha256": canonical_sha256(str(case.get("question", ""))),
        "status": response.get("status"),
        "terminal_status": response.get("terminal_status"),
        "safe_abstention": bool(response.get("safe_abstention", True)),
        "answer_source": response.get("answer_source"),
        "total_latency_ms": total_latency_ms,
        "provider_call_count": len(
            [call for call in profiler.provider_calls if call.get("call_class") in SEMANTIC_CALLS]
        ),
        "repair_attempted": bool(
            response.get("multi_evidence_verification", {}).get(
                "bounded_repair_attempted",
                response.get("repair_attempted", False),
            )
            if isinstance(response.get("multi_evidence_verification"), Mapping)
            else False
        ),
        "selected_evidence_count": len(response.get("selected_evidence", [])),
        "claim_count": len(response.get("answer_claims", [])),
        "citation_count": len(response.get("citations", [])),
        "unsupported_accepted_claims": int(
            response.get("integrity", {}).get("unsupported_accepted_claims", 0)
            if isinstance(response.get("integrity"), Mapping)
            else 0
        ),
        "provider_contract": response.get("multi_evidence_verification", {}).get(
            "provider_contract"
        )
        if isinstance(response.get("multi_evidence_verification"), Mapping)
        else "",
        "natural_answer_fallback_used": bool(
            response.get("multi_evidence_verification", {}).get(
                "natural_answer_fallback_used", False
            )
            if isinstance(response.get("multi_evidence_verification"), Mapping)
            else False
        ),
        "stage_timings": profiler.stage_timings,
        "provider_calls": profiler.provider_calls,
        "pre_review_traces": _public_pre_review_traces(profiler.pre_review_traces),
        "provider_attempt_telemetry_count": len(provider_attempts)
        if isinstance(provider_attempts, Sequence)
        else 0,
        "multi_evidence_verification": {
            "repair_trigger": list(
                verification.get("repair_trigger", [])
                if isinstance(verification, Mapping)
                else []
            ),
            "verification_failure_codes_by_attempt": list(
                verification.get("verification_failure_codes_by_attempt", [])
                if isinstance(verification, Mapping)
                else []
            ),
        },
        "semantic_review_verdict_summary": _semantic_review_verdict_summary(
            verification if isinstance(verification, Mapping) else {}
        ),
    }


def _row_failure(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("diagnostic_failure"):
        receipt = row.get("diagnostic_failure_receipt", {})
        return {
            "case_id": str(row.get("case_id", "")),
            "reason": "diagnostic_exception",
            "status": str(row.get("status", "")),
            "exception_class": str(receipt.get("exception_class", ""))
            if isinstance(receipt, Mapping)
            else "",
            "reason_codes": list(receipt.get("reason_codes", []))
            if isinstance(receipt, Mapping)
            else [],
            "stage_reached": str(receipt.get("stage_reached", ""))
            if isinstance(receipt, Mapping)
            else "",
        }
    expected = str(row.get("expected", ""))
    if expected == "answer":
        if row.get("status") != "owner_only_cited_answer":
            return {
                "case_id": str(row.get("case_id", "")),
                "reason": "answer_status",
                "status": str(row.get("status", "")),
                "reason_codes": list(
                    row.get("multi_evidence_verification", {}).get(
                        "verification_failure_codes_by_attempt", []
                    )
                )
                if isinstance(row.get("multi_evidence_verification"), Mapping)
                else [],
            }
        if int(row.get("unsupported_accepted_claims", 0)) != 0:
            return {
                "case_id": str(row.get("case_id", "")),
                "reason": "unsupported_claim",
                "unsupported_accepted_claims": int(
                    row.get("unsupported_accepted_claims", 0)
                ),
            }
    elif row.get("case_id") in {"R3-Q10", "R3-Q11"} and not row.get(
        "safe_abstention"
    ):
        return {
            "case_id": str(row.get("case_id", "")),
            "reason": "safe_abstention",
            "status": str(row.get("status", "")),
        }
    return None


def _build_artifact(
    *,
    rows: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    error_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    answer_rows = [row for row in rows if row.get("expected") == "answer"]
    return {
        "schema_version": "m26-latency-phase1-profile/v1",
        "case_count": len(rows),
        "answerable_profile_case_count": len(answer_rows),
        "failure_count": len(failures),
        "failures": list(failures),
        "error_receipt_count": len(error_receipts),
        "error_receipts": list(error_receipts),
        "sequential_concurrency": 1,
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_evidence_recorded": False,
        "raw_prompts_recorded": False,
        "raw_provider_text_recorded": False,
        "protected_knowledge_mutations": 0,
        "totals": _summary([row["total_latency_ms"] for row in answer_rows]),
        "stage_pareto": _stage_pareto(answer_rows),
        "provider_pareto": _provider_pareto(answer_rows),
        "repair_and_first_review_histograms": _histograms(answer_rows),
        "semantic_review_verdict_totals": _semantic_review_verdict_totals(answer_rows),
        "pre_review_trace_summary": _pre_review_trace_summary(rows),
        "rows": [dict(row) for row in rows],
    }


def _write_error_output(
    path: Path | None,
    error_receipts: Sequence[Mapping[str, Any]],
) -> None:
    if path is None:
        return
    _atomic_write_json(
        path,
        {
            "schema_version": "m26-latency-phase1-sanitized-errors/v1",
            "error_count": len(error_receipts),
            "errors": list(error_receipts),
            "raw_questions_recorded": False,
            "raw_answers_recorded": False,
            "raw_evidence_recorded": False,
            "raw_prompts_recorded": False,
            "raw_provider_text_recorded": False,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--error-output", type=Path)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    error_receipts: list[dict[str, Any]] = []
    try:
        root = args.root.resolve()
        gate_path = root / DEFAULT_GATE_PATH
        owner_hash = os.environ["KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"]
        provider = MiniMaxClient(
            os.environ.get("MINIMAX_API_KEY", ""),
            max_calls=64,
            max_cost=Decimal("2.00"),
        )
        dense_channel = legacy.dense_channel_from_env(
            require_remote=os.environ.get("M26_QUERY_REQUIRE_REMOTE_DENSE", "").lower()
            == "true"
        )
        cases = _selected_cases(_load_cases(args.questions), args.limit)
        for case in cases:
            row = _run_case(
                root=root,
                gate_path=gate_path,
                case=case,
                owner_subject_hash=owner_hash,
                provider_client=provider,
                dense_channel=dense_channel,
                require_remote_dense=False,
            )
            rows.append(row)
            receipt = row.get("diagnostic_failure_receipt")
            if isinstance(receipt, Mapping):
                error_receipts.append(dict(receipt))
            failure = _row_failure(row)
            if failure is not None:
                failures.append(failure)
                break
    except Exception as exc:
        receipt = _error_receipt(
            exc=exc,
            case=None,
            stage_reached="profile_setup_or_artifact",
            provider_call_count=0,
            repair_attempted=False,
        )
        error_receipts.append(receipt)
        failures.append(
            {
                "case_id": "",
                "reason": "profile_setup_or_artifact",
                "exception_class": receipt["exception_class"],
                "reason_codes": receipt["reason_codes"],
                "stage_reached": receipt["stage_reached"],
            }
        )
    artifact = _build_artifact(
        rows=rows,
        failures=failures,
        error_receipts=error_receipts,
    )
    _atomic_write_json(args.output, artifact)
    _write_error_output(args.error_output, error_receipts)
    print(json.dumps({"output": str(args.output), "case_count": len(rows)}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
