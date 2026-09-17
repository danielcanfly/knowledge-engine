from __future__ import annotations

import json
import threading
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from knowledge_engine import m26_public_api, qa_answer_quality
from knowledge_engine.m26_qa_inbox_integration import QaAnswerCaptureMiddleware
from knowledge_engine.qa_answer_quality_sqlite import SqliteQaRepository
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
        body = f"event: answer\ndata: {json.dumps(answer)}\n\n"
        return StreamingResponse(iter([body]), media_type="text/event-stream")

    app.add_middleware(
        QaAnswerCaptureMiddleware,
        repository_provider=lambda: repo,
        evaluator_provider=lambda: evaluator,
    )
    return app


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
