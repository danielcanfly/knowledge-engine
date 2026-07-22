from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

M24_14_6_POLICY_SCHEMA = "knowledge-engine-m24-14-6-benchmark-policy/v1"
M24_14_6_CASES_SCHEMA = "knowledge-engine-m24-14-6-benchmark-cases/v1"
M24_14_6_ACCEPTANCE_MATRIX_SCHEMA = "knowledge-engine-m24-14-6-acceptance-matrix/v1"
M24_14_6_HUMAN_ACCEPTANCE_SCHEMA = "knowledge-engine-m24-14-6-human-acceptance-record/v1"
M24_14_6_PENDING_ACCEPTANCE_SCHEMA = "knowledge-engine-m24-14-6-pending-final-acceptance/v1"
M24_14_6_AUTHENTICATED_RESULT_SCHEMA = "knowledge-engine-m24-14-6-authenticated-benchmark-result/v1"
M24_14_6_FINAL_ACCEPTANCE_SCHEMA = "knowledge-engine-m24-14-6-final-acceptance/v1"
M24_14_6_M25_ENTRY_BASELINE_SCHEMA = "knowledge-engine-m24-14-6-m25-entry-baseline/v2"

M24_14_6_STATUS = (
    "m24_14_6_system_chrome_auth_compatibility_repaired_pending_daniel_authenticated_benchmark"
)
M24_14_6_ISSUE_NUMBER = 1030
M24_14_6_CLOSURE_SEAL_ISSUE_NUMBER = 1034
M24_14_6_PRODUCT_ACCEPTANCE_SHA = "b9dc2f1f8a0f30bed81bea2cafe31fb11aa0bbaf"
M24_14_6_CLOSURE_SEAL_BASE_SHA = M24_14_6_PRODUCT_ACCEPTANCE_SHA
M24_14_6_CLOSURE_SEAL_REF = "refs/tags/m24-14-6-final-closure"
M24_14_6_BENCHMARK_FILE_SHA256 = (
    "3af8c6debadf8bc896952c4b9e48497a7de6971ccad489b40ae8ea23c5440c45"
)
M24_14_6_BENCHMARK_SELF_SHA256 = (
    "6fe285a4b684a61ec6c0d2b05db74d2a3afebf742dfb5e8d4c4800c0d475fe4f"
)
M24_14_6_REQUIRED_BASE_SHA = "28131aa4cb262a306bc792f95e55d69a20f5d818"
M24_14_6_FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
M24_14_6_ACCEPTED_VAULT_SHA256 = "054f2a349c173d62de0d2e7b575fbb97a46611ac435653eb6c9eca5255272f64"
M24_14_6_PRE_STAGE_A_PROTECTED_DEPLOYMENT = "5361997c-fe53-47a5-998e-81244a6470ab"
M24_14_6_IMMEDIATE_ROLLBACK_DEPLOYMENT = "b570b0c7-a812-4878-8573-e7b7d41faf78"
M24_14_6_SECONDARY_ROLLBACK_DEPLOYMENT = "586deae3-d679-45e2-8542-ec6845f9f2e7"
M24_14_6_ACCEPTED_DEPLOYMENT = "e73c3563-01eb-4c37-b2a6-500e2b86b87c"
M24_14_6_PAGES_PROJECT = "llm-wiki-m24-internal"
M24_14_6_CUSTOM_HOSTNAME = "https://m24-internal.danielcanfly.com/"
M24_14_6_DANIEL_COMMAND = (
    "python scripts/m24_14_6_authenticated_benchmark.py --headed --capture-auth "
    "--browser-channel chrome --deployment-id e73c3563-01eb-4c37-b2a6-500e2b86b87c"
)
M24_14_6_PRE_REPAIR_DEPLOYMENT = "ee80820e-727b-4a05-8b47-121fad33c1d5"
M24_14_6_FINAL_SURFACE_DEPLOYMENT = "90804e78-9975-4e70-8fdd-d5cd9a9ee753"
PLACEHOLDER_DEPLOYMENT_IDS = frozenset({"", "protected-current", "current", "latest"})

M24_14_6_ROOT = Path("pilot/m24/m24-14-6")
BENCHMARK_POLICY_PATH = M24_14_6_ROOT / "benchmark-policy.json"
BENCHMARK_CASES_PATH = M24_14_6_ROOT / "benchmark-cases.json"
HUMAN_ACCEPTANCE_PATH = M24_14_6_ROOT / "m24-14-5-human-acceptance.json"
PENDING_ACCEPTANCE_PATH = M24_14_6_ROOT / "m24-14-6-pending-acceptance.json"
FINAL_ACCEPTANCE_PATH = M24_14_6_ROOT / "m24-14-6-final-acceptance.json"
M25_ENTRY_BASELINE_PATH = M24_14_6_ROOT / "m25-entry-baseline.json"
BENCHMARK_EVIDENCE_PATH = (
    M24_14_6_ROOT / "evidence/authenticated-benchmark-result.sanitized.json"
)
BENCHMARK_EVIDENCE_METADATA_PATH = (
    M24_14_6_ROOT / "evidence/authenticated-benchmark-result.metadata.json"
)

BENCHMARK_CASE_IDS = (
    "overview",
    "concept_wiki_full",
    "concept_wiki_bounded",
    "lexical_search",
    "sigma_graph",
    "source_full_markdown",
    "source_reverse_link",
    "source_structured_json",
    "source_m3_metadata_only",
    "obsidian_vault",
    "release_identity",
)

SENSITIVE_KEY_RE = re.compile(
    r"(cookie|authorization|token|email|account|jwt|header|local[_-]?storage|"
    r"session[_-]?storage|profile[_-]?path|user[_-]?data|cdp|devtools|"
    r"debug(?:ging)?[_-]?port|endpoint|executable|process[_-]?id|pid|ip[_-]?address)",
    re.I,
)
SENSITIVE_VALUE_RE = re.compile(
    r"(cf-access-jwt-assertion|Bearer\s+[A-Za-z0-9._~-]+|"
    r"cloudflareaccess\.com/cdn-cgi/access|@)",
    re.I,
)


class M24_14_6ValidationError(ValueError):
    pass


