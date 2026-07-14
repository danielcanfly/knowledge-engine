from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_activation_decision import (
    ACTIVATION_THRESHOLD,
    decide_reasoning_activation,
)
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
        "protected_state": {
            name: False for name in PROTECTED_MUTATION_KEYS
        },
    }


def _features() -> dict:
    return {
        "concept_count": 1,
        "relation_count": 0,
        "comparison_required": False,
        "causal_chain_required": False,
        "synthesis_required": False,
        "temporal_sequence_required": False,
        "ambiguity_score": 0,
        "evidence_sources_required": 1,
        "direct_answer_available": True,
        "not_found": False,
        "acl_sufficient": True,
        "estimated_hops": 1,
        "estimated_steps": 1,
        "estimated_retrievals": 1,
        "estimated_model_calls": 1,
        "estimated_total_tokens": 1000,
        "estimated_timeout_ms": 1000,
    }


def _payload(mode: str = "auto") -> dict:
    features = _features()
    if mode == "off":
        for field in (
            "estimated_hops",
            "estimated_steps",
            "estimated_retrievals",
            "estimated_model_calls",
            "estimated_total_tokens",
            "estimated_timeout_ms",
        ):
            features[field] = 0
    return {
        "schema_version": "knowledge-engine-m22-activation-evidence/v1",
        "policy": _policy(mode),
        "features": features,
        "protected_state": {
            name: False for name in PROTECTED_MUTATION_KEYS
        },
    }


def test_off_mode_is_always_direct_and_non_executing() -> None:
    result = decide_reasoning_activation(_payload("off"))
    assert result["disposition"] == "direct_only"
    assert result["reason_codes"] == ["mode_off"]
    assert result["planner_constructed"] is False
    assert result["planner_invocations"] == 0
    assert result["model_call_count"] == 0
    assert result["production_authority"] is False


def test_force_mode_activates_when_safe_and_within_budget() -> None:
    result = decide_reasoning_activation(_payload("force"))
    assert result["disposition"] == "activate"
    assert result["reason_codes"] == ["mode_force"]


def test_auto_simple_direct_fact_stays_direct() -> None:
    result = decide_reasoning_activation(_payload("auto"))
    assert result["disposition"] == "direct_only"
    assert "below_activation_threshold" in result["reason_codes"]


def test_auto_multi_hop_comparison_activates() -> None:
    payload = _payload("auto")
    payload["features"].update(
        {
            "concept_count": 3,
            "relation_count": 2,
            "comparison_required": True,
            "synthesis_required": True,
            "evidence_sources_required": 3,
            "direct_answer_available": False,
            "estimated_hops": 3,
            "estimated_steps": 7,
            "estimated_retrievals": 8,
            "estimated_model_calls": 2,
            "estimated_total_tokens": 7000,
            "estimated_timeout_ms": 20000,
        }
    )
    result = decide_reasoning_activation(payload)
    assert result["disposition"] == "activate"
    assert result["score"] >= ACTIVATION_THRESHOLD
    assert "multi_hop_estimate" in result["reason_codes"]


def test_auto_requires_multi_hop_even_when_score_is_high() -> None:
    payload = _payload("auto")
    payload["features"].update(
        {
            "concept_count": 4,
            "relation_count": 3,
            "comparison_required": True,
            "synthesis_required": True,
            "direct_answer_available": False,
            "estimated_hops": 1,
        }
    )
    result = decide_reasoning_activation(payload)
    assert result["disposition"] == "direct_only"


def test_acl_insufficient_blocks_every_mode() -> None:
    for mode in ("off", "auto", "force"):
        payload = _payload(mode)
        payload["features"]["acl_sufficient"] = False
        result = decide_reasoning_activation(payload)
        assert result["disposition"] == "blocked"
        assert result["reason_codes"] == ["acl_insufficient"]


def test_not_found_never_activates() -> None:
    payload = _payload("force")
    payload["features"]["not_found"] = True
    payload["features"]["direct_answer_available"] = False
    result = decide_reasoning_activation(payload)
    assert result["disposition"] == "direct_only"
    assert result["reason_codes"] == ["not_found"]


def test_budget_exceeded_blocks_force_and_auto() -> None:
    for mode in ("auto", "force"):
        payload = _payload(mode)
        payload["policy"]["budget"]["max_total_tokens"] = 500
        result = decide_reasoning_activation(payload)
        assert result["disposition"] == "blocked"
        assert result["reason_codes"] == ["budget_exceeded"]


def test_deterministic_hashes_and_no_input_mutation() -> None:
    payload = _payload("auto")
    before = copy.deepcopy(payload)
    first = decide_reasoning_activation(payload)
    second = decide_reasoning_activation(payload)
    assert first == second
    assert payload == before
    assert len(first["features_sha256"]) == 64
    assert len(first["decision_sha256"]) == 64


def test_feature_change_changes_decision_identity() -> None:
    first = decide_reasoning_activation(_payload("auto"))
    changed = _payload("auto")
    changed["features"]["ambiguity_score"] = 40
    second = decide_reasoning_activation(changed)
    assert first["features_sha256"] != second["features_sha256"]
    assert first["decision_sha256"] != second["decision_sha256"]


@pytest.mark.parametrize(
    "field",
    [
        "concept_count",
        "relation_count",
        "ambiguity_score",
        "evidence_sources_required",
        "estimated_hops",
        "estimated_steps",
        "estimated_retrievals",
        "estimated_model_calls",
        "estimated_total_tokens",
        "estimated_timeout_ms",
    ],
)
def test_numeric_features_reject_booleans(field: str) -> None:
    payload = _payload("auto")
    payload["features"][field] = True
    with pytest.raises(IntegrityError, match="must be an integer"):
        decide_reasoning_activation(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("concept_count", 17),
        ("relation_count", 33),
        ("ambiguity_score", 101),
        ("evidence_sources_required", 17),
        ("estimated_hops", 5),
        ("estimated_steps", 13),
        ("estimated_retrievals", 17),
        ("estimated_model_calls", 5),
        ("estimated_total_tokens", 16001),
        ("estimated_timeout_ms", 45001),
    ],
)
def test_feature_bounds_fail_closed(field: str, value: int) -> None:
    payload = _payload("auto")
    payload["features"][field] = value
    with pytest.raises(IntegrityError, match="outside the governed bound"):
        decide_reasoning_activation(payload)


def test_inconsistent_feature_evidence_fails_closed() -> None:
    payload = _payload("auto")
    payload["features"]["not_found"] = True
    with pytest.raises(IntegrityError, match="conflicts"):
        decide_reasoning_activation(payload)

    payload = _payload("auto")
    payload["features"]["estimated_hops"] = 3
    payload["features"]["estimated_steps"] = 2
    with pytest.raises(IntegrityError, match="at least estimated_hops"):
        decide_reasoning_activation(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _payload("auto")
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        decide_reasoning_activation(payload)

    payload = _payload("auto")
    payload["schema_version"] = (
        "knowledge-engine-m22-activation-evidence/v2"
    )
    with pytest.raises(
        IntegrityError,
        match="unsupported activation evidence schema",
    ):
        decide_reasoning_activation(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload("auto")
        payload["protected_state"][name] = True
        with pytest.raises(
            IntegrityError,
            match="protected mutation was dispatched",
        ):
            decide_reasoning_activation(payload)
