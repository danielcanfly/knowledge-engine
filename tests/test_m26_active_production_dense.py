from __future__ import annotations

from typing import Any

import httpx
import pytest
import knowledge_engine.m26_active_production_dense as dense
from knowledge_engine.m26_active_production_release import ActiveProductionRelease
from knowledge_engine.m26_pa7_arbitrary_query_runtime import PA7ArbitraryQueryError
from knowledge_engine.m26_production_answer_bundle import ProductionAnswerBundle


SUCCESSOR_RELEASE_ID = "m26-successor-release"
SUCCESSOR_COLLECTION = "m26_successor_dense"
SUCCESSOR_SOURCE_SHA = "a" * 40
SUCCESSOR_ADMISSION_SHA256 = "b" * 64
SUCCESSOR_POINTER_SHA256 = "c" * 64
SUCCESSOR_MANIFEST_SHA256 = "d" * 64


def _successor_bundle() -> ProductionAnswerBundle:
    active = ActiveProductionRelease(
        release_id=SUCCESSOR_RELEASE_ID,
        production_manifest_key=(
            f"releases/{SUCCESSOR_RELEASE_ID}/promotion/production-manifest.json"
        ),
        production_manifest_sha256="1" * 64,
        candidate_manifest_key=f"releases/{SUCCESSOR_RELEASE_ID}/manifest.json",
        candidate_manifest_sha256=SUCCESSOR_MANIFEST_SHA256,
        qdrant_collection=SUCCESSOR_COLLECTION,
        source_commit_sha=SUCCESSOR_SOURCE_SHA,
        admission_sha256=SUCCESSOR_ADMISSION_SHA256,
        semantic_point_count=4424,
        pointer={
            "channel": "production",
            "release_id": SUCCESSOR_RELEASE_ID,
        },
        pointer_sha256=SUCCESSOR_POINTER_SHA256,
        production_manifest={"release_id": SUCCESSOR_RELEASE_ID},
        candidate_manifest={"release_id": SUCCESSOR_RELEASE_ID},
    )
    return ProductionAnswerBundle(
        manifest={"release_id": SUCCESSOR_RELEASE_ID},
        graph={},
        graph_v2={},
        lexical_index={},
        provenance={},
        manifest_sha256=SUCCESSOR_MANIFEST_SHA256,
        artifact_sha256={},
        artifact_keys={},
        loaded_at="2026-09-07T00:00:00Z",
        resolved_release=active,
    )


def _configure_remote_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-account")
    monkeypatch.setenv("CLOUDFLARE_AI_TOKEN", "cf-token")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")
    monkeypatch.setenv("QDRANT_API_KEY_READ", "qdrant-read")
    monkeypatch.setenv("M26_PA7_DENSE_COLLECTION", "stale_historical_collection")
    monkeypatch.setenv("QDRANT_COLLECTION", "also_stale_collection")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "third_stale_collection")


def _qdrant_result_payload(*, release_id: str = SUCCESSOR_RELEASE_ID) -> dict[str, Any]:
    return {
        "concept_id": "concepts/successor",
        "section_id": "successor-section-1",
        "source_id": "successor-source-1",
        "release_id": release_id,
        "source_commit_sha": SUCCESSOR_SOURCE_SHA,
        "admission_sha256": SUCCESSOR_ADMISSION_SHA256,
        "candidate_release_eligible": True,
        "production_authority": True,
        "text_sha256": "e" * 64,
    }


def test_remote_dense_ignores_stale_collection_env_and_follows_active_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_remote_env(monkeypatch)
    monkeypatch.setattr(dense, "embed_sections", lambda *_args, **_kwargs: [[0.1, 0.2]])
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": "successor-point-1",
                        "score": 0.91,
                        "payload": _qdrant_result_payload(),
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dense.httpx, "post", fake_post)

    channel = dense.production_dense_channel_from_env(require_remote=True)
    assert channel is not None
    result = channel.search(
        question="What changed in the successor release?",
        bundle=_successor_bundle(),
        top_k=8,
    )

    assert f"/collections/{SUCCESSOR_COLLECTION}/points/search" in captured["url"]
    assert "stale_historical_collection" not in captured["url"]
    assert "also_stale_collection" not in captured["url"]
    assert "third_stale_collection" not in captured["url"]

    must = captured["json"]["filter"]["must"]
    assert {item["key"]: item["match"]["value"] for item in must} == {
        "release_id": SUCCESSOR_RELEASE_ID,
        "source_commit_sha": SUCCESSOR_SOURCE_SHA,
        "admission_sha256": SUCCESSOR_ADMISSION_SHA256,
        "candidate_release_eligible": True,
        "production_authority": True,
    }

    backend = result["backend_identity"]
    assert backend["qdrant_collection"] == SUCCESSOR_COLLECTION
    assert backend["release_id"] == SUCCESSOR_RELEASE_ID
    assert backend["production_pointer_sha256"] == SUCCESSOR_POINTER_SHA256
    assert backend["semantic_point_count"] == 4424
    assert result["candidates"][0]["payload_release_id"] == SUCCESSOR_RELEASE_ID


def test_remote_dense_fails_closed_on_prior_release_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_remote_env(monkeypatch)
    monkeypatch.setattr(dense, "embed_sections", lambda *_args, **_kwargs: [[0.1, 0.2]])

    def fake_post(url: str, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "id": "old-point-1",
                        "score": 0.88,
                        "payload": _qdrant_result_payload(release_id="prior-release"),
                    }
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(dense.httpx, "post", fake_post)
    channel = dense.production_dense_channel_from_env(require_remote=True)
    assert channel is not None

    with pytest.raises(PA7ArbitraryQueryError) as exc_info:
        channel.search(
            question="Use only the active production release",
            bundle=_successor_bundle(),
            top_k=8,
        )

    assert exc_info.value.reason_code == "PA7_QDRANT_PAYLOAD_IDENTITY_MISMATCH"


def test_remote_dense_required_config_does_not_require_collection_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_remote_env(monkeypatch)
    monkeypatch.delenv("M26_PA7_DENSE_COLLECTION", raising=False)
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.delenv("QDRANT_COLLECTION_NAME", raising=False)

    channel = dense.production_dense_channel_from_env(require_remote=True)

    assert channel is not None
