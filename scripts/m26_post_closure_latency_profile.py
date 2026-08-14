from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from knowledge_engine.m26_ask_api import DEFAULT_GATE_PATH, run_owner_query_for_web
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

SCHEMA_VERSION = "m26-post-closure-latency-profile/v1"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _percentile(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1))))
    return int(ordered[index])


def _median(values: Sequence[int]) -> int:
    if not values:
        return 0
    return int(statistics.median(values))


def _mean(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    return round(float(statistics.mean(values)), 2)


def _stage_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    samples: dict[str, list[int]] = defaultdict(list)
    total_values = [int(row.get("total_latency_ms", 0)) for row in rows]
    total_mean = _mean(total_values)
    for row in rows:
        observability = row.get("runtime_observability", {})
        if not isinstance(observability, Mapping):
            continue
        for stage in observability.get("stage_timings", []):
            if not isinstance(stage, Mapping):
                continue
            name = str(stage.get("stage", ""))
            if name:
                samples[name].append(int(stage.get("elapsed_ms", 0)))
    result = []
    for name, values in sorted(samples.items()):
        mean_ms = _mean(values)
        result.append(
            {
                "stage": name,
                "mean_ms": mean_ms,
                "median_ms": _median(values),
                "p95_ms": _percentile(values, 95),
                "pct_total": round((mean_ms / total_mean * 100), 2)
                if total_mean
                else 0.0,
            }
        )
    return sorted(result, key=lambda item: item["mean_ms"], reverse=True)


def _provider_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    samples: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    total_values = [int(row.get("total_latency_ms", 0)) for row in rows]
    total_mean = _mean(total_values)
    for row in rows:
        observability = row.get("runtime_observability", {})
        if not isinstance(observability, Mapping):
            continue
        for call in observability.get("provider_call_timings", []):
            if not isinstance(call, Mapping):
                continue
            name = str(call.get("call_class", ""))
            if not name:
                continue
            samples[name]["elapsed_ms"].append(int(call.get("elapsed_ms", 0)))
            samples[name]["provider_latency_ms"].append(
                int(call.get("provider_latency_ms", 0))
            )
            samples[name]["output_tokens"].append(int(call.get("output_tokens", 0)))
            samples[name]["input_tokens"].append(int(call.get("input_tokens", 0)))
            samples[name]["cache_creation_input_tokens"].append(
                int(call.get("cache_creation_input_tokens", 0))
            )
            samples[name]["cache_read_input_tokens"].append(
                int(call.get("cache_read_input_tokens", 0))
            )
            samples[name]["payload_bytes"].append(int(call.get("payload_bytes", 0)))
            samples[name]["network_attempt"].append(int(call.get("network_attempt", 0)))
    result = []
    for name, values in sorted(samples.items()):
        elapsed = values["elapsed_ms"]
        provider_latency = values["provider_latency_ms"]
        mean_elapsed = _mean(elapsed)
        result.append(
            {
                "stage": name,
                "mean_ms": mean_elapsed,
                "median_ms": _median(elapsed),
                "p95_ms": _percentile(elapsed, 95),
                "pct_total": round((mean_elapsed / total_mean * 100), 2)
                if total_mean
                else 0.0,
                "provider_latency_mean_ms": _mean(provider_latency),
                "transport_overhead_mean_ms": round(
                    mean_elapsed - _mean(provider_latency), 2
                ),
                "output_tokens_mean": _mean(values["output_tokens"]),
                "input_tokens_mean": _mean(values["input_tokens"]),
                "cache_creation_input_tokens_mean": _mean(
                    values["cache_creation_input_tokens"]
                ),
                "cache_read_input_tokens_mean": _mean(
                    values["cache_read_input_tokens"]
                ),
                "payload_bytes_mean": _mean(values["payload_bytes"]),
                "network_attempt_max": max(values["network_attempt"] or [0]),
                "call_count": len(elapsed),
            }
        )
    return sorted(result, key=lambda item: item["mean_ms"], reverse=True)


def _safe_row(
    *,
    case: Mapping[str, Any],
    response: Mapping[str, Any],
    wall_ms: int,
) -> dict[str, Any]:
    observability = response.get("runtime_observability", {})
    mve = response.get("multi_evidence_verification", {})
    mve = mve if isinstance(mve, Mapping) else {}
    return {
        "case_id": str(case.get("case_id", "")),
        "class": str(case.get("class", "")),
        "expected": str(case.get("expected", "")),
        "question_sha256": canonical_sha256(str(case.get("question", ""))),
        "status": str(response.get("status", "")),
        "terminal_status": str(response.get("terminal_status", "")),
        "safe_abstention": bool(response.get("safe_abstention", True)),
        "total_latency_ms": int(response.get("accounting", {}).get("latency_ms", 0))
        if isinstance(response.get("accounting"), Mapping)
        else int(response.get("latency_ms", 0)),
        "wall_latency_ms": wall_ms,
        "provider_call_count": int(
            response.get("accounting", {}).get("provider_call_count", 0)
        )
        if isinstance(response.get("accounting"), Mapping)
        else int(response.get("provider_call_count", 0)),
        "repair_attempted": bool(response.get("repair_attempted", False))
        or bool(mve.get("bounded_repair_attempted", False)),
        "selected_evidence_count": int(
            response.get("retrieval", {}).get("selected_evidence_count", 0)
        )
        if isinstance(response.get("retrieval"), Mapping)
        else int(response.get("selected_evidence_count", 0)),
        "claim_count": len(response.get("answer_claims", []))
        if isinstance(response.get("answer_claims"), list)
        else 0,
        "support_ref_count": sum(
            len(claim.get("support_refs", []))
            for claim in response.get("answer_claims", [])
            if isinstance(claim, Mapping) and isinstance(claim.get("support_refs"), list)
        )
        if isinstance(response.get("answer_claims"), list)
        else 0,
        "reason_code_count": len(response.get("reason_codes", []))
        if isinstance(response.get("reason_codes"), list)
        else 0,
        "runtime_observability": observability
        if isinstance(observability, Mapping)
        else {},
    }


def _answerable_cases(cases: Iterable[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = [
        dict(case)
        for case in cases
        if str(case.get("expected", "")) == "answer"
        and str(case.get("question", "")).strip()
    ]
    return selected[:limit]


def run_profile(*, root: Path, questions_path: Path, limit: int) -> dict[str, Any]:
    questions = _load_json(questions_path)
    cases = _answerable_cases(questions.get("questions", []), limit)
    gate_path = Path(os.environ.get("M26_PA7_GATE_PATH", DEFAULT_GATE_PATH.as_posix()))
    if not gate_path.is_absolute():
        gate_path = root / gate_path
    owner = os.environ.get("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "")
    require_remote_dense = os.environ.get("M26_QUERY_REQUIRE_REMOTE_DENSE", "").lower() == "true"
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for case in cases:
        started = time.monotonic()
        try:
            response = run_owner_query_for_web(
                root=root,
                gate_path=gate_path,
                request_payload={"question": str(case["question"])},
                owner_subject_hash=owner,
                require_remote_dense=require_remote_dense,
            )
            rows.append(
                _safe_row(
                    case=case,
                    response=response,
                    wall_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "case_id": str(case.get("case_id", "")),
                    "exception_type": type(exc).__name__,
                    "reason_code": str(getattr(exc, "reason_code", "")),
                }
            )

    total_values = [int(row.get("total_latency_ms", 0)) for row in rows]
    return {
        "schema_version": SCHEMA_VERSION,
        "case_count": len(rows),
        "failure_count": len(failures),
        "failures": failures,
        "sequential_concurrency": 1,
        "raw_questions_recorded": False,
        "raw_answers_recorded": False,
        "raw_provider_text_recorded": False,
        "protected_knowledge_mutations": 0,
        "base_head_sha": os.environ.get("EXPECTED_HEAD_SHA", ""),
        "totals": {
            "mean_ms": _mean(total_values),
            "median_ms": _median(total_values),
            "p95_ms": _percentile(total_values, 95),
        },
        "stage_pareto": _stage_pareto(rows),
        "provider_pareto": _provider_pareto(rows),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("pilot/m26/m26-aq-final-r3-questions.json"),
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = run_profile(
        root=args.root.resolve(),
        questions_path=(args.root / args.questions).resolve()
        if not args.questions.is_absolute()
        else args.questions,
        limit=args.limit,
    )
    args.output.write_text(
        json.dumps(profile, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "case_count": profile["case_count"]}))


if __name__ == "__main__":
    main()
