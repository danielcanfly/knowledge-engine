from __future__ import annotations

from knowledge_engine.answer_performance_metrics import (
    AnswerPerformanceMetricPolicy,
    evaluate_answer_performance_metrics,
)
from knowledge_engine.m12_final_gate import M12FinalGatePolicy, evaluate_m12_final_gate
from knowledge_engine.retrieval_citation_metrics import (
    RetrievalCitationMetricPolicy,
    evaluate_retrieval_citation_metrics,
)
from tests.fixtures.m12_hardening import (
    MANIFEST_SHA,
    PRODUCTION_MANIFEST_SHA,
    PRODUCTION_POINTER_SHA,
    PRODUCTION_RELEASE_ID,
    RELEASE_ID,
    SOURCE_SHA,
    golden_report,
    legacy_answer_observations,
    release_quality_decision,
    retrieval_expectations,
)


def test_v1_retrieval_and_answer_metrics_remain_deterministic() -> None:
    retrieval = evaluate_retrieval_citation_metrics(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
        policy=RetrievalCitationMetricPolicy(),
    )
    answer = evaluate_answer_performance_metrics(
        golden_report=golden_report(),
        observations=legacy_answer_observations(),
        policy=AnswerPerformanceMetricPolicy(min_cache_hit_rate=0.5),
    )
    assert retrieval["passed"] is True
    assert retrieval["retrieval_quality"]["raw_fallback_rate"] == 0.0
    assert answer["passed"] is True
    assert answer["faithfulness_summary"]["faithfulness"] == 1.0
    assert evaluate_retrieval_citation_metrics(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    ) == evaluate_retrieval_citation_metrics(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )


def test_v1_retrieval_metrics_still_fail_closed() -> None:
    report = golden_report()
    report["cases"][0]["results"][0]["citations"][0]["source_id"] = "wrong"
    report["cases"][1]["retrieval"]["raw_fallback_used"] = True
    result = evaluate_retrieval_citation_metrics(
        golden_report=report,
        expectations=retrieval_expectations(),
    )
    assert result["passed"] is False
    assert result["release_blocking"] is True
    assert "raw_fallback_rate_above_threshold" in result["failure_reasons"]
    assert "citation_target_correctness_below_threshold" in result["failure_reasons"]


def test_v1_final_gate_remains_available_for_replay() -> None:
    release_quality = release_quality_decision()
    retrieval = evaluate_retrieval_citation_metrics(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )
    answer = evaluate_answer_performance_metrics(
        golden_report=golden_report(),
        observations=legacy_answer_observations(),
    )
    policy = M12FinalGatePolicy(
        gate_id="m12-final-v1-compatibility",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=PRODUCTION_RELEASE_ID,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
        production_pointer_sha256=PRODUCTION_POINTER_SHA,
        reviewer_identity="reviewer@example.com",
        reviewed_at="2026-07-09T03:00:00Z",
        notes="Compatibility replay for the M12 v1 gate.",
        required_artifact_ids=frozenset(
            {
                release_quality["gate_decision_id"],
                retrieval["artifact_id"],
                answer["artifact_id"],
            }
        ),
    )
    result = evaluate_m12_final_gate(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    assert result["passed"] is True
    assert result["promotion_eligible"] is True
    assert all(result["closure_matrix"].values())


def test_v1_final_gate_blocks_release_identity_drift() -> None:
    release_quality = release_quality_decision()
    retrieval = evaluate_retrieval_citation_metrics(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )
    answer = evaluate_answer_performance_metrics(
        golden_report=golden_report(),
        observations=legacy_answer_observations(),
    )
    answer["release"]["manifest_sha256"] = "f" * 64
    policy = M12FinalGatePolicy(
        gate_id="m12-final-v1-drift",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=PRODUCTION_RELEASE_ID,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
        production_pointer_sha256=PRODUCTION_POINTER_SHA,
        reviewer_identity="reviewer@example.com",
        reviewed_at="2026-07-09T03:00:00Z",
        notes="Compatibility drift test.",
        required_artifact_ids=frozenset(
            {
                release_quality["gate_decision_id"],
                retrieval["artifact_id"],
                answer["artifact_id"],
            }
        ),
    )
    result = evaluate_m12_final_gate(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    assert result["passed"] is False
    assert "manifest_sha256_mismatch" in result["failure_reasons"]
