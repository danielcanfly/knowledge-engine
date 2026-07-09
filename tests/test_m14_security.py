from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from knowledge_engine import api
from knowledge_engine.auth import Authenticator, Principal
from knowledge_engine.config import Settings
from knowledge_engine.errors import AuthorizationError, ConfigurationError
from knowledge_engine.m14_interfaces import public_ask_widget_javascript
from knowledge_engine.m14_public_contracts import PublicAskRequest
from knowledge_engine.m14_security import (
    FixedWindowRateLimiter,
    PublicAbuseController,
    PublicControlError,
    PublicEdgeSecurityMiddleware,
    PublicExecutionGate,
    is_public_origin_allowed,
    public_client_key,
    public_rejection_telemetry,
)
from knowledge_engine.m14_security_contracts import (
    harden_public_widget_javascript,
    public_product_capabilities,
)


def _settings(**overrides) -> Settings:
    base = Settings(
        app_env="test",
        auth_mode="disabled",
        jwt_issuer=None,
        jwt_jwks_url=None,
        jwt_audience=None,
        jwt_default_audiences=("public", "internal"),
        object_store_backend="filesystem",
        filesystem_store_root=Path(".artifacts/test-store"),
        r2_endpoint_url=None,
        r2_bucket=None,
        r2_access_key_id=None,
        r2_secret_access_key=None,
        r2_region="auto",
        channel="production",
        cache_dir=Path(".artifacts/test-cache"),
        log_level="INFO",
    )
    return replace(base, **overrides)


def _principal(*audiences: str, authenticated: bool = True) -> Principal:
    return Principal(
        subject="security-user",
        audiences=frozenset(audiences),
        claims={},
        authenticated=authenticated,
    )


def _runtime_result(audience: str = "public") -> dict:
    return {
        "status": "answered",
        "release": {
            "release_id": "release-security",
            "manifest_sha256": "a" * 64,
        },
        "results": [
            {
                "concept_id": "concepts/security",
                "section_id": "concepts/security#overview",
                "title": "Security",
                "section_title": "Overview",
                "excerpt": f"Authorized {audience} answer.",
                "score": 10,
                "citations": [],
            }
        ],
        "not_found_reason": None,
    }


def test_public_security_configuration_is_bounded() -> None:
    settings = _settings()
    settings.validate()

    with pytest.raises(ConfigurationError, match="wildcard"):
        _settings(public_allowed_origins=("*",)).validate()
    with pytest.raises(ConfigurationError, match="HTTPS"):
        _settings(
            app_env="production",
            auth_mode="supabase_jwt",
            jwt_issuer="https://issuer.example",
            jwt_jwks_url="https://issuer.example/jwks",
            jwt_audience="knowledge",
            public_allowed_origins=("http://blog.example",),
        ).validate()
    with pytest.raises(ConfigurationError, match="PUBLIC_MAX_BODY_BYTES"):
        _settings(public_max_body_bytes=100).validate()
    with pytest.raises(ConfigurationError, match="PUBLIC_REQUEST_TIMEOUT_SECONDS"):
        _settings(public_request_timeout_seconds=0.01).validate()


def test_anonymous_public_principal_cannot_inherit_development_audiences() -> None:
    principal = Authenticator(_settings()).authenticate_public(None)
    assert principal.subject == "anonymous-public"
    assert principal.audiences == frozenset({"public"})
    assert principal.authenticated is False

    authenticated = Authenticator(_settings()).authenticate_public("Bearer development")
    assert authenticated.authenticated is True
    assert "internal" in authenticated.audiences


def test_anonymous_public_access_can_be_disabled() -> None:
    authenticator = Authenticator(_settings(public_anonymous_enabled=False))
    with pytest.raises(AuthorizationError, match="required"):
        authenticator.authenticate_public(None)


def test_elevated_audience_requires_authenticated_exact_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as anonymous_error:
        api.ask(
            PublicAskRequest(query="internal policy", audience="internal"),
            _principal("public", authenticated=False),
        )
    assert anonymous_error.value.status_code == 403
    assert "authenticated" in anonymous_error.value.detail["message"]

    with pytest.raises(HTTPException) as missing_claim_error:
        api.ask(
            PublicAskRequest(query="internal policy", audience="internal"),
            _principal("public", authenticated=True),
        )
    assert missing_claim_error.value.status_code == 403

    class StubRuntime:
        def query(self, query: str, audiences: set[str], *, limit: int) -> dict:
            assert query == "internal policy"
            assert audiences == {"internal"}
            assert limit == 5
            return _runtime_result("internal")

    monkeypatch.setattr(api, "get_runtime", lambda: StubRuntime())
    response = api.ask(
        PublicAskRequest(query="internal policy", audience="internal"),
        _principal("public", "internal", authenticated=True),
    )
    assert response.audience == "internal"


def test_origin_policy_is_exact_and_same_origin_by_default() -> None:
    assert is_public_origin_allowed(
        None,
        request_origin="https://api.example",
        allowed_origins=(),
    )
    assert is_public_origin_allowed(
        "https://api.example",
        request_origin="https://api.example",
        allowed_origins=(),
    )
    assert is_public_origin_allowed(
        "https://blog.example",
        request_origin="https://api.example",
        allowed_origins=("https://blog.example",),
    )
    assert not is_public_origin_allowed(
        "https://evil.example",
        request_origin="https://api.example",
        allowed_origins=("https://blog.example",),
    )
    assert not is_public_origin_allowed(
        "null",
        request_origin="https://api.example",
        allowed_origins=("https://blog.example",),
    )


