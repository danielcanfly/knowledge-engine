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


def test_m26_7_acceptance_status_and_self_digest() -> None:
    acceptance = load(PILOT / "m26-7-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-7-acceptance/v1"
    assert acceptance["status"] == "m26_7_answer_presentation_non_serving_preview_accepted"
    assert acceptance["predecessor"] == {
        "status": "m26_6_answer_evaluation_refusal_gate_accepted",
        "main_seal_sha": "1f2dfbba74d6df91baa946bbac82e343ea81750e",
    }


def test_m26_7_acceptance_binds_implementation_and_issue() -> None:
    acceptance = load(PILOT / "m26-7-acceptance.json")
    assert acceptance["implementation"] == {
        "accepted_predecessor_main_seal_sha": "1f2dfbba74d6df91baa946bbac82e343ea81750e",
        "base_sha": "421f70c5696910d51ce8d93e4940109ecf06c5e7",
        "changed_file_count": 11,
        "expected_head_merge": True,
        "final_head_sha": "6b08dd445c0372865afeae2025e0ca50199c55a1",
        "merge_sha": "6ec47ffa368980c67596a9859eaa9bb3a0e4a9aa",
        "pull_request_number": 1096,
        "unresolved_review_thread_count": 0,
    }
    assert acceptance["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1095,
        "state": "closed",
        "state_reason": "completed",
    }


def test_m26_7_acceptance_records_zero_forbidden_authority() -> None:
    authority = load(PILOT / "m26-7-acceptance.json")["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["answer_presentation"] is True
    assert authority["non_serving_preview"] is True
    forbidden_true = {
        key: value
        for key, value in authority.items()
        if key not in {"synthetic_only", "answer_presentation", "non_serving_preview"}
    }
    assert not any(forbidden_true.values())


def test_m26_7_acceptance_records_benchmark_and_evidence() -> None:
    acceptance = load(PILOT / "m26-7-acceptance.json")
    assert acceptance["benchmark"]["case_count"] == 12
    assert acceptance["benchmark"]["passed_count"] == 12
    assert acceptance["benchmark"]["failed_count"] == 0
    assert acceptance["benchmark"]["non_serving_preview_count"] == 6
    assert acceptance["benchmark"]["non_serving_refusal_preview_count"] == 6
    assert acceptance["benchmark"]["warning_preview_count"] == 2
    assert acceptance["benchmark"]["provider_call_count"] == 0
    assert acceptance["benchmark"]["credentials_used_count"] == 0
    assert acceptance["benchmark"]["live_network_call_count"] == 0
    assert acceptance["benchmark"]["real_corpus_binding_count"] == 0
    assert acceptance["benchmark"]["semantic_or_hybrid_use_count"] == 0
    assert acceptance["benchmark"]["production_answer_serving_count"] == 0
    assert acceptance["benchmark"]["verified_final_answer_count"] == 0
    assert acceptance["benchmark"]["production_pointer_mutation_count"] == 0
    assert acceptance["evidence_artifact"] == {
        "artifact_id": 8574930488,
        "digest": "sha256:a13eab65c595013b4be1de4feaf321162ffedd8416eb2a799d5a6c51d4c0e191",
        "name": "m26-7-answer-presentation-evidence",
        "retention_days": 30,
        "workflow_run_id": 30035121490,
    }


def test_m26_7_acceptance_quality_and_reconciliation() -> None:
    acceptance = load(PILOT / "m26-7-acceptance.json")
    assert all(acceptance["quality_and_security"].values())
    assert all(acceptance["reconciliation"].values())
    assert acceptance["next_stage"] == {
        "authorized": True,
        "live_provider_calls_permitted": False,
        "name": "Synthetic Preview Evidence Integration and Candidate Bundle",
        "predecessor_status_required": "m26_7_answer_presentation_non_serving_preview_accepted",
        "preview_evidence_integration_permitted": True,
        "production_answer_serving_permitted": False,
        "production_pointer_mutation_permitted": False,
        "real_corpus_binding_permitted": False,
        "stage_id": "M26.8",
        "synthetic_only": True,
        "verified_final_answer_permitted": False,
    }


def test_m26_7_reconciliation_doc_mentions_boundaries() -> None:
    doc = (DOCS / "m26-7-reconciliation.md").read_text(encoding="utf-8")
    assert "m26_7_answer_presentation_non_serving_preview_accepted" in doc
    assert "production pointer mutation" in doc
    assert "verified final answers" in doc
