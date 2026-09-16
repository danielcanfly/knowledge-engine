from __future__ import annotations

import json

import pytest

from knowledge_engine.m26_qa_inbox_integration import _trusted_country
from knowledge_engine.qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    AnswerQualityEvaluation,
    StaticAnswerQualityEvaluator,
    canonical_failure_provenance,
)
from knowledge_engine.qa_answer_quality_repository_v2 import QualifiedQaRepositoryV2
from knowledge_engine.qa_failure_clustering import FailureIntentFamily
from knowledge_engine.storage import FileObjectStore


def _response(request_id: str, *, release: str, index_revision: str) -> dict:
    return {
        "request_id": request_id,
        "status": "owner_only_cited_answer",
        "answer_text": "A supported but incomplete answer.",
        "citations": [{"citation_id": "c1", "source_id": "s1"}],
        "selected_evidence": [{"source_id": "s1", "quote": "support"}],
        "release_id": release,
        "canonical_runtime": {
            "build_sha": f"build-{release}",
            "schema_version": "runtime/v1",
        },
        "identities": {
            "production_manifest_sha256": index_revision,
            "production_pointer_digest": f"pointer-{index_revision}",
            "resolved_gate_self_sha256": f"gate-{index_revision}",
        },
        "integrity": {
            "unsupported_accepted_claims": 0,
            "material_claim_support_verified": True,
            "citation_locator_valid": True,
        },
    }


def _repo(tmp_path) -> QualifiedQaRepositoryV2:
    return QualifiedQaRepositoryV2(
        FileObjectStore(tmp_path / "objects"),
        db_path=tmp_path / "qa.sqlite",
    )


def _evaluator(*, task: str, subject: str) -> StaticAnswerQualityEvaluator:
    criteria = dict(ANSWER_QUALITY_CRITERION_MAX)
    criteria["completeness_facets"] = 0
    criteria["correctness_grounding"] = 20
    score = sum(criteria.values())
    stage, failure_class, signature = canonical_failure_provenance(
        hard_fail_codes=(), criterion_scores=criteria
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
            failure_intent=FailureIntentFamily(task=task, subjects=(subject,)),
        )
    )


def _record_fail(
    repo: QualifiedQaRepositoryV2,
    *,
    request_id: str,
    question: str,
    timestamp: str,
    latency_ms: int,
    country: str,
    release: str,
    index_revision: str,
    task: str,
    subject: str,
) -> dict:
    response = _response(request_id, release=release, index_revision=index_revision)
    event = repo.record_answer(
        question=question,
        response=response,
        latency_ms=latency_ms,
        country=country,
        timestamp=timestamp,
    )
    return repo.evaluate_event(
        event["event_id"],
        evaluator=_evaluator(task=task, subject=subject),
        answer_payload=response,
    )


def test_advanced_filters_are_composable_and_query_compact_metadata(tmp_path) -> None:
    repo = _repo(tmp_path)
    first = _record_fail(
        repo,
        request_id="first",
        question="Explain routing controls",
        timestamp="2026-09-07T10:00:00Z",
        latency_ms=120,
        country="US",
        release="rel-a",
        index_revision="idx-a",
        task="explain",
        subject="routing controls",
    )
    _record_fail(
        repo,
        request_id="second",
        question="Compare citation controls",
        timestamp="2026-09-07T11:00:00Z",
        latency_ms=4200,
        country="JP",
        release="rel-b",
        index_revision="idx-b",
        task="compare",
        subject="citation controls",
    )

    page = repo.list_events(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        failure_type="quality_below_threshold",
        score_min=80,
        score_max=80,
        latency_min_ms=100,
        latency_max_ms=500,
        release="rel-a",
        index_revision="idx-a",
        provider="QUALIFIED-PROVIDER",
        model="qualified-model",
    )
    assert page["total"] == 1
    assert page["items"][0]["event_id"] == first["event_id"]

    with pytest.raises(ValueError, match="score minimum"):
        repo.list_events(
            range_name="custom",
            from_ts="2026-09-07T00:00:00Z",
            to_ts="2026-09-08T00:00:00Z",
            score_min=90,
            score_max=80,
        )


