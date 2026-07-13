from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError

REQUIRED_MILESTONES = tuple(f"M20.{index}" for index in range(1, 7))
REQUIRED_WORKFLOW_FAMILIES = (
    "M20.1 Embedding Contract and Bilingual Benchmark",
    "M20.2 Immutable Semantic Artifacts",
    "M20.3 Runtime Semantic Verification",
    "M20.4 Retrieval Modes",
    "M20.5 Hybrid Fusion",
    "M20.6 Lexical Enrichment",
    "CI",
    "M17 Architecture Canon Acceptance",
    "M18 Graph v2 Acceptance",
)
PROTECTED_MUTATION_KEYS = (
    "production_mutation_dispatched",
    "production_pointer_updated",
    "retained_r2_state_created",
    "credentials_modified",
    "permanent_ledger_written",
    "rollback_dispatched",
)
REQUIRED_GUARANTEES = (
    "lexical_authority_preserved",
    "vector_mode_diagnostic_only",
    "hybrid_non_production_only",
    "enrichment_non_production_only",
    "acl_before_serialization",
    "release_identity_bound",
    "deterministic_ordering",
    "bounded_outputs",
    "no_provider_network_dependency",
    "no_ann_or_vector_database",
    "no_public_vector_endpoint",
    "no_automatic_source_parsing",
    "no_cross_release_merge",
)


@dataclass(frozen=True)
class PhaseCAcceptanceReport:
    engine_sha: str
    source_sha: str
    foundation_sha: str
    milestone_count: int
    workflow_count: int
    guarantees_verified: tuple[str, ...]
    production_authority: bool
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-phase-c-acceptance/v1",
            "engine_sha": self.engine_sha,
            "source_sha": self.source_sha,
            "foundation_sha": self.foundation_sha,
            "milestone_count": self.milestone_count,
            "workflow_count": self.workflow_count,
            "guarantees_verified": list(self.guarantees_verified),
            "production_authority": self.production_authority,
            "accepted": self.accepted,
        }


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise IntegrityError(f"M20-ACCEPT-101 {label} must be a 40-character commit SHA")
    if any(character not in "0123456789abcdef" for character in value):
        raise IntegrityError(f"M20-ACCEPT-102 {label} must be lowercase hexadecimal")
    return value


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M20-ACCEPT-103 {label} must be an object")
    return value


def _validate_milestones(payload: Any) -> int:
    milestones = _require_mapping(payload, label="milestones")
    if tuple(sorted(milestones)) != REQUIRED_MILESTONES:
        raise IntegrityError("M20-ACCEPT-104 milestone set must be exactly M20.1 through M20.6")
    for name in REQUIRED_MILESTONES:
        evidence = _require_mapping(milestones[name], label=f"{name} evidence")
        if evidence.get("issue_state") != "completed":
            raise IntegrityError(f"M20-ACCEPT-105 {name} issue is not completed")
        if evidence.get("implementation_merged") is not True:
            raise IntegrityError(f"M20-ACCEPT-106 {name} implementation is not merged")
        if evidence.get("reconciliation_merged") is not True:
            raise IntegrityError(f"M20-ACCEPT-107 {name} reconciliation is not merged")
        _require_sha(evidence.get("implementation_merge_sha"), label=f"{name} implementation SHA")
        _require_sha(
            evidence.get("reconciliation_merge_sha"),
            label=f"{name} reconciliation SHA",
        )
    return len(milestones)


def _validate_workflows(payload: Any) -> int:
    if not isinstance(payload, list) or len(payload) > 64:
        raise IntegrityError("M20-ACCEPT-108 workflows must be a bounded list")
    names: list[str] = []
    for value in payload:
        evidence = _require_mapping(value, label="workflow evidence")
        name = evidence.get("name")
        if not isinstance(name, str) or not name:
            raise IntegrityError("M20-ACCEPT-109 workflow name is invalid")
        if evidence.get("conclusion") != "success":
            raise IntegrityError(f"M20-ACCEPT-110 workflow did not succeed: {name}")
        _require_sha(evidence.get("head_sha"), label=f"{name} workflow head")
        names.append(name)
    if len(set(names)) != len(names):
        raise IntegrityError("M20-ACCEPT-111 duplicate workflow evidence")
    missing = [name for name in REQUIRED_WORKFLOW_FAMILIES if name not in names]
    if missing:
        raise IntegrityError("M20-ACCEPT-112 required workflow evidence is missing")
    return len(names)


def _validate_guarantees(payload: Any) -> tuple[str, ...]:
    guarantees = _require_mapping(payload, label="guarantees")
    unknown = sorted(set(guarantees) - set(REQUIRED_GUARANTEES))
    if unknown:
        raise IntegrityError("M20-ACCEPT-113 unknown acceptance guarantee")
    for name in REQUIRED_GUARANTEES:
        if guarantees.get(name) is not True:
            raise IntegrityError(f"M20-ACCEPT-114 guarantee is not proven: {name}")
    return REQUIRED_GUARANTEES


def _validate_protected_state(payload: Any) -> None:
    protected = _require_mapping(payload, label="protected state")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M20-ACCEPT-115 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if protected.get(name) is not False:
            raise IntegrityError(f"M20-ACCEPT-116 protected mutation was dispatched: {name}")


def validate_phase_c_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="acceptance payload")
    if root.get("schema_version") != "knowledge-engine-phase-c-evidence/v1":
        raise IntegrityError("M20-ACCEPT-117 unsupported acceptance evidence schema")

    identity = _require_mapping(root.get("identity"), label="identity")
    engine_sha = _require_sha(identity.get("engine_sha"), label="Engine SHA")
    source_sha = _require_sha(identity.get("source_sha"), label="Source SHA")
    foundation_sha = _require_sha(identity.get("foundation_sha"), label="Foundation SHA")

    milestone_count = _validate_milestones(root.get("milestones"))
    workflow_count = _validate_workflows(root.get("workflows"))
    guarantees = _validate_guarantees(root.get("guarantees"))
    _validate_protected_state(root.get("protected_state"))

    if root.get("production_authority") is not False:
        raise IntegrityError("M20-ACCEPT-118 Phase C must not grant production authority")

    report = PhaseCAcceptanceReport(
        engine_sha=engine_sha,
        source_sha=source_sha,
        foundation_sha=foundation_sha,
        milestone_count=milestone_count,
        workflow_count=workflow_count,
        guarantees_verified=guarantees,
        production_authority=False,
        accepted=True,
    )
    return report.to_dict()


__all__ = [
    "PROTECTED_MUTATION_KEYS",
    "REQUIRED_GUARANTEES",
    "REQUIRED_MILESTONES",
    "REQUIRED_WORKFLOW_FAMILIES",
    "PhaseCAcceptanceReport",
    "validate_phase_c_acceptance",
]
