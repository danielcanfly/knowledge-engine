from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_retrieval_envelope import verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_pa3_acceptance_binds_successful_minimax_live_evidence() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-pa-3-acceptance/v1"
    assert acceptance["stage_id"] == "M26.PA.3"
    assert acceptance["status"] == "m26_pa_3_live_provider_execution_accepted"
    assert acceptance["effective_only_on_reconciliation_merge"] is True

    predecessor = acceptance["predecessor"]
    assert predecessor["pa2_status"] == "m26_pa_2_real_corpus_retrieval_binding_accepted"
    assert predecessor["pa2_acceptance_self_sha256"] == (
        "f6f597699390135b0bf7a8e31417c2e8e6f48af2dc2af4168eca1fd1e7f24f67"
    )

    evidence = acceptance["live_evidence"]
    assert evidence["artifact_id"] == 8664397892
    assert evidence["artifact_name"] == "m26-pa-3-live-provider-evidence-attempt-4"
    assert evidence["artifact_local_receipt_path"] == (
        "/tmp/m26-pa3-attempt4-artifact-1785178119/m26-pa-3-live-provider-receipt.json"
    )
    assert evidence["run_id"] == 30295355209
    assert evidence["run_attempt"] == 1
    assert evidence["workflow_name"] == "M26.PA.3 Live Provider Execution Gate"
    assert evidence["receipt_self_sha256"] == (
        "eca49a290d587449b9c3d0dc369ac7893890bc83767a983abd097bce7adecec2"
    )


def test_pa3_acceptance_keeps_downstream_authority_closed() -> None:
    acceptance = load(PILOT / "m26-pa-3-acceptance.json")
    authority = acceptance["receipt_authority"]
    assert authority["provider_calls"] == 1
    assert authority["credential_names"] == ["MINIMAX_API_KEY"]
    assert authority["secret_values_persisted"] is False
    assert authority["raw_text_persisted"] is False
    assert authority["vectors_requested"] is False
    assert authority["vectors_returned"] is False
    assert authority["source_foundation_release_mutations"] == 0

    forbidden_zero = (
        "r2_write_operations",
        "qdrant_write_operations",
        "public_shadow_canary_traffic_operations",
    )
    assert all(authority[key] == 0 for key in forbidden_zero)
    assert acceptance["next_stage"] == {
        "name": "Verified Answer and Citation Gate",
        "stage_id": "M26.PA.4",
        "predecessor_status_required": "m26_pa_3_live_provider_execution_accepted",
        "production_serving_permitted": False,
        "public_shadow_canary_traffic_permitted": False,
        "verified_answer_candidate_policy_required": True,
    }


def test_pa3_reconciliation_doc_records_accepted_attempt_4() -> None:
    reconciliation_doc = (DOCS / "m26-pa-3-reconciliation.md").read_text(encoding="utf-8")
    assert "30295355209" in reconciliation_doc
    assert "8664397892" in reconciliation_doc
    assert "MiniMax-M3" in reconciliation_doc
    assert "no production answer" in reconciliation_doc
    assert "M26.PA.4" in reconciliation_doc
