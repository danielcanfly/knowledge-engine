from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .release_quality_gate import GOVERNANCE_NO_WRITE


def _stable_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _artifact_id(artifact: dict[str, Any]) -> str:
    for key in ("gate_decision_id", "artifact_id", "report_id", "baseline_check_id"):
        value = artifact.get(key)
        if value:
            return str(value)
    return ""


def _release(artifact: dict[str, Any]) -> tuple[str | None, str | None]:
    release = artifact.get("release")
    if not isinstance(release, dict):
        return None, None
    return release.get("release_id"), release.get("manifest_sha256")


def _no_write(artifact: dict[str, Any]) -> bool:
    governance = artifact.get("governance")
    return isinstance(governance, dict) and all(
        governance.get(key) is False for key in GOVERNANCE_NO_WRITE
    )


def _family(artifact_id: str) -> str:
    for prefix, family in (
        ("rqdecision_", "M12.4_release_quality_gate"),
        ("rcmetrics2_", "M12.5_retrieval_citation_metrics_v2"),
        ("apmetrics2_", "M12.6_answer_performance_metrics_v2"),
        ("qeval_", "M12.1_runtime_query_evaluation"),
        ("gqreport_", "M12.2_golden_query_suite"),
        ("gqbaselinecheck_", "M12.3_golden_baseline_gate"),
    ):
        if artifact_id.startswith(prefix):
            return family
    return "unknown"


@dataclass(frozen=True)
class M12FinalGatePolicyV2:
    gate_id: str
    release_id: str
    manifest_sha256: str
    canonical_source_sha: str
    production_release_id: str
    production_manifest_sha256: str
    production_pointer_sha256: str
    reviewer_identity: str
    reviewed_at: str
    notes: str
    required_top_level_artifact_ids: frozenset[str] = field(default_factory=frozenset)
    required_nested_families: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "M12.1_runtime_query_evaluation",
                "M12.2_golden_query_suite",
                "M12.3_golden_baseline_gate",
            }
        )
    )

    def __post_init__(self) -> None:
        required = (
            self.gate_id,
            self.release_id,
            self.manifest_sha256,
            self.canonical_source_sha,
            self.production_release_id,
            self.production_manifest_sha256,
            self.production_pointer_sha256,
            self.reviewer_identity,
            self.reviewed_at,
        )
        if any(not value for value in required):
            raise ValueError("final gate identity fields are required")
        if not self.notes.strip():
            raise ValueError("final gate notes are required")
        if len(self.required_top_level_artifact_ids) != 3:
            raise ValueError("exactly three top-level artifact IDs are required")
        expected = {
            "M12.1_runtime_query_evaluation",
            "M12.2_golden_query_suite",
            "M12.3_golden_baseline_gate",
        }
        if self.required_nested_families != expected:
            raise ValueError("required_nested_families must exactly match M12.1-M12.3")

    def to_identity(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "release_id": self.release_id,
            "manifest_sha256": self.manifest_sha256,
            "canonical_source_sha": self.canonical_source_sha,
            "production_release_id": self.production_release_id,
            "production_manifest_sha256": self.production_manifest_sha256,
            "production_pointer_sha256": self.production_pointer_sha256,
            "reviewer_identity": self.reviewer_identity,
            "reviewed_at": self.reviewed_at,
            "notes": self.notes,
            "required_top_level_artifact_ids": sorted(
                self.required_top_level_artifact_ids
            ),
            "required_nested_families": sorted(self.required_nested_families),
        }


