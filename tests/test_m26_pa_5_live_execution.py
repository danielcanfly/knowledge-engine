from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_pa5_controlled_internal_pilot import canonical_sha256
from knowledge_engine.m26_pa5_live_execution import (
    FAILURE_RECEIPT_SCHEMA_PATH,
    MAX_PROVIDER_CALLS,
    MAX_SPEND_USD,
    OWNER_DECISION_PATH,
    OWNER_DECISION_SCHEMA_PATH,
    POPULATION_COUNT,
    POPULATION_SHA256,
    SUCCESS_RECEIPT_SCHEMA_PATH,
    TRIGGER_MARKER,
    failure_receipt,
    run_pilot,
    validate_static,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-5-controlled-internal-pilot.yml"
ARCH_WORKFLOW = ROOT / ".github" / "workflows" / "m26-1-architecture-authority.yml"
PA4_WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-4-verified-answer-citation-gate.yml"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_schema(value: dict[str, Any], schema_path: Path) -> None:
    schema = load(ROOT / schema_path)
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []


def assert_self_digest(value: dict[str, Any]) -> None:
    expected = value["self_sha256"]
    candidate = dict(value)
    candidate["self_sha256"] = ""
    assert canonical_sha256(candidate) == expected


def fake_provider(payload: dict[str, Any]) -> dict[str, Any]:
    message = json.loads(payload["messages"][0]["content"][0]["text"])
    if message["role"] == "independent_blind_review":
        body = {"verdict": "pass", "reason_codes": ["BLIND_REVIEW_PASS"]}
    elif message["abstention_class"]:
        body = {
            "answer_status": "abstained",
            "safe_terminal": True,
            "reason_codes": ["SAFE_ABSTENTION"],
            "material_claim_count": 0,
            "citation_locator_count": 0,
            "unsupported_material_claim_count": 0,
        }
    else:
        body = {
            "answer_status": "answered",
            "safe_terminal": True,
            "reason_codes": ["ANSWER_SUPPORTED_BY_ACCEPTED_IDENTITY"],
            "material_claim_count": 1,
            "citation_locator_count": 1,
            "unsupported_material_claim_count": 0,
        }
    return {
        "text": json.dumps(body, sort_keys=True),
        "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        "cost_usd": 0.001,
        "response_id": "fake",
        "model": "MiniMax-M3",
    }


def test_pa5_owner_decision_static_contract() -> None:
    decision = load(ROOT / OWNER_DECISION_PATH)
    assert_schema(decision, OWNER_DECISION_SCHEMA_PATH)
    assert_self_digest(decision)
    parsed = decision["parsed_parameters"]
    assert parsed["live_wiring_issue"] == 1214
    assert parsed["frozen_population_count"] == POPULATION_COUNT
    assert parsed["frozen_population_sha256"] == POPULATION_SHA256
    assert parsed["future_trigger_marker"] == TRIGGER_MARKER
    assert parsed["budgets"]["maximum_provider_calls"] == MAX_PROVIDER_CALLS
    assert parsed["budgets"]["maximum_total_observed_spend_usd"] == MAX_SPEND_USD
    assert validate_static(ROOT) == {
        "logical_attempt": 1,
        "max_provider_calls": 600,
        "max_spend_usd": 15.0,
        "owner_decision_self_sha256": decision["self_sha256"],
        "population_count": 200,
        "population_sha256": POPULATION_SHA256,
        "trigger_marker": TRIGGER_MARKER,
    }


def test_pa5_live_runner_emits_sanitized_success_receipt_with_fake_provider() -> None:
    receipt = run_pilot(
        root=ROOT,
        provider_call=fake_provider,
        generated_at="2026-07-29T02:30:00Z",
        workflow={
            "repository": "danielcanfly/knowledge-engine",
            "workflow_name": "M26.PA.5 Controlled Internal Shadow Pilot",
            "run_id": "test",
            "run_attempt": "1",
            "head_sha": "a" * 40,
            "trigger_marker": TRIGGER_MARKER,
        },
    )
    assert_schema(receipt, SUCCESS_RECEIPT_SCHEMA_PATH)
    assert_self_digest(receipt)
    assert receipt["population"]["complete_denominator"] is True
    assert receipt["summary"]["population_count"] == 200
    assert receipt["summary"]["metrics"]["provider_calls"] == 400
    assert receipt["summary"]["metrics"]["total_observed_spend_usd"] == 0.4
    assert len(receipt["per_question_evidence"]) == 200
    assert len(receipt["human_review_packet"]["stratified_sample_question_ids"]) == 20
    serialized = json.dumps(receipt, sort_keys=True)
    assert "raw corpus" not in serialized.lower()
    assert "provider response" not in serialized.lower()
    assert "MINIMAX_API_KEY" not in serialized


def test_pa5_failure_receipt_is_schema_valid_and_sanitized() -> None:
    receipt = failure_receipt(
        root=ROOT,
        generated_at="2026-07-29T02:30:00Z",
        workflow={"repository": "danielcanfly/knowledge-engine", "run_attempt": "1"},
        error=RuntimeError("full provider body must not be persisted"),
    )
    assert_schema(receipt, FAILURE_RECEIPT_SCHEMA_PATH)
    assert_self_digest(receipt)
    assert receipt["status"] == "controlled_internal_shadow_pilot_failed_closed"
    assert "full provider body" in receipt["error"]["message"]


def test_pa5_workflow_separates_pr_static_ci_from_future_live_trigger() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "static-authorization:\n    if: github.event_name == 'pull_request'" in workflow
    assert "test -z \"${MINIMAX_API_KEY:-}\"" in workflow
    assert "live-controlled-internal-pilot:" in workflow
    assert TRIGGER_MARKER in workflow
    assert "environment: m23-r3-diagnostic" in workflow
    assert "MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}" in workflow
    assert "python -m knowledge_engine.m26_pa5_live_execution --execute" in workflow
    assert "actions/upload-artifact@v4" in workflow

    arch = ARCH_WORKFLOW.read_text(encoding="utf-8")
    assert "src/knowledge_engine/m26_pa5_live_execution.py" in arch

    pa4 = PA4_WORKFLOW.read_text(encoding="utf-8")
    assert "schemas/m26-pa-5-success-receipt-v1.schema.json" in pa4
    assert "tests/test_m26_pa_5_live_execution.py" in pa4
