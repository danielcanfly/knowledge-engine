from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class RetrievalCitationMetricPolicy:
    min_expected_concept_hit_rate: float = 1.0
    min_selected_precision: float = 1.0
    max_false_positive_rate: float = 0.0
    min_zero_result_correctness: float = 1.0
    max_raw_fallback_rate: float = 0.0
    min_citation_presence: float = 1.0
    min_citation_support_precision: float = 1.0
    min_citation_target_correctness: float = 1.0
    min_citation_result_coverage: float = 1.0

    def __post_init__(self) -> None:
        for name, value in self.to_identity().items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

    def to_identity(self) -> dict[str, float]:
        return {
            "min_expected_concept_hit_rate": self.min_expected_concept_hit_rate,
            "min_selected_precision": self.min_selected_precision,
            "max_false_positive_rate": self.max_false_positive_rate,
            "min_zero_result_correctness": self.min_zero_result_correctness,
            "max_raw_fallback_rate": self.max_raw_fallback_rate,
            "min_citation_presence": self.min_citation_presence,
            "min_citation_support_precision": self.min_citation_support_precision,
            "min_citation_target_correctness": self.min_citation_target_correctness,
            "min_citation_result_coverage": self.min_citation_result_coverage,
        }


@dataclass(frozen=True)
class RetrievalCitationExpectation:
    case_id: str
    relevant_concepts: frozenset[str] = field(default_factory=frozenset)
    expected_concepts: frozenset[str] = field(default_factory=frozenset)
    expected_zero_result: bool = False
    allowed_citation_sources: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        if self.expected_zero_result and (
            self.relevant_concepts or self.expected_concepts or self.allowed_citation_sources
        ):
            raise ValueError("zero-result expectations cannot include result expectations")
        allowed = dict(self.allowed_citation_sources)
        if len(allowed) != len(self.allowed_citation_sources):
            raise ValueError("allowed citation concept duplicated")
        if not self.expected_concepts.issubset(self.relevant_concepts):
            raise ValueError("expected concepts must be relevant concepts")
        if not set(allowed).issubset(self.relevant_concepts):
            raise ValueError("citation targets must be relevant concepts")
        if any(not sources for sources in allowed.values()):
            raise ValueError("citation target source allowlists cannot be empty")

    def citation_sources(self) -> dict[str, frozenset[str]]:
        return {
            concept_id: frozenset(str(source_id) for source_id in source_ids)
            for concept_id, source_ids in self.allowed_citation_sources
        }

    def to_identity(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "relevant_concepts": sorted(self.relevant_concepts),
            "expected_concepts": sorted(self.expected_concepts),
            "expected_zero_result": self.expected_zero_result,
            "allowed_citation_sources": {
                concept_id: sorted(source_ids)
                for concept_id, source_ids in sorted(self.citation_sources().items())
            },
        }


def _expectation_id(expectations: list[RetrievalCitationExpectation]) -> str:
    payload = {
        "expectations": [
            item.to_identity() for item in sorted(expectations, key=lambda value: value.case_id)
        ]
    }
    digest = hashlib.sha256(_stable_json(payload)).hexdigest()[:32]
    return f"rcmetricset_{digest}"


