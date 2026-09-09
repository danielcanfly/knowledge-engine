from __future__ import annotations

import json

import pytest

from knowledge_engine.m26_admin_contract import AdminAPIError
from knowledge_engine.m26_qa_inbox_integration import QaExportRequest, _trusted_country
from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    AnswerQualityEvaluation,
    StaticAnswerQualityEvaluator,
    canonical_failure_provenance,
)
from knowledge_engine.qa_answer_quality_sqlite import SqliteQaRepository
from knowledge_engine.qa_failure_clustering import FailureIntentFamily
from knowledge_engine.storage import FileObjectStore


def _response(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "status": "owner_only_cited_answer",
        "answer_text": "A supported but incomplete answer.",
        "citations": [{"citation_id": "c1", "source_id": "s1"}],
        "selected_evidence": [{"source_id": "s1", "quote": "support"}],
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": True,
            "citation_locator_valid": True,
        },
    }


def _repo(tmp_path) -> SqliteQaRepository:
    return SqliteQaRepository(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )


def _failing_evaluator(intent: FailureIntentFamily) -> StaticAnswerQualityEvaluator:
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    criteria["completeness_facets"] = 0
    criteria["correctness_grounding"] = 20
    score = sum(criteria.values())
    stage, failure_class, signature = canonical_failure_provenance(
        hard_fail_codes=(),
        criterion_scores=criteria,
    )
    return StaticAnswerQualityEvaluator(
        AnswerQualityEvaluation(
            score=score,
            result="fail",
            criterion_scores=criteria,
            hard_fail_codes=(),
            failure_class=failure_class,
            failure_stage=stage,
            failure_signature=signature,
            evaluator_provider="qualified-provider",
            evaluator_model="qualified-model",
            failure_intent=intent,
        )
    )


def _record_fail(
    repo: SqliteQaRepository,
    *,
    request_id: str,
    question: str,
    timestamp: str,
    country: str,
    intent: FailureIntentFamily,
) -> dict:
    payload = _response(request_id)
    event = repo.record_answer(
        question=question,
        response=payload,
        latency_ms=10,
        country=country,
        timestamp=timestamp,
    )
    return repo.evaluate_event(
        event["event_id"],
        evaluator=_failing_evaluator(intent),
        answer_payload=payload,
    )


def test_question_search_is_composable_and_treats_like_wildcards_literally(tmp_path) -> None:
    repo = _repo(tmp_path)
    routing = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    _record_fail(
        repo,
        request_id="percent",
        question="Why does routing hit 100% before replanning?",
        timestamp="2026-09-07T10:00:00Z",
        country="US",
        intent=routing,
    )
    _record_fail(
        repo,
        request_id="lookalike",
        question="Why does routing hit 100X before replanning?",
        timestamp="2026-09-07T10:01:00Z",
        country="US",
        intent=routing,
    )
    _record_fail(
        repo,
        request_id="underscore",
        question="Explain route_name selection",
        timestamp="2026-09-07T10:02:00Z",
        country="JP",
        intent=FailureIntentFamily(task="explain", subjects=("route name",)),
    )

    percent = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="100%",
        result="fail",
        country="US",
    )
    assert [item["trace_id"] for item in percent["items"]] == ["percent"]

    underscore = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="route_name",
    )
    assert [item["trace_id"] for item in underscore["items"]] == ["underscore"]


def test_country_capture_uses_only_explicit_trusted_edge_metadata(monkeypatch) -> None:
    def scope(*headers: tuple[bytes, bytes]) -> dict:
        return {"headers": list(headers)}

    spoofed = scope((b"cf-ray", b"edge-ray"), (b"cf-ipcountry", b"tw"))
    monkeypatch.delenv("M26_QA_TRUST_CLOUDFLARE_COUNTRY", raising=False)
    assert _trusted_country(spoofed) == "ZZ"

    monkeypatch.setenv("M26_QA_TRUST_CLOUDFLARE_COUNTRY", "true")
    assert _trusted_country(scope((b"cf-ipcountry", b"TW"))) == "ZZ"
    assert _trusted_country(spoofed) == "TW"
    assert _trusted_country(
        scope((b"cf-ray", b"edge-ray"), (b"cf-ipcountry", b"Taiwan"))
    ) == "ZZ"
    assert _trusted_country(
        scope((b"cf-ray", b"edge-ray"), (b"cf-ipcountry", b"\xe5a"))
    ) == "ZZ"


