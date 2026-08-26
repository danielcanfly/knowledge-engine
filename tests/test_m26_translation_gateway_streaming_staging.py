from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi.testclient import TestClient

from knowledge_engine import m26_public_api as public_api
from knowledge_engine import m26_translation_gateway_streaming_staging as streaming
from knowledge_engine.m26_google_translation_provider import TranslationProviderResult
from knowledge_engine.m26_translation_gateway import (
    TranslationGatewayResult,
    run_translation_gateway,
)


class _BombProvider:
    def translate(self, request: Any) -> TranslationProviderResult:
        raise AssertionError("English bypass must not invoke the translation provider")


class _FakeTranslationProvider:
    def translate(self, request: Any) -> TranslationProviderResult:
        return TranslationProviderResult(
            ok=True,
            translated_text="What is RAG?",
            provider="google-translation-advanced-v3",
            model_resource="general/translation-llm",
            location="us-central1",
            latency_ms=1,
        )


def test_english_gateway_bypass_is_exact_and_provider_free() -> None:
    seen: list[str] = []

    def downstream(question: str) -> Mapping[str, Any]:
        seen.append(question)
        return {"status": "ok"}

    result = run_translation_gateway(
        question="What is RAG?",
        downstream=downstream,
        provider=_BombProvider(),
    )
    assert result.ok is True
    assert result.translated_question_en == "What is RAG?"
    assert result.observability["translation_applied"] is False
    assert seen == ["What is RAG?"]


def test_zh_tw_gateway_uses_qualified_translation_before_downstream() -> None:
    seen: list[str] = []
    result = run_translation_gateway(
        question="什麼是 RAG？",
        downstream=lambda question: seen.append(question) or {"status": "ok"},
        provider=_FakeTranslationProvider(),
    )
    assert result.ok is True
    assert result.observability["translation_applied"] is True
    assert seen == ["What is RAG?"]


def test_streaming_route_hands_translated_english_to_existing_sse_runtime(monkeypatch) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "edge-secret")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash")
    seen: dict[str, str] = {}

    def fake_translate(**kwargs: Any) -> TranslationGatewayResult:
        assert kwargs["question"] == "什麼是 RAG？"
        return TranslationGatewayResult(
            ok=True,
            sealed_m26_response={"translated_question_en": "What is RAG?"},
            translated_question_en="What is RAG?",
            observability={"translation_applied": True},
        )

    async def fake_stream(**kwargs: Any):
        seen["question"] = kwargs["question"]
        request_id = kwargs["admission"].request_id
        yield "id: 1\nevent: request.accepted\ndata: " + json.dumps(
            {
                "schema_version": public_api.EVENT_SCHEMA_VERSION,
                "seq": 1,
                "request_id": request_id,
                "created_at": "2026-08-22T00:00:00Z",
                "type": "request.accepted",
            }
        ) + "\n\n"
        yield "id: 2\nevent: answer.completed\ndata: " + json.dumps(
            {
                "schema_version": public_api.EVENT_SCHEMA_VERSION,
                "seq": 2,
                "request_id": request_id,
                "created_at": "2026-08-22T00:00:01Z",
                "type": "answer.completed",
                "answer": "RAG answer",
                "citations": [],
            }
        ) + "\n\n"

    monkeypatch.setattr(streaming, "run_translation_gateway", fake_translate)
    monkeypatch.setattr(public_api, "_answer_event_stream", fake_stream)

    client = TestClient(streaming.app)
    response = client.post(
        "/v1/translation-gateway/answers",
        json={"question": "什麼是 RAG？"},
        headers={
            "authorization": "Bearer edge-secret",
            "x-m26-owner-subject-hash": "owner-hash",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]
    assert seen == {"question": "What is RAG?"}
    assert "answer.completed" in response.text


def test_translation_failure_never_reaches_sealed_sse_runtime(monkeypatch) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "edge-secret")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash")

    monkeypatch.setattr(
        streaming,
        "run_translation_gateway",
        lambda **kwargs: TranslationGatewayResult(
            ok=False,
            sealed_m26_response=None,
            translated_question_en="",
            observability={"gateway_failure_code": "TRANSLATION_INVARIANT_FAILED"},
            failure_code="TRANSLATION_INVARIANT_FAILED",
            failure_detail="closed",
        ),
    )

    async def forbidden_stream(**kwargs: Any):
        raise AssertionError("sealed runtime must not run after translation failure")
        yield ""

    monkeypatch.setattr(public_api, "_answer_event_stream", forbidden_stream)
    client = TestClient(streaming.app)
    response = client.post(
        "/v1/translation-gateway/answers",
        json={"question": "測試"},
        headers={
            "authorization": "Bearer edge-secret",
            "x-m26-owner-subject-hash": "owner-hash",
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "TRANSLATION_INVARIANT_FAILED"
