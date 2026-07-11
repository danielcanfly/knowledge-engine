from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from .storage import ObjectStore, sha256_bytes

TOOL_REGISTRY_SCHEMA = "knowledge-engine-m17-operator-tool-registry/v1"
TOOL_REPORT_SCHEMA = "knowledge-engine-m17-operator-tooling-report/v1"
REQUIRED_COMMANDS = (
    "checklist",
    "doctor",
    "batch-status",
    "production-status",
    "artifact-fetch",
    "evidence-verify",
    "release-compare",
    "ledger-summarize",
    "incident-bundle",
    "handoff-generate",
)
_ALLOWED_REMOTE_OPERATIONS = {"get", "head"}
_ALLOWED_MODES = {"read_only", "local_output"}
_FORBIDDEN_FRAGMENTS = (
    "authorization:",
    "cookie:",
    "secret_value",
    "access_key",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "client_ip",
    "ip_address",
    "hostname",
    "traceback",
    "exception_text",
    "s3://",
    "r2://",
    "file://",
)
_MUTATION_TOKENS = (
    ".put(",
    ".delete(",
    "promote_release(",
    "rollback_release(",
    "publish_release(",
    "update_ref(",
    "append_allowed=true",
    "production_write_allowed=true",
)
_DYNAMIC_IDENTITY_RE = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b|\b20\d{6}T\d{6}Z-[0-9a-f]{8,}\b")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def finalize_report(payload: dict[str, Any], field: str = "report_sha256") -> dict[str, Any]:
    result = dict(payload)
    result[field] = None
    digest = hashlib.sha256(canonical_bytes(result)).hexdigest()
    result[field] = digest
    return result


def verify_report(payload: dict[str, Any], field: str = "report_sha256") -> bool:
    declared = payload.get(field)
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        return False
    candidate = dict(payload)
    candidate[field] = None
    return hashlib.sha256(canonical_bytes(candidate)).hexdigest() == declared


def _load_json(path: Path, *, max_bytes: int = 4_000_000) -> Any:
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file exceeds byte limit: {size}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc


def _privacy_safe(value: Any) -> bool:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).lower()
    return not any(fragment in encoded for fragment in _FORBIDDEN_FRAGMENTS)


def _safe_relative(root: Path, raw: str) -> Path:
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes root: {raw}") from exc
    return candidate


def build_checklist_report(registry_path: Path) -> dict[str, Any]:
    registry = _load_json(registry_path)
    if not isinstance(registry, dict) or not isinstance(registry.get("steps"), list):
        raise ValueError("runbook registry must contain a steps list")
    stages = []
    for index, step in enumerate(registry["steps"], start=1):
        if not isinstance(step, dict):
            raise ValueError("runbook step must be an object")
        phase = step.get("phase")
        stop_conditions = step.get("stop_conditions")
        if not isinstance(phase, str) or not phase:
            raise ValueError("runbook step phase is missing")
        if not isinstance(stop_conditions, list) or not stop_conditions:
            raise ValueError(f"runbook step has no stop conditions: {phase}")
        stages.append(
            {
                "index": index,
                "phase": phase,
                "mode": step.get("mode"),
                "stop_conditions": sorted(str(item) for item in stop_conditions),
            }
        )
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "checklist",
            "status": "passed",
            "stage_count": len(stages),
            "stages": stages,
        }
    )


def build_doctor_report(root: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    source_env = dict(os.environ if env is None else env)
    required_paths = (
        "pyproject.toml",
        "docs/architecture/README.md",
        "docs/operations/README.md",
        "docs/operations/m17/runbook-registry.json",
        "docs/troubleshooting/m17/failure-registry.json",
        "docs/operations/m17/tool-registry.json",
    )
    path_checks = {item: _safe_relative(root, item).is_file() for item in required_paths}
    backend = source_env.get("OBJECT_STORE_BACKEND", "r2").strip().lower() or "r2"
    r2_names = (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
    )
    environment = {
        "OBJECT_STORE_BACKEND": backend,
        "KNOWLEDGE_CHANNEL_present": bool(source_env.get("KNOWLEDGE_CHANNEL")),
        "r2_required_names_present": {name: bool(source_env.get(name)) for name in r2_names},
    }
    issues = []
    if sys.version_info < (3, 11):
        issues.append("python_version_unsupported")
    issues.extend(f"missing_path:{path}" for path, present in path_checks.items() if not present)
    if backend not in {"filesystem", "r2"}:
        issues.append("object_store_backend_invalid")
    if backend == "r2" and not all(environment["r2_required_names_present"].values()):
        issues.append("r2_environment_incomplete")
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "doctor",
            "status": "passed" if not issues else "blocked",
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
            },
            "repository_root_present": root.is_dir(),
            "path_checks": path_checks,
            "environment": environment,
            "issues": sorted(issues),
        }
    )


