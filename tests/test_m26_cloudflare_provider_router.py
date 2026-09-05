from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from knowledge_engine import m26_ask_api
from knowledge_engine.m26_cloudflare_provider_router import (
    CLOUDFLARE_MODEL,
    FALLBACK_CLOUDFLARE_DAILY_QUOTA,
    FALLBACK_CLOUDFLARE_TRANSIENT,
    FALLBACK_HARD_EXHAUSTED,
    FALLBACK_SOFT_EXHAUSTED,
    FALLBACK_TEMP_COOLDOWN,
    MINIMAX_MODEL,
    SEMANTIC_REVIEW_CALL_CLASS,
    STATE_AVAILABLE,
    STATE_HARD_EXHAUSTED_UNTIL_RESET,
    STATE_SOFT_EXHAUSTED_UNTIL_RESET,
    CloudflareFallbackRequired,
    CloudflareRouterState,
    CloudflareWorkersAIClient,
    LiveGateError,
    ProviderRoutingClient,
    build_provider_routing_client,
    classify_cloudflare_http_error,
    cloudflare_gpt_oss_120b_neurons,
    provider_status_dto,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "pilot/m26/m26-pa-7-resolved-production-gate.json"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"


class FakeProvider:
    def __init__(self, *, text: str = "{}", failure: str = "") -> None:
        self.text = text
        self.failure = failure
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        if self.failure:
            raise CloudflareFallbackRequired(self.failure)
        self.cost += Decimal("0.00001")
        return {
            "text": self.text,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": "fake-response",
            "call_class": call_class,
            "stop_reason": "stop",
            "content_block_types": ["text"],
        }


def _payload(secret: str = "do not persist this prompt") -> dict[str, Any]:
    task = {
        "evidence": [
            {
                "id": "local_1",
                "evidence_id": "ev_1",
                "locator_id": "loc_1",
                "source_identity": "source_1",
                "text_sha256": "a" * 64,
                "text": secret,
            }
        ]
    }
    return {
        "messages": [{"role": "user", "content": [{"type": "text", "text": json.dumps(task)}]}],
        "max_tokens": 128,
        "temperature": 0,
    }


def test_corrected_neuron_formula_uses_input_and_output_rates() -> None:
    assert cloudflare_gpt_oss_120b_neurons(1_000_000, 1_000_000) == Decimal("100000")
    assert cloudflare_gpt_oss_120b_neurons(1000, 2000) == Decimal("168.182000")


def test_available_routes_closure_to_cloudflare_and_review_to_minimax() -> None:
    state = CloudflareRouterState()
    cloudflare = FakeProvider(text='{"status":"abstain"}')
    fallback = FakeProvider()
    reviewer = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=reviewer,  # type: ignore[arg-type]
        state=state,
    )

    router.call(_payload(), "aq_semantic_closure")
    router.call(_payload(), SEMANTIC_REVIEW_CALL_CLASS)

    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 0
    assert len(reviewer.calls) == 1
    telemetry = router.telemetry()
    assert telemetry["closure_provider_final"] == "cloudflare"
    assert telemetry["fallback_used"] is False
    assert telemetry["provider_attempts"][0]["model"] == CLOUDFLARE_MODEL
    assert telemetry["provider_attempts"][1]["model"] == MINIMAX_MODEL


def test_valid_cloudflare_safe_abstention_does_not_fallback() -> None:
    state = CloudflareRouterState()
    cloudflare = FakeProvider(text='{"status":"abstain","answer_text":"","claims":[]}')
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=state,
    )

    router.call(_payload(), "aq_semantic_closure")

    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 0
    assert router.telemetry()["fallback_used"] is False


