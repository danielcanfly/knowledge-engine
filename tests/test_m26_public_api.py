from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_public_api
from knowledge_engine.m26_public_api import PublicQuotaLedger, create_app

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("M26_PUBLIC_IP_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "93" * 32)
    monkeypatch.setenv(
        "M26_PUBLIC_ALLOWED_ORIGINS", "https://danielcanfly.com,http://localhost:5173"
    )
    monkeypatch.setattr(m26_public_api, "BURST_PER_MINUTE_LIMIT", 100)
    ledger = PublicQuotaLedger(tmp_path / "quota.sqlite3")
    app = create_app(root=ROOT, gate_path=GATE_PATH, quota_ledger=ledger)
    app.state.test_quota_path = ledger.path
    with TestClient(app) as test_client:
        yield test_client


def _answer_dto(**overrides: Any) -> dict[str, Any]:
    dto: dict[str, Any] = {
        "status": "owner_only_cited_answer",
        "safe_abstention": False,
        "answer_text": "Use one variable at a time [claim_1_ref_1].",
        "citations": [
            {
                "citation_id": "claim_1_ref_1",
                "claim_id": "claim_1",
                "source_identity": "source_public_1",
                "section_id": "section_1",
                "concept_id": "concept_1",
                "release_id": "release_1",
                "runtime_owned_locator": True,
            }
        ],
        "sources": [
            {
                "source_identity": "source_public_1",
                "source_id": "source_1",
                "section_ids": ["section_1"],
                "concept_ids": ["concept_1"],
                "citation_numbers": [1],
            }
        ],
        "answer_claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct",
                "citation_ids": ["claim_1_ref_1"],
                "support_ref_count": 1,
            }
        ],
        "provider_routing": {
            "closure_provider_initial": "cloudflare",
            "closure_provider_final": "cloudflare",
            "fallback_used": False,
            "fallback_reason": "NONE",
            "provider_attempts": [
                {
                    "call_class": "pa7_multi_evidence_query",
                    "provider": "cloudflare",
                    "model": "@cf/openai/gpt-oss-120b",
                    "latency_ms": 12,
                },
                {
                    "call_class": "aq_claim_semantic_entailment",
                    "provider": "minimax-m3",
                    "model": "MiniMax-M3",
                    "latency_ms": 8,
                },
            ],
        },
        "reason_codes": [],
    }
    dto.update(overrides)
    return dto


def _patch_answer(monkeypatch: pytest.MonkeyPatch, dto: dict[str, Any] | None = None) -> None:
    def fake_run(**kwargs: Any) -> dict[str, Any]:
        sink = kwargs.get("event_sink")
        if sink is not None:
            sink({"type": "stage.started", "stage": "retrieval"})
            sink(
                {
                    "type": "stage.completed",
                    "stage": "retrieval",
                    "selected_evidence_count": 1,
                }
            )
            sink({"type": "stage.started", "stage": "closure", "attempt": 1})
            sink(
                {
                    "type": "model.started",
                    "role": "closure",
                    "provider": "cloudflare",
                    "model": "@cf/openai/gpt-oss-120b",
                    "attempt": 1,
                    "fallback_used": False,
                    "fallback_reason": "NONE",
                }
            )
            sink(
                {
                    "type": "model.completed",
                    "role": "closure",
                    "provider": "cloudflare",
                    "model": "@cf/openai/gpt-oss-120b",
                    "attempt": 1,
                    "status": "completed",
                    "latency_ms": 12,
                    "fallback_used": False,
                    "fallback_reason": "NONE",
                }
            )
            sink({"type": "stage.completed", "stage": "closure", "attempt": 1})
            sink({"type": "stage.started", "stage": "review", "attempt": 1})
            sink(
                {
                    "type": "model.started",
                    "role": "semantic_reviewer",
                    "provider": "minimax-m3",
                    "model": "MiniMax-M3",
                    "attempt": 1,
                    "fallback_used": False,
                    "fallback_reason": "NONE",
                }
            )
            sink(
                {
                    "type": "model.completed",
                    "role": "semantic_reviewer",
                    "provider": "minimax-m3",
                    "model": "MiniMax-M3",
                    "attempt": 1,
                    "status": "completed",
                    "latency_ms": 8,
                    "fallback_used": False,
                    "fallback_reason": "NONE",
                }
            )
            sink({"type": "stage.completed", "stage": "review", "attempt": 1})
            sink({"type": "stage.started", "stage": "verification", "attempt": 1})
            sink(
                {
                    "type": "stage.completed",
                    "stage": "verification",
                    "attempt": 1,
                    "status": "verified",
                }
            )
        return dto or _answer_dto()

    monkeypatch.setattr(m26_public_api, "run_owner_query_for_web", fake_run)


def _problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json")
    return response.json()


def _sse_events(response: Any) -> list[dict[str, Any]]:
    events = []
    for block in response.text.strip().split("\n\n"):
        data = None
        for line in block.splitlines():
            if line.startswith("data: "):
                data = line.removeprefix("data: ")
        if data:
            events.append(json.loads(data))
    return events


