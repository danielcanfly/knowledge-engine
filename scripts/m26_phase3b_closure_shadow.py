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

FROZEN_SEMANTIC_SHA = "705fd13fc23c73043587c0d322826c085c119284"
PHASE2_BASE_SHA = "f46698e37f363d7fb6f6322140ca739480522df4"
FROZEN_CLOSURE_MODEL = "MiniMax-M3"
FROZEN_REVIEWER_MODEL = "MiniMax-M3"
CANDIDATE_CLOSURE_MODEL = "MiniMax-M2.5-highspeed"
CLOSURE_CALLS = {"aq_semantic_closure", "aq_semantic_closure_repair"}
SENTINEL_CASE_IDS = ("R3-Q03", "R3-Q04", "R3-Q05", "R3-Q07")


class RoutedProviderClient:
    """Shadow-only client: closure model varies; reviewer is always frozen M3."""

    def __init__(self, api_key: str, *, closure_model: str, max_calls: int = 4) -> None:
        if not api_key:
            raise LiveGateError("MINIMAX_API_KEY missing")
        self.api_key = api_key
        self.closure_model = closure_model
        self.max_calls = max_calls
        self.calls = 0
        self.cost = Decimal("0")
        self.telemetry: list[dict[str, Any]] = []

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]:
        if call_class in CLOSURE_CALLS:
            target_model = self.closure_model
        elif call_class == semantic.SEMANTIC_REVIEW_CALL_CLASS:
            target_model = FROZEN_REVIEWER_MODEL
        else:
            raise RuntimeError(f"unexpected Phase 3B provider call class: {call_class}")

        routed_payload = dict(payload)
        if routed_payload.get("model") != FROZEN_CLOSURE_MODEL:
            raise RuntimeError("frozen provider payload model drift")
        routed_payload["model"] = target_model
        last_error: Exception | None = None

        for network_attempt in range(4):
            if self.calls >= self.max_calls:
                raise LiveGateError("provider-call budget exhausted")
            self.calls += 1
            started = time.monotonic()
            try:
                response = prepare_minimax_http_client().post(
                    ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=routed_payload,
                    timeout=120.0,
                )
                retryable = response.status_code == 429 or response.status_code >= 500
                if retryable and network_attempt < 3:
                    time.sleep(RETRY_DELAYS[network_attempt])
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"Phase 3B provider HTTP {response.status_code}")
                body = response.json()
                returned_model = str(body.get("model", ""))
                if returned_model != target_model:
                    raise RuntimeError(
                        f"Phase 3B model identity drift expected={target_model} returned={returned_model}"
                    )
                usage = _usage(body)
                text = _extract_text(body)
                latency_ms = int((time.monotonic() - started) * 1000)
                result = {
                    "text": text,
                    "usage": usage,
                    "cost_usd": "0",
                    "latency_ms": latency_ms,
                    "response_id": str(body.get("id", "")),
                    "call_class": call_class,
                    "network_attempt": network_attempt + 1,
                    "stop_reason": str(body.get("stop_reason") or body.get("finish_reason") or ""),
                    "content_block_types": _content_block_types(body),
                    "output_char_count": len(text),
                }
                self.telemetry.append(
                    {
                        "call_class": call_class,
                        "model": target_model,
                        "returned_model": returned_model,
                        "latency_ms": latency_ms,
                        "network_attempt": network_attempt + 1,
                        "stop_reason": result["stop_reason"],
                        "output_char_count": len(text),
                    }
                )
                return result
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if network_attempt < 3:
                    time.sleep(RETRY_DELAYS[network_attempt])
                    continue
                raise RuntimeError("Phase 3B provider retry exhaustion") from exc
            except ValueError as exc:
                raise RuntimeError("Phase 3B provider returned non-JSON") from exc
        raise RuntimeError("Phase 3B provider retry exhaustion") from last_error


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


def _selected_evidence_digest(response: Mapping[str, Any]) -> str:
    ids = sorted(
        str(item.get("evidence_id", ""))
        for item in response.get("selected_evidence", [])
        if isinstance(item, Mapping) and str(item.get("evidence_id", ""))
    )
    return canonical_sha256(ids)


def _reason_codes(response: Mapping[str, Any]) -> list[str]:
    return sorted({str(item) for item in response.get("reason_codes", []) if str(item)})


def _deterministic_publication(response: Mapping[str, Any]) -> bool:
    verification = response.get("multi_evidence_verification", {})
    closure = response.get("semantic_closure", {})
    answer_source = str(response.get("answer_source", ""))
    return bool(
        (isinstance(verification, Mapping) and verification.get("deterministic_evidence_synthesis_used"))
        or (isinstance(closure, Mapping) and closure.get("broad_deterministic_fallback_used"))
        or "deterministic" in answer_source.lower()
    )