def test_3036_uses_minimax_once_in_the_same_closure() -> None:
    state = CloudflareRouterState()
    cloudflare = FakeProvider(failure="CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036")
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=state,
    )

    router.call(_payload(), "aq_semantic_closure")

    assert state.snapshot()["cloudflare_state"] == STATE_HARD_EXHAUSTED_UNTIL_RESET
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 1
    telemetry = router.telemetry()
    assert telemetry["fallback_reason"] == FALLBACK_CLOUDFLARE_DAILY_QUOTA
    assert telemetry["fallback_evidence_digest_match"] is True
    assert len(telemetry["provider_attempts"]) == 2
    assert router.calls == 2
    encoded = json.dumps(telemetry)
    assert "do not persist this prompt" not in encoded


def test_lazy_utc_reset_returns_hard_exhaustion_to_available() -> None:
    now = datetime(2026, 8, 15, 23, 59, tzinfo=UTC)
    clock_value = {"now": now}
    state = CloudflareRouterState(clock=lambda: clock_value["now"])
    state.record_daily_quota_exhausted("CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036")

    assert state.route_before_call()[1] == FALLBACK_HARD_EXHAUSTED
    clock_value["now"] = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)

    assert state.route_before_call() == ("cloudflare", "NONE")
    assert state.snapshot()["cloudflare_state"] == STATE_AVAILABLE
    assert state.snapshot()["cloudflare_estimated_neurons_today"] == "0.000"


def test_soft_limit_routes_subsequent_requests_to_minimax_until_reset() -> None:
    state = CloudflareRouterState(soft_limit=Decimal("1"))
    state.record_cloudflare_usage(1000, 1000)

    assert state.snapshot()["cloudflare_state"] == STATE_SOFT_EXHAUSTED_UNTIL_RESET
    assert state.route_before_call() == ("minimax-m3", FALLBACK_SOFT_EXHAUSTED)


def test_3040_uses_minimax_once_then_lazily_recovers() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    clock_value = {"now": now}
    state = CloudflareRouterState(clock=lambda: clock_value["now"], cooldown_seconds=30)
    cloudflare = FakeProvider(failure="CLOUDFLARE_TRANSIENT_CAPACITY_3040")
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=state,
    )

    router.call(_payload(), "aq_semantic_closure")
    assert state.route_before_call() == ("minimax-m3", FALLBACK_TEMP_COOLDOWN)
    assert router.telemetry()["fallback_reason"] == FALLBACK_CLOUDFLARE_TRANSIENT
    assert len(fallback.calls) == 1

    clock_value["now"] = now + timedelta(seconds=31)
    assert state.route_before_call() == ("cloudflare", "NONE")


def test_provider_status_is_cached_observability_only() -> None:
    state = CloudflareRouterState()
    status = provider_status_dto(state)

    assert status["closure_primary"] == "cloudflare"
    assert status["closure_fallback"] == "minimax-m3"
    assert status["semantic_reviewer"] == "minimax-m3"
    assert status["live_model_request"] is False
    assert "api" not in json.dumps(status).casefold()


def test_build_provider_routing_client_accepts_cloudflare_api_token_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.delenv("CLOUDFLARE_WORKER_AI_RESTFUL_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AI_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-cloudflare-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-cloudflare-account")

    router = build_provider_routing_client(
        max_provider_calls=1,
        max_cost=Decimal("0.10"),
        state=CloudflareRouterState(),
    )

    assert router.cloudflare is not None


def test_web_dto_exposes_sanitized_provider_routing() -> None:
    runtime = {
        "schema_version": "test",
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "trace_id": "trace",
        "question_sha256": "a" * 64,
        "answer_text": "",
        "provider_routing": {
            "closure_provider_initial": "cloudflare",
            "closure_provider_final": "minimax-m3",
            "fallback_used": True,
            "fallback_reason": FALLBACK_CLOUDFLARE_DAILY_QUOTA,
        },
    }

    dto = m26_ask_api.build_web_query_dto(runtime)

    assert dto["provider_routing"]["fallback_used"] is True
    assert dto["provider_routing"]["fallback_reason"] == FALLBACK_CLOUDFLARE_DAILY_QUOTA


