from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .m24_14_6_authenticated_performance import (
    BENCHMARK_CASE_IDS,
    BENCHMARK_EVIDENCE_METADATA_PATH,
    BENCHMARK_EVIDENCE_PATH,
    M24_14_6_ACCEPTED_DEPLOYMENT,
    M24_14_6_ACCEPTED_VAULT_SHA256,
    M24_14_6_BENCHMARK_FILE_SHA256,
    M24_14_6_BENCHMARK_SELF_SHA256,
    M24_14_6_CLOSURE_SEAL_BASE_SHA,
    M24_14_6_CLOSURE_SEAL_REF,
    M24_14_6_FINAL_SURFACE_DEPLOYMENT,
    M24_14_6_FOUNDATION_SHA,
    M24_14_6_PRODUCT_ACCEPTANCE_SHA,
    M24_14_6ValidationError,
    _m24_14_6_protected_mutations_payload,
    benchmark_cases_sha256,
    benchmark_policy_sha256,
    canonical_json_bytes,
    validate_authenticated_benchmark_result,
)
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

FINAL_STATUS = "m24_14_6_authenticated_performance_and_final_acceptance_complete_reconciled"
ATTESTATION_SCHEMA = "m24-14-6-final-closure-attestation/v1"
M25_FINAL_BASELINE_SCHEMA = "knowledge-engine-m24-14-6-m25-entry-baseline/v2"
POST_MERGE_ATTESTATION_PATH = Path(
    "pilot/m24/m24-14-6/m24-14-6-final-closure-attestation.json"
)
M25_FINAL_BASELINE_PATH = Path("pilot/m24/m24-14-6/m25-entry-baseline.final.json")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def payload_self_sha256(payload: Mapping[str, Any]) -> str:
    material = dict(payload)
    material["self_sha256"] = ""
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(payload))


def load_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise M24_14_6ValidationError("benchmark evidence must be a JSON object")
    return value


def validate_portable_benchmark_file(path: Path) -> dict[str, Any]:
    file_sha256 = sha256_bytes(path.read_bytes())
    if file_sha256 != M24_14_6_BENCHMARK_FILE_SHA256:
        raise M24_14_6ValidationError("benchmark file digest mismatch")
    if str(path) in path.read_text(encoding="utf-8"):
        raise M24_14_6ValidationError("benchmark evidence contains its local source path")

    result = validate_authenticated_benchmark_result(
        load_json_file(path),
        expected_deployment_id=M24_14_6_ACCEPTED_DEPLOYMENT,
    )
    if result.get("self_sha256") != M24_14_6_BENCHMARK_SELF_SHA256:
        raise M24_14_6ValidationError("benchmark self digest mismatch")
    if result.get("decision") != "pass":
        raise M24_14_6ValidationError("benchmark decision is not pass")
    if result.get("reason_codes") != []:
        raise M24_14_6ValidationError("benchmark reason codes are not empty")

    cases = result["cases"]
    case_summary = {
        case_id: {
            "cold_samples": len(cases[case_id]["cold_samples"]),
            "warm_samples": len(cases[case_id]["warm_samples"]),
            "status": cases[case_id]["status"],
        }
        for case_id in BENCHMARK_CASE_IDS
    }
    return {
        "schema_version": "m24-14-6-benchmark-evidence-revalidation/v1",
        "benchmark_repo_path": BENCHMARK_EVIDENCE_PATH.as_posix(),
        "file_sha256": file_sha256,
        "self_sha256": result["self_sha256"],
        "authority": result["authority"],
        "decision": result["decision"],
        "reason_codes": result["reason_codes"],
        "generated_at_utc": result["generated_at_utc"],
        "deployment_id": result["deployment_id"],
        "policy_sha256": result["benchmark_policy_sha256"],
        "cases_sha256": result["benchmark_cases_sha256"],
        "case_summary": case_summary,
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
        },
        "platform_telemetry": {
            "platform_console_errors": result["resource_summary"]["platform_console_errors"],
            "platform_third_party_request_count": result["resource_summary"][
                "platform_third_party_request_count"
            ],
        },
        "sensitive_scan": {
            "passed": True,
            "local_source_path_present": False,
            "raw_credentials_present": False,
        },
        "accepted_identities": {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
        },
    }


