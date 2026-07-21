from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.m24_14_6_authenticated_performance import (
    BENCHMARK_CASE_IDS,
    BENCHMARK_CASES_PATH,
    BENCHMARK_POLICY_PATH,
    HUMAN_ACCEPTANCE_PATH,
    M24_14_6_ACCEPTED_VAULT_SHA256,
    M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
    M24_14_6_FOUNDATION_SHA,
    M24_14_6_STATUS,
    PENDING_ACCEPTANCE_PATH,
    M24_14_6ValidationError,
    benchmark_cases_payload,
    benchmark_cases_sha256,
    benchmark_policy_payload,
    benchmark_policy_sha256,
    build_m24_14_5_human_acceptance_record,
    build_m24_14_6_pending_acceptance_report,
    finalize_authenticated_benchmark_result,
    validate_authenticated_benchmark_result,
    validate_local_regression_result,
    write_m24_14_6_stage_a_artifacts,
)
from knowledge_engine.m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _case_result() -> dict:
    return {
        "status": "pass",
        "cold_samples_ms": [100, 101, 102, 103, 104],
        "warm_samples_ms": [80 + index for index in range(20)],
        "cold_p50_ms": 102,
        "cold_p95_ms": 104,
        "warm_p95_ms": 98,
        "evidence": {"route_ready": True},
    }


def _authenticated_result() -> dict:
    payload = {
        "schema_version": M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
        "authority": "authenticated_live",
        "generated_at_utc": "2026-07-22T00:00:00Z",
        "benchmark_policy_sha256": benchmark_policy_sha256(),
        "benchmark_cases_sha256": benchmark_cases_sha256(),
        "environment": {
            "browser_name": "chromium",
            "browser_version": "127.0.0.0",
            "os_family": "Darwin",
            "viewport": {"width": 1440, "height": 900},
            "network_effective_type": "4g",
        },
        "identities": {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
            "deployment_id": "protected-current",
        },
        "iterations": {"cold_completed": 5, "warm_completed": 20},
        "cases": {case_id: _case_result() for case_id in BENCHMARK_CASE_IDS},
        "errors": {
            "console_errors": 0,
            "page_errors": 0,
            "failed_required_same_origin_requests": 0,
            "access_leakage": 0,
        },
        "resource_summary": {
            "same_origin_request_count": 44,
            "runtime_third_party_cdn_requests": 0,
        },
        "long_tasks": {"count": 0, "max_ms": 0, "total_ms": 0},
        "decision": "pass",
        "self_sha256": "",
    }
    return finalize_authenticated_benchmark_result(payload)


def test_m24_14_6_policy_cases_and_reports_are_deterministic() -> None:
    artifacts = write_m24_14_6_stage_a_artifacts()

    assert {item.path for item in artifacts} == {
        BENCHMARK_POLICY_PATH.as_posix(),
        BENCHMARK_CASES_PATH.as_posix(),
        HUMAN_ACCEPTANCE_PATH.as_posix(),
        PENDING_ACCEPTANCE_PATH.as_posix(),
    }
    assert _json(BENCHMARK_POLICY_PATH) == benchmark_policy_payload()
    assert _json(BENCHMARK_CASES_PATH) == benchmark_cases_payload()
    assert benchmark_policy_sha256() == benchmark_policy_sha256()
    assert benchmark_cases_sha256() == benchmark_cases_sha256()


def test_m24_14_6_pending_report_has_exact_gate_and_one_daniel_action() -> None:
    report = build_m24_14_6_pending_acceptance_report()

    assert report["status"] == M24_14_6_STATUS
    assert report["release_id"] == CANONICAL_RELEASE_ID
    assert report["daniel_action_count"] == 1
    assert len(report["daniel_actions"]) == 1
    assert report["result_authority_required"] == "authenticated_live"
    assert report["local_ci_regression_authority"] == "local_exact_site_browser_regression"
    assert report["final_acceptance_claimed"] is False
    assert report["boundaries"]["production_retrieval"] == "lexical"
    assert report["boundaries"]["semantic_serving_enabled"] is False
    assert report["boundaries"]["temporary_public_bypass_used"] is False


def test_m24_14_5_human_acceptance_record_does_not_overclaim() -> None:
    record = build_m24_14_5_human_acceptance_record()

    accepted = {item["item"] for item in record["accepted_from_daniel_package_statements"]}
    assert "access_login" in accepted
    assert "release_identity" in accepted
    assert "authenticated_live_performance" not in accepted
    assert "authenticated_live_performance" in record["pending_retest"]
    assert record["boundaries"]["human_final_acceptance_claimed"] is False
    assert record["boundaries"]["production_retrieval"] == "lexical"


def test_m24_14_6_authenticated_result_validator_accepts_sanitized_result() -> None:
    result = _authenticated_result()

    assert validate_authenticated_benchmark_result(result) == result


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda data: data.update({"authority": "local_exact_site_browser_regression"}),
            "authority",
        ),
        (lambda data: data.update({"self_sha256": "0" * 64}), "digest"),
        (lambda data: data["identities"].update({"production_retrieval": "hybrid"}), "retrieval"),
        (lambda data: data["iterations"].update({"cold_completed": 4}), "cold"),
        (lambda data: data["iterations"].update({"warm_completed": 19}), "warm"),
        (lambda data: data["errors"].update({"console_errors": 1}), "console"),
        (lambda data: data.update({"decision": "done"}), "decision"),
    ],
)
def test_m24_14_6_authenticated_result_validator_rejects_invalid_results(
    mutator,
    reason: str,
) -> None:
    result = _authenticated_result()
    mutator(result)
    if reason != "digest":
        result = finalize_authenticated_benchmark_result(result)

    with pytest.raises(M24_14_6ValidationError, match=reason):
        validate_authenticated_benchmark_result(result)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cookie", "redacted"),
        ("authorization", "redacted"),
        ("token", "redacted"),
        ("email", "redacted"),
        ("raw_header", "redacted"),
        ("profile_path", "redacted"),
        ("note", "operator@example.invalid"),
        ("note", "Bearer abcdefghijklmnopqrstuvwxyz"),
    ],
)
def test_m24_14_6_authenticated_result_validator_rejects_sensitive_material(
    key: str,
    value: str,
) -> None:
    result = _authenticated_result()
    result["environment"][key] = value
    result = finalize_authenticated_benchmark_result(result)

    with pytest.raises(M24_14_6ValidationError, match="sensitive|forbidden"):
        validate_authenticated_benchmark_result(result)


def test_m24_14_6_local_regression_result_has_no_authenticated_authority() -> None:
    result = _authenticated_result()
    result["authority"] = "local_exact_site_browser_regression"
    result["iterations"] = {"cold_completed": 1, "warm_completed": 1}
    result = finalize_authenticated_benchmark_result(result)

    assert validate_local_regression_result(result) == result
    with pytest.raises(M24_14_6ValidationError, match="authority"):
        validate_authenticated_benchmark_result(result)