def test_web_adapter_consumes_cloudflare_infra_failure_without_restarting_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.setenv("CLOUDFLARE_WORKER_AI_RESTFUL_API_KEY", "test-cloudflare-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-cloudflare-account")
    state = CloudflareRouterState()
    cloudflare = FakeProvider(failure="CLOUDFLARE_DAILY_QUOTA_EXHAUSTED_3036")
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=state,
    )
    runtime_calls = 0

    def fake_runtime(**kwargs: Any) -> dict[str, Any]:
        nonlocal runtime_calls
        runtime_calls += 1
        kwargs["provider_client"].call(_payload(), "aq_semantic_closure")
        return {
            "schema_version": "test",
            "status": "owner_only_cited_answer",
            "terminal_status": "verified_answer_ready_candidate",
            "trace_id": "trace",
            "question_sha256": "a" * 64,
            "answer_text": "fallback answer",
            "safe_abstention": False,
            "provider_invoked": True,
            "provider_call_count": 1,
            "latency_ms": 1,
            "unsupported_accepted_claims": 0,
        }

    monkeypatch.setattr(m26_ask_api, "build_provider_routing_client", lambda **_: router)
    monkeypatch.setattr(m26_ask_api, "run_owner_arbitrary_query", fake_runtime)

    dto = m26_ask_api.run_owner_query_for_web(
        root=ROOT,
        gate_path=GATE_PATH,
        request_payload={"question": "How can a query router and a DAG work together?"},
        owner_subject_hash=OWNER_SUBJECT_HASH,
    )

    assert runtime_calls == 1
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 1
    assert dto["provider_routing"]["fallback_used"] is True
    assert dto["provider_routing"]["fallback_reason"] == FALLBACK_CLOUDFLARE_DAILY_QUOTA
    assert dto["provider_routing"]["fallback_evidence_digest_match"] is True


def test_web_adapter_does_not_fallback_on_valid_cloudflare_safe_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.setenv("CLOUDFLARE_WORKER_AI_RESTFUL_API_KEY", "test-cloudflare-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-cloudflare-account")
    state = CloudflareRouterState()
    cloudflare = FakeProvider(text='{"status":"abstain","answer_text":"","claims":[]}')
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=state,
    )
    runtime_calls = 0

    def fake_runtime(**kwargs: Any) -> dict[str, Any]:
        nonlocal runtime_calls
        runtime_calls += 1
        kwargs["provider_client"].call(_payload(), "aq_semantic_closure")
        return {
            "schema_version": "test",
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "trace_id": "trace",
            "question_sha256": "a" * 64,
            "answer_text": "",
            "safe_abstention": True,
            "provider_invoked": True,
            "provider_call_count": 1,
            "latency_ms": 1,
            "unsupported_accepted_claims": 0,
        }

    monkeypatch.setattr(m26_ask_api, "build_provider_routing_client", lambda **_: router)
    monkeypatch.setattr(m26_ask_api, "run_owner_arbitrary_query", fake_runtime)

    dto = m26_ask_api.run_owner_query_for_web(
        root=ROOT,
        gate_path=GATE_PATH,
        request_payload={"question": "How can a query router and a DAG work together?"},
        owner_subject_hash=OWNER_SUBJECT_HASH,
    )

    assert runtime_calls == 1
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 0
    assert dto["safe_abstention"] is True
    assert dto["provider_routing"]["fallback_used"] is False


@pytest.mark.parametrize(
    "failure",
    [
        "CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429",
        "CLOUDFLARE_HTTP_500",
        "CLOUDFLARE_TIMEOUT_OR_NETWORK_TRANSIENT",
    ],
)
def test_transient_cloudflare_generation_failure_uses_minimax_exactly_once(
    failure: str,
) -> None:
    cloudflare = FakeProvider(failure=failure)
    fallback = FakeProvider(text='{"status":"answer"}')
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )

    assert router.call(_payload(), "aq_fast_answer_synthesis")["text"] == '{"status":"answer"}'
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 1
    assert router.calls == 2
    assert router.telemetry()["fallback_reason"] == FALLBACK_CLOUDFLARE_TRANSIENT


