from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any


Q01_CASE_ID = "R3-Q01"
SEMANTIC_CALLS = {
    "aq_semantic_closure",
    "aq_semantic_closure_repair",
    "aq_claim_semantic_entailment",
}


class ObservedProvider:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = dict(self.inner.call(payload, call_class))
        except Exception as exc:
            self.calls.append(
                {
                    "call_class": call_class,
                    "elapsed_ms": _elapsed_ms(started),
                    "exception_class": type(exc).__name__,
                    "payload_bytes": _payload_bytes(payload),
                }
            )
            raise
        usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
        elapsed_ms = _elapsed_ms(started)
        provider_latency_ms = int(result.get("latency_ms", elapsed_ms))
        self.calls.append(
            {
                "call_class": call_class,
                "elapsed_ms": elapsed_ms,
                "provider_latency_ms": provider_latency_ms,
                "transport_overhead_ms": elapsed_ms - provider_latency_ms,
                "network_attempt": int(result.get("network_attempt", 1) or 1),
                "payload_bytes": _payload_bytes(payload),
                "input_tokens": _usage_int(usage, "input_tokens", "prompt_tokens"),
                "output_tokens": _usage_int(usage, "output_tokens", "completion_tokens"),
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
            }
        )
        return result


class ObservedDenseChannel:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def search(self, *args: Any, **kwargs: Any) -> Any:
        return self.inner.search(*args, **kwargs)


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


