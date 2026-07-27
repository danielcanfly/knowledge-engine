from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load(name: str) -> dict[str, Any]:
    value = json.loads((PILOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def verify_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert object_sha256(candidate) == expected


def test_g0_acceptance_identity_and_implementation() -> None:
    acceptance = load("m26-g0-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["status"] == "m26_g0_milestone_reconciliation_accepted"
    assert acceptance["canonical_statuses"] == {
        "g0": "m26_g0_milestone_reconciliation_accepted",
        "pa1": "m26_pa_1_production_activation_authority_freeze_accepted",
    }
    implementation = acceptance["implementation"]
    assert implementation["issue"] == 1178
    assert implementation["pull_request"] == 1182
    assert implementation["base_sha"] == (
        "4d7e661a21397ba5c88ba7160f3d0be3bd45cee3"
    )
    assert implementation["head_sha"] == (
        "fa6a7ea890538a0a707c99ed501ecf93555932c7"
    )
    assert implementation["merge_sha"] == (
        "a53eeae85265c2a8c3988f06371ee95849a22917"
    )
    assert implementation["expected_head_merge"] is True
    assert implementation["unresolved_review_threads"] == 0


def test_all_required_workflows_and_evidence_are_bound() -> None:
    acceptance = load("m26-g0-acceptance.json")
    workflows = acceptance["evidence"]["workflow_runs"]
    assert set(workflows) == {
        "CI",
        "R2 Release Integration",
        "M17 Architecture Canon Acceptance",
        "M18 Graph v2 acceptance",
        "M26.1 Architecture Authority",
        "M26.G0 Milestone Reconciliation",
    }
    assert all(item["conclusion"] == "success" for item in workflows.values())
    assert workflows["CI"]["run_id"] == 30236431337
    assert workflows["M26.G0 Milestone Reconciliation"]["run_id"] == 30236431355
    artifact = acceptance["evidence"]["artifact"]
    assert artifact["id"] == 8641769622
    assert artifact["name"] == "m26-g0-governance-evidence"
    assert artifact["digest"] == (
        "sha256:f353fa2ecffe213258403df564ae812de109d09c6d1e66eff017f9992038923f"
    )
    assert artifact["retention_days"] == 90


def test_governance_digests_match_implementation_artifacts() -> None:
    acceptance = load("m26-g0-acceptance.json")
    identities = acceptance["governance_identities"]
    files = {
        "owner_decision": "m26-g0-owner-decision.json",
        "milestone_alias_map": "m26-g0-milestone-alias-map.json",
        "stage_registry": "m26-g0-stage-registry.json",
        "pa1_ratification": "m26-g0-pa1-ratification.json",
        "legacy_pa2_candidate": "m26-g0-legacy-pa2-candidate.json",
    }
    for prefix, filename in files.items():
        value = load(filename)
        verify_self_digest(value)
        assert value["self_sha256"] == identities[f"{prefix}_self_sha256"]
        assert object_sha256(value) == identities[f"{prefix}_object_sha256"]

    registry = load("m26-g0-contract-registry.json")
    verify_self_digest(registry)
    assert registry["self_sha256"] == identities["contract_registry_self_sha256"]
    assert registry["artifacts"]["owner_decision_sha256"] == (
        identities["owner_decision_object_sha256"]
    )
    assert registry["artifacts"]["milestone_alias_map_sha256"] == (
        identities["milestone_alias_map_object_sha256"]
    )
    assert registry["artifacts"]["stage_registry_sha256"] == (
        identities["stage_registry_object_sha256"]
    )


def test_aliases_and_preserved_obligations_are_complete() -> None:
    acceptance = load("m26-g0-acceptance.json")
    assert acceptance["ratified_aliases"] == {
        "M26.9": "M26.S9",
        "M26.10": "M26.S10",
        "M26.11": "M26.PA.1",
        "M26.12": "M26.PA.2",
        "M26.13": "M26.PA.3",
        "M26.14": "M26.PA.4",
        "M26.15": "M26.PA.5",
        "M26.16": "M26.PA.6",
        "M26.17": "M26.PA.7",
    }
    obligations = acceptance["preserved_obligations"]
    assert obligations["pa5_controlled_pilot_questions_min"] == 200
    assert obligations["pa5_controlled_pilot_questions_max"] == 500
    assert obligations["pa7_final_answer_authority_and_closure"] is True


def test_pa1_and_m25_predecessors_are_exact() -> None:
    acceptance = load("m26-g0-acceptance.json")
    pa1 = acceptance["pa1_ratification"]
    assert pa1["historical_label"] == "M26.11"
    assert pa1["historical_main_seal"] == (
        "e88b50cb8f0084a6ec1ea1d9aadc9af7bce54bf6"
    )
    assert pa1["implementation_pr"] == 1174
    assert pa1["implementation_merge"] == (
        "e8b5c63ea57a8df581a2792af267f3b22a65db3c"
    )
    assert pa1["reconciliation_pr"] == 1175
    assert pa1["artifact_id"] == 8614361478
    assert pa1["live_authority"] is False

    m25 = acceptance["m25_dependency"]
    assert m25["status"] == "m25_closed"
    assert m25["final_reconciliation_merge_sha"] == (
        "4d7e661a21397ba5c88ba7160f3d0be3bd45cee3"
    )
    assert m25["new_ingestion_workload_execution_authorized"] is False


def test_authority_and_legacy_pa2_fail_closed() -> None:
    acceptance = load("m26-g0-acceptance.json")
    assert not any(acceptance["authority"].values())
    legacy = acceptance["legacy_pa2_candidate"]
    assert legacy["issue"] == 1176
    assert legacy["branch"] == "chatgpt/m26-12-real-corpus-binding"
    assert legacy["head"] == "40061ebf66b057dca490708b7abbaa5988b4edb8"
    assert legacy["classification"] == "candidate_patch_only"
    assert legacy["merge_authorized"] is False
    assert legacy["live_authorized"] is False
    assert legacy["acceptance_authorized"] is False
    assert legacy["required_repair_classes"] == ["P0", "P1"]


def test_next_legal_stage_is_non_live_pa2_repair_only() -> None:
    next_stage = load("m26-g0-acceptance.json")["next_stage"]
    assert next_stage["stage_id"] == "M26.PA.2"
    assert next_stage["fresh_non_live_repair_branch_unlocked_after_this_merge"] is True
    assert next_stage["p0_p1_repair_required"] is True
    assert next_stage["live_run_authorized"] is False
    assert next_stage["acceptance_authorized"] is False
    assert next_stage["daniel_exact_read_only_live_run_gate_required"] is True
