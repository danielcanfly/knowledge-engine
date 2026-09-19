from __future__ import annotations

import json
import threading
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from knowledge_engine import m26_public_api, qa_answer_quality
from knowledge_engine.m26_qa_inbox_integration import (
    QaAnswerCaptureMiddleware,
    _error_reason_codes,
    _terminal_answer,
    _terminal_error,
)
from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    AnswerQualityEvaluation,
    StaticAnswerQualityEvaluator,
    canonical_failure_provenance,
)
from knowledge_engine.qa_answer_quality_sqlite import SqliteQaRepository
from knowledge_engine.qa_failure_clustering import FailureIntentFamily
from knowledge_engine.storage import FileObjectStore


class _BlockingFailEvaluator:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def evaluate(self, **_: object) -> object:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test evaluator release timed out")
        raise RuntimeError("intentional evaluator failure")


def _eventually_event(repo: SqliteQaRepository, event_id: str, status: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        event = repo.get_event(event_id)
        if event["evaluation_status"] == status:
            return event
        time.sleep(0.01)
    raise AssertionError(f"event {event_id} did not reach {status}")


def _public_capture_app(
    repo: SqliteQaRepository,
    evaluator: object,
    *,
    request_id: str,
) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/answers")
    async def public_answer() -> StreamingResponse:
        answer = {
            "request_id": request_id,
            "status": "answered",
            "answer_text": "A grounded public answer that the visitor must receive before QA evaluation finishes.",
            "citations": [{"citation_id": "c1", "source_id": "s1"}],
            "selected_evidence": [{"source_id": "s1", "quote": "support"}],
            "integrity": {
                "unsupported_accepted_claims": 0,
                "material_claim_support_verified": True,
                "citation_locator_valid": True,
            },
        }
        public_event = {
            "request_id": request_id,
            "type": "answer.completed",
            "answer": answer["answer_text"],
            "citations": answer["citations"],
        }
        model_started = {
            "request_id": request_id,
            "type": "model.started",
            "provider": "cloudflare",
            "model": "@cf/openai/gpt-oss-120b",
        }
        model_completed = {
            **model_started,
            "type": "model.completed",
            "status": "completed",
        }
        body = (
            f"event: model.started\ndata: {json.dumps(model_started)}\n\n"
            f"event: model.completed\ndata: {json.dumps(model_completed)}\n\n"
            f"event: answer.completed\ndata: {json.dumps(public_event)}\n\n"
        )
        return StreamingResponse(iter([body]), media_type="text/event-stream")

    app.add_middleware(
        QaAnswerCaptureMiddleware,
        repository_provider=lambda: repo,
        evaluator_provider=lambda: evaluator,
    )
    return app


def _answer(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "status": "answered",
        "answer_text": "Grounded answer.",
        "citations": [{"citation_id": "c1", "source_id": "s1"}],
        "selected_evidence": [{"source_id": "s1", "quote": "support"}],
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": True,
            "citation_locator_valid": True,
        },
    }


def _static_evaluator(*, result: str) -> StaticAnswerQualityEvaluator:
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    if result == "fail":
        criteria["completeness_facets"] = 0
        criteria["correctness_grounding"] = 20
        score = sum(criteria.values())
        stage, failure_class, signature = canonical_failure_provenance(
            hard_fail_codes=(), criterion_scores=criteria
        )
        intent = FailureIntentFamily(task="explain", subjects=("qa",))
    else:
        score = sum(criteria.values())
        stage = failure_class = signature = None
        intent = None
    return StaticAnswerQualityEvaluator(
        AnswerQualityEvaluation(
            score=score,
            result=result,
            criterion_scores=criteria,
            hard_fail_codes=(),
            failure_class=failure_class,
            failure_stage=stage,
            failure_signature=signature,
            evaluator_provider="acceptance-provider",
            evaluator_model="acceptance-model",
            failure_intent=intent,
        )
    )


def test_public_sse_terminal_contract_normalizes_current_event_names() -> None:
    completed = _terminal_answer(
        [
            (
                "answer.completed",
                {
                    "request_id": "req-current",
                    "answer": "Grounded current-contract answer.",
                    "citations": [{"citation_id": "c1"}],
                },
            )
        ]
    )
    assert completed is not None
    assert completed["answer_text"] == "Grounded current-contract answer."
    assert completed["status"] == "owner_only_cited_answer"
    assert completed["safe_abstention"] is False

    failed = _terminal_error(
        [("answer.failed", {"request_id": "req-failed", "code": "ANSWER_TIMEOUT"})]
    )
    assert failed is not None
    assert _error_reason_codes(failed) == ["ANSWER_TIMEOUT"]