def write_portable_benchmark_evidence(source_path: Path) -> dict[str, Any]:
    validation = validate_portable_benchmark_file(source_path)
    BENCHMARK_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, BENCHMARK_EVIDENCE_PATH)
    copied_sha = sha256_bytes(BENCHMARK_EVIDENCE_PATH.read_bytes())
    if copied_sha != M24_14_6_BENCHMARK_FILE_SHA256:
        raise M24_14_6ValidationError("copied benchmark evidence digest mismatch")

    metadata = {
        "schema_version": "m24-14-6-portable-benchmark-evidence-metadata/v1",
        "repository_path": BENCHMARK_EVIDENCE_PATH.as_posix(),
        "sha256": copied_sha,
        "benchmark_self_sha256": M24_14_6_BENCHMARK_SELF_SHA256,
        "validation_command": (
            "python scripts/m24_14_6_final_closure_seal.py validate-evidence "
            "--benchmark-path pilot/m24/m24-14-6/evidence/"
            "authenticated-benchmark-result.sanitized.json"
        ),
        "policy_sha256": benchmark_policy_sha256(),
        "cases_sha256": benchmark_cases_sha256(),
        "source_acquisition_statement": (
            "Byte-for-byte copy of Daniel's accepted sanitized authenticated benchmark JSON "
            "after exact digest and sensitivity validation."
        ),
        "sensitive_scan": validation["sensitive_scan"],
        "accepted_identities": validation["accepted_identities"],
        "no_raw_credentials": True,
        "no_local_source_path": True,
        "metadata_self_sha256": "",
    }
    metadata["metadata_self_sha256"] = hashlib.sha256(canonical_json_bytes(metadata)).hexdigest()
    _write_json(BENCHMARK_EVIDENCE_METADATA_PATH, metadata)
    return {
        "validation": validation,
        "metadata": metadata,
    }


def build_final_git_identities(
    *,
    issue_number: int,
    pr_number: int,
    pr_head_sha: str,
    merge_sha: str,
    tag_target_sha: str,
) -> dict[str, Any]:
    if merge_sha != tag_target_sha:
        raise M24_14_6ValidationError("closure tag target does not match final main")
    return {
        "schema_version": "m24-14-6-final-git-identities/v1",
        "engine_product_acceptance_sha": M24_14_6_PRODUCT_ACCEPTANCE_SHA,
        "closure_seal_base_sha": M24_14_6_CLOSURE_SEAL_BASE_SHA,
        "closure_seal_issue_number": issue_number,
        "closure_seal_pr_number": pr_number,
        "closure_seal_pr_head_sha": pr_head_sha,
        "closure_seal_merge_sha": merge_sha,
        "engine_main_sha": merge_sha,
        "closure_seal_ref": M24_14_6_CLOSURE_SEAL_REF,
        "closure_seal_tag_target_sha": tag_target_sha,
    }


