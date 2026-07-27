from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from knowledge_engine.m26_real_corpus_binding import (
    CONTRACT_SCHEMA_PATH,
    ENTRY_PATH,
    FAILURE_SCHEMA_PATH,
    POLICY_PATH,
    RECEIPT_SCHEMA_PATH,
    REGISTRY_PATH,
    RealCorpusBindingError,
    canonical_sha256,
    load_json,
    validate_pa2_contracts,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def resign(value: dict[str, object]) -> None:
    value["self_sha256"] = ""
    value["self_sha256"] = canonical_sha256(value)


def copied_root(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(ROOT, target)
    return target


def refresh_registry(root: Path) -> None:
    registry = load_json(root / REGISTRY_PATH)
    entry = load_json(root / ENTRY_PATH)
    policy = load_json(root / POLICY_PATH)
    registry["artifacts"] = {
        "entry_contract_sha256": canonical_sha256(entry),
        "retrieval_policy_sha256": canonical_sha256(policy),
    }
    registry["schemas"] = {
        "contracts_schema_sha256": hashlib.sha256(
            (root / CONTRACT_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
        "receipt_schema_sha256": hashlib.sha256(
            (root / RECEIPT_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
        "failure_schema_sha256": hashlib.sha256(
            (root / FAILURE_SCHEMA_PATH).read_bytes()
        ).hexdigest(),
    }
    resign(registry)
    write_json(root / REGISTRY_PATH, registry)


def test_contract_chain_validates() -> None:
    report = validate_pa2_contracts(ROOT)
    assert report["status"] == "m26_pa_2_non_live_repair_contracts_valid"
    assert report["stage_id"] == "M26.PA.2"
    assert report["accepted"] is False
    assert report["live_execution"] is False
    assert report["provider_calls"] is False
    assert report["answer_generation"] is False
    assert report["production_mutation"] is False
    assert report["expected_point_count"] == 4197
    assert report["payload_field_count"] == 8
    assert report["legacy_candidate_merged"] is False


def test_contract_validation_is_deterministic() -> None:
    assert validate_pa2_contracts(ROOT) == validate_pa2_contracts(ROOT)


@pytest.mark.parametrize("path", [ENTRY_PATH, POLICY_PATH, REGISTRY_PATH])
def test_contract_self_digests_verify(path: str) -> None:
    verify_self_digest(load_json(ROOT / path), path)


@pytest.mark.parametrize("path", [ENTRY_PATH, POLICY_PATH, REGISTRY_PATH])
def test_contract_tamper_rejected(path: str, tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    value = load_json(root / path)
    value["self_sha256"] = "0" * 64
    write_json(root / path, value)
    with pytest.raises(RealCorpusBindingError, match="self digest mismatch"):
        validate_pa2_contracts(root)


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (ENTRY_PATH, "unexpected_entry_field"),
        (POLICY_PATH, "unexpected_policy_field"),
        (REGISTRY_PATH, "unexpected_registry_field"),
    ],
)
def test_unknown_contract_field_rejected(path: str, field: str, tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    value = load_json(root / path)
    value[field] = False
    resign(value)
    write_json(root / path, value)
    refresh_registry(root)
    with pytest.raises(RealCorpusBindingError, match="strict schema validation"):
        validate_pa2_contracts(root)


def test_registry_child_digest_drift_rejected(tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    registry = load_json(root / REGISTRY_PATH)
    registry["artifacts"]["entry_contract_sha256"] = "0" * 64
    resign(registry)
    write_json(root / REGISTRY_PATH, registry)
    with pytest.raises(RealCorpusBindingError, match="child digest"):
        validate_pa2_contracts(root)


def test_registry_schema_digest_drift_rejected(tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    registry = load_json(root / REGISTRY_PATH)
    registry["schemas"]["receipt_schema_sha256"] = "0" * 64
    resign(registry)
    write_json(root / REGISTRY_PATH, registry)
    with pytest.raises(RealCorpusBindingError, match="schema digest"):
        validate_pa2_contracts(root)


def test_g0_identity_drift_rejected(tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    entry = load_json(root / ENTRY_PATH)
    entry["predecessors"]["g0_main_seal_sha"] = "0" * 40
    resign(entry)
    write_json(root / ENTRY_PATH, entry)
    refresh_registry(root)
    with pytest.raises(RealCorpusBindingError, match="schema validation|predecessor"):
        validate_pa2_contracts(root)


def test_g0_status_drift_rejected(tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    g0 = load_json(root / "pilot/m26/m26-g0-acceptance.json")
    g0["status"] = "not_accepted"
    resign(g0)
    write_json(root / "pilot/m26/m26-g0-acceptance.json", g0)
    entry = load_json(root / ENTRY_PATH)
    entry["predecessors"]["g0_acceptance_self_sha256"] = g0["self_sha256"]
    resign(entry)
    write_json(root / ENTRY_PATH, entry)
    schema = load_json(root / CONTRACT_SCHEMA_PATH)
    schema["oneOf"][0]["properties"]["predecessors"]["properties"]["g0_acceptance_self_sha256"] = {
        "const": g0["self_sha256"]
    }
    write_json(root / CONTRACT_SCHEMA_PATH, schema)
    refresh_registry(root)
    with pytest.raises(RealCorpusBindingError, match="G0 or PA.1"):
        validate_pa2_contracts(root)


def test_m25_pointer_promotion_alone_is_not_closure(tmp_path: Path) -> None:
    root = copied_root(tmp_path)
    m25 = load_json(root / "pilot/m25/m25-final-reconciliation.json")
    m25["result"] = "production_pointer_promoted"
    resign(m25)
    write_json(root / "pilot/m25/m25-final-reconciliation.json", m25)
    entry = load_json(root / ENTRY_PATH)
    entry["predecessors"]["m25_final_reconciliation_self_sha256"] = m25["self_sha256"]
    resign(entry)
    write_json(root / ENTRY_PATH, entry)
    schema = load_json(root / CONTRACT_SCHEMA_PATH)
    schema["oneOf"][0]["properties"]["predecessors"]["properties"][
        "m25_final_reconciliation_self_sha256"
    ] = {"const": m25["self_sha256"]}
    write_json(root / CONTRACT_SCHEMA_PATH, schema)
    refresh_registry(root)
    with pytest.raises(RealCorpusBindingError, match="M25 is not formally closed"):
        validate_pa2_contracts(root)


def test_payload_selector_is_exact_allowlist() -> None:
    policy = load_json(ROOT / POLICY_PATH)
    assert policy["qdrant"]["with_payload"] == policy["payload"]["allowlist"]
    assert policy["qdrant"]["with_payload"] is not True
    assert policy["qdrant"]["with_vector"] is False


def test_payload_policy_omits_raw_heading_and_origin_path() -> None:
    policy = load_json(ROOT / POLICY_PATH)
    fields = set(policy["payload"]["allowlist"])
    assert "text" not in fields
    assert "content" not in fields
    assert "heading" not in fields
    assert "origin_path" not in fields
    assert "article_id" not in fields
    assert fields == set(policy["payload"]["required_fields"])


def test_qdrant_filter_matches_m25_production_collection_semantics() -> None:
    policy = load_json(ROOT / POLICY_PATH)
    assert policy["qdrant"]["filter"]["candidate_release_eligible"] is True
    assert policy["qdrant"]["filter"]["production_authority"] is False


def test_read_only_credential_contracts_are_frozen() -> None:
    policy = load_json(ROOT / POLICY_PATH)
    assert policy["read_only"]["r2"]["allowed_operations"] == ["get"]
    assert policy["read_only"]["qdrant"]["allowed_operations"] == ["count", "scroll"]
    assert policy["read_only"]["r2"]["scope"] == "read_only"
    assert policy["read_only"]["qdrant"]["scope"] == "read_only"
    assert (
        policy["read_only"]["r2"]["credential_contract_sha256"]
        == "28929389da704c879907f66af6934f90e587f3260333bea72d3df4ffb2ffb0e0"
    )
    assert (
        policy["read_only"]["qdrant"]["credential_contract_sha256"]
        == "fbcc36fda02d3b8eaf0af777531ab2c2b7b5c357df72ae3cebe50e44b57dc42f"
    )


def test_authority_grants_only_non_live_repair() -> None:
    entry = load_json(ROOT / ENTRY_PATH)
    authority = entry["authority"]
    assert authority["non_live_p0_p1_repair"] is True
    assert all(
        (value is False for key, value in authority.items() if key != "non_live_p0_p1_repair")
    )


def test_legacy_candidate_remains_unmergeable_and_unrunnable() -> None:
    entry = load_json(ROOT / ENTRY_PATH)
    legacy = entry["legacy_candidate"]
    assert legacy["classification"] == "candidate_patch_only"
    assert legacy["do_not_merge"] is True
    assert legacy["do_not_rebase"] is True
    assert legacy["do_not_run_live"] is True
    registry = load_json(ROOT / REGISTRY_PATH)
    assert registry["legacy_candidate"]["merged"] is False
    assert registry["legacy_candidate"]["live_run"] is False


def test_code_only_merge_cannot_accept_pa2() -> None:
    entry = load_json(ROOT / ENTRY_PATH)
    assert entry["acceptance"] == {
        "code_only_merge_is_acceptance": False,
        "live_evidence_required": True,
        "daniel_exact_live_run_approval_required": True,
        "independent_reconciliation_required": True,
    }
    registry = load_json(ROOT / REGISTRY_PATH)
    assert registry["accepted"] is False
    assert registry["live_execution"] is False
