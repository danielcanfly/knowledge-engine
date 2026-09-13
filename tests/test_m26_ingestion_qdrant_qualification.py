from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m26_active_production_release import ActiveProductionRelease
from knowledge_engine.m26_ingestion_candidate_qdrant import CANDIDATE_PAYLOAD_INDEX_SCHEMA
from knowledge_engine.m26_ingestion_qdrant_qualification import (
    QdrantQualificationConfig,
    QdrantReadOnlyQualificationObserver,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _point(point_id: str, section_id: str, *, release_id: str, source: str, admission: str):
    return {
        "id": point_id,
        "payload": {
            "section_id": section_id,
            "release_id": release_id,
            "source_commit_sha": source,
            "admission_sha256": admission,
            "candidate_release_eligible": True,
            "production_authority": False,
            "text_sha256": _sha("text:" + section_id),
            "embedding_input_sha256": _sha("embedding:" + section_id),
            "embedding_provider": "cloudflare-workers-ai",
            "embedding_model": "@cf/baai/bge-m3",
        },
        "vector": {"default": [0.1, 0.2, 0.3]},
    }


class _QdrantTransport:
    def __init__(self, *, reverse: bool = False, wrong_type: bool = False) -> None:
        self.release_id = "release-qdrant-census"
        self.source = hashlib.sha1(b"source revision").hexdigest()
        self.admission = _sha("admission")
        self.reverse = reverse
        self.wrong_type = wrong_type
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode(),
                "body": body,
                "api_key": request.headers.get("api-key"),
            }
        )
        path = request.url.path
        if request.method == "GET" and path == "/aliases":
            return httpx.Response(200, json={"status": "ok", "result": {"aliases": []}})
        if request.method == "GET" and path.startswith("/collections/"):
            schema = dict(CANDIDATE_PAYLOAD_INDEX_SCHEMA)
            if self.wrong_type:
                schema["release_id"] = "integer"
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "status": "green",
                        "points_count": 2,
                        "config": {
                            "params": {"vectors": {"default": {"size": 3, "distance": "Cosine"}}}
                        },
                        "payload_schema": {
                            field: {"data_type": data_type} for field, data_type in schema.items()
                        },
                    },
                },
            )
        if request.method == "POST" and path.endswith("/points/count"):
            return httpx.Response(200, json={"status": "ok", "result": {"count": 2}})
        if request.method == "POST" and path.endswith("/points/scroll"):
            points = [
                _point(
                    "point-a",
                    "section-a",
                    release_id=self.release_id,
                    source=self.source,
                    admission=self.admission,
                ),
                _point(
                    "point-b",
                    "section-b",
                    release_id=self.release_id,
                    source=self.source,
                    admission=self.admission,
                ),
            ]
            if self.reverse:
                points.reverse()
            offset = body.get("offset") if isinstance(body, Mapping) else None
            index = 1 if offset == "page-2" else 0
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "result": {
                        "points": [points[index]],
                        "next_page_offset": "page-2" if index == 0 else None,
                    },
                },
            )
        return httpx.Response(405, json={"status": "error"})

    def manifest(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "qdrant_collection": "candidate/census name",
            "identities": {
                "source_commit_sha": self.source,
                "admission_sha256": self.admission,
            },
            "counts": {"semantic_documents": 2},
        }


def _observer(transport: _QdrantTransport) -> QdrantReadOnlyQualificationObserver:
    client = httpx.Client(transport=httpx.MockTransport(transport))
    return QdrantReadOnlyQualificationObserver(
        QdrantQualificationConfig(
            url="https://qdrant.example.test",
            api_key="read-only-secret",
            page_size=1,
        ),
        client=client,
    )


def test_candidate_full_census_is_paginated_read_only_and_order_independent() -> None:
    first_transport = _QdrantTransport()
    second_transport = _QdrantTransport(reverse=True)

    first = _observer(first_transport).qualify_candidate(first_transport.manifest())
    second = _observer(second_transport).qualify_candidate(second_transport.manifest())

    assert first == second
    assert first.points_count == first.filtered_point_count == 2
    assert first.alias_count == 0
    assert first.payload_indexes == tuple(sorted(CANDIDATE_PAYLOAD_INDEX_SCHEMA))
    assert all(row["method"] in {"GET", "POST"} for row in first_transport.requests)
    assert all("secret" not in json.dumps(row["body"]) for row in first_transport.requests)
    scrolls = [row for row in first_transport.requests if "/points/scroll" in row["path"]]
    assert len(scrolls) == 2
    assert all(row["body"]["with_payload"] is True for row in scrolls)
    assert all(row["body"]["with_vector"] == ["default"] for row in scrolls)


def test_production_census_uses_exact_pointer_resolved_identity() -> None:
    transport = _QdrantTransport()
    active = ActiveProductionRelease(
        release_id=transport.release_id,
        production_manifest_key=f"releases/{transport.release_id}/promotion/manifest.json",
        production_manifest_sha256=_sha("production manifest"),
        candidate_manifest_key=f"releases/{transport.release_id}/manifest.json",
        candidate_manifest_sha256=_sha("candidate manifest"),
        qdrant_collection="candidate/census name",
        source_commit_sha=transport.source,
        admission_sha256=transport.admission,
        semantic_point_count=2,
        pointer={},
        pointer_sha256=_sha("pointer"),
        production_manifest={},
        candidate_manifest={},
    )

    result = _observer(transport).qualify_production(active)

    assert result.collection == active.qdrant_collection
    assert result.full_identity_count == 2
    assert result.aliases == ()


def test_observer_rejects_wrong_index_type_and_non_read_operation() -> None:
    transport = _QdrantTransport(wrong_type=True)
    observer = _observer(transport)

    with pytest.raises(IntegrityError, match="payload index type mismatch"):
        observer.qualify_candidate(transport.manifest())
    with pytest.raises(IntegrityError, match="rejected non-read operation"):
        observer._request("PUT", "/collections/forbidden", {})
