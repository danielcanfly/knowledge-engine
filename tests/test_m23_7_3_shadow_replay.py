from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_3_shadow_replay import (
    build_shadow_replay_report,
    canonical_shadow_replay_payload,
    evaluate_shadow_replay,
)


def evidence():
    return canonical_shadow_replay_payload()


def test_canonical_shadow_replay_passes_and_is_deterministic():
    first = build_shadow_replay_report(evidence())
    second = build_shadow_replay_report(evidence())
    assert first == second
    assert first["status"] == "pass"
    assert first["case_count"] == 64
    assert set(first["class_counts"].values()) == {8}
    assert first["metrics"]["candidate_recall_at_5"] == 1.0
    assert first["metrics"]["candidate_mrr_at_10"] == 1.0
    assert first["metrics"]["candidate_ndcg_at_10"] == 1.0
    assert first["metrics"]["positive_mean_overlap_at_5"] == pytest.approx(0.8)
    assert first["metrics"]["failure_isolation_success_rate"] == 1.0
    assert first["production_retrieval_authority"] == "lexical"
    assert first["candidate_outputs_discarded"] is True
    assert first["semantic_output_influenced"] is False
    assert first["protected_mutations_dispatched"] is False


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item["entry"].__setitem__("contract_sha256", "0" * 64),
            "entry identity drifted",
        ),
        (
            lambda item: item["entry"].__setitem__(
                "offline_evaluation_sha256", "1" * 64
            ),
            "entry identity drifted",
        ),
        (
            lambda item: item["entry"]["m23_7_2_issue"].__setitem__(
                "state_reason", "not_planned"
            ),
            "entry identity drifted",
        ),
        (
            lambda item: item.__setitem__("replay_seed", "drifted"),
            "replay seed drifted",
        ),
        (
            lambda item: item["cases"].pop(),
            "exactly 64 replay cases",
        ),
        (
            lambda item: item["cases"][8].__setitem__(
                "class", "known-answer-positive"
            ),
            "query digest drifted",
        ),
        (
            lambda item: item["cases"][0]["candidate"].__setitem__(
                "filter_order", ["rank", "acl"]
            ),
            "candidate filter order drifted",
        ),
        (
            lambda item: item["cases"][40]["candidate"].__setitem__(
                "ranked_section_ids", item["cases"][40]["candidate"]["candidate_pool_ids"]
            ),
            "candidate ranking bypassed safety filters",
        ),
        (
            lambda item: item["cases"][0].__setitem__(
                "authoritative_result_ids",
                item["cases"][0]["candidate"]["ranked_section_ids"],
            ),
            "lexical output is not authoritative",
        ),
        (
            lambda item: item["cases"][0].__setitem__(
                "candidate_output_discarded", False
            ),
            "candidate output was retained",
        ),
        (
            lambda item: item["cases"][0].__setitem__(
                "semantic_output_influenced", True
            ),
            "semantic output influenced authority",
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
            lambda item: item["privacy"].__setitem__("raw_query_persisted", True),
            "privacy boundary drifted",
        ),
        (
            lambda item: item["output_authority"].__setitem__(
                "authoritative_method", "semantic-vector"
            ),
            "output authority drifted",
        ),
        (
            lambda item: item["failure_probes"][0].__setitem__(
                "lexical_primary_continued", False
            ),
            "candidate failure stopped lexical primary",
        ),
        (
            lambda item: item["protected_mutations"].__setitem__(
                "production_retrieval", True
            ),
            "protected mutations dispatched or enabled",
        ),
    ],
)
def test_shadow_replay_fails_closed(mutator, match):
    item = copy.deepcopy(evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        evaluate_shadow_replay(item)


def test_acl_freshness_and_injection_filters_run_before_ranking():
    result = evaluate_shadow_replay(evidence())
    for case in result["cases"]:
        candidate = case["candidate"]
        assert set(candidate["ranked_section_ids"]).issubset(candidate["safe_ids"])
        assert set(candidate["safe_ids"]).issubset(candidate["fresh_ids"])
        assert set(candidate["fresh_ids"]).issubset(candidate["acl_allowed_ids"])
        assert set(candidate["acl_allowed_ids"]).issubset(
            candidate["candidate_pool_ids"]
        )


def test_comparison_reports_rank_and_result_set_deltas():
    result = evaluate_shadow_replay(evidence())
    positive = [
        comparison
        for comparison in result["comparisons"]
        if comparison["class"] in {"known-answer-positive", "bilingual-zh-en"}
    ]
    assert all(item["overlap_at_5"] == 0.8 for item in positive)
    assert all(len(item["lexical_only_ids"]) == 1 for item in positive)
    assert all(len(item["semantic_only_ids"]) == 1 for item in positive)
    assert all(item["output_authority"] == "lexical" for item in positive)
