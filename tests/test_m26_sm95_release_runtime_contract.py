from pathlib import Path

from knowledge_engine.m26_console_api import app

ROOT = Path(__file__).resolve().parents[1]


def test_combined_runtime_exposes_public_and_admin_routes() -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/answers" in paths
    assert "/v1/answers/health" in paths
    assert "/v1/admin/session" in paths
    assert "/v1/admin/capabilities" in paths


def test_dockerfile_uses_combined_app_and_canonical_public_health() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "knowledge_engine.m26_console_api:app" in text
    assert "http://127.0.0.1:8080/v1/answers/health" in text
    assert "http://127.0.0.1:8080/v1/health" not in text


def test_rollback_uses_canonical_public_health() -> None:
    text = (ROOT / "deploy" / "rollback.sh").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8080/v1/answers/health" in text
    assert "http://127.0.0.1:8080/v1/health" not in text


def test_deploy_liveness_deliberately_remains_openapi_probe() -> None:
    text = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8080/openapi.json" in text
    assert "Deployment only needs HTTP liveness plus immutable runtime identity" in text