def test_filtered_jsonl_records_frozen_metadata_and_reuses_identical_snapshot(tmp_path) -> None:
    repo = _repo(tmp_path)
    first = _record_fail(
        repo,
        request_id="export-a",
        question="Explain routing controls",
        timestamp="2026-09-07T10:00:00Z",
        latency_ms=120,
        country="US",
        release="rel-a",
        index_revision="idx-a",
        task="explain",
        subject="routing controls",
    )
    _record_fail(
        repo,
        request_id="export-b",
        question="Why do routing controls matter?",
        timestamp="2026-09-07T10:05:00Z",
        latency_ms=180,
        country="US",
        release="rel-b",
        index_revision="idx-b",
        task="explain",
        subject="routing controls",
    )

    exported = repo.export_filtered_failures(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="routing",
        failure_type="quality_below_threshold",
        score_min=80,
        score_max=80,
        latency_max_ms=500,
        provider="qualified-provider",
        model="qualified-model",
    )
    assert exported["created"] is True
    rows = [json.loads(line) for line in exported["jsonl"].splitlines()]
    assert rows
    row = next(item for item in rows if item["cluster_id"] == first["cluster_id"])
    assert row["exported_at"] == exported["created_at"]
    assert row["event_count"] >= 1
    assert row["release_range"]["first_seen_at"] is not None
    assert row["release_range"]["last_seen_at"] is not None
    assert row["filters"]["failure_type"] == "quality_below_threshold"
    assert row["filters"]["score_min"] == 80
    assert row["filters"]["provider"] == "qualified-provider"
    assert row["export_mode"] == "current_filter"
    assert 1 <= len(row["sample_traces"]) <= 5

    repeated = repo.export_filtered_failures(
        range_name="custom",
        from_ts="2026-09-07T00:00:00Z",
        to_ts="2026-09-08T00:00:00Z",
        search="routing",
        failure_type="quality_below_threshold",
        score_min=80,
        score_max=80,
        latency_max_ms=500,
        provider="qualified-provider",
        model="qualified-model",
    )
    assert repeated["created"] is False
    assert repeated["reused"] is True
    assert repeated["batch_id"] == exported["batch_id"]
    assert repeated["jsonl"] == exported["jsonl"]


def test_primary_export_marks_new_clusters_exported_and_excludes_them_next_time(tmp_path) -> None:
    repo = _repo(tmp_path)
    _record_fail(
        repo,
        request_id="new-a",
        question="Explain routing controls",
        timestamp="2026-09-07T10:00:00Z",
        latency_ms=120,
        country="US",
        release="rel-a",
        index_revision="idx-a",
        task="explain",
        subject="routing controls",
    )
    _record_fail(
        repo,
        request_id="new-b",
        question="Compare citation controls",
        timestamp="2026-09-07T11:00:00Z",
        latency_ms=220,
        country="JP",
        release="rel-b",
        index_revision="idx-b",
        task="compare",
        subject="citation controls",
    )

    first = repo.export_new_failures()
    assert first["created"] is True
    rows = [json.loads(line) for line in first["jsonl"].splitlines()]
    assert len(rows) == first["cluster_count"]
    assert all(row["exported_at"] == first["created_at"] for row in rows)
    assert all(row["filters"]["already_exported"] is False for row in rows)
    assert {item["lifecycle"] for item in repo.list_clusters()} == {"EXPORTED"}

    second = repo.export_new_failures()
    assert second == {"created": False, "reason": "NO_NEW_FAILURES", "mode": "new"}


def test_http_country_capture_trusts_only_qualified_proxy_boundary(monkeypatch) -> None:
    monkeypatch.setenv("M26_PUBLIC_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("M26_QA_TRUST_CLOUDFLARE_COUNTRY", "true")
    headers = [
        (b"cf-ray", b"edge-ray"),
        (b"cf-ipcountry", b"tw"),
    ]

    direct = {"type": "http", "client": ("203.0.113.8", 443), "headers": headers}
    assert _trusted_country(direct) == "ZZ"

    trusted = {"type": "http", "client": ("10.20.30.40", 443), "headers": headers}
    assert _trusted_country(trusted) == "TW"

    no_edge_proof = {
        "type": "http",
        "client": ("10.20.30.40", 443),
        "headers": [(b"cf-ipcountry", b"TW")],
    }
    assert _trusted_country(no_edge_proof) == "ZZ"
