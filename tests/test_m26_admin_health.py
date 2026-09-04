from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
)
from knowledge_engine.m26_admin_control_plane import install_admin_control_plane
from knowledge_engine.m26_admin_health import StaticHealthObserver, install_admin_health

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
    release_id: str = "release-p08"
    production_pointer_sha256: str = "sha256:pointer-p08"


class ExplodingObserver:
    def collect(self, request) -> dict[str, Any]:
        del request
        raise RuntimeError("Bearer abcdefghijklmnopqrstuvwxyz secret-provider-token")


def healthy_external_observations() -> dict[str, Any]:
    observed_at = "2026-09-05T01:00:00Z"
    return {
        key: {
            "status": "healthy",
            "source": f"qualified_{key}_observer",
            "observed_at": observed_at,
            "freshness": "live",
            "latency_ms": 5,
            "detail": "Qualified bounded read succeeded.",
        }
        for key in ("frontend", "r2", "qdrant", "metadata", "provider")
    }


def make_app(observer=None) -> FastAPI:
    app = FastAPI(title="P08 test app", version="test")

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    install_admin_control_plane(app, authenticator=FakeAuthenticator())
    install_admin_health(app, observer=observer)
    app.state.admin_health_bundle_loader = lambda: FakeBundle()
    return app


def admin_headers() -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }


def dependency(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in payload["data"]["dependencies"] if item["key"] == key)


def test_admin_health_requires_owner_auth_without_state_leak() -> None:
    client = TestClient(make_app())
    response = client.get(
        "/v1/admin/health",
        headers={"origin": "https://console.danielcanfly.com"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "ADMIN_ACCESS_ASSERTION_INVALID"
    serialized = response.text.lower()
    assert "qdrant" not in serialized
    assert "production" not in serialized


def test_public_health_route_is_not_wrapped_by_admin_middleware() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/answers/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "x-request-id" not in response.headers


def test_default_health_is_partial_and_never_fabricates_external_green() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/admin/health", headers=admin_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"].startswith("admreq_")
    assert payload["availability"]["status"] == "partial"
    assert payload["data"]["overall_status"] == "degraded"
    assert len(payload["data"]["dependencies"]) == 8
    assert dependency(payload, "backend")["status"] == "healthy"
    assert dependency(payload, "canonical_api")["status"] == "healthy"
    assert dependency(payload, "production")["status"] == "healthy"
    for key in ("frontend", "r2", "qdrant", "metadata", "provider"):
        item = dependency(payload, key)
        assert item["status"] == "unavailable"
        assert item["observed_at"] is None
        assert item["latency_ms"] is None


def test_all_required_dependencies_must_be_observed_before_overall_healthy() -> None:
    observer = StaticHealthObserver(healthy_external_observations())
    payload = TestClient(make_app(observer)).get("/v1/admin/health", headers=admin_headers()).json()

    assert payload["availability"]["status"] == "available"
    assert payload["data"]["overall_status"] == "healthy"
    assert all(item["status"] == "healthy" for item in payload["data"]["dependencies"])


def test_provider_429_is_warning_not_outage() -> None:
    observations = healthy_external_observations()
    observations["provider"] = {
        "status": "error",
        "source": "qualified_provider_probe",
        "observed_at": "2026-09-05T01:00:00Z",
        "freshness": "live",
        "latency_ms": 18,
        "error_code": "429",
        "detail": "Bounded provider probe was rate limited.",
    }
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    provider = dependency(payload, "provider")
    assert provider["status"] == "warning"
    assert provider["availability"]["status"] == "available"
    assert provider["availability"]["reason_code"] == "SYSTEM_HEALTH_RATE_LIMITED"
    assert payload["data"]["overall_status"] == "degraded"


def test_identity_mismatch_downgrades_green_to_warning() -> None:
    observations = healthy_external_observations()
    observations["frontend"] = {
        "status": "healthy",
        "source": "qualified_frontend_identity",
        "observed_at": "2026-09-05T01:00:00Z",
        "freshness": "live",
        "expected": "frontend:expected",
        "observed": "frontend:other",
        "detail": "Observed immutable frontend identity.",
    }
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    frontend = dependency(payload, "frontend")
    assert frontend["status"] == "warning"
    assert frontend["availability"]["reason_code"] == "SYSTEM_HEALTH_IDENTITY_MISMATCH"
    assert frontend["expected"] == "frontend:expected"
    assert frontend["observed"] == "frontend:other"


def test_healthy_claim_without_observation_time_fails_closed() -> None:
    observations = healthy_external_observations()
    observations["qdrant"] = {
        "status": "healthy",
        "source": "qualified_qdrant_probe",
        "freshness": "live",
        "detail": "Missing authoritative timestamp on purpose.",
    }
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    qdrant = dependency(payload, "qdrant")
    assert qdrant["status"] == "unknown"
    assert qdrant["availability"]["status"] == "unavailable"
    assert qdrant["availability"]["reason_code"] == "SYSTEM_HEALTH_OBSERVATION_TIME_REQUIRED"


def test_naive_timestamp_is_not_authoritative_health_evidence() -> None:
    observations = healthy_external_observations()
    observations["metadata"] = {
        "status": "healthy",
        "source": "qualified_metadata_probe",
        "observed_at": "2026-09-05T01:00:00",
        "freshness": "live",
        "detail": "Timestamp intentionally lacks timezone evidence.",
    }
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    metadata = dependency(payload, "metadata")
    assert metadata["status"] == "unknown"
    assert metadata["observed_at"] is None
    assert metadata["availability"]["reason_code"] == "SYSTEM_HEALTH_OBSERVATION_TIME_REQUIRED"


def test_healthy_claim_with_unknown_freshness_fails_closed() -> None:
    observations = healthy_external_observations()
    observations["r2"] = {
        "status": "healthy",
        "source": "qualified_r2_probe",
        "observed_at": "2026-09-05T01:00:00Z",
        "freshness": "mystery",
        "detail": "Freshness intentionally invalid.",
    }
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    r2 = dependency(payload, "r2")
    assert r2["status"] == "unknown"
    assert r2["availability"]["status"] == "partial"
    assert r2["availability"]["reason_code"] == "SYSTEM_HEALTH_FRESHNESS_REQUIRED"


def test_non_finite_latency_is_dropped() -> None:
    observations = healthy_external_observations()
    observations["qdrant"]["latency_ms"] = float("nan")
    payload = (
        TestClient(make_app(StaticHealthObserver(observations)))
        .get("/v1/admin/health", headers=admin_headers())
        .json()
    )

    assert dependency(payload, "qdrant")["latency_ms"] is None


def test_observer_exception_is_fail_closed_and_does_not_leak_error_text() -> None:
    response = TestClient(make_app(ExplodingObserver())).get(
        "/v1/admin/health", headers=admin_headers()
    )

    assert response.status_code == 200
    payload = response.json()
    assert dependency(payload, "provider")["status"] == "unavailable"
    serialized = response.text
    assert "secret-provider-token" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized


def test_admin_health_is_read_only_and_no_store() -> None:
    response = TestClient(make_app()).get("/v1/admin/health", headers=admin_headers())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == response.json()["request_id"]
