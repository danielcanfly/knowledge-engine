from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-3-live-provider-execution.yml"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def with_self_digest(value: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    candidate["self_sha256"] = ""
    candidate["self_sha256"] = sha256_value(candidate)
    return candidate


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_pa3_authorization_is_self_digested_and_schema_valid() -> None:
    authorization = load(PILOT / "m26-pa-3-live-provider-authorization.json")
    schema = load(SCHEMAS / "m26-pa-3-live-provider-authorization-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(authorization),
        key=lambda error: list(error.absolute_path),
    )
    assert errors == []

    expected = authorization["self_sha256"]
    candidate = dict(authorization)
    candidate["self_sha256"] = ""
    assert sha256_value(candidate) == expected
    assert expected == "1eb3545bc7bee9c483c8713c60f5c3711ba925e96efdb5eedd307a5cf139f6cd"
    assert authorization["stage_id"] == "M26.PA.3"
    assert authorization["authorized"] is True


def test_pa3_gate_binds_pa2_and_daniel_provider_decision() -> None:
    authorization = load(PILOT / "m26-pa-3-live-provider-authorization.json")
    assert authorization["predecessor"] == {
        "pa2_acceptance_self_sha256": (
            "f6f597699390135b0bf7a8e31417c2e8e6f48af2dc2af4168eca1fd1e7f24f67"
        ),
        "pa2_issue_number": 1186,
        "pa2_issue_state_after_merge": "closed",
        "pa2_reconciliation_merge_sha": "8ed2da47d04f6410e55d5855d78f734341aecf2e",
        "pa2_reconciliation_pull_request": 1196,
        "pa2_status": "m26_pa_2_real_corpus_retrieval_binding_accepted",
    }
    assert authorization["provider"] == {
        "api_style": "anthropic_compatible_messages",
        "base_url": "https://api.minimax.io/anthropic",
        "docs_checked_at": "2026-07-27",
        "endpoint": "https://api.minimax.io/anthropic/v1/messages",
        "model_id": "MiniMax-M3",
        "provider_id": "minimax",
        "secret_name": "MINIMAX_API_KEY",
        "stream": False,
        "thinking": {"mode": "not_requested"},
    }
    assert authorization["owner_decision"]["decided_by"] == "Daniel Huang"
    assert authorization["owner_decision"]["recommendation_adopted_by_gate"] is True


def test_pa3_budget_payload_and_receipt_policy_are_minimal() -> None:
    authorization = load(PILOT / "m26-pa-3-live-provider-authorization.json")
    assert authorization["budget"]["max_live_call_count"] == 1
    assert authorization["budget"]["max_spend_usd"] <= 0.05
    assert authorization["budget"]["max_output_tokens"] == 256
    assert authorization["payload_scope"] == {
        "include_pa2_receipt_identity": True,
        "include_qdrant_population": True,
        "include_release_identity": True,
        "include_sample_digest": True,
        "max_prompt_bytes": 12000,
        "production_metadata_hashes": True,
        "raw_corpus_text": False,
        "secret_values": False,
        "user_query": False,
        "vectors": False,
    }
    assert authorization["receipt_policy"] == {
        "artifact_retention_days": 30,
        "persist_error_body_hash_only": True,
        "persist_provider_response_hash": True,
        "persist_provider_response_text": False,
        "persist_request_payload_hash": True,
        "persist_usage": True,
    }
    assert all(value is False for value in authorization["denied_authority"].values())


def test_pa3_request_payload_is_metadata_only() -> None:
    authorization = load(PILOT / "m26-pa-3-live-provider-authorization.json")
    user_content = {
        "task": authorization["request_template"]["user_task"],
        "pa2_status": authorization["predecessor"]["pa2_status"],
        "production_evidence": authorization["production_evidence"],
        "constraints": {
            "no_production_answer": True,
            "raw_corpus_text_sent": False,
            "vectors_sent": False,
            "user_query_sent": False,
        },
    }
    payload = {
        "model": authorization["provider"]["model_id"],
        "max_tokens": authorization["budget"]["max_output_tokens"],
        "temperature": 0,
        "stream": False,
        "system": authorization["request_template"]["system"],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": json.dumps(user_content, sort_keys=True)}],
            }
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert len(serialized.encode("utf-8")) <= authorization["payload_scope"]["max_prompt_bytes"]
    assert "raw_text" not in serialized
    assert "text_sha256" not in serialized
    assert "MINIMAX_API_KEY" not in serialized
    assert payload["model"] == "MiniMax-M3"
    assert payload["stream"] is False
    assert "thinking" not in payload


