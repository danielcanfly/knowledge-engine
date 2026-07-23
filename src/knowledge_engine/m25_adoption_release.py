from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import AuthorizationError, IntegrityError

EVIDENCE_SCHEMA = "knowledge-engine-m25-8-adoption-evidence/v1"
RECEIPT_SCHEMA = "knowledge-engine-m25-8-adoption-receipt/v1"
GATE_SCHEMA = "knowledge-engine-m25-8-readiness-gate/v1"
BENCHMARK_CLOSURE_SCHEMA = "knowledge-engine-m25-7-benchmark-closure/v1"
LIVE_PREDECESSOR_STATUS = "m25_7_source_pr_opened_awaiting_merge"
LIVE_COMPLETE_STATUS = "m25_8_adoption_release_rollback_complete"
TEST_COMPLETE_STATUS = "m25_8_test_only_adoption_simulation_passed"
BLOCKED_STATUS = "blocked_awaiting_real_approved_source_pr"
M25_7_EXECUTOR_MERGE_SHA = "209608c3821f2958b5238659e98a8f9fb7bd7840"
M25_7_BENCHMARK_CLOSURE_MERGE_SHA = "4862761c2b90fbe5074f964bc234c42cce5bb5d5"
SOURCE_REPOSITORY = "danielcanfly/knowledge-source"
EXPECTED_SURFACES = ("search", "wiki", "graph", "sources", "vault")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._@-]{3,128}$")
MAX_CHANGED_FILES = 2_000
MAX_SURFACE_EVIDENCE = 5
FORBIDDEN_LIVE_ACTORS = {
    "browser-reviewer",
    "synthetic-reviewer",
    "synthetic-knowledge-owner",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sign(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    output = json.loads(json.dumps(value))
    output.pop(field, None)
    output[field] = digest(output)
    return output


def verify_signed(value: Mapping[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    actual = digest(unsigned)
    if not isinstance(claimed, str) or not hmac.compare_digest(claimed, actual):
        raise IntegrityError(code)
    return claimed


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M25-ADOPT-001 cannot load {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M25-ADOPT-002 {path.name} must contain an object")
    return value


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX40 if size == 40 else HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityError(f"M25-ADOPT-003 invalid {label}")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IntegrityError(f"M25-ADOPT-004 invalid {label}")
    return value


def _actor(value: Any) -> str:
    if not isinstance(value, str) or ACTOR_RE.fullmatch(value) is None:
        raise AuthorizationError("M25-ADOPT-005 invalid authority actor")
    return value


def _require_false(boundary: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    if any(boundary.get(field) is not False for field in fields):
        raise AuthorizationError("M25-ADOPT-006 protected mutation boundary drift")


def evaluate_readiness(predecessor: Mapping[str, Any]) -> dict[str, Any]:
    if predecessor.get("schema_version") != BENCHMARK_CLOSURE_SCHEMA:
        raise IntegrityError("M25-ADOPT-007 unsupported predecessor schema")
    boundary = predecessor.get("boundary")
    result = predecessor.get("result")
    if not isinstance(boundary, dict) or not isinstance(result, dict):
        raise IntegrityError("M25-ADOPT-008 malformed predecessor closure")
    if (
        predecessor.get("status") != "m25_7_benchmark_batch_closed_no_write"
        or boundary.get("m25_8_authorized") is not False
        or boundary.get("source_pr_creation") is not False
        or boundary.get("source_pr_merge") is not False
        or result.get("source_operations") != 0
        or result.get("source_pr_created") is not False
    ):
        raise IntegrityError("M25-ADOPT-009 benchmark closure authority drift")
    gate = {
        "schema_version": GATE_SCHEMA,
        "status": BLOCKED_STATUS,
        "predecessor_status": predecessor["status"],
        "predecessor_self_sha256": predecessor.get("self_sha256"),
        "m25_7_executor_merge_sha": M25_7_EXECUTOR_MERGE_SHA,
        "m25_7_benchmark_closure_merge_sha": M25_7_BENCHMARK_CLOSURE_MERGE_SHA,
        "blockers": [
            "real_terminal_item_decision_population_missing",
            "exact_live_source_baseline_missing",
            "exact_live_source_plan_approval_missing",
            "open_source_pr_missing",
            "exact_source_pr_head_merge_authority_missing",
        ],
        "benchmark_fixtures_reusable_as_live_source": False,
        "source_pr_merge_permitted": False,
        "candidate_release_build_permitted": False,
        "production_pointer_mutation_permitted": False,
        "production_release_mutation_permitted": False,
        "next_legal_action": "create_future_real_pilot_candidate_batch_under_separate_authority",
    }
    return sign(gate, "gate_sha256")


def _validate_predecessor(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-ADOPT-010 predecessor must be an object")
    if (
        value.get("status") != LIVE_PREDECESSOR_STATUS
        or value.get("executor_merge_sha") != M25_7_EXECUTOR_MERGE_SHA
        or value.get("m25_8_authorized") is not True
    ):
        raise AuthorizationError("M25-ADOPT-011 M25.7 live predecessor is not authorized")
    _hex(value.get("plan_sha256"), 64, "Source plan digest")
    _hex(value.get("opening_receipt_sha256"), 64, "Source opening receipt digest")
    return dict(value)


def _validate_source_pr(value: Any, predecessor: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-ADOPT-012 Source PR evidence must be an object")
    if (
        value.get("repository") != SOURCE_REPOSITORY
        or value.get("state") != "open"
        or value.get("draft") is not False
        or value.get("mergeable") is not True
        or value.get("ci_conclusion") != "success"
        or value.get("plan_sha256") != predecessor["plan_sha256"]
    ):
        raise IntegrityError("M25-ADOPT-013 Source PR is not merge-ready")
    _positive_int(value.get("number"), "Source PR number")
    _hex(value.get("base_sha"), 40, "Source PR base SHA")
    _hex(value.get("head_sha"), 40, "Source PR head SHA")
    files = value.get("changed_files")
    if (
        not isinstance(files, list)
        or not 1 <= len(files) <= MAX_CHANGED_FILES
        or value.get("changed_file_count") != len(files)
    ):
        raise IntegrityError("M25-ADOPT-014 invalid Source PR changed-file population")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "operation", "sha256"}:
            raise IntegrityError("M25-ADOPT-015 malformed Source PR changed-file record")
        path = item.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or ".." in path.split("/")
            or path in seen
            or item.get("operation") not in {"create", "replace", "delete"}
        ):
            raise IntegrityError("M25-ADOPT-016 unsafe or duplicate Source PR path")
        if item["operation"] == "delete":
            if item.get("sha256") is not None:
                raise IntegrityError("M25-ADOPT-017 deleted path must not claim new bytes")
        else:
            _hex(item.get("sha256"), 64, "Source changed-file digest")
        seen.add(path)
    return json.loads(json.dumps(value))


def _validate_authority(
    value: Any,
    *,
    mode: str,
    predecessor: Mapping[str, Any],
    source_pr: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorizationError("M25-ADOPT-018 authority must be an object")
    authority_sha = verify_signed(
        value,
        "authority_sha256",
        "M25-ADOPT-019 authority digest mismatch",
    )
    actor = _actor(value.get("actor"))
    if mode == "live" and actor in FORBIDDEN_LIVE_ACTORS:
        raise AuthorizationError("M25-ADOPT-020 synthetic actor cannot authorize live adoption")
    if (
        value.get("actor_role") != "knowledge_owner"
        or value.get("source_repository") != SOURCE_REPOSITORY
        or value.get("source_pr_number") != source_pr["number"]
        or value.get("exact_source_pr_base_sha") != source_pr["base_sha"]
        or value.get("exact_source_pr_head_sha") != source_pr["head_sha"]
        or value.get("plan_sha256") != predecessor["plan_sha256"]
        or value.get("source_pr_merge_authorized") is not True
        or value.get("candidate_release_build_authorized") is not True
        or value.get("production_pointer_authorized") is not False
        or value.get("production_release_authorized") is not False
    ):
        raise AuthorizationError("M25-ADOPT-021 stale or over-broad merge authority")
    _positive_int(value.get("authority_comment_id"), "authority comment ID")
    clean = json.loads(json.dumps(value))
    clean["authority_sha256"] = authority_sha
    return clean


def _validate_merge(value: Any, source_pr: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-ADOPT-022 merge receipt must be an object")
    if (
        value.get("repository") != SOURCE_REPOSITORY
        or value.get("source_pr_number") != source_pr["number"]
        or value.get("expected_head_sha") != source_pr["head_sha"]
        or value.get("merged") is not True
        or value.get("merge_method") not in {"merge", "squash", "rebase"}
    ):
        raise IntegrityError("M25-ADOPT-023 expected-head Source merge mismatch")
    _hex(value.get("merged_source_sha"), 40, "merged Source SHA")
    return dict(value)


def _validate_candidate_release(value: Any, merge: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-ADOPT-024 candidate release must be an object")
    if (
        value.get("environment") != "candidate"
        or value.get("source_commit_sha") != merge["merged_source_sha"]
        or value.get("production") is not False
        or value.get("production_pointer_mutated") is not False
    ):
        raise AuthorizationError("M25-ADOPT-025 candidate release boundary mismatch")
    release_id = value.get("release_id")
    if not isinstance(release_id, str) or not release_id.strip():
        raise IntegrityError("M25-ADOPT-026 candidate release ID is missing")
    for field in (
        "manifest_sha256",
        "builder_sha",
        "lexical_index_sha256",
        "graph_v2_sha256",
        "provenance_sha256",
        "source_snapshot_sha256",
    ):
        _hex(value.get(field), 40 if field == "builder_sha" else 64, field)
    return dict(value)


def _validate_surfaces(value: Any, release: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != MAX_SURFACE_EVIDENCE:
        raise IntegrityError("M25-ADOPT-027 exactly five surface reports are required")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise IntegrityError("M25-ADOPT-028 malformed surface report")
        surface = item.get("surface")
        if (
            surface not in EXPECTED_SURFACES
            or surface in seen
            or item.get("status") != "pass"
            or item.get("release_id") != release["release_id"]
            or item.get("manifest_sha256") != release["manifest_sha256"]
            or item.get("regression_count", 0) < 1
        ):
            raise IntegrityError("M25-ADOPT-029 product surface regression mismatch")
        _hex(item.get("evidence_sha256"), 64, "surface evidence digest")
        seen.add(surface)
        clean.append(dict(item))
    if seen != set(EXPECTED_SURFACES):
        raise IntegrityError("M25-ADOPT-030 incomplete product surface coverage")
    return sorted(clean, key=lambda row: row["surface"])


def _validate_rollback(value: Any, release: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError("M25-ADOPT-031 rollback evidence must be an object")
    if (
        value.get("scope") != "candidate_only"
        or value.get("drill_passed") is not True
        or value.get("from_release_id") != release["release_id"]
        or value.get("candidate_pointer_restored") is not True
        or value.get("production_pointer_before_sha256")
        != value.get("production_pointer_after_sha256")
    ):
        raise IntegrityError("M25-ADOPT-032 candidate rollback proof mismatch")
    to_release = value.get("to_release_id")
    if not isinstance(to_release, str) or not to_release.strip():
        raise IntegrityError("M25-ADOPT-033 rollback target release is missing")
    _hex(value.get("production_pointer_before_sha256"), 64, "production pointer digest")
    _require_false(
        value,
        (
            "production_pointer_mutated",
            "production_release_mutated",
            "r2_production_mutated",
            "qdrant_mutated",
            "traffic_mutated",
        ),
    )
    return dict(value)


def validate_adoption_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != EVIDENCE_SCHEMA:
        raise IntegrityError("M25-ADOPT-034 invalid adoption evidence schema")
    evidence_sha = verify_signed(value, "evidence_sha256", "M25-ADOPT-035 evidence digest mismatch")
    mode = value.get("mode")
    if mode not in {"live", "test_only"}:
        raise IntegrityError("M25-ADOPT-036 invalid execution mode")
    predecessor = _validate_predecessor(value.get("predecessor"))
    source_pr = _validate_source_pr(value.get("source_pr"), predecessor)
    authority = _validate_authority(
        value.get("authority"),
        mode=mode,
        predecessor=predecessor,
        source_pr=source_pr,
    )
    merge = _validate_merge(value.get("merge"), source_pr)
    release = _validate_candidate_release(value.get("candidate_release"), merge)
    surfaces = _validate_surfaces(value.get("surfaces"), release)
    rollback = _validate_rollback(value.get("rollback"), release)
    boundary = value.get("boundary")
    if not isinstance(boundary, dict):
        raise IntegrityError("M25-ADOPT-037 boundary must be an object")
    _require_false(
        boundary,
        (
            "benchmark_fixture_adopted",
            "automatic_source_merge",
            "production_pointer_mutation",
            "production_release_mutation",
            "production_r2_mutation",
            "qdrant_mutation",
            "credential_mutation",
            "traffic_mutation",
        ),
    )
    clean = json.loads(json.dumps(value))
    clean["predecessor"] = predecessor
    clean["source_pr"] = source_pr
    clean["authority"] = authority
    clean["merge"] = merge
    clean["candidate_release"] = release
    clean["surfaces"] = surfaces
    clean["rollback"] = rollback
    clean["evidence_sha256"] = evidence_sha
    return clean


def build_adoption_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    evidence = validate_adoption_evidence(value)
    mode = evidence["mode"]
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "status": LIVE_COMPLETE_STATUS if mode == "live" else TEST_COMPLETE_STATUS,
        "mode": mode,
        "evidence_sha256": evidence["evidence_sha256"],
        "authority_sha256": evidence["authority"]["authority_sha256"],
        "source_repository": SOURCE_REPOSITORY,
        "source_pr_number": evidence["source_pr"]["number"],
        "source_pr_exact_head_sha": evidence["source_pr"]["head_sha"],
        "merged_source_sha": evidence["merge"]["merged_source_sha"],
        "candidate_release_id": evidence["candidate_release"]["release_id"],
        "candidate_manifest_sha256": evidence["candidate_release"]["manifest_sha256"],
        "surface_count": len(evidence["surfaces"]),
        "surfaces": [row["surface"] for row in evidence["surfaces"]],
        "rollback_target_release_id": evidence["rollback"]["to_release_id"],
        "rollback_passed": True,
        "production_pointer_unchanged": True,
        "production_mutation_permitted": False,
        "m25_9_authorized": False,
    }
    return sign(receipt, "receipt_sha256")
