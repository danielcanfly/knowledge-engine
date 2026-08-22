from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_google_translation_provider as google_provider_module
from knowledge_engine.m26_google_translation_provider import (
    ADCBearerTokenSource,
    GoogleTranslationLLMProvider,
    TranslationProviderConfig,
    TranslationProviderError,
    TranslationProviderResult,
)
from knowledge_engine import m26_translation_gateway_public_api as public_api
from knowledge_engine.m26_translation_gateway import (
    run_owner_translation_gateway_for_web,
    run_translation_gateway,
)
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


def test_owner_gateway_english_bypass_omits_downstream_provider_call_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine import m26_ask_api

    calls: list[dict[str, Any]] = []

    def fake_run_owner_query_for_web(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"answer_text": "ok"}

    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", fake_run_owner_query_for_web)

    result = run_owner_translation_gateway_for_web(
        root=type("Pathish", (), {})(),
        gate_path=type("Pathish", (), {})(),
        request_payload={"question": "What is the M26 PA7 status?"},
        owner_subject_hash="owner",
        provider=FakeProvider("unused"),
    )

    assert result["answer_text"] == "ok"
    assert len(calls) == 1
    assert calls[0]["request_payload"] == {"question": "What is the M26 PA7 status?"}
    assert "max_provider_calls" not in calls[0]
    assert "max_cost" not in calls[0]


def test_owner_gateway_translated_and_canonical_calls_have_same_downstream_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine import m26_ask_api

    calls: list[dict[str, Any]] = []

    def fake_run_owner_query_for_web(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"answer_text": "ok"}

    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", fake_run_owner_query_for_web)
    root = type("Pathish", (), {})()
    gate_path = type("Pathish", (), {})()
    translated_provider = FakeProvider("What is the M26 PA7 status?")

    run_owner_translation_gateway_for_web(
        root=root,
        gate_path=gate_path,
        request_payload={"question": "What is the M26 PA7 status?"},
        owner_subject_hash="owner",
        provider=FakeProvider("unused"),
    )
    run_owner_translation_gateway_for_web(
        root=root,
        gate_path=gate_path,
        request_payload={"question": "M26 PA7 狀態是什麼？"},
        owner_subject_hash="owner",
        provider=translated_provider,
    )

    english_call, translated_call = calls
    assert english_call.keys() == translated_call.keys()
    assert english_call["request_payload"] == {"question": "What is the M26 PA7 status?"}
    assert translated_call["request_payload"] == {"question": "What is the M26 PA7 status?"}
    assert "max_provider_calls" not in english_call
    assert "max_provider_calls" not in translated_call
    assert "max_cost" not in english_call
    assert "max_cost" not in translated_call


def test_owner_gateway_allows_explicit_internal_downstream_limit_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine import m26_ask_api

    calls: list[dict[str, Any]] = []

    def fake_run_owner_query_for_web(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"answer_text": "ok"}

    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", fake_run_owner_query_for_web)

    run_owner_translation_gateway_for_web(
        root=type("Pathish", (), {})(),
        gate_path=type("Pathish", (), {})(),
        request_payload={"question": "What is the M26 PA7 status?"},
        owner_subject_hash="owner",
        max_provider_calls=4,
        max_cost=Decimal("0.10"),
    )

    assert calls[0]["max_provider_calls"] == 4
    assert calls[0]["max_cost"] is not None


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


def test_closure_actor_binding_uses_generic_zh_tw_modal_predicate_grammar() -> None:
    source = "如果 evidence 缺少必要限制，closure 是否還能判定結果完整？"
    bound = bind_mixed_language_component_roles(source)
    assert bound.applied
    assert "technical component named closure" in bound.rewritten_text
    provider = FakeProvider("Can technical component named closure still decide completeness?")

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: {"question": question},
    )

    assert result.ok
    assert "technical component named closure" in provider.requests[0].text
    assert result.observability["role_binding"]["bound_components"] == ["closure"]


def test_selector_actor_binding_covers_assertion_predicate_without_case_text() -> None:
    source = "當 citation 不足時，selector 可以說候選證據不合格嗎？"
    bound = bind_mixed_language_component_roles(source)
    assert bound.applied
    assert "technical component named selector" in bound.rewritten_text
    provider = FakeProvider(
        "Can technical component named selector say the evidence is not qualified?"
    )

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: {"question": question},
    )

    assert result.ok
    assert "technical component named selector" in provider.requests[0].text
    assert result.observability["role_binding"]["bound_components"] == ["selector"]


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


