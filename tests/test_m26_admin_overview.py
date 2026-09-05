from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminActor, AdminAPIError
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    install_admin_control_plane,
)
from knowledge_engine.m26_admin_overview import (
    OVERVIEW_SECTION_IDS,
    install_admin_overview,
)

OWNER = AdminActor(
    actor_id="cfaccess:owner",
    subject="owner-sub",
    email="owner@example.com",
    actor_type="human",
    issuer="https://team.cloudflareaccess.com",
    audience=("aud-1",),
)


class FakeAuthenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid-assertion":
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACCESS_ASSERTION_INVALID",
                message="invalid",
            )
        return OWNER


@dataclass
class FakeBundle:
    release_id: str = "release-test"
    manifest_sha256: str = "a" * 64
    production_pointer_sha256: str = "b" * 64
    loaded_at: str = "2026-09-04T12:00:00Z"


def admin_headers() -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }


def make_app(*, bundle_loader=None) -> FastAPI:
    app = FastAPI(title="test-admin", version="test")
    install_admin_control_plane(app, authenticator=FakeAuthenticator())
    install_admin_overview(app)
    app.state.admin_overview_bundle_loader = bundle_loader or (lambda: FakeBundle())
    app.state.admin_overview_public_health_builder = lambda **_: {
        "ok": True,
        "status": "ok",
        "surface": {"canonical_health_url": "https://api.example/v1/answers/health"},
    }
    return app


def test_overview_returns_partial_envelope_without_fabricated_metrics() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/admin/overview", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()

    assert response.headers["x-request-id"] == payload["request_id"]
    assert payload["availability"]["status"] == "partial"
    assert payload["provenance"]["source"] == "m26_admin_overview"
    assert payload["observed_at"] is not None

    sections = payload["data"]["sections"]
    assert tuple(sections) == OVERVIEW_SECTION_IDS
    assert sections["release_index"]["status"] == "unknown"
    assert sections["release_index"]["value"]["release_id"] == "release-test"
    assert sections["public_ask"]["status"] == "healthy"

    for section_id in (
        "index_audit",
        "qa_exceptions_24h",
        "ingestion_jobs",
        "usage_rate_limits",
        "golden_evaluation",
    ):
        section = sections[section_id]
        assert section["availability"]["status"] == "unavailable"
        assert section["status"] == "unavailable"
        assert section["value"] is None
        assert section["observed_at"] is None

    serialized = response.text.lower()
    assert "score_lt" not in serialized
    assert '"count":0' not in serialized
    assert '"usage":0' not in serialized


def test_overview_dependency_failure_degrades_only_affected_section() -> None:
    def failed_bundle():
        raise RuntimeError("do not expose dependency internals")

    client = TestClient(make_app(bundle_loader=failed_bundle))
    response = client.get("/v1/admin/overview", headers=admin_headers())
    assert response.status_code == 200
    sections = response.json()["data"]["sections"]

    assert sections["release_index"]["status"] == "unavailable"
    assert sections["release_index"]["value"] is None
    assert sections["public_ask"]["status"] == "healthy"
    assert "do not expose dependency internals" not in response.text


def test_overview_admin_auth_still_fails_closed() -> None:
    client = TestClient(make_app())
    response = client.get(
        "/v1/admin/overview",
        headers={"origin": "https://console.danielcanfly.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_ASSERTION_INVALID"


def test_overview_is_read_only_and_does_not_register_a_mutation() -> None:
    app = make_app()
    assert not app.state.admin_mutation_registry.is_state_changing("GET", "/v1/admin/overview")
