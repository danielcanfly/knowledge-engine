from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "pilot" / "m25" / "m25-2-acceptance.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m25_2_acceptance_contract_is_closed_and_exact() -> None:
    value = load(ACCEPTANCE)
    assert value["schema_version"] == "knowledge-engine-m25-2-acceptance/v1"
    assert value["status"] == "m25_2_intake_orchestrator_accepted"
    assert value["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1040,
        "state": "closed",
        "state_reason": "completed",
    }
    assert value["implementation"] == {
        "pull_request_number": 1041,
        "identity_resolution": "github_api_and_merge_ancestry",
        "merged_required": True,
        "exact_head_workflows_required": True,
    }
    assert value["next_stage"]["stage_id"] == "M25.3"


def test_required_workflows_and_artifacts_are_complete() -> None:
    value = load(ACCEPTANCE)
    assert set(value["required_workflows"]) == {
        "CI",
        "M17 Architecture Canon Acceptance",
        "M18 Graph v2 acceptance",
        "M25.1 Admission Architecture Freeze",
        "M25.2 Intake Orchestrator",
    }
    for relative in value["accepted_artifact_paths"]:
        assert (ROOT / relative).is_file(), relative
    assert len(value["accepted_artifact_paths"]) == len(set(value["accepted_artifact_paths"]))


def test_authority_and_population_gates_remain_closed() -> None:
    value = load(ACCEPTANCE)
    assert all(item is False for item in value["protected_mutations"].values())
    gates = value["acceptance_gates"]
    assert gates["no_silent_exclusion"] is True
    assert gates["unresolved_policy_fail_closed"] is True
    assert gates["candidate_only_outputs"] is True
    assert gates["unresolved_review_threads"] == 0
    assert value["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_used": False,
        "codex_escalations": 0,
        "daniel_gate_required": False,
    }
    assert value["reconciliation"] == {
        "resolved_identity_artifact_required": True,
        "implementation_merge_is_required_ancestor": True,
        "no_new_authority_granted": True,
    }
