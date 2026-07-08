from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .runtime import Runtime


def _stable_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


@dataclass(frozen=True)
class GoldenQueryCase:
    """Machine-verifiable expected behavior for one runtime query."""

    case_id: str
    query: str
    audiences: frozenset[str]
    expected_status: str
    min_selected_results: int = 0
    required_concepts: frozenset[str] = field(default_factory=frozenset)
    forbidden_concepts: frozenset[str] = field(default_factory=frozenset)
    expected_reasons: frozenset[str] = field(default_factory=frozenset)
    release_blocking: bool | None = None

    def to_identity(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "audiences": sorted(self.audiences),
            "expected_status": self.expected_status,
            "min_selected_results": self.min_selected_results,
            "required_concepts": sorted(self.required_concepts),
            "forbidden_concepts": sorted(self.forbidden_concepts),
            "expected_reasons": sorted(self.expected_reasons),
            "release_blocking": self.release_blocking,
        }


def _case_identity(case: GoldenQueryCase) -> str:
    digest = hashlib.sha256(_stable_json(case.to_identity())).hexdigest()[:32]
    return f"gqcase_{digest}"


def _suite_identity(cases: list[GoldenQueryCase]) -> str:
    payload = {
        "cases": [
            case.to_identity() for case in sorted(cases, key=lambda item: item.case_id)
        ]
    }
    digest = hashlib.sha256(_stable_json(payload)).hexdigest()[:32]
    return f"gqsuite_{digest}"


def _report_identity(
    *, suite_id: str, release: dict[str, Any], cases: list[dict[str, Any]]
) -> str:
    payload = {
        "suite_id": suite_id,
        "release": {
            "release_id": release["release_id"],
            "manifest_sha256": release["manifest_sha256"],
        },
        "cases": [
            {
                "case_id": case["case_id"],
                "case_run_id": case["case_run_id"],
                "passed": case["passed"],
                "failure_reasons": case["failure_reasons"],
                "evaluation_id": case["evaluation"]["evaluation_id"],
            }
            for case in cases
        ],
    }
    digest = hashlib.sha256(_stable_json(payload)).hexdigest()[:32]
    return f"gqreport_{digest}"


def evaluate_golden_query_case(
    *, case: GoldenQueryCase, response: dict[str, Any]
) -> dict[str, Any]:
    """Compare one Runtime response to its golden contract and fail closed."""

    results = response.get("results", [])
    concept_ids = {str(result.get("concept_id")) for result in results}
    evaluation = response["evaluation"]
    selected_count = int(response.get("retrieval", {}).get("selected_count", len(results)))
    actual_reasons = set(evaluation.get("reasons", []))

    failure_reasons: list[str] = []
    if response.get("status") != case.expected_status:
        failure_reasons.append("status_mismatch")
    if selected_count < case.min_selected_results:
        failure_reasons.append("insufficient_selected_results")
    missing_required = sorted(case.required_concepts - concept_ids)
    if missing_required:
        failure_reasons.append("required_concept_missing")
    forbidden_present = sorted(case.forbidden_concepts & concept_ids)
    if forbidden_present:
        failure_reasons.append("forbidden_concept_returned")
    if actual_reasons != set(case.expected_reasons):
        failure_reasons.append("evaluation_reasons_mismatch")
    expected_release_blocking = case.release_blocking
    if (
        expected_release_blocking is not None
        and evaluation.get("release_blocking") != expected_release_blocking
    ):
        failure_reasons.append("release_blocking_mismatch")
    if not evaluation.get("passed", False) and case.release_blocking is False:
        failure_reasons.append("unexpected_release_blocking_evaluation")

    failure_reasons = sorted(set(failure_reasons))
    identity_payload = {
        "case": case.to_identity(),
        "response": {
            "status": response.get("status"),
            "release": {
                "release_id": response["release"]["release_id"],
                "manifest_sha256": response["release"]["manifest_sha256"],
            },
            "concept_ids": sorted(concept_ids),
            "retrieval": response.get("retrieval", {}),
            "evaluation_id": evaluation["evaluation_id"],
            "failure_reasons": failure_reasons,
        },
    }
    run_digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    case_run_id = f"gqrun_{run_digest}"
    return {
        "case_id": case.case_id,
        "case_contract_id": _case_identity(case),
        "case_run_id": case_run_id,
        "query": case.query,
        "audiences": sorted(case.audiences),
        "passed": not failure_reasons,
        "failure_reasons": failure_reasons,
        "missing_required_concepts": missing_required,
        "forbidden_concepts_returned": forbidden_present,
        "status": response.get("status"),
        "release_blocking": evaluation.get("release_blocking"),
        "evaluation": evaluation,
        "retrieval": response.get("retrieval", {}),
        "results": results,
    }


def run_golden_query_suite(
    *, runtime: Runtime, cases: list[GoldenQueryCase]
) -> dict[str, Any]:
    """Run a deterministic golden query suite through the ACL-aware Runtime API."""

    if not cases:
        raise ValueError("golden query suite requires at least one case")
    ordered_cases = sorted(cases, key=lambda item: item.case_id)
    suite_id = _suite_identity(ordered_cases)
    case_reports: list[dict[str, Any]] = []
    release: dict[str, Any] | None = None
    for case in ordered_cases:
        response = runtime.query(case.query, set(case.audiences))
        release = response["release"]
        case_reports.append(evaluate_golden_query_case(case=case, response=response))

    if release is None:
        raise ValueError("golden query suite did not execute any cases")
    failed_cases = [case for case in case_reports if not case["passed"]]
    aggregate = {
        "case_count": len(case_reports),
        "passed_count": len(case_reports) - len(failed_cases),
        "failed_count": len(failed_cases),
        "release_blocking_count": sum(
            1 for case in case_reports if case["evaluation"].get("release_blocking")
        ),
    }
    report = {
        "schema_version": "1.0",
        "suite_id": suite_id,
        "report_id": "",
        "passed": not failed_cases,
        "release_blocking": bool(failed_cases),
        "release": {
            "release_id": release["release_id"],
            "manifest_sha256": release["manifest_sha256"],
        },
        "aggregate": aggregate,
        "failure_reasons": sorted(
            {reason for case in failed_cases for reason in case["failure_reasons"]}
        ),
        "cases": case_reports,
    }
    report["report_id"] = _report_identity(
        suite_id=suite_id, release=report["release"], cases=case_reports
    )
    return report