def test_country_normalization_unknowns_and_strict_filters(tmp_path) -> None:
    repo = _repo(tmp_path)
    records = (
        ("tw", " tw ", "TW"),
        ("missing", None, "ZZ"),
        ("invalid", "Taiwan", "ZZ"),
    )
    for request_id, country, expected in records:
        event = repo.record_answer(
            question=f"Question {request_id}",
            response=_response(request_id),
            latency_ms=10,
            country=country,
            timestamp="2026-09-07T10:00:00Z",
        )
        assert event["country"] == expected

    all_events = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
    )
    assert all_events["total"] == 3
    assert {item["country"] for item in all_events["items"]} == {"TW", "ZZ"}

    tw_events = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        country="tw",
    )
    assert [item["trace_id"] for item in tw_events["items"]] == ["tw"]
    unknown_events = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        country="ZZ",
    )
    assert {item["trace_id"] for item in unknown_events["items"]} == {
        "missing",
        "invalid",
    }

    for invalid_filter in ("Taiwan", "T1", " "):
        with pytest.raises(ValueError, match="country must be a two-letter"):
            repo.list_events(
                range_name="custom",
                from_ts="2026-09-07T00:00:00Z",
                to_ts="2026-09-08T00:00:00Z",
                country=invalid_filter,
            )


def test_country_filter_is_consistent_for_list_and_current_filter_export(tmp_path) -> None:
    repo = _repo(tmp_path)
    tw = _record_fail(
        repo,
        request_id="tw-failure",
        question="Explain routing controls",
        timestamp="2026-09-07T10:00:00Z",
        country="tw",
        intent=FailureIntentFamily(task="explain", subjects=("routing controls",)),
    )
    _record_fail(
        repo,
        request_id="jp-failure",
        question="Explain citation controls",
        timestamp="2026-09-07T10:01:00Z",
        country="JP",
        intent=FailureIntentFamily(task="explain", subjects=("citation controls",)),
    )
    unknown = _record_fail(
        repo,
        request_id="unknown-failure",
        question="Explain evidence controls",
        timestamp="2026-09-07T10:02:00Z",
        country="not-a-code",
        intent=FailureIntentFamily(task="explain", subjects=("evidence controls",)),
    )
    common = {
        "range_name": "custom",
        "from_ts": "2026-09-07T00:00:00Z",
        "to_ts": "2026-09-08T00:00:00Z",
    }

    listed = repo.list_events(**common, country="tW")
    listed_clusters = {item["cluster_id"] for item in listed["items"]}
    exported = repo.export_filtered_failures(**common, country="Tw")
    exported_clusters = {
        json.loads(line)["cluster_id"] for line in exported["jsonl"].splitlines()
    }
    assert listed_clusters == exported_clusters == {tw["cluster_id"]}
    assert json.loads(exported["jsonl"])["sample_traces"][0]["country"] == "TW"
    selected = repo.export_selected_failures(event_ids=[tw["event_id"]])
    assert json.loads(selected["jsonl"])["sample_traces"][0]["country"] == "TW"

    unfiltered = repo.list_events(**common)
    assert unfiltered["total"] == 3
    unknown_export = repo.export_filtered_failures(**common, country="zz")
    assert json.loads(unknown_export["jsonl"])["cluster_id"] == unknown["cluster_id"]
    with pytest.raises(ValueError, match="country must be a two-letter"):
        repo.export_filtered_failures(**common, country="unknown")


def test_country_does_not_affect_quality_or_cluster_identity(tmp_path) -> None:
    repo = _repo(tmp_path)
    intent = FailureIntentFamily(task="explain", subjects=("routing controls",))
    tw = _record_fail(
        repo,
        request_id="same-intent-tw",
        question="Explain routing controls",
        timestamp="2026-09-07T10:00:00Z",
        country="TW",
        intent=intent,
    )
    zz = _record_fail(
        repo,
        request_id="same-intent-unknown",
        question="Explain routing controls",
        timestamp="2026-09-07T10:01:00Z",
        country="ZZ",
        intent=intent,
    )
    assert tw["score"] == zz["score"]
    assert tw["result"] == zz["result"] == "fail"
    assert tw["failure_signature"] == zz["failure_signature"]
    assert tw["cluster_id"] == zz["cluster_id"]


