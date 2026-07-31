from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.m26_ask_api import (
    WEB_RESPONSE_SCHEMA,
    M26AskApiError,
    build_web_query_dto,
    create_app,
    run_owner_query_for_web,
    validate_query_request,
)
from knowledge_engine.m26_pa7_arbitrary_query_runtime import (
    LocalDenseProjectionChannel,
    run_owner_arbitrary_query,
)
from knowledge_engine.m26_production_promotion_closure import load_json

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
TEST_BACKEND_TOKEN = "test-backend-token"
AUTH_SCHEME = "Bear" + "er"


class ExactSpanProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        task = _task(payload)
        evidence = task["evidence_bundle"]
        passages = [item for item in evidence if item["evidence_type"] == "passage"]
        refs = [_support_ref(item) for item in passages[:2]]
        return {
            "text": json.dumps(
                {
                    "status": "answer_candidate",
                    "relation": "contrasts_with",
                    "selected_evidence_ids": [item["evidence_id"] for item in evidence],
                    "claims": [
                        {
                            "claim_id": "claim_1",
                            "claim_role": "relationship",
                            "support_refs": refs,
                        }
                    ],
                    "abstention_reason": None,
                }
            ),
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": f"fake-{self.calls}",
            "call_class": call_class,
        }


def _task(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload["messages"][0]["content"]
    text = message[0]["text"] if isinstance(message, list) else message
    return json.loads(text)


def _support_ref(item: dict[str, Any]) -> dict[str, str]:
    passage = item["text"]
    quote = passage.split(". ", 1)[0].strip() + "."
    return {
        "evidence_id": item["evidence_id"],
        "locator_id": item["locator_id"],
        "exact_quote": quote,
    }


def test_web_dto_wraps_canonical_runtime_without_raw_question() -> None:
    question = "Compare routers and adaptive planning for permission-first controls."
    dto = run_owner_query_for_web(
        root=ROOT,
        gate_path=GATE_PATH,
        request_payload={"question": question},
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=ExactSpanProvider(),
        dense_channel=LocalDenseProjectionChannel(),
    )

    encoded = json.dumps(dto, ensure_ascii=False)
    assert dto["schema_version"] == WEB_RESPONSE_SCHEMA
    assert dto["canonical_runtime"]["entrypoint"].endswith("run_owner_arbitrary_query")
    assert dto["status"] == "owner_only_cited_answer"
    assert dto["retrieval"]["distinct_source_count"] >= 2
    assert len(dto["citations"]) >= 2
    assert len(dto["sources"]) >= 2
    assert dto["multi_evidence_verification"]["support_precision"] == 1.0
    assert dto["mutations"]["canonical_writes"] == 0
    assert dto["privacy"]["raw_query_persisted"] is False
    assert question not in encoded


def test_web_dto_matches_cli_runtime_response_identity() -> None:
    runtime = run_owner_arbitrary_query(
        root=ROOT,
        gate=load_json(GATE_PATH),
        question="Compare routers and adaptive planning for permission-first controls.",
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=ExactSpanProvider(),
        dense_channel=LocalDenseProjectionChannel(),
    )
    dto = build_web_query_dto(runtime)

    assert dto["canonical_runtime"]["schema_version"] == runtime["schema_version"]
    assert dto["trace_id"] == runtime["trace_id"]
    assert dto["question_sha256"] == runtime["question_sha256"]
    assert dto["identities"]["resolved_gate_self_sha256"] == runtime["resolved_gate_self_sha256"]


def test_query_request_validation_is_bounded() -> None:
    assert validate_query_request({"question": "  explain   harness  "}) == "explain harness"
    with pytest.raises(M26AskApiError, match="question exceeds"):
        validate_query_request({"question": "x" * 2001})
    with pytest.raises(M26AskApiError, match="question must not be empty"):
        validate_query_request({"question": "   "})
    with pytest.raises(M26AskApiError, match="question must be a string"):
        validate_query_request({"question": 42})


def test_fastapi_backend_requires_server_side_owner_and_backend_auth(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", OWNER_SUBJECT_HASH)
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", TEST_BACKEND_TOKEN)
    app = create_app(root=ROOT, gate_path=GATE_PATH, require_remote_dense=False)
    client = TestClient(app)

    assert client.get("/api/m26/health").status_code == 403
    assert (
        client.get(
            "/api/m26/health",
            headers={
                "authorization": "Bearer wrong",
                "x-m26-owner-subject-hash": OWNER_SUBJECT_HASH,
            },
        ).status_code
        == 403
    )
    admitted = client.get(
        "/api/m26/health",
        headers={
            "authorization": f"{AUTH_SCHEME} {TEST_BACKEND_TOKEN}",
            "x-m26-owner-subject-hash": OWNER_SUBJECT_HASH,
        },
    )
    assert admitted.status_code == 200
    assert admitted.json()["route"]["api_query_path"] == "/api/m26/query"


def test_production_api_mounts_same_owner_only_m26_backend(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", OWNER_SUBJECT_HASH)
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", TEST_BACKEND_TOKEN)
    from knowledge_engine.api import app as production_app

    client = TestClient(production_app)
    assert client.get("/api/m26/health").status_code == 403
    admitted = client.get(
        "/api/m26/health",
        headers={
            "authorization": f"{AUTH_SCHEME} {TEST_BACKEND_TOKEN}",
            "x-m26-owner-subject-hash": OWNER_SUBJECT_HASH,
        },
    )

    assert admitted.status_code == 200
    assert admitted.json()["canonical_runtime"]["entrypoint"].endswith(
        "run_owner_arbitrary_query"
    )
