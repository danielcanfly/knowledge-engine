from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from .errors import IntegrityError
from .m23_cloudflare_qdrant import (
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    CloudflareConfig,
    SectionInput,
    build_qdrant_points,
    deterministic_point_id,
    embed_sections,
    validate_qdrant_collection_response,
    validate_sections,
)
from .m26_ingestion_candidate_writer import (
    CandidateVectorVerification,
    candidate_qdrant_collection,
)

UPSERT_BATCH_SIZE = 96
READBACK_BATCH_SIZE = 128


class CandidateQdrantError(IntegrityError):
    """Fail-closed error while materializing a candidate-only vector index."""


EmbeddingFunction = Callable[
    [Sequence[SectionInput]],
    Sequence[Sequence[float]],
]


class CloudflareQdrantCandidateMaterializer:
    def __init__(
        self,
        *,
        cloudflare: CloudflareConfig,
        qdrant_base_url: str,
        qdrant_api_key: str,
        qdrant_client: httpx.Client | None = None,
        embedding_function: EmbeddingFunction | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.cloudflare = cloudflare
        self.qdrant_base_url = qdrant_base_url.rstrip("/")
        self.qdrant_api_key = qdrant_api_key
        self.qdrant_client = qdrant_client
        self.embedding_function = embedding_function
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        if not self.qdrant_base_url.startswith("https://"):
            raise CandidateQdrantError("Qdrant base URL must use https")
        if not self.qdrant_api_key.strip():
            raise CandidateQdrantError("Qdrant API key is required")
        return {
            "api-key": self.qdrant_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _collection_path(collection_name: str) -> str:
        return f"/collections/{quote(collection_name, safe='')}"

    def _client(self) -> tuple[httpx.Client, bool]:
        if self.qdrant_client is not None:
            return self.qdrant_client, False
        return httpx.Client(timeout=self.timeout_seconds), True

    def _snapshot(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
    ) -> dict[str, Any] | None:
        response = client.get(
            self.qdrant_base_url + self._collection_path(collection_name),
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise CandidateQdrantError("Qdrant collection response must be an object")
        return validate_qdrant_collection_response(payload)

    def _ensure_collection(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
    ) -> tuple[str, dict[str, Any]]:
        before = self._snapshot(client, collection_name=collection_name)
        if before is not None:
            return "preexisting", before
        response = client.put(
            self.qdrant_base_url + self._collection_path(collection_name),
            headers=self._headers(),
            json={
                "vectors": {
                    QDRANT_VECTOR_NAME: {
                        "size": VECTOR_DIMENSION,
                        "distance": QDRANT_DISTANCE,
                    }
                }
            },
        )
        response.raise_for_status()
        after = self._snapshot(client, collection_name=collection_name)
        if after is None:
            raise CandidateQdrantError("Qdrant collection missing after create")
        return "created", after

    def _embed(
        self,
        sections: Sequence[SectionInput],
    ) -> Sequence[Sequence[float]]:
        if self.embedding_function is not None:
            return self.embedding_function(sections)
        return embed_sections(sections, self.cloudflare)

    def _upsert(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
        points: Sequence[Mapping[str, Any]],
    ) -> int:
        path = (
            self.qdrant_base_url
            + self._collection_path(collection_name)
            + "/points"
        )
        batches = 0
        for start in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = list(points[start : start + UPSERT_BATCH_SIZE])
            response = client.put(
                path,
                params={"wait": "true", "ordering": "strong"},
                headers=self._headers(),
                json={"points": batch},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping) or payload.get("status") != "ok":
                raise CandidateQdrantError(
                    "Qdrant candidate upsert was not acknowledged"
                )
            result = payload.get("result")
            if not isinstance(result, Mapping) or result.get("status") not in {
                "completed",
                "acknowledged",
            }:
                raise CandidateQdrantError(
                    "Qdrant candidate upsert did not complete"
                )
            batches += 1
        return batches

    def _readback(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
        release_id: str,
        section_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        path = (
            self.qdrant_base_url
            + self._collection_path(collection_name)
            + "/points"
        )
        point_ids = [deterministic_point_id(section_id) for section_id in section_ids]
        returned: list[Mapping[str, Any]] = []
        for start in range(0, len(point_ids), READBACK_BATCH_SIZE):
            response = client.post(
                path,
                params={"consistency": "all"},
                headers=self._headers(),
                json={
                    "ids": point_ids[start : start + READBACK_BATCH_SIZE],
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") if isinstance(payload, Mapping) else None
            if not isinstance(result, list):
                raise CandidateQdrantError(
                    "Qdrant candidate readback did not return a point list"
                )
            returned.extend(
                point for point in result if isinstance(point, Mapping)
            )
        if len(returned) != len(point_ids):
            raise CandidateQdrantError("Qdrant candidate readback count mismatch")

        by_id = {str(point.get("id")): point for point in returned}
        if set(by_id) != set(point_ids):
            raise CandidateQdrantError("Qdrant candidate readback point IDs mismatch")

        observed_sections: list[str] = []
        for point_id in point_ids:
            payload = by_id[point_id].get("payload")
            if not isinstance(payload, Mapping):
                raise CandidateQdrantError(
                    "Qdrant candidate readback payload is missing"
                )
            section_id = payload.get("section_id")
            if not isinstance(section_id, str) or not section_id:
                raise CandidateQdrantError(
                    "Qdrant candidate payload section_id is missing"
                )
            if payload.get("release_id") != release_id:
                raise CandidateQdrantError(
                    "Qdrant candidate payload release_id mismatch"
                )
            if payload.get("candidate_release_eligible") is not True:
                raise CandidateQdrantError(
                    "Qdrant candidate eligibility marker is missing"
                )
            if payload.get("production_authority") is not False:
                raise CandidateQdrantError(
                    "Qdrant candidate payload gained production authority"
                )
            observed_sections.append(section_id)
        return tuple(sorted(observed_sections))

    def materialize_and_verify(
        self,
        *,
        collection_name: str,
        release_id: str,
        semantic_documents: Sequence[Mapping[str, Any]],
    ) -> CandidateVectorVerification:
        if collection_name != candidate_qdrant_collection(release_id):
            raise CandidateQdrantError(
                "Qdrant collection is not the release-scoped candidate namespace"
            )
        raw_sections: list[dict[str, Any]] = []
        for document in semantic_documents:
            payload = document.get("payload")
            if not isinstance(payload, Mapping):
                payload = {}
            raw_sections.append(
                {
                    "section_id": document.get("section_id"),
                    "text": document.get("text"),
                    "payload": {
                        **dict(payload),
                        "release_id": release_id,
                        "candidate_release_eligible": True,
                        "production_authority": False,
                        "canonical_knowledge": False,
                    },
                }
            )
        sections = validate_sections(raw_sections)
        expected_ids = tuple(sorted(section.section_id for section in sections))
        client, owned = self._client()
        try:
            collection_action, snapshot = self._ensure_collection(
                client,
                collection_name=collection_name,
            )
            points_before = snapshot.get("points_count")
            if points_before not in {0, len(sections)}:
                raise CandidateQdrantError(
                    "candidate collection has an unexpected point count"
                )

            upsert_batches = 0
            embedding_executed = False
            if points_before == 0:
                vectors = self._embed(sections)
                points = build_qdrant_points(sections, vectors)
                for point in points:
                    payload = point["payload"]
                    payload["release_id"] = release_id
                    payload["candidate_release_eligible"] = True
                    payload["production_authority"] = False
                    payload["canonical_knowledge"] = False
                upsert_batches = self._upsert(
                    client,
                    collection_name=collection_name,
                    points=points,
                )
                embedding_executed = True

            observed_ids = self._readback(
                client,
                collection_name=collection_name,
                release_id=release_id,
                section_ids=expected_ids,
            )
            final = self._snapshot(client, collection_name=collection_name)
            if final is None or final.get("points_count") != len(sections):
                raise CandidateQdrantError(
                    "candidate collection final point count mismatch"
                )
            return CandidateVectorVerification(
                collection_name=collection_name,
                release_id=release_id,
                point_count=len(observed_ids),
                section_ids=observed_ids,
                detail={
                    "collection_action": collection_action,
                    "embedding_executed": embedding_executed,
                    "upsert_batches": upsert_batches,
                    "vector_dimension": VECTOR_DIMENSION,
                    "vector_name": QDRANT_VECTOR_NAME,
                    "production_authority": False,
                },
            )
        finally:
            if owned:
                client.close()


__all__ = [
    "CandidateQdrantError",
    "CloudflareQdrantCandidateMaterializer",
    "READBACK_BATCH_SIZE",
    "UPSERT_BATCH_SIZE",
]
