from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_pa5_controlled_internal_pilot import canonical_sha256
from knowledge_engine.m26_pa5_live_execution import (
    ATTEMPT_1_SEAL_PATH,
    ATTEMPT_1_SEAL_SCHEMA_PATH,
    ATTEMPT_2_SEAL_PATH,
    ATTEMPT_2_SEAL_SCHEMA_PATH,
    ATTEMPT_3_SEAL_PATH,
    ATTEMPT_3_SEAL_SCHEMA_PATH,
    ATTEMPT_4_SEAL_PATH,
    ATTEMPT_4_SEAL_SCHEMA_PATH,
    ATTEMPT_5_SEAL_PATH,
    ATTEMPT_5_SEAL_SCHEMA_PATH,
    FAILURE_RECEIPT_SCHEMA_PATH,
    MAX_PROVIDER_CALLS,
    MAX_SPEND_USD,
    OWNER_DECISION_PATH,
    OWNER_DECISION_SCHEMA_PATH,
    POPULATION_COUNT,
    POPULATION_SHA256,
    PRICING_CONTRACT_PATH,
    PRICING_CONTRACT_SCHEMA_PATH,
    REVIEWER_CONTRACT_PATH,
    REVIEWER_CONTRACT_SCHEMA_PATH,
    SUCCESS_RECEIPT_SCHEMA_PATH,
    THRESHOLD_SEMANTICS_PATH,
    THRESHOLD_SEMANTICS_SCHEMA_PATH,
    TRIGGER_MARKER,
    V6_EXHAUSTION_PATH,
    V6_EXHAUSTION_SCHEMA_PATH,
    MiniMaxM3Client,
    failure_receipt,
    provider_call_checked,
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
        assert message["bounded_review_envelope"]["raw_answer_text_included"] is False
        assert message["bounded_review_envelope"]["full_provider_response_included"] is False
        assert message["bounded_review_envelope"]["envelope_sha256"]
        body = {"verdict": "pass", "reason_codes": ["BLIND_REVIEW_PASS"]}
    elif message["abstention_class"]:
        body = {
            "answer_status": "abstained",
            "safe_terminal": True,
            "reason_codes": ["SAFE_ABSTENTION"],
            "material_claims": [],
        }
    else:
        body = {
            "answer_status": "answered",
            "safe_terminal": True,
            "reason_codes": ["ANSWER_SUPPORTED_BY_ACCEPTED_IDENTITY"],
            "material_claims": [
                {
                    "claim_id": "claim-1",
                    "claim_text": "bounded supported claim text",
                    "claim_type": "direct_fact",
                    "temporal_scope": "not_temporal",
                    "citations": [
                        {
                            "locator_id": "loc-1",
                            "locator_type": "accepted_corpus_locator",
                            "source_identity": "accepted source identity",
                            "evidence_excerpt": "bounded evidence excerpt",
                            "support_verdict": "supported",
                            "conflict_verdict": "no_conflict",
                            "temporal_verdict": "not_temporal",
                            "bounds_valid": True,
                        }
                    ],
                }
            ],
        }
    return {
        "text": json.dumps(body, sort_keys=True),
        "usage": {
            "input_tokens": 10,
            "output_tokens": 10,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
            "total_accounted_tokens": 25,
        },
        "response_id": "fake",
        "model": "MiniMax-M3",
    }


def fake_provider_with_one_malformed_answer(payload: dict[str, Any]) -> dict[str, Any]:
    if not hasattr(fake_provider_with_one_malformed_answer, "calls"):
        fake_provider_with_one_malformed_answer.calls = 0  # type: ignore[attr-defined]
    fake_provider_with_one_malformed_answer.calls += 1  # type: ignore[attr-defined]
    result = fake_provider(payload)
    message = json.loads(payload["messages"][0]["content"][0]["text"])
    if (
        fake_provider_with_one_malformed_answer.calls == 1  # type: ignore[attr-defined]
        and message["role"] == "answer_generation"
        and not message["repair_context"]
    ):
        result["text"] = '{"answer_status": "answered"\n"safe_terminal": true}'
        result["response_id"] = "fake-malformed"
    elif message["repair_context"]:
        result["response_id"] = "fake-bounded-repair"
    return result


def test_pa5_owner_decision_static_contract() -> None:
    decision = load(ROOT / OWNER_DECISION_PATH)
    assert_schema(decision, OWNER_DECISION_SCHEMA_PATH)
    assert_self_digest(decision)
    seal = load(ROOT / ATTEMPT_1_SEAL_PATH)
    assert_schema(seal, ATTEMPT_1_SEAL_SCHEMA_PATH)
    assert_self_digest(seal)
    attempt2_seal = load(ROOT / ATTEMPT_2_SEAL_PATH)
    assert_schema(attempt2_seal, ATTEMPT_2_SEAL_SCHEMA_PATH)
    assert_self_digest(attempt2_seal)
    attempt3_seal = load(ROOT / ATTEMPT_3_SEAL_PATH)
    assert_schema(attempt3_seal, ATTEMPT_3_SEAL_SCHEMA_PATH)
    assert_self_digest(attempt3_seal)
    attempt4_seal = load(ROOT / ATTEMPT_4_SEAL_PATH)
    assert_schema(attempt4_seal, ATTEMPT_4_SEAL_SCHEMA_PATH)
    assert_self_digest(attempt4_seal)
    attempt5_seal = load(ROOT / ATTEMPT_5_SEAL_PATH)
    assert_schema(attempt5_seal, ATTEMPT_5_SEAL_SCHEMA_PATH)
    assert_self_digest(attempt5_seal)
    reviewer_contract = load(ROOT / REVIEWER_CONTRACT_PATH)
    assert_schema(reviewer_contract, REVIEWER_CONTRACT_SCHEMA_PATH)
    assert_self_digest(reviewer_contract)
    threshold_semantics = load(ROOT / THRESHOLD_SEMANTICS_PATH)
    assert_schema(threshold_semantics, THRESHOLD_SEMANTICS_SCHEMA_PATH)
    assert_self_digest(threshold_semantics)
    v6_exhaustion = load(ROOT / V6_EXHAUSTION_PATH)
    assert_schema(v6_exhaustion, V6_EXHAUSTION_SCHEMA_PATH)
    assert_self_digest(v6_exhaustion)
    pricing = load(ROOT / PRICING_CONTRACT_PATH)
    assert_schema(pricing, PRICING_CONTRACT_SCHEMA_PATH)
    assert_self_digest(pricing)
    parsed = decision["parsed_parameters"]
    assert parsed["live_wiring_issue"] == 1224
    assert parsed["authority_package"]["package_sha256"] == (
        "087ea7bb8c270bccf958041b8a4eacfa9d8fff9177a731f093f95f991d6063af"
    )
    assert parsed["authority_package"]["logical_attempts_authorized"] == [6, 7, 8]
    assert parsed["frozen_population_count"] == POPULATION_COUNT
    assert parsed["frozen_population_sha256"] == POPULATION_SHA256
    assert parsed["future_trigger_marker"] == TRIGGER_MARKER
    assert parsed["budgets"]["maximum_provider_calls"] == MAX_PROVIDER_CALLS
    assert parsed["budgets"]["maximum_total_payg_equivalent_cost_usd"] == MAX_SPEND_USD
    assert parsed["billing"]["billing_mode"] == (
        "token_plan_subscription_with_payg_equivalent_cost_accounting"
    )
    assert parsed["billing"]["provider_reported_monetary_cost_available"] is False
    assert parsed["billing"]["provider_reported_monetary_cost_usd"] is None
    assert parsed["billing"]["automatic_prompt_cache_usage_allowed"] is True
    assert parsed["review_rules"]["human_review_completed"] is False
    assert parsed["review_rules"]["autonomous_review_amendment_applied"] is True
    assert parsed["review_rules"]["initial_disagreement_incident_stop"] is False
    assert parsed["review_rules"]["post_repair_disagreement_incident_stop_only"] is True
    assert reviewer_contract["bounded_review_envelope"][
        "same_envelope_for_model_and_deterministic_verifier"
    ] is True
    assert threshold_semantics["initial_disagreement"][
        "eligible_for_early_incident_stop"
    ] is False
    assert v6_exhaustion["status"] == "v6_attempt_window_exhausted_pa5_not_accepted"
    assert pricing["rates_per_1m_tokens"] == {
        "cache_creation_input_tokens": "0.375",
        "cache_read_input_tokens": "0.06",
        "input_tokens": "0.30",
        "output_tokens": "1.20",
    }
    assert validate_static(ROOT) == {
        "attempt_1_failure_seal_self_sha256": seal["self_sha256"],
        "attempt_2_failure_seal_self_sha256": attempt2_seal["self_sha256"],
        "attempt_3_failure_seal_self_sha256": attempt3_seal["self_sha256"],
        "attempt_4_failure_seal_self_sha256": attempt4_seal["self_sha256"],
        "attempt_5_failure_seal_self_sha256": attempt5_seal["self_sha256"],
        "billing_mode": "token_plan_subscription_with_payg_equivalent_cost_accounting",
        "logical_attempt": 6,
        "max_provider_calls": 800,
        "max_payg_equivalent_cost_usd": "20.00",
        "owner_decision_self_sha256": decision["self_sha256"],
        "population_count": 200,
        "population_sha256": POPULATION_SHA256,
        "pricing_contract_self_sha256": pricing["self_sha256"],
        "reviewer_contract_v2_self_sha256": reviewer_contract["self_sha256"],
        "threshold_semantics_v2_self_sha256": threshold_semantics["self_sha256"],
        "trigger_marker": TRIGGER_MARKER,
        "v6_exhaustion_record_self_sha256": v6_exhaustion["self_sha256"],
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
    assert receipt["summary"]["metrics"]["total_payg_equivalent_cost_usd"] == "0.00637200"
    assert receipt["summary"]["metrics"]["mean_payg_equivalent_cost_usd"] == "0.00003186"
    assert receipt["summary"]["metrics"]["provider_reported_monetary_cost_available"] is False
    assert receipt["summary"]["metrics"]["provider_reported_monetary_cost_usd"] is None
    assert receipt["summary"]["human_review_completed"] is False
    assert receipt["summary"]["autonomous_review_amendment_applied"] is True
    assert receipt["summary"]["automated_review_not_misrepresented_as_human"] is True
    assert len(receipt["per_question_evidence"]) == 200
    assert len(receipt["human_review_packet"]["stratified_sample_question_ids"]) == 20
    assert receipt["human_review_packet"]["packet_type"] == "owner_oversight_nonblocking_audit"
    first_receipts = receipt["per_question_evidence"][0]["provider_call_receipts"]
    assert first_receipts[0]["provider_reported_usage"]["input_tokens"] == 10
    assert first_receipts[0]["provider_reported_usage"]["cache_creation_input_tokens"] == 2
    assert first_receipts[0]["provider_reported_usage"]["cache_read_input_tokens"] == 3
    assert first_receipts[0]["payg_equivalent_cost_usd"] == "0.00001593"
    assert first_receipts[0]["provider_reported_monetary_cost_available"] is False
    assert first_receipts[0]["provider_reported_monetary_cost_usd"] is None
    assert receipt["per_question_evidence"][0]["owner_policy_result"][
        "autonomous_review_amendment_applied"
    ] is True
    assert receipt["summary"]["metrics"]["initial_reviewer_disagreement_count"] == 0
    assert receipt["summary"]["metrics"]["post_repair_reviewer_disagreement_count"] == 0
    assert receipt["per_question_evidence"][0]["bounded_review_envelope"][
        "claim_text_persisted"
    ] is False
    serialized = json.dumps(receipt, sort_keys=True)
    assert "bounded supported claim text" not in serialized
    assert "bounded evidence excerpt" not in serialized
    assert "raw corpus" not in serialized.lower()
    assert "provider response" not in serialized.lower()
    assert "MINIMAX_API_KEY" not in serialized


def test_pa5_live_runner_uses_one_sanitized_bounded_repair_for_json_parse() -> None:
    if hasattr(fake_provider_with_one_malformed_answer, "calls"):
        delattr(fake_provider_with_one_malformed_answer, "calls")
    receipt = run_pilot(
        root=ROOT,
        provider_call=fake_provider_with_one_malformed_answer,
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
    first = receipt["per_question_evidence"][0]
    assert first["repair_attempts_used"] == 1
    assert [item["call_class"] for item in first["provider_call_receipts"]] == [
        "answer_generation",
        "bounded_repair",
        "independent_blind_review",
    ]
    serialized = json.dumps(receipt, sort_keys=True)
    assert '{"answer_status": "answered"\n"safe_terminal": true}' not in serialized
    assert "malformed_response_digest" not in serialized


def test_pa5_cost_accounting_uses_usage_not_provider_cost_field() -> None:
    pricing = load(ROOT / PRICING_CONTRACT_PATH)
    counters = {
        "provider_calls": 0,
        "total_payg_equivalent_cost_usd": Decimal("0"),
        "latencies": [],
        "costs": [],
    }

    def fake_cost_provider(_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": "{}",
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "cache_creation_input_tokens": 1_000_000,
                "cache_read_input_tokens": 1_000_000,
            },
            "cost_usd": 999.0,
            "billing": {"cost_usd": 999.0},
            "response_id": "fake-cost-field",
            "model": "MiniMax-M3",
        }

    result = provider_call_checked(
        provider_call=fake_cost_provider,
        payload={"model": "MiniMax-M3", "messages": [], "max_tokens": 1, "temperature": 0},
        counters=counters,
        pricing_contract=pricing,
        question_id="pa5-test",
        call_class="answer_generation",
    )
    assert result["payg_equivalent_cost_usd"] == "1.93500000"
    assert result["provider_reported_monetary_cost_available"] is False
    assert result["provider_reported_monetary_cost_usd"] is None


def test_pa5_minimax_client_requires_usage_but_not_cost_field(monkeypatch: Any) -> None:
    class FakeHTTPResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "id": "realish-response-id",
                "model": "MiniMax-M3",
                "text": "{}",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }

    monkeypatch.setattr(
        "knowledge_engine.m26_pa5_live_execution.httpx.post",
        lambda *args, **kwargs: FakeHTTPResponse(),
    )
    client = MiniMaxM3Client(api_key="x", endpoint="https://example.invalid")
    result = client({"model": "MiniMax-M3"})
    assert result["usage"] == {
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "input_tokens": 10,
        "output_tokens": 20,
        "total_accounted_tokens": 30,
    }


def test_pa5_minimax_client_fails_closed_on_missing_usage(monkeypatch: Any) -> None:
    class FakeHTTPResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"id": "missing-usage", "model": "MiniMax-M3", "text": "{}"}

    monkeypatch.setattr(
        "knowledge_engine.m26_pa5_live_execution.httpx.post",
        lambda *args, **kwargs: FakeHTTPResponse(),
    )
    client = MiniMaxM3Client(api_key="x", endpoint="https://example.invalid")
    with pytest.raises(Exception, match="provider usage missing"):
        client({"model": "MiniMax-M3"})


