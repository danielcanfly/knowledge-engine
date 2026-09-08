from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine import m26_pa7_arbitrary_query_runtime as runtime
from knowledge_engine.m23_cloudflare_qdrant import CLOUDFLARE_MODEL
from knowledge_engine.m26_cloudflare_provider_router import (
    CLOUDFLARE_PROVIDER,
    MINIMAX_MODEL,
    CloudflareFallbackRequired,
    CloudflareRouterState,
    LiveGateError,
    ProviderRoutingClient,
    _cloudflare_fallback_eligible,
)
from knowledge_engine.m26_gemini_dense_fallback import (
    GEMINI_DIMENSION,
    GEMINI_MODEL,
    GEMINI_PROVIDER,
    M26_GEMINI_COLLECTION,
)
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle
from tests.test_m26_gemini_dense_fallback import _candidate_bundle, _status_error


class _Provider:
    def __init__(self, *, failure: str = "", text: str = '{"status":"answer"}') -> None:
        self.failure = failure
        self.text = text
        self.calls: list[tuple[dict[str, Any], str]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        if self.failure:
            raise CloudflareFallbackRequired(self.failure)
        return {"text": self.text, "usage": {}, "cost_usd": "0", "call_class": call_class}


def _payload() -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}]}


@pytest.mark.parametrize(
    ("failure", "eligible"),
    [
        ("CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429", True),
        ("CLOUDFLARE_HTTP_408", True),
        ("CLOUDFLARE_HTTP_503", True),
        ("CLOUDFLARE_TIMEOUT_OR_NETWORK_TRANSIENT", True),
        ("CLOUDFLARE_AUTH_OR_CONFIG", False),
        ("CLOUDFLARE_HTTP_403", False),
    ],
)
def test_d_generation_route_matrix(failure: str, eligible: bool) -> None:
    assert _cloudflare_fallback_eligible(failure) is eligible
    primary = _Provider(failure=failure)
    fallback = _Provider()
    router = ProviderRoutingClient(
        cloudflare=primary,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=_Provider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )
    if eligible:
        assert router.call(_payload(), "aq_fast_answer_synthesis")["text"]
        assert len(primary.calls) == 1
        assert len(fallback.calls) == 1
        assert router.telemetry()["provider_attempts"][-1]["model"] == MINIMAX_MODEL
    else:
        with pytest.raises(LiveGateError):
            router.call(_payload(), "aq_fast_answer_synthesis")
        assert len(primary.calls) == 1
        assert len(fallback.calls) == 0


class _Dense:
    def __init__(
        self, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        del question, bundle, top_k
        self.calls += 1
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result


def _bge_result() -> dict[str, Any]:
    return {
        "backend_identity": {
            "embedding_provider": CLOUDFLARE_PROVIDER,
            "embedding_model": CLOUDFLARE_MODEL,
            "vector_dimension": 1024,
        },
        "candidates": [{"section_id": "s", "score": 0.9}],
    }


def _gemini_result() -> dict[str, Any]:
    return {
        "backend_identity": {
            "dense_provider": GEMINI_PROVIDER,
            "dense_model": GEMINI_MODEL,
            "dense_dimension": GEMINI_DIMENSION,
            "qdrant_collection": M26_GEMINI_COLLECTION,
        },
        "candidates": [{"section_id": "s", "score": 0.8}],
    }


def test_g_retrieval_primary_success_has_no_secondary_attempt() -> None:
    primary = _Dense(_bge_result())
    secondary = _Dense(_gemini_result())
    _, dense = runtime._run_lexical_primary_retrieval(
        question="generic route question",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=secondary,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    assert primary.calls == 1 and secondary.calls == 0
    assert dense["backend_identity"]["retrieval_mode"] == "hybrid_bge"


def test_g_retrieval_transient_then_gemini_is_single_hop() -> None:
    primary = _Dense(error=_status_error(429))
    secondary = _Dense(_gemini_result())
    _, dense = runtime._run_lexical_primary_retrieval(
        question="generic route question",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=secondary,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    identity = dense["backend_identity"]
    assert primary.calls == 1 and secondary.calls == 1
    assert identity["retrieval_mode"] == "hybrid_gemini"
    assert identity["dense_provider"] == GEMINI_PROVIDER
    assert identity["dense_dimension"] == GEMINI_DIMENSION


def test_g_retrieval_secondary_transient_degrades_to_lexical_only() -> None:
    primary = _Dense(error=_status_error(503))
    secondary = _Dense(error=_status_error(503))
    _, dense = runtime._run_lexical_primary_retrieval(
        question="generic route question",
        bundle=_candidate_bundle(),
        dense_channel=primary,
        dense_fallback_channel=secondary,
        require_remote_dense=False,
        top_k=8,
        event_sink=None,
    )
    assert primary.calls == 1 and secondary.calls == 1
    assert dense["backend_identity"]["retrieval_mode"] == "lexical_only"


def test_x_boundary_keeps_generation_and_retrieval_identities_disjoint() -> None:
    assert CLOUDFLARE_PROVIDER != GEMINI_PROVIDER
    assert CLOUDFLARE_MODEL != GEMINI_MODEL
    assert GEMINI_DIMENSION != 1024
    assert M26_GEMINI_COLLECTION.endswith("gemini_e2_768")
    assert synthetic_full_production_answer_bundle().release_id != _candidate_bundle().release_id