def _run_variant(
    *,
    root: Path,
    gate: Mapping[str, Any],
    question: str,
    owner_hash: str,
    closure_model: str,
) -> dict[str, Any]:
    client = RoutedProviderClient(
        os.environ.get("MINIMAX_API_KEY", ""),
        closure_model=closure_model,
        max_calls=4,
    )
    started = time.monotonic()
    try:
        response = run_owner_arbitrary_query(
            root=root,
            gate=gate,
            question=question,
            owner_subject_hash=owner_hash,
            public_request=False,
            provider_client=client,
            require_remote_dense=True,
            max_provider_calls=4,
            max_cost=Decimal("0.25"),
        )
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "provider_calls": client.telemetry,
            "closure_model": closure_model,
        }

    reason_codes = _reason_codes(response)
    citations = response.get("citations", [])
    return {
        "error": "",
        "closure_model": closure_model,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "status": str(response.get("status", "")),
        "terminal_status": str(response.get("terminal_status", "")),
        "safe_abstention": bool(response.get("safe_abstention", False)),
        "answer_source": str(response.get("answer_source", "")),
        "selected_evidence_digest": _selected_evidence_digest(response),
        "unsupported_accepted_claims": int(response.get("unsupported_accepted_claims", 0)),
        "me065": "M26-PA7-ME-065" in reason_codes,
        "reason_codes": reason_codes,
        "repair_attempted": bool(response.get("repair_attempted", False)),
        "provider_call_count": int(response.get("provider_call_count", client.calls)),
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "deterministic_publication": _deterministic_publication(response),
        "provider_calls": client.telemetry,
    }


def _initial_closure_latency(row: Mapping[str, Any]) -> int:
    for item in row.get("provider_calls", []):
        if isinstance(item, Mapping) and item.get("call_class") == "aq_semantic_closure":
            return int(item.get("latency_ms", 0))
    return 0


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

    pairs: list[dict[str, Any]] = []
    for case_id in SENTINEL_CASE_IDS:
        question = str(question_by_id[case_id]["question"])
        a = _run_variant(
            root=root,
            gate=gate,
            question=question,
            owner_hash=owner_hash,
            closure_model=FROZEN_CLOSURE_MODEL,
        )
        b = _run_variant(
            root=root,
            gate=gate,
            question=question,
            owner_hash=owner_hash,
            closure_model=CANDIDATE_CLOSURE_MODEL,
        )
        evidence_match = bool(
            not a.get("error")
            and not b.get("error")
            and a.get("selected_evidence_digest") == b.get("selected_evidence_digest")
        )
        pairs.append(
            {
                "case_id": case_id,
                "a": a,
                "b": b,
                "matching_evidence_digest": evidence_match,
                "same_terminal_status": (
                    not a.get("error")
                    and not b.get("error")
                    and a.get("status") == b.get("status")
                    and a.get("terminal_status") == b.get("terminal_status")
                    and a.get("safe_abstention") == b.get("safe_abstention")
                ),
            }
        )

    comparable = [
        pair
        for pair in pairs
        if pair["matching_evidence_digest"] and not pair["a"].get("error") and not pair["b"].get("error")
    ]
    a_closure = [_initial_closure_latency(pair["a"]) for pair in comparable]
    b_closure = [_initial_closure_latency(pair["b"]) for pair in comparable]
    a_closure = [value for value in a_closure if value > 0]
    b_closure = [value for value in b_closure if value > 0]
    a_median = statistics.median(a_closure) if a_closure else 0.0
    b_median = statistics.median(b_closure) if b_closure else 0.0

    result = {
        "schema_version": "m26-latency-phase3b-closure-shadow-sentinels/v1",
        "frozen_semantic_base_sha": FROZEN_SEMANTIC_SHA,
        "phase2_base_sha": PHASE2_BASE_SHA,
        "a_closure_model": FROZEN_CLOSURE_MODEL,
        "b_closure_model": CANDIDATE_CLOSURE_MODEL,
        "reviewer_model_both_variants": FROZEN_REVIEWER_MODEL,
        "sentinel_case_ids": list(SENTINEL_CASE_IDS),
        "pair_count": len(pairs),
        "comparable_pair_count": len(comparable),
        "matching_evidence_digest_count": sum(bool(pair["matching_evidence_digest"]) for pair in pairs),
        "same_terminal_status_count": sum(bool(pair["same_terminal_status"]) for pair in comparable),
        "a_error_count": sum(bool(pair["a"].get("error")) for pair in pairs),
        "b_error_count": sum(bool(pair["b"].get("error")) for pair in pairs),
        "b_unsupported_accepted_claims": sum(int(pair["b"].get("unsupported_accepted_claims", 0)) for pair in pairs),
        "b_me065_count": sum(bool(pair["b"].get("me065")) for pair in pairs),
        "b_deterministic_publication_count": sum(bool(pair["b"].get("deterministic_publication")) for pair in pairs),
        "a_repair_count": sum(bool(pair["a"].get("repair_attempted")) for pair in comparable),
        "b_repair_count": sum(bool(pair["b"].get("repair_attempted")) for pair in comparable),
        "a_initial_closure_latency": {
            "mean_ms": round(statistics.mean(a_closure), 2) if a_closure else 0.0,
            "median_ms": a_median,
            "p95_ms": round(_percentile(a_closure, 0.95), 2),
        },
        "b_initial_closure_latency": {
            "mean_ms": round(statistics.mean(b_closure), 2) if b_closure else 0.0,
            "median_ms": b_median,
            "p95_ms": round(_percentile(b_closure, 0.95), 2),
        },
        "median_latency_improvement_pct": (
            round((a_median - b_median) / a_median * 100, 2) if a_median else 0.0
        ),
        "pairs": pairs,
        "authority": "A_frozen_closure_and_frozen_M3_reviewer",
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_evidence_recorded": False,
        "raw_prompts_recorded": False,
        "raw_provider_text_recorded": False,
        "protected_knowledge_mutations": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "pairs"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
