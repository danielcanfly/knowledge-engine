from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_verified_answer_citation_gate import (
    ACCEPTED_STATUS,
    RECEIPT_SCHEMA,
    SUPPORTED_ANSWER_TEXT,
    build_provider_payload,
    canonical_sha256,
    run_verified_answer_benchmark,
    validate_owner_decision,
    validate_policy,
    validate_population,
    validate_registry,
    verify_provider_output,
    with_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-4-verified-answer-citation-gate.yml"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_owner_decision_is_self_digested_and_exact() -> None:
    decision = load(PILOT / "m26-pa-4-owner-decision.json")
    schema = load(SCHEMAS / "m26-pa-4-owner-decision-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(decision)) == []
    assert validate_owner_decision(decision)["stage_id"] == "M26.PA.4"
    candidate = dict(decision)
    candidate["self_sha256"] = ""
    assert canonical_sha256(candidate) == decision["self_sha256"]
    assert decision["parsed_parameters"] == {
        "benchmark_population_count": 12,
        "citation_precision_support_threshold": 1.0,
        "credential_name": "MINIMAX_API_KEY",
        "environment": "m23-r3-diagnostic",
        "max_provider_calls_per_item_including_repair": 2,
        "max_repair_attempts": 1,
        "max_spend_usd": 1.0,
        "model_id": "MiniMax-M3",
        "population_digest_state": "to_be_frozen_before_run",
        "provider_id": "minimax",
        "provider_label": "MiniMax",
    }
    assert "no raw corpus persistence" in decision["exact_instruction_text"]
    assert decision["denied_authority"]["production_serving"] is False


def test_policy_population_and_registry_are_strict_and_bound() -> None:
    owner = load(PILOT / "m26-pa-4-owner-decision.json")
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    registry = load(PILOT / "m26-pa-4-contract-registry.json")
    for path in (
        "m26-pa-4-verified-answer-policy-v1.schema.json",
        "m26-pa-4-benchmark-population-v1.schema.json",
        "m26-pa-4-verified-answer-receipt-v1.schema.json",
    ):
        Draft202012Validator.check_schema(load(SCHEMAS / path))
    assert validate_policy(policy, owner_decision=owner)["stage_id"] == "M26.PA.4"
    assert validate_population(population, policy=policy)["stage_id"] == "M26.PA.4"
    assert validate_registry(ROOT)["stage_id"] == "M26.PA.4"
    assert population["benchmark_population_count"] == 12
    assert population["population_sha256"] == canonical_sha256(population["cases"])
    assert policy["benchmark"] == {
        "population_count": 12,
        "population_sha256": population["population_sha256"],
        "qdrant_collection": "m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043",
        "release_id": "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043",
        "semantic_inputs_sha256": (
            "377c8b8ec3b52aad03481008c50ac3c1f8203537928477de0a3d1bf89d26e7e0"
        ),
    }
    assert registry["accepted"] is False
    assert registry["artifacts"] == {
        "benchmark_population_sha256": canonical_sha256(population),
        "owner_decision_sha256": canonical_sha256(owner),
        "verified_answer_policy_sha256": canonical_sha256(policy),
    }
    assert population["release"]["semantic_inputs_key"].endswith("semantic-inputs.json")
    assert population["selection"]["qdrant_scroll_pages"] == 17
    assert all(
        case["question"]["raw_corpus_text_in_question"] is False for case in population["cases"]
    )
    assert {case["expected_terminal_policy"] for case in population["cases"]} == {
        "candidate_or_abstention",
        "abstention_required",
    }
    assert {case["category"] for case in population["cases"]} == {
        "direct_material_claim",
        "security_adversarial",
    }


def test_population_cases_bind_real_locator_and_no_raw_text() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    seen = set()
    for case in population["cases"]:
        locator = case["passage_locator"]
        assert locator["locator_id"] not in seen
        seen.add(locator["locator_id"])
        assert locator["artifact_kind"] == "semantic_inputs"
        assert locator["release_id"] == population["release"]["release_id"]
        assert locator["artifact_sha256"] == population["release"]["semantic_inputs_sha256"]
        assert locator["source_commit_sha"] == population["release"]["source_commit_sha"]
        assert len(locator["text_sha256"]) == 64
        assert "text" not in locator
        assert "body" not in locator
        question = case["question"]
        assert len(question["text_sha256"]) == 64
        assert (
            hashlib.sha256(question["text"].encode("utf-8")).hexdigest() == question["text_sha256"]
        )
    assert len(seen) == 12


def test_verify_provider_output_supports_exact_span_and_abstains_when_required() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    supported_case = population["cases"][0]
    abstain_case = population["cases"][10]
    passage_text = "Alpha beta gamma delta."
    provider_output = json.dumps(
        {
            "status": "draft_candidate",
            "answer_text": SUPPORTED_ANSWER_TEXT,
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_text": "beta gamma",
                    "citation": {"locator_id": supported_case["passage_locator"]["locator_id"]},
                }
            ],
            "reason_codes": [],
        },
        sort_keys=True,
    )
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    supported = verify_provider_output(
        case=supported_case,
        passage_text=passage_text,
        provider_text=provider_output,
        policy=policy,
    )
    assert supported["terminal_status"] == "verified_answer_ready_candidate"
    assert supported["support_verification"]["citation_precision"] == 1.0
    assert supported["material_claims"][0]["support_verdict"] == "supported_exact_passage_span"

    abstain_output = json.dumps(
        {
            "status": "abstain",
            "answer_text": "",
            "claims": [],
            "reason_codes": ["INSUFFICIENT_SUPPORT"],
        },
        sort_keys=True,
    )
    abstained = verify_provider_output(
        case=abstain_case,
        passage_text=passage_text,
        provider_text=abstain_output,
        policy=policy,
    )
    assert abstained["terminal_status"] == "abstention_required"
    assert abstained["abstention"]["policy_triggered"] is True