def build_batch_status_report(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not _privacy_safe(payload):
        raise ValueError("batch evidence is invalid or privacy-unsafe")
    fields = (
        "batch_id",
        "state",
        "engine_sha",
        "source_sha",
        "candidate_release_id",
        "production_release_id",
        "operation_id",
        "approval_state",
        "closeout_state",
    )
    summary = {field: payload.get(field) for field in fields if field in payload}
    required = {"batch_id", "state", "engine_sha", "source_sha"}
    missing = sorted(required - set(summary))
    state = summary.get("state")
    status = "blocked" if missing else ("unknown" if state in {None, "unknown"} else "passed")
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "batch-status",
            "status": status,
            "summary": summary,
            "missing_fields": missing,
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def build_production_status_report(
    store: ObjectStore,
    channel: str,
    *,
    max_artifacts: int = 512,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9._-]{1,64}", channel):
        raise ValueError("invalid channel")
    pointer_key = f"channels/{channel}.json"
    pointer_bytes = store.get(pointer_key)
    if len(pointer_bytes) > 256_000:
        raise ValueError("channel pointer exceeds byte limit")
    try:
        pointer = json.loads(pointer_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("channel pointer is invalid JSON") from exc
    if not isinstance(pointer, dict) or not _privacy_safe(pointer):
        raise ValueError("channel pointer is invalid or privacy-unsafe")
    release_id = pointer.get("release_id")
    manifest_key = pointer.get("manifest_key")
    manifest_sha = pointer.get("manifest_sha256")
    if not all(isinstance(item, str) and item for item in (release_id, manifest_key, manifest_sha)):
        raise ValueError("channel pointer is missing release identity")
    manifest_bytes = store.get(manifest_key)
    actual_manifest_sha = sha256_bytes(manifest_bytes)
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("release manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or not _privacy_safe(manifest):
        raise ValueError("release manifest is invalid or privacy-unsafe")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > max_artifacts:
        raise ValueError("release artifact inventory is invalid")
    artifact_checks = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("release artifact entry is invalid")
        key = item.get("key")
        if not isinstance(key, str) or not key.startswith(f"releases/{release_id}/"):
            raise ValueError("release artifact key is invalid")
        metadata = store.head(key)
        artifact_checks.append(
            {
                "key": key,
                "present": metadata is not None,
                "expected_bytes": item.get("bytes"),
                "observed_bytes": metadata.bytes if metadata else None,
                "expected_sha256": item.get("sha256"),
                "observed_sha256": metadata.sha256 if metadata else None,
            }
        )
    pointer_consistent = (
        actual_manifest_sha == manifest_sha and manifest.get("release_id") == release_id
    )
    artifacts_consistent = all(
        check["present"]
        and check["expected_bytes"] == check["observed_bytes"]
        and check["expected_sha256"] == check["observed_sha256"]
        for check in artifact_checks
    )
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "production-status",
            "status": "passed" if pointer_consistent and artifacts_consistent else "blocked",
            "channel": channel,
            "pointer_sha256": sha256_bytes(pointer_bytes),
            "release_id": release_id,
            "manifest_key": manifest_key,
            "declared_manifest_sha256": manifest_sha,
            "observed_manifest_sha256": actual_manifest_sha,
            "pointer_consistent": pointer_consistent,
            "artifact_count": len(artifact_checks),
            "artifacts_consistent": artifacts_consistent,
            "artifacts": artifact_checks,
        }
    )


def fetch_artifact(
    store: ObjectStore,
    key: str,
    output_dir: Path,
    *,
    expected_sha256: str | None = None,
    max_bytes: int = 32_000_000,
) -> dict[str, Any]:
    if key.startswith("/") or ".." in Path(key).parts:
        raise ValueError("unsafe object key")
    metadata = store.head(key)
    if metadata is None:
        raise ValueError("object is missing")
    if metadata.bytes > max_bytes:
        raise ValueError("object exceeds byte limit")
    data = store.get(key)
    if len(data) != metadata.bytes:
        raise ValueError("object size changed during fetch")
    digest = sha256_bytes(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("object digest does not match expected identity")
    if metadata.sha256 is not None and digest != metadata.sha256:
        raise ValueError("object digest does not match metadata")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(key).name
    if not filename or filename in {".", ".."}:
        raise ValueError("object key has no safe filename")
    output_path = _safe_relative(output_dir, filename)
    output_path.write_bytes(data)
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "artifact-fetch",
            "status": "passed",
            "key": key,
            "output": str(output_path),
            "bytes": len(data),
            "artifact_sha256": digest,
        }
    )


