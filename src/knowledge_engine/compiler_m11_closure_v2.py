from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler_contract_v1 import json_bytes, put_immutable
from .compiler_m11_closure_v1 import M11ClosureRequest, reconcile_m11_closure
from .storage import ObjectStore


def _stable_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


@dataclass(frozen=True)
class SemanticInvariant:
    name: str
    expected: bool
    observed: bool
    evidence_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected": self.expected,
            "observed": self.observed,
            "passed": self.observed is self.expected,
            "evidence_ref": self.evidence_ref,
        }


EXPECTED_INVARIANTS: tuple[tuple[str, bool], ...] = (
    ("compiler_pipeline_evidence_complete", True),
    ("human_review_mandatory", True),
    ("automatic_approval_permitted", False),
    ("unsupported_or_quarantined_content_published", False),
    ("audience_or_acl_broadened", False),
    ("canonical_source_written", False),
    ("source_pr_created_or_merged", False),
    ("candidate_or_release_created", False),
    ("production_promoted_or_rolled_back", False),
    ("production_pointer_changed", False),
    ("permanent_ledger_appended", False),
    ("deterministic_replay_supported", True),
)


def build_semantic_invariant_matrix(
    *,
    closure_id: str,
    legacy_matrix: dict[str, Any],
    legacy_matrix_ref: str,
) -> dict[str, Any]:
    """Convert the ambiguous v1 boolean map into explicit expected/observed checks."""

    observed = legacy_matrix.get("invariants")
    if not isinstance(observed, dict):
        raise ValueError("legacy invariant matrix is malformed")
    expected_names = {name for name, _ in EXPECTED_INVARIANTS}
    if set(observed) != expected_names:
        raise ValueError("legacy invariant matrix coverage mismatch")
    checks = [
        SemanticInvariant(
            name=name,
            expected=expected,
            observed=observed[name],
            evidence_ref=f"{legacy_matrix_ref}#/invariants/{name}",
        ).to_dict()
        for name, expected in EXPECTED_INVARIANTS
    ]
    if any(not isinstance(item["observed"], bool) for item in checks):
        raise ValueError("legacy invariant observations must be booleans")
    all_passed = all(item["passed"] for item in checks)
    mismatches = [item["name"] for item in checks if not item["passed"]]
    identity = {
        "closure_id": closure_id,
        "legacy_matrix_ref": legacy_matrix_ref,
        "checks": checks,
        "mismatches": mismatches,
    }
    digest = hashlib.sha256(_stable_json(identity)).hexdigest()[:32]
    return {
        "schema_version": "knowledge-compiler-m11-invariant-matrix/v2",
        "semantic_matrix_id": f"m11matrix2_{digest}",
        "closure_id": closure_id,
        "legacy_matrix_ref": legacy_matrix_ref,
        "checks": checks,
        "check_count": len(checks),
        "passed_count": sum(item["passed"] for item in checks),
        "mismatches": mismatches,
        "all_passed": all_passed,
    }


def reconcile_m11_closure_v2(
    store: ObjectStore,
    request: M11ClosureRequest,
    source_root: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run legacy closure validation, then emit an unambiguous immutable v2 matrix."""

    legacy = reconcile_m11_closure(store, request, source_root)
    if legacy.status != "closure_ready" or not legacy.closure_prefix:
        return {
            "schema_version": "knowledge-compiler-m11-closure/v2",
            "status": "rejected",
            "legacy_result": legacy.to_dict(),
            "failure_code": legacy.failure_code,
            "canonical_write_permitted": False,
            "github_write_permitted": False,
            "production_write_permitted": False,
            "ledger_write_permitted": False,
        }

    legacy_matrix_key = f"{legacy.closure_prefix}/invariant-matrix.json"
    legacy_report_key = f"{legacy.closure_prefix}/reconciliation-report.json"
    legacy_matrix = json.loads(store.get(legacy_matrix_key))
    legacy_report = json.loads(store.get(legacy_report_key))
    if not isinstance(legacy_matrix, dict) or not isinstance(legacy_report, dict):
        raise ValueError("legacy M11 closure artifacts must be objects")

    semantic_matrix = build_semantic_invariant_matrix(
        closure_id=legacy.closure_id,
        legacy_matrix=legacy_matrix,
        legacy_matrix_ref=legacy_matrix_key,
    )
    identity = {
        "legacy_closure_id": legacy.closure_id,
        "legacy_result_key": legacy.result_key,
        "legacy_reconciliation_sha256": legacy.reconciliation_sha256,
        "semantic_matrix_id": semantic_matrix["semantic_matrix_id"],
        "semantic_matrix": semantic_matrix,
    }
    digest = hashlib.sha256(_stable_json(identity)).hexdigest()[:32]
    closure_v2_id = f"m11closure2_{digest}"
    prefix = f"compiler/v2/m11-closures/{closure_v2_id}"
    matrix_key = f"{prefix}/semantic-invariant-matrix.json"
    report_key = f"{prefix}/reconciliation-report.json"
    result_key = f"{prefix}/result.json"
    report = {
        "schema_version": "knowledge-compiler-m11-reconciliation/v2",
        "closure_v2_id": closure_v2_id,
        "legacy_closure_id": legacy.closure_id,
        "status": "closure_ready" if semantic_matrix["all_passed"] else "blocked",
        "semantic_matrix_id": semantic_matrix["semantic_matrix_id"],
        "legacy_report_ref": legacy_report_key,
        "source_commit_sha": legacy_report.get("canonical_source_sha"),
        "production_release": legacy_report.get("production_release"),
        "production_manifest_sha256": legacy_report.get("production_manifest_sha256"),
        "production_pointer_sha256": legacy_report.get("production_pointer_sha256"),
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
        "ledger_write_permitted": False,
    }
    result = {
        "schema_version": "knowledge-compiler-m11-closure-result/v2",
        "closure_v2_id": closure_v2_id,
        "legacy_closure_id": legacy.closure_id,
        "status": report["status"],
        "passed": semantic_matrix["all_passed"],
        "semantic_matrix_key": matrix_key,
        "report_key": report_key,
        "mismatches": semantic_matrix["mismatches"],
        "canonical_write_permitted": False,
        "github_write_permitted": False,
        "production_write_permitted": False,
        "ledger_write_permitted": False,
    }
    states = [
        put_immutable(store, matrix_key, json_bytes(semantic_matrix)),
        put_immutable(store, report_key, json_bytes(report)),
        put_immutable(store, result_key, json_bytes(result)),
    ]
    result["idempotent"] = all(states)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "semantic-invariant-matrix.json").write_bytes(json_bytes(semantic_matrix))
        (output_dir / "reconciliation-report-v2.json").write_bytes(json_bytes(report))
        (output_dir / "m11-closure-result-v2.json").write_bytes(json_bytes(result))
    return result
