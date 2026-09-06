from __future__ import annotations

import httpx

from tests.test_m26_int2_r1_cross_layer_route_matrix import (
    ANSWERABLE_QUESTION,
    _DenseChannel,
    _run_integrated_request,
)


def test_bge_and_gemini_share_provider_neutral_downstream_contract() -> None:
    bge, *_ = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=_DenseChannel(provider="bge"),
        secondary=None,
    )
    request = httpx.Request("POST", "https://dense.invalid/search")
    unavailable = httpx.HTTPStatusError(
        "dense unavailable", request=request, response=httpx.Response(429, request=request)
    )
    gemini, *_ = _run_integrated_request(
        question=ANSWERABLE_QUESTION,
        primary=_DenseChannel(provider="bge", failure=unavailable),
        secondary=_DenseChannel(provider="gemini"),
    )

    assert bge["retrieval_mode_summary"]["retrieval_mode"] == "hybrid_bge"
    assert gemini["retrieval_mode_summary"]["retrieval_mode"] == "hybrid_gemini"
    assert bge["canonical_runtime"] == gemini["canonical_runtime"]
    assert bge["semantic_closure"]["requirements"] == gemini["semantic_closure"]["requirements"]
    assert bge["status"] == gemini["status"]
    assert bge["terminal_status"] == gemini["terminal_status"]