def test_current_filter_export_dedupes_events_to_clusters_and_can_reexport_visible_history(
    tmp_path,
) -> None:
    repo = _repo(tmp_path)
    routing = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    first = _record_fail(
        repo,
        request_id="routing-a",
        question="What is the difference between routing and replanning?",
        timestamp="2026-09-07T10:00:00Z",
        country="US",
        intent=routing,
    )
    second = _record_fail(
        repo,
        request_id="routing-b",
        question="How do routing and replanning differ?",
        timestamp="2026-09-07T10:01:00Z",
        country="US",
        intent=routing,
    )
    _record_fail(
        repo,
        request_id="citation",
        question="Explain citation controls",
        timestamp="2026-09-07T10:02:00Z",
        country="JP",
        intent=FailureIntentFamily(task="explain", subjects=("citation controls",)),
    )
    pending = repo.record_answer(
        question="How do routing and replanning differ while pending?",
        response=_response("pending"),
        latency_ms=10,
        country="US",
        timestamp="2026-09-07T10:03:00Z",
    )
    assert pending["evaluation_status"] == "PENDING"

    primary = repo.export_new_failures()
    assert primary["created"] is True
    primary_rows = [json.loads(line) for line in primary["jsonl"].splitlines()]
    assert primary_rows
    assert all(1 <= len(row["sample_traces"]) <= 5 for row in primary_rows)
    assert all(
        trace.get("schema_version", "").endswith("failure-trace/v1")
        for row in primary_rows
        for trace in row["sample_traces"]
        if not trace.get("unavailable")
    )
    assert repo.export_new_failures() == {"created": False, "reason": "NO_NEW_FAILURES"}
    assert next(
        cluster for cluster in repo.list_clusters() if cluster["cluster_id"] == first["cluster_id"]
    )["lifecycle"] == "EXPORTED"

    filtered = repo.export_filtered_failures(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="routing",
        result="fail",
        evaluation_status="ANSWERED",
        country="US",
        lifecycle="EXPORTED",
    )
    assert filtered["created"] is True
    assert filtered["mode"] == "current_filter"
    assert filtered["cluster_count"] == 1
    assert filtered["membership"] == [f"{first['cluster_id']}:1"]
    rows = [json.loads(line) for line in filtered["jsonl"].splitlines()]
    assert len(rows) == 1
    assert 1 <= len(rows[0]["sample_traces"]) <= 5
    assert rows[0]["sample_traces"][0]["schema_version"].endswith("failure-trace/v1")
    assert set(rows[0]["variants"]) == {
        first["question"],
        second["question"],
    }

    repeated = repo.export_filtered_failures(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="routing",
        result="fail",
        evaluation_status="ANSWERED",
        country="US",
        lifecycle="EXPORTED",
    )
    assert repeated["created"] is False
    assert repeated["reused"] is True
    assert repeated["batch_id"] == filtered["batch_id"]
    assert repeated["jsonl"] == filtered["jsonl"]
    assert next(
        cluster for cluster in repo.list_clusters() if cluster["cluster_id"] == first["cluster_id"]
    )["lifecycle"] == "EXPORTED"


def test_selected_export_maps_events_and_clusters_without_duplicate_cluster_records(tmp_path) -> None:
    repo = _repo(tmp_path)
    routing = FailureIntentFamily(task="compare", subjects=("replanning", "routing"))
    first = _record_fail(
        repo,
        request_id="routing-a",
        question="What is the difference between routing and replanning?",
        timestamp="2026-09-07T10:00:00Z",
        country="US",
        intent=routing,
    )
    second = _record_fail(
        repo,
        request_id="routing-b",
        question="How do routing and replanning differ?",
        timestamp="2026-09-07T10:01:00Z",
        country="US",
        intent=routing,
    )

    exported = repo.export_selected_failures(
        event_ids=[first["event_id"], second["event_id"]],
        cluster_ids=[first["cluster_id"]],
    )
    assert exported["cluster_count"] == 1
    assert exported["mode"] == "selected"
    assert len(exported["jsonl"].splitlines()) == 1
    assert repo.list_clusters()[0]["lifecycle"] == "NEW"

    repeated = repo.export_selected_failures(cluster_ids=[first["cluster_id"]])
    assert repeated["reused"] is True
    assert repeated["batch_id"] == exported["batch_id"]


def test_selected_export_rejects_non_failure_or_unknown_selection(tmp_path) -> None:
    repo = _repo(tmp_path)
    pending = repo.record_answer(
        question="Pending question",
        response=_response("pending"),
        latency_ms=10,
        timestamp="2026-09-07T10:00:00Z",
    )
    with pytest.raises(ValueError, match="clustered failures"):
        repo.export_selected_failures(event_ids=[pending["event_id"]])
    with pytest.raises(ValueError, match="unknown selected event_ids"):
        repo.export_selected_failures(event_ids=["qa_missing"])
    with pytest.raises(ValueError, match="unknown or legacy selected cluster_ids"):
        repo.export_selected_failures(cluster_ids=["aqc_missing"])


