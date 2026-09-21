from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from knowledge_engine import m26_public_api_execution_truth as truth


class FakeState:
    def __init__(self, route: str = "cloudflare", reason: str = "NONE") -> None:
        self.route = route
        self.reason = reason

    def route_before_call(self) -> tuple[str, str]:
        return self.route, self.reason


class FakeRoutingClient:
    def __init__(
        self,
        *,
        route: str = "cloudflare",
        reason: str = "NONE",
        cloudflare_present: bool = True,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.state = FakeState(route, reason)
        self.cloudflare = object() if cloudflare_present else None
        self.calls = 0
        self.cost = 0
        self.fallback_reason = reason
        self._result = result or {"latency_ms": 7, "text": "ok"}

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        del payload, call_class
        self.calls += 1
        return dict(self._result)

    def telemetry(self) -> dict[str, Any]:
        return {"provider_attempts": []}


def _capture() -> tuple[list[dict[str, Any]], Any, Any]:
    events: list[dict[str, Any]] = []
    previous_sink = getattr(truth._TLS, "raw_sink", None)  # noqa: SLF001
    previous_attempt = getattr(truth._TLS, "attempt", 1)  # noqa: SLF001
    truth._TLS.raw_sink = events.append  # noqa: SLF001
    truth._TLS.attempt = 1  # noqa: SLF001
    return events, previous_sink, previous_attempt


def _restore(previous_sink: Any, previous_attempt: Any) -> None:
    truth._TLS.raw_sink = previous_sink  # noqa: SLF001
    truth._TLS.attempt = previous_attempt  # noqa: SLF001


def test_plain_import_does_not_rebind_shared_process_globals() -> None:
    code = """
import knowledge_engine.m26_ask_api as ask
import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy
import knowledge_engine.m26_public_api as public_api

build_provider = ask.build_provider_routing_client
verify = legacy._verify_multi_evidence_provider_output
run_web = public_api.run_owner_query_for_web
model_events = public_api._model_events_from_dto

import knowledge_engine.m26_public_api_execution_truth as truth

assert truth._INSTALLED is False
assert ask.build_provider_routing_client is build_provider
assert legacy._verify_multi_evidence_provider_output is verify
assert public_api.run_owner_query_for_web is run_web
assert public_api._model_events_from_dto is model_events
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_install_and_uninstall_restore_shared_process_globals() -> None:
    before = (
        truth.ask_api.build_provider_routing_client,
        truth.legacy._verify_multi_evidence_provider_output,
        truth.public_api.run_owner_query_for_web,
        truth.public_api._model_events_from_dto,
    )
    try:
        truth.install()
        truth.install()
        assert truth.ask_api.build_provider_routing_client is truth._build_provider_routing_client
        assert (
            truth.legacy._verify_multi_evidence_provider_output
            is truth._verify_multi_evidence_provider_output
        )
        assert truth.public_api.run_owner_query_for_web is truth._run_owner_query_for_web
        assert truth.public_api._model_events_from_dto is truth._model_events_from_dto
    finally:
        truth.uninstall()

    after = (
        truth.ask_api.build_provider_routing_client,
        truth.legacy._verify_multi_evidence_provider_output,
        truth.public_api.run_owner_query_for_web,
        truth.public_api._model_events_from_dto,
    )
    assert after == before


def test_truth_filter_blocks_coarse_and_posthoc_execution_events() -> None:
    forwarded: list[dict[str, Any]] = []
    sink = truth._truth_filter(forwarded.append)  # noqa: SLF001
    assert sink is not None

    sink({"type": "stage.started", "stage": "closure"})
    sink({"type": "stage.started", "stage": "review"})
    sink({"type": "stage.completed", "stage": "verification"})
    sink({"type": "model.started", "provider": "guessed"})
    sink({"type": "model.completed", "provider": "guessed"})
    sink({"type": "repair.started"})
    sink({"type": "stage.started", "stage": "retrieval"})

    assert forwarded == [{"type": "stage.started", "stage": "retrieval"}]
    assert truth._model_events_from_dto({}) == []  # noqa: SLF001


def test_closure_model_events_are_emitted_at_actual_cloudflare_call_boundary() -> None:
    events, previous_sink, previous_attempt = _capture()
    try:
        client = truth.ExecutionBoundaryProviderClient(FakeRoutingClient())
        result = client.call({}, "aq_semantic_closure")
    finally:
        _restore(previous_sink, previous_attempt)

    assert result["text"] == "ok"
    assert [event["type"] for event in events] == [
        "stage.started",
        "model.started",
        "model.completed",
        "stage.completed",
    ]
    assert events[1]["role"] == "closure"
    assert events[1]["provider"] == "cloudflare"
    assert events[1]["model"] == "@cf/openai/gpt-oss-120b"
    assert events[1]["attempt"] == 1
    assert events[1]["fallback_used"] is False


def test_reviewer_model_events_are_bound_to_minimax_reviewer_call() -> None:
    events, previous_sink, previous_attempt = _capture()
    try:
        client = truth.ExecutionBoundaryProviderClient(FakeRoutingClient())
        client.call({}, "aq_claim_semantic_entailment")
    finally:
        _restore(previous_sink, previous_attempt)

    model_started = next(event for event in events if event["type"] == "model.started")
    assert model_started["role"] == "semantic_reviewer"
    assert model_started["provider"] == "minimax-m3"
    assert model_started["model"] == "MiniMax-M3"
    assert model_started["fallback_used"] is False


def test_closure_fallback_identity_comes_from_router_state_before_call() -> None:
    events, previous_sink, previous_attempt = _capture()
    try:
        client = truth.ExecutionBoundaryProviderClient(
            FakeRoutingClient(route="minimax-m3", reason="TEMP_COOLDOWN")
        )
        client.call({}, "aq_semantic_closure")
    finally:
        _restore(previous_sink, previous_attempt)

    model_started = next(event for event in events if event["type"] == "model.started")
    assert model_started["provider"] == "minimax-m3"
    assert model_started["model"] == "MiniMax-M3"
    assert model_started["fallback_used"] is True
    assert model_started["fallback_reason"] == "TEMP_COOLDOWN"


def test_attempt_two_emits_repair_only_when_repair_closure_really_starts() -> None:
    events, previous_sink, previous_attempt = _capture()
    try:
        client = truth.ExecutionBoundaryProviderClient(FakeRoutingClient())
        client.call({}, "aq_semantic_closure_repair")
    finally:
        _restore(previous_sink, previous_attempt)

    assert events[0]["type"] == "repair.started"
    model_started = next(event for event in events if event["type"] == "model.started")
    assert model_started["attempt"] == 2


def test_verification_stage_wraps_actual_deterministic_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, previous_sink, previous_attempt = _capture()
    truth._TLS.attempt = 2  # noqa: SLF001

    def fake_verify(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {"ok": True}

    monkeypatch.setattr(
        truth,
        "_ORIGINAL_VERIFY_MULTI_EVIDENCE_PROVIDER_OUTPUT",
        fake_verify,
    )
    try:
        result = truth._verify_multi_evidence_provider_output()  # noqa: SLF001
    finally:
        _restore(previous_sink, previous_attempt)

    assert result == {"ok": True}
    assert events == [
        {
            "type": "stage.started",
            "stage": "verification",
            "attempt": 2,
        },
        {
            "type": "stage.completed",
            "stage": "verification",
            "attempt": 2,
            "status": "verified",
        },
    ]


def test_public_runtime_drops_local_dense_and_requires_remote_dense(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(truth, "_ORIGINAL_PUBLIC_RUN_OWNER_QUERY_FOR_WEB", fake_run)
    result = truth._run_owner_query_for_web(  # noqa: SLF001
        dense_channel=object(),
        require_remote_dense=False,
        event_sink=None,
    )

    assert result == {"status": "ok"}
    assert "dense_channel" not in captured
    assert captured["require_remote_dense"] is True
