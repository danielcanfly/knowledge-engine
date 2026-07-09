from __future__ import annotations

import ast
from pathlib import Path

from knowledge_engine.answer_performance_metrics_v2 import (
    ClaimAlignmentMetricPolicy,
    evaluate_claim_aligned_answer_metrics,
)
from knowledge_engine.compiler_m11_closure_v2 import build_semantic_invariant_matrix
from knowledge_engine.m12_final_gate_v2 import (
    M12FinalGatePolicyV2,
    evaluate_m12_final_gate_v2,
)
from knowledge_engine.retrieval_citation_metrics_v2 import (
    RetrievalCoveragePolicy,
    evaluate_retrieval_citation_metrics_v2,
)
from tests.fixtures.m12_hardening import (
    MANIFEST_SHA,
    PRODUCTION_MANIFEST_SHA,
    PRODUCTION_POINTER_SHA,
    PRODUCTION_RELEASE_ID,
    RELEASE_ID,
    SOURCE_SHA,
    claim_aligned_observations,
    golden_report,
    release_quality_decision,
    retrieval_expectations,
)

ROOT = Path(__file__).resolve().parents[1]
HARDENING_MODULES = (
    ROOT / "src/knowledge_engine/compiler_m11_closure_v2.py",
    ROOT / "src/knowledge_engine/retrieval_citation_metrics_v2.py",
    ROOT / "src/knowledge_engine/answer_performance_metrics_v2.py",
    ROOT / "src/knowledge_engine/m12_final_gate_v2.py",
)


def _legacy_m11_matrix() -> dict[str, object]:
    return {
        "schema_version": "knowledge-compiler-m11-invariant-matrix/v1",
        "closure_id": "m11cl_fixture",
        "invariants": {
            "compiler_pipeline_evidence_complete": True,
            "human_review_mandatory": True,
            "automatic_approval_permitted": False,
            "unsupported_or_quarantined_content_published": False,
            "audience_or_acl_broadened": False,
            "canonical_source_written": False,
            "source_pr_created_or_merged": False,
            "candidate_or_release_created": False,
            "production_promoted_or_rolled_back": False,
            "production_pointer_changed": False,
            "permanent_ledger_appended": False,
            "deterministic_replay_supported": True,
        },
        "all_passed": True,
    }


def _final_policy(
    release_quality: dict[str, object],
    retrieval: dict[str, object],
    answer: dict[str, object],
) -> M12FinalGatePolicyV2:
    return M12FinalGatePolicyV2(
        gate_id="m12-final-v2-fixture",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=PRODUCTION_RELEASE_ID,
        production_manifest_sha256=PRODUCTION_MANIFEST_SHA,
        production_pointer_sha256=PRODUCTION_POINTER_SHA,
        reviewer_identity="reviewer@example.com",
        reviewed_at="2026-07-09T04:00:00Z",
        notes="Reviewed strict M12 v2 evidence bundle.",
        required_top_level_artifact_ids=frozenset(
            {
                str(release_quality["gate_decision_id"]),
                str(retrieval["artifact_id"]),
                str(answer["artifact_id"]),
            }
        ),
    )


def test_m11_semantic_matrix_v2_is_explicit_and_deterministic() -> None:
    matrix = build_semantic_invariant_matrix(
        closure_id="m11cl_fixture",
        legacy_matrix=_legacy_m11_matrix(),
        legacy_matrix_ref="compiler/v1/m11-closures/m11cl_fixture/invariant-matrix.json",
    )
    replay = build_semantic_invariant_matrix(
        closure_id="m11cl_fixture",
        legacy_matrix=_legacy_m11_matrix(),
        legacy_matrix_ref="compiler/v1/m11-closures/m11cl_fixture/invariant-matrix.json",
    )
    assert replay == matrix
    assert matrix["schema_version"].endswith("/v2")
    assert matrix["all_passed"] is True
    assert matrix["passed_count"] == matrix["check_count"] == 12
    automatic = next(
        check for check in matrix["checks"] if check["name"] == "automatic_approval_permitted"
    )
    assert automatic == {
        "name": "automatic_approval_permitted",
        "expected": False,
        "observed": False,
        "passed": True,
        "evidence_ref": (
            "compiler/v1/m11-closures/m11cl_fixture/invariant-matrix.json"
            "#/invariants/automatic_approval_permitted"
        ),
    }


