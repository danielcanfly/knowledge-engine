from __future__ import annotations

import inspect
import json
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine.m23_cloudflare_qdrant import CLOUDFLARE_MODEL
from knowledge_engine.m26_cloudflare_provider_router import (
    CLOUDFLARE_PROVIDER,
    MINIMAX_PROVIDER,
    CloudflareFallbackRequired,
    CloudflareRouterState,
    ProviderRoutingClient,
)
from knowledge_engine.m26_gemini_dense_fallback import (
    GEMINI_DIMENSION,
    GEMINI_MODEL,
    GEMINI_PROVIDER,
    M26_GEMINI_CANDIDATE_RELEASE_ID,
    M26_GEMINI_COLLECTION,
)
from knowledge_engine.m26_production_promotion_closure import load_json
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle

ROOT = Path(__file__).resolve().parents[1]
GATE = load_json(ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json")
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
ANSWERABLE_QUESTION = "What should a router define for permission-first controls?"
UNSUPPORTED_QUESTION = "Explain zqvplm norfex klyrith."


def _payload_task(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload["messages"][0]["content"]
    text = content[0]["text"] if isinstance(content, list) else content
    return json.loads(text)


def _candidate_bundle() -> Any:
    bundle = synthetic_full_production_answer_bundle()
    manifest = dict(bundle.manifest)
    manifest["release_id"] = M26_GEMINI_CANDIDATE_RELEASE_ID
    return replace(bundle, manifest=manifest)


def _answer_result(payload: dict[str, Any], call_class: str, response_id: str) -> dict[str, Any]:
    task = _payload_task(payload)
    passage = next(
        item for item in task["evidence_bundle"] if item["evidence_type"] == "passage"
    )
    return {
        "text": json.dumps(
            {
                "status": "answer",
                "answer_text": "The selected evidence supports the requested answer.",
                "citation_ids": [passage["evidence_id"]],
                "abstention_reason": None,
            }
        ),
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "cost_usd": "0.00001",
        "latency_ms": 1,
        "response_id": response_id,
        "call_class": call_class,
    }


class _GenerationProvider:
    def __init__(self, *, failure: str = "", name: str) -> None:
        self.failure = failure
        self.name = name
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        if self.failure:
            raise CloudflareFallbackRequired(self.failure)
        self.cost += Decimal("0.00001")
        return _answer_result(payload, call_class, f"{self.name}-{self.calls}")


class _DenseChannel:
    def __init__(self, *, provider: str, failure: Exception | None = None) -> None:
        self.provider = provider
        self.failure = failure
        self.calls = 0
        self._local = runtime.LocalDenseProjectionChannel()

    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        result = self._local.search(question=question, bundle=bundle, top_k=top_k)
        identity = dict(result.get("backend_identity", {}))
        if self.provider == "bge":
            identity.update(
                {
                    "backend": "qdrant_bge_dense_test_double",
                    "embedding_provider": CLOUDFLARE_PROVIDER,
                    "embedding_model": CLOUDFLARE_MODEL,
                    "vector_dimension": 1024,
                    "qdrant_collection": "bge-primary-test-collection",
                }
            )
        else:
            identity.update(
                {
                    "backend": "qdrant_gemini_dense_test_double",
                    "dense_provider": GEMINI_PROVIDER,
                    "dense_model": GEMINI_MODEL,
                    "dense_dimension": GEMINI_DIMENSION,
                    "qdrant_collection": M26_GEMINI_COLLECTION,
                }
            )
        result["backend_identity"] = identity
        return result


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://dense.invalid/search")
    return httpx.HTTPStatusError(
        f"dense status {status}", request=request, response=httpx.Response(status, request=request)
    )


def _run_integrated_request(
    *,
    question: str,
    primary: _DenseChannel,
    secondary: _DenseChannel | None,
    cloudflare_failure: str = "",
) -> tuple[
    dict[str, Any],
    ProviderRoutingClient,
    _GenerationProvider,
    _GenerationProvider,
    list[dict[str, Any]],
]:
    cloudflare = _GenerationProvider(failure=cloudflare_failure, name="cloudflare")
    minimax = _GenerationProvider(name="minimax")
    router = ProviderRoutingClient(
        cloudflare=cloudflare,  # type: ignore[arg-type]
        fallback=minimax,  # type: ignore[arg-type]
        reviewer=minimax,  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )
    events: list[dict[str, Any]] = []
    response = runtime.run_owner_arbitrary_query(
        root=ROOT,
        gate=GATE,
        question=question,
        owner_subject_hash=OWNER_SUBJECT_HASH,
        provider_client=router,
        dense_channel=primary,
        dense_fallback_channel=secondary,
        answer_bundle=_candidate_bundle(),
        event_sink=events.append,
    )
    return response, router, cloudflare, minimax, events


def _assert_single_request_path(events: list[dict[str, Any]], *, generated: bool) -> None:
    assert (
        sum(
            event.get("type") == "stage.started" and event.get("stage") == "retrieval"
            for event in events
        )
        == 1
    )
    assert (
        sum(
            event.get("type") == "stage.started" and event.get("stage") == "admission"
            for event in events
        )
        == 1
    )
    synthesis_count = sum(
        event.get("type") == "stage.started" and event.get("stage") == "synthesis"
        for event in events
    )
    assert synthesis_count == (1 if generated else 0)


def test_x1_bge_hybrid_and_cloudflare_generation_success() -> None:
    response, router, cloudflare, minimax, events = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=_DenseChannel(provider="bge"),
        secondary=_DenseChannel(provider="gemini"),
    )
    identity = response["retrieval_backend_identity"]["dense"]
    assert response["status"] == "owner_only_cited_answer"
    assert response["retrieval_mode_summary"]["retrieval_mode"] == "hybrid_bge"
    assert identity["dense_provider"] == CLOUDFLARE_PROVIDER
    assert cloudflare.calls == 1 and minimax.calls == 0
    assert router.telemetry()["fallback_used"] is False
    assert router.calls == 1
    _assert_single_request_path(events, generated=True)


def test_x2_gemini_hybrid_and_cloudflare_generation_success() -> None:
    primary = _DenseChannel(provider="bge", failure=_status_error(429))
    secondary = _DenseChannel(provider="gemini")
    response, router, cloudflare, minimax, events = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=primary,
        secondary=secondary,
    )
    identity = response["retrieval_backend_identity"]["dense"]
    assert response["status"] == "owner_only_cited_answer"
    assert response["retrieval_mode_summary"]["retrieval_mode"] == "hybrid_gemini"
    assert primary.calls == 1 and secondary.calls == 1
    assert cloudflare.calls == 1 and minimax.calls == 0
    assert identity["dense_provider"] == GEMINI_PROVIDER
    assert identity["dense_dimension"] == GEMINI_DIMENSION
    assert identity["qdrant_collection"] == M26_GEMINI_COLLECTION
    assert '"vector":' not in json.dumps(identity)
    assert router.telemetry()["fallback_used"] is False
    _assert_single_request_path(events, generated=True)


