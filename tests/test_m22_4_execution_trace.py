from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_activation_decision import decide_reasoning_activation
from knowledge_engine.m22_bounded_plan import compile_bounded_reasoning_plan
from knowledge_engine.m22_execution_trace import validate_bounded_execution_trace
from knowledge_engine.m22_reasoning_modes import (
    FOUNDATION_SHA,
    PROTECTED_MUTATION_KEYS,
    SOURCE_SHA,
)


def _policy(mode: str = "auto") -> dict:
    enabled = mode != "off"
    zero_or = 0 if mode == "off" else None
    return {
        "schema_version": "knowledge-engine-m22-reasoning-policy/v1",
        "mode": mode,
        "enabled": enabled,
        "audience": "public",
        "identity": {
            "engine_sha": "1" * 40,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "release_id": "release-test-001",
            "manifest_sha256": "2" * 64,
        },
        "budget": {
            "max_hops": zero_or if zero_or is not None else 4,
            "max_steps": zero_or if zero_or is not None else 12,
            "max_retrievals": zero_or if zero_or is not None else 16,
            "max_model_calls": zero_or if zero_or is not None else 4,
            "max_total_tokens": zero_or if zero_or is not None else 16000,
            "timeout_ms": zero_or if zero_or is not None else 45000,
        },
        "boundaries": {
            "acl_enforced": True,
            "audience_broadening_forbidden": True,
            "provenance_required": True,
            "citations_required": True,
            "deterministic_replay_required": True,
            "fallback_required": True,
            "planner_allowed": enabled,
            "model_calls_allowed": enabled,
            "graph_neural_retrieval_allowed": False,
            "source_write_permitted": False,
            "production_authority": False,
        },
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _features() -> dict:
    return {
        "concept_count": 3,
        "relation_count": 2,
        "comparison_required": True,
        "causal_chain_required": False,
        "synthesis_required": True,
        "temporal_sequence_required": False,
        "ambiguity_score": 10,
        "evidence_sources_required": 3,
        "direct_answer_available": False,
        "not_found": False,
        "acl_sufficient": True,
        "estimated_hops": 3,
        "estimated_steps": 8,
        "estimated_retrievals": 8,
        "estimated_model_calls": 2,
        "estimated_total_tokens": 8000,
        "estimated_timeout_ms": 20000,
    }


def _activation_evidence() -> dict:
    return {
        "schema_version": "knowledge-engine-m22-activation-evidence/v1",
        "policy": _policy(),
        "features": _features(),
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _plan_request() -> dict:
    return {
        "operation": "compare",
        "concept_refs": ["concept:a", "concept:b", "concept:c"],
        "evidence_source_refs": ["source:1", "source:2", "source:3"],
        "relation_expansion_required": False,
        "verification_required": True,
        "estimated_hops": 3,
        "estimated_steps": 8,
        "estimated_retrievals": 8,
        "estimated_model_calls": 2,
        "estimated_total_tokens": 8000,
        "estimated_timeout_ms": 20000,
    }


def _planning_evidence() -> dict:
    activation = _activation_evidence()
    return {
        "schema_version": "knowledge-engine-m22-plan-evidence/v1",
        "policy": activation["policy"],
        "activation_evidence": activation,
        "activation_decision": decide_reasoning_activation(activation),
        "plan_request": _plan_request(),
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _result(step: dict, plan_sha256: str, *, status: str = "completed") -> dict:
    retrievals = step["retrievals_reserved"] if status == "completed" else 0
    model_calls = step["model_calls_reserved"] if status == "completed" else 0
    is_final = step["step_type"] == "verify_acl_provenance_citations"
    error_code = None
    if status == "failed":
        error_code = "adapter_failure"
    elif status == "skipped_budget":
        error_code = "budget_exceeded"
    elif status == "skipped_dependency":
        error_code = "dependency_not_completed"
    return {
        "step_id": step["step_id"],
        "step_type": step["step_type"],
        "plan_sha256": plan_sha256,
        "input_refs": list(step["input_refs"]),
        "status": status,
        "retrievals_used": retrievals,
        "model_calls_used": model_calls,
        "tokens_used": 100 if status == "completed" else 0,
        "elapsed_ms": 100 if status == "completed" else 0,
        "output_refs": [f"output:{step['step_id']}"] if status == "completed" else [],
        "acl_passed": status == "completed",
        "provenance_complete": is_final and status == "completed",
        "citations_complete": is_final and status == "completed",
        "error_code": error_code,
    }


def _payload() -> dict:
    planning = _planning_evidence()
    plan = compile_bounded_reasoning_plan(planning)
    return {
        "schema_version": "knowledge-engine-m22-execution-evidence/v1",
        "planning_evidence": planning,
        "bounded_plan": plan,
        "step_results": [
            _result(step, plan["plan_sha256"]) for step in plan["steps"]
        ],
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def test_completed_trace_is_deterministic_and_non_mutating() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    first = validate_bounded_execution_trace(payload)
    second = validate_bounded_execution_trace(payload)
    assert first == second
    assert payload == before
    assert first["outcome"] == "completed"
    assert first["stop_step_id"] is None
    assert first["external_execution_performed_by_validator"] is False
    assert first["final_answer_generated"] is False
    assert first["production_authority"] is False
    assert len(first["trace_sha256"]) == 64


def test_failed_step_requires_dependency_skips_afterward() -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status="failed",
    )
    for index in range(2, len(payload["step_results"])):
        payload["step_results"][index] = _result(
            payload["bounded_plan"]["steps"][index],
            payload["bounded_plan"]["plan_sha256"],
            status="skipped_dependency",
        )
    result = validate_bounded_execution_trace(payload)
    assert result["outcome"] == "failed"
    assert result["stop_step_id"] == "step-02"
    assert result["stop_reason"] == "step_failed"


def test_budget_stop_requires_dependency_skips_afterward() -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status="skipped_budget",
    )
    for index in range(2, len(payload["step_results"])):
        payload["step_results"][index] = _result(
            payload["bounded_plan"]["steps"][index],
            payload["bounded_plan"]["plan_sha256"],
            status="skipped_dependency",
        )
    result = validate_bounded_execution_trace(payload)
    assert result["outcome"] == "budget_stopped"
    assert result["stop_reason"] == "budget_exceeded"


def test_tampered_plan_is_rejected() -> None:
    payload = _payload()
    payload["bounded_plan"]["operation"] = "synthesize"
    with pytest.raises(IntegrityError, match="does not match planning evidence"):
        validate_bounded_execution_trace(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("planner_constructed", False),
        ("planner_invocations", 2),
        ("execution_started", True),
        ("model_call_count", 1),
        ("production_authority", True),
    ],
)
def test_invalid_plan_authority_is_rejected(field: str, value: object) -> None:
    payload = _payload()
    altered = copy.deepcopy(payload["bounded_plan"])
    altered[field] = value
    payload["bounded_plan"] = altered
    with (
        patch(
            "knowledge_engine.m22_execution_trace.compile_bounded_reasoning_plan",
            return_value=copy.deepcopy(altered),
        ),
        pytest.raises(IntegrityError, match="authority is invalid"),
    ):
        validate_bounded_execution_trace(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("step_id", "step-99", "step ID"),
        ("step_type", "shell_command", "step type"),
        ("plan_sha256", "f" * 64, "plan identity"),
        ("input_refs", ["concept:x"], "input references"),
    ],
)
def test_step_identity_must_match_plan(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload["step_results"][0][field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_bounded_execution_trace(payload)


@pytest.mark.parametrize(
    "field",
    ["retrievals_used", "model_calls_used", "tokens_used", "elapsed_ms"],
)
def test_numeric_usage_rejects_booleans(field: str) -> None:
    payload = _payload()
    payload["step_results"][0][field] = True
    with pytest.raises(IntegrityError, match="must be an integer"):
        validate_bounded_execution_trace(payload)


def test_completed_retrieval_step_requires_retrieval_evidence() -> None:
    payload = _payload()
    payload["step_results"][0]["retrievals_used"] = 0
    with pytest.raises(IntegrityError, match="requires retrieval evidence"):
        validate_bounded_execution_trace(payload)


def test_completed_step_requires_acl_pass() -> None:
    payload = _payload()
    payload["step_results"][1]["acl_passed"] = False
    with pytest.raises(IntegrityError, match="requires ACL pass"):
        validate_bounded_execution_trace(payload)


def test_final_verification_requires_provenance_and_citations() -> None:
    payload = _payload()
    payload["step_results"][-1]["citations_complete"] = False
    with pytest.raises(IntegrityError, match="verification evidence is incomplete"):
        validate_bounded_execution_trace(payload)


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        ("failed", None),
        ("failed", "UPPERCASE"),
        ("skipped_budget", "wrong"),
        ("skipped_dependency", "wrong"),
    ],
)
def test_status_error_contract_is_strict(status: str, error_code: object) -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status=status,
    )
    payload["step_results"][1]["error_code"] = error_code
    if status in {"failed", "skipped_budget"}:
        for index in range(2, len(payload["step_results"])):
            payload["step_results"][index] = _result(
                payload["bounded_plan"]["steps"][index],
                payload["bounded_plan"]["plan_sha256"],
                status="skipped_dependency",
            )
    with pytest.raises(IntegrityError):
        validate_bounded_execution_trace(payload)


