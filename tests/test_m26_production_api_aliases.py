from __future__ import annotations

from fastapi.testclient import TestClient

from knowledge_engine.m26_production_api import app


def test_production_api_exposes_canonical_answers_and_health_aliases() -> None:
    route_paths = {
        getattr(route, "path", "")
        for route in app.routes
    }

    assert "/health" in route_paths
    assert "/v1/health" in route_paths
    assert "/v1/answers" in app.openapi()["paths"]
    assert "/v1/answers/health" in app.openapi()["paths"]
