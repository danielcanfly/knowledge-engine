from __future__ import annotations

from knowledge_engine.qa_answer_quality import QaRepository, evaluate_answer_quality
from knowledge_engine.storage import FileObjectStore


def good_response(request_id: str = "req_1") -> dict:
    return {
        "request_id": request_id,
        "status": "answered",
        "answer": "A grounded answer that is deliberately long enough to satisfy the completeness signal. " * 2,
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
