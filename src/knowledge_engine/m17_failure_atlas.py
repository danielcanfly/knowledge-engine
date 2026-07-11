from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "knowledge-engine-failure-atlas/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-failure-atlas-report/v1"
REQUIRED_PLANES = {"build", "control", "feedback", "operator", "runtime"}
REQUIRED_CATEGORIES = {
    "acl",
    "approval",
    "citation",
    "documentation",
    "feedback",
    "identity",
    "integrity",
    "recovery",
    "release",
    "replay",
    "runtime",
    "security",
    "source",
    "storage",
}
REQUIRED_STATES = {
    "authorization",
    "blocked",
    "degraded",
    "incident",
    "integrity",
    "security",
    "unknown",
}
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
ALLOWED_ESCALATIONS = {
    "engine_maintainer",
    "feedback_owner",
    "incident_commander",
    "release_authority",
    "security_owner",
    "source_owner",
}
_LIST_FIELDS = (
    "evidence",
    "probable_causes",
    "safe_actions",
    "signals",
    "stop_conditions",
)
_DYNAMIC_ID_PATTERNS = (
    re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"),
    re.compile(r"\b20[0-9]{6}T[0-9]{6}Z-[0-9a-f]{12}\b"),
)
_PRIVATE_PATTERNS = (
    "authorization:",
    "bearer ",
    "cookie:",
    "-----begin ",
    "secret_access_key",
    "access_key_id=",
    "raw_query",
    "raw_answer",
    "s3://",
    "r2://",
    "file://",
    "http://",
    "https://",
)
_UNSAFE_COMMAND_FRAGMENTS = (
    "--force",
    "append-ledger",
    "aws s3",
    "closeout",
    "copy-object",
    "curl -x delete",
    "curl -x post",
    "curl -x put",
    "delete-object",
    "gh pr merge",
    "git push",
    "promote-release",
    "purge",
    "put-object",
    "rclone",
    "rm -rf",
    "rollback-release",
    "rotate-credential",
    "wrangler r2",
)
_ALLOWED_COMMAND_PREFIXES = (
    "knowledge-m13 audit ",
    "knowledge-m13 ledger-summary ",
    "knowledge-m13 lookup ",
    "knowledge-m13 status ",
    "python scripts/m17_failure_atlas_acceptance.py ",
)


@dataclass(frozen=True)
class FailureAtlasIssue:
    code: str
    subject: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "subject": self.subject}


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"failure registry is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("failure registry must be a JSON object")
    return payload


def _safe_relative_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _document_issues(path: Path, relative: str) -> list[FailureAtlasIssue]:
    text = _read_text(path)
    if text is None:
        return [
            FailureAtlasIssue(
                code="document_unreadable",
                subject=relative,
                detail="owned troubleshooting document must be readable UTF-8",
            )
        ]
    lower = text.lower()
    issues: list[FailureAtlasIssue] = []
    if any(pattern.search(text) for pattern in _DYNAMIC_ID_PATTERNS):
        issues.append(
            FailureAtlasIssue(
                code="stale_dynamic_identity",
                subject=relative,
                detail="troubleshooting canon must not embed current dynamic identities",
            )
        )
    for fragment in _PRIVATE_PATTERNS:
        if fragment in lower:
            issues.append(
                FailureAtlasIssue(
                    code="privacy_unsafe_content",
                    subject=relative,
                    detail=f"owned document contains forbidden fragment: {fragment}",
                )
            )
    return issues


def _validate_reference(
    root: Path,
    subject: str,
    value: object,
    field: str,
) -> tuple[dict[str, str] | None, list[FailureAtlasIssue]]:
    if not isinstance(value, dict):
        return None, [
            FailureAtlasIssue(
                code="invalid_reference",
                subject=subject,
                detail=f"{field} must be an object",
            )
        ]
    raw_path = value.get("path")
    anchor = value.get("anchor")
    path = _safe_relative_path(root, raw_path)
    issues: list[FailureAtlasIssue] = []
    if path is None:
        issues.append(
            FailureAtlasIssue(
                code="unsafe_reference_path",
                subject=subject,
                detail=f"{field} path must be safe and repository-relative",
            )
        )
    elif not path.is_file():
        issues.append(
            FailureAtlasIssue(
                code="missing_reference_path",
                subject=subject,
                detail=f"{field} path does not exist: {raw_path}",
            )
        )
    if not isinstance(anchor, str) or not anchor.strip():
        issues.append(
            FailureAtlasIssue(
                code="missing_reference_anchor",
                subject=subject,
                detail=f"{field} anchor must be non-empty",
            )
        )
    elif path is not None and path.is_file():
        text = _read_text(path)
        if text is None:
            issues.append(
                FailureAtlasIssue(
                    code="reference_unreadable",
                    subject=subject,
                    detail=f"{field} path is not readable UTF-8: {raw_path}",
                )
            )
        elif _normalized_text(anchor) not in _normalized_text(text):
            issues.append(
                FailureAtlasIssue(
                    code="missing_reference_anchor",
                    subject=subject,
                    detail=f"{field} anchor not found in {raw_path}: {anchor}",
                )
            )
    if issues:
        return None, issues
    return {"anchor": anchor, "path": raw_path}, []


