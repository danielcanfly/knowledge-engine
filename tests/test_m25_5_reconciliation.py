from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m25_identity_governance import build_governance_gate

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"
ACCEPTANCE = json.loads((PILOT / "m25-5-acceptance.json").read_text())
POLICY = json.loads((PILOT / "m25-5-calibration-policy.json").read_text())
REPORT = json.loads((PILOT / "m25-5-calibrated-report.json").read_text())
GATE = json.loads((PILOT / "m25-5-governance-gate.json").read_text())


def test_acceptance_identity_and_metrics() -> None:
    assert ACCEPTANCE["status"] == "m25_5_identity_governance_accepted"
    assert ACCEPTANCE["implementation"]["merge_sha"] == "8ae3e77b8f9ffbd3df5ec820cca04b0b47413e02"
    assert ACCEPTANCE["frozen_identities"] == {
        "calibration_policy_sha256": POLICY["policy_sha256"],
        "calibrated_report_sha256": REPORT["report_sha256"],
        "governance_gate_sha256": GATE["gate_sha256"],
    }
    assert build_governance_gate(REPORT) == GATE
    assert all(
        value == 1.0
        for key, value in ACCEPTANCE["metrics"].items()
        if key.endswith("rate")
        or key.endswith("accuracy")
        or key.endswith("coverage")
    )
    assert ACCEPTANCE["metrics"]["false_merge_count"] == 0
    assert ACCEPTANCE["metrics"]["critical_false_merge_risk_count"] == 0
    assert ACCEPTANCE["metrics"]["destructive_decision_count"] == 0


def test_authority_and_next_stage_boundaries() -> None:
    assert ACCEPTANCE["governance"]["candidate_only"] is True
    assert ACCEPTANCE["governance"]["review_required"] is True
    assert ACCEPTANCE["governance"]["canonical_knowledge"] is False
    assert ACCEPTANCE["governance"]["production_authority"] is False
    assert ACCEPTANCE["governance"]["alias_specific_threshold_enforced"] is True
    assert ACCEPTANCE["governance"]["ranked_identity_signal_required_for_alias"] is True
    assert not any(ACCEPTANCE["protected_mutations"].values())
    assert ACCEPTANCE["execution_roles"]["codex_used"] is False
    assert ACCEPTANCE["next_stage"]["stage_id"] == "M25.6"
    assert ACCEPTANCE["next_stage"]["authorized_by_m25_5_closure"] is True
    assert ACCEPTANCE["next_stage"]["not_authorized_by_candidate_gate_alone"] is True
    assert (
        ACCEPTANCE["next_stage"]["daniel_browser_acceptance_required_before_m25_6_closure"]
        is True
    )