class FakeCredentials:
    def __init__(self) -> None:
        self.token = ""
        self.valid = False
        self.refreshes = 0

    def refresh(self, request: Any) -> None:
        self.refreshes += 1
        self.token = f"token-{self.refreshes}"
        self.valid = True


class RefreshFailureCredentials:
    token = ""
    valid = False

    def refresh(self, request: Any) -> None:
        raise RuntimeError("raw credential refresh exploded")


class MissingTokenCredentials:
    token = ""
    valid = False

    def refresh(self, request: Any) -> None:
        self.valid = True
        self.token = ""


def test_adc_token_source_reuses_valid_credentials() -> None:
    credentials = FakeCredentials()
    source = ADCBearerTokenSource(credentials=credentials, auth_request=object())

    assert source.token() == "token-1"
    assert source.token() == "token-1"
    assert credentials.refreshes == 1
    assert source.refresh_count == 1


def test_adc_token_source_refreshes_expired_or_invalid_credentials() -> None:
    credentials = FakeCredentials()
    source = ADCBearerTokenSource(credentials=credentials, auth_request=object())

    assert source.token() == "token-1"
    credentials.valid = False
    assert source.token() == "token-2"
    assert credentials.refreshes == 2
    assert source.refresh_count == 2


def test_provider_reuses_adc_source_without_hidden_translation_retry() -> None:
    credentials = FakeCredentials()
    source = ADCBearerTokenSource(credentials=credentials, auth_request=object())
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"translations": [{"translatedText": "Hello"}]})

    provider = GoogleTranslationLLMProvider(
        TranslationProviderConfig(project_id="proj"),
        token_source=source,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = type(
        "Req",
        (),
        {
            "text": "你好",
            "source_language": "zh-TW",
            "target_language": "en",
            "mime_type": "text/plain",
        },
    )()

    assert provider.translate(request).ok
    assert provider.translate(request).ok
    assert provider.calls == 2
    assert http_calls == 2
    assert credentials.refreshes == 1


def test_api_request_lifecycle_reuses_app_scoped_provider_token_source_and_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine import m26_ask_api

    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "test")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner")
    downstream_questions: list[str] = []
    http_calls = 0
    factory_calls = 0
    providers: list[GoogleTranslationLLMProvider] = []
    credentials = FakeCredentials()

    def fake_run_owner_query_for_web(**kwargs: Any) -> dict[str, Any]:
        downstream_questions.append(kwargs["request_payload"]["question"])
        return {"answer_text": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        payload = json.loads(request.content.decode())
        protected_text = payload["contents"][0]
        assert request.headers["authorization"] == "Bearer token-1"
        return httpx.Response(
            200,
            json={"translations": [{"translatedText": f"What is {protected_text}?"}]},
        )

    def provider_factory() -> GoogleTranslationLLMProvider:
        nonlocal factory_calls
        factory_calls += 1
        provider = GoogleTranslationLLMProvider(
            TranslationProviderConfig(project_id="proj"),
            token_source=ADCBearerTokenSource(credentials=credentials, auth_request=object()),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        providers.append(provider)
        return provider

    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", fake_run_owner_query_for_web)
    app = create_app(provider_factory=provider_factory)
    client = TestClient(app)
    headers = {
        "authorization": "Bearer test",
        "x-m26-owner-subject-hash": "owner",
    }

    response_1 = client.post(
        "/v1/translation-gateway/query",
        headers=headers,
        json={"question": "版本 v1.4.2 是什麼？"},
    )
    response_2 = client.post(
        "/v1/translation-gateway/query",
        headers=headers,
        json={"question": "版本 v1.4.2 是什麼？"},
    )

    assert response_1.status_code == 200
    assert response_2.status_code == 200
    assert factory_calls == 1
    assert len(providers) == 1
    assert providers[0].calls == 2
    assert http_calls == 2
    assert credentials.refreshes == 1
    assert downstream_questions == [
        "What is 版本 v1.4.2 是什麼？?",
        "What is 版本 v1.4.2 是什麼？?",
    ]


def test_provider_without_injected_token_uses_adc_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = FakeCredentials()
    monkeypatch.setattr(
        google_provider_module,
        "_default_adc_credentials",
        lambda: credentials,
    )
    monkeypatch.setattr(
        google_provider_module,
        "_google_auth_request",
        lambda: object(),
    )
    captured_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_auth.append(request.headers["authorization"])
        return httpx.Response(200, json={"translations": [{"translatedText": "Hello"}]})

    provider = GoogleTranslationLLMProvider(
        TranslationProviderConfig(project_id="proj"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
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
    assert captured_auth == ["Bearer token-1"]
    assert credentials.refreshes == 1


@pytest.mark.parametrize(
    ("provider_factory", "expected_code"),
    [
        (
            lambda: GoogleTranslationLLMProvider(
                TranslationProviderConfig(project_id="proj"),
                client=httpx.Client(
                    transport=httpx.MockTransport(lambda request: httpx.Response(200))
                ),
            ),
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
        ),
        (
            lambda: GoogleTranslationLLMProvider(
                TranslationProviderConfig(project_id="proj"),
                token_source=ADCBearerTokenSource(
                    credentials=RefreshFailureCredentials(),
                    auth_request=object(),
                ),
                client=httpx.Client(
                    transport=httpx.MockTransport(lambda request: httpx.Response(200))
                ),
            ),
            "TRANSLATION_PROVIDER_FAILED",
        ),
        (
            lambda: GoogleTranslationLLMProvider(
                TranslationProviderConfig(project_id="proj"),
                token_source=ADCBearerTokenSource(
                    credentials=MissingTokenCredentials(),
                    auth_request=object(),
                ),
                client=httpx.Client(
                    transport=httpx.MockTransport(lambda request: httpx.Response(200))
                ),
            ),
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
        ),
    ],
)
def test_auth_failures_fail_closed_before_downstream(
    monkeypatch: pytest.MonkeyPatch,
    provider_factory: Any,
    expected_code: str,
) -> None:
    if expected_code == "TRANSLATION_PROVIDER_CONFIG_MISSING":
        monkeypatch.setattr(
            google_provider_module,
            "_default_adc_credentials",
            lambda: (_ for _ in ()).throw(
                TranslationProviderError(
                    "TRANSLATION_PROVIDER_CONFIG_MISSING",
                    "sanitized adc discovery failed",
                )
            ),
        )
    provider = provider_factory()
    seen: list[str] = []

    result = run_translation_gateway(
        question="版本 v1.4.2 是什麼？",
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "bad"},
    )

    assert not result.ok
    assert result.failure_code == expected_code
    assert seen == []
    assert provider.calls == 1


def test_staging_api_returns_sanitized_503_for_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "test")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner")
    monkeypatch.setattr(
        google_provider_module,
        "_default_adc_credentials",
        lambda: (_ for _ in ()).throw(
            TranslationProviderError(
                "TRANSLATION_PROVIDER_CONFIG_MISSING",
                "sanitized adc discovery failed",
            )
        ),
    )
    app = create_app(
        provider_factory=lambda: GoogleTranslationLLMProvider(
            TranslationProviderConfig(project_id="proj"),
            client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
        )
    )
    client = TestClient(app)

    response = client.post(
        "/v1/translation-gateway/query",
        headers={
            "authorization": "Bearer test",
            "x-m26-owner-subject-hash": "owner",
        },
        json={"question": "版本 v1.4.2 是什麼？"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "TRANSLATION_PROVIDER_CONFIG_MISSING"
    assert "raw adc" not in json.dumps(detail).lower()


@pytest.mark.parametrize(
    ("env_updates", "expected_code"),
    [
        ({}, "TRANSLATION_PROVIDER_CONFIG_MISSING"),
        (
            {
                "M26_TRANSLATION_GOOGLE_PROJECT_ID": "proj",
                "M26_TRANSLATION_TIMEOUT_SECONDS": "not-a-number",
            },
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
        ),
        (
            {
                "M26_TRANSLATION_GOOGLE_PROJECT_ID": "proj",
                "M26_TRANSLATION_GOOGLE_MODEL": "general/nmt",
            },
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
        ),
    ],
)
def test_provider_factory_configuration_failures_are_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
    env_updates: dict[str, str],
    expected_code: str,
) -> None:
    from knowledge_engine import m26_ask_api

    downstream_calls = 0

    def fake_run_owner_query_for_web(**kwargs: Any) -> dict[str, Any]:
        nonlocal downstream_calls
        downstream_calls += 1
        return {"answer_text": "bad"}

    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "test")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner")
    monkeypatch.delenv("M26_TRANSLATION_GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    monkeypatch.delenv("M26_TRANSLATION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("M26_TRANSLATION_GOOGLE_MODEL", raising=False)
    for key, value in env_updates.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(m26_ask_api, "run_owner_query_for_web", fake_run_owner_query_for_web)
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1/translation-gateway/query",
        headers={
            "authorization": "Bearer test",
            "x-m26-owner-subject-hash": "owner",
        },
        json={"question": "版本 v1.4.2 是什麼？"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == expected_code
    assert detail["message"] == "M26 translation gateway failed closed before sealed runtime"
    assert downstream_calls == 0


def test_provider_factory_failure_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "test")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner")
    factory_calls = 0

    def broken_factory() -> Any:
        nonlocal factory_calls
        factory_calls += 1
        raise TranslationProviderError(
            "TRANSLATION_PROVIDER_CONFIG_MISSING",
            "sanitized factory failure",
        )

    app = create_app(provider_factory=broken_factory)
    client = TestClient(app)

    response = client.post(
        "/v1/translation-gateway/query",
        headers={
            "authorization": "Bearer test",
            "x-m26-owner-subject-hash": "owner",
        },
        json={"question": "版本 v1.4.2 是什麼？"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "TRANSLATION_PROVIDER_CONFIG_MISSING"
    assert factory_calls == 1


@pytest.mark.parametrize(
    ("source", "english"),
    [
        ("這個結果非常重要嗎？", "Is this result very important?"),
        ("未來要支援哪些模型？", "Which models should be supported in the future?"),
        (
            "無論哪個 provider 都要 fail closed 嗎？",
            "Should it fail closed regardless of the provider?",
        ),
    ],
)
def test_negation_guard_does_not_hard_fail_non_negative_compounds(
    source: str,
    english: str,
) -> None:
    provider = FakeProvider(english)
    seen: list[str] = []

    result = run_translation_gateway(
        question=source,
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert seen == [english]
    assert result.observability["invariant_checks"]["negation_requires_semantic_review"] is False


def test_negation_guard_accepts_lacks_as_valid_negative_realization() -> None:
    provider = FakeProvider("the evidence lacks a necessary constraint")
    seen: list[str] = []

    result = run_translation_gateway(
        question="evidence 沒有包含必要限制",
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert seen == ["the evidence lacks a necessary constraint"]
    checks = result.observability["invariant_checks"]
    assert checks["negation_token_not_obviously_lost"] is True
    assert checks["negation_requires_semantic_review"] is False


def test_negation_guard_flags_obvious_loss_for_semantic_review_without_hard_fail() -> None:
    provider = FakeProvider("the evidence includes a necessary constraint")
    seen: list[str] = []

    result = run_translation_gateway(
        question="evidence 沒有包含必要限制",
        provider=provider,
        downstream=lambda question: seen.append(question) or {"answer_text": "ok"},
    )

    assert result.ok
    assert seen == ["the evidence includes a necessary constraint"]
    checks = result.observability["invariant_checks"]
    assert checks["negation_token_not_obviously_lost"] is False
    assert checks["negation_requires_semantic_review"] is True


def test_provider_failure_does_not_retry_translation_request() -> None:
    credentials = FakeCredentials()
    source = ADCBearerTokenSource(credentials=credentials, auth_request=object())
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(500, json={"error": "bad"})

    provider = GoogleTranslationLLMProvider(
        TranslationProviderConfig(project_id="proj"),
        token_source=source,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
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
    assert result.failure_code == "TRANSLATION_PROVIDER_FAILED"
    assert provider.calls == 1
    assert http_calls == 1


def test_public_answers_route_reports_canonical_surface_and_streams_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setattr(
        public_api,
        "run_owner_translation_gateway_for_web",
        lambda **_: {
            "answer_text": "A grounded supported answer.",
            "answer_source": "provider_verified_runtime_bound_semantic_closure",
            "provider_identity": "MiniMax",
            "model_identity": "MiniMax-M3",
            "translation_gateway": {
                "translation_applied": True,
                "provider": "Google",
                "invariant_check_result": "pass",
            },
            "runtime_observability": {
                "stage_timings": [
                    {"stage": "dense_retrieval"},
                    {"stage": "semantic_synthesis_and_verification"},
                ]
            },
            "ok": True,
            "abstained": False,
        },
    )

    app = create_app(translation_provider=FakeProvider("unused"))
    client = TestClient(app)

    health = client.get("/v1/answers/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["surface"] == "/v1/answers"
    assert payload["canonical_host"] == "api-staging.danielcanfly.com"
    assert payload["legacy_api_rag_surface_canonical"] is False
    assert payload["legacy_namespace_status"] == "retired_compatibility_not_canonical"

    response = client.post("/v1/answers", json={"question": "What is Daniel working on?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in response.text
    assert "event: progress" in response.text
    assert "event: answer" in response.text
    assert "A grounded supported answer." in response.text


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
