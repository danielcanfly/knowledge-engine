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
VARIANT_LEGACY_REVIEWER = "variant_a_legacy_reviewer_v1"
VARIANT_PHASE1_REVIEWER = "variant_b_phase1_current_reviewer"


class Phase1Profiler:
    def __init__(self) -> None:
        self.stage_timings: list[dict[str, Any]] = []
        self.provider_calls: list[dict[str, Any]] = []
        self.semantic_decision_trace = SemanticDecisionTrace()

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


class SemanticDecisionTrace:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    def start_attempt(self) -> dict[str, Any]:
        attempt = {
            "attempt_index": len(self.attempts) + 1,
            "closure_parse_status": "not_reached",
            "candidate_claim_count": 0,
            "candidate_claim_id_digest": "",
            "reviewer_parse_status": "not_reached",
            "reviewer_canonicalization_status": "not_reached",
            "reviewer_judgment_count": 0,
            "verdict_count_histogram": {},
            "coverage_verdict": "",
            "missing_claim_ids_count": 0,
            "duplicate_claim_ids_count": 0,
            "unknown_claim_ids_count": 0,
            "out_of_local_evidence_reference_count": 0,
            "me_065_triggered": False,
            "semantic_review_blocking_reason_enum": [],
            "bounded_publication_validation_result": "not_reached",
            "legacy_verifier_exception_reason_code": "",
            "outer_failure_reasons_observed": [],
            "repair_trigger_enum": "",
        }
        self.attempts.append(attempt)
        self.current = attempt
        return attempt

    def attempt(self) -> dict[str, Any]:
        return self.current if self.current is not None else self.start_attempt()

    def add_failure_reason(self, reason: str) -> None:
        if not reason:
            return
        attempt = self.attempt()
        attempt["outer_failure_reasons_observed"] = list(
            dict.fromkeys([*attempt["outer_failure_reasons_observed"], str(reason)])
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _payload_bytes(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def _claim_id_digest(claim_ids: Sequence[str]) -> str:
    return canonical_sha256("|".join(str(item) for item in sorted(claim_ids)))


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


def _selected_cases(
    cases: Sequence[Mapping[str, Any]],
    limit: int,
    *,
    case_ids: Sequence[str] = (),
    include_safety: bool = True,
) -> list[dict[str, Any]]:
    if case_ids:
        wanted = set(str(item) for item in case_ids)
        return [dict(case) for case in cases if str(case.get("case_id", "")) in wanted]
    answerable = [dict(case) for case in cases if case.get("expected") == "answer"][:limit]
    if not include_safety:
        return answerable
    safety = [
        dict(case)
        for case in cases
        if str(case.get("case_id")) in {"R3-Q10", "R3-Q11"}
    ]
    return [*answerable, *safety]


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


def _review_claim_id_counts(
    review: Mapping[str, Any],
    claim_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    observed: list[str] = []
    for raw in review.get("claim_judgments", []):
        if isinstance(raw, Mapping):
            observed.append(str(raw.get("claim_id", "")).strip())
    expected = set(claim_by_id)
    observed_set = set(item for item in observed if item)
    return {
        "missing_claim_ids_count": len(expected - observed_set),
        "duplicate_claim_ids_count": len(observed) - len(set(observed)),
        "unknown_claim_ids_count": len(observed_set - expected),
    }


def _review_out_of_local_count(
    review: Mapping[str, Any],
    claim_by_id: Mapping[str, Mapping[str, Any]],
) -> int:
    count = 0
    for raw in review.get("claim_judgments", []):
        if not isinstance(raw, Mapping):
            continue
        claim_id = str(raw.get("claim_id", ""))
        claim = claim_by_id.get(claim_id)
        allowed = set(runtime._claim_local_evidence_ids(claim)) if claim else set()
        aliases = runtime._claim_local_evidence_aliases(claim) if claim else {}
        for raw_evidence_id in raw.get("evidence_ids", []):
            evidence_ref = str(raw_evidence_id)
            if evidence_ref not in allowed and evidence_ref not in aliases:
                count += 1
    return count


def _review_summary(review: Mapping[str, Any]) -> dict[str, Any]:
    verdicts = Counter()
    judgments = review.get("claim_judgments", [])
    if isinstance(judgments, Sequence) and not isinstance(judgments, (str, bytes)):
        for raw in judgments:
            if isinstance(raw, Mapping):
                verdicts[str(raw.get("verdict", ""))] += 1
    coverage = review.get("visible_coverage", {})
    return {
        "reviewer_judgment_count": sum(verdicts.values()),
        "verdict_count_histogram": dict(sorted(verdicts.items())),
        "coverage_verdict": str(coverage.get("verdict", ""))
        if isinstance(coverage, Mapping)
        else "",
    }


def _finalized_semantic_trace(trace: SemanticDecisionTrace) -> list[dict[str, Any]]:
    attempts = [dict(item) for item in trace.attempts]
    for index, attempt in enumerate(attempts):
        reasons = [
            str(item)
            for item in attempt.get("outer_failure_reasons_observed", [])
            if str(item)
        ]
        if index == 0 and len(attempts) > 1:
            attempt["repair_trigger_enum"] = (
                reasons[0] if reasons else "FIRST_ATTEMPT_FAILED"
            )
        elif index > 0:
            attempt["repair_trigger_enum"] = "BOUNDED_REPAIR_ATTEMPT"
    return attempts


def _legacy_semantic_review_payload(
    *,
    question: str,
    intent_class: str,
    candidate: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    evidence_by_id = {str(item.get("evidence_id", "")): item for item in evidence}
    claim_cases: list[dict[str, Any]] = []
    for raw_claim in legacy._list(candidate.get("claims"), "semantic review claims"):
        claim = legacy._object(raw_claim, "semantic review claim")
        local_evidence: list[dict[str, Any]] = []
        for raw_ref in legacy._list(
            claim.get("support_refs"), "semantic review support refs"
        ):
            ref = legacy._object(raw_ref, "semantic review support ref")
            evidence_id = str(ref.get("evidence_id", ""))
            item = evidence_by_id.get(evidence_id, {})
            graph_fact = {}
            if item.get("evidence_type") == "graph_edge":
                graph_fact = {
                    "edge_id": str(item.get("edge_id", "")),
                    "edge_source": str(item.get("edge_source", "")),
                    "edge_target": str(item.get("edge_target", "")),
                    "edge_source_label": str(item.get("edge_source_label", "")),
                    "edge_target_label": str(item.get("edge_target_label", "")),
                    "relation_type": str(item.get("relation_type", "")),
                    "provenance": "graph_artifact_fact",
                    "relation_metadata": dict(item.get("relation_metadata", {}))
                    if isinstance(item.get("relation_metadata"), Mapping)
                    else legacy._graph_relation_metadata(
                        str(item.get("relation_type", ""))
                    ),
                }
            local_evidence.append(
                {
                    "evidence_label": f"local_{len(local_evidence) + 1}",
                    "evidence_id": evidence_id,
                    "locator_id": str(ref.get("locator_id", "")),
                    "evidence_type": str(item.get("evidence_type", "passage")),
                    "source_identity": str(
                        item.get("source_identity") or item.get("source_id") or ""
                    ),
                    "text": str(ref.get("exact_quote", "")),
                    "graph_fact": graph_fact,
                }
            )
        allowed_evidence_ids = [
            str(item.get("evidence_id", "")) for item in local_evidence
        ]
        allowed_evidence_labels = [
            str(item.get("evidence_label", "")) for item in local_evidence
        ]
        claim_cases.append(
            {
                "claim_id": str(claim.get("claim_id", "")),
                "claim_type": str(claim.get("claim_type", "")),
                "surface_text": str(claim.get("surface_text", "")),
                "allowed_evidence_ids": allowed_evidence_ids,
                "allowed_evidence_labels": allowed_evidence_labels,
                "evidence_id_by_label": dict(
                    zip(allowed_evidence_labels, allowed_evidence_ids, strict=False)
                ),
                "evidence": local_evidence,
            }
        )
    task = {
        "schema_version": runtime.SEMANTIC_REVIEW_SCHEMA_VERSION,
        "question_context": question,
        "intent_class": intent_class,
        "answer_text": str(candidate.get("answer_text", "")),
        "claim_cases": claim_cases,
        "review_protocol": {
            "evidence_ids_rule": (
                "For an ENTAILED judgment, evidence_ids must contain only either "
                "exact evidence_id strings from that claim case's allowed_evidence_ids "
                "or exact claim-local labels from allowed_evidence_labels. Claim-local "
                "labels are aliases for that same case's evidence_id_by_label entries. "
                "Unknown or cross-claim IDs or labels are invalid."
            ),
            "model_explanation_rule": (
                "If claim_type is MODEL_EXPLANATION and the claim case has no local "
                "evidence, use verdict GENERIC_EXPLANATION with evidence_ids []. Do "
                "not use ENTAILED for a claim with no local evidence."
            ),
            "visible_coverage_rule": (
                "Visible coverage concerns material KB-dependent assertions in "
                "answer_text. Do not mark coverage UNCOVERED merely because a visible "
                "generic glue statement is represented by a MODEL_EXPLANATION claim."
            ),
        },
        "output": {
            "schema_version": runtime.SEMANTIC_REVIEW_SCHEMA_VERSION,
            "claim_judgments": [
                {
                    "claim_id": "claim_1",
                    "verdict": (
                        "ENTAILED|CONTRADICTED|INSUFFICIENT|GENERIC_EXPLANATION"
                    ),
                    "evidence_ids": [],
                }
            ],
            "visible_coverage": {
                "verdict": "COVERED|UNCOVERED",
                "uncovered_assertions": [],
            },
        },
    }
    system = (
        "You are the bounded M26 claim semantic-entailment reviewer. Return exactly one "
        "JSON object. Judge each claim's meaning against only that claim case's local "
        "evidence array. The user question, other claim surfaces, and other claim cases "
        "are context only and are not evidence. Paraphrase, voice, and order changes may "
        "be entailed; contradiction, strengthening, identity, quantity, time, causality, "
        "polarity, graph direction, or endpoint mutation is not entailed. Also report "
        "whether every material KB-dependent assertion visible in answer_text is covered "
        "by a structured claim. For each ENTAILED judgment, evidence_ids must be an array "
        "of exact evidence_id strings from that claim case's allowed_evidence_ids, or exact "
        "claim-local labels from that claim case's allowed_evidence_labels. "
        "If claim_type is MODEL_EXPLANATION and the claim case has no local evidence, "
        "return verdict GENERIC_EXPLANATION with evidence_ids []. "
        "If no allowed local evidence entails the claim, use INSUFFICIENT or CONTRADICTED "
        "instead of ENTAILED. Do not invent claim IDs, evidence IDs, or evidence labels; "
        "never output example labels unless that exact string is present in the claim case. "
        "For visible_coverage, only list material KB-dependent assertions that are not "
        "represented by any structured claim; a listed MODEL_EXPLANATION glue claim is "
        "not by itself an uncovered assertion."
    )
    return {
        "model": "MiniMax-M3",
        "max_tokens": 2048,
        "temperature": 0,
        "stream": False,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(task, ensure_ascii=False, separators=(",", ":")),
            }
        ],
    }


def _install_variant(variant: str) -> Callable[[], None]:
    original_payload = runtime._semantic_review_payload
    if variant == VARIANT_LEGACY_REVIEWER:
        runtime._semantic_review_payload = _legacy_semantic_review_payload
    elif variant != VARIANT_PHASE1_REVIEWER:
        raise ValueError(f"unknown diagnostic variant: {variant}")

    def restore() -> None:
        runtime._semantic_review_payload = original_payload

    return restore


def _install_stage_wrappers(profiler: Phase1Profiler) -> Callable[[], None]:
    original_bundle = runtime.load_production_answer_bundle
    original_lexical = runtime.retrieve_wiki_first
    original_select = legacy._select_evidence
    original_requirements = runtime._semantic_requirements
    original_strengthen = runtime._strengthen_evidence
    original_synthesize = runtime._synthesize_and_verify
    original_response = runtime._response_from_verification
    original_parse_closure = runtime._parse_compact_provider_result
    original_runtime_bound = runtime._runtime_bound_candidate
    original_parse_review = runtime._parse_semantic_review_result
    original_canonical_review = runtime._canonical_semantic_review_result
    original_canonicalize_refs = runtime._canonicalize_semantic_review_evidence_refs
    original_validate_claim_set = runtime._validate_semantic_review_claim_set
    original_out_of_local = runtime._semantic_review_has_out_of_local_evidence
    original_blocking = runtime._semantic_review_blocking_failures
    original_legacy_verify = legacy._verify_multi_evidence_provider_output

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
    def parse_closure_wrapper(*args: Any, **kwargs: Any) -> Any:
        attempt = profiler.semantic_decision_trace.start_attempt()
        try:
            result = original_parse_closure(*args, **kwargs)
        except Exception as exc:
            attempt["closure_parse_status"] = "failed"
            profiler.semantic_decision_trace.add_failure_reason(type(exc).__name__)
            raise
        attempt["closure_parse_status"] = "ok"
        return result

    def runtime_bound_wrapper(*args: Any, **kwargs: Any) -> Any:
        candidate = original_runtime_bound(*args, **kwargs)
        claim_ids = [
            str(claim.get("claim_id", ""))
            for claim in candidate.get("claims", [])
            if isinstance(claim, Mapping) and str(claim.get("claim_id", ""))
        ]
        attempt = profiler.semantic_decision_trace.attempt()
        attempt["candidate_claim_count"] = len(claim_ids)
        attempt["candidate_claim_id_digest"] = _claim_id_digest(claim_ids)
        return candidate

    def canonical_review_wrapper(value: Mapping[str, Any]) -> dict[str, Any]:
        attempt = profiler.semantic_decision_trace.attempt()
        try:
            result = original_canonical_review(value)
        except Exception as exc:
            attempt["reviewer_canonicalization_status"] = "failed"
            profiler.semantic_decision_trace.add_failure_reason(type(exc).__name__)
            raise
        attempt["reviewer_canonicalization_status"] = "ok"
        return result

    def parse_review_wrapper(*args: Any, **kwargs: Any) -> Any:
        attempt = profiler.semantic_decision_trace.attempt()
        try:
            review = original_parse_review(*args, **kwargs)
        except Exception as exc:
            attempt["reviewer_parse_status"] = "failed"
            profiler.semantic_decision_trace.add_failure_reason(type(exc).__name__)
            raise
        attempt["reviewer_parse_status"] = "ok"
        attempt.update(_review_summary(review))
        return review

    def canonicalize_refs_wrapper(
        semantic_review: Mapping[str, Any],
        claim_by_id: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        review = original_canonicalize_refs(semantic_review, claim_by_id)
        attempt = profiler.semantic_decision_trace.attempt()
        attempt.update(_review_summary(review))
        attempt.update(_review_claim_id_counts(review, claim_by_id))
        attempt["out_of_local_evidence_reference_count"] = _review_out_of_local_count(
            review,
            claim_by_id,
        )
        return review

    def validate_claim_set_wrapper(
        semantic_review: Mapping[str, Any],
        claim_by_id: Mapping[str, Mapping[str, Any]],
    ) -> None:
        attempt = profiler.semantic_decision_trace.attempt()
        attempt.update(_review_claim_id_counts(semantic_review, claim_by_id))
        try:
            original_validate_claim_set(semantic_review, claim_by_id)
        except Exception as exc:
            profiler.semantic_decision_trace.add_failure_reason(type(exc).__name__)
            raise

    def out_of_local_wrapper(
        semantic_review: Mapping[str, Any],
        claim_by_id: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        result = original_out_of_local(semantic_review, claim_by_id)
        attempt = profiler.semantic_decision_trace.attempt()
        attempt["me_065_triggered"] = bool(result)
        if result:
            profiler.semantic_decision_trace.add_failure_reason("M26-PA7-ME-065")
        return result

    def blocking_wrapper(review: Mapping[str, Any]) -> list[str]:
        failures = original_blocking(review)
        attempt = profiler.semantic_decision_trace.attempt()
        enums = []
        for failure in failures:
            text = str(failure)
            if text.startswith("SEMANTIC_REVIEW_BLOCKED:"):
                enums.append("SEMANTIC_REVIEW_BLOCKED")
            else:
                enums.append(text)
            profiler.semantic_decision_trace.add_failure_reason(text)
        attempt["semantic_review_blocking_reason_enum"] = list(dict.fromkeys(enums))
        return failures

    def legacy_verify_wrapper(*args: Any, **kwargs: Any) -> Any:
        attempt = profiler.semantic_decision_trace.attempt()
        try:
            result = original_legacy_verify(*args, **kwargs)
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__))
            attempt["bounded_publication_validation_result"] = "failed"
            attempt["legacy_verifier_exception_reason_code"] = code
            profiler.semantic_decision_trace.add_failure_reason(code)
            raise
        attempt["bounded_publication_validation_result"] = "ok"
        return result

    runtime._parse_compact_provider_result = parse_closure_wrapper
    runtime._runtime_bound_candidate = runtime_bound_wrapper
    runtime._canonical_semantic_review_result = canonical_review_wrapper
    runtime._parse_semantic_review_result = parse_review_wrapper
    runtime._canonicalize_semantic_review_evidence_refs = canonicalize_refs_wrapper
    runtime._validate_semantic_review_claim_set = validate_claim_set_wrapper
    runtime._semantic_review_has_out_of_local_evidence = out_of_local_wrapper
    runtime._semantic_review_blocking_failures = blocking_wrapper
    legacy._verify_multi_evidence_provider_output = legacy_verify_wrapper

    def restore() -> None:
        runtime.load_production_answer_bundle = original_bundle
        runtime.retrieve_wiki_first = original_lexical
        legacy._select_evidence = original_select
        runtime._semantic_requirements = original_requirements
        runtime._strengthen_evidence = original_strengthen
        runtime._synthesize_and_verify = original_synthesize
        runtime._response_from_verification = original_response
        runtime._parse_compact_provider_result = original_parse_closure
        runtime._runtime_bound_candidate = original_runtime_bound
        runtime._parse_semantic_review_result = original_parse_review
        runtime._canonical_semantic_review_result = original_canonical_review
        runtime._canonicalize_semantic_review_evidence_refs = original_canonicalize_refs
        runtime._validate_semantic_review_claim_set = original_validate_claim_set
        runtime._semantic_review_has_out_of_local_evidence = original_out_of_local
        runtime._semantic_review_blocking_failures = original_blocking
        legacy._verify_multi_evidence_provider_output = original_legacy_verify

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
    variant: str = VARIANT_PHASE1_REVIEWER,
) -> dict[str, Any]:
    profiler = Phase1Profiler()
    restore = _install_stage_wrappers(profiler)
    restore_variant = _install_variant(variant)
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
            "variant": variant,
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
            "semantic_decision_trace": _finalized_semantic_trace(
                profiler.semantic_decision_trace
            ),
            "diagnostic_failure": True,
            "diagnostic_failure_receipt": receipt,
        }
    finally:
        restore_variant()
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
        "variant": variant,
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
        "semantic_decision_trace": _finalized_semantic_trace(
            profiler.semantic_decision_trace
        ),
    }


