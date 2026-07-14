from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
REQUIRED_MILESTONES = tuple(f"M21.{index}" for index in range(1, 7))
MILESTONE_WORKFLOW_FAMILIES = {
    "M21.1": "M21.1 Blog Inventory",
    "M21.2": "M21.2 Resumable Batch",
    "M21.3": "M21.3 Extraction Candidates",
    "M21.4": "M21.4 Governed Relations and Tags",
    "M21.5": "M21.5 Entity Resolution and Contradictions",
    "M21.6": "M21.6 Review Packets and Source PR Preparation",
}
REQUIRED_FINAL_WORKFLOW_FAMILIES = (
    "M21.7 Phase D Acceptance",
    "CI",
    "M17 Architecture Canon Acceptance",
    "M18 Graph v2 acceptance",
    "R2 Release Integration",
)
REQUIRED_WORKFLOW_FAMILIES = (
    *tuple(MILESTONE_WORKFLOW_FAMILIES.values()),
    *REQUIRED_FINAL_WORKFLOW_FAMILIES,
)
PROTECTED_MUTATION_KEYS = (
    "source_mutation_dispatched",
    "production_mutation_dispatched",
    "production_pointer_updated",
    "retained_r2_state_created",
    "credentials_modified",
    "permanent_ledger_written",
    "rollback_dispatched",
)
REQUIRED_THROUGHPUT_GUARANTEES = (
    "bounded_inventory",
    "bounded_batch_size",
    "bounded_review_items",
    "bounded_output_bytes",
    "no_unbounded_queue",
)
REQUIRED_REPLAY_GUARANTEES = (
    "interruption_resume_verified",
    "deterministic_replay",
    "byte_identical_outputs",
    "same_inputs_same_output_sha",
    "cross_release_mix_rejected",
)
REQUIRED_PRIVACY_GUARANTEES = (
    "secret_scan_passed",
    "audience_acl_preserved",
    "raw_private_content_absent",
    "bounded_privacy_safe_diagnostics",
    "credentials_absent",
)
REQUIRED_REVIEW_GUARANTEES = (
    "all_items_individually_reviewable",
    "complete_item_coverage",
    "ambiguity_blocks_packaging",
    "contradiction_blocks_packaging",
    "automatic_approval_forbidden",
    "bulk_manifest_preserves_item_hashes",
)

MAX_INVENTORY_ITEMS = 100_000
MAX_BATCH_ITEMS = 1_000
MAX_REVIEW_ITEMS = 1_000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class PhaseDAcceptanceReport:
    engine_sha: str
    source_sha: str
    foundation_sha: str
    milestone_count: int
    workflow_count: int
    inventory_items: int
    largest_batch_items: int
    review_items: int
    output_bytes: int
    guarantees_verified: tuple[str, ...]
    production_authority: bool
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-phase-d-acceptance/v1",
            "engine_sha": self.engine_sha,
            "source_sha": self.source_sha,
            "foundation_sha": self.foundation_sha,
            "milestone_count": self.milestone_count,
            "workflow_count": self.workflow_count,
            "inventory_items": self.inventory_items,
            "largest_batch_items": self.largest_batch_items,
            "review_items": self.review_items,
            "output_bytes": self.output_bytes,
            "guarantees_verified": list(self.guarantees_verified),
            "production_authority": self.production_authority,
            "accepted": self.accepted,
        }


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M21-ACCEPT-101 {label} must be an object")
    return value


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise IntegrityError(f"M21-ACCEPT-102 {label} must be a 40-character commit SHA")
    if any(character not in "0123456789abcdef" for character in value):
        raise IntegrityError(f"M21-ACCEPT-103 {label} must be lowercase hexadecimal")
    return value


def _require_positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntegrityError(f"M21-ACCEPT-104 {label} must be a positive integer")
    return value


def _validate_successful_workflow(
    payload: Any,
    *,
    expected_name: str,
    expected_head: str,
    label: str,
) -> None:
    workflow = _require_mapping(payload, label=label)
    if set(workflow) != {"name", "conclusion", "head_sha"}:
        raise IntegrityError(f"M21-ACCEPT-105 {label} shape is invalid")
    if workflow.get("name") != expected_name:
        raise IntegrityError(f"M21-ACCEPT-106 {label} name mismatch")
    if workflow.get("conclusion") != "success":
        raise IntegrityError(f"M21-ACCEPT-107 workflow did not succeed: {expected_name}")
    workflow_head = _require_sha(
        workflow.get("head_sha"),
        label=f"{expected_name} workflow head",
    )
    if workflow_head != expected_head:
        raise IntegrityError(
            f"M21-ACCEPT-108 workflow is not bound to expected head: {expected_name}"
        )


