from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from knowledge_engine.m25_formal_closure import self_digest
from knowledge_engine.m25_reconciliation import (
    M25ReconciliationError,
    load_json,
    validate_repository_reconciliation,
)

ROOT = Path(__file__).resolve().parents[1]
RECONCILIATION = ROOT / "pilot" / "m25" / "m25-final-reconciliation.json"


def test_m25_final_reconciliation_validates() -> None:
    assert validate_repository_reconciliation(ROOT) == {
        "status": "m25_final_reconciliation_valid",
        "result": "m25_closed",
        "closure_merge_sha": "dd373e932b75c89de3bdea45e581fd0df512c40b",
        "workflow_run_count": 6,
        "authority_false_count": 12,
    }


def test_m25_final_reconciliation_self_digest_is_stable() -> None:
    reconciliation = load_json(RECONCILIATION)
    assert reconciliation["self_sha256"] == self_digest(reconciliation)
    assert reconciliation["result"] == "m25_closed"
    assert reconciliation["closure_pr"]["expected_head_merge"] is True


def test_m25_final_reconciliation_records_required_artifact_digests() -> None:
    reconciliation = load_json(RECONCILIATION)
    assert reconciliation["owner_decision"]["self_sha256"] == (
        "4a340df130df29c57e32bac80eaebc9e5b428aae80b6e8cdda4bff7e98809629"
    )
    assert reconciliation["final_acceptance"]["self_sha256"] == (
        "15012cfa708c7c19cf1be91ac6ea566886c3728b880fdf42d4b9d7b5f0bbc4ed"
    )
    assert reconciliation["closure_evidence"]["self_sha256"] == (
        "0fd453e708ab940dbc123577f239fb45cf1d8b6057ec6223dbc6fbbc55167a91"
    )
    assert reconciliation["closure_workflow_artifact"]["digest"] == (
        "sha256:7203dfa9b935dd0f05a30227ce7ae4aa81a29ede776d1b4bc3500d0e11cb7f48"
    )


def test_m25_final_reconciliation_keeps_authority_boundaries_closed() -> None:
    reconciliation = load_json(RECONCILIATION)
    authority = reconciliation["authority_boundaries"]
    assert authority["m25_closed"] is True
    assert authority["bounded_large_scale_ingestion_readiness"] is True
    for key, value in authority.items():
        if key not in {"m25_closed", "bounded_large_scale_ingestion_readiness"}:
            assert value is False


def test_m25_final_reconciliation_tampering_fails_closed(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "pilot" / "m25", tmp_path / "pilot" / "m25")
    reconciliation = load_json(RECONCILIATION)
    reconciliation["closure_pr"]["head_sha"] = "0" * 40
    tampered = tmp_path / "pilot" / "m25" / "m25-final-reconciliation.json"
    tampered.write_text(json.dumps(reconciliation, sort_keys=True), encoding="utf-8")
    with pytest.raises(M25ReconciliationError, match="self digest mismatch"):
        from knowledge_engine.m25_reconciliation import validate_reconciliation

        validate_reconciliation(tmp_path)