def test_pa5_minimax_client_accepts_nonzero_automatic_cache_usage(monkeypatch: Any) -> None:
    class FakeHTTPResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "id": "cache-drift",
                "model": "MiniMax-M3",
                "text": "{}",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 1,
                },
            }

    monkeypatch.setattr(
        "knowledge_engine.m26_pa5_live_execution.httpx.post",
        lambda *args, **kwargs: FakeHTTPResponse(),
    )
    client = MiniMaxM3Client(api_key="x", endpoint="https://example.invalid")
    result = client({"model": "MiniMax-M3"})
    assert result["usage"]["cache_read_input_tokens"] == 1


def test_pa5_provider_call_fails_closed_on_explicit_cache_control() -> None:
    pricing = load(ROOT / PRICING_CONTRACT_PATH)
    counters = {
        "provider_calls": 0,
        "total_payg_equivalent_cost_usd": Decimal("0"),
        "latencies": [],
        "costs": [],
    }

    def unused_provider(_payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("explicit cache_control must stop before provider call")

    with pytest.raises(Exception, match="explicit cache_control is forbidden"):
        provider_call_checked(
            provider_call=unused_provider,
            payload={"model": "MiniMax-M3", "messages": [{"cache_control": {}}]},
            counters=counters,
            pricing_contract=pricing,
            question_id="pa5-test",
            call_class="answer_generation",
        )


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
    assert receipt["billing"]["missing_provider_monetary_cost_field_is_error"] is False
    assert receipt["partial_denominator"]["complete_population_count"] == 200
    assert receipt["partial_denominator"]["raw_text_persisted"] is False


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
    assert "m26-pa-5-controlled-internal-shadow-pilot-evidence-attempt-6" in workflow

    arch = ARCH_WORKFLOW.read_text(encoding="utf-8")
    assert "src/knowledge_engine/m26_pa5_live_execution.py" in arch

    pa4 = PA4_WORKFLOW.read_text(encoding="utf-8")
    assert "pilot/m26/m26-pa-5-attempt-1-failure-seal.json" in pa4
    assert "pilot/m26/m26-pa-5-attempt-2-failure-seal.json" in pa4
    assert "pilot/m26/m26-pa-5-attempt-3-failure-seal.json" in pa4
    assert "pilot/m26/m26-pa-5-attempt-4-failure-seal.json" in pa4
    assert "pilot/m26/m26-pa-5-attempt-5-failure-seal.json" in pa4
    assert "pilot/m26/m26-pa-5-reviewer-contract-v2.json" in pa4
    assert "pilot/m26/m26-pa-5-threshold-semantics-v2.json" in pa4
    assert "pilot/m26/m26-pa-5-v6-exhaustion-record.json" in pa4
    assert "pilot/m26/m26-pa-5-minimax-m3-pricing-contract.json" in pa4
    assert "schemas/m26-pa-5-success-receipt-v1.schema.json" in pa4
    assert "tests/test_m26_pa_5_live_execution.py" in pa4
