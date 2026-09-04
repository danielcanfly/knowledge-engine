from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
    CapabilityGate,
    InMemoryIdempotencyStore,
    install_admin_control_plane,
)
from knowledge_engine.m26_suggested_questions_admin import (
    SuggestedQuestionsSnapshot,
    install_suggested_questions_admin,
    parse_homepage_question_source,
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
            raise AdminAPIError(status_code=403, code="ADMIN_ACCESS_ASSERTION_INVALID", message="invalid")
        return OWNER


@dataclass
class StaticCapabilities:
    gates: list[CapabilityGate]

    def list_capabilities(self) -> list[CapabilityGate]:
        return list(self.gates)

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return next((gate for gate in self.gates if gate.capability_id == capability_id), None)


class FakeSource:
    repository = "danielcanfly/daniel-blog"
    source_path = "src/data/m26-home-suggested-questions.mjs"
    source_ref = "main"

    def read(self) -> SuggestedQuestionsSnapshot:
        return SuggestedQuestionsSnapshot(
            repository=self.repository,
            source_path=self.source_path,
            source_ref=self.source_ref,
            content_blob_sha="blob123",
            observed_repo_commit="commit123",
            questions=("What is an LLM wiki?", "Why do agents need a harness?"),
            observed_at="2026-09-04T14:35:00Z",
        )


def headers(**extra: str) -> dict[str, str]:
    value = {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
    }
    value.update(extra)
    return value


def make_app(*, publish_enabled: bool = False) -> FastAPI:
    app = FastAPI()
    gates = []
    if publish_enabled:
        gates.append(
            CapabilityGate(
                capability_id="suggested_questions.publish",
                state="enabled",
                reason_code="TEST_QUALIFIED",
                source="test",
            )
        )
    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(gates),
        idempotency_store=InMemoryIdempotencyStore(),
    )
    install_suggested_questions_admin(app, source=FakeSource())
    return app


def test_parser_reads_frozen_homepage_array_without_inventing_metadata() -> None:
    source = """export const M26_HOME_SUGGESTED_QUESTIONS = Object.freeze([\n  'One?',\n  'Two?',\n]);\n"""
    assert parse_homepage_question_source(source) == ("One?", "Two?")


def test_get_projects_git_source_into_canonical_read_envelope() -> None:
    response = TestClient(make_app()).get("/v1/admin/suggested-questions", headers=headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"]["status"] == "available"
    assert payload["provenance"]["source"] == "github_repository_read_projection"
    assert payload["observed_at"] == "2026-09-04T14:35:00Z"
    assert payload["freshness"] == "live"
    assert payload["data"]["publication"]["revision"] == "github-blob:blob123"
    assert payload["data"]["publication"]["write_authority"] == "unselected"
    assert payload["data"]["publication"]["question_count"] == 2
    assert [item["state"] for item in payload["data"]["questions"]] == ["published", "published"]
    assert all(item["category"] is None and item["tags"] == [] for item in payload["data"]["questions"])


def test_put_is_fail_closed_when_publish_capability_is_missing() -> None:
    response = TestClient(make_app()).put(
        "/v1/admin/suggested-questions",
        headers=headers(**{"content-type": "application/json", "idempotency-key": "p06-missing-gate-0001"}),
        json={"base_revision": "github-blob:blob123", "operations": []},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ADMIN_CAPABILITY_EVIDENCE_REQUIRED"


def test_put_still_blocks_when_capability_is_enabled_but_write_authority_is_unselected() -> None:
    response = TestClient(make_app(publish_enabled=True)).put(
        "/v1/admin/suggested-questions",
        headers=headers(**{"content-type": "application/json", "idempotency-key": "p06-write-authority-01"}),
        json={"base_revision": "github-blob:blob123", "operations": [{"op": "disable", "id": "sq_1"}]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUGGESTED_QUESTIONS_WRITE_AUTHORITY_UNSELECTED"
