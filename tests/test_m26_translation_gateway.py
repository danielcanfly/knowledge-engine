from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from knowledge_engine.m26_google_translation_provider import (
    GoogleTranslationLLMProvider,
    TranslationProviderConfig,
    TranslationProviderResult,
)
from knowledge_engine.m26_translation_gateway import run_translation_gateway
from knowledge_engine import m26_translation_gateway_public_api as public_gateway_module
from knowledge_engine.m26_translation_gateway_public_api import create_app
from knowledge_engine.m26_translation_invariants import (
    bind_mixed_language_component_roles,
    detect_input_language,
    protect_spans,
)


@dataclass
class FakeProvider:
    translated_text: str
    ok: bool = True
    failure_code: str = ""
    failure_detail: str = ""
    calls: int = 0
    requests: list[Any] = field(default_factory=list)

    def translate(self, request: Any) -> TranslationProviderResult:
        self.calls += 1
        self.requests.append(request)
        return TranslationProviderResult(
            ok=self.ok,
            translated_text=self.translated_text,
            failure_code=self.failure_code,
            failure_detail=self.failure_detail,
            model_resource="projects/test/locations/us-central1/models/general/translation-llm",
            location="us-central1",
            latency_ms=7,
        )


def test_english_bypass_reaches_sealed_path_unchanged_and_skips_provider() -> None:
    provider = FakeProvider("unused")
    seen: list[str] = []

    result = run_translation_gateway(
        question="What is the M26 PA7 production authority status?",
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert seen == ["What is the M26 PA7 production authority status?"]
    assert provider.calls == 0
    assert result.observability["translation_applied"] is False
    assert result.observability["invariant_check_result"] == "english_bypass"


def test_zh_tw_translation_invokes_provider_once_and_passes_english_to_sealed_path() -> None:
    source = "版本 v1.4.2 的答案是什麼？"
    protected = protect_spans(source)
    provider = FakeProvider(f"What is the answer for {protected.spans[0].placeholder}?")
    seen: list[str] = []

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert provider.calls == 1
    assert provider.requests[0].target_language == "en"
    assert provider.requests[0].mime_type == "text/plain"
    assert provider.requests[0].source_language == "zh-TW"
    assert seen == ["What is the answer for v1.4.2?"]
    assert result.observability["invariant_check_result"] == "pass"


def test_mixed_input_role_binding_is_generic_and_preserves_technical_identifier() -> None:
    source = "請說明 verifier 判斷 API-42 是否通過的依據。"
    protected = protect_spans(
        bind_mixed_language_component_roles(source).rewritten_text
    )
    assert "technical component named verifier" in protected.protected_text
    provider = FakeProvider(
        f"Explain how technical component named verifier judges {protected.spans[0].placeholder}."
    )
    seen: list[str] = []

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert detect_input_language(source) == "mixed"
    assert "verifier" in seen[0]
    assert "API-42" in seen[0]
    assert result.observability["role_binding"]["applied"] is True
    assert result.observability["role_binding"]["bound_components"] == ["verifier"]


def test_protected_spans_restore_urls_hashes_versions_model_ids_numbers_and_code() -> None:
    sha = "a" * 64
    source = (
        "請比較 https://example.com/a 與 "
        f"{sha}、v1.4.2.1、general/translation-llm、"
        "src/knowledge_engine/m26_translation_gateway.py、"
        "_answer_event_stream、42、98.5%、<= 是否一致。"
    )
    protected = protect_spans(source)
    provider = FakeProvider("Check " + " ".join(span.placeholder for span in protected.spans))
    seen: list[str] = []

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    sealed_question = seen[0]
    for expected in (
        "https://example.com/a",
        sha,
        "v1.4.2.1",
        "general/translation-llm",
        "src/knowledge_engine/m26_translation_gateway.py",
        "_answer_event_stream",
        "42",
        "98.5%",
        "<=",
    ):
        assert expected in sealed_question


@pytest.mark.parametrize(
    ("translated", "code"),
    [
        ("This lost the only placeholder.", "TRANSLATION_INVARIANT_FAILED"),
        ("Use __M26TG0__ and __M26TG0__ twice.", "TRANSLATION_INVARIANT_FAILED"),
        ("Use __M26TG999__.", "TRANSLATION_INVARIANT_FAILED"),
        ("", "TRANSLATION_OUTPUT_INVALID"),
    ],
)
def test_gateway_fails_closed_for_invariant_failures(translated: str, code: str) -> None:
    source = "版本 v1.4.2 不應通過嗎？"
    provider = FakeProvider(translated)
    seen: list[str] = []

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "bad"},
    )

    assert not result.ok
    assert result.failure_code == code
    assert seen == []
    assert result.observability["gateway_failure_code"] == code


@pytest.mark.parametrize(
    "provider_result",
    [
        TranslationProviderResult(
            ok=False,
            failure_code="TRANSLATION_PROVIDER_FAILED",
            failure_detail="HTTP 500",
        ),
        TranslationProviderResult(
            ok=False,
            failure_code="TRANSLATION_TIMEOUT",
            failure_detail="timeout",
        ),
    ],
)
def test_gateway_fails_closed_for_provider_failures(
    provider_result: TranslationProviderResult,
) -> None:
    class BrokenProvider:
        calls = 0

        def translate(self, request: Any) -> TranslationProviderResult:
            self.calls += 1
            return provider_result

    seen: list[str] = []
    result = run_translation_gateway(
        question="這個版本 v1.4.2 是什麼？",
        provider=BrokenProvider(),
        downstream=lambda question: seen.append(question) or {"answer_text": "bad"},
    )

    assert not result.ok
    assert result.failure_code == provider_result.failure_code
    assert seen == []


