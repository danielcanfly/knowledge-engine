from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m25_identity_governance import (
    READY_STATUS,
    build_calibration_policy,
    build_governance_gate,
    run_calibrated_benchmark,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot/m25"
SCHEMAS = ROOT / "schemas"
SUITE = json.loads((PILOT / "m25-4-gold-suite.json").read_text())
BASELINE = json.loads((PILOT / "m25-4-baseline-report.json").read_text())
POLICY = json.loads((PILOT / "m25-5-calibration-policy.json").read_text())
REPORT = json.loads((PILOT / "m25-5-calibrated-report.json").read_text())
GATE = json.loads((PILOT / "m25-5-governance-gate.json").read_text())


def test_committed_policy_rebuilds_exactly() -> None:
    assert build_calibration_policy(SUITE, BASELINE) == POLICY
    assert validate_policy(POLICY) == POLICY


def test_final_split_is_evaluation_only() -> None:
    calibration_ids = set(POLICY["calibration"]["item_ids"])
    final_ids = set(POLICY["held_out_evaluation"]["item_ids"])
    assert len(calibration_ids) == 20
    assert len(final_ids) == 10
    assert calibration_ids.isdisjoint(final_ids)
    assert all(item.startswith("gold_final_") for item in final_ids)
    assert not any(item.startswith("gold_final_") for item in calibration_ids)
    assert REPORT["final_split_used_for_calibration"] is False


def test_committed_report_meets_conservative_gate() -> None:
    metrics = REPORT["metrics"]
    assert metrics["semantic_decision_accuracy"] == 1.0
    assert metrics["explanation_signal_coverage"] == 1.0
    assert metrics["combined_governance_pass_rate"] == 1.0
    assert metrics["final_split_governance_pass_rate"] == 1.0
    assert metrics["false_merge_count"] == 0
    assert metrics["critical_false_merge_risk_count"] == 0
    assert metrics["destructive_decision_count"] == 0
    assert len(REPORT["results"]) == 30
    assert all(result["semantic_pass"] for result in REPORT["results"])
    assert all(result["explanation_pass"] for result in REPORT["results"])
    assert all(result["no_false_merge"] for result in REPORT["results"])
    assert build_governance_gate(REPORT) == GATE
    assert GATE["status"] == READY_STATUS
    assert GATE["all_gates_passed"] is True


def test_authority_and_protected_surfaces_remain_closed() -> None:
    assert POLICY["authority"] == "candidate_only"
    assert POLICY["review_required"] is True
    assert POLICY["canonical_knowledge"] is False
    assert POLICY["production_authority"] is False
    assert POLICY["m25_6_authorized"] is False
    assert REPORT["m25_6_authorized"] is False
    assert GATE["m25_6_authorized"] is False
    assert not any(GATE["protected_mutations"].values())


def test_schema_files_are_json_and_bind_current_versions() -> None:
    expected = {
        "m25-identity-calibration-policy-v1.schema.json": POLICY["schema_version"],
        "m25-calibrated-identity-governance-v1.schema.json": (
            "knowledge-engine-m25-calibrated-identity-governance/v1"
        ),
        "m25-calibrated-identity-report-v1.schema.json": REPORT["schema_version"],
    }
    for filename, schema_version in expected.items():
        schema = json.loads((SCHEMAS / filename).read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["properties"]["schema_version"]["const"] == schema_version


def test_actual_m21_resolver_replay_matches_committed_report() -> None:
    pytest.importorskip("knowledge_engine.m21_entity_resolution")
    actual = run_calibrated_benchmark(SUITE, BASELINE, POLICY)
    assert actual == REPORT