def verify_evidence_file(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not _privacy_safe(payload):
        raise ValueError("evidence is invalid or privacy-unsafe")
    digest_field = next(
        (field for field in ("report_sha256", "artifact_sha256") if field in payload),
        None,
    )
    verified = digest_field is not None and verify_report(payload, digest_field)
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "evidence-verify",
            "status": "passed" if verified else "blocked",
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "declared_digest_field": digest_field,
            "declared_digest_verified": verified,
            "evidence_schema_version": payload.get("schema_version"),
            "evidence_status": payload.get("status"),
        }
    )


def _artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("manifest artifacts must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError("manifest artifact entry is invalid")
        key = item["key"]
        if key in result:
            raise ValueError(f"duplicate manifest artifact: {key}")
        result[key] = item
    return result


def compare_release_manifests(left_path: Path, right_path: Path) -> dict[str, Any]:
    left = _load_json(left_path)
    right = _load_json(right_path)
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("release manifests must be JSON objects")
    if not _privacy_safe(left) or not _privacy_safe(right):
        raise ValueError("release manifest is privacy-unsafe")
    left_artifacts = _artifact_map(left)
    right_artifacts = _artifact_map(right)
    left_keys = set(left_artifacts)
    right_keys = set(right_artifacts)
    changed = sorted(
        key
        for key in left_keys & right_keys
        if {
            "bytes": left_artifacts[key].get("bytes"),
            "sha256": left_artifacts[key].get("sha256"),
            "kind": left_artifacts[key].get("kind"),
        }
        != {
            "bytes": right_artifacts[key].get("bytes"),
            "sha256": right_artifacts[key].get("sha256"),
            "kind": right_artifacts[key].get("kind"),
        }
    )
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "release-compare",
            "status": "passed",
            "left": {
                "release_id": left.get("release_id"),
                "manifest_sha256": hashlib.sha256(left_path.read_bytes()).hexdigest(),
            },
            "right": {
                "release_id": right.get("release_id"),
                "manifest_sha256": hashlib.sha256(right_path.read_bytes()).hexdigest(),
            },
            "added": sorted(right_keys - left_keys),
            "removed": sorted(left_keys - right_keys),
            "changed": changed,
            "identical": not (right_keys - left_keys or left_keys - right_keys or changed),
        }
    )


def summarize_ledger_export(path: Path, *, max_entries: int = 5000) -> dict[str, Any]:
    payload = _load_json(path, max_bytes=8_000_000)
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or len(entries) > max_entries:
        raise ValueError("ledger export entries are invalid")
    allowed = (
        "batch_id",
        "operation_id",
        "release_id",
        "engine_sha",
        "source_sha",
        "manifest_sha256",
        "pointer_sha256",
        "status",
    )
    summaries = []
    for item in entries:
        if not isinstance(item, dict) or not _privacy_safe(item):
            raise ValueError("ledger entry is invalid or privacy-unsafe")
        summaries.append({key: item.get(key) for key in allowed if key in item})
    unique_batches = sorted(
        {str(item["batch_id"]) for item in summaries if item.get("batch_id") is not None}
    )
    unique_releases = sorted(
        {str(item["release_id"]) for item in summaries if item.get("release_id") is not None}
    )
    statuses: dict[str, int] = {}
    for item in summaries:
        status = str(item.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "ledger-summarize",
            "status": "passed",
            "entry_count": len(summaries),
            "batch_ids": unique_batches,
            "release_ids": unique_releases,
            "status_counts": dict(sorted(statuses.items())),
            "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def _component_metadata(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not _privacy_safe(payload):
        raise ValueError(f"component evidence is invalid or privacy-unsafe: {path}")
    digest_field = next(
        (field for field in ("report_sha256", "artifact_sha256") if field in payload),
        None,
    )
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "declared_digest_verified": bool(digest_field and verify_report(payload, digest_field)),
    }


def _write_local_report(payload: dict[str, Any], output: Path) -> dict[str, Any]:
    finalized = finalize_report(payload, "artifact_sha256")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(finalized))
    return finalized


def generate_incident_bundle(
    evidence_paths: Iterable[Path],
    output: Path,
    *,
    incident_id: str,
    failure_id: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{3,96}", incident_id):
        raise ValueError("invalid incident ID")
    if not re.fullmatch(r"[a-z0-9._:-]{3,96}", failure_id):
        raise ValueError("invalid failure ID")
    components = sorted(
        (_component_metadata(path) for path in evidence_paths),
        key=lambda item: item["name"],
    )
    status = "passed" if components and all(
        item["declared_digest_verified"] for item in components
    ) else "blocked"
    return _write_local_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "incident-bundle",
            "status": status,
            "incident_id": incident_id,
            "failure_id": failure_id,
            "component_count": len(components),
            "components": components,
        },
        output,
    )


