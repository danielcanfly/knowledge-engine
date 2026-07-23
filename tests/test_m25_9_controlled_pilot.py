from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.errors import AuthorizationError, IntegrityError
from knowledge_engine.m25_controlled_pilot import (
    BLOCKED_STATUS,
    TEST_COMPLETE_STATUS,
    build_run_receipt,
    evaluate_readiness,
    sign,
    validate_inventory,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"


def load(name: str) -> dict:
    return json.loads((PILOT / name).read_text(encoding="utf-8"))


def resign(value: dict, field: str) -> dict:
    value.pop(field, None)
    return sign(value, field)


def test_readiness_gate_is_fail_closed_and_deterministic() -> None:
    predecessor = load("m25-8-readiness-gate.json")
    result = evaluate_readiness(predecessor)
    assert result == load("m25-9-readiness-gate.json")
    assert result["status"] == BLOCKED_STATUS
    assert result["pilot_execution_permitted"] is False
    assert result["m25_9b_authorized"] is False
    assert result["m25_9c_authorized"] is False
    assert result["m25_10_authorized"] is False


def test_inventory_validates_full_heterogeneous_population() -> None:
    inventory = load("m25-9-pilot-inventory.synthetic.json")
    result = validate_inventory(inventory)
    assert result == inventory
    assert result["source_count"] == 50
    assert {item["source_type"] for item in result["sources"]} == {
        "long_form_markdown",
        "technical_note",
        "structured_json",
        "bounded_web_snapshot",
    }
    assert {item["language"] for item in result["sources"]} == {"en", "zh-Hant", "mixed"}


def test_inventory_rejects_population_below_50() -> None:
    inventory = load("m25-9-pilot-inventory.synthetic.json")
    inventory["sources"] = inventory["sources"][:-1]
    inventory["source_count"] = 49
    inventory = resign(inventory, "inventory_sha256")
    with pytest.raises(IntegrityError, match="50-100"):
        validate_inventory(inventory)


def test_inventory_rejects_missing_adversarial_trait() -> None:
    inventory = load("m25-9-pilot-inventory.synthetic.json")
    for item in inventory["sources"]:
        if "conflicting_claim" in item["traits"]:
            item["traits"] = ["ordinary"]
    inventory = resign(inventory, "inventory_sha256")
    with pytest.raises(IntegrityError, match="missing required adversarial traits"):
        validate_inventory(inventory)


def test_live_inventory_rejects_synthetic_sources() -> None:
    inventory = load("m25-9-pilot-inventory.synthetic.json")
    inventory["mode"] = "live"
    inventory = resign(inventory, "inventory_sha256")
    with pytest.raises(AuthorizationError):
        validate_inventory(inventory)


def test_synthetic_full_population_run_rebuilds_exact_receipt() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    result = build_run_receipt(evidence)
    assert result == load("m25-9a-run-receipt.synthetic.json")
    assert result["status"] == TEST_COMPLETE_STATUS
    assert result["source_count"] == 50
    assert result["accounted_source_count"] == 50
    assert result["unaccounted_source_count"] == 0
    assert result["candidate_count"] == 90
    assert result["failure_drill_count"] == 11
    assert result["hidden_exclusions"] is False
    assert result["hard_safety_gates_passed"] is True


def test_run_rejects_hidden_population_exclusion() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["population"] = evidence["population"][:-1]
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="full population record count"):
        build_run_receipt(evidence)


def test_run_rejects_failed_source_threshold_breach() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["authority"]["stop_thresholds"]["max_failed_sources"] = 0
    evidence["authority"] = resign(evidence["authority"], "authority_sha256")
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="failed source threshold"):
        build_run_receipt(evidence)


def test_run_rejects_protected_mutation() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["boundary"]["source_write"] = True
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(AuthorizationError, match="protected mutation"):
        build_run_receipt(evidence)


def test_run_rejects_overbroad_inventory_authority() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["authority"]["m25_9b_authorized"] = True
    evidence["authority"] = resign(evidence["authority"], "authority_sha256")
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(AuthorizationError, match="over-broad"):
        build_run_receipt(evidence)


def test_run_rejects_tampered_authority_digest() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["authority"]["max_cost_usd"] = 1.0
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="authority digest mismatch"):
        build_run_receipt(evidence)


def test_run_rejects_candidate_count_mismatch() -> None:
    evidence = load("m25-9a-run-evidence.synthetic.json")
    evidence["candidate_population"]["candidate_count"] += 1
    evidence = resign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="candidate count mismatch"):
        build_run_receipt(evidence)
