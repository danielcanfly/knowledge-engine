from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from knowledge_engine import m26_console_p05_ask_playground as p05
from knowledge_engine.m26_admin_control_plane import AdminActor

OWNER = AdminActor(
    actor_id="cfaccess:test-owner",
    subject="cloudflare-access-subject",
    email="owner@example.com",
    actor_type="human",
    issuer="https://team.cloudflareaccess.com",
    audience=("console-aud",),
)


def fake_request() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            admin_request_id="admreq_p05_test",
            admin_actor=OWNER,
        )
    )


def test_canonical_envelope_does_not_fabricate_observation_time() -> None:
    payload = p05._canonical_envelope(
        fake_request(),
        data={"mode": "retrieve"},
        status="partial",
        reason_code="DENSE_TRANSIENT_UNAVAILABLE",
        freshness="near_live",
    )

    assert payload == {
        "request_id": "admreq_p05_test",
        "observed_at": None,
        "freshness": "near_live",
        "availability": {
            "status": "partial",
            "reason_code": "DENSE_TRANSIENT_UNAVAILABLE",
            "detail": None,
        },
        "provenance": {"source": "m26_pa7_arbitrary_query_runtime"},
        "data": {"mode": "retrieve"},
    }


def test_runtime_owner_binding_uses_server_side_pa7_identity_not_access_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in p05._RUNTIME_OWNER_HASH_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "ABCDEF1234")

    value = p05._runtime_owner_subject_hash(fake_request())

    assert value == "abcdef1234"
    assert value != OWNER.subject


def test_runtime_owner_binding_fails_closed_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in p05._RUNTIME_OWNER_HASH_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(p05.AdminAPIError) as excinfo:
        p05._runtime_owner_subject_hash(fake_request())

    assert excinfo.value.code == "PLAYGROUND_RUNTIME_OWNER_HASH_UNCONFIGURED"


def test_english_translation_bypass_does_not_construct_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = 0

    def forbidden_provider(_app):
        nonlocal called
        called += 1
        raise AssertionError("English bypass must not construct translation provider")

    monkeypatch.setattr(p05, "_app_translation_provider", forbidden_provider)

    assert p05._translation_provider_for_question(object(), "What is retrieval?") is None
    assert called == 0


def test_non_english_translation_uses_configured_app_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = object()
    monkeypatch.setattr(p05, "_app_translation_provider", lambda _app: provider)

    assert p05._translation_provider_for_question(object(), "什麼是檢索？") is provider


def test_playground_request_is_strict_and_top_k_is_bounded() -> None:
    assert p05.PlaygroundRequest(question="hello").top_k == 5
    with pytest.raises(ValidationError):
        p05.PlaygroundRequest(question="hello", top_k=21)
    with pytest.raises(ValidationError):
        p05.PlaygroundRequest(question="hello", extra_field=True)


def test_retrieval_only_structurally_never_crosses_generation_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = {
        "self_sha256": "gate-sha",
        "production_identities": {
            "owner_only_route": "owner-route",
            "allowlisted_owner_subject_hash": "owner-hash",
        },
    }
    bundle = SimpleNamespace(
        release_id=p05.FULL_PRODUCTION_RELEASE_ID,
        manifest_sha256="manifest-sha",
    )
    evidence = [
        {
            "evidence_id": f"ev-{index}",
            "locator_id": f"loc-{index}",
            "section_id": f"section-{index}",
        }
        for index in range(4)
    ]

    monkeypatch.setattr(p05, "load_json", lambda _path: {})
    monkeypatch.setattr(p05, "_validate_gate", lambda _root, _gate: gate)
    monkeypatch.setattr(
        p05,
        "evaluate_owner_admission",
        lambda _gate, _request: {"admitted": True, "reason_codes": []},
    )
    monkeypatch.setattr(p05, "load_production_answer_bundle", lambda: bundle)
    monkeypatch.setattr(
        p05,
        "_run_lexical_primary_retrieval",
        lambda **_kwargs: ({"results": []}, {"candidates": []}),
    )
    monkeypatch.setattr(p05, "_select_evidence", lambda **_kwargs: evidence)
    monkeypatch.setattr(p05, "_has_meaningful_overlap", lambda *_args: True)
    monkeypatch.setattr(
        p05,
        "_retrieval_response_fields",
        lambda **_kwargs: {"selected_evidence_count": 2},
    )

    events: list[dict[str, object]] = []
    result = p05._retrieval_only_after_translation(
        root=Path("."),
        gate_path=Path("gate.json"),
        translated_question="What is retrieval?",
        owner_subject_hash="owner-hash",
        top_k=2,
        event_sink=events.append,
    )

    assert len(result["selected_evidence"]) == 2
    assert result["accounting"]["generation_provider_calls"] == 0
    assert result["accounting"]["generation_retries"] == 0
    assert result["accounting"]["cost_boundary_crossed"] is False
    assert result["request_policy"] == {
        "top_k_applied": True,
        "top_k": 2,
        "generation_allowed": False,
    }
    assert not any(event.get("type") == "model.started" for event in events)


