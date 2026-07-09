from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .release_quality_gate import GOVERNANCE_NO_WRITE


def _stable_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _ratio(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return round(numerator / denominator, 6)


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile samples are required")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(float(ordered[rank - 1]), 6)


@dataclass(frozen=True)
class AnswerPerformanceMetricPolicy:
    min_faithfulness: float = 1.0
    min_completeness: float = 1.0
    max_unsupported_claim_rate: float = 0.0
    min_contradiction_handling: float = 1.0
    min_unknown_handling: float = 1.0
    min_response_stability: float = 1.0
    max_p50_latency_ms: float = 1000.0
    max_p95_latency_ms: float = 2000.0
    max_mean_token_cost_usd: float = 0.01
    max_p95_index_load_ms: float = 2000.0
    min_cache_hit_rate: float = 0.0

    def __post_init__(self) -> None:
        ratio_fields = (
            "min_faithfulness",
            "min_completeness",
            "max_unsupported_claim_rate",
            "min_contradiction_handling",
            "min_unknown_handling",
            "min_response_stability",
            "min_cache_hit_rate",
        )
        for name in ratio_fields:
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        budget_fields = (
            "max_p50_latency_ms",
            "max_p95_latency_ms",
            "max_mean_token_cost_usd",
            "max_p95_index_load_ms",
        )
        if any(float(getattr(self, name)) < 0.0 for name in budget_fields):
            raise ValueError("performance budgets cannot be negative")

    def to_identity(self) -> dict[str, float]:
        return {
            name: float(getattr(self, name))
            for name in (
                "min_faithfulness",
                "min_completeness",
                "max_unsupported_claim_rate",
                "min_contradiction_handling",
                "min_unknown_handling",
                "min_response_stability",
                "max_p50_latency_ms",
                "max_p95_latency_ms",
                "max_mean_token_cost_usd",
                "max_p95_index_load_ms",
                "min_cache_hit_rate",
            )
        }


@dataclass(frozen=True)
class AnswerPerformanceObservation:
    case_id: str
    expected_claim_count: int
    supported_claim_count: int
    unsupported_claim_count: int
    expected_fact_count: int
    covered_fact_count: int
    contradiction_expected: bool
    contradiction_handled: bool
    unknown_expected: bool
    unknown_handled: bool
    response_hashes: tuple[str, ...]
    latency_ms: tuple[float, ...]
    token_cost_usd: tuple[float, ...]
    index_load_ms: tuple[float, ...]
    cache_hits: tuple[bool, ...]

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        integer_fields = (
            self.expected_claim_count,
            self.supported_claim_count,
            self.unsupported_claim_count,
            self.expected_fact_count,
            self.covered_fact_count,
        )
        if any(value < 0 for value in integer_fields):
            raise ValueError("quality counts cannot be negative")
        observed_claims = self.supported_claim_count + self.unsupported_claim_count
        if observed_claims > self.expected_claim_count:
            raise ValueError("observed claims cannot exceed expected claims")
        if self.covered_fact_count > self.expected_fact_count:
            raise ValueError("covered facts cannot exceed expected facts")
        if self.contradiction_handled and not self.contradiction_expected:
            raise ValueError("contradiction handling cannot be true when not expected")
        if self.unknown_handled and not self.unknown_expected:
            raise ValueError("unknown handling cannot be true when not expected")
        if len(self.response_hashes) < 2 or any(not value for value in self.response_hashes):
            raise ValueError("at least two response hashes are required")
        sample_lengths = {
            len(self.latency_ms),
            len(self.token_cost_usd),
            len(self.index_load_ms),
            len(self.cache_hits),
        }
        if sample_lengths != {len(self.response_hashes)}:
            raise ValueError("all performance sample lengths must match response hashes")
        numeric_samples = (*self.latency_ms, *self.token_cost_usd, *self.index_load_ms)
        if any(not math.isfinite(float(value)) or float(value) < 0.0 for value in numeric_samples):
            raise ValueError("performance samples must be finite and non-negative")

    def to_identity(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_claim_count": self.expected_claim_count,
            "supported_claim_count": self.supported_claim_count,
            "unsupported_claim_count": self.unsupported_claim_count,
            "expected_fact_count": self.expected_fact_count,
            "covered_fact_count": self.covered_fact_count,
            "contradiction_expected": self.contradiction_expected,
            "contradiction_handled": self.contradiction_handled,
            "unknown_expected": self.unknown_expected,
            "unknown_handled": self.unknown_handled,
            "response_hashes": list(self.response_hashes),
            "latency_ms": list(self.latency_ms),
            "token_cost_usd": list(self.token_cost_usd),
            "index_load_ms": list(self.index_load_ms),
            "cache_hits": list(self.cache_hits),
        }


def _observation_set_id(observations: list[AnswerPerformanceObservation]) -> str:
    payload = {
        "observations": [
            item.to_identity() for item in sorted(observations, key=lambda value: value.case_id)
        ]
    }
    digest = hashlib.sha256(_stable_json(payload)).hexdigest()[:32]
    return f"apmetricset_{digest}"


def evaluate_answer_performance_metrics(
    *,
    golden_report: dict[str, Any],
    observations: list[AnswerPerformanceObservation],
    policy: AnswerPerformanceMetricPolicy | None = None,
) -> dict[str, Any]:
    """Aggregate deterministic answer-quality and bounded performance evidence."""

    if not observations:
        raise ValueError("answer/performance observations are required")
    effective_policy = policy or AnswerPerformanceMetricPolicy()
    cases = golden_report.get("cases")
    release = golden_report.get("release")
    if not isinstance(cases, list) or not isinstance(release, dict):
        raise ValueError("golden report is malformed")
    if not release.get("release_id") or not release.get("manifest_sha256"):
        raise ValueError("golden report release identity is incomplete")
    case_ids = [str(case.get("case_id", "")) for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or any(not case_id for case_id in case_ids):
        raise ValueError("golden report case identity missing")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("golden report case identity duplicated")
    observation_map = {item.case_id: item for item in observations}
    if len(observation_map) != len(observations):
        raise ValueError("observation case_id duplicated")
    if set(case_ids) != set(observation_map):
        raise ValueError("observations must exactly cover golden report cases")

    expected_claims = 0
    supported_claims = 0
    unsupported_claims = 0
    expected_facts = 0
    covered_facts = 0
    contradiction_expected = 0
    contradiction_handled = 0
    unknown_expected = 0
    unknown_handled = 0
    stable_cases = 0
    latency_samples: list[float] = []
    token_cost_samples: list[float] = []
    index_load_samples: list[float] = []
    cache_samples: list[bool] = []
    case_metrics: list[dict[str, Any]] = []

    for case_id in sorted(case_ids):
        observation = observation_map[case_id]
        expected_claims += observation.expected_claim_count
        supported_claims += observation.supported_claim_count
        unsupported_claims += observation.unsupported_claim_count
        expected_facts += observation.expected_fact_count
        covered_facts += observation.covered_fact_count
        if observation.contradiction_expected:
            contradiction_expected += 1
            contradiction_handled += int(observation.contradiction_handled)
        if observation.unknown_expected:
            unknown_expected += 1
            unknown_handled += int(observation.unknown_handled)
        stable = len(set(observation.response_hashes)) == 1
        stable_cases += int(stable)
        latency_samples.extend(float(value) for value in observation.latency_ms)
        token_cost_samples.extend(float(value) for value in observation.token_cost_usd)
        index_load_samples.extend(float(value) for value in observation.index_load_ms)
        cache_samples.extend(observation.cache_hits)
        case_metrics.append(
            {
                "case_id": case_id,
                "faithfulness": _ratio(
                    observation.supported_claim_count,
                    observation.supported_claim_count + observation.unsupported_claim_count,
                ),
                "completeness": _ratio(
                    observation.covered_fact_count,
                    observation.expected_fact_count,
                ),
                "unsupported_claim_rate": _ratio(
                    observation.unsupported_claim_count,
                    observation.supported_claim_count + observation.unsupported_claim_count,
                    empty=0.0,
                ),
                "contradiction_handled": observation.contradiction_handled,
                "unknown_handled": observation.unknown_handled,
                "stable": stable,
                "sample_count": len(observation.response_hashes),
            }
        )

    total_observed_claims = supported_claims + unsupported_claims
    answer_quality = {
        "faithfulness": _ratio(supported_claims, total_observed_claims),
        "completeness": _ratio(covered_facts, expected_facts),
        "unsupported_claim_rate": _ratio(
            unsupported_claims,
            total_observed_claims,
            empty=0.0,
        ),
        "contradiction_handling": _ratio(
            contradiction_handled,
            contradiction_expected,
        ),
        "unknown_handling": _ratio(unknown_handled, unknown_expected),
        "response_stability": _ratio(stable_cases, len(observations)),
    }
    performance = {
        "sample_count": len(latency_samples),
        "p50_latency_ms": _nearest_rank(latency_samples, 0.50),
        "p95_latency_ms": _nearest_rank(latency_samples, 0.95),
        "mean_token_cost_usd": round(
            sum(token_cost_samples) / len(token_cost_samples),
            6,
        ),
        "p95_index_load_ms": _nearest_rank(index_load_samples, 0.95),
        "cache_hit_rate": _ratio(sum(cache_samples), len(cache_samples), empty=0.0),
    }

    reasons: list[str] = []
    if answer_quality["faithfulness"] < effective_policy.min_faithfulness:
        reasons.append("faithfulness_below_threshold")
    if answer_quality["completeness"] < effective_policy.min_completeness:
        reasons.append("completeness_below_threshold")
    if answer_quality["unsupported_claim_rate"] > effective_policy.max_unsupported_claim_rate:
        reasons.append("unsupported_claim_rate_above_threshold")
    if answer_quality["contradiction_handling"] < effective_policy.min_contradiction_handling:
        reasons.append("contradiction_handling_below_threshold")
    if answer_quality["unknown_handling"] < effective_policy.min_unknown_handling:
        reasons.append("unknown_handling_below_threshold")
    if answer_quality["response_stability"] < effective_policy.min_response_stability:
        reasons.append("response_stability_below_threshold")
    if performance["p50_latency_ms"] > effective_policy.max_p50_latency_ms:
        reasons.append("p50_latency_budget_exceeded")
    if performance["p95_latency_ms"] > effective_policy.max_p95_latency_ms:
        reasons.append("p95_latency_budget_exceeded")
    if performance["mean_token_cost_usd"] > effective_policy.max_mean_token_cost_usd:
        reasons.append("mean_token_cost_budget_exceeded")
    if performance["p95_index_load_ms"] > effective_policy.max_p95_index_load_ms:
        reasons.append("p95_index_load_budget_exceeded")
    if performance["cache_hit_rate"] < effective_policy.min_cache_hit_rate:
        reasons.append("cache_hit_rate_below_threshold")
    reasons = sorted(set(reasons))

    identity_payload = {
        "golden_report_id": golden_report.get("report_id"),
        "release": {
            "release_id": release["release_id"],
            "manifest_sha256": release["manifest_sha256"],
        },
        "observation_set_id": _observation_set_id(observations),
        "answer_quality": answer_quality,
        "performance": performance,
        "policy": effective_policy.to_identity(),
        "reasons": reasons,
        "case_metrics": case_metrics,
    }
    digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    return {
        "schema_version": "1.0",
        "artifact_id": f"apmetrics_{digest}",
        "observation_set_id": _observation_set_id(observations),
        "golden_report_id": golden_report.get("report_id"),
        "passed": not reasons,
        "release_blocking": bool(reasons),
        "stale": False,
        "failure_reasons": reasons,
        "release": identity_payload["release"],
        "faithfulness_summary": answer_quality,
        "performance_summary": performance,
        "case_metrics": case_metrics,
        "policy": effective_policy.to_identity(),
        "governance": GOVERNANCE_NO_WRITE,
    }
