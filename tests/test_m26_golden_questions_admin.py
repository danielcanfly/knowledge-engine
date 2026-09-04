from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
    CapabilityGate,
    InMemoryAuditSink,
    InMemoryIdempotencyStore,
    install_admin_control_plane,
)
from knowledge_engine.m26_golden_questions_admin import (
    RUN_REQUEST_SCHEMA_REASON,
    StaticGoldenEvaluationProvider,
    UnavailableGoldenEvaluationProvider,
    install_golden_questions_admin,
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


def gate(capability_id: str, state: str) -> CapabilityGate:
    return CapabilityGate(
        capability_id=capability_id,
        state=state,
        reason_code="TEST_QUALIFIED",
        source="test",
        observed_at="2026-09-05T00:00:00Z",
        evidence_digest="sha256:test",
    )


def admin_headers(**extra: str) -> dict[str, str]:
    headers = {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }
    headers.update(extra)
    return headers


def provider() -> StaticGoldenEvaluationProvider:
    golden = {
        "source": "fixture_registry",
        "observed_at": "2026-09-05T00:00:00Z",
        "freshness": "snapshot",
        "evidence_digest": "sha256:golden",
        "resource_identity": {"registry_revision": "golden-r7"},
        "sets": [
            {
                "dataset_id": "representative-ask",
                "version": "2026.09.05",
                "dataset_hash": "sha256:dataset-v7",
                "state": "active",
                "scoring_contract": {
                    "version": "semantic-v3",
                    "hash": "sha256:scoring-v3",
                    "metrics": ["faithfulness", "completeness", "contradiction"],
                },
                "cases": [
                    {
                        "case_id": "gq-001",
                        "question": "What is the retrieval contract?",
                        "expectation_hash": "sha256:exp-1",
                        "expected_source_ids": ["post-a"],
                        "expected_traits": ["grounded", "cited"],
                        "tags": ["retrieval"],
                    },
                    {
                        "case_id": "gq-002",
                        "question": "How is an outage classified?",
                        "expectation_hash": "sha256:exp-2",
                        "expected_source_ids": [],
                        "expected_traits": ["error-not-quality-fail"],
                    },
                ],
            }
        ],
    }
    runs = {
        "source": "fixture_run_ledger",
        "observed_at": "2026-09-05T00:01:00Z",
        "freshness": "snapshot",
        "evidence_digest": "sha256:runs",
        "resource_identity": {"ledger_revision": "run-r12"},
        "runs": [
            {
                "run_id": "run-old",
                "state": "warn",
                "mode": "all",
                "dataset": {
                    "dataset_id": "representative-ask",
                    "version": "2026.09.05",
                    "dataset_hash": "sha256:dataset-v7",
                },
                "release": {
                    "release_id": "release-a",
                    "index_identity": "qdrant:collection-a@sha256:index-a",
                    "config_identity": "sha256:config-a",
                    "provider_config_hash": "sha256:provider-a",
                },
                "scoring_contract": {
                    "version": "semantic-v2",
                    "hash": "sha256:scoring-v2",
                    "metrics": ["faithfulness"],
                },
                "created_at": "2026-09-04T23:00:00Z",
                "completed_at": "2026-09-04T23:01:00Z",
                "progress": {"completed": 2, "total": 2},
                "summary": {"pass": 1, "fail": 0, "error": 1},
                "case_results": [
                    {
                        "case_id": "gq-001",
                        "state": "pass",
                        "answer": "Grounded answer",
                        "metrics": {"faithfulness": 1.0},
                        "trace_id": "trace-old-1",
                    },
                    {
                        "case_id": "gq-002",
                        "state": "error",
                        "error": {"code": "PROVIDER_UNAVAILABLE", "retryable": True},
                        "metrics": {},
                        "trace_id": "trace-old-2",
                    },
                ],
            },
            {
                "run_id": "run-new",
                "state": "pass",
                "mode": "selected",
                "dataset": {
                    "dataset_id": "representative-ask",
                    "version": "2026.09.05",
                    "dataset_hash": "sha256:dataset-v7",
                },
                "release": {
                    "release_id": "release-b",
                    "index_identity": "qdrant:collection-b@sha256:index-b",
                    "config_identity": "sha256:config-b",
                    "provider_config_hash": "sha256:provider-b",
                },
                "scoring_contract": {
                    "version": "semantic-v3",
                    "hash": "sha256:scoring-v3",
                    "metrics": ["faithfulness", "completeness"],
                },
                "created_at": "2026-09-05T00:00:00Z",
                "completed_at": "2026-09-05T00:00:30Z",
                "progress": {"completed": 1, "total": 1},
                "summary": {"pass": 1, "fail": 0, "error": 0},
                "case_results": [
                    {
                        "case_id": "gq-001",
                        "state": "pass",
                        "answer": "New grounded answer",
                        "retrieval": {"source_ids": ["post-a"]},
                        "evidence": {"citation_ids": ["post-a"]},
                        "metrics": {"faithfulness": 1.0, "completeness": 1.0},
                        "trace_id": "trace-new-1",
                    }
                ],
            },
        ],
    }
    return StaticGoldenEvaluationProvider(golden=golden, runs=runs)


def make_app(*, start_state: str = "disabled", use_provider: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/answers/health")
    async def public_health() -> dict[str, bool]:
        return {"ok": True}

    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(
            [
                gate("evaluation.golden.read", "read_only"),
                gate("evaluation.runs.read", "read_only"),
                gate("evaluation.run.start", start_state),
            ]
        ),
        audit_sink=InMemoryAuditSink(),
        idempotency_store=InMemoryIdempotencyStore(),
    )
    install_golden_questions_admin(
        app,
        provider=provider() if use_provider else UnavailableGoldenEvaluationProvider(),
    )
    return app


def test_golden_read_preserves_versioned_dataset_and_expectation_identity() -> None:
    response = TestClient(make_app()).get("/v1/admin/evaluations/golden", headers=admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "available"
    dataset = payload["data"]["sets"][0]
    assert dataset["dataset_id"] == "representative-ask"
    assert dataset["version"] == "2026.09.05"
    assert dataset["dataset_hash"] == "sha256:dataset-v7"
    assert dataset["cases"][0]["expectation_hash"] == "sha256:exp-1"
    assert dataset["scoring_contract"]["hash"] == "sha256:scoring-v3"
    assert "min_score" not in str(payload).lower()
    assert "85" not in str(payload)


def test_run_history_keeps_exact_identity_and_infra_error_distinct_from_quality_fail() -> None:
    response = TestClient(make_app()).get("/v1/admin/evaluations/runs", headers=admin_headers())
    assert response.status_code == 200
    runs = response.json()["data"]["runs"]
    old, new = runs
    assert old["release"]["index_identity"] == "qdrant:collection-a@sha256:index-a"
    assert new["release"]["config_identity"] == "sha256:config-b"
    assert old["case_results"][1]["state"] == "error"
    assert old["case_results"][1]["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert old["summary"]["fail"] == 0
    assert old["summary"]["error"] == 1


def test_historical_scoring_contract_is_not_overwritten_by_newer_run() -> None:
    runs = (
        TestClient(make_app())
        .get("/v1/admin/evaluations/runs", headers=admin_headers())
        .json()["data"]["runs"]
    )
    assert runs[0]["scoring_contract"] == {
        "version": "semantic-v2",
        "hash": "sha256:scoring-v2",
        "metrics": ["faithfulness"],
    }
    assert runs[1]["scoring_contract"]["version"] == "semantic-v3"


def test_missing_provider_is_unavailable_not_fabricated_empty_observation() -> None:
    response = TestClient(make_app(use_provider=False)).get(
        "/v1/admin/evaluations/golden", headers=admin_headers()
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "unavailable"
    assert payload["observed_at"] is None
    assert payload["freshness"] == "unknown"
    assert payload["data"]["sets"] == []


def test_run_start_fails_closed_when_capability_is_not_mutation_authorized() -> None:
    response = TestClient(make_app(start_state="read_only")).post(
        "/v1/admin/evaluations/runs",
        headers=admin_headers(
            **{
                "content-type": "application/json",
                "idempotency-key": "p10-test-idempotency-0001",
            }
        ),
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TEST_QUALIFIED"


def test_enabled_run_is_blocked_by_missing_request_schema_and_audited() -> None:
    app = make_app(start_state="enabled")
    client = TestClient(app)
    response = client.post(
        "/v1/admin/evaluations/runs",
        headers=admin_headers(
            **{
                "content-type": "application/json",
                "idempotency-key": "p10-test-idempotency-0002",
            }
        ),
        json={},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == RUN_REQUEST_SCHEMA_REASON
    events = app.state.admin_audit_sink.events
    assert len(events) == 1
    assert events[0].action == "evaluation.run.start.blocked"
    assert events[0].reason_code == RUN_REQUEST_SCHEMA_REASON


def test_openapi_keeps_frozen_no_body_shape_instead_of_inventing_page_private_schema() -> None:
    schema = make_app().openapi()
    post = schema["paths"]["/v1/admin/evaluations/runs"]["post"]
    assert post["operationId"] == "startEvaluationRun"
    assert "requestBody" not in post
    golden_get = schema["paths"]["/v1/admin/evaluations/golden"]["get"]
    runs_get = schema["paths"]["/v1/admin/evaluations/runs"]["get"]
    assert golden_get["operationId"] == "listGoldenSets"
    assert runs_get["operationId"] == "listEvaluationRuns"


def test_public_health_is_not_wrapped_or_gated_by_admin_changes() -> None:
    response = TestClient(make_app()).get("/v1/answers/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "x-request-id" not in response.headers
