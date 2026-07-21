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
M24_14_6_ACCEPTANCE_MATRIX_SCHEMA = (
    "knowledge-engine-m24-14-6-acceptance-matrix/v1"
)
M24_14_6_HUMAN_ACCEPTANCE_SCHEMA = (
    "knowledge-engine-m24-14-6-human-acceptance-record/v1"
)
M24_14_6_PENDING_ACCEPTANCE_SCHEMA = (
    "knowledge-engine-m24-14-6-pending-final-acceptance/v1"
)
M24_14_6_AUTHENTICATED_RESULT_SCHEMA = (
    "knowledge-engine-m24-14-6-authenticated-benchmark-result/v1"
)

M24_14_6_STATUS = (
    "m24_14_6_harness_deployed_pending_daniel_authenticated_benchmark"
)
M24_14_6_ISSUE_NUMBER = 1023
M24_14_6_REQUIRED_BASE_SHA = "1c7e3a32d9e6787b0c0ea9ba129185da8f504ba1"
M24_14_6_FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
M24_14_6_ACCEPTED_VAULT_SHA256 = (
    "054f2a349c173d62de0d2e7b575fbb97a46611ac435653eb6c9eca5255272f64"
)
M24_14_6_CURRENT_PROTECTED_DEPLOYMENT = "5361997c-fe53-47a5-998e-81244a6470ab"
M24_14_6_IMMEDIATE_ROLLBACK_DEPLOYMENT = "b570b0c7-a812-4878-8573-e7b7d41faf78"
M24_14_6_SECONDARY_ROLLBACK_DEPLOYMENT = "586deae3-d679-45e2-8542-ec6845f9f2e7"
M24_14_6_PAGES_PROJECT = "llm-wiki-m24-internal"
M24_14_6_CUSTOM_HOSTNAME = "https://m24-internal.danielcanfly.com/"
M24_14_6_DANIEL_COMMAND = (
    "python scripts/m24_14_6_authenticated_benchmark.py --headed --capture-auth"
)

M24_14_6_ROOT = Path("pilot/m24/m24-14-6")
BENCHMARK_POLICY_PATH = M24_14_6_ROOT / "benchmark-policy.json"
BENCHMARK_CASES_PATH = M24_14_6_ROOT / "benchmark-cases.json"
HUMAN_ACCEPTANCE_PATH = M24_14_6_ROOT / "m24-14-5-human-acceptance.json"
PENDING_ACCEPTANCE_PATH = M24_14_6_ROOT / "m24-14-6-pending-acceptance.json"

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
    r"session[_-]?storage|profile[_-]?path|ip[_-]?address)",
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
                    "Daniel explicitly reported the current Vault downloaded "
                    "and opened normally."
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
        "current_protected_deployment": M24_14_6_CURRENT_PROTECTED_DEPLOYMENT,
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


def finalized_result_sha256(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material["self_sha256"] = ""
    return canonical_sha256(material)


def finalize_authenticated_benchmark_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    finalized = json.loads(json.dumps(payload, ensure_ascii=False))
    finalized["self_sha256"] = ""
    finalized["self_sha256"] = finalized_result_sha256(finalized)
    return finalized


def validate_authenticated_benchmark_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = _require_mapping(payload, "result")
    _assert_no_sensitive_material(result)
    if result.get("schema_version") != M24_14_6_AUTHENTICATED_RESULT_SCHEMA:
        raise M24_14_6ValidationError("unexpected benchmark result schema")
    if result.get("authority") != "authenticated_live":
        raise M24_14_6ValidationError("authenticated live authority is required")
    if result.get("self_sha256") != finalized_result_sha256(result):
        raise M24_14_6ValidationError("benchmark result self digest mismatch")
    if result.get("benchmark_policy_sha256") != benchmark_policy_sha256():
        raise M24_14_6ValidationError("benchmark policy digest mismatch")
    if result.get("benchmark_cases_sha256") != benchmark_cases_sha256():
        raise M24_14_6ValidationError("benchmark cases digest mismatch")

    identities = _require_mapping(result.get("identities"), "identities")
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
    if not identities.get("deployment_id"):
        raise M24_14_6ValidationError("deployment identity is required")

    iterations = _require_mapping(result.get("iterations"), "iterations")
    required_iterations = benchmark_policy_payload()["iterations"]
    if int(iterations.get("cold_completed", 0)) < required_iterations["cold_min"]:
        raise M24_14_6ValidationError("insufficient cold iterations")
    if int(iterations.get("warm_completed", 0)) < required_iterations["warm_min"]:
        raise M24_14_6ValidationError("insufficient warm iterations")

    cases = _require_mapping(result.get("cases"), "cases")
    missing_cases = sorted(set(BENCHMARK_CASE_IDS) - set(cases))
    if missing_cases:
        raise M24_14_6ValidationError(f"missing benchmark cases: {missing_cases}")
    for case_id in BENCHMARK_CASE_IDS:
        _require_mapping(cases[case_id], f"cases.{case_id}")

    errors = _require_mapping(result.get("errors"), "errors")
    for key in (
        "console_errors",
        "page_errors",
        "failed_required_same_origin_requests",
        "access_leakage",
    ):
        if not isinstance(errors.get(key), int) or errors[key] < 0:
            raise M24_14_6ValidationError(f"invalid error counter: {key}")

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

    decision = result.get("decision")
    if decision not in benchmark_policy_payload()["decisions"]:
        raise M24_14_6ValidationError("invalid benchmark decision")
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
    identities = _require_mapping(result.get("identities"), "identities")
    if identities.get("release_id") != CANONICAL_RELEASE_ID:
        raise M24_14_6ValidationError("local regression release drift")
    if identities.get("production_retrieval") != "lexical":
        raise M24_14_6ValidationError("local regression retrieval drift")
    cases = _require_mapping(result.get("cases"), "cases")
    missing_cases = sorted(set(BENCHMARK_CASE_IDS) - set(cases))
    if missing_cases:
        raise M24_14_6ValidationError(f"missing local cases: {missing_cases}")
    return dict(result)


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
