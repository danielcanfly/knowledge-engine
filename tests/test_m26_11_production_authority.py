from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m26_production_authority import (
    AuthorityContractError,
    load_contract,
    validate_m26_11_contracts,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def test_m26_11_contracts_validate() -> None:
    result = validate_m26_11_contracts(ROOT)
    assert result == {
        "status": "m26_11_contract_valid",
        "stage_count": 6,
        "stop_condition_count": 10,
        "secret_name_count": 9,
        "public_traffic": False,
        "live_provider_calls": False,
        "production_pointer_mutation": False,
    }


def test_m26_11_entry_binds_accepted_predecessors() -> None:
    entry = load_contract(PILOT / "m26-11-entry-contract.json")
    assert entry["predecessors"] == {
        "m25_10_production_foundation_merge_sha": (
            "a7bc1383df79c519d389a9b135397b8e4d193e06"
        ),
        "m26_10_main_seal_sha": "d5204a0e75bc8a8a529e0f71e719dd47509bc726",
        "m26_10_status": "m26_10_synthetic_final_authority_gate_accepted",
    }


def test_m26_11_current_authority_is_non_mutating() -> None:
    matrix = load_contract(PILOT / "m26-11-authority-matrix.json")
    current = matrix["current_stage_authority"]
    allowed_true = {
        "contract_definition",
        "secret_name_inventory",
        "rollback_contract_definition",
    }
    assert all(value is False for key, value in current.items() if key not in allowed_true)


def test_m26_11_future_authority_is_stage_scoped() -> None:
    matrix = load_contract(PILOT / "m26-11-authority-matrix.json")
    stages = matrix["stages"]
    assert stages["M26.12"]["may_call_provider"] is False
    assert stages["M26.13"]["may_call_provider"] is True
    assert stages["M26.15"]["may_serve_public"] is False
    assert stages["M26.16"]["may_serve_bounded_canary"] is True
    assert stages["M26.16"]["may_serve_full_production"] is False
    assert stages["M26.17"]["may_serve_full_production"] is True


def test_m26_11_gate_inventory_is_fail_closed() -> None:
    gates = load_contract(PILOT / "m26-11-production-gates.json")
    assert gates["secret_values_must_not_be_persisted"] is True
    assert "acl_leakage_detected" in gates["automatic_stop_conditions"]
    assert "rollback_verification_failed" in gates["automatic_stop_conditions"]
    assert gates["mandatory_gates"]["rollback_tested_before_canary"] is True
    assert gates["mandatory_gates"]["exact_expected_previous_pointer"] is True


def test_m26_11_tampering_fails_closed(tmp_path: Path) -> None:
    source = PILOT / "m26-11-entry-contract.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    value["authorization"]["public_traffic_authorized"] = True
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(AuthorityContractError, match="self digest mismatch"):
        load_contract(tampered)