def test_x3_gemini_hybrid_cloudflare_429_to_minimax_once() -> None:
    primary = _DenseChannel(provider="bge", failure=_status_error(429))
    secondary = _DenseChannel(provider="gemini")
    response, router, cloudflare, minimax, events = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=primary,
        secondary=secondary,
        cloudflare_failure="CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429",
    )
    identity = response["retrieval_backend_identity"]["dense"]
    telemetry = router.telemetry()
    assert response["status"] == "owner_only_cited_answer"
    assert response["retrieval_mode_summary"]["retrieval_mode"] == "hybrid_gemini"
    assert primary.calls == 1 and secondary.calls == 1
    assert cloudflare.calls == 1 and minimax.calls == 1
    assert router.calls == 2
    assert telemetry["fallback_used"] is True
    assert telemetry["closure_provider_final"] == MINIMAX_PROVIDER
    assert telemetry["fallback_evidence_digest_match"] is True
    assert [item["provider"] for item in telemetry["provider_attempts"]] == [
        CLOUDFLARE_PROVIDER,
        MINIMAX_PROVIDER,
    ]
    assert identity["dense_provider"] == GEMINI_PROVIDER
    assert MINIMAX_PROVIDER not in json.dumps(response["retrieval_backend_identity"])
    _assert_single_request_path(events, generated=True)


def test_x4_lexical_only_sufficient_evidence_reaches_cloudflare_generation() -> None:
    primary = _DenseChannel(provider="bge", failure=_status_error(503))
    secondary = _DenseChannel(provider="gemini", failure=_status_error(503))
    response, router, cloudflare, minimax, events = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=primary,
        secondary=secondary,
    )
    assert response["status"] == "owner_only_cited_answer"
    assert response["retrieval_mode_summary"]["retrieval_mode"] == "lexical_only"
    assert response["selected_evidence_count"] > 0
    assert cloudflare.calls == 1 and minimax.calls == 0
    assert router.telemetry()["fallback_used"] is False
    _assert_single_request_path(events, generated=True)


def test_x5_lexical_only_insufficient_evidence_abstains_without_generation() -> None:
    primary = _DenseChannel(provider="bge", failure=_status_error(503))
    secondary = _DenseChannel(provider="gemini", failure=_status_error(503))
    response, router, cloudflare, minimax, events = _run_integrated_request(
        question=UNSUPPORTED_QUESTION,
        primary=primary,
        secondary=secondary,
    )
    assert response["status"] == "owner_only_safe_abstention"
    assert response["terminal_status"] == "safe_abstention"
    assert response["retrieval_mode_summary"]["retrieval_mode"] == "lexical_only"
    assert response["selected_evidence_count"] == 0
    assert cloudflare.calls == 0 and minimax.calls == 0
    assert router.calls == 0
    _assert_single_request_path(events, generated=False)


def test_cross_layer_harness_has_no_question_id_or_golden_dispatch() -> None:
    source = inspect.getsource(runtime.run_owner_arbitrary_query).casefold()
    assert "question_id" not in source
    assert "golden" not in source
    assert not re.search(r"\b(?:f|r)\d{3}\b", source)
