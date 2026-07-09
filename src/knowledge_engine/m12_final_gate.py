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


def _artifact_id(artifact: dict[str, Any]) -> str:
    for key in ("gate_decision_id", "artifact_id", "report_id", "baseline_check_id"):
        value = artifact.get(key)
        if value:
            return str(value)
    return ""


def _release_identity(artifact: dict[str, Any]) -> tuple[str | None, str | None]:
    release = artifact.get("release")
    if not isinstance(release, dict):
        return None, None
    return release.get("release_id"), release.get("manifest_sha256")


def _governance_is_no_write(artifact: dict[str, Any]) -> bool:
    governance = artifact.get("governance")
    if not isinstance(governance, dict):
        return False
    return all(governance.get(key) is False for key in GOVERNANCE_NO_WRITE)


@dataclass(frozen=True)
class M12FinalGatePolicy:
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
    required_artifact_ids: frozenset[str] = field(default_factory=frozenset)

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
            raise ValueError("final gate review notes are required")
        if not self.required_artifact_ids:
            raise ValueError("required_artifact_ids is required")

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
            "required_artifact_ids": sorted(self.required_artifact_ids),
        }


def _policy_id(policy: M12FinalGatePolicy) -> str:
    digest = hashlib.sha256(_stable_json(policy.to_identity())).hexdigest()[:32]
    return f"m12gate_{digest}"