def test_request_cannot_choose_provider_or_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "test")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1/translation-gateway/query",
        headers={
            "authorization": "Bearer test",
            "x-m26-owner-subject-hash": "owner",
        },
        json={
            "question": "你好",
            "provider": "attacker",
            "model": "general/nmt",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "M26_TG_REQUEST_FIELD_DENIED"


def test_missing_server_side_translation_config_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("M26_TRANSLATION_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    seen: list[str] = []

    result = run_translation_gateway(
        question="這個版本 v1.4.2 是什麼？",
        downstream=lambda question: seen.append(question) or {"answer_text": "bad"},
    )

    assert not result.ok
    assert result.failure_code == "TRANSLATION_PROVIDER_CONFIG_MISSING"
    assert seen == []


def test_google_provider_uses_configured_model_and_plain_text_mime() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = request.read().decode()
        return httpx.Response(200, json={"translations": [{"translatedText": "Hello"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GoogleTranslationLLMProvider(
        TranslationProviderConfig(project_id="proj", location="us-central1"),
        access_token="token",
        client=client,
    )

    result = provider.translate(
        type(
            "Req",
            (),
            {
                "text": "你好",
                "source_language": "zh-TW",
                "target_language": "en",
                "mime_type": "text/plain",
            },
        )()
    )

    assert result.ok
    assert '"mimeType":"text/plain"' in captured["json"]
    assert "projects/proj/locations/us-central1/models/general/translation-llm" in captured["json"]


@pytest.mark.parametrize(
    ("response_status", "response_json", "expected_code"),
    [
        (500, {"error": "bad"}, "TRANSLATION_PROVIDER_FAILED"),
        (200, {"unexpected": []}, "TRANSLATION_OUTPUT_INVALID"),
    ],
)
def test_google_provider_4xx_5xx_and_malformed_response_fail_safely(
    response_status: int,
    response_json: dict[str, Any],
    expected_code: str,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(response_status, json=response_json)
        )
    )
    provider = GoogleTranslationLLMProvider(
        TranslationProviderConfig(project_id="proj"),
        access_token="token",
        client=client,
    )

    result = provider.translate(
        type(
            "Req",
            (),
            {
                "text": "你好",
                "source_language": "zh-TW",
                "target_language": "en",
                "mime_type": "text/plain",
            },
        )()
    )

    assert not result.ok
    assert result.failure_code == expected_code


def test_public_answers_route_streams_sse_and_reports_canonical_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "legacy-token")
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        lambda **_: {
            "schema_version": "knowledge-engine-m26-pa7-arbitrary-owner-query-response/v1",
            "status": "owner_only_cited_answer",
            "terminal_status": "answered",
            "trace_id": "trace-test",
            "question_sha256": "ab" * 32,
            "answer_text": "A grounded supported answer.",
            "answer_source": "provider_verified_runtime_bound_semantic_closure",
            "safe_abstention": False,
            "reason_codes": [],
            "citations": [
                {
                    "citation_id": "c1",
                    "claim_id": "claim_1",
                    "claim_role": "relationship",
                    "evidence_id": "evidence_1",
                    "evidence_type": "passage",
                    "locator_id": "loc_1",
                    "source_id": "source_1",
                    "source_identity": "source_identity_1",
                    "section_id": "section_1",
                    "concept_id": "concept_1",
                    "release_id": "release_test",
                    "source_locator": "synthetic://source/1",
                    "source_artifact_sha256": "11" * 32,
                    "support_text_sha256": "12" * 32,
                    "exact_quote_sha256": "13" * 32,
                    "provenance_record_sha256": "14" * 32,
                    "runtime_owned_locator": True,
                }
            ],
            "sources": [
                {
                    "title": "Source 1",
                    "url": "https://example.com/source-1",
                    "preview": "Preview 1",
                    "marker": "#1",
                }
            ],
            "answer_claims": [{"claim_id": "claim_1", "claim_role": "relationship"}],
            "relationship_summary": {},
            "multi_evidence_verification": {"support_precision": 1.0},
            "runtime_observability": {
                "schema_version": "m26-pa7-runtime-observability/v1",
                "stage_timings": [
                    {"stage": "dense_retrieval", "elapsed_ms": 2, "candidate_count": 4},
                    {
                        "stage": "semantic_synthesis_and_verification",
                        "elapsed_ms": 5,
                        "candidate_count": 1,
                    },
                ],
            },
            "provider_identity": "MiniMax",
            "model_identity": "MiniMax-M3",
            "runtime_policy_router": {"resolved": {"provider": "MiniMax"}},
            "translation_gateway": {
                "translation_applied": True,
                "provider": "Google",
                "model_resource": "projects/test/locations/us-central1/models/general/translation-llm",
                "invariant_check_result": "pass",
            },
            "ok": True,
            "abstained": False,
        },
    )
    app = create_app(
        root=Path(__file__).resolve().parents[1],
        gate_path=Path(__file__).resolve().parents[1]
        / "pilot/m26/m26-pa-7-resolved-production-gate.json",
    )
    client = TestClient(app)

    health = client.get("/v1/answers/health")
    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["surface"]["canonical_answers_url"].endswith("/v1/answers")
    assert health_payload["surface"]["legacy_api_rag_surface_canonical"] is False
    assert health_payload["surface"]["legacy_translation_gateway_url"].endswith(
        "/v1/translation-gateway/query"
    )

    with client.stream(
        "POST",
        "/v1/answers",
        json={"question": "What is the canonical M26 staging surface?"},
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in text
    assert "event: progress" in text
    assert "event: answer" in text
    assert "event: done" in text
    assert "A grounded supported answer." in text
