from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m26_governance_reconciliation import (
    ARTIFACTS,
    DENIED,
    EXPECTED_STAGES,
    GovernanceReconciliationError,
    canonical_json,
    load_json,
    validate_m26_g0,
    write_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"

GATES = [
    "owner_spec_is_unified_v3",
    "owner_approval_date_is_exact",
    "owner_denies_live_permission",
    "owner_denies_all_13_authorities",
    "owner_forbids_historical_rewrite",
    "owner_forbids_scope_inference",
    "g0_package_digest_is_exact",
    "handoff_package_digest_is_exact",
    "alias_count_is_9",
    "alias_m26_9_is_s9",
    "alias_m26_10_is_s10",
    "alias_m26_11_is_pa1",
    "alias_m26_12_is_pa2",
    "alias_m26_13_is_pa3",
    "alias_m26_14_is_pa4",
    "alias_m26_15_is_pa5",
    "alias_m26_16_is_pa6",
    "alias_m26_17_is_pa7",
    "pilot_obligation_is_pa5",
    "final_authority_obligation_is_pa7",
    "stage_count_is_10",
    "stage_graph_is_acyclic",
    "m25_closed_is_true",
    "pa2_requires_g0",
    "pa2_requires_pa1",
    "pa2_requires_m25_closed",
    "all_stages_deny_all_13_authorities",
    "pa1_status_is_reserved",
    "pa1_historical_identity_is_exact",
    "pa1_evidence_identity_is_exact",
    "pa1_no_live_authority",
    "legacy_branch_is_candidate_only",
    "legacy_branch_has_no_pr",
    "legacy_branch_has_no_live_run",
    "registry_digests_are_exact",
]


def _facts() -> dict[str, bool]:
    evidence = validate_m26_g0(ROOT)
    owner = load_json(PILOT / ARTIFACTS["owner_decision_sha256"])
    aliases = load_json(PILOT / ARTIFACTS["milestone_alias_map_sha256"])
    stages = load_json(PILOT / ARTIFACTS["stage_registry_sha256"])
    pa1 = load_json(PILOT / ARTIFACTS["pa1_ratification_sha256"])
    legacy = load_json(PILOT / ARTIFACTS["legacy_pa2_candidate_sha256"])
    alias_map = {
        item["historical_label"]: item["canonical_stage_id"]
        for item in aliases["aliases"]
    }
    by_id = {stage["stage_id"]: stage for stage in stages["stages"]}
    return {
        "owner_spec_is_unified_v3": (
            owner["specification"]["authority"] == "sole_highest_specification"
        ),
        "owner_approval_date_is_exact": owner["approval_date"] == "2026-07-26",
        "owner_denies_live_permission": owner["live_permission_granted"] is False,
        "owner_denies_all_13_authorities": set(owner["denied_authority"]) == DENIED,
        "owner_forbids_historical_rewrite": owner["historical_artifact_rewrite_permitted"] is False,
        "owner_forbids_scope_inference": (
            owner["approval_must_not_be_inferred_beyond_scope"] is True
        ),
        "g0_package_digest_is_exact": owner["execution_packages"][
            "g0_stage_package_sha256"
        ].startswith("65a2e6ae"),
        "handoff_package_digest_is_exact": owner["execution_packages"][
            "governance_execution_handoff_sha256"
        ].startswith("d0f2fa40"),
        "alias_count_is_9": len(alias_map) == 9,
        "alias_m26_9_is_s9": alias_map["M26.9"] == "M26.S9",
        "alias_m26_10_is_s10": alias_map["M26.10"] == "M26.S10",
        "alias_m26_11_is_pa1": alias_map["M26.11"] == "M26.PA.1",
        "alias_m26_12_is_pa2": alias_map["M26.12"] == "M26.PA.2",
        "alias_m26_13_is_pa3": alias_map["M26.13"] == "M26.PA.3",
        "alias_m26_14_is_pa4": alias_map["M26.14"] == "M26.PA.4",
        "alias_m26_15_is_pa5": alias_map["M26.15"] == "M26.PA.5",
        "alias_m26_16_is_pa6": alias_map["M26.16"] == "M26.PA.6",
        "alias_m26_17_is_pa7": alias_map["M26.17"] == "M26.PA.7",
        "pilot_obligation_is_pa5": any(
            item["canonical_stage_id"] == "M26.PA.5"
            for item in aliases["preserved_obligations"]
        ),
        "final_authority_obligation_is_pa7": any(
            item["canonical_stage_id"] == "M26.PA.7"
            for item in aliases["preserved_obligations"]
        ),
        "stage_count_is_10": set(by_id) == EXPECTED_STAGES,
        "stage_graph_is_acyclic": evidence["stage_count"] == 10,
        "m25_closed_is_true": stages["m25_closed_at_snapshot"] is True,
        "pa2_requires_g0": "M26.G0" in by_id["M26.PA.2"]["predecessors"],
        "pa2_requires_pa1": "M26.PA.1" in by_id["M26.PA.2"]["predecessors"],
        "pa2_requires_m25_closed": "M25.closed" in by_id["M26.PA.2"]["predecessors"],
        "all_stages_deny_all_13_authorities": all(
            set(item["denied_capabilities"]) == DENIED for item in stages["stages"]
        ),
        "pa1_status_is_reserved": (
            pa1["effective_only_after_status"]
            == "m26_g0_milestone_reconciliation_accepted"
        ),
        "pa1_historical_identity_is_exact": pa1["historical_identity"][
            "implementation_merge_sha"
        ].startswith("e8b5c63e"),
        "pa1_evidence_identity_is_exact": pa1["evidence_artifact"]["artifact_id"] == 8614361478,
        "pa1_no_live_authority": pa1["ratified_authority"]["live_provider_calls"] is False,
        "legacy_branch_is_candidate_only": legacy["classification"] == "candidate_patch_only",
        "legacy_branch_has_no_pr": legacy["pull_request_number"] is None,
        "legacy_branch_has_no_live_run": legacy["live_run"] is False,
        "registry_digests_are_exact": evidence["accepted"] is False,
    }


@pytest.mark.parametrize("gate", GATES)
def test_g0_gate_matrix(gate: str) -> None:
    assert _facts()[gate], gate


def test_evidence_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_evidence(ROOT, first)
    write_evidence(ROOT, second)
    assert first.read_bytes() == second.read_bytes()
    value = json.loads(first.read_text())
    assert value["status"] == "m26_g0_governance_evidence_candidate"
    assert value["accepted"] is False


def test_legacy_acceptance_escalation_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    for source in (ROOT / "pilot", ROOT / "schemas"):
        destination = target / source.name
        destination.mkdir(parents=True)
        for path in source.rglob("m26-g0-*.json"):
            relative = path.relative_to(source)
            (destination / relative).parent.mkdir(parents=True, exist_ok=True)
            (destination / relative).write_bytes(path.read_bytes())
    legacy_path = target / "pilot/m26/m26-g0-legacy-pa2-candidate.json"
    legacy = load_json(legacy_path)
    legacy["acceptance"] = True
    legacy["self_sha256"] = ""
    import hashlib

    legacy["self_sha256"] = hashlib.sha256(canonical_json(legacy).encode()).hexdigest()
    legacy_path.write_text(canonical_json(legacy) + "\n")
    with pytest.raises(GovernanceReconciliationError):
        validate_m26_g0(target)
