from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_retrieval_envelope import verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m26_9_acceptance_contract() -> None:
    acceptance = load(PILOT / "m26-9-acceptance.json")
    verify_self_digest(acceptance)
    assert acceptance["schema_version"] == "knowledge-engine-m26-9-acceptance/v1"
    assert acceptance["status"] == "m26_9_candidate_qa_feedback_baseline_refresh_accepted"
    assert acceptance["self_sha256"] == (
        "919a2688787fcef9ff8520836f03af9d5928097b143f127433d7b97dc6b32289"
    )
    assert acceptance["implementation"]["pull_request_number"] == 1166
    assert acceptance["implementation"]["final_head_sha"] == (
        "926f2c1eefe0a4292c7ace41a51fca0f9897dc53"
    )
    assert acceptance["implementation"]["merge_sha"] == (
        "f91d14f6b75053670c1ce2b517134e7c75ab8db0"
    )
    assert acceptance["issue"]["number"] == 1165
    assert acceptance["issue"]["state"] == "closed"
    assert acceptance["benchmark"]["case_count"] == 12
    assert acceptance["benchmark"]["passed_count"] == 12
    assert acceptance["benchmark"]["failed_count"] == 0


def test_m26_9_acceptance_authority_boundary() -> None:
    authority = load(PILOT / "m26-9-acceptance.json")["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["candidate_qa_feedback"] is True
    assert authority["baseline_refresh_planning"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key
        not in {
            "synthetic_only",
            "candidate_qa_feedback",
            "baseline_refresh_planning",
        }
    }
    assert not any(forbidden.values())


def test_m26_9_acceptance_evidence_and_next_stage() -> None:
    acceptance = load(PILOT / "m26-9-acceptance.json")
    artifact = acceptance["evidence_artifact"]
    assert artifact["artifact_id"] == 8605302196
    assert artifact["workflow_run_id"] == 30115648240
    assert artifact["digest"] == (
        "sha256:d7b702c0c8ccacba765e96160b46097e07d496b19e25767ab3aae17bdb8e9ec6"
    )
    assert acceptance["required_workflows"]["M26.9 Candidate QA Feedback"] == 30115648240
    assert acceptance["required_workflows"]["CI"] == 30115648288
    next_stage = acceptance["next_stage"]
    assert next_stage["stage_id"] == "M26.10"
    assert next_stage["authorized"] is True
    assert next_stage["synthetic_only"] is True
    assert next_stage["baseline_refresh_execution_permitted"] is False
    assert next_stage["production_answer_serving_permitted"] is False
    assert next_stage["verified_final_answer_permitted"] is False


def test_m26_9_acceptance_frozen_identities_match_registry() -> None:
    acceptance = load(PILOT / "m26-9-acceptance.json")
    registry = load(PILOT / "m26-9-contract-registry.json")
    verify_self_digest(registry)
    assert registry["self_sha256"] == acceptance["frozen_identities"]["contract_registry_self_sha256"]
    for key, value in registry["artifacts"].items():
        acceptance_key = {
            "baseline_plan_schema_sha256": "baseline_plan_schema_sha256",
            "benchmark_cases_sha256": "benchmark_cases_sha256",
            "entry_contract_sha256": "entry_contract_sha256",
            "qa_feedback_schema_sha256": "qa_feedback_schema_sha256",
            "qa_policy_sha256": "qa_policy_sha256",
        }[key]
        assert value == acceptance["frozen_identities"][acceptance_key]
