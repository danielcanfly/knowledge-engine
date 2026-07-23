from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from knowledge_engine.m25_review_surface import DecisionLedger, DecisionRequest, load_json

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"
SCHEMAS = ROOT / "schemas"
BATCH = load_json(PILOT / "m25-6-review-batch.json")
PLAN = load_json(PILOT / "m25-6-browser-acceptance-plan.json")
GATE = load_json(PILOT / "m25-6-readiness-gate.json")


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def test_committed_batch_validates_against_closed_schema() -> None:
    Draft202012Validator(_schema("m25-review-batch-v1.schema.json")).validate(BATCH)


def test_request_record_and_audit_validate_against_schemas(tmp_path: Path) -> None:
    item = next(value for value in BATCH["items"] if "approve" in value["allowed_actions"])
    request = DecisionRequest(
        batch_sha256=BATCH["batch_sha256"],
        review_item_id=item["review_item_id"],
        expected_review_state_sha256=item["review_state_sha256"],
        expected_ledger_head_sha256=None,
        reviewer="browser-reviewer",
        action="approve",
        rationale="Contract validation.",
        evidence_reviewed=True,
        comparison_reviewed=True,
        diff_reviewed=True,
        decided_at="2026-07-23T06:00:00+00:00",
    )
    request_payload = request.model_dump()
    Draft202012Validator(_schema("m25-review-decision-request-v1.schema.json")).validate(
        request_payload
    )
    ledger = DecisionLedger(tmp_path / "ledger")
    record = ledger.append(BATCH, request)
    Draft202012Validator(_schema("m25-review-decision-record-v1.schema.json")).validate(record)
    audit = ledger.export(BATCH)
    Draft202012Validator(_schema("m25-review-audit-export-v1.schema.json")).validate(audit)


def test_browser_plan_covers_all_actions_and_gate_waits_for_daniel() -> None:
    assert PLAN["status"] == "awaiting_daniel_browser_acceptance"
    assert {scenario["action"] for scenario in PLAN["scenarios"]} == {
        "approve",
        "map",
        "edit",
        "split",
        "reject",
        "defer",
    }
    assert PLAN["authentication"]["unauthenticated_review_ui_permitted"] is False
    assert PLAN["m25_7_authorized"] is False
    assert GATE["status"] == "m25_6_awaiting_daniel_browser_acceptance"
    assert GATE["exit_gates"]["daniel_browser_acceptance_recorded"] is False
    assert GATE["m25_7_authorized"] is False
    assert not any(GATE["protected_mutations"].values())
