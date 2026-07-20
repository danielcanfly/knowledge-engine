from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_query_answer_acceptance import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    P5_ISSUE_NUMBER,
    build_p5_query_answer_acceptance_report,
    m24_p5_cases,
)

EVIDENCE_PATH = Path(
    "pilot/m24/query-answer-acceptance/m24-p5-query-answer-acceptance.json"
)


def _evidence() -> dict:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_m24_p5_evidence_is_digest_bound() -> None:
    evidence = _evidence()
    unsigned = dict(evidence)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p5_freezes_all_required_query_classes() -> None:
    cases = m24_p5_cases()

    assert len(cases) == 11
    assert {case.query_class for case in cases} == {
        "direct_fact",
        "terminology",
        "relationship",
        "comparison",
        "cross_language",
        "provenance",
        "acl_negative",
        "no_answer",
        "stale_source",
        "prompt_injection",
        "contradiction",
    }
    assert len({case.case_id for case in cases}) == len(cases)
    assert all(case.safe_fallback for case in cases)


def test_m24_p5_acceptance_report_matches_committed_evidence() -> None:
    report = build_p5_query_answer_acceptance_report()

    assert report.model_dump(mode="json") == _evidence()
    assert report.issue_number == P5_ISSUE_NUMBER
    assert report.release_id == CANONICAL_RELEASE_ID
    assert report.manifest_sha256 == CANONICAL_MANIFEST_SHA256
    assert report.status == "query_answer_acceptance_complete"
    assert report.failure_reasons == []
    assert report.readiness == {
        "query_readiness": "Q2-offline-internal-acceptance",
        "answer_readiness": "A4-offline-internal-answer-candidate",
        "internal_deployment": "pending_P6",
        "production_semantic_or_hybrid": "blocked_pending_semantic_promotion_decision",
    }


def test_m24_p5_metrics_pass_frozen_acceptance_policy() -> None:
    report = build_p5_query_answer_acceptance_report()

    assert report.metrics.case_count == 11
    assert report.metrics.passed_count == 11
    assert report.metrics.recall_at_5 >= report.policy.min_recall_at_5
    assert report.metrics.mrr_at_10 >= report.policy.min_mrr_at_10
    assert report.metrics.ndcg_at_10 >= report.policy.min_ndcg_at_10
    assert report.metrics.groundedness >= report.policy.min_groundedness
    assert report.metrics.citation_coverage >= report.policy.min_citation_coverage
    assert report.metrics.citation_mismatch_rate <= report.policy.max_citation_mismatch_rate
    assert (
        report.metrics.no_answer_false_positive_rate
        <= report.policy.max_no_answer_false_positive_rate
    )
    assert report.metrics.acl_leakage_count <= report.policy.max_acl_leakage_count
    assert report.metrics.p50_latency_ms <= report.policy.max_p50_latency_ms
    assert report.metrics.p95_latency_ms <= report.policy.max_p95_latency_ms
    assert report.metrics.cost_per_query_usd <= report.policy.max_cost_per_query_usd
    assert report.metrics.deterministic_replay is True


def test_m24_p5_negative_and_adversarial_cases_have_safe_fallbacks() -> None:
    report = build_p5_query_answer_acceptance_report()
    by_class = {case.query_class: case for case in report.cases}

    assert by_class["acl_negative"].forbidden_concepts_returned == []
    assert by_class["acl_negative"].acl_leakage is False
    assert by_class["no_answer"].response_status == "not_found"
    assert by_class["no_answer"].no_answer_false_positive is False
    assert by_class["prompt_injection"].prompt_injection_blocked is True
    assert by_class["prompt_injection"].answer_status == "safe_fallback"
    assert by_class["contradiction"].contradiction_handled is True
    assert by_class["contradiction"].answer_status == "safe_fallback"
    assert by_class["stale_source"].stale_source_handled is True
    assert by_class["stale_source"].answer_status == "safe_fallback"


def test_m24_p5_preserves_non_serving_authority_boundary() -> None:
    report = build_p5_query_answer_acceptance_report()

    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_answer_serving_enabled is False
    assert report.authority.deployment_mutation is False
    assert report.authority.traffic_mutation is False
    assert report.authority.source_mutation is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.permanent_ledger_mutation is False
    assert report.authority.raw_evidence_exposed is False
