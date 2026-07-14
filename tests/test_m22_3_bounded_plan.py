from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_activation_decision import decide_reasoning_activation
from knowledge_engine.m22_bounded_plan import (
    PLAN_OPERATIONS,
    STEP_TYPES,
    compile_bounded_reasoning_plan,
)
from knowledge_engine.m22_reasoning_modes import PROTECTED_MUTATION_KEYS


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
            "source_sha": "a6ba738d910d01d2ae99b1968f0831989934c549",
            "foundation_sha": "e5ef644053d34e89c70d2ceb37521e1c59234832",
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


def _activation_evidence(mode: str = "auto") -> dict:
    return {
        "schema_version": "knowledge-engine-m22-activation-evidence/v1",
        "policy": _policy(mode),
        "features": _features(),
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _request(operation: str = "compare") -> dict:
    relation = operation in {"causal_chain", "temporal_sequence"}
    return {
        "operation": operation,
        "concept_refs": ["concept:a", "concept:b", "concept:c"],
        "evidence_source_refs": ["source:1", "source:2", "source:3"],
        "relation_expansion_required": relation,
        "verification_required": True,
        "estimated_hops": 3,
        "estimated_steps": 8,
        "estimated_retrievals": 8,
        "estimated_model_calls": 2,
        "estimated_total_tokens": 8000,
        "estimated_timeout_ms": 20000,
    }


def _payload(operation: str = "compare", mode: str = "auto") -> dict:
    activation = _activation_evidence(mode)
    return {
        "schema_version": "knowledge-engine-m22-plan-evidence/v1",
        "policy": activation["policy"],
        "activation_evidence": activation,
        "activation_decision": decide_reasoning_activation(activation),
        "plan_request": _request(operation),
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def test_compare_plan_is_deterministic_bounded_and_non_executing() -> None:
    payload = _payload()
    before = copy.deepcopy(payload)
    first = compile_bounded_reasoning_plan(payload)
    second = compile_bounded_reasoning_plan(payload)
    assert first == second
    assert payload == before
    assert first["operation"] == "compare"
    assert first["planner_constructed"] is True
    assert first["planner_invocations"] == 1
    assert first["execution_started"] is False
    assert first["model_call_count"] == 0
    assert first["production_authority"] is False
    assert first["steps"][-1]["step_type"] == "verify_acl_provenance_citations"
    assert len(first["plan_sha256"]) == 64


@pytest.mark.parametrize("operation", PLAN_OPERATIONS)
def test_all_governed_operations_compile(operation: str) -> None:
    result = compile_bounded_reasoning_plan(_payload(operation))
    assert result["operation"] == operation
    assert all(step["step_type"] in STEP_TYPES for step in result["steps"])
    assert result["steps"][-1]["step_type"] == "verify_acl_provenance_citations"


def test_plan_dependencies_are_linear_forward_safe() -> None:
    result = compile_bounded_reasoning_plan(_payload("causal_chain"))
    seen = set()
    for step in result["steps"]:
        assert set(step["depends_on"]).issubset(seen)
        seen.add(step["step_id"])


def test_tampered_activation_decision_is_rejected() -> None:
    payload = _payload()
    payload["activation_decision"]["score"] += 1
    with pytest.raises(IntegrityError, match="does not match evidence"):
        compile_bounded_reasoning_plan(payload)


def test_direct_only_activation_is_rejected() -> None:
    payload = _payload()
    payload["activation_evidence"]["features"]["estimated_hops"] = 1
    payload["activation_decision"] = decide_reasoning_activation(
        payload["activation_evidence"]
    )
    payload["plan_request"]["estimated_hops"] = 2
    with pytest.raises(IntegrityError, match="does not permit planning"):
        compile_bounded_reasoning_plan(payload)


def test_off_mode_cannot_construct_plan() -> None:
    payload = _payload(mode="off")
    with pytest.raises(IntegrityError, match="off mode cannot construct"):
        compile_bounded_reasoning_plan(payload)


def test_policy_mismatch_is_rejected() -> None:
    payload = _payload()
    payload["policy"] = copy.deepcopy(payload["policy"])
    payload["policy"]["identity"]["release_id"] = "other-release"
    with pytest.raises(IntegrityError, match="policy mismatch"):
        compile_bounded_reasoning_plan(payload)


@pytest.mark.parametrize(
    "field",
    [
        "estimated_hops",
        "estimated_steps",
        "estimated_retrievals",
        "estimated_model_calls",
        "estimated_total_tokens",
        "estimated_timeout_ms",
    ],
)
def test_plan_may_not_exceed_activation_estimate(field: str) -> None:
    payload = _payload()
    payload["activation_evidence"]["features"][field] = max(
        0, payload["plan_request"][field] - 1
    )
    payload["activation_decision"] = decide_reasoning_activation(
        payload["activation_evidence"]
    )
    with pytest.raises(IntegrityError, match="exceeds activation estimate"):
        compile_bounded_reasoning_plan(payload)


def test_plan_may_not_exceed_policy_budget() -> None:
    payload = _payload()
    payload["policy"]["budget"]["max_total_tokens"] = 7000
    payload["activation_evidence"]["policy"]["budget"]["max_total_tokens"] = 7000
    payload["activation_decision"] = decide_reasoning_activation(
        payload["activation_evidence"]
    )
    with pytest.raises(IntegrityError, match="exceeds policy budget"):
        compile_bounded_reasoning_plan(payload)


def test_compiled_step_count_must_fit_estimate() -> None:
    payload = _payload("causal_chain")
    payload["plan_request"]["estimated_steps"] = 4
    with pytest.raises(IntegrityError, match="step count exceeds estimate"):
        compile_bounded_reasoning_plan(payload)


def test_compiled_retrievals_must_fit_estimate() -> None:
    payload = _payload("causal_chain")
    payload["plan_request"]["estimated_hops"] = 2
    payload["plan_request"]["estimated_retrievals"] = 2
    with pytest.raises(IntegrityError, match="retrieval reservation exceeds estimate"):
        compile_bounded_reasoning_plan(payload)


def test_verification_cannot_be_disabled() -> None:
    payload = _payload()
    payload["plan_request"]["verification_required"] = False
    with pytest.raises(IntegrityError, match="verification cannot be disabled"):
        compile_bounded_reasoning_plan(payload)


@pytest.mark.parametrize("operation", ["causal_chain", "temporal_sequence"])
def test_chain_operations_require_relation_expansion(operation: str) -> None:
    payload = _payload(operation)
    payload["plan_request"]["relation_expansion_required"] = False
    with pytest.raises(IntegrityError, match="requires relation expansion"):
        compile_bounded_reasoning_plan(payload)


def test_compare_requires_at_least_two_concept_refs() -> None:
    payload = _payload("compare")
    payload["plan_request"]["concept_refs"] = ["concept:a"]
    with pytest.raises(IntegrityError, match="count is outside"):
        compile_bounded_reasoning_plan(payload)


@pytest.mark.parametrize("field", ["concept_refs", "evidence_source_refs"])
def test_duplicate_refs_are_rejected(field: str) -> None:
    payload = _payload()
    payload["plan_request"][field] = ["same:ref", "same:ref"]
    with pytest.raises(IntegrityError, match="duplicates"):
        compile_bounded_reasoning_plan(payload)


def test_invalid_reference_is_rejected() -> None:
    payload = _payload()
    payload["plan_request"]["concept_refs"] = ["../../secret", "concept:b"]
    with pytest.raises(IntegrityError, match="invalid reference"):
        compile_bounded_reasoning_plan(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _payload()
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        compile_bounded_reasoning_plan(payload)

    payload = _payload()
    payload["schema_version"] = "knowledge-engine-m22-plan-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported planning evidence schema"):
        compile_bounded_reasoning_plan(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            compile_bounded_reasoning_plan(payload)