def _row_failure(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("diagnostic_failure"):
        receipt = row.get("diagnostic_failure_receipt", {})
        return {
            "case_id": str(row.get("case_id", "")),
            "variant": str(row.get("variant", "")),
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
                "variant": str(row.get("variant", "")),
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
                "variant": str(row.get("variant", "")),
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
            "variant": str(row.get("variant", "")),
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


def _differential_classification(rows: Sequence[Mapping[str, Any]]) -> str:
    by_variant = {str(row.get("variant", "")): row for row in rows}
    variant_a = by_variant.get(VARIANT_LEGACY_REVIEWER, {})
    variant_b = by_variant.get(VARIANT_PHASE1_REVIEWER, {})
    a_answers = variant_a.get("status") == "owner_only_cited_answer"
    b_answers = variant_b.get("status") == "owner_only_cited_answer"
    a_abstains = bool(variant_a.get("safe_abstention", False)) and not a_answers
    b_abstains = bool(variant_b.get("safe_abstention", False)) and not b_answers
    if a_answers and b_abstains:
        return "PHASE1_REVIEWER_COMPACTION_REGRESSION_CONFIRMED"
    if a_abstains and b_abstains:
        return "PHASE1_CLOSURE_ANCHOR_INTERACTION_REGRESSION"
    if a_answers and b_answers:
        return "NONDETERMINISTIC_PROVIDER_PARITY_REQUIRES_ONE_CONFIRMATION"
    return "PHASE1_DIFFERENTIAL_INCONCLUSIVE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--error-output", type=Path)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument(
        "--reviewer-variant",
        action="append",
        choices=[VARIANT_LEGACY_REVIEWER, VARIANT_PHASE1_REVIEWER],
        default=[],
    )
    parser.add_argument("--no-safety", action="store_true")
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
        cases = _selected_cases(
            _load_cases(args.questions),
            args.limit,
            case_ids=args.case_id,
            include_safety=not args.no_safety,
        )
        variants = args.reviewer_variant or [VARIANT_PHASE1_REVIEWER]
        stop_on_first_failure = len(variants) == 1
        for variant in variants:
            for case in cases:
                row = _run_case(
                    root=root,
                    gate_path=gate_path,
                    case=case,
                    owner_subject_hash=owner_hash,
                    provider_client=provider,
                    dense_channel=dense_channel,
                    require_remote_dense=False,
                    variant=variant,
                )
                rows.append(row)
                receipt = row.get("diagnostic_failure_receipt")
                if isinstance(receipt, Mapping):
                    error_receipts.append(dict(receipt))
                failure = _row_failure(row)
                if failure is not None:
                    failures.append(failure)
                    if stop_on_first_failure:
                        break
            if failures and stop_on_first_failure:
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
    variants = list(dict.fromkeys(str(row.get("variant", "")) for row in rows))
    artifact["variant_count"] = len(variants)
    artifact["variants"] = variants
    artifact["differential_classification"] = (
        _differential_classification(rows) if len(variants) > 1 else ""
    )
    _atomic_write_json(args.output, artifact)
    _write_error_output(args.error_output, error_receipts)
    print(json.dumps({"output": str(args.output), "case_count": len(rows)}))
    return 0 if len(variants) > 1 or not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
