from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "pilot" / "m25" / "m25-3-acceptance.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m25_3_acceptance_contract_is_closed_and_exact() -> None:
    value = load(ACCEPTANCE)
    assert value["schema_version"] == "knowledge-engine-m25-3-acceptance/v1"
    assert value["status"] == "m25_3_extraction_worker_accepted"
    assert value["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1043,
        "state": "closed",
        "state_reason": "completed",
    }
    assert value["implementation"] == {
        "pull_request_number": 1044,
        "base_sha": "cc83a1e6bae1dce45fca50d3fdb515c26a70d0f9",
        "head_sha": "d0fbd585215b35313d058d5e5921557a725276fa",
        "merge_sha": "2dfb8b705ea28ea4d3cc8513aa341d58098a5a10",
        "identity_resolution": "github_api_merge_ancestry_workflows_and_artifact_digest",
        "merged_required": True,
        "exact_head_workflows_required": True,
    }


def test_required_workflows_and_evidence_are_exact() -> None:
    value = load(ACCEPTANCE)
    assert value["required_workflows"] == {
        "CI": 29962705580,
        "M17 Architecture Canon Acceptance": 29962705578,
        "M17 Independent Operator GA Acceptance": 29962705723,
        "M18 Graph v2 acceptance": 29962705640,
        "M25.2 Intake Orchestrator": 29962705605,
        "M25.3 Extraction Worker": 29962705632,
        "R2 Release Integration": 29962705671,
    }
    assert value["implementation_evidence"] == {
        "workflow_run_id": 29962705632,
        "artifact_name": "m25-3-extraction-worker-evidence",
        "artifact_digest": (
            "sha256:e440fe73a1f21a78c233399da31d8f4c57fea1b84735b95f46f336cc014c9518"
        ),
        "artifact_retention_days": 30,
    }


def test_accepted_surfaces_exist_without_duplicates() -> None:
    value = load(ACCEPTANCE)
    accepted = value["accepted_artifact_paths"]
    hardened = value["bounded_predecessor_hardening_paths"]
    assert len(accepted) == len(set(accepted))
    assert len(hardened) == len(set(hardened))
    assert set(accepted).isdisjoint(hardened)
    for relative in [*accepted, *hardened]:
        assert (ROOT / relative).is_file(), relative


def test_authority_and_extraction_gates_remain_closed() -> None:
    value = load(ACCEPTANCE)
    gates = value["acceptance_gates"]
    assert gates["dedicated_exact_head_ci_green"] is True
    assert gates["global_ci_green"] is True
    assert gates["m25_2_forward_compat_green"] is True
    assert gates["provider_neutral_interface"] is True
    assert gates["recorded_response_replay_only"] is True
    assert gates["deterministic_request_response_candidate_and_receipt"] is True
    assert gates["all_candidates_evidence_bound"] is True
    assert gates["provider_authority_escalation_fail_closed"] is True
    assert gates["secret_like_content_fail_closed"] is True
    assert gates["raw_source_text_absent_from_request_and_receipt"] is True
    assert gates["candidate_only_outputs"] is True
    assert gates["live_provider_calls_permitted"] is False
    assert gates["credentials_used"] is False
    assert gates["unresolved_review_threads"] == 0
    assert all(item is False for item in value["protected_mutations"].values())
    assert value["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_used": False,
        "codex_escalations": 0,
        "daniel_gate_required": False,
    }
    assert value["reconciliation"] == {
        "resolved_identity_artifact_required": True,
        "implementation_merge_is_required_ancestor": True,
        "implementation_evidence_digest_required": True,
        "no_new_authority_granted": True,
    }


def test_m25_4_is_the_only_authorized_next_stage() -> None:
    value = load(ACCEPTANCE)
    assert value["next_stage"] == {
        "authorized": True,
        "stage_id": "M25.4",
        "name": "Concept Identity Gold Set and Benchmark",
        "predecessor_status_required": "m25_3_extraction_worker_accepted",
    }
