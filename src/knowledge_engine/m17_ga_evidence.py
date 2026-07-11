from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "knowledge-engine-m17-ga-evidence-registry/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m17-ga-evidence-report/v1"
EXPECTED_CAPABILITIES = [
    ("GA-01", "Immutable intake"),
    ("GA-02", "Evidence-bound synthesis"),
    ("GA-03", "Dedupe and contradiction handling"),
    ("GA-04", "Human review"),
    ("GA-05", "Source validation"),
    ("GA-06", "Deterministic candidate build"),
    ("GA-07", "Runtime evaluation suite"),
    ("GA-08", "Production request governance"),
    ("GA-09", "Explicit approval"),
    ("GA-10", "Production promotion"),
    ("GA-11", "Citation quality"),
    ("GA-12", "ACL safety"),
    ("GA-13", "Observability"),
    ("GA-14", "Freshness propagation"),
    ("GA-15", "Idempotent replay"),
    ("GA-16", "Rollback and restore"),
    ("GA-17", "Multi-batch operations"),
    ("GA-18", "Real user-facing query experience"),
    ("GA-19", "Feedback correction loop"),
    ("GA-20", "Operator-independent handoff"),
]
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_STATES = {"evidence_complete", "gap", "blocked"}
ALLOWED_ROOTS = ("src/", "tests/", ".github/workflows/", "docs/", "production_promotions/")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _issue(code: str, subject: str, detail: str) -> dict[str, str]:
    return {"code": code, "subject": subject, "detail": detail}


def _safe_repo_path(root: Path, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path or raw_path.startswith(("/", "~")):
        return None
    if not raw_path.startswith(ALLOWED_ROOTS):
        return None
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _validate_reference(
    root: Path,
    capability_id: str,
    field: str,
    raw_path: object,
    issues: list[dict[str, str]],
) -> None:
    path = _safe_repo_path(root, raw_path)
    if path is None:
        issues.append(_issue("unsafe_path", capability_id, f"{field}: {raw_path!r}"))
        return
    if not path.is_file():
        issues.append(_issue("missing_path", capability_id, f"{field}: {raw_path}"))


def load_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ga_evidence(root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry = load_registry(registry_path)
    issues: list[dict[str, str]] = []

    if registry.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue("schema_version", "registry", "unexpected schema version"))
    if registry.get("required_capability_count") != len(EXPECTED_CAPABILITIES):
        issues.append(_issue("capability_count_contract", "registry", "required count must be 20"))
    if registry.get("ga_declaration_allowed") is not False:
        issues.append(_issue("premature_ga_declaration", "registry", "M17.6 must not declare GA"))
    if registry.get("overall_state") != "ready_for_m17_7":
        issues.append(_issue("overall_state", "registry", "state must remain ready_for_m17_7"))

    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
        issues.append(_issue("capabilities_type", "registry", "capabilities must be a list"))

    expected_ids = [item[0] for item in EXPECTED_CAPABILITIES]
    seen_ids: list[str] = []
    complete_count = 0
    gap_count = 0

    for index, capability in enumerate(capabilities, start=1):
        subject = f"row-{index}"
        if not isinstance(capability, dict):
            issues.append(_issue("capability_type", subject, "row must be an object"))
            continue
        capability_id = capability.get("id")
        if isinstance(capability_id, str):
            subject = capability_id
            seen_ids.append(capability_id)
        else:
            issues.append(_issue("capability_id", subject, "missing capability id"))
            continue

        if capability.get("order") != index:
            issues.append(_issue("capability_order", subject, f"expected order {index}"))
        expected = EXPECTED_CAPABILITIES[index - 1] if index <= len(EXPECTED_CAPABILITIES) else None
        if expected and (capability_id, capability.get("name")) != expected:
            issues.append(_issue("capability_identity", subject, f"expected {expected!r}"))
        if not isinstance(capability.get("owning_milestone"), str) or not capability["owning_milestone"]:
            issues.append(_issue("owning_milestone", subject, "owning milestone is required"))

        for field in ("contract_modules", "tests", "workflows"):
            values = capability.get(field)
            if not isinstance(values, list) or not values:
                issues.append(_issue("narrative_only", subject, f"{field} must be non-empty"))
                continue
            for value in values:
                _validate_reference(root, subject, field, value, issues)

        evidence = capability.get("evidence")
        if not isinstance(evidence, dict):
            issues.append(_issue("evidence_type", subject, "evidence must be an object"))
        else:
            pr = evidence.get("pr")
            if not isinstance(pr, int) or pr < 1:
                issues.append(_issue("merged_pr", subject, "positive merged PR number required"))
            merge_commit = evidence.get("merge_commit")
            if not isinstance(merge_commit, str) or SHA40_RE.fullmatch(merge_commit) is None:
                issues.append(_issue("merge_commit", subject, "40-character lowercase commit required"))
            matrix_path = _safe_repo_path(root, evidence.get("matrix_path"))
            anchor = evidence.get("matrix_anchor")
            if matrix_path is None or not matrix_path.is_file():
                issues.append(_issue("matrix_path", subject, "matrix path is missing or unsafe"))
            elif not isinstance(anchor, str) or not anchor or anchor not in matrix_path.read_text(encoding="utf-8"):
                issues.append(_issue("matrix_anchor", subject, "stable matrix anchor is missing"))

        state = capability.get("state")
        if state not in ALLOWED_STATES:
            issues.append(_issue("capability_state", subject, f"invalid state: {state!r}"))
        if state == "evidence_complete":
            complete_count += 1
            if capability.get("gap") != "none":
                issues.append(_issue("unresolved_gap", subject, "complete row must have gap=none"))
            if not capability.get("closure_action"):
                issues.append(_issue("closure_action", subject, "closure action is required"))
        else:
            gap_count += 1
            if capability.get("gap") in (None, "", "none"):
                issues.append(_issue("gap_detail", subject, "gap or blocked row needs detail"))

    if len(seen_ids) != len(set(seen_ids)):
        issues.append(_issue("duplicate_capability", "registry", "capability IDs must be unique"))
    if seen_ids != expected_ids:
        issues.append(_issue("capability_set", "registry", "exact ordered GA-01 through GA-20 required"))
    if len(capabilities) != len(EXPECTED_CAPABILITIES):
        issues.append(_issue("capability_count", "registry", f"found {len(capabilities)} rows"))
    if complete_count != len(EXPECTED_CAPABILITIES) or gap_count:
        issues.append(_issue("not_ready_for_m17_7", "registry", "all 20 rows must be evidence_complete"))

    issues.sort(key=lambda item: (item["code"], item["subject"], item["detail"]))
    registry_sha256 = sha256_hex(canonical_json(registry))
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "passed" if not issues else "failed",
        "readiness": "ready_for_m17_7" if not issues else "blocked",
        "ga_declaration_allowed": False,
        "capability_count": len(capabilities),
        "evidence_complete_count": complete_count,
        "gap_count": gap_count,
        "registry_sha256": registry_sha256,
        "issues": issues,
    }
    report["report_sha256"] = sha256_hex(canonical_json(report))
    return report


def verify_report(report: dict[str, Any]) -> bool:
    claimed = report.get("report_sha256")
    if not isinstance(claimed, str):
        return False
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    return claimed == sha256_hex(canonical_json(unsigned))