class M24_14_6Artifact(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise M24_14_6ValidationError("percentile requires at least one sample")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return ordered[index]


def benchmark_policy_payload() -> dict[str, Any]:
    return {
        "schema_version": M24_14_6_POLICY_SCHEMA,
        "release_identity": {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        },
        "iterations": {
            "cold_min": 5,
            "warm_min": 20,
        },
        "timing_budgets_ms": {
            "overview_cold_p50_max": 3000,
            "overview_cold_p95_max": 5000,
            "overview_warm_p95_max": 2500,
            "standard_route_warm_p95_max": 1500,
            "graph_route_warm_p95_max": 3000,
            "lexical_interaction_warm_p95_max": 500,
            "graph_interaction_warm_p95_max": 750,
            "source_deep_marker_warm_p95_max": 1500,
            "vault_download_p95_max": 3000,
            "long_task_total_per_case_max": 500,
            "individual_long_task_max": 250,
        },
        "hard_gates": {
            "console_errors_max": 0,
            "page_errors_max": 0,
            "failed_required_same_origin_requests_max": 0,
            "access_leakage_max": 0,
            "graph_node_count": 20,
            "graph_edge_count": 28,
            "horizontal_overflow_max": 0,
            "metadata_intersection_max": 0,
        },
        "resource_guardrails": {
            "runtime_third_party_cdn_requests_max": 0,
            "cold_traversal_transfer_bytes_max": 10_000_000,
            "required_request_count_max": 100,
        },
        "viewports": [
            {"width": 1440, "height": 900, "performance_authority": True},
            {"width": 1024, "height": 768, "performance_authority": False},
            {"width": 768, "height": 900, "performance_authority": False},
            {"width": 390, "height": 844, "performance_authority": False},
        ],
        "decisions": [
            "pass",
            "pass_with_documented_network_variance",
            "repair_required",
        ],
    }


def benchmark_cases_payload(authority: str = "authenticated_live") -> dict[str, Any]:
    return {
        "schema_version": M24_14_6_CASES_SCHEMA,
        "cases": [
            {"id": case_id, "authority": authority, "required": True}
            for case_id in BENCHMARK_CASE_IDS
        ],
    }


def required_policy_coverage_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-engine-m24-14-6-policy-coverage/v1",
        "rule": "every field has collection, enforcement, validator, and test coverage",
        "required_policy_fields": [
            "iterations.cold_min",
            "iterations.warm_min",
            "timing_budgets_ms.overview_cold_p50_max",
            "timing_budgets_ms.overview_cold_p95_max",
            "timing_budgets_ms.overview_warm_p95_max",
            "timing_budgets_ms.standard_route_warm_p95_max",
            "timing_budgets_ms.graph_route_warm_p95_max",
            "timing_budgets_ms.lexical_interaction_warm_p95_max",
            "timing_budgets_ms.graph_interaction_warm_p95_max",
            "timing_budgets_ms.source_deep_marker_warm_p95_max",
            "timing_budgets_ms.vault_download_p95_max",
            "timing_budgets_ms.long_task_total_per_case_max",
            "timing_budgets_ms.individual_long_task_max",
            "hard_gates.console_errors_max",
            "hard_gates.page_errors_max",
            "hard_gates.failed_required_same_origin_requests_max",
            "hard_gates.access_leakage_max",
            "hard_gates.graph_node_count",
            "hard_gates.graph_edge_count",
            "hard_gates.horizontal_overflow_max",
            "hard_gates.metadata_intersection_max",
            "resource_guardrails.runtime_third_party_cdn_requests_max",
            "resource_guardrails.cold_traversal_transfer_bytes_max",
            "resource_guardrails.required_request_count_max",
            "viewports[1440x900]",
            "viewports[1024x768]",
            "viewports[768x900]",
            "viewports[390x844]",
        ],
    }


def acceptance_matrix_payload() -> dict[str, Any]:
    return {
        "schema_version": M24_14_6_ACCEPTANCE_MATRIX_SCHEMA,
        "items": [
            {"id": "access_login", "prior_status": "explicitly_accepted"},
            {"id": "release_identity", "prior_status": "explicitly_accepted"},
            {
                "id": "graph_render_and_navigation",
                "prior_status": "observed_with_screenshot",
            },
            {
                "id": "concept_wiki_full_and_bounded",
                "prior_status": "observed_with_screenshot",
            },
            {
                "id": "source_viewer_full_content",
                "prior_status": "explicitly_accepted",
            },
            {
                "id": "source_metadata_responsive",
                "prior_status": "explicitly_accepted",
            },
            {
                "id": "obsidian_opens_and_full_source",
                "prior_status": "explicitly_accepted",
            },
            {
                "id": "obsidian_bidirectional_links",
                "prior_status": "pending_m24_14_6_retest",
            },
            {
                "id": "structured_json_source_complete",
                "prior_status": "pending_m24_14_6_retest",
            },
            {
                "id": "m3_metadata_only_reason",
                "prior_status": "pending_m24_14_6_retest",
            },
            {
                "id": "authenticated_live_performance",
                "prior_status": "pending_m24_14_6_retest",
            },
            {"id": "semantic_hybrid_production", "prior_status": "governed_deferred"},
            {"id": "production_answer_serving", "prior_status": "governed_deferred"},
            {
                "id": "large_scale_ingestion",
                "prior_status": "governed_deferred_to_m25",
            },
        ],
    }


def benchmark_policy_sha256() -> str:
    return canonical_sha256(benchmark_policy_payload())


def benchmark_cases_sha256() -> str:
    return canonical_sha256(benchmark_cases_payload())


def build_m24_14_5_human_acceptance_record(
    *,
    output_path: Path = HUMAN_ACCEPTANCE_PATH,
) -> dict[str, Any]:
    payload = {
        "schema_version": M24_14_6_HUMAN_ACCEPTANCE_SCHEMA,
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_commit_sha": CANONICAL_SOURCE_SHA,
        "accepted_from_daniel_package_statements": [
            {
                "item": "access_login",
                "status": "accepted",
                "basis": "Daniel explicitly reported Cloudflare Access login completed.",
            },
            {
                "item": "release_identity",
                "status": "accepted",
                "basis": (
                    "Daniel explicitly reported homepage, canonical Release ID, "
                    "and manifest digest normal."
                ),
            },
            {
                "item": "source_viewer_full_content",
                "status": "accepted",
                "basis": (
                    "Daniel explicitly reported Sources, Inspect, source content, "
                    "and deep markers passed."
                ),
            },
            {
                "item": "source_metadata_responsive",
                "status": "accepted",
                "basis": (
                    "Daniel explicitly reported Origin and Integrity overlap repair "
                    "passed before M24.14.6."
                ),
            },
            {
                "item": "obsidian_opens_and_full_source",
                "status": "accepted",
                "basis": (
                    "Daniel explicitly reported the current Vault downloaded and opened normally."
                ),
            },
        ],
        "observed_but_not_final_acceptance": [
            "graph_render_and_navigation",
            "concept_wiki_full_and_bounded",
        ],
        "pending_retest": [
            "obsidian_bidirectional_links",
            "structured_json_source_complete",
            "m3_metadata_only_reason",
            "authenticated_live_performance",
        ],
        "governed_deferred": [
            "semantic_hybrid_production",
            "production_answer_serving",
            "large_scale_ingestion",
        ],
        "boundaries": {
            "production_retrieval": "lexical",
            "semantic_serving_enabled": False,
            "hybrid_retrieval_enabled": False,
            "production_answer_serving_enabled": False,
            "human_final_acceptance_claimed": False,
        },
        "acceptance_matrix": acceptance_matrix_payload(),
    }
    payload["self_sha256"] = canonical_sha256(payload)
    _write_json(output_path, payload)
    return payload


