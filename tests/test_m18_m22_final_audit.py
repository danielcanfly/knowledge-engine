from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m18_m22_final_audit import (
    ENGINE_SHA,
    FOUNDATION_SHA,
    NON_CANONICAL_ISSUES,
    PHASES,
    PROTECTED_MUTATION_KEYS,
    SOURCE_SHA,
    validate_m18_m22_final_audit,
)


def _phase(expected: dict) -> dict:
    payload = copy.deepcopy(expected)
    payload["milestones"] = list(payload["milestones"])
    payload["issues"] = list(payload["issues"])
    payload.update(
        {
            "canonical_issues_completed": True,
            "implementation_merged": True,
            "reconciliation_merged": True,
            "implementation_expected_head_merge": True,
            "reconciliation_expected_head_merge": True,
            "machine_contract_passed": True,
        }
    )
    if expected["phase"] == "D":
        payload["repair_completed"] = True
        payload["repair_expected_head_merges"] = True
    return payload


def _payload() -> dict:
    return {
        "schema_version": "knowledge-engine-m18-m22-final-audit-evidence/v1",
        "engine_sha": ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "phases": [_phase(item) for item in PHASES],
        "non_canonical_issues": list(NON_CANONICAL_ISSUES),
        "non_canonical_zero_evidence_role": True,
        "repository_quality_gates_passed": True,
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def test_real_final_audit_is_deterministic_and_non_mutating() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    first = validate_m18_m22_final_audit(payload)
    second = validate_m18_m22_final_audit(payload)
    assert first == second
    assert payload == before
    assert first["status"] == "accepted"
    assert first["phase_count"] == 5
    assert first["canonical_milestone_count"] == 35
    assert first["canonical_issue_count"] == 35
    assert first["post_ga_m18_m22_closed"] is True
    assert first["production_authority"] is False
    assert len(first["audit_sha256"]) == 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("engine_sha", "f" * 40, "Engine identity"),
        ("source_sha", "f" * 40, "release identity"),
        ("foundation_sha", "f" * 40, "release identity"),
    ],
)
def test_exact_release_identity(field: str, value: str, message: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_m18_m22_final_audit(payload)


def test_all_five_phases_are_required_in_order() -> None:
    payload = _payload()
    payload["phases"].pop()
    with pytest.raises(IntegrityError, match="exactly five phases"):
        validate_m18_m22_final_audit(payload)

    payload = _payload()
    payload["phases"].reverse()
    with pytest.raises(IntegrityError, match="phase evidence mismatch"):
        validate_m18_m22_final_audit(payload)


@pytest.mark.parametrize(
    "field",
    [
        "closure_issue",
        "implementation_pr",
        "reconciliation_pr",
        "implementation_head",
        "implementation_merge",
        "reconciliation_head",
        "reconciliation_merge",
        "contract",
    ],
)
def test_phase_identity_cannot_drift(field: str) -> None:
    payload = _payload()
    current = payload["phases"][2][field]
    payload["phases"][2][field] = 999 if isinstance(current, int) else "f" * 40
    with pytest.raises(IntegrityError, match="phase evidence mismatch"):
        validate_m18_m22_final_audit(payload)


@pytest.mark.parametrize(
    "field",
    [
        "canonical_issues_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
        "machine_contract_passed",
    ],
)
def test_phase_completion_flags_are_required(field: str) -> None:
    payload = _payload()
    payload["phases"][1][field] = False
    with pytest.raises(IntegrityError, match="phase completion is false"):
        validate_m18_m22_final_audit(payload)


def test_phase_d_repair_chain_is_required() -> None:
    payload = _payload()
    payload["phases"][3]["repair_completed"] = False
    with pytest.raises(IntegrityError, match="Phase D repair is incomplete"):
        validate_m18_m22_final_audit(payload)

    payload = _payload()
    payload["phases"][3]["repair_expected_head_merges"] = False
    with pytest.raises(IntegrityError, match="Phase D repair is incomplete"):
        validate_m18_m22_final_audit(payload)


def test_canonical_issue_inventory_is_exact_and_unique() -> None:
    payload = _payload()
    payload["phases"][0]["issues"][0] = payload["phases"][1]["issues"][0]
    with pytest.raises(IntegrityError):
        validate_m18_m22_final_audit(payload)


def test_canonical_milestone_inventory_is_exact_and_unique() -> None:
    payload = _payload()
    payload["phases"][4]["milestones"][0] = "M21.1"
    with pytest.raises(IntegrityError):
        validate_m18_m22_final_audit(payload)


def test_non_canonical_inventory_is_exact_and_has_no_authority() -> None:
    payload = _payload()
    payload["non_canonical_issues"].append(999)
    with pytest.raises(IntegrityError, match="non-canonical inventory"):
        validate_m18_m22_final_audit(payload)

    payload = _payload()
    payload["non_canonical_zero_evidence_role"] = False
    with pytest.raises(IntegrityError, match="evidence authority"):
        validate_m18_m22_final_audit(payload)


def test_repository_quality_gates_are_required() -> None:
    payload = _payload()
    payload["repository_quality_gates_passed"] = False
    with pytest.raises(IntegrityError, match="quality gates"):
        validate_m18_m22_final_audit(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation"):
            validate_m18_m22_final_audit(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _payload()
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        validate_m18_m22_final_audit(payload)

    payload = _payload()
    payload["schema_version"] = "knowledge-engine-m18-m22-final-audit-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported schema"):
        validate_m18_m22_final_audit(payload)