def test_edge_middleware_enforces_origin_preflight_body_limit_and_headers() -> None:
    settings = _settings(
        public_allowed_origins=("https://blog.example",),
        public_max_body_bytes=1024,
    )
    test_app = FastAPI()
    test_app.add_middleware(
        PublicEdgeSecurityMiddleware,
        settings_provider=lambda: settings,
    )

    @test_app.post("/v1/ask")
    async def echo(request: Request) -> dict:
        body = await request.body()
        return {"size": len(body)}

    client = TestClient(test_app)
    denied = client.post(
        "/v1/ask",
        json={"query": "hello"},
        headers={"Origin": "https://evil.example"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PUBLIC-ORIGIN-403"
    assert "access-control-allow-origin" not in denied.headers

    preflight = client.options(
        "/v1/ask",
        headers={
            "Origin": "https://blog.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "https://blog.example"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert preflight.headers["access-control-max-age"] == "300"

    allowed = client.post(
        "/v1/ask",
        json={"query": "hello"},
        headers={"Origin": "https://blog.example"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://blog.example"
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in allowed.headers["permissions-policy"]

    oversized = client.post(
        "/v1/ask",
        content=b"x" * 1025,
        headers={
            "Content-Type": "application/json",
            "Origin": "https://blog.example",
        },
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "PUBLIC-QUERY-BODY-TOO-LARGE"
    assert oversized.headers["cache-control"] == "no-store"


def test_fixed_window_rate_limit_is_deterministic() -> None:
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=10)
    assert limiter.check("client", now=100.0) is None
    assert limiter.check("client", now=101.0) is None
    assert limiter.check("client", now=102.0) == 8
    assert limiter.check("client", now=110.0) is None


def test_client_keys_are_hashed_and_partition_authenticated_users() -> None:
    anonymous = public_client_key(
        _principal("public", authenticated=False),
        "203.0.113.10",
    )
    authenticated = public_client_key(
        _principal("public", authenticated=True),
        "203.0.113.10",
    )
    assert len(anonymous) == 64
    assert len(authenticated) == 64
    assert anonymous != authenticated
    assert "203.0.113.10" not in anonymous
    assert "security-user" not in authenticated


def test_public_request_identity_returns_stable_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = PublicAbuseController(
        _settings(
            public_rate_limit_requests=1,
            public_rate_limit_window_seconds=60,
        )
    )
    monkeypatch.setattr(api, "get_public_abuse_controller", lambda: controller)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/ask",
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("api.example", 443),
            "client": ("203.0.113.11", 1234),
        }
    )
    principal = _principal("public", authenticated=False)
    first = api.get_public_request_identity(request, principal)
    assert first.principal is principal
    with pytest.raises(HTTPException) as exc:
        api.get_public_request_identity(request, principal)
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "PUBLIC-QUERY-RATE-LIMITED"
    assert exc.value.headers == {"Retry-After": "60"}


def test_execution_gate_retains_capacity_until_timed_out_work_finishes() -> None:
    release = threading.Event()
    gate = PublicExecutionGate(max_concurrent=1, timeout_seconds=0.01)

    with pytest.raises(PublicControlError) as timeout_error:
        gate.execute(lambda: release.wait(1.0))
    assert timeout_error.value.status_code == 504
    assert timeout_error.value.code == "PUBLIC-QUERY-TIMEOUT"

    with pytest.raises(PublicControlError) as overload_error:
        gate.execute(lambda: "should not run")
    assert overload_error.value.status_code == 429
    assert overload_error.value.code == "PUBLIC-QUERY-OVERLOADED"

    release.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            assert gate.execute(lambda: "recovered") == "recovered"
            break
        except PublicControlError:
            time.sleep(0.01)
    else:
        pytest.fail("timed-out execution slot was not released")


def test_security_capabilities_expose_posture_without_origins_or_secrets() -> None:
    payload = public_product_capabilities(
        _settings(
            public_allowed_origins=(
                "https://blog.example",
                "https://docs.example",
            ),
            public_rate_limit_requests=20,
        )
    ).model_dump()
    security = payload["security"]
    assert security["anonymous_public_access"] is True
    assert security["elevated_audience_requires_authentication"] is True
    assert security["cors_mode"] == "exact_allowlist"
    assert security["allowed_origin_count"] == 2
    assert security["wildcard_origins_allowed"] is False
    assert security["cross_origin_credentials"] is False
    assert security["rate_limit_requests"] == 20
    assert security["distributed_rate_limit"] is False
    assert security["server_conversation_state"] is False
    serialized = str(payload)
    assert "blog.example" not in serialized
    assert "docs.example" not in serialized


def test_hardened_widget_omits_cross_origin_credentials() -> None:
    script = harden_public_widget_javascript(public_ask_widget_javascript())
    assert "cross-origin endpoint is disabled" not in script
    assert "const endpoint = endpointFor(this);" in script
    assert 'endpoint.origin === window.location.origin' in script
    assert '? "same-origin"' in script
    assert ': "omit"' in script
    assert 'credentials: "include"' not in script


def test_rejection_telemetry_excludes_query_token_body_and_raw_client(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="knowledge-engine.public-security")
    public_rejection_telemetry(
        reason="PUBLIC-QUERY-RATE-LIMITED",
        path="/v1/ask",
        authenticated=False,
        status_code=429,
    )
    text = caplog.text
    assert "PUBLIC-QUERY-RATE-LIMITED" in text
    assert "route_class=ask" in text
    for forbidden in (
        "secret question",
        "Bearer",
        "203.0.113.12",
        "request_body",
        "client_key",
    ):
        assert forbidden not in text