@pytest.mark.parametrize("failure", ["CLOUDFLARE_AUTH_OR_CONFIG", "CLOUDFLARE_PAID_PLAN_ONLY_5035"])
def test_cloudflare_authentication_and_configuration_fail_closed(failure: str) -> None:
    cloudflare = FakeProvider(failure=failure)
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )

    with pytest.raises(LiveGateError, match="failed closed"):
        router.call(_payload(), "aq_fast_answer_synthesis")
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 0
    assert router.telemetry()["fallback_used"] is False


def test_minimax_fallback_failure_is_terminal_and_not_retried() -> None:
    cloudflare = FakeProvider(failure="CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429")

    class FailedMiniMax(FakeProvider):
        def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
            self.calls.append((payload, call_class))
            raise LiveGateError("MINIMAX_HTTP_500")

    fallback = FailedMiniMax()
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )

    with pytest.raises(LiveGateError, match="MINIMAX_HTTP_500"):
        router.call(_payload(), "aq_fast_answer_synthesis")
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 1
    assert router.calls == 2
    assert router.telemetry()["provider_attempts"][-1]["result"] == "failed"


def test_malformed_cloudflare_response_stays_on_parser_validator_path() -> None:
    class MalformedResponse:
        status_code = 200
        text = "not-json"

        @staticmethod
        def json() -> dict[str, Any]:
            raise ValueError("invalid JSON")

    class MalformedTransport:
        @staticmethod
        def post(*args: Any, **kwargs: Any) -> MalformedResponse:
            del args, kwargs
            return MalformedResponse()

    client = CloudflareWorkersAIClient(
        api_key="test-key",
        account_id="test-account",
        state=CloudflareRouterState(),
        max_calls=1,
    )
    client.client = MalformedTransport()  # type: ignore[assignment]
    fallback = FakeProvider()
    router = ProviderRoutingClient(
        cloudflare=client,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=client.state,
    )

    result = router.call(_payload(), "aq_fast_answer_synthesis")
    assert result["text"] == "not-json"
    assert len(fallback.calls) == 0
    assert router.telemetry()["fallback_used"] is False


@pytest.mark.parametrize("status_code", [401, 403])
def test_cloudflare_auth_http_statuses_classify_as_fail_closed(status_code: int) -> None:
    response = httpx.Response(status_code, json={"errors": []})
    assert classify_cloudflare_http_error(response) == "CLOUDFLARE_AUTH_OR_CONFIG"


@pytest.mark.parametrize(
    "case_id",
    [
        "F012",
        "F021",
        "F035",
        "F070",
        "F082",
        "F094",
        "F110",
        "F120",
        "F132",
        "F145",
        "F155",
        "F167",
        "F181",
        "F195",
    ],
)
def test_fcq_429_contract_replay_routes_each_case_to_minimax(case_id: str) -> None:
    cloudflare = FakeProvider(failure="CLOUDFLARE_RATE_LIMIT_OR_CAPACITY_429")
    fallback = FakeProvider(text='{"status":"answer"}')
    router = ProviderRoutingClient(
        cloudflare=cloudflare,
        fallback=fallback,  # type: ignore[arg-type]
        reviewer=FakeProvider(),  # type: ignore[arg-type]
        state=CloudflareRouterState(),
    )
    payload = _payload(secret=f"captured provider-contract replay {case_id}")

    result = router.call(payload, "aq_fast_answer_synthesis")

    assert result["text"] == '{"status":"answer"}'
    assert len(cloudflare.calls) == 1
    assert len(fallback.calls) == 1
    assert router.calls == 2
    assert router.telemetry()["fallback_reason"] == FALLBACK_CLOUDFLARE_TRANSIENT
