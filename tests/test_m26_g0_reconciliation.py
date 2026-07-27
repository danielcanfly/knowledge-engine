from __future__ import annotations

import json
from pathlib import Path

from knowledge_engine.m26_governance_reconciliation import (
    validate_m26_g0,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_g0_acceptance_self_digest_and_statuses() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    verify_self_digest(acceptance, "m26_g0_acceptance")
    assert acceptance["self_sha256"] == (
        "a7fbd51e126414ff66fe1cf0fea5e7ab1f07476d3e7596914c2c8568e730084e"
    )
    assert acceptance["status"] == "m26_g0_milestone_reconciliation_accepted"
    assert acceptance["pa1_status"] == (
        "m26_pa_1_production_activation_authority_freeze_accepted"
    )
    assert acceptance["accepted"] is True


def test_g0_implementation_exact_identity() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    implementation = acceptance["implementation"]
    assert implementation == {
        "pull_request_number": 1182,
        "base_sha": "4d7e661a21397ba5c88ba7160f3d0be3bd45cee3",
        "head_sha": "fa6a7ea890538a0a707c99ed501ecf93555932c7",
        "merge_sha": "a53eeae85265c2a8c3988f06371ee95849a22917",
        "changed_file_count": 12,
        "expected_head_merge": True,
        "unresolved_review_thread_count": 0,
    }


def test_g0_required_workflows_and_evidence_are_bound() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    assert acceptance["required_workflows"] == {
        "CI": 30236431337,
        "M17 Architecture Canon Acceptance": 30236431345,
        "M18 Graph v2 acceptance": 30236431340,
        "M26.1 Architecture Authority": 30236431347,
        "M26.G0 Milestone Reconciliation": 30236431355,
        "R2 Release Integration": 30236431343,
    }
    artifact = acceptance["evidence_artifact"]
    assert artifact["artifact_id"] == 8641769622
    assert artifact["workflow_run_id"] == 30236431355
    assert artifact["head_sha"] == "fa6a7ea890538a0a707c99ed501ecf93555932c7"
    assert artifact["digest"] == (
        "sha256:f353fa2ecffe213258403df564ae812de109d09c6d1e66eff017f9992038923f"
    )


def test_g0_frozen_identities_match_implementation_registry() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    registry = load(PILOT / "m26-g0-contract-registry.json")
    frozen = acceptance["frozen_governance_identities"]
    assert frozen["contract_registry_self_sha256"] == registry["self_sha256"]
    assert frozen["owner_decision_sha256"] == registry["artifacts"][
        "owner_decision_sha256"
    ]
    assert frozen["milestone_alias_map_sha256"] == registry["artifacts"][
        "milestone_alias_map_sha256"
    ]
    assert frozen["stage_registry_sha256"] == registry["artifacts"][
        "stage_registry_sha256"
    ]
    assert frozen["pa1_ratification_sha256"] == registry["artifacts"][
        "pa1_ratification_sha256"
    ]
    assert frozen["legacy_pa2_candidate_sha256"] == registry["artifacts"][
        "legacy_pa2_candidate_sha256"
    ]
    assert frozen["governance_adoption_schema_sha256"] == registry["schemas"][
        "governance_adoption_schema_sha256"
    ]
    assert frozen["pa1_ratification_schema_sha256"] == registry["schemas"][
        "pa1_ratification_schema_sha256"
    ]


def test_g0_implementation_evidence_still_validates() -> None:
    report = validate_m26_g0(ROOT)
    assert report["status"] == "m26_g0_governance_evidence_candidate"
    assert report["accepted"] is False
    assert report["accepted_status_reserved_for_reconciliation"] == (
        "m26_g0_milestone_reconciliation_accepted"
    )
    assert report["pa1_status_reserved_for_reconciliation"] == (
        "m26_pa_1_production_activation_authority_freeze_accepted"
    )


def test_g0_authority_boundary_remains_closed() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    assert all(value is False for value in acceptance["authority_boundary"].values())
    assert acceptance["pa1_ratification"]["historical_artifacts_rewritten"] is False
    assert acceptance["pa1_ratification"]["additional_live_authority_granted"] is False


def test_pa2_is_unlocked_only_for_fresh_non_live_repair() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    next_stage = acceptance["next_stage"]
    assert next_stage["stage_id"] == "M26.PA.2"
    assert next_stage["fresh_branch_non_live_p0_p1_repair_authorized"] is True
    assert next_stage["legacy_branch_merge_authorized"] is False
    assert next_stage["real_corpus_live_run_authorized"] is False
    assert next_stage["acceptance_authorized"] is False
    assert next_stage["requires_daniel_exact_read_only_live_run_approval"] is True
    assert next_stage["requires_independent_pa2_reconciliation"] is True


def test_m25_closure_and_legacy_pa2_are_not_overstated() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    assert acceptance["m25_predecessor"] == {
        "status": "m25_closed",
        "final_reconciliation_path": "pilot/m25/m25-final-reconciliation.json",
        "final_reconciliation_merge_sha": (
            "4d7e661a21397ba5c88ba7160f3d0be3bd45cee3"
        ),
        "closure_not_inferred_from_pointer": True,
    }
    legacy = acceptance["legacy_pa2"]
    assert legacy["classification"] == "candidate_patch_only"
    assert legacy["merge_ready"] is False
    assert legacy["live_run"] is False
    assert legacy["accepted"] is False
    assert legacy["requires_fresh_post_g0_branch"] is True
    assert legacy["p0_p1_repair_required"] is True


def test_reconciliation_ci_repair_is_bounded() -> None:
    acceptance = load(PILOT / "m26-g0-acceptance.json")
    repair = acceptance["reconciliation_ci_repair"]
    assert repair["failure_run_id"] == 30237010744
    assert repair["failure_step"] == "Enforce exact change surface"
    assert repair["changed_file"] == (
        ".github/workflows/m26-g0-milestone-reconciliation.yml"
    )
    assert repair["implementation_evidence_rewritten"] is False
    assert repair["authority_expansion"] is False
    assert repair["protected_path_relaxation"] is False
