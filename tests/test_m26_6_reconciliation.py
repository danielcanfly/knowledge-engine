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


def test_m26_6_acceptance_status_and_self_digest() -> None:
    acceptance = load(PILOT / "m26-6-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-6-acceptance/v1"
    assert acceptance["status"] == "m26_6_answer_evaluation_refusal_gate_accepted"
    assert acceptance["predecessor"] == {
        "status": "m26_5_draft_answer_contract_accepted",
        "main_seal_sha": "c76fe00af61a9eef97614b0e78ede0506593e671",
    }


def test_m26_6_acceptance_binds_implementation_and_issue() -> None:
    acceptance = load(PILOT / "m26-6-acceptance.json")
    assert acceptance["implementation"] == {
        "accepted_predecessor_main_seal_sha": "c76fe00af61a9eef97614b0e78ede0506593e671",
        "base_sha": "b456c0c33efb84df94aa4e4668bdbce22e2d955b",
        "changed_file_count": 11,
        "expected_head_merge": True,
        "final_head_sha": "ecd596e2e4346d03f5463c0696127b98bdef8c95",
        "merge_sha": "dd65419933a135349b3d54b6a1813fd46c70e569",
        "pull_request_number": 1079,
        "unresolved_review_thread_count": 0,
    }
    assert acceptance["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1078,
        "state": "closed",
        "state_reason": "completed",
    }


def test_m26_6_acceptance_records_zero_forbidden_authority() -> None:
    authority = load(PILOT / "m26-6-acceptance.json")["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["answer_evaluation"] is True
    assert authority["refusal_gate"] is True
    assert authority["draft_answer_contract_required"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key
        not in {
            "synthetic_only",
            "answer_evaluation",
            "refusal_gate",
            "draft_answer_contract_required",
        }
    }
    assert set(forbidden.values()) == {False}


def test_m26_6_acceptance_benchmark_and_evidence() -> None:
    acceptance = load(PILOT / "m26-6-acceptance.json")
    assert acceptance["benchmark"] == {
        "case_count": 12,
        "passed_count": 12,
        "failed_count": 0,
        "evaluation_passed_count": 6,
        "refusal_required_count": 6,
        "abstain_refusal_count": 3,
        "privacy_refusal_count": 1,
        "authority_refusal_count": 1,
        "citation_integrity_refusal_count": 1,
        "provider_call_count": 0,
        "credentials_used_count": 0,
        "live_network_call_count": 0,
        "real_corpus_binding_count": 0,
        "semantic_or_hybrid_use_count": 0,
        "production_answer_serving_count": 0,
        "verified_final_answer_count": 0,
    }
    assert acceptance["evidence_artifact"] == {
        "artifact_id": 8565255191,
        "name": "m26-6-answer-evaluation-evidence",
        "digest": "sha256:8fe69d57c1f8f481b5aa6a2e0ff9f488ec9af745e1012c5bc819157c34e9977f",
        "workflow_run_id": 30011487508,
        "retention_days": 30,
    }


def test_m26_6_acceptance_workflows_and_next_stage() -> None:
    acceptance = load(PILOT / "m26-6-acceptance.json")
    assert acceptance["required_workflows"] == {
        "CI": 30011487409,
        "M17 Architecture Canon Acceptance": 30011487298,
        "M18 Graph v2 acceptance": 30011487152,
        "M26.1 Architecture Authority": 30011487357,
        "M26.4 Provider Mock Replay": 30011487408,
        "M26.5 Draft Answer Contract": 30011487237,
        "M26.6 Answer Evaluation Refusal Gate": 30011487508,
        "R2 Release Integration": 30011487363,
    }
    assert acceptance["next_stage"] == {
        "stage_id": "M26.7",
        "name": "Synthetic Answer Presentation Contract and Non-Serving Preview",
        "authorized": True,
        "predecessor_status_required": "m26_6_answer_evaluation_refusal_gate_accepted",
        "synthetic_only": True,
        "presentation_contract_permitted": True,
        "live_provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "production_answer_serving_permitted": False,
        "verified_final_answer_permitted": False,
        "production_pointer_mutation_permitted": False,
    }


def test_m26_6_acceptance_quality_and_docs() -> None:
    acceptance = load(PILOT / "m26-6-acceptance.json")
    assert set(acceptance["quality_and_security"].values()) == {True}
    assert set(acceptance["reconciliation"].values()) == {True}
    text = (DOCS / "m26-6-reconciliation.md").read_text(encoding="utf-8")
    assert "m26_6_answer_evaluation_refusal_gate_accepted" in text
    assert "verified final answers" in text
    assert "production answer serving" in text
    assert "M26.7" in text