def test_m11_semantic_matrix_v2_detects_false_positive_legacy_closure() -> None:
    legacy = _legacy_m11_matrix()
    legacy["invariants"]["canonical_source_written"] = True  # type: ignore[index]
    matrix = build_semantic_invariant_matrix(
        closure_id="m11cl_fixture",
        legacy_matrix=legacy,
        legacy_matrix_ref="legacy-matrix.json",
    )
    assert matrix["all_passed"] is False
    assert matrix["mismatches"] == ["canonical_source_written"]


def test_retrieval_metrics_v2_enforce_coverage_floors() -> None:
    result = evaluate_retrieval_citation_metrics_v2(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )
    replay = evaluate_retrieval_citation_metrics_v2(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )
    assert replay == result
    assert result["passed"] is True
    assert all(result["coverage_checks"].values())
    assert result["coverage"] == {
        "case_count": 3,
        "answered_cases": 2,
        "cited_results": 2,
        "expected_concepts": 2,
        "citation_expectations": 2,
        "zero_result_cases": 1,
    }

    blocked = evaluate_retrieval_citation_metrics_v2(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
        coverage_policy=RetrievalCoveragePolicy(min_answered_cases=3),
    )
    assert blocked["passed"] is False
    assert "insufficient_answered_cases" in blocked["failure_reasons"]


def test_claim_level_answer_metrics_v2_require_support_alignment() -> None:
    result = evaluate_claim_aligned_answer_metrics(
        golden_report=golden_report(),
        observations=claim_aligned_observations(),
        policy=ClaimAlignmentMetricPolicy(
            min_faithfulness=0.6,
            max_unsupported_claim_rate=0.4,
            min_cache_hit_rate=0.5,
        ),
    )
    replay = evaluate_claim_aligned_answer_metrics(
        golden_report=golden_report(),
        observations=claim_aligned_observations(),
        policy=ClaimAlignmentMetricPolicy(
            min_faithfulness=0.6,
            max_unsupported_claim_rate=0.4,
            min_cache_hit_rate=0.5,
        ),
    )
    assert replay == result
    assert result["passed"] is True
    assert result["coverage"]["claim_count"] == 4
    assert result["coverage"]["contradiction_probes"] == 1
    assert result["coverage"]["unknown_probes"] == 1
    assert len(result["claim_alignment"]) == 4
    assert result["unsupported_claim_summary"]["unsupported_claim_count"] == 1

    blocked = evaluate_claim_aligned_answer_metrics(
        golden_report=golden_report(),
        observations=claim_aligned_observations(),
        policy=ClaimAlignmentMetricPolicy(min_claim_count=5),
    )
    assert blocked["passed"] is False
    assert "claim_count_check_failed" in blocked["failure_reasons"]


def test_final_gate_v2_requires_exact_artifact_families_and_claim_alignment() -> None:
    release_quality = release_quality_decision()
    retrieval = evaluate_retrieval_citation_metrics_v2(
        golden_report=golden_report(),
        expectations=retrieval_expectations(),
    )
    answer = evaluate_claim_aligned_answer_metrics(
        golden_report=golden_report(),
        observations=claim_aligned_observations(),
        policy=ClaimAlignmentMetricPolicy(
            min_faithfulness=0.6,
            max_unsupported_claim_rate=0.4,
        ),
    )
    policy = _final_policy(release_quality, retrieval, answer)
    result = evaluate_m12_final_gate_v2(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    replay = evaluate_m12_final_gate_v2(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    assert replay == result
    assert result["passed"] is True
    assert result["promotion_eligible"] is True
    assert result["nested_family_counts"] == {
        "M12.1_runtime_query_evaluation": 1,
        "M12.2_golden_query_suite": 1,
        "M12.3_golden_baseline_gate": 1,
    }
    assert all(result["closure_matrix"].values())

    release_quality["artifact_refs"][1]["artifact_id"] = "unknown_report"
    blocked = evaluate_m12_final_gate_v2(
        policy=policy,
        release_quality_decision=release_quality,
        retrieval_citation_metrics=retrieval,
        answer_performance_metrics=answer,
    )
    assert blocked["passed"] is False
    assert "required_nested_artifact_family_missing" in blocked["failure_reasons"]
    assert "unknown_nested_artifact_family" in blocked["failure_reasons"]
    assert blocked["regression_matrix"]["M12.2_golden_query_suite"] is False


def test_hardening_modules_have_no_network_or_mutation_surface() -> None:
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
    }
    for path in HARDENING_MODULES:
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
