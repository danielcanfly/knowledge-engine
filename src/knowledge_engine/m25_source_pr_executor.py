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

BASELINE_SCHEMA = "knowledge-engine-m25-7-source-baseline/v1"
AUTHORITY_SCHEMA = "knowledge-engine-m25-7-item-authority/v1"
PLAN_SCHEMA = "knowledge-engine-m25-7-source-pr-plan/v1"
PLAN_APPROVAL_SCHEMA = "knowledge-engine-m25-7-plan-approval/v1"
OPENING_RECEIPT_SCHEMA = "knowledge-engine-m25-7-opening-receipt/v1"
BATCH_SCHEMA = "knowledge-engine-m25-6-review-batch/v1"
AUDIT_SCHEMA = "knowledge-engine-m25-6-audit-export/v1"
DECISION_SCHEMA = "knowledge-engine-m25-6-decision-record/v1"
ACCEPTANCE_SCHEMA = "knowledge-engine-m25-6-acceptance/v1"

M25_6_STATUS = "m25_6_review_surface_accepted"
M25_6_MAIN_SEAL = "134edbcfa3841321d3ea1106d35243b866cb6913"
M25_6_IMPLEMENTATION_MERGE = "dd1559f7730c796933dfe0996acc0a558870a61e"

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._@-]{3,128}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
ALLOWED_ROOTS = ("bundle/concepts/", "provenance/", "registry/", "reviews/")
TERMINAL_ACTIONS = {"approve", "map", "edit", "split", "reject"}
WRITE_ACTIONS = TERMINAL_ACTIONS - {"reject"}
DISPOSITIONS = {"create", "replace", "delete", "no_write"}
MAX_FILES = 2_000
MAX_ITEMS = 1_000
MAX_OPERATIONS = 4_000
MAX_CONTENT_BYTES = 1_000_000
FORBIDDEN_LIVE_ACTORS = {"browser-reviewer", "synthetic-reviewer", "synthetic-knowledge-owner"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def content_digest(value: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError("M25-SOURCE-101 content must be UTF-8 text")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sign(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    output = dict(value)
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
        raise IntegrityError(f"M25-SOURCE-102 cannot load {path}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M25-SOURCE-103 {path.name} must be an object")
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
        raise IntegrityError(f"M25-SOURCE-104 invalid {label}")
    return value


def _actor(value: Any, label: str) -> str:
    if not isinstance(value, str) or ACTOR_RE.fullmatch(value) is None:
        raise AuthorizationError(f"M25-SOURCE-105 invalid {label}")
    return value


def _safe_path(value: Any) -> str:
    if not isinstance(value, str):
        raise IntegrityError("M25-SOURCE-106 Source path must be text")
    if (
        not value
        or value.startswith("/")
        or ".." in value.split("/")
        or "//" in value
        or SAFE_PATH.fullmatch(value) is None
        or not value.startswith(ALLOWED_ROOTS)
        or not value.endswith((".md", ".json"))
    ):
        raise IntegrityError("M25-SOURCE-107 unsafe Source path")
    return value


def validate_acceptance(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != ACCEPTANCE_SCHEMA:
        raise IntegrityError("M25-SOURCE-108 invalid M25.6 acceptance schema")
    if value.get("status") != M25_6_STATUS:
        raise IntegrityError("M25-SOURCE-109 M25.6 is not accepted")
    implementation = value.get("implementation")
    next_stage = value.get("next_stage")
    governance = value.get("governance")
    if (
        not isinstance(implementation, dict)
        or implementation.get("merge_sha") != M25_6_IMPLEMENTATION_MERGE
    ):
        raise IntegrityError("M25-SOURCE-110 M25.6 implementation identity drift")
    if not isinstance(next_stage, dict) or next_stage.get("stage_id") != "M25.7":
        raise IntegrityError("M25-SOURCE-111 invalid M25.7 predecessor transition")
    if not isinstance(governance, dict) or governance.get("m25_7_authorized") is not False:
        raise IntegrityError("M25-SOURCE-112 predecessor authority drift")
    return json.loads(json.dumps(value))


def validate_batch(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != BATCH_SCHEMA:
        raise IntegrityError("M25-SOURCE-113 invalid review batch schema")
    batch_sha = verify_signed(value, "batch_sha256", "M25-SOURCE-114 batch digest mismatch")
    items = value.get("items")
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= MAX_ITEMS
        or value.get("item_count") != len(items)
        or value.get("bulk_approval_permitted") is not False
        or value.get("source_write_permitted") is not False
        or value.get("github_pr_creation_permitted") is not False
        or value.get("m25_7_authorized") is not False
    ):
        raise IntegrityError("M25-SOURCE-115 invalid batch population or authority")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise IntegrityError("M25-SOURCE-116 malformed review item")
        review_item_id = item.get("review_item_id")
        state_sha = item.get("review_state_sha256")
        if not isinstance(review_item_id, str) or review_item_id in seen:
            raise IntegrityError("M25-SOURCE-117 duplicate review item")
        _hex(state_sha, 64, "review state digest")
        unsigned = dict(item)
        unsigned.pop("review_item_id", None)
        unsigned.pop("review_state_sha256", None)
        if state_sha != digest(unsigned) or review_item_id != f"m25review_{state_sha[:32]}":
            raise IntegrityError("M25-SOURCE-118 review state identity drift")
        seen.add(review_item_id)
    if batch_sha != value.get("batch_sha256"):
        raise IntegrityError("M25-SOURCE-119 batch identity drift")
    return json.loads(json.dumps(value))


def _latest_records(
    audit: Mapping[str, Any], batch: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    if audit.get("schema_version") != AUDIT_SCHEMA:
        raise IntegrityError("M25-SOURCE-120 invalid audit schema")
    verify_signed(audit, "audit_sha256", "M25-SOURCE-121 audit digest mismatch")
    if audit.get("batch_sha256") != batch["batch_sha256"]:
        raise IntegrityError("M25-SOURCE-122 audit batch mismatch")
    records = audit.get("records")
    if not isinstance(records, list) or len(records) > MAX_ITEMS * 2:
        raise IntegrityError("M25-SOURCE-123 invalid decision population")
    previous: str | None = None
    latest: dict[str, dict[str, Any]] = {}
    for sequence, record in enumerate(records, start=1):
        if not isinstance(record, dict) or record.get("schema_version") != DECISION_SCHEMA:
            raise IntegrityError("M25-SOURCE-124 malformed decision record")
        verify_signed(record, "decision_sha256", "M25-SOURCE-125 decision digest mismatch")
        if record.get("sequence") != sequence or record.get("previous_decision_sha256") != previous:
            raise IntegrityError("M25-SOURCE-126 decision chain mismatch")
        if (
            record.get("batch_sha256") != batch["batch_sha256"]
            or record.get("authority") != "admission_decision_only"
            or record.get("canonical_knowledge") is not False
            or record.get("production_authority") is not False
            or record.get("source_write_permitted") is not False
            or record.get("github_pr_creation_permitted") is not False
            or record.get("m25_7_authorized") is not False
        ):
            raise IntegrityError("M25-SOURCE-127 decision binding or authority drift")
        review_item_id = record.get("review_item_id")
        if not isinstance(review_item_id, str):
            raise IntegrityError("M25-SOURCE-128 invalid decision item identity")
        latest[review_item_id] = json.loads(json.dumps(record))
        previous = record["decision_sha256"]
    expected_items = {item["review_item_id"] for item in batch["items"]}
    if set(latest) != expected_items:
        raise IntegrityError("M25-SOURCE-129 incomplete terminal decision coverage")
    if any(record.get("action") not in TERMINAL_ACTIONS for record in latest.values()):
        raise IntegrityError("M25-SOURCE-130 deferred or non-terminal decision blocks Source plan")
    if (
        audit.get("review_complete") is not True
        or audit.get("admission_ready") is not True
        or audit.get("terminal_item_count") != batch["item_count"]
        or audit.get("deferred_item_count") != 0
        or audit.get("pending_item_count") != 0
        or audit.get("latest_item_decision_count") != batch["item_count"]
        or audit.get("source_write_permitted") is not False
        or audit.get("github_pr_creation_permitted") is not False
        or audit.get("m25_7_authorized") is not False
    ):
        raise IntegrityError("M25-SOURCE-131 audit is not complete and terminal")
    return latest


def validate_source_baseline(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != BASELINE_SCHEMA:
        raise IntegrityError("M25-SOURCE-132 invalid Source baseline schema")
    manifest_sha = verify_signed(
        value, "manifest_sha256", "M25-SOURCE-133 baseline digest mismatch"
    )
    mode = value.get("mode")
    if mode not in {"live", "test_only"}:
        raise IntegrityError("M25-SOURCE-134 invalid baseline mode")
    _hex(value.get("source_base_sha"), 40, "Source base SHA")
    repository = value.get("source_repository")
    files = value.get("files")
    if (
        not isinstance(repository, str)
        or "/" not in repository
        or not isinstance(files, list)
        or len(files) > MAX_FILES
        or value.get("file_count") != len(files)
    ):
        raise IntegrityError("M25-SOURCE-135 invalid Source baseline population")
    seen: set[str] = set()
    for file in files:
        if not isinstance(file, dict) or set(file) != {"path", "sha256", "content_utf8"}:
            raise IntegrityError("M25-SOURCE-136 malformed Source baseline file")
        path = _safe_path(file["path"])
        if path in seen:
            raise IntegrityError("M25-SOURCE-137 duplicate Source baseline path")
        seen.add(path)
        claimed = _hex(file["sha256"], 64, "Source file digest")
        if claimed != content_digest(file["content_utf8"]):
            raise IntegrityError("M25-SOURCE-138 Source baseline file digest mismatch")
    if manifest_sha != value.get("manifest_sha256"):
        raise IntegrityError("M25-SOURCE-139 Source baseline identity drift")
    return json.loads(json.dumps(value))


def _validate_operation(
    operation: Mapping[str, Any],
    *,
    action: str,
    baseline_by_path: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    required = {
        "operation_id",
        "disposition",
        "path",
        "expected_old_sha256",
        "new_content_utf8",
        "new_content_sha256",
        "rationale",
    }
    if set(operation) != required:
        raise IntegrityError("M25-SOURCE-140 malformed approved Source operation")
    operation_id = operation.get("operation_id")
    disposition = operation.get("disposition")
    if not isinstance(operation_id, str) or not operation_id or disposition not in DISPOSITIONS:
        raise IntegrityError("M25-SOURCE-141 invalid Source operation identity")
    rationale = operation.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2_000:
        raise IntegrityError("M25-SOURCE-142 invalid Source operation rationale")
    if disposition == "no_write":
        if action != "reject" or any(
            operation.get(key) is not None
            for key in ("path", "expected_old_sha256", "new_content_utf8", "new_content_sha256")
        ):
            raise IntegrityError("M25-SOURCE-143 invalid no-write operation")
        return dict(operation)
    if action == "reject":
        raise IntegrityError("M25-SOURCE-144 rejected decision cannot write Source")
    path = _safe_path(operation.get("path"))
    existing = baseline_by_path.get(path)
    expected_old = operation.get("expected_old_sha256")
    new_content = operation.get("new_content_utf8")
    new_digest = operation.get("new_content_sha256")
    if disposition == "create":
        if existing is not None or expected_old is not None:
            raise IntegrityError("M25-SOURCE-145 create operation collides with Source")
        if not isinstance(new_content, str) or not isinstance(new_digest, str):
            raise IntegrityError("M25-SOURCE-146 create operation lacks approved bytes")
    elif disposition == "replace":
        if existing is None or expected_old != existing["sha256"]:
            raise IntegrityError("M25-SOURCE-147 stale replace operation")
        if not isinstance(new_content, str) or not isinstance(new_digest, str):
            raise IntegrityError("M25-SOURCE-148 replace operation lacks approved bytes")
    elif disposition == "delete":
        if existing is None or expected_old != existing["sha256"]:
            raise IntegrityError("M25-SOURCE-149 stale delete operation")
        if new_content is not None or new_digest is not None:
            raise IntegrityError("M25-SOURCE-150 delete operation contains new bytes")
    if isinstance(new_content, str):
        if len(new_content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise IntegrityError("M25-SOURCE-151 approved Source file exceeds byte limit")
        _hex(new_digest, 64, "approved new-content digest")
        if content_digest(new_content) != new_digest:
            raise IntegrityError("M25-SOURCE-152 approved Source bytes digest mismatch")
    clean = dict(operation)
    clean["path"] = path
    clean["rationale"] = rationale.strip()
    return clean


def validate_item_authority(
    value: Mapping[str, Any],
    *,
    batch: Mapping[str, Any],
    audit: Mapping[str, Any],
    latest: Mapping[str, Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    if value.get("schema_version") != AUTHORITY_SCHEMA:
        raise AuthorizationError("M25-SOURCE-153 invalid item authority schema")
    authority_sha = verify_signed(
        value, "authority_sha256", "M25-SOURCE-154 authority digest mismatch"
    )
    mode = value.get("mode")
    if mode not in {"live", "test_only"} or mode != baseline["mode"]:
        raise AuthorizationError("M25-SOURCE-155 authority mode mismatch")
    actor = _actor(value.get("actor"), "knowledge authority actor")
    if value.get("actor_role") != "knowledge_owner":
        raise AuthorizationError("M25-SOURCE-156 invalid authority role")
    comment_id = value.get("authority_comment_id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise AuthorizationError("M25-SOURCE-157 invalid authority comment identity")
    if mode == "live" and actor in FORBIDDEN_LIVE_ACTORS:
        raise AuthorizationError(
            "M25-SOURCE-158 synthetic or browser actor cannot authorize live Source"
        )
    if (
        value.get("batch_sha256") != batch["batch_sha256"]
        or value.get("audit_sha256") != audit["audit_sha256"]
        or value.get("source_base_sha") != baseline["source_base_sha"]
        or value.get("source_manifest_sha256") != baseline["manifest_sha256"]
        or value.get("canonical_decisions_attested") is not True
        or value.get("source_pr_preparation_authorized") is not True
        or value.get("source_pr_opening_authorized") is not False
    ):
        raise AuthorizationError("M25-SOURCE-159 stale or over-broad item authority")
    decisions = value.get("decisions")
    if not isinstance(decisions, list) or value.get("item_count") != len(decisions):
        raise AuthorizationError("M25-SOURCE-160 invalid authority decision population")
    if len(decisions) != batch["item_count"] or len(decisions) > MAX_ITEMS:
        raise AuthorizationError("M25-SOURCE-161 authority lacks full item population")
    baseline_by_path = {file["path"]: file for file in baseline["files"]}
    batch_by_id = {item["review_item_id"]: item for item in batch["items"]}
    seen_items: set[str] = set()
    seen_operations: set[str] = set()
    path_owner: dict[str, str] = {}
    clean_decisions: list[dict[str, Any]] = []
    operation_count = 0
    for decision in decisions:
        required = {
            "review_item_id",
            "decision_sha256",
            "review_state_sha256",
            "action",
            "source_operations",
        }
        if not isinstance(decision, dict) or set(decision) != required:
            raise AuthorizationError("M25-SOURCE-162 malformed authority decision")
        review_item_id = decision.get("review_item_id")
        if not isinstance(review_item_id, str) or review_item_id in seen_items:
            raise AuthorizationError("M25-SOURCE-163 duplicate authority item")
        record = latest.get(review_item_id)
        item = batch_by_id.get(review_item_id)
        if record is None or item is None:
            raise AuthorizationError("M25-SOURCE-164 unknown authority item")
        if (
            record.get("reviewer") != actor
            or decision.get("decision_sha256") != record.get("decision_sha256")
            or decision.get("review_state_sha256") != record.get("review_state_sha256")
            or decision.get("review_state_sha256") != item.get("review_state_sha256")
            or decision.get("action") != record.get("action")
        ):
            raise AuthorizationError("M25-SOURCE-165 authority does not bind exact decision")
        action = decision["action"]
        operations = decision.get("source_operations")
        if not isinstance(operations, list) or not operations:
            raise AuthorizationError("M25-SOURCE-166 decision lacks explicit Source disposition")
        if action in WRITE_ACTIONS and all(
            op.get("disposition") == "no_write" for op in operations
        ):
            raise AuthorizationError(
                "M25-SOURCE-167 approved write decision lacks exact Source bytes"
            )
        clean_operations: list[dict[str, Any]] = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise AuthorizationError("M25-SOURCE-168 malformed Source operation")
            clean = _validate_operation(operation, action=action, baseline_by_path=baseline_by_path)
            operation_id = clean["operation_id"]
            if operation_id in seen_operations:
                raise AuthorizationError("M25-SOURCE-169 duplicate operation identity")
            seen_operations.add(operation_id)
            path = clean.get("path")
            if path is not None:
                owner = path_owner.setdefault(path, review_item_id)
                if owner != review_item_id:
                    raise AuthorizationError("M25-SOURCE-170 cross-item Source path collision")
            clean_operations.append(clean)
            operation_count += 1
        clean_decisions.append(
            {
                **{key: decision[key] for key in required - {"source_operations"}},
                "source_operations": sorted(
                    clean_operations,
                    key=lambda op: (op["path"] or "", op["disposition"], op["operation_id"]),
                ),
            }
        )
        seen_items.add(review_item_id)
    if seen_items != set(batch_by_id) or operation_count > MAX_OPERATIONS:
        raise AuthorizationError("M25-SOURCE-171 incomplete or unbounded authority population")
    clean_value = dict(value)
    clean_value["decisions"] = sorted(clean_decisions, key=lambda row: row["review_item_id"])
    clean_value["authority_sha256"] = authority_sha
    return clean_value


def build_source_pr_plan(
    batch_value: Mapping[str, Any],
    audit_value: Mapping[str, Any],
    acceptance_value: Mapping[str, Any],
    baseline_value: Mapping[str, Any],
    authority_value: Mapping[str, Any],
) -> dict[str, Any]:
    acceptance = validate_acceptance(acceptance_value)
    batch = validate_batch(batch_value)
    baseline = validate_source_baseline(baseline_value)
    latest = _latest_records(audit_value, batch)
    authority = validate_item_authority(
        authority_value,
        batch=batch,
        audit=audit_value,
        latest=latest,
        baseline=baseline,
    )
    operations: list[dict[str, Any]] = []
    write_count = 0
    no_write_count = 0
    for decision in authority["decisions"]:
        for operation in decision["source_operations"]:
            row = {
                "review_item_id": decision["review_item_id"],
                "decision_sha256": decision["decision_sha256"],
                "review_state_sha256": decision["review_state_sha256"],
                "action": decision["action"],
                **operation,
            }
            operations.append(row)
            if operation["disposition"] == "no_write":
                no_write_count += 1
            else:
                write_count += 1
    operations.sort(
        key=lambda row: (
            row["path"] or "",
            row["review_item_id"],
            row["disposition"],
            row["operation_id"],
        )
    )
    authority_sha = authority["authority_sha256"]
    branch_name = f"m25-7/approved-{authority_sha[:12]}"
    plan = {
        "schema_version": PLAN_SCHEMA,
        "status": "m25_7_source_pr_plan_candidate",
        "mode": authority["mode"],
        "predecessor_status": acceptance["status"],
        "predecessor_main_seal_sha": M25_6_MAIN_SEAL,
        "source_repository": baseline["source_repository"],
        "source_base_sha": baseline["source_base_sha"],
        "source_manifest_sha256": baseline["manifest_sha256"],
        "batch_sha256": batch["batch_sha256"],
        "audit_sha256": audit_value["audit_sha256"],
        "authority_sha256": authority_sha,
        "item_count": batch["item_count"],
        "operation_count": len(operations),
        "write_operation_count": write_count,
        "no_write_operation_count": no_write_count,
        "operations": operations,
        "branch": {
            "name": branch_name,
            "base_sha": baseline["source_base_sha"],
            "commit_title": "M25.7 apply approved knowledge decisions",
        },
        "pull_request": {
            "title": "M25.7 approved knowledge admission",
            "body_lines": [
                "Applies only exact Daniel-approved item decisions and Source bytes.",
                f"Decision authority: `{authority_sha}`.",
                f"Source base: `{baseline['source_base_sha']}`.",
                "No automatic merge, release, production pointer or serving authority.",
            ],
            "draft": True,
        },
        "exact_plan_approval_required_before_source_write": True,
        "source_branch_write_permitted": False,
        "github_pr_creation_permitted": False,
        "source_pr_merge_permitted": False,
        "canonical_knowledge": False,
        "production_authority": False,
        "release_mutation_permitted": False,
        "production_mutation_permitted": False,
        "m25_8_authorized": False,
    }
    plan["plan_sha256"] = digest(plan)
    return plan


def validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != PLAN_SCHEMA:
        raise IntegrityError("M25-SOURCE-172 invalid Source PR plan schema")
    verify_signed(value, "plan_sha256", "M25-SOURCE-173 plan digest mismatch")
    operations = value.get("operations")
    if (
        value.get("status") != "m25_7_source_pr_plan_candidate"
        or value.get("mode") not in {"live", "test_only"}
        or not isinstance(operations, list)
        or value.get("operation_count") != len(operations)
        or value.get("source_branch_write_permitted") is not False
        or value.get("github_pr_creation_permitted") is not False
        or value.get("source_pr_merge_permitted") is not False
        or value.get("release_mutation_permitted") is not False
        or value.get("production_mutation_permitted") is not False
        or value.get("m25_8_authorized") is not False
    ):
        raise IntegrityError("M25-SOURCE-174 invalid plan population or authority")
    return json.loads(json.dumps(value))


def authorize_source_pr_opening(
    plan_value: Mapping[str, Any], approval_value: Mapping[str, Any]
) -> dict[str, Any]:
    plan = validate_plan(plan_value)
    if approval_value.get("schema_version") != PLAN_APPROVAL_SCHEMA:
        raise AuthorizationError("M25-SOURCE-175 invalid plan approval schema")
    approval_sha = verify_signed(
        approval_value,
        "approval_sha256",
        "M25-SOURCE-176 plan approval digest mismatch",
    )
    actor = _actor(approval_value.get("actor"), "plan approval actor")
    if plan["mode"] != "live" or actor in FORBIDDEN_LIVE_ACTORS:
        raise AuthorizationError("M25-SOURCE-177 test or synthetic plan cannot open Source PR")
    comment_id = approval_value.get("authority_comment_id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise AuthorizationError("M25-SOURCE-178 invalid plan approval comment")
    if (
        approval_value.get("actor_role") != "knowledge_owner"
        or approval_value.get("plan_sha256") != plan["plan_sha256"]
        or approval_value.get("source_repository") != plan["source_repository"]
        or approval_value.get("source_base_sha") != plan["source_base_sha"]
        or approval_value.get("approved_branch_name") != plan["branch"]["name"]
        or approval_value.get("approved_for_source_branch_and_pr") is not True
        or approval_value.get("approved_for_merge") is not False
    ):
        raise AuthorizationError("M25-SOURCE-179 stale or over-broad plan approval")
    receipt = {
        "schema_version": OPENING_RECEIPT_SCHEMA,
        "status": "m25_7_source_pr_opening_authorized",
        "actor": actor,
        "authority_comment_id": comment_id,
        "plan_sha256": plan["plan_sha256"],
        "approval_sha256": approval_sha,
        "source_repository": plan["source_repository"],
        "source_base_sha": plan["source_base_sha"],
        "branch_name": plan["branch"]["name"],
        "source_branch_write_permitted": True,
        "github_pr_creation_permitted": True,
        "source_pr_merge_permitted": False,
        "release_mutation_permitted": False,
        "production_mutation_permitted": False,
        "m25_8_authorized": False,
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


def materialize_test_plan(
    plan_value: Mapping[str, Any],
    baseline_value: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    plan = validate_plan(plan_value)
    baseline = validate_source_baseline(baseline_value)
    if plan["mode"] != "test_only" or baseline["mode"] != "test_only":
        raise AuthorizationError("M25-SOURCE-180 live materialization is forbidden in this adapter")
    if (
        plan["source_base_sha"] != baseline["source_base_sha"]
        or plan["source_manifest_sha256"] != baseline["manifest_sha256"]
    ):
        raise IntegrityError("M25-SOURCE-181 stale materialization baseline")
    output_root.mkdir(parents=True, exist_ok=True)
    for file in baseline["files"]:
        target = output_root / file["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file["content_utf8"], encoding="utf-8")
    written: list[dict[str, Any]] = []
    for operation in plan["operations"]:
        disposition = operation["disposition"]
        if disposition == "no_write":
            continue
        target = output_root / operation["path"]
        if disposition == "delete":
            if (
                not target.exists()
                or content_digest(target.read_text(encoding="utf-8"))
                != operation["expected_old_sha256"]
            ):
                raise IntegrityError("M25-SOURCE-182 stale test delete")
            target.unlink()
            written.append({"path": operation["path"], "disposition": disposition, "sha256": None})
            continue
        if disposition == "replace":
            if (
                not target.exists()
                or content_digest(target.read_text(encoding="utf-8"))
                != operation["expected_old_sha256"]
            ):
                raise IntegrityError("M25-SOURCE-183 stale test replace")
        elif target.exists():
            raise IntegrityError("M25-SOURCE-184 test create collision")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(operation["new_content_utf8"], encoding="utf-8")
        actual = content_digest(target.read_text(encoding="utf-8"))
        if actual != operation["new_content_sha256"]:
            raise IntegrityError("M25-SOURCE-185 test materialization digest mismatch")
        written.append({"path": operation["path"], "disposition": disposition, "sha256": actual})
    receipt = {
        "schema_version": "knowledge-engine-m25-7-test-materialization/v1",
        "mode": "test_only",
        "plan_sha256": plan["plan_sha256"],
        "source_base_sha": baseline["source_base_sha"],
        "written_file_count": len(written),
        "written_files": sorted(written, key=lambda row: row["path"]),
        "live_source_write_permitted": False,
        "github_pr_creation_permitted": False,
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


__all__ = [
    "AUTHORITY_SCHEMA",
    "BASELINE_SCHEMA",
    "OPENING_RECEIPT_SCHEMA",
    "PLAN_APPROVAL_SCHEMA",
    "PLAN_SCHEMA",
    "authorize_source_pr_opening",
    "build_source_pr_plan",
    "canonical_bytes",
    "content_digest",
    "digest",
    "load_json",
    "materialize_test_plan",
    "sign",
    "validate_acceptance",
    "validate_batch",
    "validate_item_authority",
    "validate_plan",
    "validate_source_baseline",
    "verify_signed",
    "write_json_atomic",
]