def test_verify_provider_output_rejects_unsupported_or_mismatched_claims() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    case = population["cases"][1]
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    bad_output = json.dumps(
        {
            "status": "draft_candidate",
            "answer_text": SUPPORTED_ANSWER_TEXT,
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_text": "not in the passage",
                    "citation": {"locator_id": case["passage_locator"]["locator_id"]},
                }
            ],
            "reason_codes": [],
        },
        sort_keys=True,
    )
    with pytest.raises(Exception, match="exact passage span"):
        verify_provider_output(
            case=case,
            passage_text="Alpha beta gamma delta.",
            provider_text=bad_output,
            policy=policy,
        )


def test_run_verified_answer_benchmark_compiles_sanitized_receipt() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    passages = {case["case_id"]: "Alpha beta gamma delta." for case in population["cases"]}

    def fake_provider(payload: dict[str, Any]) -> dict[str, Any]:
        task = json.loads(payload["messages"][0]["content"][0]["text"])
        if task["expected_terminal_policy"] == "abstention_required":
            provider_text = json.dumps(
                {
                    "status": "abstain",
                    "answer_text": "",
                    "claims": [],
                    "reason_codes": ["CASE_POLICY_REQUIRES_ABSTENTION"],
                },
                sort_keys=True,
            )
        else:
            provider_text = json.dumps(
                {
                    "status": "draft_candidate",
                    "answer_text": SUPPORTED_ANSWER_TEXT,
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "claim_text": "beta gamma",
                            "citation": {"locator_id": task["passage"]["locator_id"]},
                        }
                    ],
                    "reason_codes": [],
                },
                sort_keys=True,
            )
        return {
            "response_json": {
                "id": f"msg_{task['case_id']}",
                "model": "MiniMax-M3",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": provider_text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "provider_text": provider_text,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "provider_response_id": f"msg_{task['case_id']}",
            "response_model": "MiniMax-M3",
            "stop_reason": "end_turn",
        }

    receipt = run_verified_answer_benchmark(
        root=ROOT,
        passages_by_case_id=passages,
        provider_call=fake_provider,
        generated_at="2026-07-28T00:00:00Z",
        workflow={
            "repository": "danielcanfly/knowledge-engine",
            "workflow_name": "M26.PA.4 Real Verified Answer and Citation Gate",
            "run_id": "30296000000",
            "run_attempt": "1",
            "head_sha": "ae130666813ec30f082020c89c02a75384d5068e",
            "environment": "m23-r3-diagnostic",
        },
        evidence_summary={
            "release_id": population["release"]["release_id"],
            "raw_corpus_text_persisted": False,
            "vectors_requested": False,
        },
    )
    schema = load(SCHEMAS / "m26-pa-4-verified-answer-receipt-v1.schema.json")
    assert list(Draft202012Validator(schema).iter_errors(receipt)) == []
    assert receipt["summary"]["benchmark_population_count"] == 12
    assert receipt["summary"]["ready_candidate_count"] == 10
    assert receipt["summary"]["abstention_count"] == 2
    assert receipt["summary"]["unsupported_material_claim_count"] == 0
    assert receipt["authority"]["provider_calls"] == 12
    assert receipt["authority"]["raw_corpus_text_persisted"] is False


def test_build_provider_payload_is_bounded_and_metadata_only() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    policy = load(PILOT / "m26-pa-4-verified-answer-policy.json")
    case = population["cases"][0]
    payload = build_provider_payload(
        policy=policy,
        case=case,
        passage_text="Alpha beta gamma delta.",
    )
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload["model"] == "MiniMax-M3"
    assert payload["stream"] is False
    assert "MINIMAX_API_KEY" not in serialized
    assert "Alpha beta gamma delta." in serialized
    assert len(serialized.encode("utf-8")) <= policy["budget"]["max_prompt_bytes_per_item"]


def test_workflow_and_receipt_schema_are_bounded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in workflow
    assert "environment: m23-r3-diagnostic" in workflow
    assert "QDRANT_API_KEY_READ" in workflow
    assert "MINIMAX_API_KEY" in workflow
    assert "[m26.pa4-real-verified-answer-authorized-attempt-1]" in workflow
    assert "workflow_dispatch" not in workflow
    assert "contents: write" not in workflow
    assert "production serving" not in workflow
    assert "pointer mutation" not in workflow
    assert "canonical writes" not in workflow

    schema = load(SCHEMAS / "m26-pa-4-verified-answer-receipt-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    item = {
        "case_id": "pa4_case_01_date_claim",
        "terminal_status": "verified_answer_ready_candidate",
        "expected_terminal_policy": "candidate_or_abstention",
        "draft_answer": {
            "answer_text_sha256": "3" * 64,
            "provider_response_text_sha256": "4" * 64,
            "answer_text_persisted": False,
            "provider_response_text_persisted": False,
            "raw_corpus_text_persisted": False,
            "verified_final_answer": False,
            "production_answer_serving": False,
        },
        "material_claims": [
            {
                "claim_id": "claim_1",
                "material": True,
                "material_claim_type": "date",
                "claim_text_sha256": "5" * 64,
                "claim_char_count": 10,
                "citation_locator_id": "m26-pa4-01",
                "source_id": "source",
                "section_id": "section",
                "passage_text_sha256": "6" * 64,
                "passage_span": {"start_char": 1, "end_char": 11},
                "support_verdict": "supported_exact_passage_span",
                "support_reason_code": "EXACT_SPAN_MATCH",
            }
        ],
        "support_verification": {
            "material_claim_count": 1,
            "supported_claim_count": 1,
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
        "conflict_temporal_verification": {
            "conflict_status": "no_unresolved_conflict_in_single_locator_scope",
            "temporal_status": "release_bounded_not_current_status",
            "stale_temporal_evidence": False,
        },
        "privacy_security": {
            "secret_value_findings": [],
            "prompt_injection_followed": False,
            "raw_corpus_text_persisted": False,
        },
        "repair": {"attempts_used": 0, "max_attempts": 1},
    }
    receipt = with_self_digest(
        {
            "schema_version": RECEIPT_SCHEMA,
            "stage_id": "M26.PA.4",
            "status": "real_verified_answer_citation_gate_verified",
            "generated_at": "2026-07-28T00:00:00Z",
            "owner_decision": {
                "owner_decision_self_sha256": "a" * 64,
                "exact_instruction_text_sha256": "b" * 64,
            },
            "policy": {
                "policy_self_sha256": "c" * 64,
                "max_provider_calls_per_item_including_repair": 2,
                "max_repair_attempts": 1,
                "support_threshold": 1.0,
            },
            "population": {
                "benchmark_population_count": 12,
                "population_self_sha256": "d" * 64,
                "population_sha256": "e" * 64,
            },
            "workflow": {"repository": "danielcanfly/knowledge-engine"},
            "provider": {
                "provider_id": "minimax",
                "model_id": "MiniMax-M3",
                "endpoint": "https://api.minimax.io/anthropic/v1/messages",
                "provider_response_text_persisted": False,
            },
            "evidence_summary": {},
            "request_receipts": [
                {
                    "case_id": "pa4_case_01_date_claim",
                    "attempt": 1,
                    "payload_sha256": "f" * 64,
                    "prompt_bytes": 100,
                    "provider_response_json_sha256": "0" * 64,
                    "provider_response_text_sha256": "1" * 64,
                    "provider_response_text_persisted": False,
                    "raw_corpus_text_persisted": False,
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    "provider_response_id_sha256": "2" * 64,
                    "response_model": "MiniMax-M3",
                    "stop_reason": "end_turn",
                }
            ]
            * 12,
            "items": [item] * 12,
            "summary": {
                "benchmark_population_count": 12,
                "ready_candidate_count": 12,
                "abstention_count": 0,
                "material_claim_count": 12,
                "supported_material_claim_count": 12,
                "unsupported_material_claim_count": 0,
                "citation_precision": 1.0,
                "all_non_abstained_material_claims_supported": True,
            },
            "usage": {"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
            "authority": {
                "provider_calls": 12,
                "credential_names": ["MINIMAX_API_KEY"],
                "secret_values_persisted": False,
                "raw_corpus_text_sent_to_provider": True,
                "raw_corpus_text_persisted": False,
                "provider_response_text_persisted": False,
                "vectors_requested": False,
                "vectors_returned": False,
                "vectors_persisted": False,
                "r2_write_operations": 0,
                "qdrant_write_operations": 0,
                "source_foundation_release_mutations": 0,
                "production_pointer_mutations": 0,
                "public_shadow_canary_traffic_operations": 0,
                "production_answer_serving": False,
                "canonical_writes": 0,
            },
        }
    )
    assert list(Draft202012Validator(schema).iter_errors(receipt)) == []
    assert receipt["self_sha256"] == canonical_sha256({**receipt, "self_sha256": ""})


def test_population_schema_and_workflow_path_list_are_exact() -> None:
    population = load(PILOT / "m26-pa-4-benchmark-population.json")
    assert validate_population(
        population, policy=load(PILOT / "m26-pa-4-verified-answer-policy.json")
    )
    assert population["benchmark_population_count"] == len(population["cases"])
    assert population["population_sha256"] == canonical_sha256(population["cases"])
    assert population["release"]["qdrant_collection"].startswith("m25_blog_")
    assert (
        population["release"]["semantic_inputs_sha256"]
        == "377c8b8ec3b52aad03481008c50ac3c1f8203537928477de0a3d1bf89d26e7e0"
    )
    assert (
        population["selection"]["source_commit_sha"] == "5250f8422f4fa08c1f3dc84840dc756850817635"
    )
    assert population["selection"]["raw_corpus_text_persisted"] is False
    assert ACCEPTED_STATUS == "m26_pa_4_verified_answer_citation_gate_accepted"
