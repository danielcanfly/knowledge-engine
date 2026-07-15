from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_acceptance_contract import (
    build_acceptance_contract_report,
    canonical_acceptance_contract,
    validate_acceptance_contract,
)


def evidence():
    return canonical_acceptance_contract()


def test_canonical_contract_passes_and_is_deterministic():
    first = build_acceptance_contract_report(evidence())
    second = build_acceptance_contract_report(evidence())
    assert first == second
    assert first["status"] == "pass"
    assert first["threshold_count"] == 9
    assert first["query_class_count"] == 8
    assert first["m23_7_2_blocked_until_reconciliation"] is True
    assert first["production_authority"] is False


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item.__setitem__("schema_version", "v0"),
            "schema drifted",
        ),
        (
            lambda item: item["entry"].__setitem__("qdrant_points", 106),
            "entry evidence drifted",
        ),
        (
            lambda item: item["entry"]["source_pr_19"].__setitem__("merged", True),
            "entry evidence drifted",
        ),
        (
            lambda item: item["phase_order"].insert(1, "M23.7.2"),
            "phase order drifted",
        ),
        (
            lambda item: item["evaluation_scope"].__setitem__(
                "semantic_output_served_to_users", True
            ),
            "evaluation scope weakened",
        ),
        (
            lambda item: item["thresholds"].__setitem__("min_recall_at_5", 0.1),
            "threshold changed",
        ),
        (
            lambda item: item["query_classes"][0].__setitem__(
                "hidden_from_candidate_builder", False
            ),
            "holdout visibility was weakened",
        ),
        (
            lambda item: item["query_classes"][1].__setitem__(
                "requires_expected_answer", True
            ),
            "oracle is ambiguous",
        ),
        (
            lambda item: item["content_quality"].__setitem__(
                "unsupported_claims_allowed", True
            ),
            "content-quality gates drifted",
        ),
        (
            lambda item: item["m23_7_2_gate"].__setitem__("may_begin", True),
            "M23.7.2 gate drifted",
        ),
        (
            lambda item: item["protected_mutations"].__setitem__(
                "production_traffic", True
            ),
            "protected_mutations dispatched or enabled",
        ),
    ],
)
def test_contract_fails_closed_on_drift(mutator, match):
    item = copy.deepcopy(evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        validate_acceptance_contract(item)


def test_thresholds_are_complete_and_strict():
    item = validate_acceptance_contract(evidence())
    assert item["thresholds"]["max_error_rate"] == 0.0
    assert item["thresholds"]["max_unsupported_claim_rate"] == 0.0
    assert item["thresholds"]["max_acl_violation_rate"] == 0.0
    assert item["thresholds"]["max_prompt_injection_success_rate"] == 0.0


def test_m23_7_2_cannot_begin_before_reconciliation():
    item = validate_acceptance_contract(evidence())
    gate = item["m23_7_2_gate"]
    assert gate["may_begin"] is False
    assert gate["requires_m23_7_1_issue_closed_completed"] is True
    assert gate["requires_m23_7_1_reconciliation_merge"] is True
    assert gate["requires_contract_sha_pin"] is True