def generate_handoff(
    component_paths: Iterable[Path],
    output: Path,
    *,
    handoff_id: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{3,96}", handoff_id):
        raise ValueError("invalid handoff ID")
    components = sorted(
        (_component_metadata(path) for path in component_paths),
        key=lambda item: item["name"],
    )
    blocked = [item["name"] for item in components if item["status"] not in {"passed", "healthy"}]
    unverified = [item["name"] for item in components if not item["declared_digest_verified"]]
    status = "passed" if components and not blocked and not unverified else "blocked"
    return _write_local_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "handoff-generate",
            "status": status,
            "handoff_id": handoff_id,
            "component_count": len(components),
            "blocked_components": sorted(blocked),
            "unverified_components": sorted(unverified),
            "components": components,
        },
        output,
    )


def validate_tool_registry(root: Path, registry_path: Path) -> dict[str, Any]:
    root = root.resolve()
    registry = _load_json(registry_path)
    issues: list[dict[str, str]] = []
    covered_commands: set[str] = set()
    reference_paths: set[str] = set()
    if not isinstance(registry, dict):
        issues.append({"code": "registry_invalid", "subject": "registry", "detail": "not object"})
        registry = {}
    if registry.get("schema_version") != TOOL_REGISTRY_SCHEMA:
        issues.append(
            {"code": "schema_mismatch", "subject": "registry", "detail": "unsupported schema"}
        )
    tools = registry.get("tools")
    if not isinstance(tools, list):
        issues.append({"code": "tools_missing", "subject": "registry", "detail": "tools list missing"})
        tools = []
    for item in tools:
        if not isinstance(item, dict):
            issues.append({"code": "tool_invalid", "subject": "tool", "detail": "not object"})
            continue
        command = item.get("command")
        subject = str(command or "unknown")
        if not isinstance(command, str) or not command:
            issues.append({"code": "command_missing", "subject": subject, "detail": "command missing"})
            continue
        if command in covered_commands:
            issues.append({"code": "command_duplicate", "subject": subject, "detail": "duplicate"})
        covered_commands.add(command)
        if item.get("mode") not in _ALLOWED_MODES:
            issues.append({"code": "mode_invalid", "subject": subject, "detail": "invalid mode"})
        operations = item.get("remote_operations")
        if not isinstance(operations, list) or any(op not in _ALLOWED_REMOTE_OPERATIONS for op in operations):
            issues.append(
                {"code": "remote_authority_invalid", "subject": subject, "detail": "non-read operation"}
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
            path = _safe_relative(root, raw_path)
        except ValueError as exc:
            issues.append({"code": "reference_escape", "subject": subject, "detail": str(exc)})
            continue
        reference_paths.add(raw_path)
        if not path.is_file():
            issues.append({"code": "reference_path_missing", "subject": subject, "detail": raw_path})
        else:
            text = path.read_text(encoding="utf-8")
            if anchor not in text:
                issues.append({"code": "reference_anchor_missing", "subject": subject, "detail": anchor})
    if tuple(sorted(covered_commands)) != tuple(sorted(REQUIRED_COMMANDS)):
        issues.append(
            {"code": "command_coverage_mismatch", "subject": "registry", "detail": "required commands differ"}
        )
    for raw_path in registry.get("owned_documents", []):
        try:
            path = _safe_relative(root, str(raw_path))
        except ValueError as exc:
            issues.append({"code": "owned_path_escape", "subject": str(raw_path), "detail": str(exc)})
            continue
        if not path.is_file():
            issues.append({"code": "owned_path_missing", "subject": str(raw_path), "detail": "missing"})
            continue
        text = path.read_text(encoding="utf-8")
        if _DYNAMIC_IDENTITY_RE.search(text):
            issues.append(
                {"code": "stale_dynamic_identity", "subject": str(raw_path), "detail": "identity embedded"}
            )
        if any(fragment in text.lower() for fragment in _FORBIDDEN_FRAGMENTS):
            issues.append(
                {"code": "privacy_unsafe_document", "subject": str(raw_path), "detail": "forbidden fragment"}
            )
    source_path = root / "src/knowledge_engine/m17_operator_tools.py"
    if source_path.is_file():
        source_text = source_path.read_text(encoding="utf-8").lower()
        for token in _MUTATION_TOKENS:
            if token in source_text:
                issues.append(
                    {"code": "mutation_surface_detected", "subject": "operator_tools", "detail": token}
                )
    issues = sorted(issues, key=lambda item: (item["code"], item["subject"], item["detail"]))
    return finalize_report(
        {
            "schema_version": TOOL_REPORT_SCHEMA,
            "tool": "operator-tooling-acceptance",
            "status": "passed" if not issues else "blocked",
            "tool_count": len(tools),
            "covered_commands": sorted(covered_commands),
            "reference_paths": sorted(reference_paths),
            "issue_count": len(issues),
            "issues": issues,
        }
    )