def build_m24_14_6_pending_acceptance_report(
    *,
    output_path: Path = PENDING_ACCEPTANCE_PATH,
    deployed_url_label: str = "protected_custom_hostname",
) -> dict[str, Any]:
    payload = {
        "schema_version": M24_14_6_PENDING_ACCEPTANCE_SCHEMA,
        "status": M24_14_6_STATUS,
        "issue_number": M24_14_6_ISSUE_NUMBER,
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_commit_sha": CANONICAL_SOURCE_SHA,
        "foundation_sha": M24_14_6_FOUNDATION_SHA,
        "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        "deployment_identity": {
            "pre_repair_deployment": M24_14_6_PRE_REPAIR_DEPLOYMENT,
            "pre_stage_a_protected_deployment": M24_14_6_PRE_STAGE_A_PROTECTED_DEPLOYMENT,
            "post_repair_deployment_recorded_in_return_handoff": True,
            "benchmark_requires_explicit_deployment_id": True,
        },
        "rollback_deployments": [
            M24_14_6_IMMEDIATE_ROLLBACK_DEPLOYMENT,
            M24_14_6_SECONDARY_ROLLBACK_DEPLOYMENT,
        ],
        "pages_project": M24_14_6_PAGES_PROJECT,
        "deployed_url_label": deployed_url_label,
        "benchmark_policy_path": BENCHMARK_POLICY_PATH.as_posix(),
        "benchmark_policy_sha256": benchmark_policy_sha256(),
        "benchmark_cases_path": BENCHMARK_CASES_PATH.as_posix(),
        "benchmark_cases_sha256": benchmark_cases_sha256(),
        "result_schema_version": M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
        "result_authority_required": "authenticated_live",
        "daniel_action_count": 1,
        "daniel_actions": [
            {
                "id": "run_authenticated_browser_benchmark_after_access_login",
                "required_actor": "Daniel",
                "command": M24_14_6_DANIEL_COMMAND,
                "return_artifact": "sanitized authenticated benchmark JSON only",
            }
        ],
        "policy_coverage": required_policy_coverage_payload(),
        "local_ci_regression_authority": "local_exact_site_browser_regression",
        "final_acceptance_claimed": False,
        "manual_browser_acceptance_claimed": False,
        "boundaries": {
            "cloudflare_access_required": True,
            "access_policy_population_changed": False,
            "service_token_bypass_used": False,
            "temporary_public_bypass_used": False,
            "production_retrieval": "lexical",
            "semantic_serving_enabled": False,
            "hybrid_retrieval_enabled": False,
            "source_mutation": False,
            "foundation_mutation": False,
            "qdrant_mutation": False,
            "r2_production_mutation": False,
            "production_pointer_mutation": False,
        },
    }
    payload["self_sha256"] = canonical_sha256(payload)
    _write_json(output_path, payload)
    return payload


