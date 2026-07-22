from __future__ import annotations

import copy
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
    required_policy_coverage_payload,
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


def _resources(**overrides: int) -> dict[str, int]:
    material = {
        "same_origin_request_count": 0,
        "same_origin_transfer_bytes": 0,
        "runtime_third_party_cdn_requests": 0,
        "failed_required_same_origin_requests": 0,
        "console_errors": 0,
        "page_errors": 0,
        "long_task_count": 0,
        "long_task_max_ms": 0,
        "long_task_total_ms": 0,
    }
    material.update(overrides)
    return material


def _sample(elapsed_ms: float, phase: str) -> dict:
    return {
        "iteration": 1,
        "phase": phase,
        "elapsed_ms": elapsed_ms,
        "cache": {
            "cleared_before_sample": phase == "cold",
            "disabled_during_sample": phase == "cold",
        },
        "resources": _resources(),
    }


def _case_evidence(case_id: str) -> dict:
    if case_id == "sigma_graph":
        return {
            "node_count": 20,
            "edge_count": 28,
            "node_count_source": "graph_payload_fetch",
            "sigma_ready": True,
            "harness_selected": True,
            "one_hop_action": True,
            "two_hop_action": True,
            "open_wiki_action": True,
            "view_sources_action": True,
        }
    if case_id == "source_full_markdown":
        return {
            "viewer_id": "viewer_source_blog_agent_execution_paths",
            "source_id": "source_blog_agent_execution_paths",
            "deep_marker_present": True,
            "content_bytes": 29020,
            "line_count": 759,
            "layout": {
                "scroll_overflow": False,
                "metadata_intersection": False,
                "metadata_value_overflow": False,
            },
        }
    if case_id == "source_structured_json":
        return {
            "source_id": "source_m23_4_harness_provenance_summary",
            "parseable_json": True,
            "records_count": 3,
            "snapshot_sha256": "c9a6da0252fee27033bed294ffd22617de2130f4fa2ecd996385ea44b72cc46f",
            "truncated": False,
        }
    if case_id == "source_m3_metadata_only":
        return {
            "metadata_only_reason": (
                "No exact release-authoritative file or immutable snapshot was resolved "
                "for this governance contract in the M24.14.5 repair authority boundary."
            )
        }
    if case_id == "obsidian_vault":
        return {
            "vault_zip_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "crc_pass": True,
            "member_count": 30,
            "concept_notes": 20,
            "source_notes": 7,
            "required_members": [
                ".obsidian/app.json",
                "README.md",
                "manifest.json",
                "sources/007-m3-delivery-contract.md",
            ],
            "unresolved_wikilinks": 0,
            "bidirectional_source_concept_pairs": True,
            "deep_markers": [
                "Multi-agent is an organisational choice, not a maturity level",
                "Simple requests pay the latency and error surface of planning",
                "The production objective is not maximum planning freedom",
            ],
        }
    if case_id == "release_identity":
        return {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
            "semantic_serving_enabled": False,
            "hybrid_retrieval_enabled": False,
        }
    return {"route_ready": True}


def _case_result(case_id: str, *, cold: int = 5, warm: int = 20) -> dict:
    cold_samples = [_sample(100 + index, "cold") for index in range(cold)]
    warm_samples = [_sample(80 + index, "warm") for index in range(warm)]
    return {
        "status": "pass",
        "cold_samples": cold_samples,
        "warm_samples": warm_samples,
        "aggregates": {
            "cold_p50_ms": 102 if cold == 5 else 100,
            "cold_p95_ms": 104 if cold == 5 else 100,
            "warm_p95_ms": 98 if warm == 20 else 80,
        },
        "evidence": _case_evidence(case_id),
    }


def _interaction_result(*, warm: int = 20) -> dict:
    samples = [_sample(10 + index, "warm") for index in range(warm)]
    return {
        "status": "pass",
        "warm_samples": samples,
        "aggregates": {"warm_p95_ms": 28 if warm == 20 else 10},
        "evidence": {"setup_excluded_from_timing": True},
    }