def evaluate_m12_final_gate_v2(
    *,
    policy: M12FinalGatePolicyV2,
    release_quality_decision: dict[str, Any],
    retrieval_citation_metrics: dict[str, Any],
    answer_performance_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Require exact artifact families, coverage, and claim alignment before eligibility."""

    artifacts = [
        release_quality_decision,
        retrieval_citation_metrics,
        answer_performance_metrics,
    ]
    artifact_ids = [_artifact_id(artifact) for artifact in artifacts]
    families = [_family(artifact_id) for artifact_id in artifact_ids]
    expected_top_families = [
        "M12.4_release_quality_gate",
        "M12.5_retrieval_citation_metrics_v2",
        "M12.6_answer_performance_metrics_v2",
    ]
    reasons: list[str] = []

    if artifact_ids != list(dict.fromkeys(artifact_ids)):
        reasons.append("top_level_artifact_identity_duplicated")
    if set(artifact_ids) != policy.required_top_level_artifact_ids:
        reasons.append("top_level_artifact_identity_mismatch")
    if families != expected_top_families:
        reasons.append("top_level_artifact_family_mismatch")
    if release_quality_decision.get("schema_version") != "1.0":
        reasons.append("release_quality_schema_mismatch")
    if retrieval_citation_metrics.get("schema_version") != "2.0":
        reasons.append("retrieval_metrics_schema_mismatch")
    if answer_performance_metrics.get("schema_version") != "2.0":
        reasons.append("answer_metrics_schema_mismatch")

    failed_artifacts: list[str] = []
    stale_artifacts: list[str] = []
    release_blocking_artifacts: list[str] = []
    release_mismatches: list[str] = []
    manifest_mismatches: list[str] = []
    governance_mismatches: list[str] = []
    for artifact_id, artifact in zip(artifact_ids, artifacts, strict=True):
        label = artifact_id or "<missing>"
        if artifact.get("passed") is not True:
            failed_artifacts.append(label)
        if artifact.get("release_blocking"):
            release_blocking_artifacts.append(label)
        if artifact.get("stale"):
            stale_artifacts.append(label)
        release_id, manifest_sha256 = _release(artifact)
        if release_id != policy.release_id:
            release_mismatches.append(label)
        if manifest_sha256 != policy.manifest_sha256:
            manifest_mismatches.append(label)
        if not _no_write(artifact):
            governance_mismatches.append(label)

    if failed_artifacts:
        reasons.append("artifact_failed")
    if stale_artifacts:
        reasons.append("artifact_stale")
    if release_blocking_artifacts:
        reasons.append("artifact_release_blocking")
    if release_mismatches:
        reasons.append("release_id_mismatch")
    if manifest_mismatches:
        reasons.append("manifest_sha256_mismatch")
    if governance_mismatches:
        reasons.append("governance_boundary_mismatch")

    nested_refs = release_quality_decision.get("artifact_refs")
    if not isinstance(nested_refs, list) or not nested_refs:
        nested_refs = []
        reasons.append("nested_artifact_refs_missing")
    nested_ids = [
        str(item.get("artifact_id", ""))
        for item in nested_refs
        if isinstance(item, dict)
    ]
    if len(nested_ids) != len(nested_refs) or any(not item for item in nested_ids):
        reasons.append("nested_artifact_identity_missing")
    if len(set(nested_ids)) != len(nested_ids):
        reasons.append("nested_artifact_identity_duplicated")
    nested_families = [_family(artifact_id) for artifact_id in nested_ids]
    nested_family_counts = {
        family: nested_families.count(family) for family in policy.required_nested_families
    }
    missing_nested_families = sorted(
        family for family, count in nested_family_counts.items() if count == 0
    )
    if missing_nested_families:
        reasons.append("required_nested_artifact_family_missing")
    unknown_nested = sorted(
        artifact_id
        for artifact_id, family in zip(nested_ids, nested_families, strict=True)
        if family == "unknown"
    )
    if unknown_nested:
        reasons.append("unknown_nested_artifact_family")

    retrieval_quality = retrieval_citation_metrics.get("retrieval_quality")
    citation_quality = retrieval_citation_metrics.get("citation_quality")
    retrieval_coverage = retrieval_citation_metrics.get("coverage")
    retrieval_checks = retrieval_citation_metrics.get("coverage_checks")
    faithfulness_summary = answer_performance_metrics.get("faithfulness_summary")
    unsupported_claim_summary = answer_performance_metrics.get(
        "unsupported_claim_summary"
    )
    performance_summary = answer_performance_metrics.get("performance_summary")
    answer_coverage = answer_performance_metrics.get("coverage")
    claim_alignment = answer_performance_metrics.get("claim_alignment")
    metric_sections = (
        retrieval_quality,
        citation_quality,
        retrieval_coverage,
        retrieval_checks,
        faithfulness_summary,
        unsupported_claim_summary,
        performance_summary,
        answer_coverage,
    )
    if not all(isinstance(value, dict) for value in metric_sections):
        reasons.append("metric_section_missing")
    if not isinstance(claim_alignment, list) or not claim_alignment:
        reasons.append("claim_alignment_missing")
    if isinstance(retrieval_checks, dict) and not all(retrieval_checks.values()):
        reasons.append("retrieval_coverage_floor_failed")
    answer_checks = answer_performance_metrics.get("checks")
    if not isinstance(answer_checks, dict) or not all(answer_checks.values()):
        reasons.append("answer_or_performance_check_failed")

    audience_broadening = sorted(
        {
            *release_quality_decision.get("audience_broadening", []),
            *retrieval_citation_metrics.get("audience_broadening", []),
        }
    )
    raw_fallback_rate = (
        retrieval_quality.get("raw_fallback_rate")
        if isinstance(retrieval_quality, dict)
        else None
    )
    boundary_failures: list[str] = []
    if audience_broadening:
        boundary_failures.append("audience_broadening")
    if raw_fallback_rate != 0.0:
        boundary_failures.append("raw_fallback_detected")
    if governance_mismatches:
        boundary_failures.append("write_boundary_violation")
    if boundary_failures:
        reasons.append("boundary_evaluation_failed")

    regression_matrix = {
        "M12.1_runtime_query_evaluation": nested_family_counts[
            "M12.1_runtime_query_evaluation"
        ]
        > 0,
        "M12.2_golden_query_suite": nested_family_counts[
            "M12.2_golden_query_suite"
        ]
        == 1,
        "M12.3_golden_baseline_gate": nested_family_counts[
            "M12.3_golden_baseline_gate"
        ]
        == 1,
        "M12.4_release_quality_gate": release_quality_decision.get("passed") is True,
        "M12.5_retrieval_citation_metrics_v2": retrieval_citation_metrics.get("passed")
        is True,
        "M12.6_answer_performance_metrics_v2": answer_performance_metrics.get("passed")
        is True,
    }
    if not all(regression_matrix.values()):
        reasons.append("regression_matrix_incomplete")
    reasons = sorted(set(reasons))
    passed = not reasons

    artifact_refs = [
        {
            "artifact_id": artifact_id,
            "family": family,
            "schema_version": artifact.get("schema_version"),
            "release_id": _release(artifact)[0],
            "manifest_sha256": _release(artifact)[1],
        }
        for artifact_id, family, artifact in zip(
            artifact_ids, families, artifacts, strict=True
        )
    ]
    identity = {
        "policy": policy.to_identity(),
        "artifact_refs": artifact_refs,
        "nested_artifact_ids": sorted(nested_ids),
        "nested_family_counts": nested_family_counts,
        "failure_reasons": reasons,
        "regression_matrix": regression_matrix,
        "retrieval_coverage": retrieval_coverage,
        "answer_coverage": answer_coverage,
    }
    digest = hashlib.sha256(_stable_json(identity)).hexdigest()[:32]
    return {
        "schema_version": "2.0",
        "artifact_id": f"m12closure2_{digest}",
        "gate_id": policy.gate_id,
        "passed": passed,
        "release_blocking": not passed,
        "stale": False,
        "promotion_eligible": passed,
        "failure_reasons": reasons,
        "artifact_refs": artifact_refs,
        "nested_artifact_ids": sorted(nested_ids),
        "nested_family_counts": nested_family_counts,
        "missing_nested_families": missing_nested_families,
        "unknown_nested_artifacts": unknown_nested,
        "failed_artifacts": sorted(failed_artifacts),
        "stale_artifacts": sorted(stale_artifacts),
        "release_blocking_artifacts": sorted(release_blocking_artifacts),
        "release_mismatches": sorted(release_mismatches),
        "manifest_mismatches": sorted(manifest_mismatches),
        "governance_mismatches": sorted(governance_mismatches),
        "retrieval_quality": retrieval_quality,
        "citation_quality": citation_quality,
        "retrieval_coverage": retrieval_coverage,
        "faithfulness_summary": faithfulness_summary,
        "unsupported_claim_summary": unsupported_claim_summary,
        "performance_summary": performance_summary,
        "answer_coverage": answer_coverage,
        "claim_alignment": claim_alignment,
        "boundary_eval": {
            "passed": not boundary_failures,
            "failure_reasons": sorted(boundary_failures),
            "audience_broadening": audience_broadening,
            "raw_fallback_rate": raw_fallback_rate,
            "governance_no_write": not governance_mismatches,
        },
        "regression_matrix": regression_matrix,
        "closure_matrix": {
            **regression_matrix,
            "M12.7_final_release_blocking_gate_v2": passed,
        },
        "release": {
            "release_id": policy.release_id,
            "manifest_sha256": policy.manifest_sha256,
            "canonical_source_sha": policy.canonical_source_sha,
            "production_release_id": policy.production_release_id,
            "production_manifest_sha256": policy.production_manifest_sha256,
            "production_pointer_sha256": policy.production_pointer_sha256,
        },
        "review": {
            "reviewer_identity": policy.reviewer_identity,
            "reviewed_at": policy.reviewed_at,
            "notes": policy.notes,
        },
        "governance": GOVERNANCE_NO_WRITE,
    }
