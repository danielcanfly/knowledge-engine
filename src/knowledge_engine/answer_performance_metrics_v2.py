from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .release_quality_gate import GOVERNANCE_NO_WRITE


def _stable_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
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
class ClaimAlignment:
    claim_id: str
    claim_text_sha256: str
    support_status: str
    expected_fact_ids: tuple[str, ...] = ()
    citation_source_ids: tuple[str, ...] = ()
    unsupported_reason: str | None = None
    contradiction_evidence_ids: tuple[str, ...] = ()
    unknown_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("claim_id is required")
        if len(self.claim_text_sha256) != 64:
            raise ValueError("claim_text_sha256 must be a SHA-256 hex digest")
        try:
            int(self.claim_text_sha256, 16)
        except ValueError as exc:
            raise ValueError("claim_text_sha256 must be hexadecimal") from exc
        statuses = {"supported", "unsupported", "contradicted", "unknown"}
        if self.support_status not in statuses:
            raise ValueError("support_status is invalid")
        if len(set(self.expected_fact_ids)) != len(self.expected_fact_ids):
            raise ValueError("expected_fact_ids cannot contain duplicates")
        if len(set(self.citation_source_ids)) != len(self.citation_source_ids):
            raise ValueError("citation_source_ids cannot contain duplicates")
        if self.support_status == "supported":
            if not self.expected_fact_ids or not self.citation_source_ids:
                raise ValueError("supported claims require facts and citations")
            if self.unsupported_reason:
                raise ValueError("supported claims cannot have unsupported_reason")
        elif self.support_status == "unsupported":
            if not self.unsupported_reason:
                raise ValueError("unsupported claims require unsupported_reason")
        elif self.support_status == "contradicted":
            if not self.contradiction_evidence_ids:
                raise ValueError("contradicted claims require contradiction evidence")
            if not self.unsupported_reason:
                raise ValueError("contradicted claims require a reason")
        elif not self.unknown_evidence_ids:
            raise ValueError("unknown claims require unknown evidence")

    def to_identity(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text_sha256": self.claim_text_sha256,
            "support_status": self.support_status,
            "expected_fact_ids": list(self.expected_fact_ids),
            "citation_source_ids": list(self.citation_source_ids),
            "unsupported_reason": self.unsupported_reason,
            "contradiction_evidence_ids": list(self.contradiction_evidence_ids),
            "unknown_evidence_ids": list(self.unknown_evidence_ids),
        }


@dataclass(frozen=True)
class ClaimAlignedObservation:
    case_id: str
    expected_fact_ids: tuple[str, ...]
    claims: tuple[ClaimAlignment, ...]
    contradiction_expected: bool
    unknown_expected: bool
    response_hashes: tuple[str, ...]
    latency_ms: tuple[float, ...]
    token_cost_usd: tuple[float, ...]
    index_load_ms: tuple[float, ...]
    cache_hits: tuple[bool, ...]

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        if len(set(self.expected_fact_ids)) != len(self.expected_fact_ids):
            raise ValueError("expected_fact_ids cannot contain duplicates")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim_id duplicated within case")
        if len(self.response_hashes) < 2 or any(not value for value in self.response_hashes):
            raise ValueError("at least two response hashes are required")
        lengths = {
            len(self.latency_ms),
            len(self.token_cost_usd),
            len(self.index_load_ms),
            len(self.cache_hits),
        }
        if lengths != {len(self.response_hashes)}:
            raise ValueError("all sample lengths must match response hashes")
        samples = (*self.latency_ms, *self.token_cost_usd, *self.index_load_ms)
        if any(not math.isfinite(float(value)) or float(value) < 0 for value in samples):
            raise ValueError("performance samples must be finite and non-negative")
        contradicted = any(claim.support_status == "contradicted" for claim in self.claims)
        unknown = any(claim.support_status == "unknown" for claim in self.claims)
        if contradicted and not self.contradiction_expected:
            raise ValueError("contradiction evidence is unexpected for this case")
        if unknown and not self.unknown_expected:
            raise ValueError("unknown evidence is unexpected for this case")

    def to_identity(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_fact_ids": list(self.expected_fact_ids),
            "claims": [claim.to_identity() for claim in self.claims],
            "contradiction_expected": self.contradiction_expected,
            "unknown_expected": self.unknown_expected,
            "response_hashes": list(self.response_hashes),
            "latency_ms": list(self.latency_ms),
            "token_cost_usd": list(self.token_cost_usd),
            "index_load_ms": list(self.index_load_ms),
            "cache_hits": list(self.cache_hits),
        }