def _interactions(*, warm: int = 20) -> dict:
    return {
        "lexical_search": {"search": _interaction_result(warm=warm)},
        "sigma_graph": {
            "search": _interaction_result(warm=warm),
            "result_selection": _interaction_result(warm=warm),
            "one_hop": _interaction_result(warm=warm),
            "two_hop": _interaction_result(warm=warm),
            "open_wiki": _interaction_result(warm=warm),
            "view_sources": _interaction_result(warm=warm),
        },
    }


def _viewport_results() -> dict:
    return {
        viewport: {
            "status": "pass",
            "horizontal_overflow": False,
            "metadata_intersection": False,
            "metadata_value_overflow": False,
            "resources": _resources(),
        }
        for viewport in ("1440x900", "1024x768", "768x900", "390x844")
    }


def _recomputed(*, cold: int = 5, warm: int = 20) -> dict:
    case_aggregate = {
        "cold_p50_ms": 102 if cold == 5 else 100,
        "cold_p95_ms": 104 if cold == 5 else 100,
        "warm_p95_ms": 98 if warm == 20 else 80,
    }
    interaction_aggregate = {"warm_p95_ms": 28 if warm == 20 else 10}
    return {
        "cases": {case_id: case_aggregate for case_id in BENCHMARK_CASE_IDS},
        "interactions": {
            "lexical_search": {"search": interaction_aggregate},
            "sigma_graph": {
                "search": interaction_aggregate,
                "result_selection": interaction_aggregate,
                "one_hop": interaction_aggregate,
                "two_hop": interaction_aggregate,
                "open_wiki": interaction_aggregate,
                "view_sources": interaction_aggregate,
            },
        },
        "errors": {
            "console_errors": 0,
            "page_errors": 0,
            "failed_required_same_origin_requests": 0,
            "access_leakage": 0,
        },
        "resources": {
            "same_origin_request_count": 0,
            "same_origin_transfer_bytes": 0,
            "cold_traversal_transfer_bytes": 0,
            "runtime_third_party_cdn_requests": 0,
        },
        "long_tasks": {"count": 0, "max_ms": 0, "total_ms": 0},
        "decision": "pass",
        "reason_codes": [],
    }


