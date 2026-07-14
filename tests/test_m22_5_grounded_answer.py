from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_activation_decision import decide_reasoning_activation
from knowledge_engine.m22_bounded_plan import compile_bounded_reasoning_plan
from knowledge_engine.m22_execution_trace import validate_bounded_execution_trace
from knowledge_engine.m22_grounded_answer import validate_grounded_answer_package
from knowledge_engine.m22_reasoning_modes import (
    FOUNDATION_SHA,
    PROTECTED_MUTATION_KEYS,
    SOURCE_SHA,
)


def _policy() -> dict:
    return {
        "schema_version": "knowledge-engine-m22-reasoning-policy/v1",
        "mode": "auto",
        "enabled": True,
        "audience": "public",
        "identity": {
            "engine_sha": "1" * 40,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "release_id": "release-test-001",
            "manifest_sha256": "2" * 64,
        },
        "budget": {
            "max_hops": 4,
            "max_steps": 12,
            "max_retrievals": 16,
            "max_model_calls": 4,
            "max_total_tokens": 16000,
            "timeout_ms": 45000,
        },
        "boundaries": {
            "acl_enforced": True,
            "audience_broadening_forbidden": True,
            "provenance_required": True,
            "citations_required": True,
            "deterministic_replay_required": True,
            "fallback_required": True,
            "planner_allowed": True,
            "model_calls_allowed": True,
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


def _step_result(step: dict, plan_sha256: str, *, status: str = "completed") -> dict:
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


def _execution_evidence(outcome: str = "completed") -> dict:
    planning = _planning_evidence()
    plan = compile_bounded_reasoning_plan(planning)
    results = [_step_result(step, plan["plan_sha256"]) for step in plan["steps"]]
    if outcome in {"failed", "budget_stopped"}:
        stop_status = "failed" if outcome == "failed" else "skipped_budget"
        results[1] = _step_result(
            plan["steps"][1],
            plan["plan_sha256"],
            status=stop_status,
        )
        for index in range(2, len(results)):
            results[index] = _step_result(
                plan["steps"][index],
                plan["plan_sha256"],
                status="skipped_dependency",
            )
    return {
        "schema_version": "knowledge-engine-m22-execution-evidence/v1",
        "planning_evidence": planning,
        "bounded_plan": plan,
        "step_results": results,
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _citation(index: int, evidence_ref: str) -> dict:
    return {
        "citation_id": f"citation-{index:02d}",
        "source_ref": f"source:{index}",
        "evidence_refs": [evidence_ref],
        "audience": "public",
        "acl_passed": True,
        "provenance_complete": True,
    }


def _claim(index: int, evidence_ref: str, citation_id: str) -> dict:
    return {
        "claim_id": f"claim-{index:02d}",
        "claim_sha256": f"{index}" * 64,
        "evidence_refs": [evidence_ref],
        "citation_ids": [citation_id],
        "acl_passed": True,
        "provenance_complete": True,
        "supported": True,
    }


def _answered_payload() -> dict:
    execution = _execution_evidence()
    trace = validate_bounded_execution_trace(execution)
    output_refs = [
        ref
        for result in trace["step_results"]
        for ref in result["output_refs"]
    ]
    return {
        "schema_version": "knowledge-engine-m22-answer-evidence/v1",
        "execution_evidence": execution,
        "execution_trace": trace,
        "answer_candidate": {
            "disposition": "answered",
            "audience": "public",
            "answer_sha256": "b" * 64,
            "claim_order": ["claim-01", "claim-02"],
            "claims": [
                _claim(1, output_refs[0], "citation-01"),
                _claim(2, output_refs[1], "citation-02"),
            ],
            "citations": [
                _citation(1, output_refs[0]),
                _citation(2, output_refs[1]),
            ],
            "fallback_reason": None,
        },
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _fallback_payload(outcome: str, reason: str) -> dict:
    execution = _execution_evidence(outcome)
    return {
        "schema_version": "knowledge-engine-m22-answer-evidence/v1",
        "execution_evidence": execution,
        "execution_trace": validate_bounded_execution_trace(execution),
        "answer_candidate": {
            "disposition": "fallback",
            "audience": "public",
            "answer_sha256": None,
            "claim_order": [],
            "claims": [],
            "citations": [],
            "fallback_reason": reason,
        },
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def test_answered_package_is_deterministic_and_non_mutating() -> None:
    payload = _answered_payload()
    before = copy.deepcopy(payload)
    first = validate_grounded_answer_package(payload)
    second = validate_grounded_answer_package(payload)
    assert first == second
    assert payload == before
    assert first["disposition"] == "answered"
    assert first["answer_evidence_validated"] is True
    assert first["answer_content_generated_by_validator"] is False
    assert first["provider_call_performed"] is False
    assert first["production_authority"] is False
    assert len(first["package_sha256"]) == 64


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("failed", "reasoning_failed"),
        ("budget_stopped", "budget_exceeded"),
        ("completed", "insufficient_evidence"),
        ("completed", "citation_incomplete"),
        ("completed", "acl_blocked"),
        ("completed", "not_found"),
        ("completed", "direct_answer_preserved"),
    ],
)
def test_governed_fallbacks(outcome: str, reason: str) -> None:
    result = validate_grounded_answer_package(_fallback_payload(outcome, reason))
    assert result["disposition"] == "fallback"
    assert result["fallback_reason"] == reason
    assert result["claims"] == []


def test_tampered_trace_is_rejected() -> None:
    payload = _answered_payload()
    payload["execution_trace"]["trace_sha256"] = "f" * 64
    with pytest.raises(IntegrityError, match="does not match execution evidence"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_evidence_validated", False),
        ("external_execution_performed_by_validator", True),
        ("final_answer_generated", True),
        ("production_authority", True),
    ],
)
def test_invalid_trace_authority_is_rejected(field: str, value: object) -> None:
    payload = _answered_payload()
    altered = copy.deepcopy(payload["execution_trace"])
    altered[field] = value
    payload["execution_trace"] = altered
    with (
        patch(
            "knowledge_engine.m22_grounded_answer.validate_bounded_execution_trace",
            return_value=copy.deepcopy(altered),
        ),
        pytest.raises(IntegrityError, match="authority is invalid"),
    ):
        validate_grounded_answer_package(payload)


def test_answered_requires_completed_trace() -> None:
    payload = _answered_payload()
    failed = _fallback_payload("failed", "reasoning_failed")
    payload["execution_evidence"] = failed["execution_evidence"]
    payload["execution_trace"] = failed["execution_trace"]
    with pytest.raises(IntegrityError, match="requires completed trace"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize("field", ["claims", "citations"])
def test_answered_requires_claims_and_citations(field: str) -> None:
    payload = _answered_payload()
    payload["answer_candidate"][field] = []
    with pytest.raises(IntegrityError, match="requires claims and citations"):
        validate_grounded_answer_package(payload)


def test_claim_evidence_must_come_from_trace() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["claims"][0]["evidence_refs"] = ["evidence:other"]
    with pytest.raises(IntegrityError, match="outside the trace"):
        validate_grounded_answer_package(payload)


def test_citation_evidence_must_come_from_trace() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["citations"][0]["evidence_refs"] = [
        "evidence:other"
    ]
    with pytest.raises(IntegrityError, match="outside the trace"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize(
    "field",
    ["acl_passed", "provenance_complete", "supported"],
)
def test_claim_grounding_must_be_complete(field: str) -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["claims"][0][field] = False
    with pytest.raises(IntegrityError, match="grounding is incomplete"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize("field", ["acl_passed", "provenance_complete"])
def test_citation_verification_must_be_complete(field: str) -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["citations"][0][field] = False
    with pytest.raises(IntegrityError, match="verification is incomplete"):
        validate_grounded_answer_package(payload)


def test_citation_audience_must_match_policy() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["citations"][0]["audience"] = "internal"
    with pytest.raises(IntegrityError, match="citation audience"):
        validate_grounded_answer_package(payload)


def test_answer_audience_must_match_policy() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["audience"] = "internal"
    with pytest.raises(IntegrityError, match="answer audience"):
        validate_grounded_answer_package(payload)


def test_unknown_citation_is_rejected() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["claims"][0]["citation_ids"] = ["citation-99"]
    with pytest.raises(IntegrityError, match="unknown citation"):
        validate_grounded_answer_package(payload)


def test_every_citation_must_support_a_claim() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["claims"][1]["citation_ids"] = ["citation-01"]
    with pytest.raises(IntegrityError, match="every citation"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("claim_order", ["claim-02", "claim-01"], "claim order"),
        ("answer_sha256", "BAD", "lowercase SHA-256"),
    ],
)
def test_answer_identity_and_order_are_strict(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _answered_payload()
    payload["answer_candidate"][field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_grounded_answer_package(payload)


def test_claim_ids_must_be_sequential() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["claims"][1]["claim_id"] = "claim-03"
    payload["answer_candidate"]["claim_order"][1] = "claim-03"
    with pytest.raises(IntegrityError, match="claim IDs must be sequential"):
        validate_grounded_answer_package(payload)


def test_citation_ids_must_be_sequential() -> None:
    payload = _answered_payload()
    payload["answer_candidate"]["citations"][1]["citation_id"] = "citation-03"
    payload["answer_candidate"]["claims"][1]["citation_ids"] = ["citation-03"]
    with pytest.raises(IntegrityError, match="citation IDs must be sequential"):
        validate_grounded_answer_package(payload)


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("failed", "budget_exceeded"),
        ("budget_stopped", "reasoning_failed"),
        ("completed", "reasoning_failed"),
        ("completed", "budget_exceeded"),
    ],
)
def test_fallback_reason_must_match_trace(outcome: str, reason: str) -> None:
    with pytest.raises(IntegrityError, match="fallback reason"):
        validate_grounded_answer_package(_fallback_payload(outcome, reason))


def test_fallback_cannot_contain_answer_material() -> None:
    payload = _fallback_payload("completed", "insufficient_evidence")
    payload["answer_candidate"]["answer_sha256"] = "b" * 64
    with pytest.raises(IntegrityError, match="cannot contain answer identity"):
        validate_grounded_answer_package(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _answered_payload()
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        validate_grounded_answer_package(payload)

    payload = _answered_payload()
    payload["schema_version"] = "knowledge-engine-m22-answer-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported answer evidence schema"):
        validate_grounded_answer_package(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _answered_payload()
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            validate_grounded_answer_package(payload)
