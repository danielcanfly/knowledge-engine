from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI

from knowledge_engine import m26_ask_api
from knowledge_engine import m26_pa5_v8_live as live


class _FakeResponse:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {
            "model": live.MODEL,
            "id": "phase2-response",
            "content": [{"type": "text", "text": "{}"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "stop_reason": "end_turn",
        }


class _RetryableResponse:
    status_code = 500


class _FakeHttpClient:
    instances: list[_FakeHttpClient] = []

    def __init__(self) -> None:
        self.posts = 0
        self.closed = False
        self.__class__.instances.append(self)

    def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        del args, kwargs
        self.posts += 1
        return _FakeResponse()

    def close(self) -> None:
        self.closed = True


class _RetryThenSuccessHttpClient(_FakeHttpClient):
    instances: list[_RetryThenSuccessHttpClient] = []

    def post(self, *args: Any, **kwargs: Any) -> _FakeResponse | _RetryableResponse:
        del args, kwargs
        self.posts += 1
        if self.posts == 1:
            return _RetryableResponse()
        return _FakeResponse()


@pytest.fixture(autouse=True)
def _reset_process_client() -> None:
    live.close_minimax_http_client()
    _FakeHttpClient.instances.clear()
    _RetryThenSuccessHttpClient.instances.clear()
    yield
    live.close_minimax_http_client()


def test_minimax_client_reuses_one_process_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live.httpx, "Client", _FakeHttpClient)
    provider = live.MiniMaxClient("test-key", max_calls=4, max_cost=Decimal("1"))
    payload = {"model": live.MODEL, "messages": []}

    provider.call(payload, "first")
    provider.call(payload, "second")

    assert len(_FakeHttpClient.instances) == 1
    assert _FakeHttpClient.instances[0].posts == 2
    assert provider.calls == 2


def test_minimax_retry_preserves_backoff_and_call_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[int] = []
    monkeypatch.setattr(live.httpx, "Client", _RetryThenSuccessHttpClient)
    monkeypatch.setattr(live.time, "sleep", sleeps.append)
    provider = live.MiniMaxClient("test-key", max_calls=4, max_cost=Decimal("1"))

    result = provider.call({"model": live.MODEL, "messages": []}, "selection")

    assert len(_RetryThenSuccessHttpClient.instances) == 1
    assert _RetryThenSuccessHttpClient.instances[0].posts == 2
    assert sleeps == [live.RETRY_DELAYS[0]]
    assert provider.calls == 2
    assert result["network_attempt"] == 2


def test_process_http_client_closes_and_recreates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live.httpx, "Client", _FakeHttpClient)

    first = live.prepare_minimax_http_client()
    assert live.prepare_minimax_http_client() is first

    live.close_minimax_http_client()
    assert first.closed is True

    second = live.prepare_minimax_http_client()
    assert second is not first
    assert len(_FakeHttpClient.instances) == 2


def test_query_runtime_preload_materializes_bundle_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    monkeypatch.setattr(
        m26_ask_api,
        "load_production_answer_bundle",
        lambda: observed.append("bundle"),
    )
    monkeypatch.setattr(
        m26_ask_api,
        "prepare_minimax_http_client",
        lambda: observed.append("transport"),
    )

    m26_ask_api._preload_query_runtime()

    assert observed == ["bundle", "transport"]


def test_ask_routes_register_startup_preload_and_shutdown_cleanup() -> None:
    app = FastAPI()
    m26_ask_api.register_m26_ask_routes(app, require_remote_dense=False)

    assert m26_ask_api._preload_query_runtime in app.router.on_startup
    assert m26_ask_api.close_minimax_http_client in app.router.on_shutdown
