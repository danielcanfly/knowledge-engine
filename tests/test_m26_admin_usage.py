from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminActor, AdminAPIError
from knowledge_engine.m26_admin_control_plane import ACCESS_ASSERTION_HEADER, install_admin_control_plane
from knowledge_engine.m26_admin_usage import (
    StaticUsageProvider,
    WORKERS_AI_FREE_ALLOCATION,
    install_admin_usage,
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


def headers() -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }


def make_app(payload: dict | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    install_admin_control_plane(app, authenticator=FakeAuthenticator())
    install_admin_usage(app, provider=StaticUsageProvider(payload or {}))
    return app


def metric(payload: dict, key: str) -> dict:
    return next(item for item in payload["data"]["metrics"] if item["key"] == key)


def test_default_usage_is_truthfully_unavailable_not_zero() -> None:
    response = TestClient(make_app()).get("/v1/admin/usage", headers=headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["observed_at"] is None
    assert payload["freshness"] == "unknown"
    for item in payload["data"]["metrics"]:
        assert item["value"] is None
        assert item["limit"] is None
        assert item["remaining"] is None
        assert item["availability"]["status"] == "unavailable"


def test_workers_ai_policy_is_separate_from_live_usage() -> None:
    payload = TestClient(make_app()).get("/v1/admin/usage", headers=headers()).json()
    policy = payload["data"]["workers_ai_policy"]
    usage = metric(payload, "workers_ai_neurons_day")
    assert policy["allocation"]["value"] == WORKERS_AI_FREE_ALLOCATION
    assert policy["allocation"]["unit"] == "neurons"
    assert policy["allocation"]["window"] == "day"
    assert policy["allocation"]["state"] == "verified"
    assert policy["allocation"]["reset_boundary"] == "00:00 UTC"
    assert policy["freshness"] == "snapshot"
    assert usage["value"] is None


def test_verified_limit_derives_remaining_and_floors_at_zero() -> None:
    provider = {
        "metrics": {
            "workers_ai_neurons_day": {
                "value": 12_500,
                "unit": "neurons",
                "window": "day",
                "source": "qualified_workers_ai_usage",
                "observed_at": "2026-09-04T23:59:59Z",
                "freshness": "near_live",
                "limit": {
                    "value": 10_000,
                    "unit": "neurons",
                    "window": "day",
                    "source": "cloudflare_workers_ai_pricing",
                    "verified": True,
                },
            }
        }
    }
    payload = TestClient(make_app(provider)).get("/v1/admin/usage", headers=headers()).json()
    item = metric(payload, "workers_ai_neurons_day")
    assert item["value"] == 12_500
    assert item["remaining"]["value"] == 0.0
    assert item["remaining"]["state"] == "derived"
    assert item["limit"]["verified"] is True


def test_unverified_limit_never_creates_remaining() -> None:
    provider = {
        "metrics": {
            "requests_minute": {
                "value": 70,
                "unit": "requests",
                "window": "minute",
                "source": "local_counter",
                "observed_at": "2026-09-04T12:00:00Z",
                "freshness": "live",
                "limit": {
                    "value": 100,
                    "source": "unqualified_config",
                    "verified": False,
                },
            }
        }
    }
    payload = TestClient(make_app(provider)).get("/v1/admin/usage", headers=headers()).json()
    item = metric(payload, "requests_minute")
    assert item["limit"]["value"] == 100
    assert item["remaining"] is None


def test_wrong_unit_is_rejected_instead_of_silently_converted() -> None:
    provider = {
        "metrics": {
            "tokens_hour": {
                "value": 1_000,
                "unit": "requests",
                "window": "hour",
                "source": "bad_source",
                "observed_at": "2026-09-04T12:00:00Z",
                "freshness": "live",
            }
        }
    }
    payload = TestClient(make_app(provider)).get("/v1/admin/usage", headers=headers()).json()
    item = metric(payload, "tokens_hour")
    assert item["value"] is None
    assert item["availability"]["reason_code"] == "USAGE_METRIC_INVALID_OR_UNQUALIFIED"


def test_missing_timestamp_and_partial_coverage_are_explicitly_partial() -> None:
    provider = {
        "metrics": {
            "requests_hour": {
                "value": 42,
                "unit": "requests",
                "window": "hour",
                "source": "qualified_request_counter",
                "freshness": "near_live",
                "coverage": {
                    "start": "2026-09-04T11:30:00Z",
                    "end": "2026-09-04T12:00:00Z",
                    "complete": False,
                },
            }
        }
    }
    payload = TestClient(make_app(provider)).get("/v1/admin/usage", headers=headers()).json()
    item = metric(payload, "requests_hour")
    assert item["value"] == 42
    assert item["observed_at"] is None
    assert item["availability"]["status"] == "partial"
    assert item["coverage"]["complete"] is False
    assert payload["availability"]["status"] == "partial"


def test_stale_metric_preserves_stale_freshness() -> None:
    provider = {
        "metrics": {
            "cache_reads_day": {
                "value": 9,
                "unit": "reads",
                "window": "day",
                "source": "cache_telemetry",
                "observed_at": "2026-09-03T00:00:00Z",
                "freshness": "stale",
            }
        }
    }
    payload = TestClient(make_app(provider)).get("/v1/admin/usage", headers=headers()).json()
    assert metric(payload, "cache_reads_day")["freshness"] == "stale"
    assert payload["freshness"] == "stale"


def test_daily_reset_boundary_remains_midnight_utc_across_boundary_fixture() -> None:
    before = {
        "metrics": {
            "workers_ai_neurons_day": {
                "value": 9_999,
                "unit": "neurons",
                "window": "day",
                "source": "qualified_workers_ai_usage",
                "observed_at": "2026-09-04T23:59:59Z",
                "freshness": "near_live",
            }
        }
    }
    after = {
        "metrics": {
            "workers_ai_neurons_day": {
                "value": 1,
                "unit": "neurons",
                "window": "day",
                "source": "qualified_workers_ai_usage",
                "observed_at": "2026-09-05T00:00:01Z",
                "freshness": "near_live",
            }
        }
    }
    client_before = TestClient(make_app(before))
    client_after = TestClient(make_app(after))
    before_payload = client_before.get("/v1/admin/usage", headers=headers()).json()
    after_payload = client_after.get("/v1/admin/usage", headers=headers()).json()
    assert before_payload["data"]["workers_ai_policy"]["allocation"]["reset_boundary"] == "00:00 UTC"
    assert after_payload["data"]["workers_ai_policy"]["allocation"]["reset_boundary"] == "00:00 UTC"
    assert metric(before_payload, "workers_ai_neurons_day")["value"] == 9_999
    assert metric(after_payload, "workers_ai_neurons_day")["value"] == 1


def test_admin_usage_auth_fails_closed_and_public_health_is_unchanged() -> None:
    client = TestClient(make_app())
    denied = client.get(
        "/v1/admin/usage",
        headers={"origin": "https://console.danielcanfly.com"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_ACCESS_ASSERTION_INVALID"

    public = client.get("/v1/answers/health")
    assert public.status_code == 200
    assert public.json() == {"ok": True}
