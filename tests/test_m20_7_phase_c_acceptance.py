from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m20_phase_c_acceptance import (
    PROTECTED_MUTATION_KEYS,
    REQUIRED_GUARANTEES,
    REQUIRED_MILESTONES,
    REQUIRED_WORKFLOW_FAMILIES,
    validate_phase_c_acceptance,
)

ENGINE_SHA = "1" * 40
SOURCE_SHA = "2" * 40
FOUNDATION_SHA = "3" * 40


def _payload() -> dict:
    milestones = {}
    for index, name in enumerate(REQUIRED_MILESTONES, start=1):
        milestones[name] = {
            "issue_state": "completed",
            "implementation_merged": True,
            "reconciliation_merged": True,
            "implementation_merge_sha": f"{index:x}" * 40,
            "reconciliation_merge_sha": f"{index + 6:x}" * 40,
        }
    workflows = [
        {
            "name": name,
            "conclusion": "success",
            "head_sha": ENGINE_SHA,
        }
        for name in REQUIRED_WORKFLOW_FAMILIES
    ]
    return {
        "schema_version": "knowledge-engine-phase-c-evidence/v1",
        "identity": {
            "engine_sha": ENGINE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
        },
        "milestones": milestones,
        "workflows": workflows,
        "guarantees": {name: True for name in REQUIRED_GUARANTEES},
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
        "production_authority": False,
    }


def test_complete_phase_c_evidence_is_accepted_deterministically() -> None:
    first = validate_phase_c_acceptance(_payload())
    second = validate_phase_c_acceptance(_payload())

    assert first == second
    assert first["accepted"] is True
    assert first["production_authority"] is False
    assert first["milestone_count"] == 6
    assert first["workflow_count"] == len(REQUIRED_WORKFLOW_FAMILIES)
    assert first["guarantees_verified"] == list(REQUIRED_GUARANTEES)


def test_missing_or_extra_milestones_fail_closed() -> None:
    missing = _payload()
    missing["milestones"].pop("M20.6")
    with pytest.raises(IntegrityError, match="milestone set"):
        validate_phase_c_acceptance(missing)

    extra = _payload()
    extra["milestones"]["M20.8"] = copy.deepcopy(extra["milestones"]["M20.6"])
    with pytest.raises(IntegrityError, match="milestone set"):
        validate_phase_c_acceptance(extra)


def test_unmerged_or_open_milestone_evidence_fails_closed() -> None:
    payload = _payload()
    payload["milestones"]["M20.4"]["issue_state"] = "open"
    with pytest.raises(IntegrityError, match="issue is not completed"):
        validate_phase_c_acceptance(payload)

    payload = _payload()
    payload["milestones"]["M20.5"]["reconciliation_merged"] = False
    with pytest.raises(IntegrityError, match="reconciliation is not merged"):
        validate_phase_c_acceptance(payload)


def test_missing_failed_or_duplicate_workflow_evidence_fails_closed() -> None:
    missing = _payload()
    missing["workflows"].pop()
    with pytest.raises(IntegrityError, match="workflow evidence is missing"):
        validate_phase_c_acceptance(missing)

    failed = _payload()
    failed["workflows"][0]["conclusion"] = "failure"
    with pytest.raises(IntegrityError, match="workflow did not succeed"):
        validate_phase_c_acceptance(failed)

    duplicate = _payload()
    duplicate["workflows"].append(copy.deepcopy(duplicate["workflows"][0]))
    with pytest.raises(IntegrityError, match="duplicate workflow"):
        validate_phase_c_acceptance(duplicate)


def test_missing_false_or_unknown_guarantees_fail_closed() -> None:
    missing = _payload()
    missing["guarantees"].pop("acl_before_serialization")
    with pytest.raises(IntegrityError, match="guarantee is not proven"):
        validate_phase_c_acceptance(missing)

    false_value = _payload()
    false_value["guarantees"]["deterministic_ordering"] = False
    with pytest.raises(IntegrityError, match="guarantee is not proven"):
        validate_phase_c_acceptance(false_value)

    unknown = _payload()
    unknown["guarantees"]["secret_heuristic_enabled"] = True
    with pytest.raises(IntegrityError, match="unknown acceptance guarantee"):
        validate_phase_c_acceptance(unknown)


def test_any_protected_mutation_fails_closed() -> None:
    for key in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][key] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            validate_phase_c_acceptance(payload)


def test_production_authority_cannot_be_granted() -> None:
    payload = _payload()
    payload["production_authority"] = True
    with pytest.raises(IntegrityError, match="must not grant production authority"):
        validate_phase_c_acceptance(payload)


def test_identity_and_schema_drift_fail_closed() -> None:
    schema = _payload()
    schema["schema_version"] = "knowledge-engine-phase-c-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported acceptance evidence schema"):
        validate_phase_c_acceptance(schema)

    identity = _payload()
    identity["identity"]["engine_sha"] = "NOT-A-SHA"
    with pytest.raises(IntegrityError, match="40-character commit SHA"):
        validate_phase_c_acceptance(identity)
