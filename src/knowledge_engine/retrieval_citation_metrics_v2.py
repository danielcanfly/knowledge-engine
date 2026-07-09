from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .release_quality_gate import GOVERNANCE_NO_WRITE
from .retrieval_citation_metrics import (
    RetrievalCitationExpectation,
    RetrievalCitationMetricPolicy,
    evaluate_retrieval_citation_metrics,
)


def _stable_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


@dataclass(frozen=True)
class RetrievalCoveragePolicy:
    min_case_count: int = 3
    min_answered_cases: int = 1
    min_cited_results: int = 1
    min_expected_concepts: int = 1
    min_citation_expectations: int = 1
    min_zero_result_cases: int = 1

    def __post_init__(self) -> None:
        values = self.to_identity().values()
        if any(value < 0 for value in values):
            raise ValueError("coverage floors cannot be negative")
        if self.min_case_count == 0:
            raise ValueError("min_case_count must be positive")

    def to_identity(self) -> dict[str, int]:
        return {
            "min_case_count": self.min_case_count,
            "min_answered_cases": self.min_answered_cases,
            "min_cited_results": self.min_cited_results,
            "min_expected_concepts": self.min_expected_concepts,
            "min_citation_expectations": self.min_citation_expectations,
            "min_zero_result_cases": self.min_zero_result_cases,
        }


def evaluate_retrieval_citation_metrics_v2(
    *,
    golden_report: dict[str, Any],
    expectations: list[RetrievalCitationExpectation],
    metric_policy: RetrievalCitationMetricPolicy | None = None,
    coverage_policy: RetrievalCoveragePolicy | None = None,
) -> dict[str, Any]:
    """Add explicit suite-coverage floors to the deterministic v1 metrics."""

    effective_coverage = coverage_policy or RetrievalCoveragePolicy()
    legacy = evaluate_retrieval_citation_metrics(
        golden_report=golden_report,
        expectations=expectations,
        policy=metric_policy,
    )
    cases = golden_report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("golden report cases are required")

    answered_cases = 0
    cited_results = 0
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("golden report case must be an object")
        results = case.get("results")
        if not isinstance(results, list):
            raise ValueError("golden report results must be a list")
        if case.get("status") == "answered" and results:
            answered_cases += 1
        cited_results += sum(
            1
            for result in results
            if isinstance(result, dict)
            and isinstance(result.get("citations"), list)
            and bool(result["citations"])
        )

    expected_concepts = sum(len(item.expected_concepts) for item in expectations)
    citation_expectations = sum(len(item.allowed_citation_sources) for item in expectations)
    zero_result_cases = sum(item.expected_zero_result for item in expectations)
    coverage = {
        "case_count": len(cases),
        "answered_cases": answered_cases,
        "cited_results": cited_results,
        "expected_concepts": expected_concepts,
        "citation_expectations": citation_expectations,
        "zero_result_cases": zero_result_cases,
    }
    floors = effective_coverage.to_identity()
    coverage_checks = {
        "case_count": coverage["case_count"] >= floors["min_case_count"],
        "answered_cases": coverage["answered_cases"] >= floors["min_answered_cases"],
        "cited_results": coverage["cited_results"] >= floors["min_cited_results"],
        "expected_concepts": coverage["expected_concepts"]
        >= floors["min_expected_concepts"],
        "citation_expectations": coverage["citation_expectations"]
        >= floors["min_citation_expectations"],
        "zero_result_cases": coverage["zero_result_cases"]
        >= floors["min_zero_result_cases"],
    }
    coverage_failures = sorted(
        f"insufficient_{name}" for name, passed in coverage_checks.items() if not passed
    )
    failure_reasons = sorted({*legacy["failure_reasons"], *coverage_failures})
    identity = {
        "legacy_artifact_id": legacy["artifact_id"],
        "expectation_set_id": legacy["expectation_set_id"],
        "release": legacy["release"],
        "coverage_policy": floors,
        "coverage": coverage,
        "coverage_checks": coverage_checks,
        "failure_reasons": failure_reasons,
    }
    digest = hashlib.sha256(_stable_json(identity)).hexdigest()[:32]
    return {
        "schema_version": "2.0",
        "artifact_id": f"rcmetrics2_{digest}",
        "legacy_artifact_id": legacy["artifact_id"],
        "expectation_set_id": legacy["expectation_set_id"],
        "golden_report_id": legacy["golden_report_id"],
        "passed": not failure_reasons,
        "release_blocking": bool(failure_reasons),
        "stale": False,
        "failure_reasons": failure_reasons,
        "release": legacy["release"],
        "retrieval_quality": legacy["retrieval_quality"],
        "citation_quality": legacy["citation_quality"],
        "case_metrics": legacy["case_metrics"],
        "audience_broadening": legacy["audience_broadening"],
        "coverage": coverage,
        "coverage_policy": floors,
        "coverage_checks": coverage_checks,
        "governance": GOVERNANCE_NO_WRITE,
    }