@dataclass(frozen=True)
class ClaimAlignmentMetricPolicy:
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
    min_case_count: int = 3
    min_claim_count: int = 2
    min_supported_claims: int = 1
    min_cited_claims: int = 1
    min_contradiction_probes: int = 1
    min_unknown_probes: int = 1
    min_samples_per_case: int = 2

    def __post_init__(self) -> None:
        ratio_names = (
            "min_faithfulness",
            "min_completeness",
            "max_unsupported_claim_rate",
            "min_contradiction_handling",
            "min_unknown_handling",
            "min_response_stability",
            "min_cache_hit_rate",
        )
        if any(not 0.0 <= float(getattr(self, name)) <= 1.0 for name in ratio_names):
            raise ValueError("quality ratios must be between 0 and 1")
        budget_names = (
            "max_p50_latency_ms",
            "max_p95_latency_ms",
            "max_mean_token_cost_usd",
            "max_p95_index_load_ms",
        )
        if any(float(getattr(self, name)) < 0 for name in budget_names):
            raise ValueError("performance budgets cannot be negative")
        floor_names = (
            "min_case_count",
            "min_claim_count",
            "min_supported_claims",
            "min_cited_claims",
            "min_contradiction_probes",
            "min_unknown_probes",
            "min_samples_per_case",
        )
        if any(int(getattr(self, name)) < 0 for name in floor_names):
            raise ValueError("coverage floors cannot be negative")
        if self.min_case_count == 0 or self.min_samples_per_case < 2:
            raise ValueError("case count and samples per case floors are too low")

    def to_identity(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def evaluate_claim_aligned_answer_metrics(
    *,
    golden_report: dict[str, Any],
    observations: list[ClaimAlignedObservation],
    policy: ClaimAlignmentMetricPolicy | None = None,
) -> dict[str, Any]:
    """Evaluate answer quality from claim-level support and citation alignment evidence."""

    if not observations:
        raise ValueError("claim-aligned observations are required")
    effective_policy = policy or ClaimAlignmentMetricPolicy()
    cases = golden_report.get("cases")
    release = golden_report.get("release")
    if not isinstance(cases, list) or not isinstance(release, dict):
        raise ValueError("golden report is malformed")
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

    all_claims: list[ClaimAlignment] = []
    expected_facts: set[tuple[str, str]] = set()
    covered_facts: set[tuple[str, str]] = set()
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
        all_claims.extend(observation.claims)
        expected_facts.update((case_id, fact_id) for fact_id in observation.expected_fact_ids)
        for claim in observation.claims:
            if claim.support_status == "supported":
                covered_facts.update((case_id, fact_id) for fact_id in claim.expected_fact_ids)
        handled_contradiction = any(
            claim.support_status == "contradicted" and claim.contradiction_evidence_ids
            for claim in observation.claims
        )
        handled_unknown = any(
            claim.support_status == "unknown" and claim.unknown_evidence_ids
            for claim in observation.claims
        )
        if observation.contradiction_expected:
            contradiction_expected += 1
            contradiction_handled += int(handled_contradiction)
        if observation.unknown_expected:
            unknown_expected += 1
            unknown_handled += int(handled_unknown)
        stable = len(set(observation.response_hashes)) == 1
        stable_cases += int(stable)
        latency_samples.extend(float(value) for value in observation.latency_ms)
        token_cost_samples.extend(float(value) for value in observation.token_cost_usd)
        index_load_samples.extend(float(value) for value in observation.index_load_ms)
        cache_samples.extend(observation.cache_hits)
        case_metrics.append(
            {
                "case_id": case_id,
                "claim_count": len(observation.claims),
                "supported_claim_count": sum(
                    claim.support_status == "supported" for claim in observation.claims
                ),
                "unsupported_claim_count": sum(
                    claim.support_status in {"unsupported", "contradicted"}
                    for claim in observation.claims
                ),
                "contradiction_handled": handled_contradiction,
                "unknown_handled": handled_unknown,
                "stable": stable,
                "sample_count": len(observation.response_hashes),
            }
        )

    supported_claims = sum(claim.support_status == "supported" for claim in all_claims)
    unsupported_claims = sum(
        claim.support_status in {"unsupported", "contradicted"} for claim in all_claims
    )
    assertive_claims = supported_claims + unsupported_claims
    cited_claims = sum(bool(claim.citation_source_ids) for claim in all_claims)
    contradiction_probes = sum(item.contradiction_expected for item in observations)
    unknown_probes = sum(item.unknown_expected for item in observations)
    minimum_samples = min(len(item.response_hashes) for item in observations)

    quality = {
        "faithfulness": _ratio(supported_claims, assertive_claims),
        "completeness": _ratio(len(covered_facts & expected_facts), len(expected_facts)),
        "unsupported_claim_rate": _ratio(unsupported_claims, assertive_claims, empty=0.0),
        "contradiction_handling": _ratio(contradiction_handled, contradiction_expected),
        "unknown_handling": _ratio(unknown_handled, unknown_expected),
        "response_stability": _ratio(stable_cases, len(observations)),
    }
    performance = {
        "sample_count": len(latency_samples),
        "p50_latency_ms": _nearest_rank(latency_samples, 0.50),
        "p95_latency_ms": _nearest_rank(latency_samples, 0.95),
        "mean_token_cost_usd": round(sum(token_cost_samples) / len(token_cost_samples), 6),
        "p95_index_load_ms": _nearest_rank(index_load_samples, 0.95),
        "cache_hit_rate": _ratio(sum(cache_samples), len(cache_samples), empty=0.0),
    }
    coverage = {
        "case_count": len(observations),
        "claim_count": len(all_claims),
        "supported_claims": supported_claims,
        "cited_claims": cited_claims,
        "contradiction_probes": contradiction_probes,
        "unknown_probes": unknown_probes,
        "minimum_samples_per_case": minimum_samples,
    }

    reasons: list[str] = []
    checks = {
        "faithfulness": quality["faithfulness"] >= effective_policy.min_faithfulness,
        "completeness": quality["completeness"] >= effective_policy.min_completeness,
        "unsupported_claim_rate": quality["unsupported_claim_rate"]
        <= effective_policy.max_unsupported_claim_rate,
        "contradiction_handling": quality["contradiction_handling"]
        >= effective_policy.min_contradiction_handling,
        "unknown_handling": quality["unknown_handling"]
        >= effective_policy.min_unknown_handling,
        "response_stability": quality["response_stability"]
        >= effective_policy.min_response_stability,
        "p50_latency_ms": performance["p50_latency_ms"]
        <= effective_policy.max_p50_latency_ms,
        "p95_latency_ms": performance["p95_latency_ms"]
        <= effective_policy.max_p95_latency_ms,
        "mean_token_cost_usd": performance["mean_token_cost_usd"]
        <= effective_policy.max_mean_token_cost_usd,
        "p95_index_load_ms": performance["p95_index_load_ms"]
        <= effective_policy.max_p95_index_load_ms,
        "cache_hit_rate": performance["cache_hit_rate"]
        >= effective_policy.min_cache_hit_rate,
        "case_count": coverage["case_count"] >= effective_policy.min_case_count,
        "claim_count": coverage["claim_count"] >= effective_policy.min_claim_count,
        "supported_claims": coverage["supported_claims"]
        >= effective_policy.min_supported_claims,
        "cited_claims": coverage["cited_claims"] >= effective_policy.min_cited_claims,
        "contradiction_probes": coverage["contradiction_probes"]
        >= effective_policy.min_contradiction_probes,
        "unknown_probes": coverage["unknown_probes"] >= effective_policy.min_unknown_probes,
        "minimum_samples_per_case": coverage["minimum_samples_per_case"]
        >= effective_policy.min_samples_per_case,
    }
    reasons.extend(f"{name}_check_failed" for name, passed in checks.items() if not passed)
    reasons = sorted(reasons)

    claim_alignment = [
        {"case_id": observation.case_id, **claim.to_identity()}
        for observation in sorted(observations, key=lambda item: item.case_id)
        for claim in sorted(observation.claims, key=lambda item: item.claim_id)
    ]
    identity = {
        "golden_report_id": golden_report.get("report_id"),
        "release": {
            "release_id": release.get("release_id"),
            "manifest_sha256": release.get("manifest_sha256"),
        },
        "policy": effective_policy.to_identity(),
        "quality": quality,
        "performance": performance,
        "coverage": coverage,
        "checks": checks,
        "claim_alignment": claim_alignment,
        "failure_reasons": reasons,
    }
    digest = hashlib.sha256(_stable_json(identity)).hexdigest()[:32]
    return {
        "schema_version": "2.0",
        "artifact_id": f"apmetrics2_{digest}",
        "golden_report_id": golden_report.get("report_id"),
        "passed": not reasons,
        "release_blocking": bool(reasons),
        "stale": False,
        "failure_reasons": reasons,
        "release": identity["release"],
        "faithfulness_summary": {
            key: quality[key]
            for key in (
                "faithfulness",
                "completeness",
                "contradiction_handling",
                "unknown_handling",
                "response_stability",
            )
        },
        "unsupported_claim_summary": {
            "unsupported_claim_rate": quality["unsupported_claim_rate"],
            "unsupported_claim_count": unsupported_claims,
        },
        "performance_summary": performance,
        "coverage": coverage,
        "checks": checks,
        "claim_alignment": claim_alignment,
        "case_metrics": case_metrics,
        "policy": effective_policy.to_identity(),
        "governance": GOVERNANCE_NO_WRITE,
    }
