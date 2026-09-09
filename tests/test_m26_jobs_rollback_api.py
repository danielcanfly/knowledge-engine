from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_contract import AdminActor, AdminAPIError
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    InMemoryIdempotencyStore,
    install_admin_control_plane,
)
from knowledge_engine.m26_jobs_rollback_api import (
    EvidenceObservation,
    install_jobs_rollback_routes,
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
        if assertion != "valid-owner":
            raise AdminAPIError(
                status_code=403,
                code="ADMIN_ACTOR_NOT_OWNER",
                message="owner access required",
            )
        return OWNER


class EvidenceProvider:
    def list_jobs(self) -> EvidenceObservation:
        return EvidenceObservation(
            availability_status="available",
            reason_code=None,
            detail=None,
            source="test.job-manifest",
            data={
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "completed",
                        "operation_id": "op-1",
                        "evidence_digest": "a" * 64,
                    }
                ]
            },
            observed_at="2026-09-04T12:00:00Z",
            freshness="snapshot",
            resource_identity={"manifest": "jobs-v1"},
            evidence_digest="b" * 64,
            source_observed_at="2026-09-04T12:00:00Z",
        )

    def get_job(self, job_id: str) -> EvidenceObservation:
        if job_id != "job-1":
            return EvidenceObservation(
                availability_status="unavailable",
                reason_code="JOB_EVIDENCE_NOT_FOUND",
                detail="No authoritative evidence exists for the requested job id.",
                source="test.job-manifest",
                data=None,
            )
        return EvidenceObservation(
            availability_status="available",
            reason_code=None,
            detail=None,
            source="test.job-manifest",
            data={"job_id": job_id, "status": "completed"},
            observed_at="2026-09-04T12:00:00Z",
            freshness="snapshot",
            evidence_digest="c" * 64,
        )

    def list_versions(self) -> EvidenceObservation:
        return EvidenceObservation(
            availability_status="partial",
            reason_code="PRODUCTION_POINTER_UNQUALIFIED",
            detail="Lineage evidence exists, but production pointer authority is unqualified.",
            source="test.release-manifest",
            data={
                "versions": [
                    {
                        "version_id": "v1",
                        "lineage_state": "previous",
                        "immutable_target": "bundle-1",
                        "evidence_digest": "d" * 64,
                        "eligibility": "unknown",
                    }
                ]
            },
            observed_at="2026-09-04T12:00:00Z",
            freshness="snapshot",
        )


def make_app(*, evidence_provider=None) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        idempotency_store=InMemoryIdempotencyStore(),
    )
    install_jobs_rollback_routes(app, evidence_provider=evidence_provider)
    return app


def admin_headers(**extra: str) -> dict[str, str]:
    headers = {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-owner",
    }
    headers.update(extra)
    return headers


def mutation_headers(**extra: str) -> dict[str, str]:
    return admin_headers(
        **{
            "content-type": "application/json",
            "idempotency-key": "p09-test-key-0001",
            **extra,
        }
    )


def test_default_reads_are_truthfully_unavailable_not_synthetic_empty() -> None:
    client = TestClient(make_app())

    for path in (
        "/v1/admin/ingestion/jobs",
        "/v1/admin/ingestion/jobs/unknown-job",
        "/v1/admin/index/versions",
    ):
        response = client.get(path, headers=admin_headers())
        assert response.status_code == 200
        payload = response.json()
        assert payload["availability"]["status"] == "unavailable"
        assert payload["availability"]["reason_code"] == (
            "P09_AUTHORITATIVE_EVIDENCE_SOURCE_UNAVAILABLE"
        )
        assert payload["provenance"]["source"] == "p09_jobs_rollback.unconfigured"
        assert payload["observed_at"] is None
        assert payload["freshness"] == "unknown"
        assert payload["data"] is None
        assert response.headers["x-request-id"] == payload["request_id"]


def test_injected_evidence_preserves_observation_and_partial_semantics() -> None:
    client = TestClient(make_app(evidence_provider=EvidenceProvider()))

    jobs = client.get("/v1/admin/ingestion/jobs", headers=admin_headers()).json()
    assert jobs["availability"]["status"] == "available"
    assert jobs["observed_at"] == "2026-09-04T12:00:00Z"
    assert jobs["provenance"]["source"] == "test.job-manifest"
    assert jobs["provenance"]["resource_identity"] == {"manifest": "jobs-v1"}
    assert jobs["data"]["jobs"][0]["job_id"] == "job-1"

    versions = client.get("/v1/admin/index/versions", headers=admin_headers()).json()
    assert versions["availability"]["status"] == "partial"
    assert versions["availability"]["reason_code"] == "PRODUCTION_POINTER_UNQUALIFIED"
    assert versions["data"]["versions"][0]["eligibility"] == "unknown"


def test_unknown_job_is_not_inferred_from_request_identity() -> None:
    client = TestClient(make_app(evidence_provider=EvidenceProvider()))
    response = client.get("/v1/admin/ingestion/jobs/job-404", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["data"] is None
    assert payload["observed_at"] is None


def test_preflight_is_exact_target_zero_write_and_never_issues_token() -> None:
    client = TestClient(make_app(evidence_provider=EvidenceProvider()))
    response = client.post(
        "/v1/admin/index/versions/v1/rollback-preflight",
        headers=mutation_headers(),
        content=b"",
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["data"]["version_id"] == "v1"
    assert payload["data"]["eligibility"] == "not_eligible"
    assert payload["data"]["preflight_token"] is None
    assert payload["data"]["write_attempts"] == 0
    capability = payload["data"]["activation_capability"]
    assert capability["qualification_status"] == "unavailable"
    assert capability["effective_state"] == "unavailable"
    assert capability["mutation_authorized"] is False


def test_preflight_still_requires_transport_idempotency_gate() -> None:
    client = TestClient(make_app())
    response = client.post(
        "/v1/admin/index/versions/v1/rollback-preflight",
        headers=admin_headers(**{"content-type": "application/json"}),
        content=b"",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ADMIN_IDEMPOTENCY_KEY_INVALID"


def test_activate_validates_request_then_fails_closed_without_actuator() -> None:
    client = TestClient(make_app())

    malformed = client.post(
        "/v1/admin/index/versions/v1/activate",
        headers=mutation_headers(),
        json={"preflight_token": "token-but-no-confirmation"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "ADMIN_REQUEST_VALIDATION_FAILED"

    response = client.post(
        "/v1/admin/index/versions/v1/activate",
        headers=mutation_headers(),
        json={"preflight_token": "preflight-token", "confirmation": True},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "P09_PRODUCTION_POINTER_ACTUATOR_UNAVAILABLE"
    assert payload["error"]["details"]["mutation_authorized"] is False
    assert "operation_id" not in payload


def test_unauthorized_requests_reveal_no_p09_state_and_public_api_is_untouched() -> None:
    client = TestClient(make_app(evidence_provider=EvidenceProvider()))

    denied = client.get(
        "/v1/admin/index/versions",
        headers={
            "origin": "https://console.danielcanfly.com",
            ACCESS_ASSERTION_HEADER: "not-owner",
        },
    )
    assert denied.status_code == 403
    payload = denied.json()
    assert payload["error"]["code"] == "ADMIN_ACTOR_NOT_OWNER"
    assert "availability" not in payload
    assert "provenance" not in payload
    assert "data" not in payload

    public = client.get("/v1/answers/health")
    assert public.status_code == 200
    assert public.json() == {"ok": True}
    assert "x-request-id" not in public.headers