def _digest_json(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _load_q01(root: Path) -> dict[str, Any]:
    payload = json.loads(
        (root / "pilot/m26/m26-aq-final-r3-questions.json").read_text()
    )
    rows = payload.get("questions", payload)
    for row in rows:
        if str(row.get("case_id")) == Q01_CASE_ID:
            return dict(row)
    raise SystemExit("R3-Q01 not found")


def _review_summary(review: Mapping[str, Any]) -> dict[str, Any]:
    verdicts = Counter()
    judgments = review.get("claim_judgments", [])
    if isinstance(judgments, Sequence) and not isinstance(judgments, (str, bytes)):
        for judgment in judgments:
            if isinstance(judgment, Mapping):
                verdicts[str(judgment.get("verdict", ""))] += 1
    coverage = review.get("visible_coverage")
    return {
        "verdict_histogram": dict(sorted(verdicts.items())),
        "visible_coverage_verdict": (
            str(coverage.get("verdict", "")) if isinstance(coverage, Mapping) else ""
        ),
        "judgment_count": sum(verdicts.values()),
    }


def _provider_call_groups(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closures = [
        dict(call)
        for call in calls
        if call.get("call_class")
        in {"aq_semantic_closure", "aq_semantic_closure_repair"}
    ]
    reviewers = [
        dict(call)
        for call in calls
        if call.get("call_class") == "aq_claim_semantic_entailment"
    ]
    return {
        "closure_calls": closures,
        "reviewer_calls": reviewers,
        "closure_output_tokens": int(closures[0].get("output_tokens", 0))
        if closures
        else 0,
        "closure_latency_ms": int(closures[0].get("elapsed_ms", 0))
        if closures
        else 0,
        "reviewer_output_tokens": int(reviewers[0].get("output_tokens", 0))
        if reviewers
        else 0,
        "reviewer_latency_ms": int(reviewers[0].get("elapsed_ms", 0))
        if reviewers
        else 0,
    }


def _reason_codes(response: Mapping[str, Any], closure: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    verification = response.get("multi_evidence_verification", {})
    if isinstance(verification, Mapping):
        for key in ("repair_trigger", "verification_failure_codes_by_attempt"):
            values = verification.get(key, [])
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                codes.extend(str(item) for item in values if str(item))
    values = closure.get("failures", [])
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        codes.extend(str(item) for item in values if str(item))
    return list(dict.fromkeys(codes))


def _run_child(args: argparse.Namespace) -> int:
    root = Path(args.variant_root).resolve()
    sys.path.insert(0, str(root / "src"))

    from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
    from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
    from knowledge_engine.m26_ask_api import DEFAULT_GATE_PATH, run_owner_query_for_web
    from knowledge_engine.m26_pa5_v8_live import MiniMaxClient

    review_summaries: list[dict[str, Any]] = []
    original_review = runtime._call_semantic_entailment_review

    def review_with_summary(*review_args: Any, **review_kwargs: Any) -> Any:
        review, raw = original_review(*review_args, **review_kwargs)
        review_summaries.append(_review_summary(review))
        return review, raw

    runtime._call_semantic_entailment_review = review_with_summary
    observed_provider = ObservedProvider(
        MiniMaxClient(
            os.environ.get("MINIMAX_API_KEY", ""),
            max_calls=16,
            max_cost=Decimal("1.00"),
        )
    )
    dense_channel = legacy.dense_channel_from_env(
        require_remote=os.environ.get("M26_QUERY_REQUIRE_REMOTE_DENSE", "").lower()
        == "true"
    )
    case = _load_q01(root)
    started = time.monotonic()
    try:
        response = run_owner_query_for_web(
            root=root,
            gate_path=root / DEFAULT_GATE_PATH,
            request_payload={"question": str(case.get("question", ""))},
            owner_subject_hash=os.environ["KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH"],
            provider_client=observed_provider,
            dense_channel=ObservedDenseChannel(dense_channel),
            require_remote_dense=False,
            max_cost=Decimal("0.50"),
        )
        closure = (
            response.get("semantic_closure", {})
            if isinstance(response.get("semantic_closure"), Mapping)
            else {}
        )
        selected_ids = sorted(
            str(item.get("evidence_id", ""))
            for item in response.get("selected_evidence", [])
            if isinstance(item, Mapping) and str(item.get("evidence_id", ""))
        )
        codes = _reason_codes(response, closure)
        grouped_calls = _provider_call_groups(observed_provider.calls)
        row = {
            "variant": str(args.variant),
            "iteration": int(args.iteration),
            "case_id": Q01_CASE_ID,
            "status": str(response.get("status", "")),
            "terminal_status": str(response.get("terminal_status", "")),
            "safe_abstention": bool(response.get("safe_abstention", True)),
            "provider_call_count": len(
                [
                    call
                    for call in observed_provider.calls
                    if call.get("call_class") in SEMANTIC_CALLS
                ]
            ),
            "repair_attempted": bool(
                response.get("multi_evidence_verification", {}).get(
                    "bounded_repair_attempted",
                    response.get("repair_attempted", False),
                )
                if isinstance(response.get("multi_evidence_verification"), Mapping)
                else False
            ),
            "claim_count": len(response.get("answer_claims", [])),
            "citation_count": len(response.get("citations", [])),
            "unsupported_accepted_claims": int(
                response.get("integrity", {}).get("unsupported_accepted_claims", 0)
                if isinstance(response.get("integrity"), Mapping)
                else response.get("unsupported_accepted_claims", 0)
            ),
            "selected_evidence_count": len(selected_ids),
            "selected_evidence_id_digest": _digest_json(selected_ids),
            "total_latency_ms": _elapsed_ms(started),
            "first_review_verdict_histogram": (
                review_summaries[0]["verdict_histogram"] if review_summaries else {}
            ),
            "visible_coverage_verdict": (
                review_summaries[0]["visible_coverage_verdict"]
                if review_summaries
                else ""
            ),
            "me065": "M26-PA7-ME-065" in codes,
            "repair_trigger_enum": [
                code
                for code in codes
                if code.startswith("SEMANTIC_REVIEW")
                or code.startswith("M26-PA7-ME-")
                or code.startswith("COMPACT_PROVIDER")
            ],
            "final_reviewer_verdict_histogram": (
                review_summaries[-1]["verdict_histogram"]
                if len(review_summaries) > 1
                else {}
            ),
            "review_summaries": review_summaries,
            "raw_questions_recorded": False,
            "raw_answers_recorded": False,
            "raw_evidence_recorded": False,
            "raw_prompts_recorded": False,
            "raw_provider_text_recorded": False,
            **grouped_calls,
        }
    except Exception as exc:
        row = {
            "variant": str(args.variant),
            "iteration": int(args.iteration),
            "case_id": Q01_CASE_ID,
            "status": "diagnostic_exception",
            "terminal_status": "diagnostic_exception",
            "exception_class": type(exc).__name__,
            "sanitized_traceback": [
                {
                    "file": Path(frame.filename).name,
                    "line": int(frame.lineno),
                    "function": str(frame.name),
                }
                for frame in traceback.extract_tb(exc.__traceback__)[-8:]
            ],
            "safe_abstention": True,
            "provider_call_count": len(observed_provider.calls),
            "repair_attempted": any(
                call.get("call_class") == "aq_semantic_closure_repair"
                for call in observed_provider.calls
            ),
            "claim_count": 0,
            "citation_count": 0,
            "unsupported_accepted_claims": 0,
            "selected_evidence_count": 0,
            "selected_evidence_id_digest": _digest_json([]),
            "total_latency_ms": _elapsed_ms(started),
            "first_review_verdict_histogram": {},
            "visible_coverage_verdict": "",
            "me065": False,
            "repair_trigger_enum": [type(exc).__name__],
            "final_reviewer_verdict_histogram": {},
            "review_summaries": review_summaries,
            "raw_questions_recorded": False,
            "raw_answers_recorded": False,
            "raw_evidence_recorded": False,
            "raw_prompts_recorded": False,
            "raw_provider_text_recorded": False,
            **_provider_call_groups(observed_provider.calls),
        }
    print(json.dumps(row, sort_keys=True))
    return 0


def _run_controller(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    order = [
        ("A", 1),
        ("B", 1),
        ("A", 2),
        ("B", 2),
        ("A", 3),
        ("B", 3),
        ("A", 4),
        ("B", 4),
        ("A", 5),
        ("B", 5),
    ]
    roots = {
        "A": str(Path(args.variant_a_root).resolve()),
        "B": str(Path(args.variant_b_root).resolve()),
    }
    for variant, iteration in order:
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                "--variant",
                variant,
                "--iteration",
                str(iteration),
                "--variant-root",
                roots[variant],
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        if child.stdout.strip():
            rows.append(json.loads(child.stdout.strip().splitlines()[-1]))
        else:
            rows.append(
                {
                    "variant": variant,
                    "iteration": iteration,
                    "case_id": Q01_CASE_ID,
                    "status": "diagnostic_child_no_output",
                    "terminal_status": "diagnostic_child_no_output",
                    "child_returncode": child.returncode,
                    "stderr_digest": _digest_json(child.stderr[-2000:]),
                    "provider_call_count": 0,
                    "repair_attempted": False,
                    "claim_count": 0,
                    "citation_count": 0,
                    "unsupported_accepted_claims": 0,
                    "selected_evidence_count": 0,
                    "selected_evidence_id_digest": _digest_json([]),
                    "me065": False,
                    "repair_trigger_enum": ["diagnostic_child_no_output"],
                    "raw_questions_recorded": False,
                    "raw_answers_recorded": False,
                    "raw_evidence_recorded": False,
                    "raw_prompts_recorded": False,
                    "raw_provider_text_recorded": False,
                }
            )
    artifact = _artifact(rows)
    _atomic_write_json(Path(args.output), artifact)
    _atomic_write_json(
        Path(args.error_output),
        {
            "schema_version": "m26-q01-paired-stability-errors/v1",
            "error_count": len(
                [row for row in rows if str(row.get("status", "")).startswith("diagnostic_")]
            ),
            "raw_questions_recorded": False,
            "raw_answers_recorded": False,
            "raw_evidence_recorded": False,
            "raw_prompts_recorded": False,
            "raw_provider_text_recorded": False,
        },
    )
    print(json.dumps({"output": str(args.output), "case_count": len(rows)}))
    return 0


def _artifact(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[Mapping[str, Any]]] = {"A": [], "B": []}
    for row in rows:
        by_variant.setdefault(str(row.get("variant", "")), []).append(row)
    variant_summary = {}
    for variant, variant_rows in by_variant.items():
        successes = [
            row
            for row in variant_rows
            if row.get("status") == "owner_only_cited_answer"
            and int(row.get("unsupported_accepted_claims", 0)) == 0
            and row.get("me065") is False
        ]
        digests = Counter(
            str(row.get("selected_evidence_id_digest", "")) for row in variant_rows
        )
        variant_summary[variant] = {
            "run_count": len(variant_rows),
            "success_count": len(successes),
            "safe_abstention_count": len(
                [
                    row
                    for row in variant_rows
                    if row.get("status") == "owner_only_safe_abstention"
                ]
            ),
            "diagnostic_exception_count": len(
                [
                    row
                    for row in variant_rows
                    if str(row.get("status", "")).startswith("diagnostic_")
                ]
            ),
            "me065_count": len([row for row in variant_rows if row.get("me065")]),
            "unsupported_accepted_claims_total": sum(
                int(row.get("unsupported_accepted_claims", 0))
                for row in variant_rows
            ),
            "selected_evidence_digest_counts": dict(sorted(digests.items())),
        }
    return {
        "schema_version": "m26-q01-paired-stability/v1",
        "case_id": Q01_CASE_ID,
        "case_count": len(rows),
        "execution_order": [
            f"{row.get('variant')}{row.get('iteration')}" for row in rows
        ],
        "variant_summary": variant_summary,
        "rows": [dict(row) for row in rows],
        "protected_knowledge_mutations": 0,
        "sequential_concurrency": 1,
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_evidence_recorded": False,
        "raw_prompts_recorded": False,
        "raw_provider_text_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant-a-root", type=Path)
    parser.add_argument("--variant-b-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--error-output", type=Path)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--variant", default="")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--variant-root", type=Path)
    args = parser.parse_args()
    if args.child:
        return _run_child(args)
    if args.variant_a_root is None or args.variant_b_root is None:
        raise SystemExit("variant roots are required")
    if args.output is None or args.error_output is None:
        raise SystemExit("output paths are required")
    return _run_controller(args)


if __name__ == "__main__":
    raise SystemExit(main())
