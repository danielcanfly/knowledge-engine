from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_audit import (
    AuditHistorySnapshot,
    StaticAuditHistoryReader,
    install_admin_audit,
)
from knowledge_engine.m26_admin_contract import AuditEvent
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
    CapabilityGate,
    install_admin_control_plane,
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
        return next(
            (gate for gate in self.gates if gate.capability_id == capability_id),
            None,
        )


class ExplodingReader:
    def read(self, request):
        del request
        raise RuntimeError("private storage detail must not escape")


def audit_gate(state: str = "read_only") -> CapabilityGate:
    return CapabilityGate(
        capability_id="audit.read",
        state=state,
        reason_code="AUDIT_READ_QUALIFIED" if state == "read_only" else "AUDIT_DISABLED",
        source="test-capability-evidence",
        observed_at="2026-09-05T01:00:00Z",
    )


def make_app(*, gates=None, reader=None) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(list(gates or [])),
    )
    install_admin_audit(app, reader=reader)
    return app


def admin_headers() -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }


def event(**overrides):
    value = {
        "event_id": "admevt_1",
        "observed_at": "2026-09-05T00:59:00Z",
        "actor_id": "cfaccess:owner",
        "actor_type": "human",
        "action": "ingestion.confirm",
        "object_type": "ingestion_job",
        "object_id": "job-1",
        "request_id": "admreq_write_1",
        "operation_id": "admop_1",
        "outcome": "accepted",
        "reason_code": "INGESTION_CONFIRMED",
        "metadata": {
            "before_ref": "sha256:before",
            "after_ref": "sha256:after",
        },
    }
    value.update(overrides)
    return value


def snapshot(events, **overrides) -> AuditHistorySnapshot:
    values = {
        "events": events,
        "source": "durable-admin-audit-ledger",
        "observed_at": "2026-09-05T01:00:00Z",
        "freshness": "near_live",
        "resource_identity": {"ledger": "admin-audit-v1"},
        "evidence_digest": "a" * 64,
        "complete": True,
    }
    values.update(overrides)
    return AuditHistorySnapshot(**values)


def test_missing_capability_returns_unavailable_envelope_not_fake_empty() -> None:
    client = TestClient(make_app(reader=StaticAuditHistoryReader(snapshot([]))))
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["availability"]["reason_code"] == "ADMIN_CAPABILITY_EVIDENCE_REQUIRED"
    assert payload["observed_at"] is None
    assert payload["data"]["events"] is None
    assert payload["data"]["append_only"] is True
    assert payload["data"]["mutable"] is False


def test_disabled_capability_never_reads_history() -> None:
    client = TestClient(
        make_app(
            gates=[audit_gate("disabled")],
            reader=StaticAuditHistoryReader(snapshot([event()])),
        )
    )
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["availability"]["reason_code"] == "AUDIT_DISABLED"
    assert payload["data"]["events"] is None


def test_qualified_capability_without_durable_reader_is_unavailable() -> None:
    client = TestClient(make_app(gates=[audit_gate()]))
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    payload = response.json()
    assert response.status_code == 200
    assert payload["availability"]["status"] == "unavailable"
    assert payload["availability"]["reason_code"] == "AUDIT_HISTORY_UNAVAILABLE"
    assert payload["data"]["events"] is None


def test_available_empty_snapshot_is_authoritative_empty_history() -> None:
    client = TestClient(
        make_app(gates=[audit_gate()], reader=StaticAuditHistoryReader(snapshot([])))
    )
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    payload = response.json()
    assert response.status_code == 200
    assert payload["availability"]["status"] == "available"
    assert payload["data"]["events"] == []
    assert payload["data"]["coverage"] == {
        "complete": True,
        "returned_count": 0,
        "rejected_count": 0,
    }


def test_event_identity_and_references_are_preserved_and_secrets_redacted() -> None:
    raw = event(
        metadata={
            "before_ref": "sha256:before",
            "after_ref": "sha256:after",
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            "safe": "visible",
        }
    )
    client = TestClient(
        make_app(
            gates=[audit_gate()],
            reader=StaticAuditHistoryReader(snapshot([raw])),
        )
    )
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    payload = response.json()
    item = payload["data"]["events"][0]
    assert item["actor_id"] == "cfaccess:owner"
    assert item["request_id"] == "admreq_write_1"
    assert item["operation_id"] == "admop_1"
    assert item["before_ref"] == "sha256:before"
    assert item["after_ref"] == "sha256:after"
    assert item["metadata"]["Authorization"] == "[REDACTED]"
    assert item["metadata"]["safe"] == "visible"
    assert "abcdefghijklmnopqrstuvwxyz" not in response.text


def test_b01_audit_event_is_accepted_without_mutating_append_contract() -> None:
    raw = AuditEvent(
        event_id="admevt_2",
        observed_at="2026-09-05T00:58:00Z",
        actor_id="cfaccess:owner",
        actor_type="human",
        action="index.activate",
        object_type="index_version",
        object_id="version-2",
        request_id="admreq_write_2",
        operation_id="admop_2",
        outcome="accepted",
        reason_code="INDEX_ACTIVATION_ACCEPTED",
        metadata={"cookie": "private", "safe": "ok"},
    )
    client = TestClient(
        make_app(
            gates=[audit_gate()],
            reader=StaticAuditHistoryReader(snapshot([raw])),
        )
    )
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    item = response.json()["data"]["events"][0]
    assert item["event_id"] == "admevt_2"
    assert item["metadata"] == {"cookie": "[REDACTED]", "safe": "ok"}


def test_malformed_event_is_withheld_and_marks_snapshot_partial() -> None:
    client = TestClient(
        make_app(
            gates=[audit_gate()],
            reader=StaticAuditHistoryReader(
                snapshot([event(), {"event_id": "missing-frozen-identities"}])
            ),
        )
    )
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    payload = response.json()
    assert payload["availability"]["status"] == "partial"
    assert payload["availability"]["reason_code"] == "AUDIT_HISTORY_PARTIAL_EVIDENCE"
    assert len(payload["data"]["events"]) == 1
    assert payload["data"]["coverage"]["rejected_count"] == 1
    assert payload["data"]["coverage"]["complete"] is False


def test_reader_failure_is_fail_closed_without_private_exception_text() -> None:
    client = TestClient(make_app(gates=[audit_gate()], reader=ExplodingReader()))
    response = client.get("/v1/admin/audit-log", headers=admin_headers())
    payload = response.json()
    assert response.status_code == 200
    assert payload["availability"]["status"] == "unavailable"
    assert payload["availability"]["reason_code"] == "AUDIT_HISTORY_READ_FAILED"
    assert payload["data"]["events"] is None
    assert "private storage detail" not in response.text


def test_admin_auth_and_public_route_boundaries_are_unchanged() -> None:
    client = TestClient(
        make_app(gates=[audit_gate()], reader=StaticAuditHistoryReader(snapshot([])))
    )
    denied = client.get(
        "/v1/admin/audit-log",
        headers={"origin": "https://console.danielcanfly.com"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ADMIN_ACCESS_ASSERTION_INVALID"

    public = client.get("/v1/answers/health")
    assert public.status_code == 200
    assert public.json() == {"ok": True}
    assert "x-request-id" not in public.headers
