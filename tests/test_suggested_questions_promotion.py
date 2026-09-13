from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.m26_admin_control_plane import (
    ACCESS_ASSERTION_HEADER,
    AdminActor,
    AdminAPIError,
    CapabilityGate,
    InMemoryAuditSink,
    InMemoryIdempotencyStore,
    install_admin_control_plane,
)
from knowledge_engine.m26_suggested_questions_admin import (
    SuggestedQuestionsSnapshot,
    install_suggested_questions_admin,
)
from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    ANSWER_QUALITY_RUBRIC_VERSION,
    AnswerQualityEvaluation,
    StaticAnswerQualityEvaluator,
)
from knowledge_engine.storage import FileObjectStore
from knowledge_engine.suggested_questions_promotion import (
    ObjectStoreSuggestedQuestionsPromotionStore,
    SuggestedQuestionsPromotionError,
    build_promotion_preview,
    publish_promotion,
)
from knowledge_engine.suggested_questions_scoring import (
    SUGGESTED_QUESTIONS_CRITERION_MAX,
    SUGGESTED_QUESTIONS_RUBRIC_VERSION,
    SUGGESTED_QUESTIONS_THRESHOLD,
    StaticSuggestedQuestionsEvaluator,
    SuggestedQuestionsEvaluation,
    deterministic_hard_fail_codes,
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
            raise AdminAPIError(status_code=403, code="DENIED", message="invalid")
        return OWNER


@dataclass
class StaticCapabilities:
    enabled: bool = True

    def list_capabilities(self) -> list[CapabilityGate]:
        gate = self.get_capability("suggested_questions.publish")
        return [gate] if gate else []

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        if capability_id != "suggested_questions.publish" or not self.enabled:
            return None
        return CapabilityGate(
            capability_id="suggested_questions.publish",
            state="enabled",
            reason_code="TEST_QUALIFIED",
            source="test",
        )


@dataclass
class FakeSource:
    questions: list[str] = field(
        default_factory=lambda: ["What is an LLM wiki?", "Why do agents need a harness?"]
    )
    blob: str = "blob123"
    commit: str = "commit123"
    repository: str = "danielcanfly/daniel-blog"
    source_path: str = "src/data/m26-home-suggested-questions.mjs"
    source_ref: str = "main"

    def read(self) -> SuggestedQuestionsSnapshot:
        return SuggestedQuestionsSnapshot(
            repository=self.repository,
            source_path=self.source_path,
            source_ref=self.source_ref,
            content_blob_sha=self.blob,
            observed_repo_commit=self.commit,
            questions=tuple(self.questions),
            observed_at="2026-09-07T09:00:00Z",
        )


@dataclass
class FakePublisher:
    source: FakeSource
    calls: list[dict[str, Any]] = field(default_factory=list)

    def publish(
        self,
        *,
        base_revision: str,
        questions: list[str],
        operation_id: str,
    ) -> Mapping[str, Any]:
        if base_revision != self.source.read().revision:
            raise ReleaseConflictError("Suggested Questions base revision changed")
        self.calls.append(
            {
                "base_revision": base_revision,
                "questions": list(questions),
                "operation_id": operation_id,
            }
        )
        for question in questions:
            if question not in self.source.questions:
                self.source.questions.append(question)
        self.source.blob = "blob456"
        self.source.commit = "commit456"
        return {
            "revision": "github-blob:blob456",
            "content_blob_sha": "blob456",
            "commit_sha": "commit456",
            "question_count": len(self.source.questions),
            "added_questions": list(questions),
            "readback_verified": True,
        }


@dataclass
class FakeRerunner:
    calls: list[str] = field(default_factory=list)

    def run(self, question: str) -> Mapping[str, Any]:
        self.calls.append(question)
        return {
            "status": "answered",
            "terminal_status": "answered",
            "trace_id": "trace-1",
            "answer_text": "A grounded answer about the requested concept and its practical implications.",
            "citations": [{"source_id": "source-1"}],
            "sources": [{"source_id": "source-1"}],
            "integrity": {
                "unsupported_accepted_claims": 0,
                "material_claim_support_verified": True,
                "citation_locator_valid": True,
            },
        }


@dataclass
class FakeQaRepository:
    events: dict[str, dict[str, Any]]
    writes: list[dict[str, Any]] = field(default_factory=list)

    def get_event(self, event_id: str) -> dict[str, Any]:
        if event_id not in self.events:
            raise KeyError(event_id)
        return dict(self.events[event_id])

    def record_suggested_questions_evaluation(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        if event_id not in self.events:
            raise KeyError(event_id)
        self.writes.append({"event_id": event_id, **kwargs})
        suggested = dict(self.events[event_id].get("suggested_questions") or {})
        projected = dict(kwargs)
        if "status" in projected:
            projected["evaluation_status"] = projected.pop("status")
        suggested.update(projected)
        self.events[event_id]["suggested_questions"] = suggested
        return dict(self.events[event_id])


def _eligible_event(event_id: str, question: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "question": question,
        "score": 96,
        "result": "pass",
        "evaluation_status": "ANSWERED",
        "evaluator": {"rubric_version": ANSWER_QUALITY_RUBRIC_VERSION},
        "suggested_questions": {"eligible": True},
    }


def _aq_pass() -> StaticAnswerQualityEvaluator:
    return StaticAnswerQualityEvaluator(
        AnswerQualityEvaluation(
            score=100,
            result="pass",
            criterion_scores=dict(ANSWER_QUALITY_CRITERION_MAX),
            hard_fail_codes=(),
            failure_class=None,
            failure_stage=None,
            failure_signature=None,
            evaluator_provider="test",
            evaluator_model="test-aq",
        )
    )


def _sq_pass(score_delta: int = 0) -> StaticSuggestedQuestionsEvaluator:
    criteria = dict(SUGGESTED_QUESTIONS_CRITERION_MAX)
    if score_delta:
        criteria["answer_quality"] += score_delta
    score = sum(criteria.values())
    return StaticSuggestedQuestionsEvaluator(
        SuggestedQuestionsEvaluation(
            score=score,
            result="pass" if score >= SUGGESTED_QUESTIONS_THRESHOLD else "fail",
            criterion_scores=criteria,
            hard_fail_codes=(),
            duplicate_of=None,
            topic_family="AI agents",
            diagnostic="qualified",
            evaluator_provider="test",
            evaluator_model="test-sq",
        )
    )


def _headers(key: str | None = None) -> dict[str, str]:
    result = {
        "origin": "https://console.danielcanfly.com",
        ACCESS_ASSERTION_HEADER: "valid-assertion",
        "content-type": "application/json",
    }
    if key is not None:
        result["idempotency-key"] = key
    return result


def _make_app(tmp_path: Path, *, qa_repo: FakeQaRepository, source: FakeSource | None = None):
    source = source or FakeSource()
    publisher = FakePublisher(source)
    rerunner = FakeRerunner()
    store = ObjectStoreSuggestedQuestionsPromotionStore(FileObjectStore(tmp_path / "promotions"))
    app = FastAPI()
    audit = InMemoryAuditSink()
    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(),
        idempotency_store=InMemoryIdempotencyStore(),
        audit_sink=audit,
    )
    install_suggested_questions_admin(
        app,
        source=source,
        promotion_store=store,
        rerunner=rerunner,
        aq_evaluator=_aq_pass(),
        sq_evaluator=_sq_pass(),
        publisher=publisher,
    )
    app.state.suggested_questions_qa_repository = qa_repo
    return app, source, publisher, rerunner, store, audit


def test_owner_rubric_is_separate_six_dimension_100_point_contract() -> None:
    assert SUGGESTED_QUESTIONS_CRITERION_MAX == {
        "answer_quality": 30,
        "evidence_citations": 20,
        "homepage_fit": 15,
        "question_framing": 15,
        "corpus_representativeness": 10,
        "non_duplication": 10,
    }
    assert sum(SUGGESTED_QUESTIONS_CRITERION_MAX.values()) == 100
    assert SUGGESTED_QUESTIONS_THRESHOLD == 85
    assert SUGGESTED_QUESTIONS_RUBRIC_VERSION != ANSWER_QUALITY_RUBRIC_VERSION


def test_article_index_and_exact_existing_duplicate_are_hard_failures() -> None:
    codes = deterministic_hard_fail_codes(
        question="What does the article Part 2 say?",
        answer_payload={"status": "answered", "answer_text": "answer", "citations": [{"source_id": "s1"}]},
        existing_questions=["What does the article Part 2 say?"],
        batch_questions=["What does the article Part 2 say?"],
    )
    assert "ARTICLE_INDEX_SMELL" in codes
    assert "DUPLICATE_EXISTING" in codes


def test_preview_requires_historical_aq_pass_and_never_calls_publisher(tmp_path: Path) -> None:
    qa = FakeQaRepository(
        {
            "evt-pass": _eligible_event("evt-pass", "How should agents verify completion?"),
            "evt-fail": {
                **_eligible_event("evt-fail", "Why do weak answers fail?"),
                "result": "fail",
                "score": 70,
                "suggested_questions": {"eligible": False},
            },
        }
    )
    app, source, publisher, rerunner, _, _ = _make_app(tmp_path, qa_repo=qa)
    response = TestClient(app).post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-0001"),
        json={"event_ids": ["evt-pass", "evt-fail"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "review_ready"
    by_id = {item["event_id"]: item for item in payload["data"]["candidates"]}
    assert by_id["evt-pass"]["status"] == "eligible"
    assert by_id["evt-fail"]["status"] == "rejected"
    assert by_id["evt-fail"]["reason_codes"] == ["HISTORICAL_AQ_NOT_ELIGIBLE"]
    assert rerunner.calls == ["How should agents verify completion?"]
    assert publisher.calls == []
    assert source.questions == ["What is an LLM wiki?", "Why do agents need a harness?"]


def test_preview_is_durable_and_idempotent(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, _, publisher, _, store, _ = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    headers = _headers("sq-preview-idempotency-0002")
    first = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=headers,
        json={"event_ids": ["evt-1"]},
    )
    second = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=headers,
        json={"event_ids": ["evt-1"]},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["operation_id"] == second.json()["operation_id"]
    assert second.json()["replayed"] is True
    promotion_id = first.json()["data"]["promotion_id"]
    assert store.get(promotion_id)["status"] == "review_ready"
    assert publisher.calls == []


def test_preview_requires_idempotency_key_via_registered_mutation_route(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, *_ = _make_app(tmp_path, qa_repo=qa)
    response = TestClient(app).post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers(),
        json={"event_ids": ["evt-1"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ADMIN_IDEMPOTENCY_KEY_INVALID"


def test_publish_is_explicit_cas_guarded_readback_verified_and_idempotent(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, source, publisher, _, store, _ = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    preview = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-0003"),
        json={"event_ids": ["evt-1"]},
    ).json()["data"]
    promotion_id = preview["promotion_id"]
    publish_headers = _headers("sq-publish-idempotency-0001")
    body = {
        "base_revision": preview["base_revision"],
        "selected_event_ids": ["evt-1"],
    }
    first = client.post(
        f"/v1/admin/suggested-questions/promotions/{promotion_id}/publish",
        headers=publish_headers,
        json=body,
    )
    second = client.post(
        f"/v1/admin/suggested-questions/promotions/{promotion_id}/publish",
        headers=publish_headers,
        json=body,
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["status"] == "published"
    assert first.json()["data"]["publication"]["readback_verified"] is True
    assert second.json()["replayed"] is True
    assert len(publisher.calls) == 1
    assert "How should agents verify completion?" in source.questions
    assert store.get(promotion_id)["publication"]["revision"] == "github-blob:blob456"
    assert qa.events["evt-1"]["suggested_questions"]["production_published"] is True


def test_publish_fails_closed_on_revision_drift_before_mutation(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, source, publisher, _, _, _ = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    preview = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-0004"),
        json={"event_ids": ["evt-1"]},
    ).json()["data"]
    source.blob = "drifted-blob"
    response = client.post(
        f"/v1/admin/suggested-questions/promotions/{preview['promotion_id']}/publish",
        headers=_headers("sq-publish-idempotency-0002"),
        json={
            "base_revision": preview["base_revision"],
            "selected_event_ids": ["evt-1"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SUGGESTED_QUESTIONS_REVISION_CONFLICT"
    assert publisher.calls == []


def test_published_promotion_rejects_different_second_selection(tmp_path: Path) -> None:
    qa = FakeQaRepository(
        {
            "evt-1": _eligible_event("evt-1", "How should agents verify completion?"),
            "evt-2": _eligible_event("evt-2", "How should agent state survive disconnects?"),
        }
    )
    app, _, publisher, _, _, _ = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    preview = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-0005"),
        json={"event_ids": ["evt-1", "evt-2"]},
    ).json()["data"]
    promotion_id = preview["promotion_id"]
    first = client.post(
        f"/v1/admin/suggested-questions/promotions/{promotion_id}/publish",
        headers=_headers("sq-publish-idempotency-0003"),
        json={"base_revision": preview["base_revision"], "selected_event_ids": ["evt-1"]},
    )
    assert first.status_code == 200
    second = client.post(
        f"/v1/admin/suggested-questions/promotions/{promotion_id}/publish",
        headers=_headers("sq-publish-idempotency-0004"),
        json={"base_revision": preview["base_revision"], "selected_event_ids": ["evt-2"]},
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SUGGESTED_QUESTIONS_PROMOTION_INVALID"
    assert len(publisher.calls) == 1


def test_batch_answer_overlap_dedupes_otherwise_eligible_candidates(tmp_path: Path) -> None:
    qa = FakeQaRepository(
        {
            "evt-a": _eligible_event("evt-a", "How should agents verify completion?"),
            "evt-b": _eligible_event("evt-b", "How can an agent prove that work is finished?"),
        }
    )
    source = FakeSource()
    preview = build_promotion_preview(
        promotion_id="promotion-overlap",
        event_ids=["evt-a", "evt-b"],
        qa_repository=qa,
        rerunner=FakeRerunner(),
        aq_evaluator=_aq_pass(),
        sq_evaluator=_sq_pass(),
        existing_questions=source.questions,
        source_revision=source.read().revision,
        source_evidence_digest=source.read().evidence_digest,
        observed_at="2026-09-07T09:00:00Z",
    )
    statuses = [item["status"] for item in preview["candidates"]]
    assert statuses.count("eligible") == 1
    assert statuses.count("rejected") == 1
    loser = next(item for item in preview["candidates"] if item["status"] == "rejected")
    assert "DUPLICATE_BATCH" in loser["reason_codes"]
    assert loser["duplicate_of_event_id"] in {"evt-a", "evt-b"}
    assert loser["suggested_questions_evaluation"]["result"] == "fail"
    assert "DUPLICATE_BATCH" in loser["suggested_questions_evaluation"]["hard_fail_codes"]


def test_core_publish_replay_rejects_different_selection() -> None:
    record = {
        "promotion_id": "p1",
        "status": "published",
        "publication": {"selected_event_ids": ["evt-1"]},
        "candidates": [
            {"event_id": "evt-1", "question": "One?", "status": "eligible"},
            {"event_id": "evt-2", "question": "Two?", "status": "eligible"},
        ],
    }
    with pytest.raises(SuggestedQuestionsPromotionError, match="different candidate selection"):
        publish_promotion(
            record=record,
            selected_event_ids=["evt-2"],
            current_source_revision="github-blob:any",
            publisher=FakePublisher(FakeSource()),
            publish_operation_id="op",
            qa_repository=FakeQaRepository({}),
        )


def test_preview_store_failure_does_not_project_event_metadata(tmp_path: Path) -> None:
    class FailingStore:
        def get(self, promotion_id: str) -> dict[str, Any]:
            raise KeyError(promotion_id)

        def create(self, promotion_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
            raise RuntimeError("store unavailable")

    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    source = FakeSource()
    publisher = FakePublisher(source)
    app = FastAPI()
    install_admin_control_plane(
        app,
        authenticator=FakeAuthenticator(),
        capability_provider=StaticCapabilities(),
        idempotency_store=InMemoryIdempotencyStore(),
        audit_sink=InMemoryAuditSink(),
    )
    install_suggested_questions_admin(
        app,
        source=source,
        promotion_store=FailingStore(),
        rerunner=FakeRerunner(),
        aq_evaluator=_aq_pass(),
        sq_evaluator=_sq_pass(),
        publisher=publisher,
    )
    app.state.suggested_questions_qa_repository = qa
    response = TestClient(app).post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-storefail"),
        json={"event_ids": ["evt-1"]},
    )
    assert response.status_code == 500
    assert qa.writes == []
    assert publisher.calls == []


def test_successful_preview_and_publish_are_audited(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, _, _, _, _, audit = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    preview_response = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-audit01"),
        json={"event_ids": ["evt-1"]},
    )
    preview = preview_response.json()["data"]
    publish_response = client.post(
        f"/v1/admin/suggested-questions/promotions/{preview['promotion_id']}/publish",
        headers=_headers("sq-publish-idempotency-audit01"),
        json={"base_revision": preview["base_revision"], "selected_event_ids": ["evt-1"]},
    )
    assert publish_response.status_code == 200
    actions = [event.action for event in audit.events]
    assert "suggested_questions.promotion.preview.accepted" in actions
    assert "suggested_questions.promotion.publish.accepted" in actions


def test_get_promotion_reads_durable_preview_record(tmp_path: Path) -> None:
    qa = FakeQaRepository({"evt-1": _eligible_event("evt-1", "How should agents verify completion?")})
    app, *_ = _make_app(tmp_path, qa_repo=qa)
    client = TestClient(app)
    preview = client.post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-get001"),
        json={"event_ids": ["evt-1"]},
    ).json()["data"]
    response = client.get(
        f"/v1/admin/suggested-questions/promotions/{preview['promotion_id']}",
        headers={
            "origin": "https://console.danielcanfly.com",
            ACCESS_ASSERTION_HEADER: "valid-assertion",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["promotion_id"] == preview["promotion_id"]
    assert response.json()["data"]["status"] == "review_ready"


def test_source_append_targets_the_frozen_array_even_if_earlier_close_marker_exists() -> None:
    from knowledge_engine.m26_suggested_questions_admin import _append_questions_to_source

    source = (
        "const unrelated = Object.freeze([\n  'ignore',\n]);\n"
        "export const M26_HOME_SUGGESTED_QUESTIONS = Object.freeze([\n  'One?',\n]);\n"
    )
    updated = _append_questions_to_source(source, ["Two?"])
    assert "const unrelated = Object.freeze([\n  'ignore',\n]);" in updated
    assert "M26_HOME_SUGGESTED_QUESTIONS = Object.freeze([\n  'One?',\n  \"Two?\",\n]);" in updated


def test_concrete_github_publisher_uses_blob_cas_and_readback_without_live_network() -> None:
    import base64

    from knowledge_engine.m26_suggested_questions_admin import GitHubSuggestedQuestionsPublisher

    class RecordingPublisher(GitHubSuggestedQuestionsPublisher):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.source_text = (
                "export const M26_HOME_SUGGESTED_QUESTIONS = Object.freeze([\n"
                "  'One?',\n]);\n"
            )
            self.blob = "blob-a"
            self.put_count = 0

        def _request_json(
            self,
            url: str,
            *,
            method: str = "GET",
            payload: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            if method == "GET":
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(self.source_text.encode()).decode(),
                    "sha": self.blob,
                }
            assert method == "PUT"
            assert payload is not None
            assert payload["sha"] == self.blob
            self.put_count += 1
            self.source_text = base64.b64decode(str(payload["content"])).decode()
            self.blob = "blob-b"
            return {"content": {"sha": self.blob}, "commit": {"sha": "commit-b"}}

    publisher = RecordingPublisher()
    result = publisher.publish(
        base_revision="github-blob:blob-a",
        questions=["Two?"],
        operation_id="admop-test",
    )
    assert publisher.put_count == 1
    assert result["revision"] == "github-blob:blob-b"
    assert result["readback_verified"] is True
    assert "Two?" in publisher.source_text


def test_concrete_github_publisher_refuses_stale_blob_before_put() -> None:
    from knowledge_engine.m26_suggested_questions_admin import GitHubSuggestedQuestionsPublisher

    class StalePublisher(GitHubSuggestedQuestionsPublisher):
        def __init__(self) -> None:
            super().__init__(token="test-token")
            self.put_count = 0

        def _request_json(
            self,
            url: str,
            *,
            method: str = "GET",
            payload: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            if method == "PUT":
                self.put_count += 1
            return {"encoding": "base64", "content": "", "sha": "newer-blob"}

    publisher = StalePublisher()
    with pytest.raises(ReleaseConflictError):
        publisher.publish(
            base_revision="github-blob:old-blob",
            questions=["Two?"],
            operation_id="admop-test",
        )
    assert publisher.put_count == 0


def test_provider_output_rejects_extra_fields_and_unknown_topic_family() -> None:
    from knowledge_engine.suggested_questions_scoring import (
        ProviderSuggestedQuestionsEvaluator,
        SuggestedQuestionsEvaluationError,
    )

    class Provider:
        def __init__(self, payload: Mapping[str, Any]) -> None:
            self.payload = payload

        def call(self, payload: Mapping[str, Any], call_class: str) -> Mapping[str, Any]:
            return {"text": __import__("json").dumps(self.payload)}

    base = {
        "criterion_scores": dict(SUGGESTED_QUESTIONS_CRITERION_MAX),
        "hard_fail_codes": [],
        "duplicate_of": None,
        "topic_family": "AI agents",
        "diagnostic": "ok",
    }
    evaluator = ProviderSuggestedQuestionsEvaluator(
        Provider({**base, "unexpected": True}), provider_name="test", model="test"
    )
    with pytest.raises(SuggestedQuestionsEvaluationError, match="exactly"):
        evaluator.evaluate(
            question="How should agents verify completion?",
            answer_payload={
                "status": "answered",
                "answer_text": "grounded",
                "citations": [{"source_id": "s1"}],
            },
            existing_questions=[],
            batch_questions=["How should agents verify completion?"],
        )

    evaluator = ProviderSuggestedQuestionsEvaluator(
        Provider({**base, "topic_family": "made-up-family"}),
        provider_name="test",
        model="test",
    )
    with pytest.raises(SuggestedQuestionsEvaluationError, match="canonical topic families"):
        evaluator.evaluate(
            question="How should agents verify completion?",
            answer_payload={
                "status": "answered",
                "answer_text": "grounded",
                "citations": [{"source_id": "s1"}],
            },
            existing_questions=[],
            batch_questions=["How should agents verify completion?"],
        )


def test_historical_aq_rejection_projects_as_ineligible_not_fake_sq_failure(tmp_path: Path) -> None:
    qa = FakeQaRepository(
        {
            "evt-fail": {
                **_eligible_event("evt-fail", "Why do weak answers fail?"),
                "result": "fail",
                "score": 70,
                "suggested_questions": {"eligible": False},
            }
        }
    )
    app, *_ = _make_app(tmp_path, qa_repo=qa)
    response = TestClient(app).post(
        "/v1/admin/suggested-questions/promotions/preview",
        headers=_headers("sq-preview-idempotency-ineligible"),
        json={"event_ids": ["evt-fail"]},
    )
    assert response.status_code == 200
    assert qa.events["evt-fail"]["suggested_questions"]["evaluation_status"] == "ineligible"
    assert qa.events["evt-fail"]["suggested_questions"]["score"] is None
    assert qa.events["evt-fail"]["suggested_questions"]["result"] is None
