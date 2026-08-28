from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.auth import Authenticator, Principal
from knowledge_engine.m26_translation_gateway_public_api import (
    create_app,
)


@pytest.fixture
def staging_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AUTH_MODE", "supabase_jwt")
    monkeypatch.setenv(
        "JWT_ISSUER",
        "https://votyiqqxkpiurwqshylx.supabase.co/auth/v1",
    )
    monkeypatch.setenv(
        "JWT_JWKS_URL",
        "https://votyiqqxkpiurwqshylx.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setenv("JWT_AUDIENCE", "authenticated")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv(
        "M26_PUBLIC_ALLOWED_ORIGINS",
        "https://staging.danielcanfly.com",
    )
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")
    app = create_app(root=Path("."), translation_provider=object())
    with TestClient(app) as client:
        yield client


def test_staging_answers_reject_missing_auth_before_body(
    staging_client: TestClient,
) -> None:
    response = staging_client.post(
        "/v1/answers",
        headers={"origin": "https://staging.danielcanfly.com"},
        content=b"{",
    )

    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "M26_STAGING_QUALIFICATION_MISSING"


def test_staging_answers_forward_authenticated_requests_with_public_request_false(
    staging_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_authenticate(self: Authenticator, authorization: str | None) -> Principal:
        observed["authorization"] = authorization
        return Principal(
            subject="staging-test-user",
            audiences=frozenset({"authenticated", "public"}),
            claims={"sub": "staging-test-user"},
        )

    def fake_run_owner_translation_gateway_for_web(**kwargs: Any) -> dict[str, Any]:
        observed["run_kwargs"] = kwargs
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

    monkeypatch.setattr(Authenticator, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        "knowledge_engine.m26_translation_gateway_public_api.run_owner_translation_gateway_for_web",
        fake_run_owner_translation_gateway_for_web,
    )

    response = staging_client.post(
        "/v1/answers",
        headers={
            "origin": "https://staging.danielcanfly.com",
            "authorization": "Bearer staging-token",
        },
        json={"question": "What is safe?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: answer" in response.text
    assert observed["authorization"] == "Bearer staging-token"
    assert observed["run_kwargs"]["public_request"] is False
    assert observed["run_kwargs"]["request_payload"] == {"question": "What is safe?"}
    assert observed["run_kwargs"]["owner_subject_hash"] == "owner-hash"


def test_staging_answers_reject_browser_asserted_owner_fields(
    staging_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_authenticate(self: Authenticator, authorization: str | None) -> Principal:
        return Principal(
            subject="staging-test-user",
            audiences=frozenset({"authenticated"}),
            claims={"sub": "staging-test-user"},
        )

    monkeypatch.setattr(Authenticator, "authenticate", fake_authenticate)

    response = staging_client.post(
        "/v1/answers",
        headers={
            "origin": "https://staging.danielcanfly.com",
            "authorization": "Bearer staging-token",
        },
        json={
            "question": "What is safe?",
            "public_request": True,
            "owner_subject_hash": "attacker",
            "owner": "attacker",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["reason_code"] == "M26_TG_REQUEST_FIELD_DENIED"


def test_staging_answers_preflight_allows_authorization(
    staging_client: TestClient,
) -> None:
    response = staging_client.options(
        "/v1/answers",
        headers={
            "origin": "https://staging.danielcanfly.com",
            "access-control-request-method": "POST",
            "access-control-request-headers": "authorization,content-type",
        },
    )

    assert response.status_code in {200, 204}
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