def test_full_ask_bypasses_default_provider_routing_and_limits_synthesis_to_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMiniMax:
        def __init__(self, api_key: str, *, max_calls: int, max_cost: Decimal) -> None:
            captured["api_key"] = api_key
            captured["client_max_calls"] = max_calls
            captured["client_max_cost"] = max_cost

    def fake_run_owner_query_for_web(**kwargs):
        captured.update(kwargs)
        return {"accounting": {"provider_call_count": 1}}

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(p05, "MiniMaxClient", FakeMiniMax)
    monkeypatch.setattr(p05, "run_owner_query_for_web", fake_run_owner_query_for_web)

    result = p05._full_ask_after_translation(
        root=Path("."),
        gate_path=Path("gate.json"),
        translated_question="What is retrieval?",
        owner_subject_hash="owner-hash",
        event_sink=lambda _event: None,
    )

    assert result["accounting"]["provider_call_count"] == 1
    assert captured["client_max_calls"] == 1
    assert captured["client_max_cost"] == Decimal("0.10")
    assert captured["max_provider_calls"] == 1
    assert captured["max_cost"] == Decimal("0.10")
    assert captured["provider_client"].__class__ is FakeMiniMax
    assert captured["public_request"] is False


def test_retrieval_degradation_preserves_runtime_reason_code() -> None:
    reason, detail = p05._retrieval_degradation(
        [
            {
                "type": "stage.degraded",
                "stage": "retrieval",
                "channel": "dense",
                "reason_code": "DENSE_SEARCH_DEADLINE_EXCEEDED",
                "deadline_ms": 2000,
            }
        ]
    )

    assert reason == "DENSE_SEARCH_DEADLINE_EXCEEDED"
    assert detail == "dense deadline_ms=2000"


def test_exception_reason_code_prefers_stable_runtime_code() -> None:
    class RuntimeFailure(RuntimeError):
        reason_code = "PA7_DENSE_BACKEND_INVALID"

    assert (
        p05._exception_reason_code(RuntimeFailure("boom"), "PLAYGROUND_RETRIEVAL_FAILED")
        == "PA7_DENSE_BACKEND_INVALID"
    )


def test_router_declares_both_playground_posts_as_non_state_changing() -> None:
    routes = {route.path: route for route in p05.router().routes if hasattr(route, "openapi_extra")}

    retrieve = routes["/v1/admin/playground/retrieve"]
    ask = routes["/v1/admin/playground/ask"]
    assert retrieve.operation_id == "inspectRetrieval"
    assert ask.operation_id == "runFullAsk"
    assert retrieve.openapi_extra["x-m26-capability-id"] == "playground.retrieve"
    assert ask.openapi_extra["x-m26-capability-id"] == "playground.ask"
    assert retrieve.openapi_extra["x-m26-state-changing"] is False
    assert ask.openapi_extra["x-m26-state-changing"] is False
    assert retrieve.openapi_extra["x-m26-public-contract-separate"] is True
    assert ask.openapi_extra["x-m26-public-contract-separate"] is True
