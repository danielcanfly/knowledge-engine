from __future__ import annotations

from knowledge_engine.qa_answer_quality import QaRepository, evaluate_answer_quality
from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    AnswerQualityEvaluation,
    AnswerQualityEvaluationError,
    ProviderAnswerQualityEvaluator,
    StaticAnswerQualityEvaluator,
    UnavailableAnswerQualityEvaluator,
    validate_answer_quality_evaluation,
)
from knowledge_engine.qa_answer_quality_sqlite import SqliteQaRepository
from knowledge_engine.storage import FileObjectStore


def good_response(request_id: str = "req_1") -> dict:
    return {
        "request_id": request_id,
        "status": "answered",
        "answer": "A grounded answer that is deliberately long enough to satisfy the completeness signal. "
        * 2,
        "citations": [{"citation_id": "c1", "source_id": "s1"}],
        "source_cards": [{"source_id": "s1"}],
        "release_id": "rel-1",
    }


def bad_response(request_id: str = "req_bad") -> dict:
    return {
        "request_id": request_id,
        "status": "degraded",
        "answer": "",
        "citations": [],
        "source_cards": [],
        "release_id": "rel-1",
        "authorization": "Bearer super-secret",
    }


def test_answer_quality_v1_pass_and_hard_fail() -> None:
    passed = evaluate_answer_quality(question="What is X?", response=good_response())
    assert passed["score"] >= 85
    assert passed["result"] == "pass"

    unsupported = good_response()
    unsupported["integrity"] = {"unsupported_accepted_claims": 1}
    failed = evaluate_answer_quality(question="What is X?", response=unsupported)
    assert failed["score"] < 85
    assert failed["result"] == "fail"
    assert "UNSUPPORTED_ACCEPTED_CLAIMS" in failed["hard_fail_reasons"]


def test_every_query_is_a_distinct_event(tmp_path) -> None:
    repo = QaRepository(FileObjectStore(tmp_path))
    first = repo.record_answer(
        question="What is X?",
        response=good_response(),
        latency_ms=100,
        timestamp="2026-09-07T00:00:00Z",
    )
    second = repo.record_answer(
        question="What is X?",
        response=good_response(),
        latency_ms=110,
        timestamp="2026-09-07T00:00:01Z",
    )
    assert first["event_id"] != second["event_id"]
    page = repo.list_events(
        range_name="custom",
        from_ts="2026-09-06T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
    )
    assert page["total"] == 2


def test_failure_trace_redacts_secrets(tmp_path) -> None:
    repo = QaRepository(FileObjectStore(tmp_path))
    event = repo.record_answer(
        question="broken query",
        response=bad_response(),
        latency_ms=200,
        trace={"authorization": "Bearer nope", "nested": {"api_key": "abc"}},
        timestamp="2026-09-07T00:00:00Z",
    )
    trace = repo.get_event(event["event_id"])["failure_trace"]
    assert trace["raw_runtime_trace"]["authorization"] == "[REDACTED]"
    assert trace["raw_runtime_trace"]["nested"]["api_key"] == "[REDACTED]"


def test_jsonl_export_is_idempotent_and_verified_recurrence_reopens(tmp_path) -> None:
    repo = QaRepository(FileObjectStore(tmp_path))
    event = repo.record_answer(
        question="broken query",
        response=bad_response(),
        latency_ms=200,
        timestamp="2026-09-07T00:00:00Z",
    )
    cluster_id = event["cluster_id"]

    first = repo.export_new_failures()
    second = repo.export_new_failures()
    assert first["created"] is True
    assert second == {"created": False, "reason": "NO_NEW_FAILURES"}

    repo.transition_cluster(cluster_id, state="IN_REPAIR")
    repo.transition_cluster(cluster_id, state="RESOLVED", resolved_by_release="rel-fixed")
    repo.transition_cluster(cluster_id, state="VERIFIED", resolved_by_release="rel-fixed")
    repo.record_answer(
        question="broken query",
        response=bad_response("req_bad_2"),
        latency_ms=210,
        timestamp="2026-09-08T00:00:00Z",
    )
    cluster = repo.list_clusters()[0]
    assert cluster["lifecycle"] == "REOPENED"
    assert cluster["version"] == 2
    third = repo.export_new_failures()
    assert third["created"] is True
    assert third["membership"] == [f"{cluster_id}:2"]


def test_summary_reports_required_metrics_and_latency_percentiles(tmp_path) -> None:
    repo = QaRepository(FileObjectStore(tmp_path))
    for idx, latency in enumerate([10, 20, 30, 40, 100]):
        repo.record_answer(
            question=f"good {idx}",
            response=good_response(f"req_{idx}"),
            latency_ms=latency,
            timestamp=f"2026-09-07T00:00:0{idx}Z",
        )
    summary = repo.summary(
        range_name="custom",
        from_ts="2026-09-06T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
    )
    assert summary["queries"] == 5
    assert summary["pass_rate"] == 100.0
    assert summary["median_latency_ms"] == 30
    assert summary["p95_latency_ms"] == 88
    assert summary["quality_series"]
    assert summary["latency_series"]


def _static_evaluator(
    result: str = "pass", score: int = 100, hard_fail_codes: tuple[str, ...] = ()
):
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    if score != 100:
        criteria["directness_intent"] = score - sum(
            value for key, value in criteria.items() if key != "directness_intent"
        )
    return StaticAnswerQualityEvaluator(
        AnswerQualityEvaluation(
            score=score,
            result=result,
            criterion_scores=criteria,
            hard_fail_codes=hard_fail_codes,
            failure_class="test_failure" if result == "fail" else None,
            failure_stage="test" if result == "fail" else None,
            failure_signature="test_signature" if result == "fail" else None,
            evaluator_provider="test-provider",
            evaluator_model="test-model",
        )
    )


