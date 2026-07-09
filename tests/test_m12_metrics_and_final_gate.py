from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from knowledge_engine.answer_performance_metrics import (
    AnswerPerformanceMetricPolicy,
    AnswerPerformanceObservation,
    evaluate_answer_performance_metrics,
)
from knowledge_engine.m12_final_gate import M12FinalGatePolicy, evaluate_m12_final_gate
from knowledge_engine.release_quality_gate import (
    GOVERNANCE_NO_WRITE,
    ReleaseQualityGatePolicy,
    evaluate_release_quality_gate,
)
from knowledge_engine.retrieval_citation_metrics import (
    RetrievalCitationExpectation,
    RetrievalCitationMetricPolicy,
    evaluate_retrieval_citation_metrics,
)

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    ROOT / "src/knowledge_engine/retrieval_citation_metrics.py",
    ROOT / "src/knowledge_engine/answer_performance_metrics.py",
    ROOT / "src/knowledge_engine/m12_final_gate.py",
)
RELEASE_ID = "release-fixture"
MANIFEST_SHA = "a" * 64
SOURCE_SHA = "b" * 40
PRODUCTION_RELEASE_ID = "20260708T040116Z-69a9f445699a"
PRODUCTION_MANIFEST_SHA = "c" * 64
PRODUCTION_POINTER_SHA = "d" * 64


