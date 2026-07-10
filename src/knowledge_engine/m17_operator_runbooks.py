from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "knowledge-engine-operator-runbook/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-operator-runbook-report/v1"
REQUIRED_PHASES = (
    "preflight",
    "intake",
    "synthesis_prepare",
    "synthesis_validate",
    "resolution",
    "human_review",
    "source_package",
    "source_pr",
    "source_validation",
    "candidate_build",
    "candidate_acceptance",
    "promotion_request",
    "production_approval",
    "production_promotion",
    "runtime_verification",
    "ledger_evidence",
    "batch_closeout",
    "final_reconciliation",
)
ALLOWED_MODES = {"inspect", "local_prepare", "human_review", "governed_external_mutation"}
ALLOWED_AUTHORITIES = {
    "none",
    "source_pr",
    "candidate_publish",
    "production_promotion",
    "permanent_ledger_append",
    "batch_closeout",
}
MUTATION_AUTHORITIES = ALLOWED_AUTHORITIES - {"none"}
MUTATION_PHASES = {
    "source_pr",
    "candidate_build",
    "production_promotion",
    "ledger_evidence",
    "batch_closeout",
}
_FORBIDDEN_COMMAND_FRAGMENTS = (
    "authorization:",
    "bearer ",
    "ghp_",
    "github_pat_",
    "aws_access_key_id",
    "aws_secret_access_key",
    "wrangler r2 object put",
    "aws s3 cp",
    "git push --force",
    "git reset --hard",
    "channels/production.json >",
)
_DYNAMIC_ID_PATTERNS = (
    re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"),
    re.compile(r"\b20[0-9]{6}T[0-9]{6}Z-[0-9a-f]{12}\b"),
)


@dataclass(frozen=True)
class RunbookIssue:
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


def load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"runbook registry is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("runbook registry must be a JSON object")
    return payload


def _validate_reference(
    root: Path,
    step_id: str,
    reference: object,
) -> tuple[dict[str, str] | None, list[RunbookIssue]]:
    if not isinstance(reference, dict):
        return None, [
            RunbookIssue("invalid_reference", step_id, "reference must be an object")
        ]
    raw_path = reference.get("path")
    anchor = reference.get("anchor")
    kind = reference.get("kind")
    issues: list[RunbookIssue] = []
    if kind not in {"code", "contract", "documentation", "test", "workflow"}:
        issues.append(
            RunbookIssue("invalid_reference_kind", step_id, "reference kind is invalid")
        )
    path = _safe_relative_path(root, raw_path)
    if path is None:
        issues.append(
            RunbookIssue(
                "unsafe_reference_path",
                step_id,
                "reference path must be safe and repository-relative",
            )
        )
    elif not path.is_file():
        issues.append(
            RunbookIssue("missing_reference_path", step_id, f"missing path: {raw_path}")
        )
    if not isinstance(anchor, str) or not anchor.strip():
        issues.append(
            RunbookIssue("missing_reference_anchor", step_id, "anchor is required")
        )
    elif path is not None and path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append(
                RunbookIssue("reference_unreadable", step_id, f"unreadable path: {raw_path}")
            )
        else:
            if anchor not in text:
                issues.append(
                    RunbookIssue(
                        "missing_reference_anchor",
                        step_id,
                        f"anchor not found in {raw_path}: {anchor}",
                    )
                )
    if issues:
        return None, issues
    return {"anchor": anchor, "kind": kind, "path": raw_path}, []


def _non_empty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _dynamic_identity_issues(path: Path, relative: str) -> list[RunbookIssue]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [RunbookIssue("document_unreadable", relative, "document must be UTF-8")]
    for pattern in _DYNAMIC_ID_PATTERNS:
        if pattern.search(text):
            return [
                RunbookIssue(
                    "stale_dynamic_identity",
                    relative,
                    "owned runbooks must use placeholders, not moving Git or production identities",
                )
            ]
    return []


