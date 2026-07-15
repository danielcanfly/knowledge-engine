from __future__ import annotations

import math

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_candidate_semantic_runtime import (
    QUERY_SCHEMA,
    RELEASE_ID,
    RELEASE_MANIFEST_SHA256,
    VECTOR_DIMENSION,
    shape_response,
    shape_shadow_response,
    validate_embedding,
    validate_request,
)


def request(**extra: object) -> dict[str, object]:
    return {"schema_version": QUERY_SCHEMA, "query": "decision quality", "top_k": 3, **extra}


def point(point_id: str, score: float, *, authority: bool = False) -> dict[str, object]:
    return {
        "id": point_id,
        "score": score,
        "payload": {
            "section_id": f"section:{point_id}",
            "article_id": "article:one",
            "document_id": "document:one",
            "concept_id": "concept:one",
            "source_path": "proposals/m23-4/one.md",
            "source_sha256": "a" * 64,
            "text_sha256": "b" * 64,
            "audience": "internal",
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": RELEASE_ID,
            "release_manifest_sha256": RELEASE_MANIFEST_SHA256,
            "graph_node_id": "concept:one",
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": "@cf/baai/bge-m3",
            "vector_dimension": 1024,
            "vector_name": "default",
            "canonical_knowledge": authority,
            "candidate_release_eligible": False,
            "production_authority": False,
        },
    }


def test_request_is_bounded_and_deterministic() -> None:
    first = validate_request(request())
    second = validate_request(request())
    assert first == second
    assert first["request_id"].startswith("m23qry-")
    with pytest.raises(IntegrityError, match="top_k"):
        validate_request(request(top_k=21))
    with pytest.raises(IntegrityError, match="query length"):
        validate_request(request(query="x" * 2001))


def test_embedding_is_normalized_and_rejects_bad_vectors() -> None:
    vector = [0.0] * VECTOR_DIMENSION
    vector[0] = 3.0
    vector[1] = 4.0
    normalized = validate_embedding(vector)
    assert math.isclose(sum(value * value for value in normalized), 1.0)
    with pytest.raises(IntegrityError, match="dimension"):
        validate_embedding([1.0])
    bad = [0.0] * VECTOR_DIMENSION
    bad[0] = float("nan")
    with pytest.raises(IntegrityError, match="non-finite"):
        validate_embedding(bad)


def test_response_is_sorted_fingerprinted_and_fail_closed() -> None:
    raw = [point("b", 0.7), point("a", 0.9), point("c", 0.7)]
    first = shape_response(request(), raw)
    second = shape_response(request(), list(reversed(raw)))
    assert first == second
    assert [item["point_id"] for item in first["results"]] == ["a", "b", "c"]
    assert first["authority"]["lexical_production_authority_unchanged"] is True
    assert first["authority"]["semantic_output_production_authority"] is False
    assert len(first["response_sha256"]) == 64


def test_response_rejects_authority_score_and_duplicate_drift() -> None:
    with pytest.raises(IntegrityError, match="authority"):
        shape_response(request(), [point("a", 0.9, authority=True)])
    with pytest.raises(IntegrityError, match="cosine"):
        shape_response(request(), [point("a", 2.0)])
    with pytest.raises(IntegrityError, match="duplicate"):
        shape_response(request(), [point("a", 0.9), point("a", 0.8)])


def test_shadow_keeps_lexical_authoritative_and_computes_rank_deltas() -> None:
    raw = [point("b", 0.9), point("a", 0.8), point("c", 0.7)]
    shadow = shape_shadow_response(request(lexical_point_ids=["a", "x", "b"]), raw)
    assert shadow["lexical_point_ids"] == ["a", "x", "b"]
    assert shadow["semantic_point_ids"] == ["b", "a", "c"]
    assert shadow["overlap_count"] == 2
    assert shadow["authority"]["lexical_output_authoritative"] is True
    assert shadow["authority"]["semantic_output_served_to_production"] is False
    assert shadow["rank_diagnostics"] == [
        {"point_id": "a", "lexical_rank": 1, "semantic_rank": 2, "rank_delta": 1},
        {"point_id": "b", "lexical_rank": 3, "semantic_rank": 1, "rank_delta": -2},
    ]


def test_shadow_rejects_duplicate_or_oversize_lexical_ids() -> None:
    with pytest.raises(IntegrityError, match="unique"):
        validate_request(request(lexical_point_ids=["a", "a"]), shadow=True)
    with pytest.raises(IntegrityError, match="bounded"):
        validate_request(request(lexical_point_ids=[str(i) for i in range(21)]), shadow=True)
