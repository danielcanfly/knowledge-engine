from __future__ import annotations

from pathlib import Path

from knowledge_engine.golden_query_baseline import (
    GoldenQueryBaseline,
    evaluate_golden_query_baseline,
)
from knowledge_engine.golden_query_suite import GoldenQueryCase, run_golden_query_suite
from knowledge_engine.runtime import Runtime


def _report(tmp_path: Path, built_store) -> dict:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    cases = [
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
    return run_golden_query_suite(runtime=runtime, cases=cases)


def _baseline(report: dict) -> GoldenQueryBaseline:
    return GoldenQueryBaseline(
        baseline_id="m12-3-reference-quality-baseline",
        suite_id=report["suite_id"],
        release_id=report["release"]["release_id"],
        manifest_sha256=report["release"]["manifest_sha256"],
        min_passed_count=2,
        max_failed_count=0,
        max_release_blocking_count=1,
        required_case_ids=frozenset(
            {
                "m12-answer-internal-knowledge-compiler",
                "m12-public-acl-non-answer",
            }
        ),
        approved_audiences=frozenset({"public", "internal"}),
        notes="M12.3 locks the M12.2 suite as the first runtime quality floor.",
    )


def test_golden_query_baseline_passes_and_replays(tmp_path: Path, built_store) -> None:
    report = _report(tmp_path, built_store)
    baseline = _baseline(report)

    first = evaluate_golden_query_baseline(baseline=baseline, report=report)
    second = evaluate_golden_query_baseline(baseline=baseline, report=report)

    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["baseline_contract_id"].startswith("gqbaseline_")
    assert first["baseline_check_id"].startswith("gqbaselinecheck_")
    assert first["passed"] is True
    assert first["release_blocking"] is False
    assert first["failure_reasons"] == []
    assert first["governance"] == {
        "canonical_source_write_permitted": False,
        "candidate_write_permitted": False,
        "release_write_permitted": False,
        "production_write_permitted": False,
        "permanent_ledger_append_permitted": False,
    }


def test_golden_query_baseline_fails_closed_on_quality_regression(
    tmp_path: Path, built_store
) -> None:
    report = _report(tmp_path, built_store)
    baseline = _baseline(report)
    regressed = {
        **report,
        "aggregate": {
            **report["aggregate"],
            "passed_count": 1,
            "failed_count": 1,
        },
        "failure_reasons": ["required_concept_missing"],
    }

    check = evaluate_golden_query_baseline(baseline=baseline, report=regressed)

    assert check["passed"] is False
    assert check["release_blocking"] is True
    assert check["failure_reasons"] == [
        "failed_count_regression",
        "passed_count_regression",
        "unexpected_failure_reason",
    ]
    assert check["unexpected_failure_reasons"] == ["required_concept_missing"]


def test_golden_query_baseline_fails_closed_on_identity_or_audience_drift(
    tmp_path: Path, built_store
) -> None:
    report = _report(tmp_path, built_store)
    baseline = _baseline(report)
    drifted = {
        **report,
        "suite_id": "gqsuite_wrong",
        "release": {
            **report["release"],
            "manifest_sha256": "wrong",
        },
        "cases": [
            *report["cases"],
            {
                "case_id": "m12-unapproved-audience",
                "audiences": ["private"],
            },
        ],
    }

    check = evaluate_golden_query_baseline(baseline=baseline, report=drifted)

    assert check["passed"] is False
    assert check["release_blocking"] is True
    assert check["failure_reasons"] == [
        "audience_broadening",
        "manifest_sha256_mismatch",
        "suite_id_mismatch",
    ]
    assert check["audience_broadening"] == ["private"]


def test_golden_query_baseline_requires_complete_contract() -> None:
    try:
        GoldenQueryBaseline(
            baseline_id="",
            suite_id="gqsuite_x",
            release_id="release_x",
            manifest_sha256="manifest",
            min_passed_count=0,
            approved_audiences=frozenset({"public"}),
            notes="complete",
        )
    except ValueError as exc:
        assert str(exc) == "baseline_id is required"
    else:  # pragma: no cover
        raise AssertionError("baseline contract should fail closed")