def _validate_string_list(
    subject: str,
    field: str,
    value: object,
    minimum: int = 1,
) -> tuple[list[str], list[FailureAtlasIssue]]:
    if not isinstance(value, list) or len(value) < minimum:
        return [], [
            FailureAtlasIssue(
                code="incomplete_failure_entry",
                subject=subject,
                detail=f"{field} must contain at least {minimum} item(s)",
            )
        ]
    normalized: list[str] = []
    issues: list[FailureAtlasIssue] = []
    for item in value:
        if not isinstance(item, str) or len(item.strip()) < 3:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_field",
                    subject=subject,
                    detail=f"{field} items must be meaningful strings",
                )
            )
            continue
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        issues.append(
            FailureAtlasIssue(
                code="duplicate_failure_field",
                subject=subject,
                detail=f"{field} items must be unique within an entry",
            )
        )
    return normalized, issues


def _validate_command(subject: str, value: object) -> list[FailureAtlasIssue]:
    if value is None:
        return []
    if not isinstance(value, str) or not value.strip():
        return [
            FailureAtlasIssue(
                code="invalid_diagnostic_command",
                subject=subject,
                detail="diagnostic_command must be null or a non-empty string",
            )
        ]
    lower = value.lower()
    issues: list[FailureAtlasIssue] = []
    if not lower.startswith(_ALLOWED_COMMAND_PREFIXES):
        issues.append(
            FailureAtlasIssue(
                code="unapproved_diagnostic_command",
                subject=subject,
                detail="diagnostic command is not on the read-only allowlist",
            )
        )
    for fragment in _UNSAFE_COMMAND_FRAGMENTS:
        if fragment in lower:
            issues.append(
                FailureAtlasIssue(
                    code="unsafe_diagnostic_command",
                    subject=subject,
                    detail=f"diagnostic command contains forbidden fragment: {fragment}",
                )
            )
    return issues


def _base_report(
    *,
    status: str,
    entry_count: int,
    signal_count: int,
    covered_planes: set[str],
    covered_categories: set[str],
    covered_states: set[str],
    reference_paths: set[str],
    issues: list[FailureAtlasIssue],
) -> dict[str, Any]:
    return {
        "covered_categories": sorted(covered_categories),
        "covered_planes": sorted(covered_planes),
        "covered_states": sorted(covered_states),
        "entry_count": entry_count,
        "issue_count": len(issues),
        "issues": [item.to_dict() for item in sorted(issues, key=lambda item: item.to_dict().values())],
        "reference_paths": sorted(reference_paths),
        "report_sha256": None,
        "schema_version": REPORT_SCHEMA_VERSION,
        "signal_count": signal_count,
        "status": status,
    }


