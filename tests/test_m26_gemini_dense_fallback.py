from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine.m23_cloudflare_qdrant import CLOUDFLARE_MODEL, SectionInput
from knowledge_engine.m26_gemini_dense_fallback import (
    GEMINI_DIMENSION,
    GEMINI_DOCUMENT_TASK_INTENT,
    GEMINI_MODEL,
    GEMINI_PROVIDER,
    GEMINI_QUERY_TASK_INTENT,
    GEMINI_VECTOR_NAME,
    M26_GEMINI_CANDIDATE_RELEASE_ID,
    M26_GEMINI_COLLECTION,
    GeminiDenseConfig,
    GeminiDenseFallbackError,
    GeminiEmbeddingClient,
    GeminiEmbeddingConfig,
    GeminiQdrantDenseChannel,
    build_gemini_qdrant_points,
    canonical_manifest_payload,
    format_retrieval_document,
    format_retrieval_query,
    qdrant_collection_create_payload,
)
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://example.invalid")

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "test status",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


def _unit_vector() -> list[float]:
    return [1.0, *([0.0] * (GEMINI_DIMENSION - 1))]


def _candidate_bundle() -> Any:
    bundle = synthetic_full_production_answer_bundle()
    manifest = dict(bundle.manifest)
    manifest["release_id"] = M26_GEMINI_CANDIDATE_RELEASE_ID
    return replace(bundle, manifest=manifest)


class _DenseSuccess:
    def __init__(self, *, gemini: bool = False) -> None:
        self.calls = 0
        self.gemini = gemini

    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        del question, bundle, top_k
        self.calls += 1
        if self.gemini:
            identity = {
                "backend": "test_gemini",
                "dense_provider": GEMINI_PROVIDER,
                "dense_model": GEMINI_MODEL,
                "dense_dimension": GEMINI_DIMENSION,
                "qdrant_collection": M26_GEMINI_COLLECTION,
            }
        else:
            identity = {
                "backend": "test_bge",
                "embedding_provider": "cloudflare-workers-ai",
                "embedding_model": CLOUDFLARE_MODEL,
                "vector_dimension": 1024,
            }
        return {
            "backend_identity": identity,
            "candidates": [
                {
                    "channel": "dense",
                    "section_id": "section_test",
                    "concept_id": "concept_test",
                    "score": 0.9,
                }
            ],
        }


class _DenseFailure:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        del question, bundle, top_k
        self.calls += 1
        raise self.exc


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://dense.invalid")
    return httpx.HTTPStatusError(
        f"status {status}", request=request, response=httpx.Response(status, request=request)
    )


def test_gemini_embedding_2_retrieval_intent_uses_supported_prompt_contract() -> None:
    assert format_retrieval_query("hello") == "task: search result | query: hello"
    assert format_retrieval_document("body", title="Title") == "title: Title | text: body"
    assert format_retrieval_document("body") == "title: none | text: body"
    manifest = canonical_manifest_payload()
    assert manifest["model"] == GEMINI_MODEL
    assert manifest["dimension"] == 768
    assert manifest["document_task_intent"] == GEMINI_DOCUMENT_TASK_INTENT
    assert manifest["query_task_intent"] == GEMINI_QUERY_TASK_INTENT
    assert manifest["api_task_type_parameter"] is None


def test_embed_query_wire_contract_omits_unsupported_task_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Response:
        captured.update({"url": url, **kwargs})
        return _Response({"embedding": {"values": _unit_vector()}})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = GeminiEmbeddingClient(GeminiEmbeddingConfig(api_key="unit-test-key"))
    vector = client.embed_query("how does fallback work?")

    assert len(vector) == 768
    assert captured["url"].endswith("/models/gemini-embedding-2:embedContent")
    body = captured["json"]
    assert body["output_dimensionality"] == 768
    assert "taskType" not in body
    assert "task_type" not in body
    assert body["content"]["parts"][0]["text"].startswith(
        "task: search result | query: "
    )
    assert captured["headers"]["x-goog-api-key"] == "unit-test-key"


def test_gemini_points_are_separate_space_and_provider_identified() -> None:
    section = SectionInput(
        section_id="section_1",
        text="body",
        payload={
            "release_id": M26_GEMINI_CANDIDATE_RELEASE_ID,
            "source_commit_sha": "f5e20062c1400d7320fe2dbecf6409a0a8c910a7",
            "admission_sha256": "ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d",
            "title": "Title",
        },
    )
    [point] = build_gemini_qdrant_points([section], [_unit_vector()])
    payload = point["payload"]
    assert payload["embedding_provider"] == GEMINI_PROVIDER
    assert payload["embedding_model"] == GEMINI_MODEL
    assert payload["embedding_task_intent"] == GEMINI_DOCUMENT_TASK_INTENT
    assert payload["vector_dimension"] == 768
    assert payload["vector_name"] == GEMINI_VECTOR_NAME
    assert point["vector"].keys() == {GEMINI_VECTOR_NAME}
    assert qdrant_collection_create_payload()["vectors"][GEMINI_VECTOR_NAME]["size"] == 768