def _authenticated_result(
    *,
    authority: str = "authenticated_live",
    cold: int = 5,
    warm: int = 20,
    deployment_id: str = "11111111-2222-4333-8444-555555555555",
) -> dict:
    recomputed = _recomputed(cold=cold, warm=warm)
    payload = {
        "schema_version": M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
        "authority": authority,
        "deployment_id": deployment_id,
        "generated_at_utc": "2026-07-22T00:00:00Z",
        "benchmark_policy_sha256": benchmark_policy_sha256(),
        "benchmark_cases_sha256": benchmark_cases_sha256(),
        "environment": {
            "browser_name": "chromium",
            "browser_version": "127.0.0.0",
            "os_family": "Darwin",
            "viewport": {"width": 1440, "height": 900},
        },
        "identities": {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
            "deployment_id": deployment_id,
        },
        "iterations": {"cold_completed": cold, "warm_completed": warm},
        "cases": {
            case_id: _case_result(case_id, cold=cold, warm=warm) for case_id in BENCHMARK_CASE_IDS
        },
        "interactions": _interactions(warm=warm),
        "viewport_results": _viewport_results(),
        "errors": recomputed["errors"],
        "resource_summary": recomputed["resources"],
        "long_tasks": recomputed["long_tasks"],
        "recomputed_aggregates": recomputed,
        "decision": recomputed["decision"],
        "reason_codes": recomputed["reason_codes"],
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
    assert report["deployment_identity"]["pre_repair_deployment"]
    assert (
        report["deployment_identity"]["post_repair_deployment_recorded_in_return_handoff"] is True
    )
    assert (
        "--browser-channel chrome --deployment-id e73c3563-01eb-4c37-b2a6-500e2b86b87c"
        in report["daniel_actions"][0]["command"]
    )
    assert report["policy_coverage"] == required_policy_coverage_payload()
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

    assert (
        validate_authenticated_benchmark_result(
            result,
            expected_deployment_id="11111111-2222-4333-8444-555555555555",
        )
        == result
    )


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda data: data.update({"authority": "local_exact_site_browser_regression"}),
            "authority",
        ),
        (lambda data: data.update({"self_sha256": "0" * 64}), "digest"),
        (lambda data: data.update({"deployment_id": "protected-current"}), "placeholder"),
        (lambda data: data["identities"].update({"deployment_id": "different"}), "identity"),
        (lambda data: data["identities"].update({"production_retrieval": "hybrid"}), "retrieval"),
        (lambda data: data["iterations"].update({"cold_completed": 4}), "cold"),
        (lambda data: data["iterations"].update({"warm_completed": 19}), "warm"),
        (lambda data: data["errors"].update({"console_errors": 1}), "console"),
        (lambda data: data.update({"decision": "done"}), "decision"),
        (
            lambda data: data["cases"]["overview"]["aggregates"].update({"warm_p95_ms": 1}),
            "aggregate",
        ),
        (lambda data: data.update({"reason_codes": ["manual-pass"]}), "reason"),
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
    ("mutator", "reason"),
    [
        (
            lambda data: data["cases"]["sigma_graph"]["evidence"].update({"node_count": 19}),
            "decision",
        ),
        (
            lambda data: data["cases"]["sigma_graph"]["evidence"].update(
                {"node_count_source": "constant"}
            ),
            "graph counts",
        ),
        (
            lambda data: data["cases"]["source_full_markdown"]["evidence"].update(
                {"line_count": 20}
            ),
            "decision",
        ),
        (
            lambda data: data["cases"]["source_structured_json"]["evidence"].update(
                {"snapshot_sha256": "0" * 64}
            ),
            "decision",
        ),
        (
            lambda data: data["cases"]["source_m3_metadata_only"]["evidence"].update(
                {"metadata_only_reason": "invented"}
            ),
            "decision",
        ),
        (
            lambda data: data["cases"]["obsidian_vault"]["evidence"].update(
                {"unresolved_wikilinks": 1}
            ),
            "decision",
        ),
        (lambda data: data["viewport_results"].pop("390x844"), "viewport"),
        (
            lambda data: data["cases"]["overview"]["cold_samples"][0]["cache"].update(
                {"cleared_before_sample": False}
            ),
            "cold sample",
        ),
        (
            lambda data: data["cases"]["overview"]["warm_samples"][0]["cache"].update(
                {"cleared_before_sample": True}
            ),
            "warm sample",
        ),
        (
            lambda data: data["cases"]["overview"]["warm_samples"][0]["resources"].update(
                {"runtime_third_party_cdn_requests": 1}
            ),
            "resource",
        ),
        (
            lambda data: data["cases"]["overview"]["warm_samples"][0]["resources"].update(
                {"long_task_max_ms": 251}
            ),
            "long-task",
        ),
    ],
)
def test_m24_14_6_authenticated_result_validator_rejects_evidence_and_policy_drift(
    mutator,
    reason: str,
) -> None:
    result = _authenticated_result()
    mutator(result)
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
        ("cdp_endpoint", "http://127.0.0.1:45678"),
        ("debugging_port", "45678"),
        ("chrome_executable_path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("process_id", "12345"),
        ("user_data_dir", "/tmp/m24-14-6-chrome-profile"),
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
    result = _authenticated_result(
        authority="local_exact_site_browser_regression",
        cold=1,
        warm=1,
        deployment_id="local-exact-site",
    )

    assert validate_local_regression_result(result) == result
    with pytest.raises(M24_14_6ValidationError, match="authority"):
        validate_authenticated_benchmark_result(result)


def test_m24_14_6_expected_deployment_id_is_authoritative() -> None:
    result = _authenticated_result(deployment_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")

    with pytest.raises(M24_14_6ValidationError, match="expected"):
        validate_authenticated_benchmark_result(
            result,
            expected_deployment_id="ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        )


def test_m24_14_6_validator_rejects_legacy_aggregate_only_schema() -> None:
    result = _authenticated_result()
    legacy = copy.deepcopy(result)
    legacy["cases"]["overview"].pop("cold_samples")
    legacy["cases"]["overview"]["cold_samples_ms"] = [100, 101, 102, 103, 104]
    legacy = finalize_authenticated_benchmark_result(legacy)

    with pytest.raises(M24_14_6ValidationError, match="sample list"):
        validate_authenticated_benchmark_result(legacy)