def _golden_report() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "suite_id": "gqsuite_fixture",
        "report_id": "gqreport_fixture",
        "passed": True,
        "release_blocking": False,
        "release": {
            "release_id": RELEASE_ID,
            "manifest_sha256": MANIFEST_SHA,
        },
        "aggregate": {
            "case_count": 3,
            "passed_count": 3,
            "failed_count": 0,
            "release_blocking_count": 0,
        },
        "failure_reasons": [],
        "cases": [
            {
                "case_id": "answer-existing",
                "case_run_id": "gqrun_existing",
                "passed": True,
                "failure_reasons": [],
                "status": "answered",
                "audiences": ["internal"],
                "retrieval": {
                    "candidate_count": 2,
                    "selected_count": 1,
                    "acl_filtered_count": 1,
                    "raw_fallback_used": False,
                },
                "results": [
                    {
                        "concept_id": "ko_existing",
                        "citations": [{"source_id": "src-existing"}],
                    }
                ],
                "evaluation": {
                    "evaluation_id": "qeval_existing",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
            {
                "case_id": "answer-legacy",
                "case_run_id": "gqrun_legacy",
                "passed": True,
                "failure_reasons": [],
                "status": "answered",
                "audiences": ["public"],
                "retrieval": {
                    "candidate_count": 1,
                    "selected_count": 1,
                    "acl_filtered_count": 0,
                    "raw_fallback_used": False,
                },
                "results": [
                    {
                        "concept_id": "ko_legacy",
                        "citations": [{"source_id": "src-legacy"}],
                    }
                ],
                "evaluation": {
                    "evaluation_id": "qeval_legacy",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
            {
                "case_id": "unknown-topic",
                "case_run_id": "gqrun_unknown",
                "passed": True,
                "failure_reasons": [],
                "status": "not_found",
                "audiences": ["public"],
                "retrieval": {
                    "candidate_count": 0,
                    "selected_count": 0,
                    "acl_filtered_count": 0,
                    "raw_fallback_used": False,
                },
                "results": [],
                "evaluation": {
                    "evaluation_id": "qeval_unknown",
                    "passed": True,
                    "release_blocking": False,
                    "reasons": [],
                },
            },
        ],
    }


def _expectations() -> list[RetrievalCitationExpectation]:
    return [
        RetrievalCitationExpectation(
            case_id="answer-existing",
            relevant_concepts=frozenset({"ko_existing"}),
            expected_concepts=frozenset({"ko_existing"}),
            allowed_citation_sources=(("ko_existing", ("src-existing",)),),
        ),
        RetrievalCitationExpectation(
            case_id="answer-legacy",
            relevant_concepts=frozenset({"ko_legacy"}),
            expected_concepts=frozenset({"ko_legacy"}),
            allowed_citation_sources=(("ko_legacy", ("src-legacy",)),),
        ),
        RetrievalCitationExpectation(
            case_id="unknown-topic",
            expected_zero_result=True,
        ),
    ]


def _observations() -> list[AnswerPerformanceObservation]:
    return [
        AnswerPerformanceObservation(
            case_id="answer-existing",
            expected_claim_count=1,
            supported_claim_count=1,
            unsupported_claim_count=0,
            expected_fact_count=1,
            covered_fact_count=1,
            contradiction_expected=False,
            contradiction_handled=False,
            unknown_expected=False,
            unknown_handled=False,
            response_hashes=("hash-existing", "hash-existing"),
            latency_ms=(100.0, 110.0),
            token_cost_usd=(0.001, 0.001),
            index_load_ms=(25.0, 20.0),
            cache_hits=(False, True),
        ),
        AnswerPerformanceObservation(
            case_id="answer-legacy",
            expected_claim_count=1,
            supported_claim_count=1,
            unsupported_claim_count=0,
            expected_fact_count=1,
            covered_fact_count=1,
            contradiction_expected=True,
            contradiction_handled=True,
            unknown_expected=False,
            unknown_handled=False,
            response_hashes=("hash-legacy", "hash-legacy"),
            latency_ms=(120.0, 125.0),
            token_cost_usd=(0.002, 0.002),
            index_load_ms=(15.0, 10.0),
            cache_hits=(True, True),
        ),
        AnswerPerformanceObservation(
            case_id="unknown-topic",
            expected_claim_count=0,
            supported_claim_count=0,
            unsupported_claim_count=0,
            expected_fact_count=0,
            covered_fact_count=0,
            contradiction_expected=False,
            contradiction_handled=False,
            unknown_expected=True,
            unknown_handled=True,
            response_hashes=("hash-unknown", "hash-unknown"),
            latency_ms=(80.0, 85.0),
            token_cost_usd=(0.0, 0.0),
            index_load_ms=(5.0, 5.0),
            cache_hits=(True, True),
        ),
    ]


def _release_quality_decision() -> dict[str, Any]:
    artifacts = [
        {
            "evaluation_id": "qeval_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {
                "release_id": RELEASE_ID,
                "manifest_sha256": MANIFEST_SHA,
            },
        },
        {
            "report_id": "gqreport_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {
                "release_id": RELEASE_ID,
                "manifest_sha256": MANIFEST_SHA,
            },
        },
        {
            "baseline_check_id": "gqbaselinecheck_fixture",
            "schema_version": "1.0",
            "passed": True,
            "release_blocking": False,
            "stale": False,
            "audiences": ["public", "internal"],
            "release": {
                "release_id": RELEASE_ID,
                "manifest_sha256": MANIFEST_SHA,
            },
        },
    ]
    return evaluate_release_quality_gate(
        policy=ReleaseQualityGatePolicy(
            gate_id="m12-4-fixture",
            release_id=RELEASE_ID,
            manifest_sha256=MANIFEST_SHA,
            canonical_source_sha=SOURCE_SHA,
            production_release_id=PRODUCTION_RELEASE_ID,
            production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
            production_pointer_sha256=PRODUCTION_POINTER_SHA,
            reviewer_identity="reviewer@example.com",
            reviewed_at="2026-07-09T02:00:00Z",
            notes="Fixture quality gate review.",
            required_artifact_ids=frozenset(
                {"qeval_fixture", "gqreport_fixture", "gqbaselinecheck_fixture"}
            ),
            approved_audiences=frozenset({"public", "internal"}),
        ),
        artifacts=artifacts,
    )


def test_m12_5_metrics_pass_and_replay() -> None:
    report = evaluate_retrieval_citation_metrics(
        golden_report=_golden_report(),
        expectations=_expectations(),
    )
    replay = evaluate_retrieval_citation_metrics(
        golden_report=_golden_report(),
        expectations=_expectations(),
    )
    assert replay == report
    assert report["passed"] is True
    assert report["release_blocking"] is False
    assert report["retrieval_quality"] == {
        "expected_concept_hit_rate": 1.0,
        "selected_precision": 1.0,
        "false_positive_rate": 0.0,
        "zero_result_correctness": 1.0,
        "raw_fallback_rate": 0.0,
        "acl_filtered_count": 1,
    }
    assert all(value == 1.0 for value in report["citation_quality"].values())
    assert report["governance"] == GOVERNANCE_NO_WRITE


def test_m12_5_fails_closed_on_bad_citation_and_raw_fallback() -> None:
    golden = _golden_report()
    golden["cases"][0]["results"][0]["citations"][0]["source_id"] = "wrong-source"
    golden["cases"][1]["retrieval"]["raw_fallback_used"] = True
    report = evaluate_retrieval_citation_metrics(
        golden_report=golden,
        expectations=_expectations(),
        policy=RetrievalCitationMetricPolicy(),
    )
    assert report["passed"] is False
    assert report["release_blocking"] is True
    assert report["failure_reasons"] == [
        "citation_result_coverage_below_threshold",
        "citation_support_precision_below_threshold",
        "citation_target_correctness_below_threshold",
        "raw_fallback_rate_above_threshold",
    ]


def test_m12_5_rejects_incomplete_or_duplicate_case_coverage() -> None:
    with pytest.raises(ValueError, match="exactly cover"):
        evaluate_retrieval_citation_metrics(
            golden_report=_golden_report(),
            expectations=_expectations()[:-1],
        )
    golden = _golden_report()
    golden["cases"][1]["case_id"] = golden["cases"][0]["case_id"]
    with pytest.raises(ValueError, match="duplicated"):
        evaluate_retrieval_citation_metrics(
            golden_report=golden,
            expectations=_expectations(),
        )


def test_m12_6_metrics_pass_and_replay() -> None:
    report = evaluate_answer_performance_metrics(
        golden_report=_golden_report(),
        observations=_observations(),
        policy=AnswerPerformanceMetricPolicy(min_cache_hit_rate=0.5),
    )
    replay = evaluate_answer_performance_metrics(
        golden_report=_golden_report(),
        observations=_observations(),
        policy=AnswerPerformanceMetricPolicy(min_cache_hit_rate=0.5),
    )
    assert replay == report
    assert report["passed"] is True
    assert all(value == 1.0 for value in report["faithfulness_summary"].values())
    assert report["performance_summary"]["sample_count"] == 6
    assert report["performance_summary"]["p95_latency_ms"] == 125.0
    assert report["performance_summary"]["cache_hit_rate"] == pytest.approx(5 / 6)
    assert report["governance"] == GOVERNANCE_NO_WRITE


def test_m12_6_fails_closed_on_quality_and_performance_regression() -> None:
    observations = _observations()
    broken = observations[0]
    observations[0] = AnswerPerformanceObservation(
        case_id=broken.case_id,
        expected_claim_count=1,
        supported_claim_count=0,
        unsupported_claim_count=1,
        expected_fact_count=1,
        covered_fact_count=0,
        contradiction_expected=False,
        contradiction_handled=False,
        unknown_expected=False,
        unknown_handled=False,
        response_hashes=("hash-a", "hash-b"),
        latency_ms=(3000.0, 4000.0),
        token_cost_usd=(0.10, 0.10),
        index_load_ms=(3000.0, 4000.0),
        cache_hits=(False, False),
    )
    report = evaluate_answer_performance_metrics(
        golden_report=_golden_report(),
        observations=observations,
        policy=AnswerPerformanceMetricPolicy(min_cache_hit_rate=0.9),
    )
    assert report["passed"] is False
    assert report["release_blocking"] is True
    assert "faithfulness_below_threshold" in report["failure_reasons"]
    assert "completeness_below_threshold" in report["failure_reasons"]
    assert "unsupported_claim_rate_above_threshold" in report["failure_reasons"]
    assert "response_stability_below_threshold" in report["failure_reasons"]
    assert "p95_latency_budget_exceeded" in report["failure_reasons"]
    assert "mean_token_cost_budget_exceeded" in report["failure_reasons"]
    assert "p95_index_load_budget_exceeded" in report["failure_reasons"]
    assert "cache_hit_rate_below_threshold" in report["failure_reasons"]


def test_m12_7_final_gate_passes_replays_and_emits_all_sections() -> None:
    release_quality = _release_quality_decision()
    retrieval = evaluate_retrieval_citation_metrics(
        golden_report=_golden_report(),
        expectations=_expectations(),
    )
    answer = evaluate_answer_performance_metrics(
        golden_report=_golden_report(),
        observations=_observations(),
    )
    policy = M12FinalGatePolicy(
        gate_id="m12-final-fixture",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=PRODUCTION_RELEASE_ID,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
        production_pointer_sha256=PRODUCTION_POINTER_SHA,
        reviewer_identity="reviewer@example.com",
        reviewed_at="2026-07-09T03:00:00Z",
        notes="Reviewed complete M12 evidence bundle.",
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
    replay = evaluate_m12_final_gate(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    assert replay == result
    assert result["passed"] is True
    assert result["promotion_eligible"] is True
    assert result["release_blocking"] is False
    assert result["failure_reasons"] == []
    assert result["boundary_eval"]["passed"] is True
    assert all(result["regression_matrix"].values())
    assert all(result["closure_matrix"].values())
    for section in (
        "query_eval_summary",
        "retrieval_quality",
        "citation_quality",
        "faithfulness_summary",
        "performance_summary",
        "boundary_eval",
        "regression_matrix",
    ):
        assert isinstance(result[section], dict)
    assert result["governance"] == GOVERNANCE_NO_WRITE


def test_m12_7_blocks_failed_metrics_and_release_drift() -> None:
    release_quality = _release_quality_decision()
    retrieval = evaluate_retrieval_citation_metrics(
        golden_report=_golden_report(),
        expectations=_expectations(),
    )
    answer = evaluate_answer_performance_metrics(
        golden_report=_golden_report(),
        observations=_observations(),
    )
    retrieval["passed"] = False
    retrieval["release_blocking"] = True
    answer["release"]["manifest_sha256"] = "f" * 64
    policy = M12FinalGatePolicy(
        gate_id="m12-final-fixture",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=PRODUCTION_RELEASE_ID,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
        production_pointer_sha256=PRODUCTION_POINTER_SHA,
        reviewer_identity="reviewer@example.com",
        reviewed_at="2026-07-09T03:00:00Z",
        notes="Reviewed failing M12 evidence bundle.",
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
    assert result["promotion_eligible"] is False
    assert result["release_blocking"] is True
    assert "artifact_failed" in result["failure_reasons"]
    assert "artifact_release_blocking" in result["failure_reasons"]
    assert "manifest_sha256_mismatch" in result["failure_reasons"]
    assert result["closure_matrix"]["M12.7_final_release_blocking_gate"] is False


def test_m12_metric_modules_have_no_mutating_or_network_surface() -> None:
    forbidden_imports = {
        "boto3",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "create_pull_request",
        "merge_pull_request",
        "promote",
        "rollback",
        "delete",
        "put",
        "write_text",
        "write_bytes",
    }
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imported.isdisjoint(forbidden_imports)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls)
