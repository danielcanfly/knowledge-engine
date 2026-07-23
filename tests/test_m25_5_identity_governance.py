from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m25_identity_governance import (
    READY_STATUS,
    build_calibration_policy,
    build_governance_gate,
    build_governance_packet,
    run_calibrated_benchmark,
    sign,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE = json.loads((ROOT / "pilot/m25/m25-4-gold-suite.json").read_text())
BASELINE = json.loads((ROOT / "pilot/m25/m25-4-baseline-report.json").read_text())
BASELINE_BY_ID = {item["item_id"]: item for item in BASELINE["results"]}


def _synthetic_runner(case: dict[str, Any]) -> dict[str, Any]:
    item = next(item for item in SUITE["items"] if item["case"] == case)
    result = BASELINE_BY_ID[item["item_id"]]
    endpoint_ids = sorted(
        candidate["candidate_id"]
        for candidate in case["candidates"]
        if candidate["kind"] in {"concept", "entity", "alias", "term"}
    )
    resolutions = []
    for index, outcome in enumerate(result["actual_resolution_outcomes"]):
        resolutions.append(
            {
                "resolution_id": f"synthetic_{item['item_id']}_{index}",
                "candidate_ids": endpoint_ids,
                "outcome": outcome,
                "strong_signals": result["actual_explanation_signals"],
                "weak_signals": [],
                "authority": "candidate_only",
                "canonical_knowledge": False,
                "production_authority": False,
            }
        )
    packet = {
        "schema": "knowledge-engine-resolution-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "resolution_count": len(resolutions),
        "contradiction_count": result["actual_contradiction_count"],
        "packaging_blocked": result["actual_packaging_blocked"],
        "resolutions": resolutions,
        "contradictions": [
            {"contradiction_id": f"synthetic_{item['item_id']}"}
            for _ in range(result["actual_contradiction_count"])
        ],
    }
    return sign(packet, "packet_sha256")


def _item(class_label: str, split: str = "calibration") -> dict[str, Any]:
    return next(
        item
        for item in SUITE["items"]
        if item["class_label"] == class_label and item["split"] == split
    )


def test_policy_uses_only_train_and_calibration() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    assert policy["calibration"]["item_count"] == 20
    assert policy["held_out_evaluation"]["item_count"] == 10
    assert all("gold_final_" not in value for value in policy["calibration"]["item_ids"])
    assert policy["calibration"]["final_split_used"] is False
    assert policy["held_out_evaluation"]["may_change_policy"] is False
    assert validate_policy(policy) == policy


def test_calibrated_benchmark_closes_all_explanation_gaps() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    report = run_calibrated_benchmark(
        SUITE,
        BASELINE,
        policy,
        runner=_synthetic_runner,
    )
    assert report["metrics"]["semantic_decision_accuracy"] == 1.0
    assert report["metrics"]["explanation_signal_coverage"] == 1.0
    assert report["metrics"]["combined_governance_pass_rate"] == 1.0
    assert report["metrics"]["final_split_governance_pass_rate"] == 1.0
    assert report["metrics"]["false_merge_count"] == 0
    assert report["metrics"]["critical_false_merge_risk_count"] == 0
    assert report["metrics"]["destructive_decision_count"] == 0
    assert report["metrics"]["relation_candidate_count_by_type"] == {
        "narrower_than": 3,
        "supersedes": 3,
    }
    assert all(not result["missing_explanation_signals"] for result in report["results"])
    gate = build_governance_gate(report)
    assert gate["status"] == READY_STATUS
    assert gate["all_gates_passed"] is True
    assert gate["m25_6_authorized"] is False


@pytest.mark.parametrize(
    ("class_label", "signal", "relation"),
    [
        ("near_match_distinct", "near_match_distinction", None),
        ("parent_child_distinct", "parent_child_distinction", "narrower_than"),
        ("polysemy_ambiguous", "polysemy_collision", None),
        (
            "supersession_without_identity_collapse",
            "supersession_distinction",
            "supersedes",
        ),
    ],
)
def test_governance_explains_former_gap_classes(
    class_label: str, signal: str, relation: str | None
) -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    item = _item(class_label)
    packet = build_governance_packet(item["case"], _synthetic_runner(item["case"]), policy)
    assert signal in packet["explanation_signals"]
    assert packet["critical_false_merge_risk_count"] == 0
    assert packet["destructive_decision_count"] == 0
    if relation is None:
        assert packet["relation_candidate_count"] == 0
    else:
        assert {value["relation_type"] for value in packet["relation_candidates"]} == {
            relation
        }
        assert all(
            value["automatic_write_permitted"] is False
            for value in packet["relation_candidates"]
        )


def test_alias_ranking_is_exact_target_bound_and_non_writing() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    item = _item("approved_alias")
    packet = build_governance_packet(item["case"], _synthetic_runner(item["case"]), policy)
    resolution = packet["governed_resolutions"][0]
    assert resolution["inherited_outcome"] == "attach_alias_candidate"
    assert resolution["merge_gate_pass"] is True
    assert resolution["automatic_action_allowed"] is False
    assert resolution["blocks_destructive_action"] is False
    assert resolution["ranked_targets"][0]["targets"][0]["score"] >= 0.9


def test_ambiguous_and_policy_blocked_items_fail_closed() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    for class_label in ("polysemy_ambiguous", "ambiguous_insufficient_evidence", "blocked_policy"):
        item = _item(class_label)
        packet = build_governance_packet(item["case"], _synthetic_runner(item["case"]), policy)
        assert packet["packaging_blocked"] is True
        assert packet["destructive_decision_count"] == 0
        assert all(
            resolution["blocks_destructive_action"] is True
            for resolution in packet["governed_resolutions"]
        )


def test_policy_tampering_and_final_leakage_fail_closed() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    policy["calibration"]["item_ids"].append(policy["held_out_evaluation"]["item_ids"][0])
    policy = sign(policy, "policy_sha256")
    with pytest.raises(IntegrityError, match="final split leakage"):
        validate_policy(policy)


def test_base_outcome_drift_is_rejected() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)

    def drift_runner(case: dict[str, Any]) -> dict[str, Any]:
        packet = _synthetic_runner(case)
        if packet["resolutions"]:
            packet["resolutions"][0]["outcome"] = "exact_existing_match"
        return sign(packet, "packet_sha256")

    with pytest.raises(IntegrityError, match="inherited resolver outcome drift"):
        run_calibrated_benchmark(SUITE, BASELINE, policy, runner=drift_runner)


def test_governed_tags_are_preserved_without_authority_upgrade() -> None:
    policy = build_calibration_policy(SUITE, BASELINE)
    item = _item("near_match_distinct")
    case = json.loads(json.dumps(item["case"]))
    candidate = case["candidates"][0]
    tag = {
        "tag_candidate_id": "tag_model_governance",
        "source_candidate_id": candidate["candidate_id"],
        "source_tag": "model-governance",
        "canonical_tag": "model-governance",
        "dimension": "domain",
        "confidence": 0.7,
        "evidence_spans": candidate["evidence_spans"],
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    case["governed_tags"] = [tag]
    base = _synthetic_runner(item["case"])
    base = sign({**base, "packet_sha256": None}, "packet_sha256")
    packet = build_governance_packet(case, base, policy)
    assert packet["governed_tag_count"] == 1
    assert packet["governed_tag_candidates"] == [tag]
    assert packet["tag_governance_preserved"] is True
    assert packet["governed_tag_candidates"][0]["authority"] == "candidate_only"
