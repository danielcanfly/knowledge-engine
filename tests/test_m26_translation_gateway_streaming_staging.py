from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from knowledge_engine import m26_console_api as console_module
from knowledge_engine import m26_public_api as public_api_module
from knowledge_engine import m26_translation_gateway_public_api as public_gateway_module


def _set_non_staging_public_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setenv("M26_PUBLIC_IP_HMAC_SECRET", "test-only-hmac-secret")


def _event_from_sse(block: str) -> dict[str, Any] | None:
    lines = [line for line in block.splitlines() if line]
    if not lines or lines[0].startswith(":"):
        return None
    event = ""
    data: list[str] = []
    for line in lines:
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    payload = json.loads("\n".join(data) or "{}")
    payload["type"] = event
    return payload


def _events(text: str) -> list[dict[str, Any]]:
    return [
        event
        for event in (_event_from_sse(block) for block in text.split("\n\n"))
        if event is not None
    ]


def test_production_entrypoint_exposes_canonical_answers_surface_and_streams_sse(
    monkeypatch,
) -> None:
    _set_non_staging_public_env(monkeypatch)
    monkeypatch.setattr(public_gateway_module, "load_production_answer_bundle", lambda: None)

    def fake_run_owner_query_for_web(**_: object) -> dict[str, object]:
        return {
            "status": "owner_only_cited_answer",
            "safe_abstention": False,
            "answer_text": "A grounded supported answer.",
            "citations": [
                {
                    "citation_id": "claim_1_ref_1",
                    "claim_id": "claim_1",
                    "source_identity": "source_public_1",
                    "section_id": "section_1",
                    "concept_id": "concept_1",
                    "release_id": "release_1",
                    "runtime_owned_locator": True,
                }
            ],
            "sources": [
                {
                    "source_identity": "source_public_1",
                    "source_id": "source_1",
                    "section_ids": ["section_1"],
                    "concept_ids": ["concept_1"],
                    "citation_numbers": [1],
                }
            ],
            "answer_claims": [
                {
                    "claim_id": "claim_1",
                    "claim_role": "direct",
                    "citation_ids": ["claim_1_ref_1"],
                    "support_ref_count": 1,
                }
            ],
            "provider_routing": {
                "closure_provider_initial": "cloudflare",
                "closure_provider_final": "cloudflare",
                "fallback_used": False,
                "fallback_reason": "NONE",
                "provider_attempts": [],
            },
            "reason_codes": [],
        }

    monkeypatch.setattr(
        public_api_module,
        "run_owner_query_for_web",
        fake_run_owner_query_for_web,
    )

    client = TestClient(console_module.create_app())

    health = client.get("/v1/answers/health")
    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["schema_version"] == "danielcanfly-answers-health/v1"
    assert health_payload["ok"] is True
    assert health_payload["answers_url"] == "/v1/answers"
    assert health_payload["backend"]["entrypoint"] == (
        "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
    )

    with client.stream(
        "POST",
        "/v1/answers",
        json={"question": "What is Daniel working on in the M26 integration?"},
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: request.accepted" in text
    assert '"type":"request.accepted"' in text
    assert "event: answer.completed" in text
    assert '"type":"answer.completed"' in text
    assert "A grounded supported answer." in text

    assert client.get("/api/rag/answers/health").status_code == 404


def test_translation_answers_sse_streams_runtime_stage_and_model_events(
    monkeypatch,
) -> None:
    _set_non_staging_public_env(monkeypatch)
    monkeypatch.setattr(public_gateway_module, "load_production_answer_bundle", lambda: None)

    def fake_run_owner_translation_gateway_for_web(**kwargs: object) -> dict[str, object]:
        sink = kwargs["event_sink"]
        sink({"type": "stage.started", "stage": "retrieval", "status": "started"})
        sink({"type": "stage.completed", "stage": "retrieval", "status": "completed"})
        sink(
            {
                "type": "model.started",
                "role": "closure",
                "provider": "cloudflare",
                "model": "@cf/meta/llama",
                "attempt": 1,
            }
        )
        sink(
            {
                "type": "model.completed",
                "role": "closure",
                "provider": "cloudflare",
                "model": "@cf/meta/llama",
                "attempt": 1,
                "status": "ok",
            }
        )
        return {"answer_text": "A grounded supported answer."}

    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )

    client = TestClient(
        public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    )

    with client.stream("POST", "/v1/answers", json={"question": "What is safe?"}) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    events = _events(text)
    event_names = [event["type"] for event in events]
    assert event_names.count("answer") == 1
    assert event_names.count("done") == 1
    assert event_names.index("stage_started") < event_names.index("stage_completed")
    assert event_names.index("model_started") < event_names.index("model_completed")
    assert event_names.index("model_completed") < event_names.index("answer")
    assert events[event_names.index("stage_started")]["stage"] == "retrieval"
    assert events[event_names.index("model_started")]["provider"] == "cloudflare"
    assert "reflect_retry" not in {str(event.get("stage")) for event in events}


def test_translation_answers_stage_started_streams_before_runtime_returns(
    monkeypatch,
) -> None:
    _set_non_staging_public_env(monkeypatch)
    monkeypatch.setattr(public_gateway_module, "load_production_answer_bundle", lambda: None)
    release_runtime = threading.Event()

    def fake_run_owner_translation_gateway_for_web(**kwargs: object) -> dict[str, object]:
        sink = kwargs["event_sink"]
        sink({"type": "stage.started", "stage": "retrieval", "status": "started"})
        release_runtime.wait(timeout=2)
        sink({"type": "stage.completed", "stage": "retrieval", "status": "completed"})
        return {"answer_text": "A grounded supported answer."}

    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )
    app = public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))

    async def run() -> list[dict[str, Any]]:
        stream = public_gateway_module._answer_event_stream(  # noqa: SLF001
            app=app,
            base_url="https://api.danielcanfly.com",
            payload={"question": "What is safe?"},
            correlation_id="test-correlation",
        )
        first = _event_from_sse(await anext(stream))
        second = _event_from_sse(await anext(stream))
        third = await asyncio.wait_for(anext(stream), timeout=1)
        release_runtime.set()
        await stream.aclose()
        return [event for event in (first, second, _event_from_sse(third)) if event is not None]

    events = asyncio.run(run())

    assert [event["type"] for event in events] == ["meta", "progress", "stage_started"]
    assert events[2]["stage"] == "retrieval"


def test_translation_answers_ignores_event_sink_exceptions(
    monkeypatch,
) -> None:
    _set_non_staging_public_env(monkeypatch)
    monkeypatch.setattr(public_gateway_module, "load_production_answer_bundle", lambda: None)

    def fake_public_runtime_event(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("observability failed")

    def fake_run_owner_translation_gateway_for_web(**kwargs: object) -> dict[str, object]:
        sink = kwargs["event_sink"]
        sink({"type": "stage.started", "stage": "retrieval"})
        return {"answer_text": "A grounded supported answer."}

    monkeypatch.setattr(public_gateway_module, "_public_runtime_event", fake_public_runtime_event)
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )

    client = TestClient(
        public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    )
    response = client.post("/v1/answers", json={"question": "What is safe?"})

    assert response.status_code == 200
    events = _events(response.text)
    assert [event["type"] for event in events].count("answer") == 1
    assert [event["type"] for event in events].count("done") == 1
    assert "A grounded supported answer." in response.text