def _ci_run_entries(ci_runs: Sequence[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in ci_runs:
        name, _, run_id = item.partition("=")
        if not name or not run_id:
            raise M24_14_6ValidationError("ci run entries must use name=run_id")
        entries.append({"name": name, "run_id": run_id})
    return entries


def build_m25_final_entry_baseline(
    *,
    issue_number: int,
    pr_number: int,
    pr_head_sha: str,
    merge_sha: str,
    tag_target_sha: str,
    final_surface_deployment_id: str = M24_14_6_FINAL_SURFACE_DEPLOYMENT,
    ci_runs: Sequence[str] = (),
    attestation_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identities = build_final_git_identities(
        issue_number=issue_number,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        merge_sha=merge_sha,
        tag_target_sha=tag_target_sha,
    )
    payload: dict[str, Any] = {
        "schema_version": M25_FINAL_BASELINE_SCHEMA,
        "m24_14_6_closed": True,
        "daniel_acceptance_recorded": True,
        "authenticated_performance_decision": "pass",
        **identities,
        "source_sha": CANONICAL_SOURCE_SHA,
        "foundation_sha": M24_14_6_FOUNDATION_SHA,
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        "accepted_benchmark_deployment_id": M24_14_6_ACCEPTED_DEPLOYMENT,
        "final_surface_deployment_id": final_surface_deployment_id,
        "benchmark_file_sha256": M24_14_6_BENCHMARK_FILE_SHA256,
        "benchmark_self_sha256": M24_14_6_BENCHMARK_SELF_SHA256,
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "production_answer_serving_enabled": False,
        "large_scale_ingestion_enabled": False,
        "protected_mutations": _m24_14_6_protected_mutations_payload(),
        "ci_runs": _ci_run_entries(ci_runs),
        "attestation_artifact": dict(attestation_artifact or {}),
        "self_sha256": "",
    }
    payload["self_sha256"] = payload_self_sha256(payload)
    return payload


def build_post_merge_attestation(
    *,
    issue_number: int,
    pr_number: int,
    pr_head_sha: str,
    merge_sha: str,
    tag_target_sha: str,
    final_surface_deployment_id: str = M24_14_6_FINAL_SURFACE_DEPLOYMENT,
    ci_runs: Sequence[str] = (),
    attestation_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = build_m25_final_entry_baseline(
        issue_number=issue_number,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        merge_sha=merge_sha,
        tag_target_sha=tag_target_sha,
        final_surface_deployment_id=final_surface_deployment_id,
        ci_runs=ci_runs,
        attestation_artifact=attestation_artifact,
    )
    payload: dict[str, Any] = {
        "schema_version": ATTESTATION_SCHEMA,
        "final_status": FINAL_STATUS,
        "git": build_final_git_identities(
            issue_number=issue_number,
            pr_number=pr_number,
            pr_head_sha=pr_head_sha,
            merge_sha=merge_sha,
            tag_target_sha=tag_target_sha,
        ),
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_sha": CANONICAL_SOURCE_SHA,
        "foundation_sha": M24_14_6_FOUNDATION_SHA,
        "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        "accepted_benchmark_deployment_id": M24_14_6_ACCEPTED_DEPLOYMENT,
        "final_surface_deployment_id": final_surface_deployment_id,
        "benchmark_file_sha256": M24_14_6_BENCHMARK_FILE_SHA256,
        "benchmark_self_sha256": M24_14_6_BENCHMARK_SELF_SHA256,
        "production_retrieval": "lexical",
        "ci_runs": _ci_run_entries(ci_runs),
        "attestation_artifact": dict(attestation_artifact or {}),
        "m25_entry_baseline_sha256": hashlib.sha256(json_bytes(baseline)).hexdigest(),
        "protected_mutations": _m24_14_6_protected_mutations_payload(),
        "self_sha256": "",
    }
    payload["self_sha256"] = payload_self_sha256(payload)
    return payload


def write_post_merge_attestation_artifacts(
    output_dir: Path,
    *,
    issue_number: int,
    pr_number: int,
    pr_head_sha: str,
    merge_sha: str,
    tag_target_sha: str,
    final_surface_deployment_id: str = M24_14_6_FINAL_SURFACE_DEPLOYMENT,
    ci_runs: Sequence[str] = (),
) -> dict[str, Any]:
    baseline = build_m25_final_entry_baseline(
        issue_number=issue_number,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        merge_sha=merge_sha,
        tag_target_sha=tag_target_sha,
        final_surface_deployment_id=final_surface_deployment_id,
        ci_runs=ci_runs,
        attestation_artifact={"artifact_name": "m24-14-6-final-closure-attestation"},
    )
    attestation = build_post_merge_attestation(
        issue_number=issue_number,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        merge_sha=merge_sha,
        tag_target_sha=tag_target_sha,
        final_surface_deployment_id=final_surface_deployment_id,
        ci_runs=ci_runs,
        attestation_artifact={"artifact_name": "m24-14-6-final-closure-attestation"},
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / M25_FINAL_BASELINE_PATH.name
    attestation_path = output_dir / POST_MERGE_ATTESTATION_PATH.name
    _write_json(baseline_path, baseline)
    _write_json(attestation_path, attestation)
    return {
        "baseline_path": baseline_path.as_posix(),
        "baseline_sha256": sha256_bytes(baseline_path.read_bytes()),
        "attestation_path": attestation_path.as_posix(),
        "attestation_sha256": sha256_bytes(attestation_path.read_bytes()),
    }


def validate_committed_closure_artifacts() -> dict[str, Any]:
    validation = validate_portable_benchmark_file(BENCHMARK_EVIDENCE_PATH)
    metadata = load_json_file(BENCHMARK_EVIDENCE_METADATA_PATH)
    if metadata.get("sha256") != M24_14_6_BENCHMARK_FILE_SHA256:
        raise M24_14_6ValidationError("benchmark metadata file digest mismatch")
    if metadata.get("benchmark_self_sha256") != M24_14_6_BENCHMARK_SELF_SHA256:
        raise M24_14_6ValidationError("benchmark metadata self digest mismatch")
    metadata_material = dict(metadata)
    metadata_self_sha256 = str(metadata_material.get("metadata_self_sha256") or "")
    metadata_material["metadata_self_sha256"] = ""
    if hashlib.sha256(canonical_json_bytes(metadata_material)).hexdigest() != metadata_self_sha256:
        raise M24_14_6ValidationError("benchmark metadata self digest mismatch")
    if metadata.get("no_local_source_path") is not True:
        raise M24_14_6ValidationError("benchmark metadata must exclude local source path")
    return {
        "schema_version": "m24-14-6-closure-artifact-validation/v1",
        "benchmark": validation,
        "metadata_sha256": sha256_bytes(BENCHMARK_EVIDENCE_METADATA_PATH.read_bytes()),
    }
