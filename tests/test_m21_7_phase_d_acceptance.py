from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_phase_d_acceptance import (
    FOUNDATION_SHA,
    MILESTONE_WORKFLOW_FAMILIES,
    PROTECTED_MUTATION_KEYS,
    REQUIRED_FINAL_WORKFLOW_FAMILIES,
    REQUIRED_MILESTONES,
    REQUIRED_PRIVACY_GUARANTEES,
    REQUIRED_REPLAY_GUARANTEES,
    REQUIRED_REVIEW_GUARANTEES,
    REQUIRED_THROUGHPUT_GUARANTEES,
    REQUIRED_WORKFLOW_FAMILIES,
    SOURCE_SHA,
    validate_phase_d_acceptance,
)

ENGINE_SHA = "1" * 40


def _payload() -> dict:
    milestones = {}
    for index, name in enumerate(REQUIRED_MILESTONES, start=1):
        implementation_head = f"{index:x}" * 40
        milestones[name] = {
            "issue_number": 300 + index,
            "implementation_pr": 310 + index,
            "reconciliation_pr": 320 + index,
            "issue_state": "completed",
            "implementation_merged": True,
            "reconciliation_merged": True,
            "implementation_head_sha": implementation_head,
            "implementation_merge_sha": f"{index + 6:x}" * 40,
            "reconciliation_head_sha": f"{index + 7:x}" * 40,
            "reconciliation_merge_sha": f"{index + 8:x}" * 40,
            "workflow": {
                "name": MILESTONE_WORKFLOW_FAMILIES[name],
                "conclusion": "success",
                "head_sha": implementation_head,
            },
        }
    return {
        "schema_version": "knowledge-engine-phase-d-evidence/v1",
        "identity": {
            "engine_sha": ENGINE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
        },
        "milestones": milestones,
        "workflows": [
            {"name": name, "conclusion": "success", "head_sha": ENGINE_SHA}
            for name in REQUIRED_FINAL_WORKFLOW_FAMILIES
        ],
        "throughput": {
            "inventory_items": 5000,
            "largest_batch_items": 500,
            "review_items": 500,
            "output_bytes": 2_000_000,
            "guarantees": {name: True for name in REQUIRED_THROUGHPUT_GUARANTEES},
        },
        "replay": {name: True for name in REQUIRED_REPLAY_GUARANTEES},
        "privacy": {name: True for name in REQUIRED_PRIVACY_GUARANTEES},
        "review_enforcement": {name: True for name in REQUIRED_REVIEW_GUARANTEES},
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
        "source_write_permitted": False,
        "github_source_pr_creation_permitted": False,
        "production_authority": False,
    }


def test_complete_phase_d_evidence_is_accepted_deterministically() -> None:
    first = validate_phase_d_acceptance(_payload())
    second = validate_phase_d_acceptance(_payload())

    assert first == second
    assert first["accepted"] is True
    assert first["production_authority"] is False
    assert first["milestone_count"] == 6
    assert first["workflow_count"] == len(REQUIRED_WORKFLOW_FAMILIES)
    assert first["inventory_items"] == 5000
    assert len(first["guarantees_verified"]) == (
        len(REQUIRED_THROUGHPUT_GUARANTEES)
        + len(REQUIRED_REPLAY_GUARANTEES)
        + len(REQUIRED_PRIVACY_GUARANTEES)
        + len(REQUIRED_REVIEW_GUARANTEES)
    )


def test_missing_or_extra_milestones_fail_closed() -> None:
    missing = _payload()
    missing["milestones"].pop("M21.6")
    with pytest.raises(IntegrityError, match="milestone set"):
        validate_phase_d_acceptance(missing)

    extra = _payload()
    extra["milestones"]["M21.8"] = copy.deepcopy(extra["milestones"]["M21.6"])
    with pytest.raises(IntegrityError, match="milestone set"):
        validate_phase_d_acceptance(extra)


def test_incomplete_or_duplicate_milestone_evidence_fails_closed() -> None:
    open_issue = _payload()
    open_issue["milestones"]["M21.4"]["issue_state"] = "open"
    with pytest.raises(IntegrityError, match="issue is not completed"):
        validate_phase_d_acceptance(open_issue)

    unmerged = _payload()
    unmerged["milestones"]["M21.5"]["reconciliation_merged"] = False
    with pytest.raises(IntegrityError, match="reconciliation is not merged"):
        validate_phase_d_acceptance(unmerged)

    duplicate = _payload()
    duplicate["milestones"]["M21.2"]["implementation_pr"] = duplicate["milestones"][
        "M21.1"
    ]["implementation_pr"]
    with pytest.raises(IntegrityError, match="duplicate issue or PR"):
        validate_phase_d_acceptance(duplicate)


