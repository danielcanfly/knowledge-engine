from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AccessJWTAuthenticator,
    AdminAccessSettings,
    AdminActor,
    AdminAPIError,
    CapabilityGate,
    IdempotencyCoordinator,
    InMemoryIdempotencyStore,
    build_audit_event,
    install_admin_control_plane,
    redact,
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
class StaticCapabilities:
    gates: list[CapabilityGate]

    def list_capabilities(self) -> list[CapabilityGate]:
        return list(self.gates)

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return next((gate for gate in self.gates if gate.capability_id == capability_id), None)


def make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/answers/fail")
    async def public_fail() -> None:
        raise HTTPException(status_code=418, detail={"public": True})

    @app.post("/v1/admin/test-read-post")
    async def read_post() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/v1/admin/test-mutation")
    async def mutation(request: Request) -> dict[str, str]:
        operation_id, replay = request.app.state.admin_idempotency.begin(
            actor_id=request.state.admin_actor.actor_id,
            method=request.method,
            path=request.url.path,
            idempotency_key=request.headers["idempotency-key"],
            request_payload=await request.json(),
        )
        return {"operation_id": operation_id, "replay": str(replay).lower()}

    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(
            [
                CapabilityGate(
                    capability_id="corpus.read",
                    state="read_only",
                    reason_code="READ_ONLY_QUALIFIED",
                    source="test",
                )
            ]
        ),
        idempotency_store=InMemoryIdempotencyStore(),
    )
    app.state.admin_mutation_registry.register("POST", "/v1/admin/test-mutation")
    return app


def admin_headers(**extra: str) -> dict[str, str]:
    headers = {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }
    headers.update(extra)
    return headers


def test_public_route_is_not_subject_to_admin_auth_or_envelope() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/answers/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "x-request-id" not in response.headers

    failure = client.get("/v1/answers/fail")
    assert failure.status_code == 418
    assert failure.json() == {"detail": {"public": True}}