def evaluate_m12_final_gate(
    *,
    policy: M12FinalGatePolicy,
    release_quality_decision: dict[str, Any],
    retrieval_citation_metrics: dict[str, Any],
    answer_performance_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Compose the final M12 release-blocking decision without mutating release state."""

    artifacts = [
        release_quality_decision,
        retrieval_citation_metrics,
        answer_performance_metrics,
    ]
    artifact_ids = [_artifact_id(artifact) for artifact in artifacts]
    present_ids = {artifact_id for artifact_id in artifact_ids if artifact_id}
    duplicate_ids = sorted(
        {
            artifact_id
            for artifact_id in artifact_ids
            if artifact_id and artifact_ids.count(artifact_id) > 1
        }
    )
    missing_required = sorted(policy.required_artifact_ids - present_ids)
    reasons: list[str] = []
    if any(not artifact_id for artifact_id in artifact_ids):
        reasons.append("artifact_identity_missing")
    if duplicate_ids:
        reasons.append("artifact_identity_duplicated")
    if missing_required:
        reasons.append("required_artifact_missing")

    failed_artifacts: list[str] = []
    release_blocking_artifacts: list[str] = []
    stale_artifacts: list[str] = []
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
        release_id, manifest_sha256 = _release_identity(artifact)
        if release_id != policy.release_id:
            release_mismatches.append(label)
        if manifest_sha256 != policy.manifest_sha256:
            manifest_mismatches.append(label)
        if not _governance_is_no_write(artifact):
            governance_mismatches.append(label)

    if failed_artifacts:
        reasons.append("artifact_failed")
    if release_blocking_artifacts:
        reasons.append("artifact_release_blocking")
    if stale_artifacts:
        reasons.append("artifact_stale")
    if release_mismatches:
        reasons.append("release_id_mismatch")
    if manifest_mismatches:
        reasons.append("manifest_sha256_mismatch")
    if governance_mismatches:
        reasons.append("governance_boundary_mismatch")

    retrieval_quality = retrieval_citation_metrics.get("retrieval_quality")
    citation_quality = retrieval_citation_metrics.get("citation_quality")
    faithfulness_summary = answer_performance_metrics.get("faithfulness_summary")
    performance_summary = answer_performance_metrics.get("performance_summary")
    if not all(
        isinstance(value, dict)
        for value in (
            retrieval_quality,
            citation_quality,
            faithfulness_summary,
            performance_summary,
        )
    ):
        reasons.append("metric_section_missing")

    rq_audience = release_quality_decision.get("audience_broadening", [])
    rc_audience = retrieval_citation_metrics.get("audience_broadening", [])
    raw_fallback_rate = None
    if isinstance(retrieval_quality, dict):
        raw_fallback_rate = retrieval_quality.get("raw_fallback_rate")
    boundary_failures: list[str] = []
    if rq_audience or rc_audience:
        boundary_failures.append("audience_broadening")
    if raw_fallback_rate != 0.0:
        boundary_failures.append("raw_fallback_detected")
    if governance_mismatches:
        boundary_failures.append("write_boundary_violation")
    if boundary_failures:
        reasons.append("boundary_evaluation_failed")

    query_eval_summary = {
        "release_quality_decision_id": _artifact_id(release_quality_decision),
        "artifact_count": len(release_quality_decision.get("artifact_refs", [])),
        "failed_artifact_count": len(release_quality_decision.get("failed_artifacts", [])),
        "release_blocking_artifact_count": len(
            release_quality_decision.get("release_blocking_artifacts", [])
        ),
        "stale_artifact_count": len(release_quality_decision.get("stale_artifacts", [])),
        "passed": release_quality_decision.get("passed") is True,
    }
    boundary_eval = {
        "passed": not boundary_failures,
        "release_blocking": bool(boundary_failures),
        "failure_reasons": sorted(boundary_failures),
        "audience_broadening": sorted({*rq_audience, *rc_audience}),
        "raw_fallback_rate": raw_fallback_rate,
        "governance_no_write": not governance_mismatches,
    }
    regression_matrix = {
        "M12.1_runtime_query_evaluation": query_eval_summary["passed"],
        "M12.2_golden_query_suite": query_eval_summary["artifact_count"] > 0,
        "M12.3_golden_baseline_gate": query_eval_summary["artifact_count"] > 0,
        "M12.4_release_quality_gate": release_quality_decision.get("passed") is True,
        "M12.5_retrieval_citation_metrics": retrieval_citation_metrics.get("passed") is True,
        "M12.6_answer_performance_metrics": answer_performance_metrics.get("passed") is True,
    }
    if not all(regression_matrix.values()):
        reasons.append("regression_matrix_incomplete")
    reasons = sorted(set(reasons))

    artifact_refs = [
        {
            "artifact_id": artifact_id,
            "schema_version": str(artifact.get("schema_version", "")),
            "release_id": _release_identity(artifact)[0],
            "manifest_sha256": _release_identity(artifact)[1],
        }
        for artifact_id, artifact in sorted(
            zip(artifact_ids, artifacts, strict=True),
            key=lambda item: item[0],
        )
    ]
    identity_payload = {
        "policy_id": _policy_id(policy),
        "artifact_refs": artifact_refs,
        "failure_reasons": reasons,
        "query_eval_summary": query_eval_summary,
        "retrieval_quality": retrieval_quality,
        "citation_quality": citation_quality,
        "faithfulness_summary": faithfulness_summary,
        "performance_summary": performance_summary,
        "boundary_eval": boundary_eval,
        "regression_matrix": regression_matrix,
    }
    digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    passed = not reasons
    return {
        "schema_version": "1.0",
        "artifact_id": f"m12closure_{digest}",
        "gate_policy_id": _policy_id(policy),
        "gate_id": policy.gate_id,
        "passed": passed,
        "release_blocking": not passed,
        "stale": False,
        "promotion_eligible": passed,
        "failure_reasons": reasons,
        "missing_required_artifacts": missing_required,
        "duplicate_artifacts": duplicate_ids,
        "failed_artifacts": sorted(failed_artifacts),
        "release_blocking_artifacts": sorted(release_blocking_artifacts),
        "stale_artifacts": sorted(stale_artifacts),
        "release_mismatches": sorted(release_mismatches),
        "manifest_mismatches": sorted(manifest_mismatches),
        "governance_mismatches": sorted(governance_mismatches),
        "artifact_refs": artifact_refs,
        "query_eval_summary": query_eval_summary,
        "retrieval_quality": retrieval_quality,
        "citation_quality": citation_quality,
        "faithfulness_summary": faithfulness_summary,
        "performance_summary": performance_summary,
        "boundary_eval": boundary_eval,
        "regression_matrix": regression_matrix,
        "closure_matrix": {
            **regression_matrix,
            "M12.7_final_release_blocking_gate": passed,
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