def test_milestone_workflow_must_match_name_and_implementation_head() -> None:
    swapped = _payload()
    swapped["milestones"]["M21.2"]["workflow"]["name"] = MILESTONE_WORKFLOW_FAMILIES[
        "M21.1"
    ]
    with pytest.raises(IntegrityError, match="name mismatch"):
        validate_phase_d_acceptance(swapped)

    stale = _payload()
    stale["milestones"]["M21.3"]["workflow"]["head_sha"] = "f" * 40
    with pytest.raises(IntegrityError, match="expected head"):
        validate_phase_d_acceptance(stale)

    failed = _payload()
    failed["milestones"]["M21.4"]["workflow"]["conclusion"] = "failure"
    with pytest.raises(IntegrityError, match="workflow did not succeed"):
        validate_phase_d_acceptance(failed)


def test_final_workflows_must_be_complete_unique_and_exact_head() -> None:
    missing = _payload()
    missing["workflows"].pop()
    with pytest.raises(IntegrityError, match="required final workflow"):
        validate_phase_d_acceptance(missing)

    failed = _payload()
    failed["workflows"][0]["conclusion"] = "failure"
    with pytest.raises(IntegrityError, match="workflow did not succeed"):
        validate_phase_d_acceptance(failed)

    stale = _payload()
    stale["workflows"][0]["head_sha"] = "f" * 40
    with pytest.raises(IntegrityError, match="expected head"):
        validate_phase_d_acceptance(stale)

    duplicate = _payload()
    duplicate["workflows"].append(copy.deepcopy(duplicate["workflows"][0]))
    with pytest.raises(IntegrityError, match="duplicate final workflow"):
        validate_phase_d_acceptance(duplicate)


def test_source_and_foundation_release_identity_are_pinned() -> None:
    source = _payload()
    source["identity"]["source_sha"] = "a" * 40
    with pytest.raises(IntegrityError, match="Source release identity mismatch"):
        validate_phase_d_acceptance(source)

    foundation = _payload()
    foundation["identity"]["foundation_sha"] = "b" * 40
    with pytest.raises(IntegrityError, match="Foundation release identity mismatch"):
        validate_phase_d_acceptance(foundation)


@pytest.mark.parametrize(
    ("field", "limit", "message"),
    [
        ("inventory_items", 100_001, "inventory bound"),
        ("largest_batch_items", 1_001, "batch bound"),
        ("review_items", 1_001, "review-item bound"),
        ("output_bytes", 64 * 1024 * 1024 + 1, "output-byte bound"),
    ],
)
def test_throughput_bounds_fail_closed(field: str, limit: int, message: str) -> None:
    payload = _payload()
    payload["throughput"][field] = limit
    with pytest.raises(IntegrityError, match=message):
        validate_phase_d_acceptance(payload)


@pytest.mark.parametrize(
    ("group", "required", "label"),
    [
        ("throughput", REQUIRED_THROUGHPUT_GUARANTEES, "throughput"),
        ("replay", REQUIRED_REPLAY_GUARANTEES, "replay"),
        ("privacy", REQUIRED_PRIVACY_GUARANTEES, "privacy"),
        ("review_enforcement", REQUIRED_REVIEW_GUARANTEES, "review"),
    ],
)
def test_missing_false_or_unknown_guarantees_fail_closed(
    group: str, required: tuple[str, ...], label: str
) -> None:
    payload = _payload()
    container = payload[group]["guarantees"] if group == "throughput" else payload[group]
    container.pop(required[0])
    with pytest.raises(IntegrityError, match=f"{label} guarantee is not proven"):
        validate_phase_d_acceptance(payload)

    payload = _payload()
    container = payload[group]["guarantees"] if group == "throughput" else payload[group]
    container[required[0]] = False
    with pytest.raises(IntegrityError, match=f"{label} guarantee is not proven"):
        validate_phase_d_acceptance(payload)

    payload = _payload()
    container = payload[group]["guarantees"] if group == "throughput" else payload[group]
    container["invented_guarantee"] = True
    with pytest.raises(IntegrityError, match=f"unknown {label} guarantee"):
        validate_phase_d_acceptance(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for key in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][key] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            validate_phase_d_acceptance(payload)


@pytest.mark.parametrize(
    "field",
    [
        "source_write_permitted",
        "github_source_pr_creation_permitted",
        "production_authority",
    ],
)
def test_authority_cannot_be_granted(field: str) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(IntegrityError, match="must not"):
        validate_phase_d_acceptance(payload)


def test_identity_and_schema_drift_fail_closed() -> None:
    schema = _payload()
    schema["schema_version"] = "knowledge-engine-phase-d-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported acceptance evidence schema"):
        validate_phase_d_acceptance(schema)

    identity = _payload()
    identity["identity"]["engine_sha"] = "NOT-A-SHA"
    with pytest.raises(IntegrityError, match="40-character commit SHA"):
        validate_phase_d_acceptance(identity)