def validate_failure_registry(*, root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry_path = registry_path.resolve()
    try:
        registry_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("registry path must be inside the repository root") from exc

    registry = load_registry(registry_path)
    issues: list[FailureAtlasIssue] = []
    if registry.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            FailureAtlasIssue(
                code="invalid_schema_version",
                subject="registry",
                detail=f"schema_version must be {SCHEMA_VERSION}",
            )
        )

    canonical_raw = registry.get("canonical_entry")
    canonical = _safe_relative_path(root, canonical_raw)
    if canonical is None or not canonical.is_file():
        issues.append(
            FailureAtlasIssue(
                code="missing_canonical_entry",
                subject="registry",
                detail="canonical_entry must resolve to an existing file",
            )
        )

    owned = registry.get("owned_documents")
    normalized_owned: list[str] = []
    if not isinstance(owned, list) or not owned:
        issues.append(
            FailureAtlasIssue(
                code="missing_owned_documents",
                subject="registry",
                detail="owned_documents must be a non-empty list",
            )
        )
    else:
        for item in owned:
            path = _safe_relative_path(root, item)
            if path is None or not path.is_file():
                issues.append(
                    FailureAtlasIssue(
                        code="missing_owned_document",
                        subject=str(item),
                        detail="owned document must be safe and exist",
                    )
                )
                continue
            relative = path.relative_to(root).as_posix()
            normalized_owned.append(relative)
            issues.extend(_document_issues(path, relative))
    if isinstance(canonical_raw, str) and canonical_raw not in normalized_owned:
        issues.append(
            FailureAtlasIssue(
                code="canonical_entry_not_owned",
                subject="registry",
                detail="canonical_entry must appear in owned_documents",
            )
        )

    required_planes = registry.get("required_planes")
    if required_planes != sorted(REQUIRED_PLANES):
        issues.append(
            FailureAtlasIssue(
                code="invalid_required_planes",
                subject="registry",
                detail=f"required_planes must equal {sorted(REQUIRED_PLANES)}",
            )
        )
    required_categories = registry.get("required_categories")
    if required_categories != sorted(REQUIRED_CATEGORIES):
        issues.append(
            FailureAtlasIssue(
                code="invalid_required_categories",
                subject="registry",
                detail=f"required_categories must equal {sorted(REQUIRED_CATEGORIES)}",
            )
        )
    required_states = registry.get("required_states")
    if required_states != sorted(REQUIRED_STATES):
        issues.append(
            FailureAtlasIssue(
                code="invalid_required_states",
                subject="registry",
                detail=f"required_states must equal {sorted(REQUIRED_STATES)}",
            )
        )

    entries = registry.get("entries")
    if not isinstance(entries, list) or len(entries) < 20:
        issues.append(
            FailureAtlasIssue(
                code="insufficient_failure_entries",
                subject="registry",
                detail="entries must contain at least 20 failure families",
            )
        )
        entries = [] if not isinstance(entries, list) else entries

    seen_ids: set[str] = set()
    seen_signals: set[str] = set()
    covered_planes: set[str] = set()
    covered_categories: set[str] = set()
    covered_states: set[str] = set()
    reference_paths: set[str] = set()
    normalized_entries: list[dict[str, Any]] = []

    for index, entry in enumerate(entries):
        subject = f"entry[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_entry",
                    subject=subject,
                    detail="failure entry must be an object",
                )
            )
            continue
        failure_id = entry.get("failure_id")
        if not isinstance(failure_id, str) or not re.fullmatch(r"F[0-9]{3}", failure_id):
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_id",
                    subject=subject,
                    detail="failure_id must match F followed by three digits",
                )
            )
            failure_id = subject
        elif failure_id in seen_ids:
            issues.append(
                FailureAtlasIssue(
                    code="duplicate_failure_id",
                    subject=failure_id,
                    detail="failure_id must be unique",
                )
            )
        seen_ids.add(failure_id)

        title = entry.get("title")
        if not isinstance(title, str) or len(title.strip()) < 12:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_title",
                    subject=failure_id,
                    detail="title must be a meaningful string",
                )
            )

        plane = entry.get("plane")
        if plane not in REQUIRED_PLANES:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_plane",
                    subject=failure_id,
                    detail=f"plane must be one of {sorted(REQUIRED_PLANES)}",
                )
            )
        else:
            covered_planes.add(plane)
        category = entry.get("category")
        if category not in REQUIRED_CATEGORIES:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_category",
                    subject=failure_id,
                    detail=f"category must be one of {sorted(REQUIRED_CATEGORIES)}",
                )
            )
        else:
            covered_categories.add(category)
        state = entry.get("state")
        if state not in REQUIRED_STATES:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_state",
                    subject=failure_id,
                    detail=f"state must be one of {sorted(REQUIRED_STATES)}",
                )
            )
        else:
            covered_states.add(state)
        severity = entry.get("severity")
        if severity not in ALLOWED_SEVERITIES:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_failure_severity",
                    subject=failure_id,
                    detail=f"severity must be one of {sorted(ALLOWED_SEVERITIES)}",
                )
            )
        escalation = entry.get("escalation")
        if escalation not in ALLOWED_ESCALATIONS:
            issues.append(
                FailureAtlasIssue(
                    code="invalid_escalation_target",
                    subject=failure_id,
                    detail=f"escalation must be one of {sorted(ALLOWED_ESCALATIONS)}",
                )
            )
        if state == "security" and (
            severity != "critical" or escalation != "security_owner"
        ):
            issues.append(
                FailureAtlasIssue(
                    code="security_escalation_invalid",
                    subject=failure_id,
                    detail="security state must be critical and escalate to security_owner",
                )
            )
        if state == "authorization" and escalation != "release_authority":
            issues.append(
                FailureAtlasIssue(
                    code="authorization_escalation_invalid",
                    subject=failure_id,
                    detail="authorization state must escalate to release_authority",
                )
            )

        normalized_lists: dict[str, list[str]] = {}
        for field in _LIST_FIELDS:
            minimum = 3 if field in {"evidence", "safe_actions"} else 1
            values, list_issues = _validate_string_list(
                failure_id,
                field,
                entry.get(field),
                minimum,
            )
            normalized_lists[field] = values
            issues.extend(list_issues)
        for signal in normalized_lists["signals"]:
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,95}", signal):
                issues.append(
                    FailureAtlasIssue(
                        code="invalid_signal_code",
                        subject=failure_id,
                        detail=f"signal must be a stable lower-case code: {signal}",
                    )
                )
            if signal in seen_signals:
                issues.append(
                    FailureAtlasIssue(
                        code="duplicate_signal_code",
                        subject=failure_id,
                        detail=f"signal is already owned by another entry: {signal}",
                    )
                )
            seen_signals.add(signal)

        issues.extend(_validate_command(failure_id, entry.get("diagnostic_command")))
        reference, reference_issues = _validate_reference(
            root,
            failure_id,
            entry.get("reference"),
            "reference",
        )
        recovery, recovery_issues = _validate_reference(
            root,
            failure_id,
            entry.get("recovery_reference"),
            "recovery_reference",
        )
        issues.extend(reference_issues)
        issues.extend(recovery_issues)
        if reference is not None:
            reference_paths.add(reference["path"])
        if recovery is not None:
            reference_paths.add(recovery["path"])

        normalized_entries.append(
            {
                "category": category,
                "diagnostic_command": entry.get("diagnostic_command"),
                "escalation": escalation,
                "failure_id": failure_id,
                "plane": plane,
                "severity": severity,
                "signals": normalized_lists["signals"],
                "state": state,
                "title": title,
            }
        )

    if covered_planes != REQUIRED_PLANES:
        issues.append(
            FailureAtlasIssue(
                code="plane_coverage_mismatch",
                subject="registry",
                detail=f"covered planes must equal {sorted(REQUIRED_PLANES)}",
            )
        )
    if covered_categories != REQUIRED_CATEGORIES:
        issues.append(
            FailureAtlasIssue(
                code="category_coverage_mismatch",
                subject="registry",
                detail=f"covered categories must equal {sorted(REQUIRED_CATEGORIES)}",
            )
        )
    if covered_states != REQUIRED_STATES:
        issues.append(
            FailureAtlasIssue(
                code="state_coverage_mismatch",
                subject="registry",
                detail=f"covered states must equal {sorted(REQUIRED_STATES)}",
            )
        )

    registry_text = registry_path.read_text(encoding="utf-8")
    if any(pattern.search(registry_text) for pattern in _DYNAMIC_ID_PATTERNS):
        issues.append(
            FailureAtlasIssue(
                code="stale_dynamic_identity",
                subject=registry_path.relative_to(root).as_posix(),
                detail="failure registry must not embed current dynamic identities",
            )
        )
    lower_registry = registry_text.lower()
    for fragment in _PRIVATE_PATTERNS:
        if fragment in lower_registry:
            issues.append(
                FailureAtlasIssue(
                    code="privacy_unsafe_content",
                    subject=registry_path.relative_to(root).as_posix(),
                    detail=f"failure registry contains forbidden fragment: {fragment}",
                )
            )

    status = "passed" if not issues else "blocked"
    report = _base_report(
        status=status,
        entry_count=len(normalized_entries),
        signal_count=len(seen_signals),
        covered_planes=covered_planes,
        covered_categories=covered_categories,
        covered_states=covered_states,
        reference_paths=reference_paths,
        issues=issues,
    )
    report["report_sha256"] = sha256_hex(canonical_json_bytes(report))
    return report


def verify_failure_report(report: dict[str, Any]) -> bool:
    expected = report.get("report_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    payload = dict(report)
    payload["report_sha256"] = None
    return expected == sha256_hex(canonical_json_bytes(payload))
