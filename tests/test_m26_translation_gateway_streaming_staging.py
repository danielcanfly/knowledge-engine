from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from knowledge_engine import m26_translation_gateway_public_api as public_api


def test_public_staging_compose_runs_canonical_public_api_entrypoint() -> None:
    compose = yaml.safe_load(Path("docker-compose.public-staging.yml").read_text(encoding="utf-8"))
    service = compose["services"]["m26-public-api-staging"]
    command = service["command"]
    healthcheck = service["healthcheck"]["test"]

    assert "knowledge_engine.m26_translation_gateway_public_api:app" in command
    assert "knowledge_engine.m26_translation_gateway_streaming_staging:app" not in command
    assert any("/v1/answers/health" in part for part in healthcheck)
    assert not any("/v1/health" in part for part in healthcheck)


def test_public_staging_entrypoint_exposes_canonical_answers_surface_and_streams_sse(
    monkeypatch,
) -> None:
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")

    async def fake_answer_event_stream(**_: object):
        yield 'event: meta\ndata: {"route":"/v1/answers"}\n\n'
        yield 'event: progress\ndata: {"stage":"synthesis"}\n\n'
        yield 'event: answer\ndata: {"answer_text":"A grounded supported answer."}\n\n'
        yield 'event: done\ndata: {"status":"ok"}\n\n'

    monkeypatch.setattr(public_api, "_answer_event_stream", fake_answer_event_stream)

    client = TestClient(public_api.app)

    health = client.get("/v1/answers/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["surface"] == "/v1/answers"
    assert payload["canonical_host"] == "api-staging.danielcanfly.com"
    assert payload["legacy_api_rag_surface_canonical"] is False
    assert payload["legacy_namespace_status"] == "retired_compatibility_not_canonical"
    assert payload["urls"]["canonical_answers_url"] == "https://api-staging.danielcanfly.com/v1/answers"

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
    assert "event: answer" in text
    assert "event: done" in text
    assert "A grounded supported answer." in text
    assert client.get("/api/rag/answers/health").status_code == 404
