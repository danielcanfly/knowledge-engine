from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_2_offline_retrieval import (
    build_offline_retrieval_report,
    canonical_evaluation_payload,
    evaluate_offline_retrieval,
)


def evidence():
    return canonical_evaluation_payload()


def test_canonical_evaluation_passes_and_is_deterministic():
    first = build_offline_retrieval_report(evidence())
    second = build_offline_retrieval_report(evidence())
    assert first == second
    assert first["status"] == "pass"
    assert first["case_count"] == 64
    assert first["metrics"]["recall_at_5"] == 1.0
    assert first["metrics"]["mrr_at_10"] == 1.0
    assert first["metrics"]["ndcg_at_10"] == 1.0
    assert first["m23_7_3_blocked_until_reconciliation"] is True


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item.__setitem__("contract_sha256", "0" * 64),
            "contract SHA drifted",
        ),
        (
            lambda item: item["contract_report"].__setitem__(
                "contract_sha256", "1" * 64
            ),
            "contract report is not pinned",
        ),
        (
            lambda item: item["cases"].pop(),
            "exactly 64 cases",
        ),
        (
            lambda item: item["cases"][0].__setitem__(
                "hidden_from_candidate_builder", False
            ),
            "hidden holdout was exposed",
        ),
        (
            lambda item: item["cases"][0].__setitem__("ranked_docs", []),
            "positive case lacks retrieval",
        ),
        (
            lambda item: item["cases"][8].__setitem__(
                "ranked_docs", ["pilot/harness-theory-part-01#section-001"]
            ),
            "negative false positive retrieval",
        ),
        (
            lambda item: item["cases"][40].__setitem__("acl_leak", True),
            "forbidden case outcome: acl_leak",
        ),
        (
            lambda item: item["cases"][32].__setitem__(
                "stale_source_accepted", True
            ),
            "forbidden case outcome: stale_source_accepted",
        ),
        (
            lambda item: item["cases"][48].__setitem__(
                "prompt_injection_succeeded", True
            ),
            "forbidden case outcome: prompt_injection_succeeded",
        ),
        (
            lambda item: item.__setitem__("production_retrieval_authority", "semantic"),
            "lexical authority was weakened",
        ),
        (
            lambda item: item.__setitem__("semantic_output_served_to_users", True),
            "semantic output was served",
        ),
        (
            lambda item: item["m23_7_3_gate"].__setitem__("may_begin", True),
            "M23.7.3 gate drifted",
        ),
        (
            lambda item: item["protected_mutations"].__setitem__(
                "source_pr_19_merge", True
            ),
            "protected_mutations dispatched or enabled",
        ),
    ],
)
def test_offline_evaluation_fails_closed(mutator, match):
    item = copy.deepcopy(evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        evaluate_offline_retrieval(item)


def test_class_partitions_are_hidden_and_complete():
    result = evaluate_offline_retrieval(evidence())
    assert set(result["class_counts"].values()) == {8}
    assert len(result["class_counts"]) == 8


def test_strict_zero_security_and_quality_rates():
    result = evaluate_offline_retrieval(evidence())
    assert result["metrics"]["error_rate"] == 0.0
    assert result["metrics"]["unsupported_claim_rate"] == 0.0
    assert result["metrics"]["acl_violation_rate"] == 0.0
    assert result["metrics"]["stale_acceptance_rate"] == 0.0
    assert result["metrics"]["prompt_injection_success_rate"] == 0.0
    assert result["protected_mutations"]["graph_neural_retrieval"] is False
