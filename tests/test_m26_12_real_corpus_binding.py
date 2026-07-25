from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m26_real_corpus_binding import (
    PRODUCTION_MANIFEST_KEY,
    bind_real_corpus,
)

ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
SOURCE_SHA = "5250f8422f4fa08c1f3dc84840dc756850817635"
ADMISSION_SHA = "f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2"


class FakeStore:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values

    def get(self, key: str) -> bytes:
        return self.values[key]


class FakeResponse:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.value


class FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.calls.append((url, json))
        if url.endswith("/count"):
            return FakeResponse({"status": "ok", "result": {"count": 4197}})
        points = []
        for index in range(5):
            points.append(
                {
                    "id": f"point-{index}",
                    "payload": {
                        "section_id": f"section-{index}",
                        "source_id": f"source-{index}",
                        "release_id": RELEASE_ID,
                        "source_commit_sha": SOURCE_SHA,
                        "admission_sha256": ADMISSION_SHA,
                        "candidate_release_eligible": True,
                        "production_authority": False,
                        "text_sha256": hashlib.sha256(
                            f"text-{index}".encode()
                        ).hexdigest(),
                    },
                }
            )
        return FakeResponse({"status": "ok", "result": {"points": points}})


def production_values() -> dict[str, bytes]:
    manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": RELEASE_ID,
        "status": "production",
        "authority": {
            "production_pointer_authorized": True,
            "public_production_traffic_authorized": False,
        },
        "identities": {
            "engine_commit_sha": "fe499db2e043209bfa4c2390d513c5dc579727a2",
            "source_commit_sha": SOURCE_SHA,
            "foundation_commit_sha": "e53af5833193a644a4d7397b7d466ababb5e1373",
            "admission_sha256": ADMISSION_SHA,
        },
        "counts": {
            "document_sources": 156,
            "document_series": 25,
            "document_articles": 156,
            "document_sections": 4041,
            "document_graph_nodes": 4222,
            "document_graph_edges": 8525,
            "semantic_documents": 4197,
        },
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": RELEASE_ID,
        "manifest_key": PRODUCTION_MANIFEST_KEY,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    return {
        "channels/production.json": json.dumps(pointer).encode(),
        PRODUCTION_MANIFEST_KEY: manifest_bytes,
    }


def test_m26_12_real_corpus_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "knowledge_engine.m26_real_corpus_binding.httpx.Client", FakeClient
    )
    receipt = bind_real_corpus(
        root=ROOT,
        store=FakeStore(production_values()),
        qdrant_url="https://qdrant.example",
        qdrant_api_key="not-persisted",
    )
    assert receipt["status"] == "real_corpus_retrieval_binding_verified"
    assert receipt["release"]["release_id"] == RELEASE_ID
    assert receipt["qdrant"]["filtered_point_count"] == 4197
    assert receipt["qdrant"]["sample_count"] == 5
    assert receipt["qdrant"]["vectors_returned"] is False
    assert receipt["authority"]["live_provider_calls"] is False
    assert receipt["authority"]["production_pointer_mutation"] is False
    assert receipt["authority"]["raw_corpus_text_persisted"] is False


def test_m26_12_manifest_digest_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "knowledge_engine.m26_real_corpus_binding.httpx.Client", FakeClient
    )
    values = production_values()
    pointer = json.loads(values["channels/production.json"])
    pointer["manifest_sha256"] = "0" * 64
    values["channels/production.json"] = json.dumps(pointer).encode()
    with pytest.raises(IntegrityError, match="manifest digest drift"):
        bind_real_corpus(
            root=ROOT,
            store=FakeStore(values),
            qdrant_url="https://qdrant.example",
            qdrant_api_key="not-persisted",
        )


def test_m26_12_raw_text_payload_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TextClient(FakeClient):
        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> FakeResponse:
            response = super().post(url, headers=headers, json=json)
            if url.endswith("/scroll"):
                response.value["result"]["points"][0]["payload"]["text"] = "forbidden"
            return response

    monkeypatch.setattr(
        "knowledge_engine.m26_real_corpus_binding.httpx.Client", TextClient
    )
    with pytest.raises(IntegrityError, match="raw corpus text"):
        bind_real_corpus(
            root=ROOT,
            store=FakeStore(production_values()),
            qdrant_url="https://qdrant.example",
            qdrant_api_key="not-persisted",
        )