def evaluate_retrieval_citation_metrics(
    *,
    golden_report: dict[str, Any],
    expectations: list[RetrievalCitationExpectation],
    policy: RetrievalCitationMetricPolicy | None = None,
) -> dict[str, Any]:
    """Aggregate deterministic retrieval and citation metrics from golden case reports."""

    if not expectations:
        raise ValueError("retrieval/citation expectations are required")
    effective_policy = policy or RetrievalCitationMetricPolicy()
    cases = golden_report.get("cases")
    release = golden_report.get("release")
    if not isinstance(cases, list) or not isinstance(release, dict):
        raise ValueError("golden report is malformed")
    if not release.get("release_id") or not release.get("manifest_sha256"):
        raise ValueError("golden report release identity is incomplete")

    expectation_map = {item.case_id: item for item in expectations}
    if len(expectation_map) != len(expectations):
        raise ValueError("expectation case_id duplicated")
    case_ids = [str(case.get("case_id", "")) for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or any(not case_id for case_id in case_ids):
        raise ValueError("golden report case identity missing")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("golden report case identity duplicated")
    if set(case_ids) != set(expectation_map):
        raise ValueError("expectations must exactly cover golden report cases")

    expected_concepts = 0
    hit_concepts = 0
    selected_total = 0
    relevant_selected = 0
    zero_expected = 0
    zero_correct = 0
    raw_fallback_cases = 0
    acl_filtered_total = 0
    selected_with_citations = 0
    citations_total = 0
    citations_target_correct = 0
    cited_results_total = 0
    cited_results_supported = 0
    relevant_selected_total = 0
    relevant_selected_with_valid_citation = 0
    audience_broadening: set[str] = set()
    case_metrics: list[dict[str, Any]] = []

    for case in sorted(cases, key=lambda value: str(value["case_id"])):
        expectation = expectation_map[str(case["case_id"])]
        case_release = case.get("evaluation", {}).get("release")
        if isinstance(case_release, dict) and case_release:
            if case_release.get("release_id") != release["release_id"]:
                raise ValueError("case release identity mismatch")
            if case_release.get("manifest_sha256") != release["manifest_sha256"]:
                raise ValueError("case manifest identity mismatch")
        audiences = {str(value) for value in case.get("audiences", [])}
        audience_broadening.update(audiences - {"public", "internal", "confidential", "restricted"})
        retrieval = case.get("retrieval")
        results = case.get("results")
        if not isinstance(retrieval, dict) or not isinstance(results, list):
            raise ValueError("case retrieval evidence is malformed")
        if retrieval.get("raw_fallback_used"):
            raw_fallback_cases += 1
        acl_filtered_total += int(retrieval.get("acl_filtered_count", 0))

        result_concepts: list[str] = []
        case_relevant_selected = 0
        case_valid_cited_results = 0
        allowed_sources = expectation.citation_sources()
        for result in results:
            if not isinstance(result, dict):
                raise ValueError("result must be an object")
            concept_id = str(result.get("concept_id", ""))
            if not concept_id:
                raise ValueError("result concept_id is required")
            result_concepts.append(concept_id)
            selected_total += 1
            if concept_id in expectation.relevant_concepts:
                relevant_selected += 1
                relevant_selected_total += 1
                case_relevant_selected += 1
            citations = result.get("citations", [])
            if not isinstance(citations, list):
                raise ValueError("result citations must be a list")
            if citations:
                selected_with_citations += 1
                cited_results_total += 1
            valid_for_result = False
            for citation in citations:
                if not isinstance(citation, dict):
                    raise ValueError("citation must be an object")
                source_id = str(citation.get("source_id", ""))
                if not source_id:
                    raise ValueError("citation source_id is required")
                citations_total += 1
                if source_id in allowed_sources.get(concept_id, frozenset()):
                    citations_target_correct += 1
                    valid_for_result = True
            if citations and valid_for_result and concept_id in expectation.relevant_concepts:
                cited_results_supported += 1
                relevant_selected_with_valid_citation += 1
                case_valid_cited_results += 1

        result_set = set(result_concepts)
        expected_concepts += len(expectation.expected_concepts)
        hit_concepts += len(expectation.expected_concepts & result_set)
        if expectation.expected_zero_result:
            zero_expected += 1
            if case.get("status") == "not_found" and not results:
                zero_correct += 1

        case_metrics.append(
            {
                "case_id": expectation.case_id,
                "selected_count": len(results),
                "relevant_selected_count": case_relevant_selected,
                "expected_hit_count": len(expectation.expected_concepts & result_set),
                "expected_concept_count": len(expectation.expected_concepts),
                "valid_cited_result_count": case_valid_cited_results,
                "expected_zero_result": expectation.expected_zero_result,
            }
        )

    metrics = {
        "expected_concept_hit_rate": _ratio(hit_concepts, expected_concepts),
        "selected_precision": _ratio(relevant_selected, selected_total),
        "false_positive_rate": _ratio(
            selected_total - relevant_selected,
            selected_total,
            empty=0.0,
        ),
        "zero_result_correctness": _ratio(zero_correct, zero_expected),
        "raw_fallback_rate": _ratio(raw_fallback_cases, len(cases), empty=0.0),
        "acl_filtered_count": acl_filtered_total,
        "citation_presence": _ratio(selected_with_citations, selected_total),
        "citation_support_precision": _ratio(cited_results_supported, cited_results_total),
        "citation_target_correctness": _ratio(citations_target_correct, citations_total),
        "citation_result_coverage": _ratio(
            relevant_selected_with_valid_citation,
            relevant_selected_total,
        ),
    }
    reasons: list[str] = []
    if metrics["expected_concept_hit_rate"] < effective_policy.min_expected_concept_hit_rate:
        reasons.append("expected_concept_hit_rate_below_threshold")
    if metrics["selected_precision"] < effective_policy.min_selected_precision:
        reasons.append("selected_precision_below_threshold")
    if metrics["false_positive_rate"] > effective_policy.max_false_positive_rate:
        reasons.append("false_positive_rate_above_threshold")
    if metrics["zero_result_correctness"] < effective_policy.min_zero_result_correctness:
        reasons.append("zero_result_correctness_below_threshold")
    if metrics["raw_fallback_rate"] > effective_policy.max_raw_fallback_rate:
        reasons.append("raw_fallback_rate_above_threshold")
    if metrics["citation_presence"] < effective_policy.min_citation_presence:
        reasons.append("citation_presence_below_threshold")
    if metrics["citation_support_precision"] < effective_policy.min_citation_support_precision:
        reasons.append("citation_support_precision_below_threshold")
    if metrics["citation_target_correctness"] < effective_policy.min_citation_target_correctness:
        reasons.append("citation_target_correctness_below_threshold")
    if metrics["citation_result_coverage"] < effective_policy.min_citation_result_coverage:
        reasons.append("citation_result_coverage_below_threshold")
    if audience_broadening:
        reasons.append("audience_broadening")
    reasons = sorted(set(reasons))

    identity_payload = {
        "golden_report_id": golden_report.get("report_id"),
        "release": {
            "release_id": release["release_id"],
            "manifest_sha256": release["manifest_sha256"],
        },
        "expectation_set_id": _expectation_id(expectations),
        "metrics": metrics,
        "policy": effective_policy.to_identity(),
        "reasons": reasons,
        "case_metrics": case_metrics,
    }
    digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    return {
        "schema_version": "1.0",
        "artifact_id": f"rcmetrics_{digest}",
        "expectation_set_id": _expectation_id(expectations),
        "golden_report_id": golden_report.get("report_id"),
        "passed": not reasons,
        "release_blocking": bool(reasons),
        "stale": False,
        "failure_reasons": reasons,
        "release": identity_payload["release"],
        "retrieval_quality": {
            key: metrics[key]
            for key in (
                "expected_concept_hit_rate",
                "selected_precision",
                "false_positive_rate",
                "zero_result_correctness",
                "raw_fallback_rate",
                "acl_filtered_count",
            )
        },
        "citation_quality": {
            key: metrics[key]
            for key in (
                "citation_presence",
                "citation_support_precision",
                "citation_target_correctness",
                "citation_result_coverage",
            )
        },
        "case_metrics": case_metrics,
        "audience_broadening": sorted(audience_broadening),
        "policy": effective_policy.to_identity(),
        "governance": GOVERNANCE_NO_WRITE,
    }