def test_sqlite_capture_and_semantic_lifecycle(tmp_path) -> None:
    repo = SqliteQaRepository(FileObjectStore(tmp_path / "objects"), db_path=tmp_path / "qa.sqlite")
    event = repo.record_answer(
        question="What is X?",
        response=good_response("sqlite-1"),
        latency_ms=12,
        timestamp="2026-09-07T00:00:00Z",
    )
    assert event["evaluation_status"] == "PENDING"
    assert event["score"] is None and event["result"] is None
    answered = repo.evaluate_event(
        event["event_id"], evaluator=_static_evaluator(), answer_payload=good_response("sqlite-1")
    )
    assert answered["evaluation_status"] == "ANSWERED"
    assert answered["score"] == 100 and answered["result"] == "pass"
    assert (
        repo.evaluate_event(
            event["event_id"], evaluator=UnavailableAnswerQualityEvaluator(), answer_payload={}
        )["score"]
        == 100
    )


def test_sqlite_evaluator_failure_is_not_evaluated(tmp_path) -> None:
    repo = SqliteQaRepository(FileObjectStore(tmp_path / "objects"), db_path=tmp_path / "qa.sqlite")
    event = repo.record_answer(question="Q", response=good_response("sqlite-2"), latency_ms=1)
    failed = repo.evaluate_event(
        event["event_id"], evaluator=UnavailableAnswerQualityEvaluator(), answer_payload={}
    )
    assert failed["evaluation_status"] == "NOT_EVALUATED"
    assert failed["score"] is None and failed["result"] is None
    assert failed["evaluation_error_code"] == "EVALUATOR_UNAVAILABLE"
    assert repo.list_clusters() == []


def test_sqlite_v1_rows_migrate_as_legacy_provenance(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    import sqlite3

    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE qa_events(
              event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, question TEXT NOT NULL,
              score INTEGER NOT NULL, result TEXT NOT NULL, latency_ms INTEGER NOT NULL,
              country TEXT NOT NULL, release_identity_json TEXT NOT NULL,
              index_identity_json TEXT NOT NULL, evaluator_json TEXT NOT NULL,
              dedupe_identity TEXT NOT NULL, trace_id TEXT NOT NULL, failure_class TEXT,
              failure_signature TEXT, cluster_id TEXT, failure_trace_key TEXT,
              suggested_questions_json TEXT NOT NULL
            );
            INSERT INTO qa_events VALUES('legacy-1','2026-09-07T00:00:00Z','Q',90,'pass',3,'ZZ','{}','{}','{}','d','t',NULL,NULL,NULL,NULL,'{}');
            """
        )
    repo = SqliteQaRepository(FileObjectStore(tmp_path / "objects"), db_path=db_path)
    event = repo.get_event("legacy-1")
    assert event["evaluation_status"] == "ANSWERED"
    assert event["evaluator"]["rubric_version"] == "ANSWER_QUALITY_HEURISTIC_LEGACY_v0"
    assert (
        repo.summary(
            range_name="custom", from_ts="2026-09-06T00:00:00Z", to_ts="2026-09-08T00:00:00Z"
        )["scored"]
        == 0
    )


class _FakeProvider:
    def __init__(self, payload):
        self.payload = payload

    def call(self, payload, call_class):
        assert call_class == "answer_quality_evaluation"
        assert "Suggested Questions" in payload["system"]
        return {"text": self.payload}


def test_semantic_adapter_computes_total_and_preserves_hard_fail_score() -> None:
    import json

    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    criteria["directness_intent"] = 14
    evaluator = ProviderAnswerQualityEvaluator(
        _FakeProvider(
            json.dumps(
                {
                    "criterion_scores": criteria,
                    "hard_fail_codes": ["UNSUPPORTED_ACCEPTED_CLAIMS"],
                    "failure_class": "grounding_integrity",
                    "failure_stage": "validation",
                }
            )
        ),
        provider_name="fake",
        model="model",
    )
    evaluation = evaluator.evaluate(
        question="Q",
        answer_payload={
            "answer_text": "grounded answer",
            "citations": [{}],
            "integrity": {"unsupported_accepted_claims": 1},
        },
        forensic_trace=None,
    )
    assert evaluation.score == 99
    assert evaluation.result == "fail"
    assert evaluation.hard_fail_codes == ("UNSUPPORTED_ACCEPTED_CLAIMS",)


def test_semantic_validator_rejects_forbidden_or_missing_dimensions() -> None:
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    criteria.pop("abstention_appropriateness")
    criteria["homepage_fit"] = 1
    import pytest

    with pytest.raises(AnswerQualityEvaluationError):
        validate_answer_quality_evaluation(
            AnswerQualityEvaluation(
                score=100,
                result="pass",
                criterion_scores=criteria,
                hard_fail_codes=(),
                failure_class=None,
                failure_stage=None,
                failure_signature=None,
                evaluator_provider="fake",
                evaluator_model="model",
            )
        )


def test_duplicate_runtime_identity_is_one_compact_event(tmp_path) -> None:
    repo = SqliteQaRepository(FileObjectStore(tmp_path / "objects"), db_path=tmp_path / "qa.sqlite")
    first = repo.record_answer(
        question="Q",
        response=good_response("same-request"),
        latency_ms=1,
        timestamp="2026-09-07T00:00:00Z",
    )
    second = repo.record_answer(
        question="Q",
        response=good_response("same-request"),
        latency_ms=2,
        timestamp="2026-09-07T00:00:01Z",
    )
    assert first["event_id"] == second["event_id"]
    assert (
        repo.summary(
            range_name="custom", from_ts="2026-09-06T00:00:00Z", to_ts="2026-09-08T00:00:00Z"
        )["queries"]
        == 1
    )
