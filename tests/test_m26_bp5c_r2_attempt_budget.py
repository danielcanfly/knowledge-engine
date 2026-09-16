from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from knowledge_engine import m26_pa5_v8_live
from knowledge_engine.m26_cloudflare_provider_router import (
    CloudflareFallbackRequired,
    CloudflareRouterState,
    ProviderRoutingClient,
)
from knowledge_engine.m26_pa5_v8_live import (
    AnswerProviderAttemptBudget,
    LiveGateError,
    MiniMaxClient,
)


class _Provider:
    def __init__(self, *, failure: str = "") -> None:
        self.failure = failure
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        del payload
        self.calls += 1
        if self.failure:
            raise CloudflareFallbackRequired(self.failure)
        return {
            "text": "{}",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "cost_usd": "0",
            "call_class": call_class,
        }


def test_fifth_physical_attempt_is_mechanically_impossible() -> None:
    budget = AnswerProviderAttemptBudget(4)
    for _ in range(4):
        budget.consume(call_class="test")
    with pytest.raises(LiveGateError, match="physical-attempt budget exhausted"):
        budget.consume(call_class="test")


def test_cloudflare_failure_and_minimax_fallback_consume_two_attempts() -> None:
    budget = AnswerProviderAttemptBudget(4)
    router = ProviderRoutingClient(
        cloudflare=_Provider(failure="CLOUDFLARE_HTTP_500"),  # type: ignore[arg-type]
        fallback=_Provider(),  # type: ignore[arg-type]
        reviewer=_Provider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
        attempt_budget=budget,
    )

    router.call({}, "aq_fast_answer_synthesis")

    assert budget.snapshot()["consumed_physical_attempts"] == 2


def test_minimax_internal_retry_consumes_one_token_per_http_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            httpx.Response(500, json={}),
            httpx.Response(
                200,
                json={
                    "id": "ok",
                    "model": "MiniMax-M3",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "content": [{"type": "text", "text": "{}"}],
                },
            ),
        ]
    )

    class _Transport:
        @staticmethod
        def post(*args: Any, **kwargs: Any) -> httpx.Response:
            del args, kwargs
            return next(responses)

    budget = AnswerProviderAttemptBudget(4)
    monkeypatch.setattr(m26_pa5_v8_live, "prepare_minimax_http_client", lambda: _Transport())
    monkeypatch.setattr(m26_pa5_v8_live.time, "sleep", lambda _: None)
    client = MiniMaxClient(
        "test-key",
        max_calls=4,
        max_cost=Decimal("1"),
        attempt_budget=budget,
    )

    client.call({}, "aq_fast_answer_synthesis")

    assert budget.snapshot()["consumed_physical_attempts"] == 2


def test_generation_cannot_consume_reserved_reviewer_tail() -> None:
    budget = AnswerProviderAttemptBudget(4)
    budget.consume(call_class="aq_fast_answer_synthesis")
    budget.consume(call_class="aq_semantic_closure", reserve_tail_attempts=1)
    budget.consume(call_class="aq_semantic_closure_repair", reserve_tail_attempts=1)

    with pytest.raises(LiveGateError, match="physical-attempt budget exhausted"):
        budget.consume(
            call_class="aq_semantic_closure_repair",
            reserve_tail_attempts=1,
        )

    budget.consume(
        call_class="aq_claim_semantic_entailment",
        use_reserved_tail=True,
    )
    assert budget.snapshot() == {
        "max_physical_attempts": 4,
        "consumed_physical_attempts": 4,
        "remaining_physical_attempts": 0,
        "reserved_tail_attempts": 0,
        "events": budget.snapshot()["events"],
    }
