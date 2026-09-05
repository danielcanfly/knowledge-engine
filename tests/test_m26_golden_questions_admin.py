from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import FastAPI, Request
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
    RUNNER_UNAVAILABLE_REASON,
    StaticGoldenEvaluationProvider,
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
RELEASE = {
    "release_id": "release-b",
    "index_identity": "qdrant:collection-b@sha256:index-b",
    "config_identity": "sha256:config-b",
    "runtime_sha256": "sha256:runtime-b",
    "collection": "collection-b",
    "manifest_sha256": "sha256:manifest-b",
    "provider_id": "provider-test",
    "model_id": "model-test",
    "provider_config_hash": "sha256:provider-b",
}
DATASET = {
    "dataset_id": "representative-ask",
    "version": "2026.09.05",
    "dataset_hash": "sha256:dataset-v7",
}
SCORING = {"version": "semantic-v3", "hash": "sha256:scoring-v3"}


class FakeAuthenticator:
    def authenticate(self, assertion: str | None) -> AdminActor:
        if assertion != "valid-assertion":
            raise AdminAPIError(status_code=403, code="ADMIN_ACCESS_ASSERTION_INVALID", message="invalid")
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


def admin_headers(key: str = "p10-test-idempotency-0001") -> dict[str, str]:
    return {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
        "content-type": "application/json",
        "idempotency-key": key,
    }


def provider(*, contract_status: str = "available") -> StaticGoldenEvaluationProvider:
    contract: dict[str, Any]
    if contract_status == "available":
        contract = {"status": "available", "release": RELEASE}
    else:
        contract = {"status": "blocked", "reason_code": "RUN_TARGET_NOT_QUALIFIED"}
    golden = {
        "source": "fixture_registry",
        "observed_at": "2026-09-05T00:00:00Z",
        "freshness": "snapshot",
        "evidence_digest": "sha256:golden",
        "resource_identity": {"registry_revision": "golden-r7"},
        "run_request_contract": contract,
        "sets": [
            {
                **DATASET,
                "state": "active",
                "scoring_contract": {**SCORING, "metrics": ["faithfulness", "completeness"]},
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
                "dataset": DATASET,
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
                    {"case_id": "gq-001", "state": "pass", "metrics": {"faithfulness": 1.0}},
                    {
                        "case_id": "gq-002",
                        "state": "error",
                        "error": {"code": "PROVIDER_UNAVAILABLE", "retryable": True},
                        "metrics": {},
                    },
                ],
            }
        ],
    }
    return StaticGoldenEvaluationProvider(golden=golden, runs=runs)


class InertAcceptedRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[Mapping[str, Any]] = []

    def start_run(
        self, request: Request, *, operation_id: str, run_request: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del request
        self.calls += 1
        self.requests.append(dict(run_request))
        case_ids = list(run_request.get("case_ids", []))
        return {
            "run_id": operation_id,
            "state": "pass",
            "mode": run_request["mode"],
            "dataset": run_request["dataset"],
            "release": run_request["release"],
            "scoring_contract": {**run_request["scoring_contract"], "metrics": ["faithfulness"]},
            "created_at": "2026-09-05T00:02:00Z",
            "completed_at": "2026-09-05T00:02:01Z",
            "progress": {"completed": len(case_ids), "total": len(case_ids)},
            "summary": {"pass": len(case_ids), "fail": 0, "error": 0},
            "case_results": [
                {"case_id": case_id, "state": "pass", "metrics": {"faithfulness": 1.0}}
                for case_id in case_ids
            ],
        }


def run_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "selected",
        "dataset": DATASET,
        "case_ids": ["gq-001"],
        "release": RELEASE,
        "scoring_contract": SCORING,
    }
    payload.update(overrides)
    return payload


def make_app(
    *,
    start_state: str = "enabled",
    runner: Any | None = None,
    contract_status: str = "available",
) -> FastAPI:
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
    install_golden_questions_admin(app, provider=provider(contract_status=contract_status), runner=runner)
    return app


def test_openapi_requires_typed_immutable_run_body() -> None:
    post = make_app().openapi()["paths"]["/v1/admin/evaluations/runs"]["post"]
    assert post["operationId"] == "startEvaluationRun"
    assert post["requestBody"]["required"] is True
    schema = post["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/StartEvaluationRunRequest")


def test_missing_or_malformed_immutable_identities_fail_closed() -> None:
    client = TestClient(make_app())
    assert client.post("/v1/admin/evaluations/runs", headers=admin_headers(), json={}).status_code == 422
    malformed = run_request(release={"release_id": "release-b"})
    response = client.post("/v1/admin/evaluations/runs", headers=admin_headers(), json=malformed)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ADMIN_REQUEST_VALIDATION_FAILED"


def test_selected_mode_requires_explicit_non_empty_case_ids() -> None:
    response = TestClient(make_app()).post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request(case_ids=[])
    )
    assert response.status_code == 422


