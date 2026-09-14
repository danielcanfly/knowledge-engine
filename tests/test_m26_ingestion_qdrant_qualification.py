from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_cloudflare_qdrant import (
    VECTOR_DIMENSION,
    SectionInput,
    build_cloudflare_request,
    build_qdrant_points,
    normalize_text,
    validate_sections,
)
from knowledge_engine.m26_active_production_release import ActiveProductionRelease
from knowledge_engine.m26_ingestion_candidate_qdrant import (
    CANDIDATE_PAYLOAD_INDEX_SCHEMA,
    candidate_text_identities,
)
from knowledge_engine.m26_ingestion_qdrant_qualification import (
    QdrantQualificationConfig,
    QdrantReadOnlyQualificationObserver,
)
from knowledge_engine.m26_production_promotion import (
    LEGACY_M25_RAW_TEXT_WITH_DERIVED_NORMALIZED_EMBEDDING_V1,
    STRICT_V2,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _point(
    point_id: str,
    section_id: str,
    *,
    release_id: str,
    source: str,
    admission: str,
    embedding_input: bool = True,
    provider: str = "cloudflare-workers-ai",
    model: str = "@cf/baai/bge-m3",
):
    point = {
        "id": point_id,
        "payload": {
            "section_id": section_id,
            "release_id": release_id,
            "source_commit_sha": source,
            "admission_sha256": admission,
            "candidate_release_eligible": True,
            "production_authority": False,
            "text_sha256": _sha("text:" + section_id),
            "embedding_provider": provider,
            "embedding_model": model,
        },
        "vector": {"default": [0.1, 0.2, 0.3]},
    }
    if embedding_input:
        point["payload"]["embedding_input_sha256"] = _sha("embedding:" + section_id)
    return point


class _QdrantTransport:
    def __init__(
        self,
        *,
        reverse: bool = False,
        wrong_type: bool = False,
        identity_mode: str = "strict",
        provider: str = "cloudflare-workers-ai",
        model: str = "@cf/baai/bge-m3",
    ) -> None:
        self.release_id = "release-qdrant-census"
        self.source = hashlib.sha1(b"source revision").hexdigest()
        self.admission = _sha("admission")
        self.reverse = reverse
        self.wrong_type = wrong_type
        self.identity_mode = identity_mode
        self.provider = provider
        self.model = model
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
                    embedding_input=self.identity_mode == "strict",
                    provider=self.provider,
                    model=self.model,
                ),
                _point(
                    "point-b",
                    "section-b",
                    release_id=self.release_id,
                    source=self.source,
                    admission=self.admission,
                    embedding_input=self.identity_mode != "legacy",
                    provider=self.provider,
                    model=self.model,
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
    assert result.identity_profile == STRICT_V2
    assert result.derived_embedding_input_count == 0


def test_observer_rejects_wrong_index_type_and_non_read_operation() -> None:
    transport = _QdrantTransport(wrong_type=True)
    observer = _observer(transport)

    with pytest.raises(IntegrityError, match="payload index type mismatch"):
        observer.qualify_candidate(transport.manifest())
    with pytest.raises(IntegrityError, match="rejected non-read operation"):
        observer._request("PUT", "/collections/forbidden", {})


def test_exact_historical_writer_separates_raw_payload_from_normalized_embedding() -> None:
    raw = "  Legacy fullwidth text: Ａ  "
    section = SectionInput(section_id="legacy#1", text=raw, payload={})
    vector = [0.0] * (VECTOR_DIMENSION - 1) + [1.0]

    provider_input = build_cloudflare_request([section.text])["text"][0]
    legacy_payload = build_qdrant_points([section], [vector])[0]["payload"]
    raw_sha256, normalized_sha256 = candidate_text_identities(raw, {"text_sha256": _sha(raw)})

    assert provider_input == normalize_text(raw)
    assert legacy_payload["text_sha256"] == raw_sha256
    assert normalized_sha256 == _sha(provider_input)
    assert legacy_payload["text_sha256"] != normalized_sha256


def test_generic_m23_validated_path_hashes_normalized_embedding_input() -> None:
    raw = "  Generic M23 fullwidth: Ａ  "
    validated = validate_sections([{"section_id": "generic#1", "text": raw, "payload": {}}])[0]
    vector = [0.0] * (VECTOR_DIMENSION - 1) + [1.0]

    payload = build_qdrant_points([validated], [vector])[0]["payload"]

    assert validated.text == normalize_text(raw)
    assert payload["text_sha256"] == _sha(normalize_text(raw))


def test_unknown_all_missing_production_population_fails_closed() -> None:
    transport = _QdrantTransport(identity_mode="legacy")

    with pytest.raises(IntegrityError, match="legacy predecessor profile is not authorized"):
        _direct_census(transport, candidate=False)


def _direct_census(
    transport: _QdrantTransport,
    *,
    candidate: bool,
    legacy_source_identities: Mapping[str, tuple[str, str]] | None = None,
):
    return _observer(transport)._census(
        collection="candidate/census name",
        release_id=transport.release_id,
        source_commit_sha=transport.source,
        admission_sha256=transport.admission,
        expected_count=2,
        candidate=candidate,
        legacy_source_identities=legacy_source_identities,
    )


def test_legacy_profile_is_collection_wide_source_bound_and_domain_separated() -> None:
    legacy = _QdrantTransport(identity_mode="legacy")
    strict = _QdrantTransport()
    source = {
        "section-a": (_sha("text:section-a"), _sha("embedding:section-a")),
        "section-b": (_sha("text:section-b"), _sha("embedding:section-b")),
    }
    legacy_result = _direct_census(legacy, candidate=False, legacy_source_identities=source)
    strict_result = _direct_census(strict, candidate=False)

    assert legacy_result["identity_profile"] == (
        LEGACY_M25_RAW_TEXT_WITH_DERIVED_NORMALIZED_EMBEDDING_V1
    )
    assert legacy_result["derived_embedding_input_count"] == 2
    assert strict_result["identity_profile"] == STRICT_V2
    assert legacy_result["aggregate_identity_sha256"] != strict_result["aggregate_identity_sha256"]


def test_candidate_missing_embedding_input_cannot_enter_legacy_profile() -> None:
    transport = _QdrantTransport(identity_mode="legacy")
    with pytest.raises(IntegrityError, match="candidate requires STRICT_V2"):
        _direct_census(
            transport,
            candidate=True,
            legacy_source_identities={
                "section-a": (_sha("text:section-a"), _sha("embedding:section-a")),
                "section-b": (_sha("text:section-b"), _sha("embedding:section-b")),
            },
        )


def test_mixed_strict_legacy_population_fails_closed() -> None:
    transport = _QdrantTransport(identity_mode="mixed")
    with pytest.raises(IntegrityError, match="mixed strict/legacy"):
        _direct_census(transport, candidate=False, legacy_source_identities={})


@pytest.mark.parametrize(
    ("provider", "model"),
    [("wrong-provider", "@cf/baai/bge-m3"), ("cloudflare-workers-ai", "wrong-model")],
)
def test_census_requires_exact_embedding_provider_and_model(provider: str, model: str) -> None:
    transport = _QdrantTransport(provider=provider, model=model)
    with pytest.raises(IntegrityError, match="provider/model mismatch"):
        _direct_census(transport, candidate=False)


def test_legacy_profile_requires_exact_source_text_digest() -> None:
    transport = _QdrantTransport(identity_mode="legacy")
    with pytest.raises(IntegrityError, match="payload/source text identity mismatch"):
        _direct_census(
            transport,
            candidate=False,
            legacy_source_identities={
                "section-a": ("f" * 64, _sha("embedding:section-a")),
                "section-b": (_sha("text:section-b"), _sha("embedding:section-b")),
            },
        )
