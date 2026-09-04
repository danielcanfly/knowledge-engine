from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminActor, AdminAPIError, CapabilityGate
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    install_admin_control_plane,
)
from knowledge_engine.m26_admin_settings import (
    CANONICAL_ADMIN_API_VERSION,
    CANONICAL_ADMIN_OPENAPI_SHA256,
    canonicalize_capability,
    install_admin_settings,
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
    gates: list[object]

    def list_capabilities(self) -> list[object]:
        return list(self.gates)

    def get_capability(self, capability_id: str) -> object | None:
        for gate in self.gates:
            payload = gate if isinstance(gate, dict) else gate.to_payload()
            if payload.get("capability_id") == capability_id:
                return gate
        return None


def make_app(gates: list[object] | None = None) -> FastAPI:
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(gates or []),
    )
    install_admin_settings(app)
    return app


def admin_headers() -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }


def test_settings_requires_owner_auth_and_is_get_only() -> None:
    client = TestClient(make_app())

    denied = client.get(
        "/v1/admin/settings",
        headers={"origin": "https://console.danielcanfly.com"},
    )
    assert denied.status_code == 403

    allowed = client.get("/v1/admin/settings", headers=admin_headers())
    assert allowed.status_code == 200

    mutation = client.post(
        "/v1/admin/settings",
        headers={**admin_headers(), "content-type": "application/json"},
        json={"enabled": True},
    )
    assert mutation.status_code == 405


def test_settings_returns_canonical_contract_and_read_semantics() -> None:
    client = TestClient(make_app())
    payload = client.get("/v1/admin/settings", headers=admin_headers()).json()

    assert payload["availability"]["status"] == "available"
    assert payload["freshness"] == "live"
    assert payload["provenance"]["source"] == "admin_settings_adapter"
    assert payload["data"]["contract"] == {
        "name": "M26 LLM-Wiki Admin API",
        "version": CANONICAL_ADMIN_API_VERSION,
        "openapi_sha256": CANONICAL_ADMIN_OPENAPI_SHA256,
    }
    assert payload["data"]["preferences"]["supported"] is False
    assert payload["data"]["preferences"]["mutation_authorized"] is False


def test_settings_only_exposes_configuration_presence(monkeypatch) -> None:
    secret_markers = {
        "M26_CONSOLE_ACCESS_TEAM_DOMAIN": "https://private.cloudflareaccess.com",
        "M26_CONSOLE_ACCESS_AUD": "super-secret-audience",
        "M26_CONSOLE_OWNER_EMAILS": "owner-secret@example.com",
        "M26_CONSOLE_OWNER_SUBJECTS": "subject-secret-value",
    }
    for key, value in secret_markers.items():
        monkeypatch.setenv(key, value)

    client = TestClient(make_app())
    payload = client.get("/v1/admin/settings", headers=admin_headers()).json()
    serialized = json.dumps(payload, sort_keys=True)

    for value in secret_markers.values():
        assert value not in serialized

    configured = {item["key"]: item["configured"] for item in payload["data"]["configuration"]}
    assert configured == {
        "cloudflare_access_team_domain": True,
        "cloudflare_access_audience": True,
        "owner_allowlist": True,
    }


def test_legacy_enabled_gate_is_not_promoted_to_mutation_authority() -> None:
    legacy = CapabilityGate(
        capability_id="index.activate",
        state="enabled",
        reason_code="LEGACY_ENABLED",
        source="legacy-test",
    )
    mapped = canonicalize_capability(legacy)

    assert mapped["qualification_status"] == "qualification_candidate"
    assert mapped["effective_state"] == "disabled"
    assert mapped["mutation_authorized"] is False
    assert mapped["reason_code"] == "ADMIN_CAPABILITY_REQUALIFICATION_REQUIRED"


def test_canonical_capability_mapping_preserves_only_qualified_mutation() -> None:
    canonical = {
        "capability_id": "index.activate",
        "qualification_status": "qualified",
        "effective_state": "enabled",
        "mutation_authorized": True,
        "reason_code": "QUALIFIED",
        "source": "b03-test",
    }
    blocked = {
        "capability_id": "index.activate",
        "qualification_status": "blocked_authority",
        "effective_state": "enabled",
        "mutation_authorized": True,
        "reason_code": "AUTHORITY_BLOCKED",
        "source": "b03-test",
    }

    assert canonicalize_capability(canonical)["mutation_authorized"] is True
    blocked_mapped = canonicalize_capability(blocked)
    assert blocked_mapped["effective_state"] == "unavailable"
    assert blocked_mapped["mutation_authorized"] is False


def test_missing_capability_policy_fails_closed() -> None:
    client = TestClient(make_app())
    default = client.get("/v1/admin/settings", headers=admin_headers()).json()["data"][
        "capability_policy"
    ]["default_when_missing"]

    assert default == {
        "qualification_status": "unavailable",
        "effective_state": "unavailable",
        "mutation_authorized": False,
        "reason_code": "ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
    }
