from __future__ import annotations

from typing import Any

from knowledge_engine.m23_7_5_live_shadow import VECTOR_DIMENSION
from knowledge_engine.m23_7_5_qdrant_strict_mode import (
    StrictModeSafeHttpLiveShadowClient,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHttpClient:
    calls: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(self.payloads.pop(0))


def _client() -> StrictModeSafeHttpLiveShadowClient:
    return StrictModeSafeHttpLiveShadowClient(
        CloudflareConfig(account_id="account", api_token="token"),
        QdrantConfig(
            base_url="https://qdrant.example",
            api_key="key",
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
        ),
    )


def test_scroll_and_query_avoid_unindexed_server_side_filters(monkeypatch):
    FakeHttpClient.calls = []
    FakeHttpClient.payloads = [
        {"result": {"points": [{"id": "sample", "payload": {}}]}},
        {"result": {"points": [{"id": "ranked", "score": 0.9, "payload": {}}]}},
    ]
    monkeypatch.setattr(
        "knowledge_engine.m23_7_5_qdrant_strict_mode.httpx.Client",
        FakeHttpClient,
    )

    client = _client()
    assert len(client.sample_points(8)) == 1
    assert len(client.query([1.0] + [0.0] * (VECTOR_DIMENSION - 1), 5)) == 1

    scroll, query = FakeHttpClient.calls
    assert scroll["url"].endswith("/points/scroll")
    assert query["url"].endswith("/points/query")
    assert "filter" not in scroll["json"]
    assert "filter" not in query["json"]
    assert scroll["json"] == {
        "limit": 8,
        "with_payload": True,
        "with_vector": False,
    }
    assert query["json"]["using"] == "default"
    assert query["json"]["limit"] == 5
    assert query["json"]["with_payload"] is True
    assert query["json"]["with_vector"] is False
    assert all(call["headers"] == {"api-key": "key"} for call in FakeHttpClient.calls)
    assert all("delete" not in call["url"] for call in FakeHttpClient.calls)
    assert all("upsert" not in call["url"] for call in FakeHttpClient.calls)
