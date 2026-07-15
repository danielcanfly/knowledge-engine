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
    instances: list[FakeHttpClient] = []
    queued_payloads: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.instances.append(self)

    @classmethod
    def reset(cls, payloads: list[dict[str, Any]]) -> None:
        cls.instances = []
        cls.queued_payloads = list(payloads)

    def _response(self) -> FakeResponse:
        return FakeResponse(self.queued_payloads.pop(0))

    def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return self._response()

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> FakeResponse:
        self.calls.append(
            {"method": "POST", "url": url, "headers": headers, "json": json}
        )
        return self._response()

    def close(self) -> None:
        self.closed = True


def _client() -> StrictModeSafeHttpLiveShadowClient:
    return StrictModeSafeHttpLiveShadowClient(
        CloudflareConfig(account_id="account", api_token="token"),
        QdrantConfig(
            base_url="https://qdrant.example",
            api_key="key",
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
        ),
    )


def test_scroll_and_query_reuse_one_qdrant_session_without_filters(monkeypatch):
    FakeHttpClient.reset(
        [
            {"result": {"points": [{"id": "sample", "payload": {}}]}},
            {
                "result": {
                    "points": [{"id": "ranked", "score": 0.9, "payload": {}}]
                }
            },
        ]
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_7_5_qdrant_strict_mode.httpx.Client",
        FakeHttpClient,
    )

    with _client() as client:
        assert len(client.sample_points(8)) == 1
        assert len(client.query([1.0] + [0.0] * (VECTOR_DIMENSION - 1), 5)) == 1

    assert len(FakeHttpClient.instances) == 2
    cloudflare_http, qdrant_http = FakeHttpClient.instances
    assert cloudflare_http.calls == []
    assert len(qdrant_http.calls) == 2
    scroll, query = qdrant_http.calls
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
    assert all(call["headers"] == {"api-key": "key"} for call in qdrant_http.calls)
    assert all("delete" not in call["url"] for call in qdrant_http.calls)
    assert all("upsert" not in call["url"] for call in qdrant_http.calls)
    assert cloudflare_http.closed is True
    assert qdrant_http.closed is True


def test_embedding_requests_reuse_one_cloudflare_session_and_close(monkeypatch):
    vector = [1.0] + [0.0] * (VECTOR_DIMENSION - 1)
    FakeHttpClient.reset(
        [
            {"success": True, "result": {"data": [vector]}},
            {"success": True, "result": {"data": [vector]}},
        ]
    )
    monkeypatch.setattr(
        "knowledge_engine.m23_7_5_qdrant_strict_mode.httpx.Client",
        FakeHttpClient,
    )

    with _client() as client:
        assert len(client.embed("pilot/live-shadow#section-001")) == VECTOR_DIMENSION
        assert len(client.embed("pilot/live-shadow#section-002")) == VECTOR_DIMENSION

    assert len(FakeHttpClient.instances) == 2
    cloudflare_http, qdrant_http = FakeHttpClient.instances
    assert len(cloudflare_http.calls) == 2
    assert qdrant_http.calls == []
    assert all(call["method"] == "POST" for call in cloudflare_http.calls)
    assert all("api.cloudflare.com" in call["url"] for call in cloudflare_http.calls)
    assert cloudflare_http.closed is True
    assert qdrant_http.closed is True
