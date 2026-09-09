from __future__ import annotations

import hashlib
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
    normalize_text,
    validate_qdrant_collection_response,
    validate_sections,
)
from .m26_ingestion_candidate_writer import (
    CandidateVectorVerification,
    candidate_qdrant_collection,
)

UPSERT_BATCH_SIZE = 96
READBACK_BATCH_SIZE = 128
CANDIDATE_PAYLOAD_INDEX_SCHEMA = {
    "release_id": "keyword",
    "source_commit_sha": "keyword",
    "admission_sha256": "keyword",
    "candidate_release_eligible": "bool",
    "production_authority": "bool",
}


class CandidateQdrantError(IntegrityError):
    """Fail-closed error while materializing a candidate-only vector index."""


EmbeddingFunction = Callable[
    [Sequence[SectionInput]],
    Sequence[Sequence[float]],
]


def candidate_text_identities(text: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    raw_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    declared = payload.get("text_sha256")
    if declared != raw_sha256:
        raise CandidateQdrantError("semantic payload text_sha256 does not match raw text bytes")
    normalized = normalize_text(text)
    return raw_sha256, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        snapshot = validate_qdrant_collection_response(payload)
        result = payload.get("result")
        raw_schema = result.get("payload_schema") if isinstance(result, Mapping) else None
        if raw_schema is None:
            raw_schema = {}
        if not isinstance(raw_schema, Mapping):
            raise CandidateQdrantError("Qdrant payload schema must be an object")
        snapshot["payload_schema"] = {
            str(field): value.get("data_type")
            for field, value in raw_schema.items()
            if isinstance(value, Mapping)
        }
        return snapshot

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

    def _ensure_payload_indexes(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
        snapshot: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        observed = snapshot.get("payload_schema")
        if not isinstance(observed, Mapping):
            raise CandidateQdrantError("Qdrant candidate payload schema is missing")
        wrong = {
            field: {"expected": expected, "observed": observed.get(field)}
            for field, expected in CANDIDATE_PAYLOAD_INDEX_SCHEMA.items()
            if field in observed and observed.get(field) != expected
        }
        if wrong:
            raise CandidateQdrantError(f"Qdrant candidate payload index type mismatch: {wrong}")
        created: list[str] = []
        for field, schema in CANDIDATE_PAYLOAD_INDEX_SCHEMA.items():
            if field in observed:
                continue
            response = client.put(
                self.qdrant_base_url + self._collection_path(collection_name) + "/index",
                params={"wait": "true"},
                headers=self._headers(),
                json={"field_name": field, "field_schema": schema},
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result") if isinstance(payload, Mapping) else None
            if (
                not isinstance(payload, Mapping)
                or payload.get("status") != "ok"
                or not isinstance(result, Mapping)
                or result.get("status") not in {"completed", "acknowledged"}
            ):
                raise CandidateQdrantError(f"Qdrant payload index creation failed: {field}")
            created.append(field)
        after = self._snapshot(client, collection_name=collection_name)
        if after is None:
            raise CandidateQdrantError("Qdrant collection missing after payload index creation")
        after_schema = after.get("payload_schema")
        if not isinstance(after_schema, Mapping) or any(
            after_schema.get(field) != schema
            for field, schema in CANDIDATE_PAYLOAD_INDEX_SCHEMA.items()
        ):
            raise CandidateQdrantError("Qdrant required payload indexes failed verification")
        return tuple(created), after

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
        path = self.qdrant_base_url + self._collection_path(collection_name) + "/points"
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
                raise CandidateQdrantError("Qdrant candidate upsert was not acknowledged")
            result = payload.get("result")
            if not isinstance(result, Mapping) or result.get("status") not in {
                "completed",
                "acknowledged",
            }:
                raise CandidateQdrantError("Qdrant candidate upsert did not complete")
            batches += 1
        return batches

    def _readback(
        self,
        client: httpx.Client,
        *,
        collection_name: str,
        release_id: str,
        section_ids: tuple[str, ...],
        text_identities: Mapping[str, tuple[str, str]],
    ) -> tuple[str, ...]:
        path = self.qdrant_base_url + self._collection_path(collection_name) + "/points"
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
                raise CandidateQdrantError("Qdrant candidate readback did not return a point list")
            returned.extend(point for point in result if isinstance(point, Mapping))
        if len(returned) != len(point_ids):
            raise CandidateQdrantError("Qdrant candidate readback count mismatch")

        by_id = {str(point.get("id")): point for point in returned}
        if set(by_id) != set(point_ids):
            raise CandidateQdrantError("Qdrant candidate readback point IDs mismatch")

        observed_sections: list[str] = []
        for point_id in point_ids:
            payload = by_id[point_id].get("payload")
            if not isinstance(payload, Mapping):
                raise CandidateQdrantError("Qdrant candidate readback payload is missing")
            section_id = payload.get("section_id")
            if not isinstance(section_id, str) or not section_id:
                raise CandidateQdrantError("Qdrant candidate payload section_id is missing")
            if payload.get("release_id") != release_id:
                raise CandidateQdrantError("Qdrant candidate payload release_id mismatch")
            if payload.get("candidate_release_eligible") is not True:
                raise CandidateQdrantError("Qdrant candidate eligibility marker is missing")
            if payload.get("production_authority") is not False:
                raise CandidateQdrantError("Qdrant candidate payload gained production authority")
            raw_text_sha256, embedding_input_sha256 = text_identities[section_id]
            if payload.get("text_sha256") != raw_text_sha256:
                raise CandidateQdrantError("Qdrant candidate raw text identity mismatch")
            if payload.get("embedding_input_sha256") != embedding_input_sha256:
                raise CandidateQdrantError("Qdrant candidate embedding input identity mismatch")
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
                raise CandidateQdrantError("semantic payload is missing")
            text = document.get("text")
            if not isinstance(text, str):
                raise CandidateQdrantError("semantic text is missing")
            raw_text_sha256, embedding_input_sha256 = candidate_text_identities(text, payload)
            raw_sections.append(
                {
                    "section_id": document.get("section_id"),
                    "text": text,
                    "payload": {
                        **dict(payload),
                        "text_sha256": raw_text_sha256,
                        "embedding_input_sha256": embedding_input_sha256,
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
            index_writes, snapshot = self._ensure_payload_indexes(
                client,
                collection_name=collection_name,
                snapshot=snapshot,
            )
            points_before = snapshot.get("points_count")
            if points_before not in {0, len(sections)}:
                raise CandidateQdrantError("candidate collection has an unexpected point count")

            upsert_batches = 0
            embedding_executed = False
            if points_before == 0:
                vectors = self._embed(sections)
                points = build_qdrant_points(sections, vectors)
                for section, point in zip(sections, points, strict=True):
                    payload = point["payload"]
                    payload["text_sha256"] = section.payload["text_sha256"]
                    payload["embedding_input_sha256"] = section.payload["embedding_input_sha256"]
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
                text_identities={
                    section.section_id: (
                        str(section.payload["text_sha256"]),
                        str(section.payload["embedding_input_sha256"]),
                    )
                    for section in sections
                },
            )
            final = self._snapshot(client, collection_name=collection_name)
            if final is None or final.get("points_count") != len(sections):
                raise CandidateQdrantError("candidate collection final point count mismatch")
            return CandidateVectorVerification(
                collection_name=collection_name,
                release_id=release_id,
                point_count=len(observed_ids),
                section_ids=observed_ids,
                detail={
                    "collection_action": collection_action,
                    "payload_index_writes": len(index_writes),
                    "payload_indexes": dict(CANDIDATE_PAYLOAD_INDEX_SCHEMA),
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
    "CANDIDATE_PAYLOAD_INDEX_SCHEMA",
    "CandidateQdrantError",
    "CloudflareQdrantCandidateMaterializer",
    "READBACK_BATCH_SIZE",
    "UPSERT_BATCH_SIZE",
    "candidate_text_identities",
]