def validate_runbook_registry(*, root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry_path = registry_path.resolve()
    try:
        registry_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("registry path must be inside repository root") from exc

    registry = load_registry(registry_path)
    issues: list[RunbookIssue] = []
    if registry.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            RunbookIssue(
                "invalid_schema_version",
                "registry",
                f"schema_version must be {SCHEMA_VERSION}",
            )
        )

    canonical_entry_raw = registry.get("canonical_entry")
    canonical_entry = _safe_relative_path(root, canonical_entry_raw)
    if canonical_entry is None or not canonical_entry.is_file():
        issues.append(
            RunbookIssue(
                "missing_canonical_entry",
                "registry",
                "canonical_entry must be an existing repository file",
            )
        )

    owned_documents = registry.get("owned_documents")
    normalized_documents: list[str] = []
    if not isinstance(owned_documents, list) or not owned_documents:
        issues.append(
            RunbookIssue(
                "missing_owned_documents",
                "registry",
                "owned_documents must be a non-empty list",
            )
        )
    else:
        for item in owned_documents:
            path = _safe_relative_path(root, item)
            if path is None or not path.is_file():
                issues.append(
                    RunbookIssue(
                        "missing_owned_document",
                        str(item),
                        "owned document must be a safe existing file",
                    )
                )
                continue
            relative = path.relative_to(root).as_posix()
            normalized_documents.append(relative)
            issues.extend(_dynamic_identity_issues(path, relative))

    if isinstance(canonical_entry_raw, str) and canonical_entry_raw not in normalized_documents:
        issues.append(
            RunbookIssue(
                "canonical_entry_not_owned",
                "registry",
                "canonical_entry must appear in owned_documents",
            )
        )

    if registry.get("required_phases") != list(REQUIRED_PHASES):
        issues.append(
            RunbookIssue(
                "invalid_required_phases",
                "registry",
                "required_phases must equal the canonical lifecycle sequence",
            )
        )

    steps = registry.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append(RunbookIssue("missing_steps", "registry", "steps must be a non-empty list"))
        steps = []

    normalized_steps: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_phases: list[str] = []
    previous_outputs: set[str] = set()
    for index, step in enumerate(steps, 1):
        subject = f"step[{index}]"
        if not isinstance(step, dict):
            issues.append(RunbookIssue("invalid_step", subject, "step must be an object"))
            continue

        step_id = step.get("step_id")
        phase = step.get("phase")
        order = step.get("order")
        mode = step.get("mode")
        authority = step.get("authority")
        command = step.get("command_template")
        if not isinstance(step_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{2,127}", step_id
        ):
            issues.append(
                RunbookIssue("invalid_step_id", subject, "step_id must be stable lower-case")
            )
            step_id = subject
        elif step_id in seen_ids:
            issues.append(RunbookIssue("duplicate_step_id", step_id, "step_id must be unique"))
        seen_ids.add(step_id)

        if order != index:
            issues.append(
                RunbookIssue(
                    "invalid_step_order",
                    step_id,
                    f"order must be contiguous and equal {index}",
                )
            )
        if phase not in REQUIRED_PHASES:
            issues.append(RunbookIssue("invalid_phase", step_id, "phase is not canonical"))
        else:
            seen_phases.append(phase)
        if mode not in ALLOWED_MODES:
            issues.append(RunbookIssue("invalid_mode", step_id, "mode is invalid"))
        if authority not in ALLOWED_AUTHORITIES:
            issues.append(RunbookIssue("invalid_authority", step_id, "authority is invalid"))

        for field in (
            "inputs",
            "produces",
            "evidence",
            "verification",
            "stop_conditions",
            "rollback",
        ):
            if not _non_empty_strings(step.get(field)):
                issues.append(
                    RunbookIssue(
                        f"missing_{field}",
                        step_id,
                        f"{field} must be a non-empty list of strings",
                    )
                )

        title = step.get("title")
        instruction = step.get("instruction")
        if not isinstance(title, str) or len(title.strip()) < 4:
            issues.append(RunbookIssue("invalid_title", step_id, "title is too short"))
        if not isinstance(instruction, str) or len(instruction.strip()) < 20:
            issues.append(
                RunbookIssue("invalid_instruction", step_id, "instruction is too short")
            )

        if command is not None:
            if not isinstance(command, str) or not command.strip():
                issues.append(
                    RunbookIssue("invalid_command_template", step_id, "command must be text or null")
                )
            else:
                lowered = command.lower()
                if any(fragment in lowered for fragment in _FORBIDDEN_COMMAND_FRAGMENTS):
                    issues.append(
                        RunbookIssue(
                            "unsafe_command_template",
                            step_id,
                            "command bypasses governed interfaces or embeds secret-like material",
                        )
                    )

        consumes = step.get("inputs") if isinstance(step.get("inputs"), list) else []
        produces = step.get("produces") if isinstance(step.get("produces"), list) else []
        if index > 1 and previous_outputs and not previous_outputs.intersection(consumes):
            issues.append(
                RunbookIssue(
                    "broken_evidence_chain",
                    step_id,
                    "step must consume at least one output from the previous step",
                )
            )
        previous_outputs = set(produces)

        is_mutation = phase in MUTATION_PHASES
        if is_mutation:
            if mode != "governed_external_mutation":
                issues.append(
                    RunbookIssue(
                        "mutation_mode_mismatch",
                        step_id,
                        "mutation phase must use governed_external_mutation mode",
                    )
                )
            if authority not in MUTATION_AUTHORITIES:
                issues.append(
                    RunbookIssue(
                        "missing_mutation_authority",
                        step_id,
                        "mutation phase requires a bounded authority",
                    )
                )
            for flag in (
                "requires_approval",
                "requires_operation_id",
                "requires_expected_previous",
            ):
                if step.get(flag) is not True:
                    issues.append(
                        RunbookIssue(
                            "missing_mutation_guard",
                            step_id,
                            f"{flag} must be true for mutation steps",
                        )
                    )
        else:
            if authority != "none":
                issues.append(
                    RunbookIssue(
                        "authority_drift",
                        step_id,
                        "non-mutation step cannot claim mutation authority",
                    )
                )
            if mode == "governed_external_mutation":
                issues.append(
                    RunbookIssue(
                        "mode_drift",
                        step_id,
                        "non-mutation phase cannot use mutation mode",
                    )
                )

        reference, reference_issues = _validate_reference(root, step_id, step.get("reference"))
        issues.extend(reference_issues)
        normalized_steps.append(
            {
                "authority": authority,
                "command_template": command,
                "evidence": sorted(step.get("evidence", [])),
                "inputs": step.get("inputs", []),
                "instruction": instruction,
                "mode": mode,
                "order": order,
                "phase": phase,
                "produces": step.get("produces", []),
                "reference": reference,
                "requires_approval": step.get("requires_approval"),
                "requires_expected_previous": step.get("requires_expected_previous"),
                "requires_operation_id": step.get("requires_operation_id"),
                "rollback": sorted(step.get("rollback", [])),
                "step_id": step_id,
                "stop_conditions": sorted(step.get("stop_conditions", [])),
                "title": title,
                "verification": sorted(step.get("verification", [])),
            }
        )

    if seen_phases != list(REQUIRED_PHASES):
        issues.append(
            RunbookIssue(
                "phase_coverage_mismatch",
                "registry",
                "steps must cover every canonical phase exactly once and in order",
            )
        )

    normalized = {
        "canonical_entry": canonical_entry_raw,
        "owned_documents": sorted(normalized_documents),
        "required_phases": list(REQUIRED_PHASES),
        "schema_version": SCHEMA_VERSION,
        "steps": normalized_steps,
    }
    issues = sorted(issues, key=lambda item: (item.code, item.subject, item.detail))
    report_payload = {
        "issue_count": len(issues),
        "issues": [item.to_dict() for item in issues],
        "registry_sha256": sha256_hex(canonical_json_bytes(normalized)),
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "passed" if not issues else "blocked",
        "step_count": len(normalized_steps),
    }
    report_sha256 = sha256_hex(canonical_json_bytes(report_payload))
    return {**report_payload, "artifact_sha256": report_sha256}


def verify_runbook_report(report: dict[str, Any]) -> bool:
    expected = report.get("artifact_sha256")
    if not isinstance(expected, str):
        return False
    payload = dict(report)
    payload.pop("artifact_sha256", None)
    return expected == sha256_hex(canonical_json_bytes(payload))
