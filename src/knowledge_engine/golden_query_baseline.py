from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _stable_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


@dataclass(frozen=True)
class GoldenQueryBaseline:
    """Immutable expected aggregate quality floor for one golden query suite."""

    baseline_id: str
    suite_id: str
    release_id: str
    manifest_sha256: str
    min_passed_count: int
    max_failed_count: int = 0
    max_release_blocking_count: int = 0
    required_case_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_failure_reasons: frozenset[str] = field(default_factory=frozenset)
    approved_audiences: frozenset[str] = field(default_factory=frozenset)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.baseline_id:
            raise ValueError("baseline_id is required")
        if not self.suite_id.startswith("gqsuite_"):
            raise ValueError("suite_id must be a golden query suite identity")
        if not self.release_id:
            raise ValueError("release_id is required")
        if not self.manifest_sha256:
            raise ValueError("manifest_sha256 is required")
        if self.min_passed_count < 0:
            raise ValueError("min_passed_count cannot be negative")
        if self.max_failed_count < 0:
            raise ValueError("max_failed_count cannot be negative")
        if self.max_release_blocking_count < 0:
            raise ValueError("max_release_blocking_count cannot be negative")
        if not self.approved_audiences:
            raise ValueError("approved_audiences is required")
        if not self.notes.strip():
            raise ValueError("baseline notes are required")

    def to_identity(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "suite_id": self.suite_id,
            "release_id": self.release_id,
            "manifest_sha256": self.manifest_sha256,
            "min_passed_count": self.min_passed_count,
            "max_failed_count": self.max_failed_count,
            "max_release_blocking_count": self.max_release_blocking_count,
            "required_case_ids": sorted(self.required_case_ids),
            "allowed_failure_reasons": sorted(self.allowed_failure_reasons),
            "approved_audiences": sorted(self.approved_audiences),
            "notes": self.notes,
        }


def _baseline_contract_id(baseline: GoldenQueryBaseline) -> str:
    digest = hashlib.sha256(_stable_json(baseline.to_identity())).hexdigest()[:32]
    return f"gqbaseline_{digest}"


def _case_ids(report: dict[str, Any]) -> set[str]:
    return {str(case.get("case_id")) for case in report.get("cases", [])}


def _case_audiences(report: dict[str, Any]) -> set[str]:
    audiences: set[str] = set()
    for case in report.get("cases", []):
        audiences.update(str(audience) for audience in case.get("audiences", []))
    return audiences


def evaluate_golden_query_baseline(
    *, baseline: GoldenQueryBaseline, report: dict[str, Any]
) -> dict[str, Any]:
    """Compare a golden query report to an immutable baseline and fail closed."""

    aggregate = report.get("aggregate", {})
    report_release = report.get("release", {})
    report_case_ids = _case_ids(report)
    report_audiences = _case_audiences(report)
    failure_reasons: list[str] = []

    if report.get("suite_id") != baseline.suite_id:
        failure_reasons.append("suite_id_mismatch")
    if report_release.get("release_id") != baseline.release_id:
        failure_reasons.append("release_id_mismatch")
    if report_release.get("manifest_sha256") != baseline.manifest_sha256:
        failure_reasons.append("manifest_sha256_mismatch")
    if int(aggregate.get("passed_count", 0)) < baseline.min_passed_count:
        failure_reasons.append("passed_count_regression")
    if int(aggregate.get("failed_count", 0)) > baseline.max_failed_count:
        failure_reasons.append("failed_count_regression")
    if int(aggregate.get("release_blocking_count", 0)) > baseline.max_release_blocking_count:
        failure_reasons.append("release_blocking_count_regression")
    missing_cases = sorted(baseline.required_case_ids - report_case_ids)
    if missing_cases:
        failure_reasons.append("required_case_missing")
    unexpected_reasons = sorted(
        set(report.get("failure_reasons", [])) - baseline.allowed_failure_reasons
    )
    if unexpected_reasons:
        failure_reasons.append("unexpected_failure_reason")
    audience_broadening = sorted(report_audiences - baseline.approved_audiences)
    if audience_broadening:
        failure_reasons.append("audience_broadening")
    if report.get("release_blocking") and not baseline.allowed_failure_reasons:
        failure_reasons.append("unexpected_report_release_blocking")

    failure_reasons = sorted(set(failure_reasons))
    identity_payload = {
        "baseline_contract_id": _baseline_contract_id(baseline),
        "report_id": report.get("report_id"),
        "failure_reasons": failure_reasons,
        "aggregate": aggregate,
        "missing_required_cases": missing_cases,
        "unexpected_failure_reasons": unexpected_reasons,
        "audience_broadening": audience_broadening,
    }
    digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    return {
        "schema_version": "1.0",
        "baseline_contract_id": _baseline_contract_id(baseline),
        "baseline_check_id": f"gqbaselinecheck_{digest}",
        "baseline_id": baseline.baseline_id,
        "report_id": report.get("report_id"),
        "passed": not failure_reasons,
        "release_blocking": bool(failure_reasons),
        "failure_reasons": failure_reasons,
        "missing_required_cases": missing_cases,
        "unexpected_failure_reasons": unexpected_reasons,
        "audience_broadening": audience_broadening,
        "aggregate": aggregate,
        "governance": {
            "canonical_source_write_permitted": False,
            "candidate_write_permitted": False,
            "release_write_permitted": False,
            "production_write_permitted": False,
            "permanent_ledger_append_permitted": False,
        },
    }
