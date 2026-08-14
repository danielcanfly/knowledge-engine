from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from knowledge_engine import m26_pa7_semantic_closure_runtime as semantic
from knowledge_engine.m26_aq_semantic_contract import run_owner_arbitrary_query
from knowledge_engine.m26_pa5_v8_live import (
    ENDPOINT,
    RETRY_DELAYS,
    LiveGateError,
    _content_block_types,
    _extract_text,
    _usage,
    prepare_minimax_http_client,
)
from knowledge_engine.m26_production_promotion_closure import load_json
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

FROZEN_REVIEWER_MODEL = "MiniMax-M3"
CANDIDATE_REVIEWER_MODEL = "MiniMax-M2.7-highspeed"
CASE_IDS = (
    "R3-Q01",
    "R3-Q02",
    "R3-Q03",
    "R3-Q04",
    "R3-Q05",
    "R3-Q06",
    "R3-Q07",
    "R3-Q08",
    "R3-Q09",
    "R3-Q12",
)


class ShadowReviewerClient:
    """Reviewer-only client that changes only the model field of the frozen payload."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise LiveGateError("MINIMAX_API_KEY missing")
        self.api_key = api_key
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]:
        if call_class != semantic.SEMANTIC_REVIEW_CALL_CLASS:
            raise RuntimeError("shadow client may only execute semantic reviewer calls")
        candidate_payload = dict(payload)
        if candidate_payload.get("model") != FROZEN_REVIEWER_MODEL:
            raise RuntimeError("frozen reviewer payload model drift")
        candidate_payload["model"] = CANDIDATE_REVIEWER_MODEL
        last_error: Exception | None = None
        for network_attempt in range(4):
            self.calls += 1
            started = time.monotonic()
            try:
                response = prepare_minimax_http_client().post(
                    ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=candidate_payload,
                    timeout=120.0,
                )
                retryable = response.status_code == 429 or response.status_code >= 500
                if retryable and network_attempt < 3:
                    time.sleep(RETRY_DELAYS[network_attempt])
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"candidate reviewer HTTP {response.status_code}")
                body = response.json()
                returned_model = str(body.get("model", ""))
                if not returned_model:
                    raise RuntimeError("candidate reviewer model identity missing")
                usage = _usage(body)
                text = _extract_text(body)
                return {
                    "text": text,
                    "usage": usage,
                    "cost_usd": "0",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "response_id": str(body.get("id", "")),
                    "call_class": call_class,
                    "network_attempt": network_attempt + 1,
                    "stop_reason": str(body.get("stop_reason") or body.get("finish_reason") or ""),
                    "content_block_types": _content_block_types(body),
                    "output_char_count": len(text),
                    "returned_model": returned_model,
                }
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if network_attempt < 3:
                    time.sleep(RETRY_DELAYS[network_attempt])
                    continue
                raise RuntimeError("candidate reviewer retry exhaustion") from exc
            except ValueError as exc:
                raise RuntimeError("candidate reviewer returned non-JSON") from exc
        raise RuntimeError("candidate reviewer retry exhaustion") from last_error


def _percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _review_summary(review: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    claim_by_id = semantic._candidate_claim_by_id(candidate)
    canonical = semantic._canonicalize_semantic_review_evidence_refs(review, claim_by_id)
    judgments = []
    for raw in canonical.get("claim_judgments", []):
        if not isinstance(raw, Mapping):
            continue
        judgments.append(
            {
                "claim_id": str(raw.get("claim_id", "")),
                "verdict": str(raw.get("verdict", "")),
                "evidence_ids": sorted(str(item) for item in raw.get("evidence_ids", [])),
            }
        )
    coverage = canonical.get("visible_coverage", {})
    coverage_verdict = str(coverage.get("verdict", "")) if isinstance(coverage, Mapping) else ""
    blocking = semantic._semantic_review_blocking_failures(canonical)
    out_of_local = semantic._semantic_review_has_out_of_local_evidence(canonical, claim_by_id)
    return {
        "review_digest": canonical_sha256(canonical),
        "judgments": judgments,
        "coverage_verdict": coverage_verdict,
        "blocking_failures": blocking,
        "out_of_local_evidence": out_of_local,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    question_doc = json.loads((root / "pilot/m26/m26-aq-final-r3-questions.json").read_text())
    question_by_id = {str(item["case_id"]): item for item in question_doc["questions"]}
    owner_hash = os.environ.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "").strip().lower()
    if not owner_hash:
        raise SystemExit("owner subject hash missing")
    gate = load_json(root / "pilot/m26/m26-pa-7-resolved-production-gate.json")
    shadow_client = ShadowReviewerClient(os.environ.get("MINIMAX_API_KEY", ""))

    original_review = semantic._call_semantic_entailment_review
    current_case = {"case_id": ""}
    shadow_rows: list[dict[str, Any]] = []

    def shadow_review(
        *,
        provider_client: Any,
        question: str,
        intent_class: str,
        candidate: Mapping[str, Any],
        evidence: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        a_review, a_raw = original_review(
            provider_client=provider_client,
            question=question,
            intent_class=intent_class,
            candidate=candidate,
            evidence=evidence,
        )
        a_summary = _review_summary(a_review, candidate)
        row: dict[str, Any] = {
            "case_id": current_case["case_id"],
            "invocation_index": 1 + sum(
                item["case_id"] == current_case["case_id"] for item in shadow_rows
            ),
            "a_model": FROZEN_REVIEWER_MODEL,
            "b_model": CANDIDATE_REVIEWER_MODEL,
            "a_latency_ms": int(a_raw.get("latency_ms", 0)),
            "a": a_summary,
            "b_error": "",
        }
        try:
            b_review, b_raw = original_review(
                provider_client=shadow_client,
                question=question,
                intent_class=intent_class,
                candidate=candidate,
                evidence=evidence,
            )
            b_summary = _review_summary(b_review, candidate)
            row.update(
                {
                    "b_latency_ms": int(b_raw.get("latency_ms", 0)),
                    "b_network_attempt": int(b_raw.get("network_attempt", 0)),
                    "b_returned_model": str(b_raw.get("returned_model", "")),
                    "b": b_summary,
                    "exact_review_match": a_summary["review_digest"] == b_summary["review_digest"],
                    "same_blocking_outcome": (
                        a_summary["blocking_failures"] == b_summary["blocking_failures"]
                        and a_summary["out_of_local_evidence"] == b_summary["out_of_local_evidence"]
                    ),
                    "same_coverage_verdict": (
                        a_summary["coverage_verdict"] == b_summary["coverage_verdict"]
                    ),
                }
            )
        except Exception as exc:
            row.update(
                {
                    "b_latency_ms": 0,
                    "b_network_attempt": 0,
                    "b_returned_model": "",
                    "b": {},
                    "exact_review_match": False,
                    "same_blocking_outcome": False,
                    "same_coverage_verdict": False,
                    "b_error": type(exc).__name__,
                }
            )
        shadow_rows.append(row)
        return a_review, a_raw

    semantic._call_semantic_entailment_review = shadow_review
    case_rows: list[dict[str, Any]] = []
    try:
        for case_id in CASE_IDS:
            current_case["case_id"] = case_id
            case = question_by_id[case_id]
            response = run_owner_arbitrary_query(
                root=root,
                gate=gate,
                question=str(case["question"]),
                owner_subject_hash=owner_hash,
                public_request=False,
                require_remote_dense=True,
                max_provider_calls=4,
                max_cost=Decimal("0.10"),
            )
            selected_ids = sorted(
                str(item.get("evidence_id", ""))
                for item in response.get("selected_evidence", [])
                if isinstance(item, Mapping) and str(item.get("evidence_id", ""))
            )
            case_rows.append(
                {
                    "case_id": case_id,
                    "status": str(response.get("status", "")),
                    "terminal_status": str(response.get("terminal_status", "")),
                    "safe_abstention": bool(response.get("safe_abstention", False)),
                    "unsupported_accepted_claims": int(response.get("unsupported_accepted_claims", 0)),
                    "me065": "M26-PA7-ME-065" in set(str(x) for x in response.get("reason_codes", [])),
                    "repair_attempted": bool(response.get("repair_attempted", False)),
                    "provider_call_count": int(response.get("provider_call_count", 0)),
                    "selected_evidence_digest": canonical_sha256(selected_ids),
                }
            )
    finally:
        semantic._call_semantic_entailment_review = original_review

    successful_shadow = [row for row in shadow_rows if not row["b_error"]]
    a_latencies = [int(row["a_latency_ms"]) for row in successful_shadow]
    b_latencies = [int(row["b_latency_ms"]) for row in successful_shadow]
    a_median = statistics.median(a_latencies) if a_latencies else 0.0
    b_median = statistics.median(b_latencies) if b_latencies else 0.0
    result = {
        "schema_version": "m26-latency-phase3a-reviewer-shadow/v1",
        "frozen_semantic_base_sha": "705fd13fc23c73043587c0d322826c085c119284",
        "phase2_base_sha": "f46698e37f363d7fb6f6322140ca739480522df4",
        "a_model": FROZEN_REVIEWER_MODEL,
        "b_model": CANDIDATE_REVIEWER_MODEL,
        "case_count": len(case_rows),
        "review_invocation_count": len(shadow_rows),
        "successful_b_invocation_count": len(successful_shadow),
        "exact_review_match_count": sum(bool(row["exact_review_match"]) for row in successful_shadow),
        "same_blocking_outcome_count": sum(bool(row["same_blocking_outcome"]) for row in successful_shadow),
        "same_coverage_verdict_count": sum(bool(row["same_coverage_verdict"]) for row in successful_shadow),
        "b_out_of_local_evidence_count": sum(
            bool(row.get("b", {}).get("out_of_local_evidence")) for row in successful_shadow
        ),
        "b_error_count": sum(bool(row["b_error"]) for row in shadow_rows),
        "unsupported_accepted_claims": sum(row["unsupported_accepted_claims"] for row in case_rows),
        "me065_count": sum(bool(row["me065"]) for row in case_rows),
        "a_reviewer_latency": {
            "mean_ms": round(statistics.mean(a_latencies), 2) if a_latencies else 0.0,
            "median_ms": a_median,
            "p95_ms": round(_percentile(a_latencies, 0.95), 2),
        },
        "b_reviewer_latency": {
            "mean_ms": round(statistics.mean(b_latencies), 2) if b_latencies else 0.0,
            "median_ms": b_median,
            "p95_ms": round(_percentile(b_latencies, 0.95), 2),
        },
        "median_latency_improvement_pct": (
            round((a_median - b_median) / a_median * 100, 2) if a_median else 0.0
        ),
        "rows": shadow_rows,
        "cases": case_rows,
        "authority": "A_frozen_reviewer_only",
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_evidence_recorded": False,
        "raw_prompts_recorded": False,
        "raw_provider_text_recorded": False,
        "protected_knowledge_mutations": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "cases"}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
