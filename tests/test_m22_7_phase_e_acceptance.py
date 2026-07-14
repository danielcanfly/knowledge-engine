from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_phase_e_acceptance import (
    EXPECTED_CAPABILITIES,
    EXPECTED_MILESTONES,
    FINAL_ENGINE_SHA,
    FOUNDATION_SHA,
    PROTECTED_MUTATION_KEYS,
    SOURCE_SHA,
    validate_phase_e_acceptance,
)


def _workflows(expected: dict) -> list[dict]:
    return [
        {
            "name": expected["dedicated_workflow"],
            "run_number": expected["dedicated_run"],
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        },
        {
            "name": "CI",
            "run_number": expected["ci_run"],
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        },
        {
            "name": "M17 Architecture Canon Acceptance",
            "run_number": expected["m17_run"],
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        },
        {
            "name": "M18 Graph v2 acceptance",
            "run_number": expected["m18_run"],
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        },
        {
            "name": "R2 Release Integration",
            "run_number": expected["r2_run"],
            "head_sha": expected["implementation_head"],
            "conclusion": "success",
        },
    ]


def _record(expected: dict) -> dict:
    return {
        "milestone": expected["milestone"],
        "issue": expected["issue"],
        "implementation_pr": expected["implementation_pr"],
        "reconciliation_pr": expected["reconciliation_pr"],
        "entry_base": expected["entry_base"],
        "implementation_head": expected["implementation_head"],
        "implementation_merge": expected["implementation_merge"],
        "reconciliation_head": expected["reconciliation_head"],
        "reconciliation_merge": expected["reconciliation_merge"],
        "issue_completed": True,
        "implementation_merged": True,
        "reconciliation_merged": True,
        "implementation_expected_head_merge": True,
        "reconciliation_expected_head_merge": True,
        "workflows": _workflows(expected),
    }


def _payload() -> dict:
    return {
        "schema_version": "knowledge-engine-m22-phase-e-evidence/v1",
        "engine_sha": FINAL_ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "milestones": [_record(item) for item in EXPECTED_MILESTONES],
        "capabilities": copy.deepcopy(EXPECTED_CAPABILITIES),
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def test_real_phase_e_chain_is_deterministic_and_non_mutating() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    first = validate_phase_e_acceptance(payload)
    second = validate_phase_e_acceptance(payload)
    assert first == second
    assert payload == before
    assert first["status"] == "accepted"
    assert first["phase_e_closed"] is True
    assert first["m18_m22_final_audit_required"] is True
    assert first["production_authority"] is False
    assert first["milestone_count"] == 6
    assert len(first["acceptance_sha256"]) == 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("engine_sha", "f" * 40, "Engine identity"),
        ("source_sha", "f" * 40, "release identity"),
        ("foundation_sha", "f" * 40, "release identity"),
    ],
)
def test_release_identity_is_exact(field: str, value: str, message: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_phase_e_acceptance(payload)


@pytest.mark.parametrize(
    "field",
    [
        "issue_completed",
        "implementation_merged",
        "reconciliation_merged",
        "implementation_expected_head_merge",
        "reconciliation_expected_head_merge",
    ],
)
def test_milestone_completion_flags_are_required(field: str) -> None:
    payload = _payload()
    payload["milestones"][2][field] = False
    with pytest.raises(IntegrityError, match="milestone state is incomplete"):
        validate_phase_e_acceptance(payload)


@pytest.mark.parametrize(
    "field",
    [
        "issue",
        "implementation_pr",
        "reconciliation_pr",
        "entry_base",
        "implementation_head",
        "implementation_merge",
        "reconciliation_head",
        "reconciliation_merge",
    ],
)
def test_exact_milestone_evidence_cannot_drift(field: str) -> None:
    payload = _payload()
    payload["milestones"][1][field] = (
        999 if isinstance(payload["milestones"][1][field], int) else "f" * 40
    )
    with pytest.raises(IntegrityError, match="milestone evidence mismatch"):
        validate_phase_e_acceptance(payload)


def test_milestone_order_and_count_are_exact() -> None:
    payload = _payload()
    payload["milestones"].reverse()
    with pytest.raises(IntegrityError, match="milestone evidence mismatch"):
        validate_phase_e_acceptance(payload)

    payload = _payload()
    payload["milestones"].pop()
    with pytest.raises(IntegrityError, match="six milestones"):
        validate_phase_e_acceptance(payload)


@pytest.mark.parametrize(
    ("index", "field", "value", "message"),
    [
        (0, "name", "wrong", "workflow identity"),
        (1, "run_number", 999, "workflow identity"),
        (2, "head_sha", "f" * 40, "not bound"),
        (3, "conclusion", "failure", "did not succeed"),
    ],
)
def test_workflow_evidence_is_exact(
    index: int,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload["milestones"][4]["workflows"][index][field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_phase_e_acceptance(payload)


def test_workflow_count_is_exact() -> None:
    payload = _payload()
    payload["milestones"][0]["workflows"].pop()
    with pytest.raises(IntegrityError, match="exactly five workflows"):
        validate_phase_e_acceptance(payload)


@pytest.mark.parametrize(
    ("capability", "value"),
    [
        ("bounded_plan", False),
        ("direct_path_preserved", False),
        ("graph_neural_retrieval", True),
        ("provider_call", True),
        ("traffic_change", True),
        ("rollout", True),
        ("production_authority", True),
    ],
)
def test_capability_boundary_fails_closed(capability: str, value: bool) -> None:
    payload = _payload()
    payload["capabilities"][capability] = value
    with pytest.raises(IntegrityError, match="capability boundary"):
        validate_phase_e_acceptance(payload)


def test_unknown_capability_fails_closed() -> None:
    payload = _payload()
    payload["capabilities"]["secret_executor"] = False
    with pytest.raises(IntegrityError, match="capability boundary"):
        validate_phase_e_acceptance(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation"):
            validate_phase_e_acceptance(payload)


def test_missing_protected_state_fails_closed() -> None:
    payload = _payload()
    payload["protected_state"].pop(PROTECTED_MUTATION_KEYS[0])
    with pytest.raises(IntegrityError, match="protected state is incomplete"):
        validate_phase_e_acceptance(payload)


def test_unknown_root_field_and_schema_drift_fail_closed() -> None:
    payload = _payload()
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        validate_phase_e_acceptance(payload)

    payload = _payload()
    payload["schema_version"] = "knowledge-engine-m22-phase-e-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported schema"):
        validate_phase_e_acceptance(payload)


def test_boolean_or_wrong_container_types_fail_closed() -> None:
    payload = _payload()
    payload["milestones"] = "not-a-list"
    with pytest.raises(IntegrityError, match="must be a list"):
        validate_phase_e_acceptance(payload)

    payload = _payload()
    payload["capabilities"] = []
    with pytest.raises(IntegrityError, match="must be an object"):
        validate_phase_e_acceptance(payload)