def _validate_milestones(payload: Any) -> int:
    milestones = _require_mapping(payload, label="milestones")
    if tuple(sorted(milestones)) != REQUIRED_MILESTONES:
        raise IntegrityError("M21-ACCEPT-109 milestone set must be exactly M21.1 through M21.6")
    issue_numbers: set[int] = set()
    implementation_prs: set[int] = set()
    reconciliation_prs: set[int] = set()
    for name in REQUIRED_MILESTONES:
        evidence = _require_mapping(milestones[name], label=f"{name} evidence")
        issue = _require_positive_int(evidence.get("issue_number"), label=f"{name} issue number")
        implementation_pr = _require_positive_int(
            evidence.get("implementation_pr"), label=f"{name} implementation PR"
        )
        reconciliation_pr = _require_positive_int(
            evidence.get("reconciliation_pr"), label=f"{name} reconciliation PR"
        )
        if (
            issue in issue_numbers
            or implementation_pr in implementation_prs
            or reconciliation_pr in reconciliation_prs
        ):
            raise IntegrityError("M21-ACCEPT-110 duplicate issue or PR evidence")
        issue_numbers.add(issue)
        implementation_prs.add(implementation_pr)
        reconciliation_prs.add(reconciliation_pr)
        if evidence.get("issue_state") != "completed":
            raise IntegrityError(f"M21-ACCEPT-111 {name} issue is not completed")
        if evidence.get("implementation_merged") is not True:
            raise IntegrityError(f"M21-ACCEPT-112 {name} implementation is not merged")
        if evidence.get("reconciliation_merged") is not True:
            raise IntegrityError(f"M21-ACCEPT-113 {name} reconciliation is not merged")
        implementation_head = _require_sha(
            evidence.get("implementation_head_sha"),
            label=f"{name} implementation head",
        )
        _require_sha(
            evidence.get("implementation_merge_sha"),
            label=f"{name} implementation merge",
        )
        _require_sha(
            evidence.get("reconciliation_head_sha"),
            label=f"{name} reconciliation head",
        )
        _require_sha(
            evidence.get("reconciliation_merge_sha"),
            label=f"{name} reconciliation merge",
        )
        _validate_successful_workflow(
            evidence.get("workflow"),
            expected_name=MILESTONE_WORKFLOW_FAMILIES[name],
            expected_head=implementation_head,
            label=f"{name} workflow evidence",
        )
    return len(milestones)


def _validate_final_workflows(payload: Any, engine_sha: str) -> int:
    if not isinstance(payload, list) or not payload or len(payload) > 32:
        raise IntegrityError("M21-ACCEPT-114 final workflows must be a bounded non-empty list")
    by_name: dict[str, Mapping[str, Any]] = {}
    for value in payload:
        evidence = _require_mapping(value, label="final workflow evidence")
        name = evidence.get("name")
        if not isinstance(name, str) or not name:
            raise IntegrityError("M21-ACCEPT-115 final workflow name is invalid")
        if name in by_name:
            raise IntegrityError("M21-ACCEPT-116 duplicate final workflow evidence")
        by_name[name] = evidence
    if set(by_name) != set(REQUIRED_FINAL_WORKFLOW_FAMILIES):
        raise IntegrityError("M21-ACCEPT-117 required final workflow evidence is missing")
    for name in REQUIRED_FINAL_WORKFLOW_FAMILIES:
        _validate_successful_workflow(
            by_name[name],
            expected_name=name,
            expected_head=engine_sha,
            label=f"{name} final workflow evidence",
        )
    return len(REQUIRED_MILESTONES) + len(by_name)


def _validate_guarantee_group(
    payload: Any,
    *,
    required: tuple[str, ...],
    label: str,
    code: int,
) -> tuple[str, ...]:
    guarantees = _require_mapping(payload, label=label)
    unknown = sorted(set(guarantees) - set(required))
    if unknown:
        raise IntegrityError(f"M21-ACCEPT-{code} unknown {label} guarantee")
    for name in required:
        if guarantees.get(name) is not True:
            raise IntegrityError(
                f"M21-ACCEPT-{code + 1} {label} guarantee is not proven: {name}"
            )
    return required


