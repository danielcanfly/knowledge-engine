from __future__ import annotations

from typing import Any

import httpx
import pytest

from knowledge_engine.m23_cloudflare_qdrant import (
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    CloudflareConfig,
)
from knowledge_engine.m26_ingestion_candidate_qdrant import (
    CandidateQdrantError,
    CloudflareQdrantCandidateMaterializer,
)
from knowledge_engine.m26_ingestion_candidate_writer import (
    candidate_qdrant_collection,
)


class QdrantState:
    def __init__(self) -> None:
        self.exists = False
        self.points: dict[str, dict[str, Any]] = {}
        self.release_override: str | None = None
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET" and "/collections/" in path:
            if not self.exists:
                return httpx.Response(404, json={"status": "missing"})
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "status": "green",
                        "points_count": len(self.points),
                        "indexed_vectors_count": len(self.points),
                        "config": {
                            "params": {
                                "vectors": {
                                    QDRANT_VECTOR_NAME: {
                                        "size": VECTOR_DIMENSION,
                                        "distance": QDRANT_DISTANCE,
                                    }
                                },
                                "sparse_vectors": None,
                            }
                        },
                    },
                },
            )
        if request.method == "PUT" and path.endswith("/points"):
            payload = __import__("json").loads(request.content)
            for point in payload["points"]:
                self.points[str(point["id"])] = point
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {"status": "completed", "operation_id": 1},
                },
            )
        if request.method == "PUT" and "/collections/" in path:
            self.exists = True
            return httpx.Response(200, json={"status": "ok", "result": True})
        if request.method == "POST" and path.endswith("/points"):
            payload = __import__("json").loads(request.content)
            result = []
            for point_id in payload["ids"]:
                point = self.points.get(str(point_id))
                if point is None:
                    continue
                row = {
                    "id": point["id"],
                    "payload": dict(point["payload"]),
                }
                if self.release_override is not None:
                    row["payload"]["release_id"] = self.release_override
                result.append(row)
            return httpx.Response(200, json={"status": "ok", "result": result})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


def _documents() -> tuple[dict[str, Any], ...]:
    return (
        {
            "section_id": "section-a",
            "text": "alpha",
            "payload": {"source_id": "source-1"},
        },
        {
            "section_id": "section-b",
            "text": "beta",
            "payload": {"source_id": "source-1"},
        },
    )


def _vectors(sections) -> list[list[float]]:
    vector = [1.0] + [0.0] * (VECTOR_DIMENSION - 1)
    return [list(vector) for _ in sections]


def _materializer(
    state: QdrantState,
    *,
    embedding_function=_vectors,
) -> CloudflareQdrantCandidateMaterializer:
    client = httpx.Client(
        transport=httpx.MockTransport(state.handler),
        base_url="https://qdrant.example",
    )
    return CloudflareQdrantCandidateMaterializer(
        cloudflare=CloudflareConfig(
            account_id="account",
            api_token="token",
        ),
        qdrant_base_url="https://qdrant.example",
        qdrant_api_key="qdrant-key",
        qdrant_client=client,
        embedding_function=embedding_function,
    )


def test_materializer_creates_candidate_collection_and_exact_readback() -> None:
    state = QdrantState()
    release_id = "m26blog-test-release-001"
    materializer = _materializer(state)

    result = materializer.materialize_and_verify(
        collection_name=candidate_qdrant_collection(release_id),
        release_id=release_id,
        semantic_documents=_documents(),
    )

    assert result.point_count == 2
    assert result.section_ids == ("section-a", "section-b")
    assert result.detail == {
        "collection_action": "created",
        "embedding_executed": True,
        "upsert_batches": 1,
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": QDRANT_VECTOR_NAME,
        "production_authority": False,
    }
    assert all(
        point["payload"]["candidate_release_eligible"] is True
        and point["payload"]["production_authority"] is False
        for point in state.points.values()
    )


def test_exact_replay_skips_embedding_and_reuses_verified_points() -> None:
    state = QdrantState()
    release_id = "m26blog-test-release-001"
    first = _materializer(state)
    first.materialize_and_verify(
        collection_name=candidate_qdrant_collection(release_id),
        release_id=release_id,
        semantic_documents=_documents(),
    )

    calls = 0

    def should_not_embed(_sections):
        nonlocal calls
        calls += 1
        raise AssertionError("embedding should not run for exact replay")

    second = _materializer(state, embedding_function=should_not_embed)
    result = second.materialize_and_verify(
        collection_name=candidate_qdrant_collection(release_id),
        release_id=release_id,
        semantic_documents=_documents(),
    )

    assert calls == 0
    assert result.detail["collection_action"] == "preexisting"
    assert result.detail["embedding_executed"] is False
    assert result.detail["upsert_batches"] == 0


def test_unexpected_preexisting_point_count_fails_before_embedding() -> None:
    state = QdrantState()
    state.exists = True
    state.points["foreign"] = {"id": "foreign", "payload": {}}
    release_id = "m26blog-test-release-001"
    calls = 0

    def should_not_embed(_sections):
        nonlocal calls
        calls += 1
        return _vectors(_sections)

    materializer = _materializer(state, embedding_function=should_not_embed)
    with pytest.raises(CandidateQdrantError, match="unexpected point count"):
        materializer.materialize_and_verify(
            collection_name=candidate_qdrant_collection(release_id),
            release_id=release_id,
            semantic_documents=_documents(),
        )

    assert calls == 0


def test_readback_release_drift_fails_closed() -> None:
    state = QdrantState()
    release_id = "m26blog-test-release-001"
    first = _materializer(state)
    first.materialize_and_verify(
        collection_name=candidate_qdrant_collection(release_id),
        release_id=release_id,
        semantic_documents=_documents(),
    )
    state.release_override = "m26blog-wrong-release"

    second = _materializer(state)
    with pytest.raises(CandidateQdrantError, match="release_id mismatch"):
        second.materialize_and_verify(
            collection_name=candidate_qdrant_collection(release_id),
            release_id=release_id,
            semantic_documents=_documents(),
        )


def test_non_release_scoped_collection_is_rejected_without_network() -> None:
    state = QdrantState()
    materializer = _materializer(state)

    with pytest.raises(CandidateQdrantError, match="release-scoped"):
        materializer.materialize_and_verify(
            collection_name="production",
            release_id="m26blog-test-release-001",
            semantic_documents=_documents(),
        )

    assert state.requests == []
