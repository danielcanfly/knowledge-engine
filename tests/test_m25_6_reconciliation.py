from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"
ACCEPTANCE = json.loads((PILOT / "m25-6-acceptance.json").read_text())
BATCH_BYTES = (PILOT / "m25-6-review-batch.json").read_bytes()
PLAN_BYTES = (PILOT / "m25-6-browser-acceptance-plan.json").read_bytes()
GATE_BYTES = (PILOT / "m25-6-readiness-gate.json").read_bytes()
BATCH = json.loads(BATCH_BYTES)
PLAN = json.loads(PLAN_BYTES)
GATE = json.loads(GATE_BYTES)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_acceptance_identity_and_evidence_binding() -> None:
    assert ACCEPTANCE["status"] == "m25_6_review_surface_accepted"
    assert ACCEPTANCE["implementation"] == {
        "pull_request_number": 1057,
        "base_sha": "d3cf8cc72d951174f10c0a8328f848143c24e004",
        "final_head_sha": "bf6ec965851f139e2dafa008c3efcab856ea6e77",
        "merge_sha": "dd1559f7730c796933dfe0996acc0a558870a61e",
        "changed_file_count": 17,
        "unresolved_review_thread_count": 0,
        "expected_head_merge": True,
    }
    assert ACCEPTANCE["daniel_browser_acceptance"]["authority_comment_id"] == 5056370409
    assert ACCEPTANCE["daniel_browser_acceptance"]["accepted_screenshot_count"] == 12
    assert ACCEPTANCE["frozen_identities"]["review_batch_file_sha256"] == sha256(BATCH_BYTES)
    assert ACCEPTANCE["frozen_identities"]["browser_acceptance_plan_sha256"] == sha256(PLAN_BYTES)
    assert ACCEPTANCE["frozen_identities"]["readiness_gate_sha256"] == sha256(GATE_BYTES)
    assert ACCEPTANCE["evidence_artifact"]["artifact_id"] == 8556895980
    assert ACCEPTANCE["evidence_artifact"]["digest"] == (
        "sha256:5013f7a2b8a655e48564d4769c175a3a6704b3ddde4c3222d9caa2588dcf01f0"
    )


def test_browser_population_and_product_contract() -> None:
    population = ACCEPTANCE["browser_population"]
    assert population["review_item_count"] == 30
    assert population["scenario_count"] == 6
    assert population["decision_count"] == 6
    assert population["terminal_item_count"] == 5
    assert population["deferred_item_count"] == 1
    assert population["pending_item_count"] == 24
    assert population["review_complete"] is False
    assert population["admission_ready"] is False
    assert population["unauthenticated_review_status"] == 401
    assert population["all_scenarios_passed"] is True
    assert BATCH["item_count"] == 30
    assert BATCH["bulk_approval_permitted"] is False
    assert set(BATCH["decision_actions"]) == {
        "approve",
        "map",
        "edit",
        "split",
        "reject",
        "defer",
    }
    assert PLAN["daniel_browser_acceptance_required"] is True
    assert GATE["status"] == "m25_6_awaiting_daniel_browser_acceptance"


def test_authority_and_next_stage_boundaries() -> None:
    governance = ACCEPTANCE["governance"]
    assert governance["candidate_only"] is True
    assert governance["admission_decision_only"] is True
    assert governance["immutable_append_only_ledger"] is True
    assert governance["valid_hash_chain"] is True
    assert governance["stale_state_fails_closed"] is True
    assert governance["bulk_approval_permitted"] is False
    assert governance["source_write_permitted"] is False
    assert governance["github_pr_creation_permitted"] is False
    assert governance["canonical_knowledge"] is False
    assert governance["production_authority"] is False
    assert governance["m25_7_authorized"] is False
    assert not any(ACCEPTANCE["protected_mutations"].values())
    assert ACCEPTANCE["execution_roles"]["codex_used"] is False
    assert ACCEPTANCE["execution_roles"]["daniel_gate_satisfied"] is True
    assert ACCEPTANCE["next_stage"]["stage_id"] == "M25.7"
    assert ACCEPTANCE["next_stage"]["authorized"] is False
    assert ACCEPTANCE["next_stage"]["requires_separate_daniel_instruction"] is True
    assert ACCEPTANCE["next_stage"]["not_authorized_by_browser_acceptance"] is True