def _validate_throughput(payload: Any) -> tuple[int, int, int, int, tuple[str, ...]]:
    throughput = _require_mapping(payload, label="throughput")
    allowed = {
        "inventory_items",
        "largest_batch_items",
        "review_items",
        "output_bytes",
        "guarantees",
    }
    if set(throughput) != allowed:
        raise IntegrityError("M21-ACCEPT-120 throughput evidence shape is invalid")
    inventory_items = _require_positive_int(
        throughput.get("inventory_items"), label="inventory item count"
    )
    largest_batch_items = _require_positive_int(
        throughput.get("largest_batch_items"), label="largest batch item count"
    )
    review_items = _require_positive_int(
        throughput.get("review_items"), label="review item count"
    )
    output_bytes = _require_positive_int(
        throughput.get("output_bytes"), label="output byte count"
    )
    if inventory_items > MAX_INVENTORY_ITEMS:
        raise IntegrityError("M21-ACCEPT-121 inventory bound exceeded")
    if largest_batch_items > MAX_BATCH_ITEMS:
        raise IntegrityError("M21-ACCEPT-122 batch bound exceeded")
    if review_items > MAX_REVIEW_ITEMS:
        raise IntegrityError("M21-ACCEPT-123 review-item bound exceeded")
    if output_bytes > MAX_OUTPUT_BYTES:
        raise IntegrityError("M21-ACCEPT-124 output-byte bound exceeded")
    guarantees = _validate_guarantee_group(
        throughput.get("guarantees"),
        required=REQUIRED_THROUGHPUT_GUARANTEES,
        label="throughput",
        code=125,
    )
    return inventory_items, largest_batch_items, review_items, output_bytes, guarantees


def _validate_protected_state(payload: Any) -> None:
    protected = _require_mapping(payload, label="protected state")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M21-ACCEPT-140 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if protected.get(name) is not False:
            raise IntegrityError(f"M21-ACCEPT-141 protected mutation was dispatched: {name}")


def validate_phase_d_acceptance(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="acceptance payload")
    if root.get("schema_version") != "knowledge-engine-phase-d-evidence/v1":
        raise IntegrityError("M21-ACCEPT-142 unsupported acceptance evidence schema")

    identity = _require_mapping(root.get("identity"), label="identity")
    engine_sha = _require_sha(identity.get("engine_sha"), label="Engine SHA")
    source_sha = _require_sha(identity.get("source_sha"), label="Source SHA")
    foundation_sha = _require_sha(identity.get("foundation_sha"), label="Foundation SHA")
    if source_sha != SOURCE_SHA:
        raise IntegrityError("M21-ACCEPT-143 Source release identity mismatch")
    if foundation_sha != FOUNDATION_SHA:
        raise IntegrityError("M21-ACCEPT-144 Foundation release identity mismatch")

    milestone_count = _validate_milestones(root.get("milestones"))
    workflow_count = _validate_final_workflows(root.get("workflows"), engine_sha)
    inventory_items, largest_batch_items, review_items, output_bytes, throughput = (
        _validate_throughput(root.get("throughput"))
    )
    replay = _validate_guarantee_group(
        root.get("replay"),
        required=REQUIRED_REPLAY_GUARANTEES,
        label="replay",
        code=130,
    )
    privacy = _validate_guarantee_group(
        root.get("privacy"),
        required=REQUIRED_PRIVACY_GUARANTEES,
        label="privacy",
        code=132,
    )
    review = _validate_guarantee_group(
        root.get("review_enforcement"),
        required=REQUIRED_REVIEW_GUARANTEES,
        label="review",
        code=134,
    )
    _validate_protected_state(root.get("protected_state"))

    if root.get("source_write_permitted") is not False:
        raise IntegrityError("M21-ACCEPT-145 Phase D must not permit Source writes")
    if root.get("github_source_pr_creation_permitted") is not False:
        raise IntegrityError("M21-ACCEPT-146 Phase D must not permit Source PR creation")
    if root.get("production_authority") is not False:
        raise IntegrityError("M21-ACCEPT-147 Phase D must not grant production authority")

    verified = tuple((*throughput, *replay, *privacy, *review))
    report = PhaseDAcceptanceReport(
        engine_sha=engine_sha,
        source_sha=source_sha,
        foundation_sha=foundation_sha,
        milestone_count=milestone_count,
        workflow_count=workflow_count,
        inventory_items=inventory_items,
        largest_batch_items=largest_batch_items,
        review_items=review_items,
        output_bytes=output_bytes,
        guarantees_verified=verified,
        production_authority=False,
        accepted=True,
    )
    return report.to_dict()


__all__ = [
    "FOUNDATION_SHA",
    "MAX_BATCH_ITEMS",
    "MAX_INVENTORY_ITEMS",
    "MAX_OUTPUT_BYTES",
    "MAX_REVIEW_ITEMS",
    "MILESTONE_WORKFLOW_FAMILIES",
    "PROTECTED_MUTATION_KEYS",
    "REQUIRED_FINAL_WORKFLOW_FAMILIES",
    "REQUIRED_MILESTONES",
    "REQUIRED_PRIVACY_GUARANTEES",
    "REQUIRED_REPLAY_GUARANTEES",
    "REQUIRED_REVIEW_GUARANTEES",
    "REQUIRED_THROUGHPUT_GUARANTEES",
    "REQUIRED_WORKFLOW_FAMILIES",
    "SOURCE_SHA",
    "PhaseDAcceptanceReport",
    "validate_phase_d_acceptance",
]
