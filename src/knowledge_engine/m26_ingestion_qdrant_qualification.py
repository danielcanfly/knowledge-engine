from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .errors import ConfigurationError, IntegrityError
from .m26_active_production_release import ActiveProductionRelease
from .m26_admin_contract import canonical_json_bytes
from .m26_ingestion_candidate_qdrant import CANDIDATE_PAYLOAD_INDEX_SCHEMA
from .m26_production_promotion import (
    REQUIRED_QDRANT_PAYLOAD_INDEXES,
    ProductionQdrantQualification,
    QdrantQualification,
)


@dataclass(frozen=True)
class QdrantQualificationConfig:
    url: str
    api_key: str
    timeout_seconds: float = 180.0
    page_size: int = 256

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ConfigurationError("Qdrant qualification URL must be an absolute HTTPS URL")
        if not self.api_key:
            raise ConfigurationError("Qdrant qualification credential is required")
        if not 1 <= self.page_size <= 1000:
            raise ConfigurationError("Qdrant qualification page size must be between 1 and 1000")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"QDRANT-QUALIFY {label} must be an object")
    return value


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    observed = value.get(key)
    if not isinstance(observed, str) or not observed:
        raise IntegrityError(f"QDRANT-QUALIFY {label} missing {key}")
    return observed


def _required_int(value: Mapping[str, Any], key: str, label: str) -> int:
    observed = value.get(key)
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
        raise IntegrityError(f"QDRANT-QUALIFY {label} has invalid {key}")
    return observed


