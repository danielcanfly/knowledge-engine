from __future__ import annotations

import json

import httpx
import pytest

from knowledge_engine.m26_active_production_release import ActiveProductionRelease
from knowledge_engine.m26_active_release_dense import (
    ActiveReleaseDenseConfig,
    ActiveReleaseQdrantDenseChannel,
    active_release_dense_channel_from_env,
)
from knowledge_engine.m26_pa7_arbitrary_query_runtime import (
    LocalDenseProjectionChannel,
    PA7ArbitraryQueryError,
)
from knowledge_engine.m26_production_answer_bundle import ProductionAnswerBundle


def _bundle(
    *,
    release_id: str = "m26-successor-release",
    collection: str = "m26_blog_m26_successor_release",
    source_commit_sha: str = "a" * 40,
    admission_sha256: str = "b" * 64,
    semantic_point_count: int = 2,
) -> ProductionAnswerBundle:
    candidate_manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
    }
    active = ActiveProductionRelease(
        release_id=release_id,
        production_manifest_key=f"releases/{release_id}/promotion/production.json",
        production_manifest_sha256="c" * 64,
        candidate_manifest_key=f"releases/{release_id}/manifest.json",
        candidate_manifest_sha256="d" * 64,
        qdrant_collection=collection,
        source_commit_sha=source_commit_sha,
        admission_sha256=admission_sha256,
        semantic_point_count=semantic_point_count,
        pointer={"release_id": release_id},
        pointer_sha256="e" * 64,
        production_manifest={"release_id": release_id},
        candidate_manifest=candidate_manifest,
    )
    return ProductionAnswerBundle(
        manifest=candidate_manifest,
        graph={},
        graph_v2={},
        lexical_index={},
        provenance={},
        manifest_sha256=active.candidate_manifest_sha256,
        artifact_sha256={},
        artifact_keys={},
        loaded_at="2026-09-07T08:00:00Z",
        semantic_inputs={
            "documents": [
                {"section_id": "section-a", "text": "alpha"},
                {"section_id": "section-b", "text": "beta"},
            ]
        },
        resolved_release=active,
    )


class QdrantSearchState:
    def __init__(self, bundle: ProductionAnswerBundle) -> None:
        self.bundle = bundle
        self.requests: list[httpx.Request] = []
        self.payload_release_override: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        active = self.bundle.active_release
        release_id = self.payload_release_override or active.release_id
        assert request.method == "POST"
        assert request.url.path == (
            f"/collections/{active.qdrant_collection}/points/search"
        )
        assert body["filter"]["must"][0] == {
            "key": "release_id",
            "match": {"value": active.release_id},
        }
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": "point-a",
                        "score": 0.91,
                        "payload": {
                            "concept_id": "concept-a",
                            "section_id": "section-a",
                            "source_id": "source-a",
                            "release_id": release_id,
                            "source_commit_sha": active.source_commit_sha,
                            "admission_sha256": active.admission_sha256,
                            "candidate_release_eligible": True,
                            "production_authority": False,
                            "text_sha256": "f" * 64,
                        },
                    }
                ]
            },
        )


def _vectors(_sections) -> list[list[float]]:
    return [[1.0, 0.0]]


def _channel(
    bundle: ProductionAnswerBundle,
    state: QdrantSearchState,
) -> ActiveReleaseQdrantDenseChannel:
    client = httpx.Client(
        transport=httpx.MockTransport(state.handler),
        base_url="https://qdrant.example",
    )
    return ActiveReleaseQdrantDenseChannel(
        ActiveReleaseDenseConfig(
            cloudflare_account_id="account",
            cloudflare_api_token="token",
            qdrant_url="https://qdrant.example",
            qdrant_api_key="read-key",
        ),
        qdrant_client=client,
        embedding_function=_vectors,
    )


def test_successor_pointer_drives_collection_and_identity_filter() -> None:
    bundle = _bundle(
        release_id="m26-successor-release-20260907",
        collection="m26_blog_successor_20260907",
    )
    state = QdrantSearchState(bundle)
    channel = _channel(bundle, state)

    result = channel.search(question="successor question", bundle=bundle, top_k=8)

    assert len(result["candidates"]) == 1
    backend = result["backend_identity"]
    assert backend["qdrant_collection"] == "m26_blog_successor_20260907"
    assert backend["release_id"] == "m26-successor-release-20260907"
    assert backend["authority_source"] == "resolved_production_pointer_chain"
    assert backend["read_only"] is True
    assert len(state.requests) == 1


def test_historical_payload_release_is_rejected() -> None:
    bundle = _bundle()
    state = QdrantSearchState(bundle)
    state.payload_release_override = "m25-historical-release"
    channel = _channel(bundle, state)

    with pytest.raises(
        PA7ArbitraryQueryError,
        match="PA7_ACTIVE_RELEASE_QDRANT_PAYLOAD_MISMATCH",
    ):
        channel.search(question="query", bundle=bundle, top_k=8)


def test_semantic_point_count_mismatch_fails_before_network() -> None:
    bundle = _bundle(semantic_point_count=3)
    state = QdrantSearchState(bundle)
    channel = _channel(bundle, state)

    with pytest.raises(
        PA7ArbitraryQueryError,
        match="PA7_ACTIVE_RELEASE_SEMANTIC_COUNT_MISMATCH",
    ):
        channel.search(question="query", bundle=bundle, top_k=8)

    assert state.requests == []


def test_collection_environment_cannot_override_active_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "token")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "read-key")
    monkeypatch.setenv("QDRANT_COLLECTION", "historical-frozen-collection")
    monkeypatch.setenv("M26_PA7_DENSE_COLLECTION", "attacker-selected-collection")

    channel = active_release_dense_channel_from_env(require_remote=True)

    assert isinstance(channel, ActiveReleaseQdrantDenseChannel)
    assert not hasattr(channel.config, "qdrant_collection")


def test_partial_remote_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "QDRANT_URL",
        "QDRANT_API_KEY_READ",
        "QDRANT_READ_ONLY_API_KEY",
        "QDRANT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")

    with pytest.raises(
        PA7ArbitraryQueryError,
        match="PA7_ACTIVE_RELEASE_REMOTE_DENSE_CONFIG_PARTIAL",
    ):
        active_release_dense_channel_from_env(require_remote=False)


def test_local_projection_is_explicit_fallback_when_remote_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "QDRANT_URL",
        "QDRANT_API_KEY_READ",
        "QDRANT_READ_ONLY_API_KEY",
        "QDRANT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    channel = active_release_dense_channel_from_env(require_remote=False)

    assert isinstance(channel, LocalDenseProjectionChannel)


def test_remote_requirement_without_credentials_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_TOKEN",
        "CLOUDFLARE_API_TOKEN",
        "QDRANT_URL",
        "QDRANT_API_KEY_READ",
        "QDRANT_READ_ONLY_API_KEY",
        "QDRANT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(
        PA7ArbitraryQueryError,
        match="PA7_ACTIVE_RELEASE_REMOTE_DENSE_CONFIG_MISSING",
    ):
        active_release_dense_channel_from_env(require_remote=True)