def test_capability_not_mutation_authorized_fails_before_runner() -> None:
    runner = InertAcceptedRunner()
    response = TestClient(make_app(start_state="read_only", runner=runner)).post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request()
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TEST_QUALIFIED"
    assert runner.calls == 0


def test_blocked_run_contract_fails_closed_before_runner_and_audits() -> None:
    runner = InertAcceptedRunner()
    app = make_app(runner=runner, contract_status="blocked")
    response = TestClient(app).post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request()
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_TARGET_NOT_QUALIFIED"
    assert runner.calls == 0
    assert app.state.admin_audit_sink.events[-1].reason_code == "RUN_TARGET_NOT_QUALIFIED"


def test_unavailable_runner_never_creates_fake_run() -> None:
    app = make_app()
    client = TestClient(app)
    before = client.get("/v1/admin/evaluations/runs", headers=admin_headers()).json()["data"]["runs"]
    response = client.post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request()
    )
    after = client.get("/v1/admin/evaluations/runs", headers=admin_headers()).json()["data"]["runs"]
    assert response.status_code == 503
    assert response.json()["error"]["code"] == RUNNER_UNAVAILABLE_REASON
    assert [run["run_id"] for run in after] == [run["run_id"] for run in before]


def test_inert_accepted_runner_preserves_identity_readback_replay_and_audit() -> None:
    runner = InertAcceptedRunner()
    app = make_app(runner=runner)
    client = TestClient(app)
    first = client.post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request()
    )
    assert first.status_code == 202
    operation_id = first.json()["operation_id"]
    assert first.json()["replayed"] is False
    replay = client.post(
        "/v1/admin/evaluations/runs", headers=admin_headers(), json=run_request()
    )
    assert replay.status_code == 202
    assert replay.json()["operation_id"] == operation_id
    assert replay.json()["replayed"] is True
    assert runner.calls == 1
    runs = client.get("/v1/admin/evaluations/runs", headers=admin_headers()).json()["data"]["runs"]
    accepted = next(run for run in runs if run["run_id"] == operation_id)
    assert accepted["dataset"] == DATASET
    assert accepted["release"] == RELEASE
    assert accepted["scoring_contract"]["version"] == SCORING["version"]
    assert accepted["scoring_contract"]["hash"] == SCORING["hash"]
    events = app.state.admin_audit_sink.events
    accepted_event = next(event for event in events if event.action == "evaluation.run.start.accepted")
    assert accepted_event.actor_id == OWNER.actor_id
    assert accepted_event.request_id.startswith("admreq_")
    assert accepted_event.operation_id == operation_id
    assert "valid-assertion" not in str(accepted_event.to_payload())


def test_same_idempotency_key_with_changed_normalized_request_conflicts() -> None:
    runner = InertAcceptedRunner()
    app = make_app(runner=runner)
    client = TestClient(app)
    key_headers = admin_headers("p10-test-idempotency-0009")
    assert client.post("/v1/admin/evaluations/runs", headers=key_headers, json=run_request()).status_code == 202
    changed = run_request(case_ids=["gq-002"])
    response = client.post("/v1/admin/evaluations/runs", headers=key_headers, json=changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ADMIN_IDEMPOTENCY_CONFLICT"
    assert runner.calls == 1


def test_authority_mismatch_rejects_unknown_case_release_and_scoring() -> None:
    client = TestClient(make_app(runner=InertAcceptedRunner()))
    unknown_case = client.post(
        "/v1/admin/evaluations/runs",
        headers=admin_headers("p10-authority-case-001"),
        json=run_request(case_ids=["missing-case"]),
    )
    assert unknown_case.status_code == 409
    assert unknown_case.json()["error"]["code"] == "GOLDEN_CASE_SELECTION_MISMATCH"
    bad_release = {**RELEASE, "manifest_sha256": "sha256:wrong"}
    release = client.post(
        "/v1/admin/evaluations/runs",
        headers=admin_headers("p10-authority-release-01"),
        json=run_request(release=bad_release),
    )
    assert release.status_code == 409
    assert release.json()["error"]["code"] == "GOLDEN_RELEASE_IDENTITY_MISMATCH"
    scoring = client.post(
        "/v1/admin/evaluations/runs",
        headers=admin_headers("p10-authority-score-001"),
        json=run_request(scoring_contract={"version": "semantic-v2", "hash": "sha256:scoring-v2"}),
    )
    assert scoring.status_code == 409
    assert scoring.json()["error"]["code"] == "GOLDEN_SCORING_CONTRACT_MISMATCH"


def test_historical_scoring_identity_and_public_health_remain_unchanged() -> None:
    app = make_app(runner=InertAcceptedRunner())
    client = TestClient(app)
    runs = client.get("/v1/admin/evaluations/runs", headers=admin_headers()).json()["data"]["runs"]
    assert runs[0]["scoring_contract"] == {
        "version": "semantic-v2",
        "hash": "sha256:scoring-v2",
        "metrics": ["faithfulness"],
    }
    response = client.get("/v1/answers/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "x-request-id" not in response.headers
