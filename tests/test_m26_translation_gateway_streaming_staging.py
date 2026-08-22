from __future__ import annotations

from fastapi.testclient import TestClient

from knowledge_engine import m26_translation_gateway_public_api as public_gateway_module
from knowledge_engine.m26_production_api import app as production_app


def test_production_entrypoint_exposes_canonical_answers_surface_and_streams_sse(
    monkeypatch,
) -> None:
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")

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
