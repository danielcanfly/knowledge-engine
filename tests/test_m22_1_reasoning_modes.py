from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_reasoning_modes import (
    FOUNDATION_SHA,
    PROTECTED_MUTATION_KEYS,
    SOURCE_SHA,
    evaluate_reasoning_gate,
    validate_reasoning_mode_policy,
)

ENGINE_SHA = "1" * 40
MANIFEST_SHA = "2" * 64


def _payload(mode: str = "off") -> dict:
    enabled = mode != "off"
    zero_or_one = 0 if mode == "off" else 1
    return {
        "schema_version": "knowledge-engine-m22-reasoning-policy/v1",
        "mode": mode,
        "enabled": enabled,
        "audience": "public",
        "identity": {
            "engine_sha": ENGINE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "release_id": "release-test-001",
            "manifest_sha256": MANIFEST_SHA,
        },
        "budget": {
            "max_hops": zero_or_one,
            "max_steps": zero_or_one,
            "max_retrievals": zero_or_one,
            "max_model_calls": zero_or_one,
            "max_total_tokens": zero_or_one,
            "timeout_ms": zero_or_one,
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


def test_off_mode_is_deterministic_and_disables_reasoning() -> None:
    first = validate_reasoning_mode_policy(_payload())
    second = validate_reasoning_mode_policy(_payload())

    assert first == second
    assert first["mode"] == "off"
    assert first["enabled"] is False
    assert first["planner_construction_permitted"] is False
    assert first["model_calls_permitted"] is False
    assert first["activation_decision_required"] is False
    assert first["production_authority"] is False


@pytest.mark.parametrize("mode", ["auto", "force"])
def test_enabled_modes_are_bounded_without_constructing_a_planner(mode: str) -> None:
    payload = _payload(mode)
    payload["budget"].update(
        {
            "max_hops": 3,
            "max_steps": 8,
            "max_retrievals": 10,
            "max_model_calls": 2,
            "max_total_tokens": 8000,
            "timeout_ms": 30000,
        }
    )

    report = validate_reasoning_mode_policy(payload)
    gate = evaluate_reasoning_gate(payload)

    assert report["planner_construction_permitted"] is True
    assert report["model_calls_permitted"] is True
    assert gate["planner_constructed"] is False
    assert gate["planner_invocations"] == 0
    assert gate["model_call_count"] == 0
    assert gate["disposition"] == (
        "await_activation_decision" if mode == "auto" else "planner_required"
    )


@pytest.mark.parametrize("field", ["enabled"])
def test_off_mode_rejects_conflicting_enablement(field: str) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(IntegrityError, match="enabled flag conflicts"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize("field", ["planner_allowed", "model_calls_allowed"])
def test_off_mode_rejects_executor_permission(field: str) -> None:
    payload = _payload()
    payload["boundaries"][field] = True
    with pytest.raises(IntegrityError, match="permission conflicts"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize(
    "field",
    [
        "max_hops",
        "max_steps",
        "max_retrievals",
        "max_model_calls",
        "max_total_tokens",
        "timeout_ms",
    ],
)
def test_off_mode_requires_zero_budget(field: str) -> None:
    payload = _payload()
    payload["budget"][field] = 1
    with pytest.raises(IntegrityError, match="zero execution budget"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_hops", 5, "between"),
        ("max_steps", 13, "between"),
        ("max_retrievals", 17, "between"),
        ("max_model_calls", 5, "between"),
        ("max_total_tokens", 16001, "between"),
        ("timeout_ms", 45001, "between"),
    ],
)
def test_enabled_modes_reject_unbounded_budget(
    field: str,
    value: int,
    message: str,
) -> None:
    payload = _payload("force")
    payload["budget"][field] = value
    with pytest.raises(IntegrityError, match=message):
        validate_reasoning_mode_policy(payload)


def test_budget_rejects_bool_and_inconsistent_step_counts() -> None:
    payload = _payload("auto")
    payload["budget"]["max_hops"] = True
    with pytest.raises(IntegrityError, match="must be an integer"):
        validate_reasoning_mode_policy(payload)

    payload = _payload("auto")
    payload["budget"]["max_hops"] = 3
    payload["budget"]["max_steps"] = 2
    with pytest.raises(IntegrityError, match="at least max_hops"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize("field", ["source_sha", "foundation_sha"])
def test_release_identity_is_pinned(field: str) -> None:
    payload = _payload()
    payload["identity"][field] = "f" * 40
    with pytest.raises(IntegrityError, match="release identity mismatch"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize(
    "field",
    [
        "acl_enforced",
        "audience_broadening_forbidden",
        "provenance_required",
        "citations_required",
        "deterministic_replay_required",
        "fallback_required",
    ],
)
def test_required_safety_boundaries_fail_closed(field: str) -> None:
    payload = _payload()
    payload["boundaries"][field] = False
    with pytest.raises(IntegrityError, match="required safety boundary is false"):
        validate_reasoning_mode_policy(payload)


@pytest.mark.parametrize(
    "field",
    [
        "graph_neural_retrieval_allowed",
        "source_write_permitted",
        "production_authority",
    ],
)
def test_forbidden_authority_cannot_be_granted(field: str) -> None:
    payload = _payload()
    payload["boundaries"][field] = True
    with pytest.raises(IntegrityError, match="forbidden authority was granted"):
        validate_reasoning_mode_policy(payload)


def test_any_protected_mutation_fails_closed() -> None:
    for field in PROTECTED_MUTATION_KEYS:
        payload = _payload()
        payload["protected_state"][field] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            validate_reasoning_mode_policy(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    payload = _payload()
    payload["provider_api_key"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        validate_reasoning_mode_policy(payload)

    payload = _payload()
    payload["schema_version"] = "knowledge-engine-m22-reasoning-policy/v2"
    with pytest.raises(IntegrityError, match="unsupported reasoning policy schema"):
        validate_reasoning_mode_policy(payload)


def test_invalid_mode_audience_and_identity_fail_closed() -> None:
    payload = _payload()
    payload["mode"] = "smart"
    with pytest.raises(IntegrityError, match="off, auto, or force"):
        validate_reasoning_mode_policy(payload)

    payload = _payload()
    payload["audience"] = "everyone"
    with pytest.raises(IntegrityError, match="audience is invalid"):
        validate_reasoning_mode_policy(payload)

    payload = _payload()
    payload["identity"]["engine_sha"] = "NOT-A-SHA"
    with pytest.raises(IntegrityError, match="40-character commit SHA"):
        validate_reasoning_mode_policy(payload)


def test_policy_hash_changes_when_release_or_audience_changes() -> None:
    first = validate_reasoning_mode_policy(_payload())

    changed = _payload()
    changed["identity"]["release_id"] = "release-test-002"
    second = validate_reasoning_mode_policy(changed)

    audience = _payload()
    audience["audience"] = "internal"
    third = validate_reasoning_mode_policy(audience)

    assert len({first["policy_sha256"], second["policy_sha256"], third["policy_sha256"]}) == 3


def test_input_is_not_mutated() -> None:
    payload = _payload("force")
    before = copy.deepcopy(payload)
    validate_reasoning_mode_policy(payload)
    assert payload == before