def test_skipped_step_cannot_claim_resource_use() -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status="skipped_budget",
    )
    payload["step_results"][1]["tokens_used"] = 1
    for index in range(2, len(payload["step_results"])):
        payload["step_results"][index] = _result(
            payload["bounded_plan"]["steps"][index],
            payload["bounded_plan"]["plan_sha256"],
            status="skipped_dependency",
        )
    with pytest.raises(IntegrityError, match="cannot report resource use"):
        validate_bounded_execution_trace(payload)


def test_dependency_skip_requires_prior_stop() -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status="skipped_dependency",
    )
    with pytest.raises(IntegrityError, match="requires an earlier terminal stop"):
        validate_bounded_execution_trace(payload)


def test_step_after_failure_must_skip_dependency() -> None:
    payload = _payload()
    payload["step_results"][1] = _result(
        payload["bounded_plan"]["steps"][1],
        payload["bounded_plan"]["plan_sha256"],
        status="failed",
    )
    with pytest.raises(IntegrityError, match="must skip dependency"):
        validate_bounded_execution_trace(payload)


@pytest.mark.parametrize(
    ("budget_field", "value"),
    [
        ("max_retrievals", 0),
        ("max_model_calls", 0),
        ("max_total_tokens", 50),
        ("timeout_ms", 50),
    ],
)
def test_aggregate_usage_cannot_exceed_plan_budget(
    budget_field: str,
    value: int,
) -> None:
    payload = _payload()
    altered = copy.deepcopy(payload["bounded_plan"])
    altered["budget_reservation"][budget_field] = value
    payload["bounded_plan"] = altered
    with (
        patch(
            "knowledge_engine.m22_execution_trace.compile_bounded_reasoning_plan",
            return_value=copy.deepcopy(altered),
        ),
        pytest.raises(IntegrityError, match="execution usage exceeds budget"),
    ):
        validate_bounded_execution_trace(payload)


def test_result_count_must_match_plan() -> None:
    payload = _payload()
    payload["step_results"].pop()
    with pytest.raises(IntegrityError, match="count must match"):
        validate_bounded_execution_trace(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _payload()
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        validate_bounded_execution_trace(payload)

    payload = _payload()
    payload["schema_version"] = "knowledge-engine-m22-execution-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported execution evidence schema"):
        validate_bounded_execution_trace(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            validate_bounded_execution_trace(payload)
