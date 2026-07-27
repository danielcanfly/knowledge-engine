from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from knowledge_engine.m26_governance_reconciliation import (
    ALIAS_MAP,
    CANONICAL_STATUS_CATALOG,
    CONTRACT_REGISTRY,
    EXPECTED_CHANGED_FILES,
    LEGACY_PA2,
    OWNER_DECISION,
    PA1_RATIFICATION,
    STAGE_REGISTRY,
    GovernanceReconciliationError,
    canonical_sha256,
    load_json,
    validate_changed_files,
    validate_m26_g0,
    validate_schema,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def copied_repo(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(ROOT, target)
    return target


def resign(value: dict[str, object]) -> None:
    candidate = copy.deepcopy(value)
    candidate["self_sha256"] = ""
    value["self_sha256"] = canonical_sha256(candidate)


def test_g0_repository_contract_validates() -> None:
    report = validate_m26_g0(ROOT)
    assert report["status"] == "m26_g0_governance_adoption_valid"
    assert report["stage_count"] == 10
    assert report["alias_count"] == 9
    assert report["m25_status"] == "m25_closed"
    assert report["live_execution"] is False
    assert report["provider_execution"] is False
    assert report["answer_generation"] is False
    assert report["production_mutation"] is False
    assert report["secret_access"] is False


def test_deterministic_artifact_replay() -> None:
    assert validate_m26_g0(ROOT) == validate_m26_g0(ROOT)


def test_changed_file_allowlist_exact() -> None:
    validate_changed_files(sorted(EXPECTED_CHANGED_FILES))


def test_changed_file_allowlist_rejects_missing_file() -> None:
    files = set(EXPECTED_CHANGED_FILES)
    files.remove("tests/test_m26_g0_governance_reconciliation.py")
    with pytest.raises(GovernanceReconciliationError, match="allowlist"):
        validate_changed_files(files)


def test_changed_file_allowlist_rejects_protected_path() -> None:
    files = set(EXPECTED_CHANGED_FILES)
    files.add("production/pointer.json")
    with pytest.raises(GovernanceReconciliationError, match="allowlist"):
        validate_changed_files(files)


def test_owner_decision_unknown_authority_field_rejected() -> None:
    owner = load_json(ROOT / OWNER_DECISION)
    schema = load_json(ROOT / "schemas/m26-g0-governance-adoption-v1.schema.json")
    owner["authority_boundary"]["unknown_authority"] = False
    resign(owner)
    with pytest.raises(GovernanceReconciliationError, match="schema validation"):
        validate_schema(owner, schema)


def test_owner_decision_digest_tamper_rejected() -> None:
    owner = load_json(ROOT / OWNER_DECISION)
    owner["approved_by"] = "someone-else"
    with pytest.raises(GovernanceReconciliationError, match="digest"):
        verify_self_digest(owner)


def test_unified_v3_digest_tamper_rejected(tmp_path: Path) -> None:
    repo = copied_repo(tmp_path)
    owner = load_json(repo / OWNER_DECISION)
    owner["unified_specification"]["sha256"] = "0" * 64
    resign(owner)
    write_json(repo / OWNER_DECISION, owner)
    registry = load_json(repo / CONTRACT_REGISTRY)
    registry["artifacts"][OWNER_DECISION] = canonical_sha256(owner)
    resign(registry)
    write_json(repo / CONTRACT_REGISTRY, registry)
    with pytest.raises(GovernanceReconciliationError, match="schema validation|Unified v3"):
        validate_m26_g0(repo)


def test_historical_aliases_are_unique_and_exact() -> None:
    alias_map = load_json(ROOT / ALIAS_MAP)
    aliases = alias_map["aliases"]
    assert len({entry["historical_label"] for entry in aliases}) == 9
    assert len({entry["canonical_stage_id"] for entry in aliases}) == 9
    assert alias_map["canonical_status_catalog"] == CANONICAL_STATUS_CATALOG


def test_s9_s10_are_not_formal_pilot_or_final_closure() -> None:
    alias_map = load_json(ROOT / ALIAS_MAP)
    by_label = {entry["historical_label"]: entry for entry in alias_map["aliases"]}
    assert by_label["M26.9"]["classification"] == "synthetic_preflight"
    assert "pilot" in by_label["M26.9"]["non_equivalence_warning"]
    assert by_label["M26.10"]["classification"] == "synthetic_preflight"
    assert "final_answer" in by_label["M26.10"]["non_equivalence_warning"]


def test_pa5_and_pa7_obligations_are_preserved() -> None:
    alias_map = load_json(ROOT / ALIAS_MAP)
    obligations = alias_map["preserved_obligations"]
    assert "frozen_population_between_200_and_500_questions" in obligations["M26.PA.5"]
    assert "multiple_reviewers" in obligations["M26.PA.5"]
    assert "daniel_explicit_answer_serving_authority_outcome" in obligations["M26.PA.7"]
    assert "independent_final_reconciliation_and_m26_closure" in obligations["M26.PA.7"]


def test_stage_registry_has_no_cycles_or_skipped_predecessor() -> None:
    report = validate_m26_g0(ROOT)
    assert report["stage_count"] == 10
    registry = load_json(ROOT / STAGE_REGISTRY)
    assert registry["dependency_dag"]["M26.PA.2"] == ["M26.G0", "M26.PA.1"]
    assert registry["dependency_dag"]["M26.PA.7"] == ["M26.PA.6"]


def test_pa2_live_gate_requires_m25_and_daniel() -> None:
    registry = load_json(ROOT / STAGE_REGISTRY)
    pa2 = next(stage for stage in registry["stages"] if stage["stage_id"] == "M26.PA.2")
    assert "m25_closed" in pa2["daniel_gate"]
    assert "exact_read_only_live_run_approval" in pa2["daniel_gate"]
    assert "real_corpus_live_reads_without_m25_closed_and_daniel_exact_approval" in (
        pa2["denied_capabilities"]
    )


def test_pa1_ratifies_exact_historical_identity_without_live_authority() -> None:
    pa1 = load_json(ROOT / PA1_RATIFICATION)
    identity = pa1["historical_identity"]
    assert identity["issue_number"] == 1173
    assert identity["implementation_pr_number"] == 1174
    assert identity["implementation_head_sha"] == (
        "3cbfbcca9cc8c54e76fb63120bc0f34254904257"
    )
    assert identity["implementation_merge_sha"] == (
        "e8b5c63ea57a8df581a2792af267f3b22a65db3c"
    )
    assert identity["reconciliation_pr_number"] == 1175
    assert pa1["ratification"]["historical_artifacts_rewritten"] is False
    assert pa1["ratification"]["live_authority_granted"] is False
    assert all(value is False for value in pa1["authority_boundary"].values())


def test_legacy_pa2_is_candidate_only_and_not_merge_ready() -> None:
    candidate = load_json(ROOT / LEGACY_PA2)
    assert candidate["issue_number"] == 1176
    assert candidate["branch"] == "chatgpt/m26-12-real-corpus-binding"
    assert candidate["head_sha"] == "40061ebf66b057dca490708b7abbaa5988b4edb8"
    assert candidate["pull_request"] is None
    assert candidate["live_run"] is None
    assert candidate["acceptance"] is None
    assert candidate["do_not_merge"] is True
    assert candidate["do_not_run_live"] is True
    assert candidate["repair_required"] == {"P0": True, "P1": True}


def test_m25_closure_is_bound_to_final_reconciliation_not_pointer() -> None:
    owner = load_json(ROOT / OWNER_DECISION)
    snapshot = owner["repository_snapshot"]
    assert snapshot["m25_status"] == "m25_closed"
    assert snapshot["m25_evidence_path"] == "pilot/m25/m25-final-reconciliation.json"
    assert snapshot["m25_closure_not_inferred_from_pointer"] is True


def test_registry_inventory_and_digests_are_exact() -> None:
    registry = load_json(ROOT / CONTRACT_REGISTRY)
    expected = {
        OWNER_DECISION,
        ALIAS_MAP,
        STAGE_REGISTRY,
        PA1_RATIFICATION,
        LEGACY_PA2,
    }
    assert set(registry["artifacts"]) == expected
    for path in expected:
        assert registry["artifacts"][path] == canonical_sha256(load_json(ROOT / path))


def test_registry_tamper_is_rejected(tmp_path: Path) -> None:
    repo = copied_repo(tmp_path)
    registry = load_json(repo / CONTRACT_REGISTRY)
    registry["artifacts"][OWNER_DECISION] = "0" * 64
    resign(registry)
    write_json(repo / CONTRACT_REGISTRY, registry)
    with pytest.raises(GovernanceReconciliationError, match="registry mismatch"):
        validate_m26_g0(repo)


def test_dependency_cycle_is_rejected(tmp_path: Path) -> None:
    repo = copied_repo(tmp_path)
    registry = load_json(repo / STAGE_REGISTRY)
    registry["dependency_dag"]["M26.G0"] = ["M26.PA.7"]
    resign(registry)
    write_json(repo / STAGE_REGISTRY, registry)
    contract = load_json(repo / CONTRACT_REGISTRY)
    contract["artifacts"][STAGE_REGISTRY] = canonical_sha256(registry)
    resign(contract)
    write_json(repo / CONTRACT_REGISTRY, contract)
    with pytest.raises(GovernanceReconciliationError, match="cycle"):
        validate_m26_g0(repo)


def test_m25_pointer_only_cannot_be_used_as_closure(tmp_path: Path) -> None:
    repo = copied_repo(tmp_path)
    m25 = load_json(repo / "pilot/m25/m25-final-reconciliation.json")
    m25["result"] = "pointer_promoted"
    write_json(repo / "pilot/m25/m25-final-reconciliation.json", m25)
    with pytest.raises(GovernanceReconciliationError, match="formal M25 reconciliation"):
        validate_m26_g0(repo)