def test_validation_errors_are_problem_details(client: TestClient) -> None:
    cases = [
        (b"{", "INVALID_JSON"),
        (b"[]", "REQUEST_NOT_OBJECT"),
        (b"{}", "QUESTION_MISSING"),
        (json.dumps({"question": "   "}).encode(), "QUESTION_EMPTY"),
        (json.dumps({"question": "ok", "extra": True}).encode(), "UNSUPPORTED_FIELD"),
        (json.dumps({"question": "ok", "provider": "x"}).encode(), "PROVIDER_SELECTION_FORBIDDEN"),
        (json.dumps({"question": "ok", "model": "x"}).encode(), "PROVIDER_SELECTION_FORBIDDEN"),
    ]
    for body, code in cases:
        response = client.post("/v1/answers", content=body)
        assert _problem(response)["code"] == code


def test_oversized_body_and_question_are_rejected(client: TestClient) -> None:
    body = b"{" + b'"question":"' + b"a" * 5000 + b'"}'
    assert _problem(client.post("/v1/answers", content=body))["code"] == "REQUEST_BODY_TOO_LARGE"
    question = "a" * (m26_public_api.MAX_QUERY_CHARS + 1)
    response = client.post("/v1/answers", json={"question": question})
    assert _problem(response)["code"] == "QUESTION_TOO_LONG"


def test_language_gate_rejects_chinese_without_consuming_quota(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_answer(monkeypatch)
    assert _problem(client.post("/v1/answers", json={"question": "你好"}))["code"] == (
        "INPUT_LANGUAGE_NOT_SUPPORTED"
    )
    assert _problem(client.post("/v1/answers", json={"question": "Hello 你好"}))["code"] == (
        "INPUT_LANGUAGE_NOT_SUPPORTED"
    )
    for _ in range(m26_public_api.PER_IP_DAILY_LIMIT):
        response = client.post(
            "/v1/answers", json={"question": "What is safe? https://x.test `code` 🙂"}
        )
        assert response.status_code == 200
    assert _problem(client.post("/v1/answers", json={"question": "What is safe?"}))["code"] == (
        "DAILY_IP_LIMIT_EXCEEDED"
    )


def test_sse_contract_has_monotonic_seq_single_terminal_and_no_early_answer_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_answer(monkeypatch)
    response = client.post(
        "/v1/answers",
        headers={"origin": "https://danielcanfly.com"},
        json={"question": "What is safe with URL https://example.com and code `x=1` 🙂?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    terminal = [event for event in events if event["type"].startswith("answer.")]
    assert len(terminal) == 1
    assert terminal[0]["type"] == "answer.completed"
    assert "Use one variable" not in "\n".join(
        json.dumps(event, sort_keys=True) for event in events[:-1]
    )
    assert any(event["type"] == "model.completed" for event in events)
    assert all(event["request_id"] == events[0]["request_id"] for event in events)


def test_safe_abstention_terminal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_answer(
        monkeypatch,
        _answer_dto(
            status="owner_only_safe_abstention",
            safe_abstention=True,
            answer_text="",
            citations=[],
            sources=[],
            answer_claims=[],
            reason_codes=["LOW_RETRIEVAL_SUPPORT"],
        ),
    )
    events = _sse_events(client.post("/v1/answers", json={"question": "What is safe?"}))
    assert events[-1]["type"] == "answer.abstained"
    assert events[-1]["code"] == "LOW_RETRIEVAL_SUPPORT"


def test_cors_allows_configured_origin_and_rejects_invalid_origin(client: TestClient) -> None:
    allowed = client.options("/v1/answers", headers={"origin": "https://danielcanfly.com"})
    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == "https://danielcanfly.com"
    rejected = client.post(
        "/v1/answers",
        headers={"origin": "https://evil.example"},
        json={"question": "What is safe?"},
    )
    assert _problem(rejected)["code"] == "PUBLIC_ADMISSION_DENIED"


def test_direct_origin_spoofed_cf_header_does_not_share_quota_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_answer(monkeypatch)
    for _ in range(m26_public_api.PER_IP_DAILY_LIMIT):
        assert (
            client.post(
                "/v1/answers",
                headers={"cf-connecting-ip": "203.0.113.10"},
                json={"question": "What is safe?"},
            ).status_code
            == 200
        )
    denied = client.post(
        "/v1/answers",
        headers={"cf-connecting-ip": "198.51.100.99"},
        json={"question": "What is safe?"},
    )
    assert _problem(denied)["code"] == "DAILY_IP_LIMIT_EXCEEDED"
    db_path = client.app.state.test_quota_path
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT key FROM quota_counts").fetchall()
    encoded = json.dumps(rows)
    assert "203.0.113.10" not in encoded
    assert "198.51.100.99" not in encoded


def test_active_ip_limit(client: TestClient) -> None:
    ip_key = m26_public_api._pseudonymous_ip_key(  # noqa: SLF001
        type(
            "RequestLike",
            (),
            {"client": type("Client", (), {"host": "testclient"})(), "headers": {}},
        )(),
        now=m26_public_api.datetime.now(m26_public_api.UTC),
    )
    with sqlite3.connect(client.app.state.test_quota_path) as db:
        client.app.state.public_quota_ledger._increment_active(  # noqa: SLF001
            db,
            "ip_active",
            ip_key,
        )
    response = client.post("/v1/answers", json={"question": "What is safe?"})
    assert _problem(response)["code"] == "ACTIVE_IP_REQUEST_LIMIT_EXCEEDED"


def test_provider_budget_guard(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M26_PUBLIC_PROVIDER_BUDGET_GUARD_ACTIVE", "true")
    response = client.post("/v1/answers", json={"question": "What is safe?"})
    assert _problem(response)["code"] == "PROVIDER_BUDGET_GUARD_ACTIVE"