def _hex64(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise IntegrityError(f"QDRANT-QUALIFY {label} must be lowercase sha256")
    return value


class QdrantReadOnlyQualificationObserver:
    """Full-census Qdrant qualification limited to read-only endpoints."""

    def __init__(
        self,
        config: QdrantQualificationConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.calls: list[tuple[str, str]] = []

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        allowed = (
            method == "GET"
            and body is None
            and (path == "/aliases" or path.startswith("/collections/"))
        ) or (
            method == "POST"
            and body is not None
            and (
                path.endswith("/points/count?consistency=all")
                or path.endswith("/points/scroll?consistency=all")
            )
        )
        if not allowed:
            raise IntegrityError(f"QDRANT-QUALIFY rejected non-read operation: {method} {path}")
        self.calls.append((method, path))
        owned = self._client is None
        client = self._client or httpx.Client(timeout=self.config.timeout_seconds)
        try:
            response = client.request(
                method,
                self.config.url.rstrip("/") + path,
                headers={"api-key": self.config.api_key, "Accept": "application/json"},
                json=dict(body) if body is not None else None,
            )
            response.raise_for_status()
            value = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrityError(f"QDRANT-QUALIFY read failed: {method} {path}") from exc
        finally:
            if owned:
                client.close()
        result = _mapping(value, "response")
        if result.get("status") != "ok":
            raise IntegrityError("QDRANT-QUALIFY response status is not ok")
        return result

    @staticmethod
    def _collection_path(collection: str) -> str:
        if not collection:
            raise IntegrityError("QDRANT-QUALIFY collection is required")
        return f"/collections/{quote(collection, safe='')}"

    def _snapshot(self, collection: str) -> dict[str, Any]:
        response = self._request("GET", self._collection_path(collection))
        raw = _mapping(response.get("result"), "collection result")
        config = _mapping(raw.get("config"), "collection config")
        params = _mapping(config.get("params"), "collection params")
        vectors = _mapping(params.get("vectors"), "collection vectors")
        default = _mapping(vectors.get("default"), "default vector")
        payload_schema = _mapping(raw.get("payload_schema"), "payload schema")
        observed_schema = {
            str(key): value.get("data_type")
            for key, value in payload_schema.items()
            if isinstance(value, Mapping)
        }
        payload_indexes = tuple(sorted(observed_schema))
        missing = sorted(REQUIRED_QDRANT_PAYLOAD_INDEXES - set(payload_indexes))
        if missing:
            raise IntegrityError(
                "QDRANT-QUALIFY required payload indexes missing: " + ",".join(missing)
            )
        wrong_types = sorted(
            field
            for field, expected in CANDIDATE_PAYLOAD_INDEX_SCHEMA.items()
            if observed_schema.get(field) != expected
        )
        if wrong_types:
            raise IntegrityError(
                "QDRANT-QUALIFY payload index type mismatch: " + ",".join(wrong_types)
            )
        size = _required_int(default, "size", "default vector")
        distance = _required_string(default, "distance", "default vector")
        if size <= 0 or distance.casefold() != "cosine":
            raise IntegrityError("QDRANT-QUALIFY vector configuration mismatch")
        status = _required_string(raw, "status", "collection")
        if status.casefold() != "green":
            raise IntegrityError("QDRANT-QUALIFY collection is not green")
        return {
            "status": status,
            "points_count": _required_int(raw, "points_count", "collection"),
            "vector_name": "default",
            "vector_dimension": size,
            "distance": distance,
            "payload_indexes": payload_indexes,
        }

    def _aliases(self, collection: str) -> tuple[str, ...]:
        response = self._request("GET", "/aliases")
        result = _mapping(response.get("result"), "aliases result")
        aliases = result.get("aliases")
        if not isinstance(aliases, list):
            raise IntegrityError("QDRANT-QUALIFY aliases must be a list")
        return tuple(
            sorted(
                _required_string(row, "alias_name", "alias")
                for raw in aliases
                if isinstance(raw, Mapping)
                and (row := _mapping(raw, "alias")).get("collection_name") == collection
            )
        )

    def _exact_count(
        self,
        collection: str,
        filter_value: Mapping[str, Any] | None = None,
    ) -> int:
        body: dict[str, Any] = {"exact": True}
        if filter_value is not None:
            body["filter"] = dict(filter_value)
        response = self._request(
            "POST",
            self._collection_path(collection) + "/points/count?consistency=all",
            body,
        )
        return _required_int(_mapping(response.get("result"), "count result"), "count", "count")

    def _inventory(self, collection: str) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        offset: Any = None
        observed_offsets: set[str] = set()
        path = self._collection_path(collection) + "/points/scroll?consistency=all"
        while True:
            body: dict[str, Any] = {
                "limit": self.config.page_size,
                "with_payload": True,
                "with_vector": ["default"],
            }
            if offset is not None:
                body["offset"] = offset
            response = self._request("POST", path, body)
            result = _mapping(response.get("result"), "scroll result")
            points = result.get("points")
            if not isinstance(points, list) or any(
                not isinstance(point, Mapping) for point in points
            ):
                raise IntegrityError("QDRANT-QUALIFY scroll points are invalid")
            rows.extend(points)
            offset = result.get("next_page_offset")
            if offset is None:
                return rows
            offset_identity = _digest(offset)
            if offset_identity in observed_offsets:
                raise IntegrityError("QDRANT-QUALIFY scroll pagination repeated an offset")
            observed_offsets.add(offset_identity)

    def _census(
        self,
        *,
        collection: str,
        release_id: str,
        source_commit_sha: str,
        admission_sha256: str,
        expected_count: int,
        candidate: bool,
    ) -> dict[str, Any]:
        snapshot = self._snapshot(collection)
        aliases = self._aliases(collection)
        exact_count = self._exact_count(collection)
        points = self._inventory(collection)
        identities: list[dict[str, Any]] = []
        vectors: list[dict[str, str]] = []
        expected_payload: dict[str, Any] = {
            "release_id": release_id,
            "source_commit_sha": source_commit_sha,
            "admission_sha256": admission_sha256,
        }
        expected_payload.update({"candidate_release_eligible": True, "production_authority": False})
        for point in points:
            payload = _mapping(point.get("payload"), "point payload")
            mismatches = [
                key for key, expected in expected_payload.items() if payload.get(key) != expected
            ]
            if mismatches:
                raise IntegrityError(
                    "QDRANT-QUALIFY point identity mismatch: " + ",".join(sorted(mismatches))
                )
            point_id = str(point.get("id") if point.get("id") is not None else "")
            section_id = _required_string(payload, "section_id", "point payload")
            if not point_id:
                raise IntegrityError("QDRANT-QUALIFY point id is missing")
            vector = point.get("vector")
            if isinstance(vector, Mapping):
                vector = vector.get("default")
            if (
                not isinstance(vector, list)
                or len(vector) != snapshot["vector_dimension"]
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in vector
                )
            ):
                raise IntegrityError("QDRANT-QUALIFY default vector content mismatch")
            identity = {
                "point_id": point_id,
                "section_id": section_id,
                "release_id": payload.get("release_id"),
                "source_commit_sha": payload.get("source_commit_sha"),
                "admission_sha256": payload.get("admission_sha256"),
                "candidate_release_eligible": payload.get("candidate_release_eligible"),
                "production_authority": payload.get("production_authority"),
                "text_sha256": _hex64(payload.get("text_sha256"), "payload text_sha256"),
                "embedding_input_sha256": _hex64(
                    payload.get("embedding_input_sha256"), "payload embedding_input_sha256"
                ),
                "embedding_provider": _required_string(
                    payload, "embedding_provider", "point payload"
                ),
                "embedding_model": _required_string(payload, "embedding_model", "point payload"),
                "vector_name": "default",
                "vector_dimension": len(vector),
            }
            identities.append(identity)
            vectors.append({"point_id": point_id, "vector_sha256": _digest(vector)})
        point_ids = [row["point_id"] for row in identities]
        section_ids = [row["section_id"] for row in identities]
        if (
            expected_count <= 0
            or snapshot["points_count"] != expected_count
            or exact_count != expected_count
            or len(points) != expected_count
            or len(set(point_ids)) != expected_count
            or len(set(section_ids)) != expected_count
        ):
            raise IntegrityError("QDRANT-QUALIFY full identity census mismatch")
        return {
            **snapshot,
            "aliases": aliases,
            "exact_count": exact_count,
            "full_identity_count": len(points),
            "point_ids_sha256": _digest(sorted(point_ids)),
            "section_ids_sha256": _digest(sorted(section_ids)),
            "aggregate_identity_sha256": _digest(
                sorted(identities, key=lambda row: row["point_id"])
            ),
            "vector_fingerprint_sha256": _digest(sorted(vectors, key=lambda row: row["point_id"])),
        }

    def qualify_candidate(self, manifest: Mapping[str, Any]) -> QdrantQualification:
        identities = _mapping(manifest.get("identities"), "candidate identities")
        counts = _mapping(manifest.get("counts"), "candidate counts")
        collection = _required_string(manifest, "qdrant_collection", "candidate manifest")
        release_id = _required_string(manifest, "release_id", "candidate manifest")
        expected_count = _required_int(counts, "semantic_documents", "candidate counts")
        census = self._census(
            collection=collection,
            release_id=release_id,
            source_commit_sha=_required_string(
                identities, "source_commit_sha", "candidate identities"
            ),
            admission_sha256=_required_string(
                identities, "admission_sha256", "candidate identities"
            ),
            expected_count=expected_count,
            candidate=True,
        )
        identity_filter = {
            "must": [
                {"key": "release_id", "match": {"value": release_id}},
                {
                    "key": "source_commit_sha",
                    "match": {"value": identities["source_commit_sha"]},
                },
                {
                    "key": "admission_sha256",
                    "match": {"value": identities["admission_sha256"]},
                },
                {"key": "candidate_release_eligible", "match": {"value": True}},
                {"key": "production_authority", "match": {"value": False}},
            ]
        }
        filtered = self._exact_count(collection, identity_filter)
        if filtered != expected_count or census["aliases"]:
            raise IntegrityError("QDRANT-QUALIFY candidate filter or alias isolation mismatch")
        return QdrantQualification(
            collection=collection,
            status=str(census["status"]),
            points_count=int(census["points_count"]),
            filtered_point_count=filtered,
            vector_name=str(census["vector_name"]),
            vector_dimension=int(census["vector_dimension"]),
            distance=str(census["distance"]),
            payload_indexes=tuple(census["payload_indexes"]),
            alias_count=len(census["aliases"]),
            point_ids_sha256=str(census["point_ids_sha256"]),
            section_ids_sha256=str(census["section_ids_sha256"]),
            aggregate_identity_sha256=str(census["aggregate_identity_sha256"]),
            vector_fingerprint_sha256=str(census["vector_fingerprint_sha256"]),
        )

    def qualify_production(self, active: ActiveProductionRelease) -> ProductionQdrantQualification:
        census = self._census(
            collection=active.qdrant_collection,
            release_id=active.release_id,
            source_commit_sha=active.source_commit_sha,
            admission_sha256=active.admission_sha256,
            expected_count=active.semantic_point_count,
            candidate=False,
        )
        return ProductionQdrantQualification(
            collection=active.qdrant_collection,
            status=str(census["status"]),
            points_count=int(census["points_count"]),
            full_identity_count=int(census["full_identity_count"]),
            vector_name=str(census["vector_name"]),
            vector_dimension=int(census["vector_dimension"]),
            distance=str(census["distance"]),
            aliases=tuple(census["aliases"]),
            point_ids_sha256=str(census["point_ids_sha256"]),
            section_ids_sha256=str(census["section_ids_sha256"]),
            aggregate_identity_sha256=str(census["aggregate_identity_sha256"]),
            vector_fingerprint_sha256=str(census["vector_fingerprint_sha256"]),
        )


__all__ = [
    "QdrantQualificationConfig",
    "QdrantReadOnlyQualificationObserver",
]