def test_pa3_receipt_schema_accepts_sanitized_provider_receipt_only() -> None:
    schema = load(SCHEMAS / "m26-pa-3-live-provider-receipt-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    receipt = with_self_digest(
        {
            "schema_version": "knowledge-engine-m26-pa-3-live-provider-receipt/v1",
            "stage_id": "M26.PA.3",
            "status": "live_provider_execution_verified",
            "generated_at": "2026-07-27T12:30:00Z",
            "authorization": {
                "authorization_self_sha256": "a" * 64,
                "logical_attempt": 1,
                "trigger_marker": "[m26.pa3-provider-authorized-attempt-1]",
            },
            "workflow": {
                "workflow_name": "M26.PA.3 Live Provider Execution Gate",
                "run_id": "30270000000",
                "run_attempt": "1",
                "head_sha": "8ed2da47d04f6410e55d5855d78f734341aecf2e",
            },
            "request": {
                "payload_sha256": "b" * 64,
                "prompt_bytes": 2048,
                "max_output_tokens": 256,
                "stream": False,
                "raw_corpus_text_sent": False,
                "vectors_sent": False,
                "user_query_sent": False,
            },
            "provider": {
                "provider_id": "minimax",
                "model_id": "MiniMax-M3",
                "api_style": "anthropic_compatible_messages",
                "endpoint": "https://api.minimax.io/anthropic/v1/messages",
                "provider_response_id": "msg_123",
                "response_model": "MiniMax-M3",
                "stop_reason": "end_turn",
                "content_block_count": 1,
                "response_json_sha256": "c" * 64,
                "response_text_sha256": "d" * 64,
                "response_text_persisted": False,
            },
            "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
            "authority": {
                "provider_calls": 1,
                "credential_names": ["MINIMAX_API_KEY"],
                "secret_values_persisted": False,
                "raw_text_persisted": False,
                "vectors_requested": False,
                "vectors_returned": False,
                "r2_write_operations": 0,
                "qdrant_write_operations": 0,
                "source_foundation_release_mutations": 0,
                "public_shadow_canary_traffic_operations": 0,
            },
        }
    )
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    assert errors == []
    tampered = dict(receipt)
    tampered["provider"] = {**receipt["provider"], "response_text_persisted": True}
    with pytest.raises(AssertionError):
        assert list(Draft202012Validator(schema).iter_errors(tampered)) == []


def test_pa3_workflow_is_bounded_and_pr_safe() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "workflow_dispatch" not in text
    assert "environment: m23-r3-diagnostic" in text
    assert "MINIMAX_API_KEY: ${{ secrets.MINIMAX_API_KEY }}" in text
    assert "R2_ACCESS_KEY_ID_READ" not in text
    assert "QDRANT_READ_ONLY" not in text
    assert "github.event_name == 'push'" in text
    assert "[m26.pa3-provider-authorized-attempt-1]" in text
    assert "test -z \"${MINIMAX_API_KEY:-}\"" in text
    assert "m26-pa-3-live-provider-evidence-attempt-1" in text
    assert "response_text_persisted" in text
    assert "response_text" not in text.replace("response_text_sha256", "").replace(
        "response_text_persisted",
        "",
    )


def test_pa3_doc_keeps_downstream_authority_closed() -> None:
    text = (DOCS / "m26-pa-3-live-provider-execution.md").read_text(encoding="utf-8")
    assert "MiniMax-M3" in text
    assert "MINIMAX_API_KEY" in text
    assert "no raw corpus text" in text
    assert "not a production answer" in text
    assert "Production answer serving" in text
    assert "remain forbidden" in text