def test_gemini_channel_rejects_collection_collision_with_primary() -> None:
    with pytest.raises(GeminiDenseFallbackError, match="GEMINI_VECTOR_SPACE_COLLISION"):
        GeminiQdrantDenseChannel(
            GeminiDenseConfig(
                embedding=GeminiEmbeddingConfig(api_key="unit-test-key"),
                qdrant_url="https://qdrant.invalid",
                qdrant_api_key="unit-test-qdrant-key",
                primary_qdrant_collection=M26_GEMINI_COLLECTION,
            )
        )


def test_cloudflare_success_does_not_call_gemini() -> None:
    primary = _DenseSuccess()
    fallback = _DenseSuccess(gemini=True)
    _, dense = runtime._run_lexical_primary_retrieval(
        question="What should a router define for permission-first controls?",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=fallback,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 1
    assert fallback.calls == 0
    assert identity["retrieval_mode"] == "hybrid_bge"
    assert identity["fallback_attempted"] is False


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_cloudflare_eligible_transient_status_routes_once_to_gemini(status: int) -> None:
    primary = _DenseFailure(_status_error(status))
    fallback = _DenseSuccess(gemini=True)
    _, dense = runtime._run_lexical_primary_retrieval(
        question="What should a router define for permission-first controls?",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=fallback,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 1
    assert fallback.calls == 1
    assert identity["retrieval_mode"] == "hybrid_gemini"
    assert identity["dense_provider"] == GEMINI_PROVIDER
    assert identity["dense_model"] == GEMINI_MODEL
    assert identity["dense_dimension"] == 768
    assert identity["fallback_attempted"] is True
    assert identity["fallback_succeeded"] is True


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("timeout", request=httpx.Request("POST", "https://dense.invalid")),
        httpx.ConnectError("network", request=httpx.Request("POST", "https://dense.invalid")),
    ],
)
def test_cloudflare_network_or_timeout_routes_once_to_gemini(exc: Exception) -> None:
    primary = _DenseFailure(exc)
    fallback = _DenseSuccess(gemini=True)
    _, dense = runtime._run_lexical_primary_retrieval(
        question="What should a router define for permission-first controls?",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=fallback,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 1
    assert fallback.calls == 1
    assert identity["retrieval_mode"] == "hybrid_gemini"
    assert identity["fallback_attempted"] is True
    assert identity["fallback_succeeded"] is True


def test_forced_candidate_qualification_bypasses_primary_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M26_GEMINI_DENSE_FORCE", "1")
    primary = _DenseSuccess()
    fallback = _DenseSuccess(gemini=True)
    _, dense = runtime._run_lexical_primary_retrieval(
        question="What should a router define for permission-first controls?",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=fallback,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 0
    assert fallback.calls == 1
    assert identity["retrieval_mode"] == "hybrid_gemini"
    assert identity["fallback_reason"] == "DENSE_FORCED_GEMINI_QUALIFICATION"


def test_gemini_transient_failure_degrades_to_lexical_only_without_ping_pong() -> None:
    primary = _DenseFailure(_status_error(429))
    fallback = _DenseFailure(_status_error(503))
    _, dense = runtime._run_lexical_primary_retrieval(
        question="What should a router define for permission-first controls?",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=fallback,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 1
    assert fallback.calls == 1
    assert dense["candidates"] == []
    assert identity["retrieval_mode"] == "lexical_only"
    assert identity["fallback_attempted"] is True
    assert identity["fallback_succeeded"] is False
    assert identity["fallback_dense_identity"]["reason_code"] == (
        "GEMINI_DENSE_TRANSIENT_UNAVAILABLE"
    )


@pytest.mark.parametrize("status", [401, 403])
def test_gemini_authority_errors_remain_fail_closed(status: int) -> None:
    primary = _DenseFailure(_status_error(429))
    fallback = _DenseFailure(_status_error(status))
    with pytest.raises(httpx.HTTPStatusError):
        runtime._run_lexical_primary_retrieval(
            question="What should a router define for permission-first controls?",
            bundle=_candidate_bundle(),
            dense_channel=primary,
            dense_fallback_channel=fallback,
            require_remote_dense=False,
            top_k=8,
            event_sink=None,
        )
    assert primary.calls == 1
    assert fallback.calls == 1


def test_fallback_injection_is_rejected_outside_frozen_candidate_release() -> None:
    with pytest.raises(runtime.PA7ArbitraryQueryError, match="candidate-release only"):
        runtime._run_lexical_primary_retrieval(
            question="What should a router define for permission-first controls?",
            bundle=synthetic_full_production_answer_bundle(),
            dense_channel=_DenseFailure(_status_error(429)),
            dense_fallback_channel=_DenseSuccess(gemini=True),
            require_remote_dense=False,
            top_k=8,
            event_sink=None,
        )