def test_admin_missing_or_invalid_assertion_fails_closed() -> None:
    client = TestClient(make_app())
    missing = client.get(
        "/v1/admin/session",
        headers={"origin": "https://console.danielcanfly.com"},
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "ADMIN_ACCESS_ASSERTION_INVALID"
    assert missing.headers["cache-control"] == "no-store"


def test_admin_session_has_common_envelope_and_safe_actor() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/admin/session", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"].startswith("admreq_")
    assert response.headers["x-request-id"] == payload["request_id"]
    assert payload["data"]["actor"]["actor_id"] == "cfaccess:owner"
    assert payload["data"]["auth"]["cookie_is_authority"] is False
    assert response.headers["access-control-allow-origin"] == "https://console.danielcanfly.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_admin_wrong_origin_is_rejected_before_handler() -> None:
    client = TestClient(make_app())
    response = client.get(
        "/v1/admin/session",
        headers={
            "origin": "https://evil.example",
            ACCESS_ASSERTION_HEADER: "valid-assertion",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_ORIGIN_DENIED"


def test_admin_preflight_is_strict_and_does_not_require_assertion() -> None:
    client = TestClient(make_app())
    allowed = client.options(
        "/v1/admin/test-mutation",
        headers={
            "origin": "https://console.danielcanfly.com",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type,idempotency-key",
        },
    )
    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == "https://console.danielcanfly.com"
    assert "authorization" not in allowed.headers["access-control-allow-headers"].lower()

    denied = client.options(
        "/v1/admin/test-mutation",
        headers={
            "origin": "https://console.danielcanfly.com",
            "access-control-request-method": "POST",
            "access-control-request-headers": "x-api-key",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_CORS_HEADER_DENIED"


def test_admin_mutation_requires_json_origin_and_idempotency_key() -> None:
    client = TestClient(make_app())
    bad_type = client.post(
        "/v1/admin/test-mutation",
        headers=admin_headers(**{"idempotency-key": "abcdefghijklmnop"}),
        content="x=1",
    )
    assert bad_type.status_code == 415
    assert bad_type.json()["error"]["code"] == "ADMIN_JSON_REQUIRED"

    missing_key = client.post(
        "/v1/admin/test-mutation",
        headers=admin_headers(**{"content-type": "application/json"}),
        json={"x": 1},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "ADMIN_IDEMPOTENCY_KEY_INVALID"


def test_non_state_changing_post_does_not_require_idempotency_key() -> None:
    client = TestClient(make_app())
    response = client.post(
        "/v1/admin/test-read-post",
        headers=admin_headers(**{"content-type": "application/json"}),
        json={"question": "safe read"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_default_mutation_registry_matches_parameterized_activation_path() -> None:
    app = make_app()
    registry = app.state.admin_mutation_registry
    assert registry.is_state_changing(
        "POST", "/v1/admin/index/versions/release-123/activate"
    )
    assert not registry.is_state_changing("POST", "/v1/admin/playground/ask")


def test_idempotency_safe_replay_and_conflict() -> None:
    coordinator = IdempotencyCoordinator(InMemoryIdempotencyStore())
    first_id, first_replay = coordinator.begin(
        actor_id="actor",
        method="POST",
        path="/v1/admin/jobs",
        idempotency_key="abcdefghijklmnop",
        request_payload={"scope": "one"},
    )
    second_id, second_replay = coordinator.begin(
        actor_id="actor",
        method="POST",
        path="/v1/admin/jobs",
        idempotency_key="abcdefghijklmnop",
        request_payload={"scope": "one"},
    )
    assert second_id == first_id
    assert first_replay is False
    assert second_replay is True

    with pytest.raises(AdminAPIError) as excinfo:
        coordinator.begin(
            actor_id="actor",
            method="POST",
            path="/v1/admin/jobs",
            idempotency_key="abcdefghijklmnop",
            request_payload={"scope": "two"},
        )
    assert excinfo.value.code == "ADMIN_IDEMPOTENCY_CONFLICT"


def test_mutation_endpoint_replays_same_operation_id() -> None:
    client = TestClient(make_app())
    headers = admin_headers(
        **{
            "content-type": "application/json",
            "idempotency-key": "abcdefghijklmnop",
        }
    )
    first = client.post("/v1/admin/test-mutation", headers=headers, json={"x": 1})
    second = client.post("/v1/admin/test-mutation", headers=headers, json={"x": 1})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["operation_id"] == second.json()["operation_id"]
    assert first.json()["replay"] == "false"
    assert second.json()["replay"] == "true"


def test_capability_contract_exposes_only_evidence_backed_states() -> None:
    client = TestClient(make_app())
    response = client.get("/v1/admin/capabilities", headers=admin_headers())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["capabilities"][0]["capability_id"] == "corpus.read"
    assert data["capabilities"][0]["state"] == "read_only"
    assert data["default_when_missing"]["state"] == "unavailable"


def test_redaction_removes_headers_jwts_bearers_and_nested_secret_keys() -> None:
    value = {
        "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
        "nested": {
            "Cf-Access-Jwt-Assertion": "aaa.bbb.ccc",
            "note": "Bearer abcdefghijklmnop",
            "api_key": "secret-value",
        },
    }
    redacted = redact(value)
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["Cf-Access-Jwt-Assertion"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "abcdefghijklmnop" not in redacted["nested"]["note"]

    event = build_audit_event(
        actor=OWNER,
        action="test",
        object_type="job",
        object_id="job-1",
        request_id="req-1",
        operation_id="op-1",
        outcome="accepted",
        reason_code="OK",
        metadata={"cookie": "private", "safe": "visible"},
    )
    assert event.to_payload()["metadata"] == {"cookie": "[REDACTED]", "safe": "visible"}


class StaticJWKClient:
    def __init__(self, key) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str):
        class Key:
            pass

        result = Key()
        result.key = self.key
        return result


def make_access_token(private_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://team.cloudflareaccess.com",
        "aud": ["aud-1"],
        "sub": "owner-sub",
        "email": "owner@example.com",
        "iat": now,
        "exp": now + 300,
        "type": "user",
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_access_validator_checks_signature_issuer_audience_and_owner_allowlist() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    settings = AdminAccessSettings(
        team_domain="https://team.cloudflareaccess.com",
        audience="aud-1",
        owner_emails=frozenset({"owner@example.com"}),
    )
    authenticator = AccessJWTAuthenticator(settings, jwk_client=StaticJWKClient(public_key))
    with pytest.raises(AdminAPIError) as missing:
        authenticator.authenticate(None)
    assert missing.value.code == "ADMIN_ACCESS_ASSERTION_MISSING"

    actor = authenticator.authenticate(make_access_token(private_key))
    assert actor.email == "owner@example.com"
    assert actor.actor_id.startswith("cfaccess:")

    with pytest.raises(AdminAPIError) as wrong_aud:
        authenticator.authenticate(make_access_token(private_key, aud=["wrong"]))
    assert wrong_aud.value.code == "ADMIN_ACCESS_ASSERTION_INVALID"

    with pytest.raises(AdminAPIError) as wrong_issuer:
        authenticator.authenticate(
            make_access_token(private_key, iss="https://evil.cloudflareaccess.com")
        )
    assert wrong_issuer.value.code == "ADMIN_ACCESS_ASSERTION_INVALID"

    non_owner = AccessJWTAuthenticator(
        AdminAccessSettings(
            team_domain="https://team.cloudflareaccess.com",
            audience="aud-1",
            owner_emails=frozenset({"someoneelse@example.com"}),
        ),
        jwk_client=StaticJWKClient(public_key),
    )
    with pytest.raises(AdminAPIError) as denied:
        non_owner.authenticate(make_access_token(private_key))
    assert denied.value.code == "ADMIN_ACTOR_NOT_OWNER"