def test_export_request_contract_defaults_primary_and_supports_secondary_modes() -> None:
    assert QaExportRequest().mode == "new"
    selected = QaExportRequest(mode="selected", event_ids=["qa_1"], cluster_ids=["aqc_1"])
    assert selected.event_ids == ["qa_1"]
    assert selected.cluster_ids == ["aqc_1"]
    filtered = QaExportRequest(
        mode="current_filter",
        search="routing",
        result="fail",
        evaluation_status="ANSWERED",
        country="US",
        lifecycle="EXPORTED",
    )
    assert filtered.search == "routing"
    assert filtered.lifecycle == "EXPORTED"


def test_runtime_inbox_routes_expose_search_and_secondary_exports(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import knowledge_engine.m26_qa_inbox_integration as integration

    repo = _repo(tmp_path)
    failed = _record_fail(
        repo,
        request_id="route-fail",
        question="How do routing and replanning differ?",
        timestamp="2026-09-07T10:00:00Z",
        country="US",
        intent=FailureIntentFamily(task="compare", subjects=("replanning", "routing")),
    )
    monkeypatch.setattr(integration, "require_capability", lambda *args, **kwargs: None)
    app = FastAPI()
    app.include_router(integration._inbox_router(lambda: repo))
    client = TestClient(app)

    listed = client.get(
        "/v1/admin/qa/inbox/events",
        params={
            "range_name": "custom",
            "from_ts": "2026-09-07T00:00:00Z",
            "to_ts": "2026-09-08T00:00:00Z",
            "search": "routing",
            "result": "fail",
            "evaluation_status": "ANSWERED",
            "country": "US",
        },
    )
    assert listed.status_code == 200
    assert [row["event_id"] for row in listed.json()["data"]["items"]] == [failed["event_id"]]

    with pytest.raises(AdminAPIError) as invalid_country:
        client.get(
            "/v1/admin/qa/inbox/events",
            params={
                "range_name": "custom",
                "from_ts": "2026-09-07T00:00:00Z",
                "to_ts": "2026-09-08T00:00:00Z",
                "country": "Taiwan",
            },
        )
    assert invalid_country.value.status_code == 422
    assert invalid_country.value.code == "QA_COUNTRY_INVALID"

    lifecycle_list = client.get(
        "/v1/admin/qa/inbox/events",
        params={
            "range_name": "custom",
            "from_ts": "2026-09-07T00:00:00Z",
            "to_ts": "2026-09-08T00:00:00Z",
            "lifecycle": "NEW",
        },
    )
    assert lifecycle_list.status_code == 200
    assert [row["event_id"] for row in lifecycle_list.json()["data"]["items"]] == [
        failed["event_id"]
    ]

    filtered = client.post(
        "/v1/admin/qa/inbox/export-jsonl",
        json={
            "mode": "current_filter",
            "range_name": "custom",
            "from_ts": "2026-09-07T00:00:00Z",
            "to_ts": "2026-09-08T00:00:00Z",
            "search": "routing",
            "result": "fail",
            "evaluation_status": "ANSWERED",
            "country": "US",
        },
    )
    assert filtered.status_code == 200
    assert filtered.headers["x-qa-export-mode"] == "current_filter"
    assert json.loads(filtered.text)["cluster_id"] == failed["cluster_id"]

    with pytest.raises(AdminAPIError) as invalid_export_country:
        client.post(
            "/v1/admin/qa/inbox/export-jsonl",
            json={
                "mode": "current_filter",
                "range_name": "custom",
                "from_ts": "2026-09-07T00:00:00Z",
                "to_ts": "2026-09-08T00:00:00Z",
                "country": "Taiwan",
            },
        )
    assert invalid_export_country.value.status_code == 422
    assert invalid_export_country.value.code == "QA_EXPORT_REQUEST_INVALID"

    selected = client.post(
        "/v1/admin/qa/inbox/export-jsonl",
        json={"mode": "selected", "event_ids": [failed["event_id"]]},
    )
    assert selected.status_code == 200
    assert selected.headers["x-qa-export-mode"] == "selected"
    assert json.loads(selected.text)["cluster_id"] == failed["cluster_id"]
