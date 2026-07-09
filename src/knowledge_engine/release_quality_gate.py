from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _stable_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


GOVERNANCE_NO_WRITE = {
    "canonical_source_write_permitted": False,
    "source_pr_creation_permitted": False,
    "candidate_write_permitted": False,
    "release_write_permitted": False,
    "production_write_permitted": False,
    "rollback_permitted": False,
    "permanent_ledger_append_permitted": False,
}


@dataclass(frozen=True)
class ReleaseQualityGatePolicy:
    """Immutable release-quality gate policy for one exact release baseline."""

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
    approved_audiences: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.gate_id:
            raise ValueError("gate_id is required")
        if not self.release_id:
            raise ValueError("release_id is required")
        if not self.manifest_sha256:
            raise ValueError("manifest_sha256 is required")
        if not self.canonical_source_sha:
            raise ValueError("canonical_source_sha is required")
        if not self.production_release_id:
            raise ValueError("production_release_id is required")
        if not self.production_manifest_sha256:
            raise ValueError("production_manifest_sha256 is required")
        if not self.production_pointer_sha256:
            raise ValueError("production_pointer_sha256 is required")
        if not self.reviewer_identity:
            raise ValueError("reviewer_identity is required")
        if not self.reviewed_at:
            raise ValueError("reviewed_at is required")
        if not self.notes.strip():
            raise ValueError("notes are required")
        if not self.required_artifact_ids:
            raise ValueError("required_artifact_ids is required")
        if not self.approved_audiences:
            raise ValueError("approved_audiences is required")

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
            "approved_audiences": sorted(self.approved_audiences),
        }


def _policy_id(policy: ReleaseQualityGatePolicy) -> str:
    digest = hashlib.sha256(_stable_json(policy.to_identity())).hexdigest()[:32]
    return f"rqgate_{digest}"


def _artifact_id(artifact: dict[str, Any]) -> str:
    for key in (
        "evaluation_id",
        "report_id",
        "baseline_check_id",
        "artifact_id",
        "gate_decision_id",
    ):
        value = artifact.get(key)
        if value:
            return str(value)
    return ""


def _artifact_audiences(artifact: dict[str, Any]) -> set[str]:
    audiences: set[str] = set()
    audiences.update(str(audience) for audience in artifact.get("audiences", []))
    for case in artifact.get("cases", []):
        audiences.update(str(audience) for audience in case.get("audiences", []))
    return audiences


def _artifact_release(artifact: dict[str, Any]) -> dict[str, Any]:
    release = artifact.get("release")
    if isinstance(release, dict):
        return release
    return {
        "release_id": artifact.get("release_id"),
        "manifest_sha256": artifact.get("manifest_sha256"),
    }


def evaluate_release_quality_gate(
    *, policy: ReleaseQualityGatePolicy, artifacts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Bundle M12 query-quality evidence into one fail-closed release gate."""

    failure_reasons: list[str] = []
    artifact_ids = [_artifact_id(artifact) for artifact in artifacts]
    present_ids = {artifact_id for artifact_id in artifact_ids if artifact_id}
    missing_required = sorted(policy.required_artifact_ids - present_ids)
    duplicate_ids = sorted(
        {
            artifact_id
            for artifact_id in artifact_ids
            if artifact_id and artifact_ids.count(artifact_id) > 1
        }
    )
    empty_artifact_indexes = [
        index for index, artifact_id in enumerate(artifact_ids) if not artifact_id
    ]
    release_mismatches: list[str] = []
    manifest_mismatches: list[str] = []
    failed_artifacts: list[str] = []
    release_blocking_artifacts: list[str] = []
    stale_artifacts: list[str] = []
    audience_broadening: set[str] = set()

    if not artifacts:
        failure_reasons.append("no_artifacts")
    if missing_required:
        failure_reasons.append("required_artifact_missing")
    if duplicate_ids:
        failure_reasons.append("duplicate_artifact")
    if empty_artifact_indexes:
        failure_reasons.append("artifact_missing_identity")

    for artifact in artifacts:
        artifact_id = _artifact_id(artifact) or "<missing>"
        release = _artifact_release(artifact)
        if release.get("release_id") != policy.release_id:
            release_mismatches.append(artifact_id)
        if release.get("manifest_sha256") != policy.manifest_sha256:
            manifest_mismatches.append(artifact_id)
        if artifact.get("passed") is not True:
            failed_artifacts.append(artifact_id)
        if artifact.get("release_blocking"):
            release_blocking_artifacts.append(artifact_id)
        if artifact.get("stale"):
            stale_artifacts.append(artifact_id)
        audience_broadening.update(
            _artifact_audiences(artifact) - policy.approved_audiences
        )

    if release_mismatches:
        failure_reasons.append("release_id_mismatch")
    if manifest_mismatches:
        failure_reasons.append("manifest_sha256_mismatch")
    if failed_artifacts:
        failure_reasons.append("artifact_failed")
    if release_blocking_artifacts:
        failure_reasons.append("artifact_release_blocking")
    if stale_artifacts:
        failure_reasons.append("stale_artifact")
    if audience_broadening:
        failure_reasons.append("audience_broadening")

    failure_reasons = sorted(set(failure_reasons))
    artifact_refs = [
        {
            "artifact_id": artifact_id,
            "schema_version": str(artifact.get("schema_version", "")),
            "release_id": _artifact_release(artifact).get("release_id"),
            "manifest_sha256": _artifact_release(artifact).get("manifest_sha256"),
        }
        for artifact_id, artifact in sorted(
            zip(artifact_ids, artifacts, strict=True), key=lambda item: item[0]
        )
    ]
    identity_payload = {
        "gate_policy_id": _policy_id(policy),
        "artifact_refs": artifact_refs,
        "failure_reasons": failure_reasons,
        "missing_required_artifacts": missing_required,
        "duplicate_artifacts": duplicate_ids,
        "release_mismatches": sorted(release_mismatches),
        "manifest_mismatches": sorted(manifest_mismatches),
        "failed_artifacts": sorted(failed_artifacts),
        "release_blocking_artifacts": sorted(release_blocking_artifacts),
        "stale_artifacts": sorted(stale_artifacts),
        "audience_broadening": sorted(audience_broadening),
    }
    digest = hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    return {
        "schema_version": "1.0",
        "gate_policy_id": _policy_id(policy),
        "gate_decision_id": f"rqdecision_{digest}",
        "gate_id": policy.gate_id,
        "passed": not failure_reasons,
        "release_blocking": bool(failure_reasons),
        "failure_reasons": failure_reasons,
        "missing_required_artifacts": missing_required,
        "duplicate_artifacts": duplicate_ids,
        "release_mismatches": sorted(release_mismatches),
        "manifest_mismatches": sorted(manifest_mismatches),
        "failed_artifacts": sorted(failed_artifacts),
        "release_blocking_artifacts": sorted(release_blocking_artifacts),
        "stale_artifacts": sorted(stale_artifacts),
        "audience_broadening": sorted(audience_broadening),
        "artifact_refs": artifact_refs,
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
