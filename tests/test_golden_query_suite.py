from __future__ import annotations

from pathlib import Path

from knowledge_engine.golden_query_suite import GoldenQueryCase, run_golden_query_suite
from knowledge_engine.runtime import Runtime


def _cases() -> list[GoldenQueryCase]:
    return [
        GoldenQueryCase(
            case_id="m12-answer-internal-knowledge-compiler",
            query="knowledge compiler",
            audiences=frozenset({"public", "internal"}),
            expected_status="answered",
            min_selected_results=1,
            release_blocking=False,
        ),
        GoldenQueryCase(
            case_id="m12-public-acl-non-answer",
            query="knowledge compiler",
            audiences=frozenset({"public"}),
            expected_status="not_found",
            expected_reasons=frozenset({"no_authorized_match", "no_retrieval_candidates"}),
            release_blocking=True,
        ),
    ]


def test_golden_query_suite_is_deterministic_and_replayable(
    tmp_path: Path, built_store
) -> None:
    store, compiled, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")

    first = run_golden_query_suite(runtime=runtime, cases=list(reversed(_cases())))
    second = run_golden_query_suite(runtime=runtime, cases=_cases())

    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["suite_id"].startswith("gqsuite_")
    assert first["report_id"].startswith("gqreport_")
    assert first["passed"] is True
    assert first["release_blocking"] is False
    assert first["release"]["release_id"] == compiled.release_id
    assert first["aggregate"] == {
        "case_count": 2,
        "passed_count": 2,
        "failed_count": 0,
        "release_blocking_count": 1,
    }
    assert [case["case_id"] for case in first["cases"]] == sorted(
        case.case_id for case in _cases()
    )


def test_golden_query_suite_fails_closed_on_required_concept_mismatch(
    tmp_path: Path, built_store
) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    bad_case = GoldenQueryCase(
        case_id="m12-answer-wrong-required-concept",
        query="knowledge compiler",
        audiences=frozenset({"public", "internal"}),
        expected_status="answered",
        min_selected_results=1,
        required_concepts=frozenset({"concepts/does-not-exist"}),
        release_blocking=False,
    )

    report = run_golden_query_suite(runtime=runtime, cases=[bad_case])

    assert report["passed"] is False
    assert report["release_blocking"] is True
    assert report["aggregate"]["failed_count"] == 1
    assert report["failure_reasons"] == ["required_concept_missing"]
    assert report["cases"][0]["missing_required_concepts"] == ["concepts/does-not-exist"]


def test_golden_query_suite_fails_closed_on_acl_forbidden_concept(
    tmp_path: Path, built_store
) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    baseline = runtime.query("knowledge compiler", {"public", "internal"})
    forbidden = str(baseline["results"][0]["concept_id"])
    bad_case = GoldenQueryCase(
        case_id="m12-forbidden-concept",
        query="knowledge compiler",
        audiences=frozenset({"public", "internal"}),
        expected_status="answered",
        forbidden_concepts=frozenset({forbidden}),
        release_blocking=False,
    )

    report = run_golden_query_suite(runtime=runtime, cases=[bad_case])

    assert report["passed"] is False
    assert report["release_blocking"] is True
    assert report["failure_reasons"] == ["forbidden_concept_returned"]
    assert report["cases"][0]["forbidden_concepts_returned"] == [forbidden]
