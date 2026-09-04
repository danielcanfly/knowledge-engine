from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from knowledge_engine import m26_translation_gateway_public_api as public_gateway_module
from knowledge_engine.m26_production_api import app as production_app


def _set_non_staging_public_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")


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

    def fake_run_owner_translation_gateway_for_web(**_: object) -> dict[str, object]:
        return {
            "answer_text": "A grounded supported answer.",
            "citation_count": 1,
            "source_count": 1,
            "translation_gateway": {
                "translation_applied": True,
                "invariant_check_result": "pass",
                "provider": "Google",
            },
        }

    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )

    client = TestClient(production_app)

    health = client.get("/v1/answers/health")
    assert health.status_code == 200
    surface = health.json()["surface"]
    assert surface["canonical_answers_url"].endswith("/v1/answers")
    assert surface["canonical_health_url"].endswith("/v1/answers/health")
    assert surface["future_production_answers_url"] == "https://api.danielcanfly.com/v1/answers"
    assert surface["legacy_api_rag_surface_canonical"] is False

    with client.stream(
        "POST",
        "/v1/answers",
        json={"question": "What is Daniel working on in the M26 integration?"},
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in text
    assert 'route":"/v1/answers"' in text
    assert "event: progress" in text
    assert "event: answer" in text
    assert "event: done" in text
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
        sink({
            "type": "model.started",
            "role": "closure",
            "provider": "cloudflare",
            "model": "@cf/meta/llama",
            "attempt": 1,
        })
        sink({
            "type": "model.completed",
            "role": "closure",
            "provider": "cloudflare",
            "model": "@cf/meta/llama",
            "attempt": 1,
            "status": "ok",
        })
        return {"answer_text": "A grounded supported answer."}

    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )

    client = TestClient(public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json")))

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

    client = TestClient(public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json")))
    response = client.post("/v1/answers", json={"question": "What is safe?"})

    assert response.status_code == 200
    events = _events(response.text)
    assert [event["type"] for event in events].count("answer") == 1
    assert [event["type"] for event in events].count("done") == 1
    assert "A grounded supported answer." in response.text