def write_m24_14_6_stage_a_artifacts() -> list[M24_14_6Artifact]:
    payloads = [
        (BENCHMARK_POLICY_PATH, benchmark_policy_payload()),
        (BENCHMARK_CASES_PATH, benchmark_cases_payload()),
        (HUMAN_ACCEPTANCE_PATH, build_m24_14_5_human_acceptance_record()),
        (PENDING_ACCEPTANCE_PATH, build_m24_14_6_pending_acceptance_report()),
    ]
    artifacts: list[M24_14_6Artifact] = []
    for path, payload in payloads:
        _write_json(path, payload)
        artifacts.append(
            M24_14_6Artifact(
                path=path.as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return artifacts


def build_m24_14_6_final_acceptance_report(
    benchmark_result: Mapping[str, Any],
    *,
    output_path: Path = FINAL_ACCEPTANCE_PATH,
    benchmark_result_file_sha256: str | None = None,
    closure_seal_issue_number: int = M24_14_6_CLOSURE_SEAL_ISSUE_NUMBER,
    closure_seal_pr_number: int | None = None,
) -> dict[str, Any]:
    result = validate_authenticated_benchmark_result(
        benchmark_result,
        expected_deployment_id=M24_14_6_ACCEPTED_DEPLOYMENT,
    )
    recomputed = _require_mapping(result["recomputed_aggregates"], "recomputed_aggregates")
    payload = {
        "schema_version": M24_14_6_FINAL_ACCEPTANCE_SCHEMA,
        "status": "m24_14_6_authenticated_performance_and_final_acceptance_complete",
        "m24_14_6_closed": result["decision"] in {
            "pass",
            "pass_with_documented_network_variance",
        },
        "issue_number": M24_14_6_ISSUE_NUMBER,
        "issues": {
            "chrome_compatibility": M24_14_6_ISSUE_NUMBER,
            "final_closure_seal": closure_seal_issue_number,
        },
        "closure_pr": closure_seal_pr_number,
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "engine_product_acceptance_sha": M24_14_6_PRODUCT_ACCEPTANCE_SHA,
        "closure_seal_base_sha": M24_14_6_CLOSURE_SEAL_BASE_SHA,
        "closure_seal_ref": M24_14_6_CLOSURE_SEAL_REF,
        "closure_seal_attestation": "post_merge",
        "validated_benchmark_result": {
            "authority": result["authority"],
            "decision": result["decision"],
            "reason_codes": result["reason_codes"],
            "self_sha256": result["self_sha256"],
            "file_sha256": benchmark_result_file_sha256 or "external_artifact",
            "generated_at_utc": result["generated_at_utc"],
        },
        "exact_identities": {
            "deployment_id": result["deployment_id"],
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
        },
        "deployment_and_rollback": {
            "pages_project": M24_14_6_PAGES_PROJECT,
            "protected_custom_hostname": M24_14_6_CUSTOM_HOSTNAME,
            "accepted_deployment_id": result["deployment_id"],
            "final_surface_deployment_id": M24_14_6_FINAL_SURFACE_DEPLOYMENT,
            "rollback_deployments": [
                M24_14_6_IMMEDIATE_ROLLBACK_DEPLOYMENT,
                M24_14_6_SECONDARY_ROLLBACK_DEPLOYMENT,
            ],
        },
        "benchmark_policy": {
            "path": BENCHMARK_POLICY_PATH.as_posix(),
            "sha256": benchmark_policy_sha256(),
            "cases_path": BENCHMARK_CASES_PATH.as_posix(),
            "cases_sha256": benchmark_cases_sha256(),
        },
        "recomputed_metrics": {
            "cases": recomputed["cases"],
            "interactions": recomputed["interactions"],
            "errors": recomputed["errors"],
            "resources": recomputed["resources"],
            "long_tasks": recomputed["long_tasks"],
        },
        "hard_gate_outcome": {
            "console_errors": result["errors"]["console_errors"],
            "page_errors": result["errors"]["page_errors"],
            "failed_required_same_origin_requests": result["errors"][
                "failed_required_same_origin_requests"
            ],
            "access_leakage": result["errors"]["access_leakage"],
            "runtime_third_party_cdn_requests": result["resource_summary"][
                "runtime_third_party_cdn_requests"
            ],
            "passed": result["decision"] in {"pass", "pass_with_documented_network_variance"},
        },
        "final_acceptance_matrix": {
            "daniel_browser_acceptance": "recorded_from_prior_explicit_acceptance",
            "authenticated_live_performance": result["decision"],
            "internal_product_baseline": "accepted",
            "independent_clean_room_replay": "not_run",
            "independent_human_unseen_source_exercise": "governed_deferred_to_m25",
            "semantic_hybrid_production": "governed_deferred",
            "production_answer_serving": "governed_deferred",
            "large_scale_ingestion": "governed_deferred_to_m25",
        },
        "known_limitations_and_governed_defers": [
            {
                "item": "production_semantic_hybrid_retrieval",
                "status": "governed_deferred",
                "reason": "M24.14.6 closes the protected internal product baseline only.",
            },
            {
                "item": "production_answer_serving",
                "status": "governed_deferred",
                "reason": "Production answer serving remains outside M24.14.6 authority.",
            },
            {
                "item": "large_scale_ingestion",
                "status": "governed_deferred_to_m25",
                "reason": "M25 owns production admission and larger ingestion work.",
            },
            {
                "item": "independent_human_unseen_source_exercise",
                "status": "governed_deferred_to_m25",
                "reason": "No separate human operator exercise was performed in M24.14.6.",
            },
        ],
        "protected_mutations": _m24_14_6_protected_mutations_payload(),
        "m25_entry_baseline_path": M25_ENTRY_BASELINE_PATH.as_posix(),
    }
    payload["self_sha256"] = canonical_sha256(payload)
    _write_json(output_path, payload)
    return payload


def build_m24_14_6_m25_entry_baseline(
    final_acceptance_report: Mapping[str, Any],
    *,
    output_path: Path = M25_ENTRY_BASELINE_PATH,
) -> dict[str, Any]:
    report = _require_mapping(final_acceptance_report, "final_acceptance_report")
    if report.get("status") != "m24_14_6_authenticated_performance_and_final_acceptance_complete":
        raise M24_14_6ValidationError("final acceptance report is not complete")
    identities = _require_mapping(report.get("exact_identities"), "exact_identities")
    payload = {
        "schema_version": M24_14_6_M25_ENTRY_BASELINE_SCHEMA,
        "m24_14_6_closed": True,
        "daniel_acceptance_recorded": True,
        "authenticated_performance_decision": report["validated_benchmark_result"]["decision"],
        "engine_product_acceptance_sha": report["engine_product_acceptance_sha"],
        "closure_seal_base_sha": report["closure_seal_base_sha"],
        "closure_seal_ref": report["closure_seal_ref"],
        "closure_seal_attestation": "post_merge",
        "closure_seal_issue_number": report["issues"]["final_closure_seal"],
        "closure_seal_pr_number": report["closure_pr"],
        "deployment_id": identities["deployment_id"],
        "release_id": identities["release_id"],
        "manifest_sha256": identities["manifest_sha256"],
        "source_sha": identities["source_sha"],
        "foundation_sha": identities["foundation_sha"],
        "vault_sha256": identities["vault_sha256"],
        "accepted_benchmark_deployment_id": identities["deployment_id"],
        "final_surface_deployment_id": report["deployment_and_rollback"][
            "final_surface_deployment_id"
        ],
        "benchmark_file_sha256": report["validated_benchmark_result"]["file_sha256"],
        "benchmark_self_sha256": report["validated_benchmark_result"]["self_sha256"],
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "production_answer_serving_enabled": False,
        "large_scale_ingestion_enabled": False,
        "protected_mutations": _m24_14_6_protected_mutations_payload(),
        "m25_allowed_next": [
            "production_admission_pipeline",
            "semantic_promotion_decision_before_production_semantic_or_hybrid_retrieval",
            "large_scale_ingestion_planning",
        ],
    }
    payload["self_sha256"] = canonical_sha256(payload)
    _write_json(output_path, payload)
    return payload


def write_m24_14_6_stage_b_artifacts(
    benchmark_result: Mapping[str, Any],
    *,
    benchmark_result_file_sha256: str | None = None,
    closure_seal_issue_number: int = M24_14_6_CLOSURE_SEAL_ISSUE_NUMBER,
    closure_seal_pr_number: int | None = None,
    final_acceptance_path: Path = FINAL_ACCEPTANCE_PATH,
    m25_entry_baseline_path: Path = M25_ENTRY_BASELINE_PATH,
) -> list[M24_14_6Artifact]:
    final_report = build_m24_14_6_final_acceptance_report(
        benchmark_result,
        benchmark_result_file_sha256=benchmark_result_file_sha256,
        closure_seal_issue_number=closure_seal_issue_number,
        closure_seal_pr_number=closure_seal_pr_number,
        output_path=final_acceptance_path,
    )
    build_m24_14_6_m25_entry_baseline(final_report, output_path=m25_entry_baseline_path)
    return [
        M24_14_6Artifact(
            path=final_acceptance_path.as_posix(),
            sha256=hashlib.sha256(final_acceptance_path.read_bytes()).hexdigest(),
        ),
        M24_14_6Artifact(
            path=m25_entry_baseline_path.as_posix(),
            sha256=hashlib.sha256(m25_entry_baseline_path.read_bytes()).hexdigest(),
        ),
    ]


def _m24_14_6_protected_mutations_payload() -> dict[str, bool]:
    return {
        "source_mutation": False,
        "foundation_mutation": False,
        "qdrant_mutation": False,
        "r2_production_mutation": False,
        "production_pointer_mutation": False,
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "production_answer_serving_enabled": False,
        "large_scale_ingestion_enabled": False,
        "cloudflare_access_population_broadened": False,
        "temporary_public_bypass_used": False,
        "service_token_bypass_used": False,
    }


def finalized_result_sha256(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material["self_sha256"] = ""
    return canonical_sha256(material)


def finalize_authenticated_benchmark_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    finalized = json.loads(json.dumps(payload, ensure_ascii=False))
    finalized["self_sha256"] = ""
    finalized["self_sha256"] = finalized_result_sha256(finalized)
    return finalized


def recompute_benchmark_decision(
    payload: Mapping[str, Any],
    *,
    expected_deployment_id: str | None = None,
    require_authenticated_iterations: bool = True,
) -> dict[str, Any]:
    result = _require_mapping(payload, "result")
    _assert_no_sensitive_material(result)
    if result.get("schema_version") != M24_14_6_AUTHENTICATED_RESULT_SCHEMA:
        raise M24_14_6ValidationError("unexpected benchmark result schema")
    if result.get("benchmark_policy_sha256") != benchmark_policy_sha256():
        raise M24_14_6ValidationError("benchmark policy digest mismatch")
    if result.get("benchmark_cases_sha256") != benchmark_cases_sha256():
        raise M24_14_6ValidationError("benchmark cases digest mismatch")

    deployment_id = str(result.get("deployment_id") or "")
    _validate_deployment_id(deployment_id, expected_deployment_id=expected_deployment_id)
    identities = _require_mapping(result.get("identities"), "identities")
    if identities.get("deployment_id") != deployment_id:
        raise M24_14_6ValidationError("deployment identity mismatch")
    expected_identities = benchmark_policy_payload()["release_identity"]
    expected_pairs = {
        "release_id": expected_identities["release_id"],
        "manifest_sha256": expected_identities["manifest_sha256"],
        "source_sha": expected_identities["source_sha"],
        "foundation_sha": expected_identities["foundation_sha"],
        "vault_sha256": expected_identities["vault_sha256"],
        "production_retrieval": "lexical",
    }
    for key, expected in expected_pairs.items():
        if identities.get(key) != expected:
            raise M24_14_6ValidationError(f"identity drift: {key}")

    iterations = _require_mapping(result.get("iterations"), "iterations")
    required_iterations = benchmark_policy_payload()["iterations"]
    cold_min = required_iterations["cold_min"] if require_authenticated_iterations else 1
    warm_min = required_iterations["warm_min"] if require_authenticated_iterations else 1
    if int(iterations.get("cold_completed", 0)) < cold_min:
        raise M24_14_6ValidationError("insufficient cold iterations")
    if int(iterations.get("warm_completed", 0)) < warm_min:
        raise M24_14_6ValidationError("insufficient warm iterations")

    cases = _require_mapping(result.get("cases"), "cases")
    missing_cases = sorted(set(BENCHMARK_CASE_IDS) - set(cases))
    if missing_cases:
        raise M24_14_6ValidationError(f"missing benchmark cases: {missing_cases}")
    reason_codes: list[str] = []
    recomputed_cases: dict[str, Any] = {}
    for case_id in BENCHMARK_CASE_IDS:
        recomputed_cases[case_id] = _validate_case_record(
            case_id,
            _require_mapping(cases[case_id], f"cases.{case_id}"),
            cold_min=cold_min,
            warm_min=warm_min,
            reason_codes=reason_codes,
        )
    _validate_case_evidence(cases, reason_codes)

    interactions = _require_mapping(result.get("interactions"), "interactions")
    recomputed_interactions = _validate_interactions(interactions, warm_min, reason_codes)
    viewport_results = _require_mapping(result.get("viewport_results"), "viewport_results")
    _validate_viewports(viewport_results, reason_codes)

    recomputed_errors = _recompute_errors(cases, interactions, viewport_results)
    errors = _require_mapping(result.get("errors"), "errors")
    for key in (
        "console_errors",
        "page_errors",
        "failed_required_same_origin_requests",
        "access_leakage",
    ):
        if not isinstance(errors.get(key), int) or errors[key] < 0:
            raise M24_14_6ValidationError(f"invalid error counter: {key}")
        if errors[key] != recomputed_errors[key]:
            raise M24_14_6ValidationError(f"error counter aggregate mismatch: {key}")

    hard_gates = benchmark_policy_payload()["hard_gates"]
    if errors["console_errors"] > hard_gates["console_errors_max"]:
        raise M24_14_6ValidationError("console error hard gate failed")
    if errors["page_errors"] > hard_gates["page_errors_max"]:
        raise M24_14_6ValidationError("page error hard gate failed")
    if (
        errors["failed_required_same_origin_requests"]
        > hard_gates["failed_required_same_origin_requests_max"]
    ):
        raise M24_14_6ValidationError("same-origin request hard gate failed")
    if errors["access_leakage"] > hard_gates["access_leakage_max"]:
        raise M24_14_6ValidationError("access leakage hard gate failed")

    resource_summary = _require_mapping(result.get("resource_summary"), "resource_summary")
    recomputed_resources = _recompute_resource_summary(cases, interactions, viewport_results)
    for key, expected in recomputed_resources.items():
        if resource_summary.get(key) != expected:
            raise M24_14_6ValidationError(f"resource aggregate mismatch: {key}")
    _enforce_resource_guardrails(recomputed_resources, reason_codes)

    long_tasks = _require_mapping(result.get("long_tasks"), "long_tasks")
    recomputed_long_tasks = _recompute_long_tasks(cases, interactions, viewport_results)
    for key, expected in recomputed_long_tasks.items():
        if long_tasks.get(key) != expected:
            raise M24_14_6ValidationError(f"long-task aggregate mismatch: {key}")

    recomputed_decision = _decision_for_reason_codes(reason_codes)
    if result.get("decision") not in benchmark_policy_payload()["decisions"]:
        raise M24_14_6ValidationError("invalid benchmark decision")
    if result.get("decision") != recomputed_decision:
        raise M24_14_6ValidationError("decision does not match validator recomputation")

    stored_reasons = result.get("reason_codes", [])
    if stored_reasons != reason_codes:
        raise M24_14_6ValidationError("reason codes do not match validator recomputation")
    aggregates = _require_mapping(result.get("recomputed_aggregates"), "recomputed_aggregates")
    expected_aggregates = {
        "cases": recomputed_cases,
        "interactions": recomputed_interactions,
        "errors": recomputed_errors,
        "resources": recomputed_resources,
        "long_tasks": recomputed_long_tasks,
        "decision": recomputed_decision,
        "reason_codes": reason_codes,
    }
    if aggregates != expected_aggregates:
        raise M24_14_6ValidationError("stored aggregate metrics do not match recomputation")
    return expected_aggregates


def validate_authenticated_benchmark_result(
    payload: Mapping[str, Any],
    *,
    expected_deployment_id: str | None = None,
) -> dict[str, Any]:
    result = _require_mapping(payload, "result")
    _assert_no_sensitive_material(result)
    if result.get("authority") != "authenticated_live":
        raise M24_14_6ValidationError("authenticated live authority is required")
    if result.get("self_sha256") != finalized_result_sha256(result):
        raise M24_14_6ValidationError("benchmark result self digest mismatch")
    recompute_benchmark_decision(
        result,
        expected_deployment_id=expected_deployment_id,
        require_authenticated_iterations=True,
    )
    return dict(result)


def validate_local_regression_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = _require_mapping(payload, "result")
    _assert_no_sensitive_material(result)
    if result.get("schema_version") != M24_14_6_AUTHENTICATED_RESULT_SCHEMA:
        raise M24_14_6ValidationError("unexpected benchmark result schema")
    if result.get("authority") != "local_exact_site_browser_regression":
        raise M24_14_6ValidationError("local regression authority is required")
    if result.get("self_sha256") != finalized_result_sha256(result):
        raise M24_14_6ValidationError("benchmark result self digest mismatch")
    recompute_benchmark_decision(
        result,
        expected_deployment_id=None,
        require_authenticated_iterations=False,
    )
    return dict(result)


def _validate_deployment_id(
    deployment_id: str,
    *,
    expected_deployment_id: str | None = None,
) -> None:
    if deployment_id in PLACEHOLDER_DEPLOYMENT_IDS:
        raise M24_14_6ValidationError("deployment identity placeholder rejected")
    if expected_deployment_id is not None:
        _validate_deployment_id(expected_deployment_id)
        if deployment_id != expected_deployment_id:
            raise M24_14_6ValidationError("deployment identity does not match expected ID")


def _validate_case_record(
    case_id: str,
    record: Mapping[str, Any],
    *,
    cold_min: int,
    warm_min: int,
    reason_codes: list[str],
) -> dict[str, Any]:
    if record.get("status") != "pass":
        reason_codes.append(f"{case_id}:case_status_failed")
    cold_samples = _sample_list(record.get("cold_samples"), f"{case_id}.cold_samples")
    warm_samples = _sample_list(record.get("warm_samples"), f"{case_id}.warm_samples")
    if len(cold_samples) < cold_min:
        raise M24_14_6ValidationError(f"{case_id} insufficient cold samples")
    if len(warm_samples) < warm_min:
        raise M24_14_6ValidationError(f"{case_id} insufficient warm samples")
    for sample in cold_samples:
        cache = _require_mapping(sample.get("cache"), f"{case_id}.cold.cache")
        if cache.get("cleared_before_sample") is not True:
            raise M24_14_6ValidationError(f"{case_id} cold sample did not clear cache")
        if cache.get("disabled_during_sample") is not True:
            raise M24_14_6ValidationError(f"{case_id} cold sample did not disable cache")
    for sample in warm_samples:
        cache = _require_mapping(sample.get("cache"), f"{case_id}.warm.cache")
        if cache.get("cleared_before_sample") is True:
            raise M24_14_6ValidationError(f"{case_id} warm sample cleared cache")
    recomputed = {
        "cold_p50_ms": _rounded_nearest_rank(_elapsed(cold_samples), 50),
        "cold_p95_ms": _rounded_nearest_rank(_elapsed(cold_samples), 95),
        "warm_p95_ms": _rounded_nearest_rank(_elapsed(warm_samples), 95),
    }
    if record.get("aggregates") != recomputed:
        raise M24_14_6ValidationError(f"{case_id} aggregate percentile mismatch")
    _enforce_case_budget(case_id, recomputed, cold_samples, warm_samples, reason_codes)
    _enforce_sample_resource_limits(case_id, [*cold_samples, *warm_samples], reason_codes)
    return recomputed


def _validate_interactions(
    interactions: Mapping[str, Any],
    warm_min: int,
    reason_codes: list[str],
) -> dict[str, Any]:
    expected = {
        "lexical_search": ("search",),
        "sigma_graph": (
            "search",
            "result_selection",
            "one_hop",
            "two_hop",
            "open_wiki",
            "view_sources",
        ),
    }
    recomputed: dict[str, Any] = {}
    for group, names in expected.items():
        group_payload = _require_mapping(interactions.get(group), f"interactions.{group}")
        recomputed[group] = {}
        for name in names:
            record = _require_mapping(group_payload.get(name), f"interactions.{group}.{name}")
            samples = _sample_list(record.get("warm_samples"), f"interactions.{group}.{name}")
            if len(samples) < warm_min:
                raise M24_14_6ValidationError(f"{group}.{name} insufficient samples")
            if record.get("status") != "pass":
                reason_codes.append(f"{group}.{name}:interaction_failed")
            aggregate = {"warm_p95_ms": _rounded_nearest_rank(_elapsed(samples), 95)}
            if record.get("aggregates") != aggregate:
                raise M24_14_6ValidationError(f"{group}.{name} aggregate mismatch")
            budget_key = (
                "lexical_interaction_warm_p95_max"
                if group == "lexical_search"
                else "graph_interaction_warm_p95_max"
            )
            budget = benchmark_policy_payload()["timing_budgets_ms"][budget_key]
            if aggregate["warm_p95_ms"] > budget:
                reason_codes.append(f"{group}.{name}:{budget_key}_exceeded")
            _enforce_sample_resource_limits(f"{group}.{name}", samples, reason_codes)
            recomputed[group][name] = aggregate
    return recomputed


def _validate_case_evidence(cases: Mapping[str, Any], reason_codes: list[str]) -> None:
    graph = _require_mapping(cases["sigma_graph"].get("evidence"), "sigma_graph.evidence")
    gates = benchmark_policy_payload()["hard_gates"]
    if graph.get("node_count") != gates["graph_node_count"]:
        reason_codes.append("sigma_graph:node_count_mismatch")
    if graph.get("edge_count") != gates["graph_edge_count"]:
        reason_codes.append("sigma_graph:edge_count_mismatch")
    if graph.get("node_count_source") in {"constant", None}:
        raise M24_14_6ValidationError("graph counts must come from measured source")
    for key in (
        "sigma_ready",
        "harness_selected",
        "one_hop_action",
        "two_hop_action",
        "open_wiki_action",
        "view_sources_action",
    ):
        if graph.get(key) is not True:
            reason_codes.append(f"sigma_graph:{key}_missing")

    source = _require_mapping(
        cases["source_full_markdown"].get("evidence"),
        "source_full_markdown.evidence",
    )
    if source.get("viewer_id") != "viewer_source_blog_agent_execution_paths":
        reason_codes.append("source_full_markdown:viewer_id_mismatch")
    if source.get("source_id") != "source_blog_agent_execution_paths":
        reason_codes.append("source_full_markdown:source_id_mismatch")
    if source.get("deep_marker_present") is not True:
        reason_codes.append("source_full_markdown:deep_marker_missing")
    if int(source.get("content_bytes", 0)) < 28_000:
        reason_codes.append("source_full_markdown:content_bytes_too_small")
    if int(source.get("line_count", 0)) != 759:
        reason_codes.append("source_full_markdown:line_count_mismatch")
    layout = _require_mapping(source.get("layout"), "source_full_markdown.layout")
    if layout.get("scroll_overflow") is True:
        reason_codes.append("source_full_markdown:horizontal_overflow")
    if layout.get("metadata_intersection") is True:
        reason_codes.append("source_full_markdown:metadata_intersection")
    if layout.get("metadata_value_overflow") is True:
        reason_codes.append("source_full_markdown:metadata_value_overflow")

    structured = _require_mapping(
        cases["source_structured_json"].get("evidence"),
        "source_structured_json.evidence",
    )
    if structured.get("source_id") != "source_m23_4_harness_provenance_summary":
        reason_codes.append("source_structured_json:source_id_mismatch")
    if structured.get("parseable_json") is not True:
        reason_codes.append("source_structured_json:not_parseable_json")
    if structured.get("records_count", 0) <= 0:
        reason_codes.append("source_structured_json:no_records")
    if structured.get("truncated") is True:
        reason_codes.append("source_structured_json:truncated")
    expected_structured_sha = "c9a6da0252fee27033bed294ffd22617de2130f4fa2ecd996385ea44b72cc46f"
    if structured.get("snapshot_sha256") != expected_structured_sha:
        reason_codes.append("source_structured_json:snapshot_sha_mismatch")

    m3 = _require_mapping(cases["source_m3_metadata_only"].get("evidence"), "m3.evidence")
    exact_reason = (
        "No exact release-authoritative file or immutable snapshot was resolved for this "
        "governance contract in the M24.14.5 repair authority boundary."
    )
    if m3.get("metadata_only_reason") != exact_reason:
        reason_codes.append("source_m3_metadata_only:reason_mismatch")

    vault = _require_mapping(cases["obsidian_vault"].get("evidence"), "obsidian_vault.evidence")
    if vault.get("vault_zip_sha256") != M24_14_6_ACCEPTED_VAULT_SHA256:
        reason_codes.append("obsidian_vault:sha_mismatch")
    if vault.get("crc_pass") is not True:
        reason_codes.append("obsidian_vault:crc_failed")
    if vault.get("member_count") != 30:
        reason_codes.append("obsidian_vault:member_count_mismatch")
    if vault.get("concept_notes") != 20:
        reason_codes.append("obsidian_vault:concept_count_mismatch")
    if vault.get("source_notes") != 7:
        reason_codes.append("obsidian_vault:source_count_mismatch")
    if vault.get("unresolved_wikilinks") != 0:
        reason_codes.append("obsidian_vault:unresolved_wikilinks")
    if vault.get("bidirectional_source_concept_pairs") is not True:
        reason_codes.append("obsidian_vault:bidirectional_pairs_failed")
    for marker in (
        "Multi-agent is an organisational choice, not a maturity level",
        "Simple requests pay the latency and error surface of planning",
        "The production objective is not maximum planning freedom",
    ):
        if marker not in set(vault.get("deep_markers", [])):
            reason_codes.append("obsidian_vault:deep_marker_missing")
    required_members = {
        ".obsidian/app.json",
        "README.md",
        "manifest.json",
        "sources/007-m3-delivery-contract.md",
    }
    if not required_members.issubset(set(vault.get("required_members", []))):
        reason_codes.append("obsidian_vault:required_member_missing")

    release = _require_mapping(cases["release_identity"].get("evidence"), "release.evidence")
    expected = benchmark_policy_payload()["release_identity"]
    if release.get("release_id") != expected["release_id"]:
        reason_codes.append("release_identity:release_mismatch")
    if release.get("manifest_sha256") != expected["manifest_sha256"]:
        reason_codes.append("release_identity:manifest_mismatch")
    if release.get("source_sha") != expected["source_sha"]:
        reason_codes.append("release_identity:source_mismatch")
    if release.get("foundation_sha") != expected["foundation_sha"]:
        reason_codes.append("release_identity:foundation_mismatch")
    if release.get("vault_sha256") != expected["vault_sha256"]:
        reason_codes.append("release_identity:vault_mismatch")
    if release.get("production_retrieval") != "lexical":
        reason_codes.append("release_identity:retrieval_mismatch")
    if release.get("semantic_serving_enabled") is not False:
        reason_codes.append("release_identity:semantic_enabled")
    if release.get("hybrid_retrieval_enabled") is not False:
        reason_codes.append("release_identity:hybrid_enabled")


def _validate_viewports(viewport_results: Mapping[str, Any], reason_codes: list[str]) -> None:
    required = {
        f"{item['width']}x{item['height']}" for item in benchmark_policy_payload()["viewports"]
    }
    missing = required - set(viewport_results)
    if missing:
        raise M24_14_6ValidationError(f"missing viewport results: {sorted(missing)}")
    for viewport in sorted(required):
        record = _require_mapping(viewport_results[viewport], f"viewport.{viewport}")
        if record.get("status") != "pass":
            reason_codes.append(f"viewport:{viewport}:failed")
        resources = _resources(record)
        if resources["console_errors"] or resources["page_errors"]:
            reason_codes.append(f"viewport:{viewport}:browser_errors")
        if record.get("horizontal_overflow") is True:
            reason_codes.append(f"viewport:{viewport}:horizontal_overflow")
        if record.get("metadata_intersection") is True:
            reason_codes.append(f"viewport:{viewport}:metadata_intersection")
        if record.get("metadata_value_overflow") is True:
            reason_codes.append(f"viewport:{viewport}:metadata_value_overflow")


def _enforce_case_budget(
    case_id: str,
    aggregates: Mapping[str, float],
    cold_samples: list[Mapping[str, Any]],
    warm_samples: list[Mapping[str, Any]],
    reason_codes: list[str],
) -> None:
    budgets = benchmark_policy_payload()["timing_budgets_ms"]
    if case_id == "overview":
        if aggregates["cold_p50_ms"] > budgets["overview_cold_p50_max"]:
            reason_codes.append("overview:overview_cold_p50_max_exceeded")
        if aggregates["cold_p95_ms"] > budgets["overview_cold_p95_max"]:
            reason_codes.append("overview:overview_cold_p95_max_exceeded")
        if aggregates["warm_p95_ms"] > budgets["overview_warm_p95_max"]:
            reason_codes.append("overview:overview_warm_p95_max_exceeded")
    elif case_id == "sigma_graph":
        if aggregates["warm_p95_ms"] > budgets["graph_route_warm_p95_max"]:
            reason_codes.append("sigma_graph:graph_route_warm_p95_max_exceeded")
    elif case_id == "source_full_markdown":
        if aggregates["warm_p95_ms"] > budgets["source_deep_marker_warm_p95_max"]:
            reason_codes.append("source_full_markdown:source_deep_marker_warm_p95_max_exceeded")
    elif case_id == "obsidian_vault":
        if aggregates["warm_p95_ms"] > budgets["vault_download_p95_max"]:
            reason_codes.append("obsidian_vault:vault_download_p95_max_exceeded")
    else:
        if aggregates["warm_p95_ms"] > budgets["standard_route_warm_p95_max"]:
            reason_codes.append(f"{case_id}:standard_route_warm_p95_max_exceeded")
    cold_transfer = sum(_resources(sample)["same_origin_transfer_bytes"] for sample in cold_samples)
    if (
        cold_transfer
        > benchmark_policy_payload()["resource_guardrails"]["cold_traversal_transfer_bytes_max"]
    ):
        reason_codes.append(f"{case_id}:cold_traversal_transfer_bytes_max_exceeded")
    _ = warm_samples


def _enforce_sample_resource_limits(
    label: str,
    samples: list[Mapping[str, Any]],
    reason_codes: list[str],
) -> None:
    policy = benchmark_policy_payload()
    for sample in samples:
        resources = _resources(sample)
        if (
            resources["same_origin_request_count"]
            > policy["resource_guardrails"]["required_request_count_max"]
        ):
            reason_codes.append(f"{label}:required_request_count_max_exceeded")
        if (
            resources["runtime_third_party_cdn_requests"]
            > policy["resource_guardrails"]["runtime_third_party_cdn_requests_max"]
        ):
            reason_codes.append(f"{label}:runtime_third_party_cdn_requests_max_exceeded")
        max_long_task_total = policy["timing_budgets_ms"]["long_task_total_per_case_max"]
        if resources["long_task_total_ms"] > max_long_task_total:
            reason_codes.append(f"{label}:long_task_total_per_case_max_exceeded")
        if resources["long_task_max_ms"] > policy["timing_budgets_ms"]["individual_long_task_max"]:
            reason_codes.append(f"{label}:individual_long_task_max_exceeded")


def _enforce_resource_guardrails(
    resource_summary: Mapping[str, int],
    reason_codes: list[str],
) -> None:
    policy = benchmark_policy_payload()
    if (
        resource_summary["runtime_third_party_cdn_requests"]
        > policy["resource_guardrails"]["runtime_third_party_cdn_requests_max"]
    ):
        reason_codes.append("resource_summary:runtime_third_party_cdn_requests_max_exceeded")


def _decision_for_reason_codes(reason_codes: list[str]) -> str:
    if not reason_codes:
        return "pass"
    if all(_is_documentable_timing_variance(reason) for reason in reason_codes):
        return "pass_with_documented_network_variance"
    return "repair_required"


def _is_documentable_timing_variance(reason: str) -> bool:
    return reason.endswith("_p95_max_exceeded") or reason.endswith("_p50_max_exceeded")


def _recompute_errors(
    cases: Mapping[str, Any],
    interactions: Mapping[str, Any],
    viewport_results: Mapping[str, Any],
) -> dict[str, int]:
    samples = _all_samples(cases, interactions, viewport_results)
    return {
        "console_errors": sum(_resources(sample)["console_errors"] for sample in samples),
        "page_errors": sum(_resources(sample)["page_errors"] for sample in samples),
        "failed_required_same_origin_requests": sum(
            _resources(sample)["failed_required_same_origin_requests"] for sample in samples
        ),
        "access_leakage": 0,
    }


def _recompute_resource_summary(
    cases: Mapping[str, Any],
    interactions: Mapping[str, Any],
    viewport_results: Mapping[str, Any],
) -> dict[str, int]:
    samples = _all_samples(cases, interactions, viewport_results)
    cold_samples = [
        sample
        for case in cases.values()
        for sample in _sample_list(case.get("cold_samples"), "cold")
    ]
    return {
        "same_origin_request_count": sum(
            _resources(sample)["same_origin_request_count"] for sample in samples
        ),
        "same_origin_transfer_bytes": sum(
            _resources(sample)["same_origin_transfer_bytes"] for sample in samples
        ),
        "cold_traversal_transfer_bytes": sum(
            _resources(sample)["same_origin_transfer_bytes"] for sample in cold_samples
        ),
        "runtime_third_party_cdn_requests": sum(
            _resources(sample)["runtime_third_party_cdn_requests"] for sample in samples
        ),
        "platform_third_party_request_count": sum(
            _resources(sample)["platform_third_party_request_count"] for sample in samples
        ),
        "platform_console_errors": sum(
            _resources(sample)["platform_console_errors"] for sample in samples
        ),
    }


def _recompute_long_tasks(
    cases: Mapping[str, Any],
    interactions: Mapping[str, Any],
    viewport_results: Mapping[str, Any],
) -> dict[str, int]:
    samples = _all_samples(cases, interactions, viewport_results)
    return {
        "count": sum(_resources(sample)["long_task_count"] for sample in samples),
        "max_ms": max([_resources(sample)["long_task_max_ms"] for sample in samples] or [0]),
        "total_ms": sum(_resources(sample)["long_task_total_ms"] for sample in samples),
    }


def _all_samples(
    cases: Mapping[str, Any],
    interactions: Mapping[str, Any],
    viewport_results: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    samples: list[Mapping[str, Any]] = []
    for case in cases.values():
        samples.extend(_sample_list(case.get("cold_samples"), "case.cold"))
        samples.extend(_sample_list(case.get("warm_samples"), "case.warm"))
    for group in interactions.values():
        if isinstance(group, Mapping):
            for item in group.values():
                if isinstance(item, Mapping):
                    samples.extend(_sample_list(item.get("warm_samples"), "interaction.warm"))
    for viewport in viewport_results.values():
        if isinstance(viewport, Mapping):
            samples.append(viewport)
    return samples


def _sample_list(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise M24_14_6ValidationError(f"{label} must be a sample list")
    samples: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        samples.append(_require_mapping(item, f"{label}[{index}]"))
    return samples


def _elapsed(samples: list[Mapping[str, Any]]) -> list[float]:
    return [float(sample.get("elapsed_ms", -1)) for sample in samples]


def _rounded_nearest_rank(values: list[float], percentile: float) -> float:
    if any(value < 0 for value in values):
        raise M24_14_6ValidationError("sample elapsed_ms must be non-negative")
    return round(float(nearest_rank(values, percentile)), 2)


def _resources(record: Mapping[str, Any]) -> dict[str, int]:
    resources = _require_mapping(record.get("resources"), "resources")
    defaults = {
        "same_origin_request_count": 0,
        "same_origin_transfer_bytes": 0,
        "runtime_third_party_cdn_requests": 0,
        "platform_third_party_request_count": 0,
        "failed_required_same_origin_requests": 0,
        "console_errors": 0,
        "platform_console_errors": 0,
        "page_errors": 0,
        "long_task_count": 0,
        "long_task_max_ms": 0,
        "long_task_total_ms": 0,
    }
    material: dict[str, int] = {}
    for key, default in defaults.items():
        value = resources.get(key, default)
        if not isinstance(value, int) or value < 0:
            raise M24_14_6ValidationError(f"invalid resource counter: {key}")
        material[key] = value
    return material


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(payload), encoding="utf-8")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise M24_14_6ValidationError(f"{label} must be an object")
    return value


def _assert_no_sensitive_material(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                raise M24_14_6ValidationError(f"forbidden sensitive key at {path}.{key}")
            _assert_no_sensitive_material(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_material(item, f"{path}[{index}]")
    elif isinstance(value, str) and SENSITIVE_VALUE_RE.search(value):
        raise M24_14_6ValidationError(f"forbidden sensitive value at {path}")