def test_public_v1_answers_is_visitor_first_and_durable_before_evaluation_failure(
    tmp_path, monkeypatch
) -> None:
    repo = SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )
    evaluator = _BlockingFailEvaluator()

    # TestClient's synthetic client name is not an IP address. Country trust is
    # orthogonal to this test, so force the public trusted-proxy predicate closed.
    monkeypatch.setattr(m26_public_api, "_trusted_proxy", lambda _remote: False)
    app = _public_capture_app(repo, evaluator, request_id="public-capture-1")

    response = TestClient(app).post(
        "/v1/answers",
        json={"question": "How does public answer capture work?"},
    )

    # The public response must complete while the evaluator is still blocked.
    assert response.status_code == 200
    assert "public-capture-1" in response.text
    assert evaluator.started.wait(timeout=1)
    assert evaluator.release.is_set() is False

    page = repo.list_events(range_name="90d", limit=10)
    assert page["total"] == 1
    event_id = page["items"][0]["event_id"]
    pending = repo.get_event(event_id)
    assert pending["evaluation_status"] == "PENDING"
    assert pending["score"] is None
    assert pending["result"] is None
    assert pending["country"] == "ZZ"

    evaluator.release.set()
    failed = _eventually_event(repo, event_id, "NOT_EVALUATED")
    assert failed["score"] is None
    assert failed["result"] is None
    assert failed["evaluation_error_code"] == "EVALUATOR_ERROR"

    # Evaluator failure changes evaluation state; it never erases the captured query.
    assert repo.list_events(range_name="90d", limit=10)["total"] == 1


def test_public_v1_answers_queue_saturation_preserves_durable_event(
    tmp_path, monkeypatch
) -> None:
    repo = SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )
    evaluator = _BlockingFailEvaluator()
    saturated = threading.BoundedSemaphore(value=1)
    assert saturated.acquire(blocking=False)

    monkeypatch.setattr(m26_public_api, "_trusted_proxy", lambda _remote: False)
    monkeypatch.setattr(qa_answer_quality, "_CAPTURE_SLOTS", saturated)
    app = _public_capture_app(repo, evaluator, request_id="public-capture-saturated")

    response = TestClient(app).post(
        "/v1/answers",
        json={"question": "Does queue pressure erase this query?"},
    )

    assert response.status_code == 200
    assert "public-capture-saturated" in response.text
    assert evaluator.started.is_set() is False

    page = repo.list_events(range_name="90d", limit=10)
    assert page["total"] == 1
    event = repo.get_event(page["items"][0]["event_id"])
    assert event["evaluation_status"] == "NOT_EVALUATED"
    assert event["score"] is None
    assert event["result"] is None
    assert event["evaluation_error_code"] == "EVALUATION_QUEUE_SATURATED"


def test_public_capture_preserves_current_dotted_provider_events(tmp_path, monkeypatch) -> None:
    repo = SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )
    monkeypatch.setattr(m26_public_api, "_trusted_proxy", lambda _remote: False)
    app = _public_capture_app(repo, _static_evaluator(result="fail"), request_id="provider-events")

    response = TestClient(app).post(
        "/v1/answers",
        json={"question": "Which provider produced this answer?"},
    )
    assert response.status_code == 200

    page = repo.list_events(range_name="90d", limit=10)
    assert page["total"] == 1
    event = _eventually_event(repo, page["items"][0]["event_id"], "ANSWERED")
    provider_events = event["failure_trace"]["raw_runtime_trace"]["provider_events"]
    assert [item["type"] for item in provider_events] == ["model.started", "model.completed"]
    assert provider_events[0]["provider"] == "cloudflare"
    assert provider_events[0]["model"] == "@cf/openai/gpt-oss-120b"


def test_production_sqlite_pass_is_compact_and_fail_trace_redacts_secrets(tmp_path) -> None:
    repo = SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )
    secret_token = "acceptance-super-secret-token"
    secret_key = "acceptance-super-secret-api-key"
    forensic = {
        "authorization": f"Bearer {secret_token}",
        "nested": {"api_key": secret_key},
        "retrieval": {"selected": [{"source_id": "s1", "score": 0.9}]},
    }

    pass_event = repo.record_answer(
        question="A passing question",
        response=_answer("pass-compact"),
        latency_ms=12,
        trace=forensic,
    )
    passed = repo.evaluate_event(
        pass_event["event_id"],
        evaluator=_static_evaluator(result="pass"),
        answer_payload=_answer("pass-compact"),
        forensic_trace=forensic,
    )
    assert passed["result"] == "pass"
    assert passed["failure_trace_key"] is None
    assert "failure_trace" not in passed

    fail_event = repo.record_answer(
        question="A failing question",
        response=_answer("fail-redacted"),
        latency_ms=25,
        trace=forensic,
    )
    failed = repo.evaluate_event(
        fail_event["event_id"],
        evaluator=_static_evaluator(result="fail"),
        answer_payload=_answer("fail-redacted"),
        forensic_trace=forensic,
    )
    assert failed["result"] == "fail"
    assert failed["failure_trace_key"]
    trace = failed["failure_trace"]
    serialized = json.dumps(trace, ensure_ascii=False)
    assert secret_token not in serialized
    assert secret_key not in serialized
    assert "[REDACTED]" in serialized
    assert trace["raw_runtime_trace"]["retrieval"]["selected"][0]["source_id"] == "s1"
