from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "pilot" / "m25" / "m25-4-acceptance.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m25_4_acceptance_identity_is_exact() -> None:
    value = load(ACCEPTANCE)
    assert value["schema_version"] == "knowledge-engine-m25-4-acceptance/v1"
    assert value["status"] == "m25_4_gold_benchmark_accepted"
    assert value["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1046,
        "state": "closed",
        "state_reason": "completed",
    }
    assert value["implementation"] == {
        "pull_request_number": 1047,
        "base_sha": "744cfdc830da4a7bcfd4ed6ec3cf55972b042358",
        "approved_candidate_head_sha": "cf56bad3b9128020214c3a30100ec741d6842e56",
        "final_head_sha": "a58df21e1ace0bf5793fab3de3aca161818df528",
        "merge_sha": "9b75e467678889980aa91d31f1c41bfb72e41ee6",
        "merged_required": True,
        "exact_head_workflows_required": True,
    }


def test_daniel_authority_is_exact_and_does_not_self_authorize_m25_5() -> None:
    value = load(ACCEPTANCE)
    assert value["daniel_authority"] == {
        "actor": "huaihsuanbusiness",
        "issue_comment_id": 5053875354,
        "approved_annotation_and_adjudication_policy": True,
        "approved_all_30_labels": True,
        "confirmed_disputed_item_count": 0,
        "approved_candidate_head_sha": "cf56bad3b9128020214c3a30100ec741d6842e56",
        "m25_5_authorized_by_approval": False,
    }


def test_population_and_baseline_are_frozen() -> None:
    value = load(ACCEPTANCE)
    assert value["population"] == {
        "item_count": 30,
        "class_count": 10,
        "train_count": 10,
        "calibration_count": 10,
        "final_count": 10,
        "semantic_family_leakage_count": 0,
        "disputed_item_count": 0,
    }
    assert value["baseline"] == {
        "semantic_decision_correct": 30,
        "semantic_decision_total": 30,
        "semantic_decision_accuracy": 1.0,
        "false_merge_count": 0,
        "explanation_signal_covered": 18,
        "explanation_signal_total": 30,
        "explanation_signal_coverage": 0.6,
        "explanation_signal_gap_count": 12,
        "resolver_or_threshold_changed": False,
        "final_split_used_for_calibration": False,
    }


def test_workflow_and_artifact_evidence_is_exact() -> None:
    value = load(ACCEPTANCE)
    assert value["required_workflows"] == {
        "CI": 29978054382,
        "M17 Architecture Canon Acceptance": 29978054490,
        "M17 Independent Operator GA Acceptance": 29978054417,
        "M18 Graph v2 acceptance": 29978054422,
        "M25.2 Intake Orchestrator": 29978054379,
        "M25.3 Extraction Worker": 29978054430,
        "M25.4 Identity Gold Benchmark": 29978054451,
        "M25.4 Daniel Approval Finalization": 29978054409,
        "R2 Release Integration": 29978054390,
    }
    assert value["evidence_artifacts"]["benchmark"]["digest"] == (
        "sha256:091aa7a584c2ba7ba056647dbaeeab73ba95bca3b0c66ac52ea1a8e247f43e81"
    )
    assert value["evidence_artifacts"]["daniel_approval"]["digest"] == (
        "sha256:1eef2312f88d38d7316c05911ba175c8a38ee058f9cfea6b5fbf710aab1960f1"
    )


def test_protected_mutations_remain_zero() -> None:
    value = load(ACCEPTANCE)
    assert all(item is False for item in value["protected_mutations"].values())
    assert value["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_used": False,
        "codex_escalations": 0,
        "daniel_gate_required": True,
        "daniel_gate_satisfied": True,
    }
    assert value["reconciliation"] == {
        "implementation_merge_is_required_ancestor": True,
        "approved_candidate_is_required_ancestor": True,
        "authority_comment_required": True,
        "both_evidence_digests_required": True,
        "no_new_authority_granted": True,
    }


def test_m25_5_is_unlocked_only_by_m25_4_closure() -> None:
    value = load(ACCEPTANCE)
    assert value["next_stage"] == {
        "authorized_by_m25_4_closure": True,
        "stage_id": "M25.5",
        "name": "Calibrated Concept Identity and Knowledge Governance",
        "predecessor_status_required": "m25_4_gold_benchmark_accepted",
        "not_authorized_by_daniel_m25_4_approval_alone": True,
    }
