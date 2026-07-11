from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from .m17_operator_tools import (
    REQUIRED_COMMANDS,
    TOOL_REGISTRY_SCHEMA,
    TOOL_REPORT_SCHEMA,
    finalize_report,
)

_ALLOWED_REMOTE_OPERATIONS = {"get", "head"}
_ALLOWED_MODES = {"read_only", "local_output"}
_MUTATION_CALLS = {
    "put",
    "delete",
    "promote_release",
    "rollback_release",
    "publish_release",
    "update_ref",
    "append_comment",
    "close_batch",
}
_FORBIDDEN_DOCUMENT_FRAGMENTS = (
    "authorization:",
    "cookie:",
    "secret_value",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "traceback",
    "exception_text",
    "s3://",
    "r2://",
    "file://",
)
_DYNAMIC_IDENTITY_RE = re.compile(
    r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b|\b20\d{6}T\d{6}Z-[0-9a-f]{8,}\b"
)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid registry: {path}") from exc


def _resolve(root: Path, raw: str) -> Path:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes root: {raw}") from exc
    return candidate


def _mutation_calls(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"unreadable:{exc.__class__.__name__}"]
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name: str | None = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name in _MUTATION_CALLS:
            calls.append(name)
    return sorted(set(calls))


def validate_operator_tooling(root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry = _load(registry_path)
    issues: list[dict[str, str]] = []
    commands: set[str] = set()
    references: set[str] = set()

    if not isinstance(registry, dict):
        registry = {}
        issues.append({"code": "registry_invalid", "subject": "registry", "detail": "not object"})
    if registry.get("schema_version") != TOOL_REGISTRY_SCHEMA:
        issues.append({"code": "schema_mismatch", "subject": "registry", "detail": "unsupported"})
    tools = registry.get("tools")
    if not isinstance(tools, list):
        tools = []
        issues.append({"code": "tools_missing", "subject": "registry", "detail": "missing list"})

    for item in tools:
        if not isinstance(item, dict):
            issues.append({"code": "tool_invalid", "subject": "tool", "detail": "not object"})
            continue
        command = item.get("command")
        subject = str(command or "unknown")
        if not isinstance(command, str) or not command:
            issues.append({"code": "command_missing", "subject": subject, "detail": "missing"})
            continue
        if command in commands:
            issues.append({"code": "command_duplicate", "subject": subject, "detail": "duplicate"})
        commands.add(command)
        if item.get("mode") not in _ALLOWED_MODES:
            issues.append({"code": "mode_invalid", "subject": subject, "detail": "invalid"})
        operations = item.get("remote_operations")
        if not isinstance(operations, list) or any(
            operation not in _ALLOWED_REMOTE_OPERATIONS for operation in operations
        ):
            issues.append(
                {"code": "remote_authority_invalid", "subject": subject, "detail": "non-read operation"}
            )
        if bool(item.get("local_output")) != (item.get("mode") == "local_output"):
            issues.append(
                {"code": "local_output_mode_mismatch", "subject": subject, "detail": "mode differs"}
            )
        reference = item.get("reference")
        if not isinstance(reference, dict):
            issues.append({"code": "reference_missing", "subject": subject, "detail": "missing"})
            continue
        raw_path = reference.get("path")
        anchor = reference.get("anchor")
        if not isinstance(raw_path, str) or not isinstance(anchor, str):
            issues.append({"code": "reference_invalid", "subject": subject, "detail": "invalid"})
            continue
        try:
            path = _resolve(root, raw_path)
        except ValueError as exc:
            issues.append({"code": "reference_escape", "subject": subject, "detail": str(exc)})
            continue
        references.add(raw_path)
        if not path.is_file():
            issues.append({"code": "reference_path_missing", "subject": subject, "detail": raw_path})
        elif anchor not in path.read_text(encoding="utf-8"):
            issues.append({"code": "reference_anchor_missing", "subject": subject, "detail": anchor})

    if tuple(sorted(commands)) != tuple(sorted(REQUIRED_COMMANDS)):
        issues.append(
            {"code": "command_coverage_mismatch", "subject": "registry", "detail": "required commands differ"}
        )

    for raw_path in registry.get("owned_documents", []):
        subject = str(raw_path)
        try:
            path = _resolve(root, subject)
        except ValueError as exc:
            issues.append({"code": "owned_path_escape", "subject": subject, "detail": str(exc)})
            continue
        if not path.is_file():
            issues.append({"code": "owned_path_missing", "subject": subject, "detail": "missing"})
            continue
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        if _DYNAMIC_IDENTITY_RE.search(text):
            issues.append({"code": "stale_dynamic_identity", "subject": subject, "detail": "embedded"})
        if any(fragment in lower for fragment in _FORBIDDEN_DOCUMENT_FRAGMENTS):
            issues.append({"code": "privacy_unsafe_document", "subject": subject, "detail": "fragment"})

    source_path = root / "src/knowledge_engine/m17_operator_tools.py"
    for call in _mutation_calls(source_path):
        issues.append(
            {"code": "mutation_surface_detected", "subject": "operator_tools", "detail": call}
        )

    issues = sorted(issues, key=lambda item: (item["code"], item["subject"], item["detail"]))
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "operator-tooling-acceptance",
            "status": "passed" if not issues else "blocked",
            "tool_count": len(tools),
            "covered_commands": sorted(commands),
            "reference_paths": sorted(references),
            "issue_count": len(issues),
            "issues": issues,
        }
    )
