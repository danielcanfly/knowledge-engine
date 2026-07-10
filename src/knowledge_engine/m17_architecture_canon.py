from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "knowledge-engine-architecture-canon/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-architecture-canon-report/v1"
ALLOWED_REFERENCE_KINDS = {"code", "contract", "documentation", "evidence", "test", "workflow"}
REQUIRED_PLANES = {"build", "control", "feedback", "runtime"}
REQUIRED_MODELS = {
    "acl_model",
    "documentation_ownership",
    "identity_model",
    "lifecycle_model",
    "mutation_authority",
    "release_model",
    "repository_boundaries",
    "source_of_truth",
    "storage_model",
    "trust_boundaries",
}
_DYNAMIC_ID_PATTERNS = (
    re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"),
    re.compile(r"\b20[0-9]{6}T[0-9]{6}Z-[0-9a-f]{12}\b"),
)


@dataclass(frozen=True)
class ArchitectureIssue:
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
        raise ValueError(f"architecture registry is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("architecture registry must be a JSON object")
    return payload


def _dynamic_id_issues(path: Path, relative: str) -> list[ArchitectureIssue]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [
            ArchitectureIssue(
                code="document_unreadable",
                subject=relative,
                detail="owned architecture document must be readable UTF-8",
            )
        ]

    issues: list[ArchitectureIssue] = []
    for pattern in _DYNAMIC_ID_PATTERNS:
        if pattern.search(text):
            issues.append(
                ArchitectureIssue(
                    code="stale_dynamic_identity",
                    subject=relative,
                    detail=(
                        "architecture canon must not embed current Git, release, "
                        "manifest, or pointer identities"
                    ),
                )
            )
            break
    return issues


def _validate_reference(
    root: Path,
    claim_id: str,
    reference: object,
) -> tuple[dict[str, str] | None, list[ArchitectureIssue]]:
    if not isinstance(reference, dict):
        return None, [
            ArchitectureIssue(
                code="invalid_reference",
                subject=claim_id,
                detail="reference must be an object",
            )
        ]

    kind = reference.get("kind")
    raw_path = reference.get("path")
    anchor = reference.get("anchor")
    issues: list[ArchitectureIssue] = []

    if kind not in ALLOWED_REFERENCE_KINDS:
        issues.append(
            ArchitectureIssue(
                code="invalid_reference_kind",
                subject=claim_id,
                detail=f"reference kind must be one of {sorted(ALLOWED_REFERENCE_KINDS)}",
            )
        )
    path = _safe_relative_path(root, raw_path)
    if path is None:
        issues.append(
            ArchitectureIssue(
                code="unsafe_reference_path",
                subject=claim_id,
                detail="reference path must be a safe non-empty repository-relative path",
            )
        )
    elif not path.is_file():
        issues.append(
            ArchitectureIssue(
                code="missing_reference_path",
                subject=claim_id,
                detail=f"referenced path does not exist: {raw_path}",
            )
        )

    if not isinstance(anchor, str) or not anchor.strip():
        issues.append(
            ArchitectureIssue(
                code="missing_reference_anchor",
                subject=claim_id,
                detail="reference anchor must be a non-empty string",
            )
        )
    elif path is not None and path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append(
                ArchitectureIssue(
                    code="reference_unreadable",
                    subject=claim_id,
                    detail=f"referenced path is not readable UTF-8: {raw_path}",
                )
            )
        else:
            if anchor not in text:
                issues.append(
                    ArchitectureIssue(
                        code="missing_reference_anchor",
                        subject=claim_id,
                        detail=f"anchor not found in {raw_path}: {anchor}",
                    )
                )

    if issues:
        return None, issues
    return {"anchor": anchor, "kind": kind, "path": raw_path}, []


def validate_architecture_registry(
    *,
    root: Path,
    registry_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    registry_path = registry_path.resolve()
    try:
        registry_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("registry path must be inside the repository root") from exc

    registry = load_registry(registry_path)
    issues: list[ArchitectureIssue] = []

    if registry.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            ArchitectureIssue(
                code="invalid_schema_version",
                subject="registry",
                detail=f"schema_version must be {SCHEMA_VERSION}",
            )
        )

    canonical_entry_raw = registry.get("canonical_entry")
    canonical_entry = _safe_relative_path(root, canonical_entry_raw)
    if canonical_entry is None or not canonical_entry.is_file():
        issues.append(
            ArchitectureIssue(
                code="missing_canonical_entry",
                subject="registry",
                detail="canonical_entry must resolve to an existing repository file",
            )
        )

    owned_documents = registry.get("owned_documents")
    normalized_documents: list[str] = []
    if not isinstance(owned_documents, list) or not owned_documents:
        issues.append(
            ArchitectureIssue(
                code="missing_owned_documents",
                subject="registry",
                detail="owned_documents must be a non-empty list",
            )
        )
    else:
        for item in owned_documents:
            path = _safe_relative_path(root, item)
            if path is None or not path.is_file():
                issues.append(
                    ArchitectureIssue(
                        code="missing_owned_document",
                        subject=str(item),
                        detail="owned document must be a safe existing repository file",
                    )
                )
                continue
            relative = path.relative_to(root).as_posix()
            normalized_documents.append(relative)
            issues.extend(_dynamic_id_issues(path, relative))

    if isinstance(canonical_entry_raw, str) and canonical_entry_raw not in normalized_documents:
        issues.append(
            ArchitectureIssue(
                code="canonical_entry_not_owned",
                subject="registry",
                detail="canonical_entry must also appear in owned_documents",
            )
        )

    declared_planes = registry.get("required_planes")
    if declared_planes != sorted(REQUIRED_PLANES):
        issues.append(
            ArchitectureIssue(
                code="invalid_required_planes",
                subject="registry",
                detail=f"required_planes must equal {sorted(REQUIRED_PLANES)}",
            )
        )

    declared_models = registry.get("required_models")
    if declared_models != sorted(REQUIRED_MODELS):
        issues.append(
            ArchitectureIssue(
                code="invalid_required_models",
                subject="registry",
                detail=f"required_models must equal {sorted(REQUIRED_MODELS)}",
            )
        )

    claims = registry.get("claims")
    normalized_claims: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    covered_planes: set[str] = set()
    covered_models: set[str] = set()
    reference_paths: set[str] = set()

    if not isinstance(claims, list) or not claims:
        issues.append(
            ArchitectureIssue(
                code="missing_claims",
                subject="registry",
                detail="claims must be a non-empty list",
            )
        )
        claims = []

    for index, claim in enumerate(claims):
        subject = f"claim[{index}]"
        if not isinstance(claim, dict):
            issues.append(
                ArchitectureIssue(
                    code="invalid_claim",
                    subject=subject,
                    detail="claim must be an object",
                )
            )
            continue

        claim_id = claim.get("claim_id")
        plane = claim.get("plane")
        model = claim.get("model")
        statement = claim.get("statement")
        owner = claim.get("owner")

        if not isinstance(claim_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{2,127}", claim_id
        ):
            issues.append(
                ArchitectureIssue(
                    code="invalid_claim_id",
                    subject=subject,
                    detail="claim_id must be a stable lower-case identifier",
                )
            )
            claim_id = subject
        elif claim_id in seen_ids:
            issues.append(
                ArchitectureIssue(
                    code="duplicate_claim_id",
                    subject=claim_id,
                    detail="claim_id must be unique",
                )
            )
        seen_ids.add(claim_id)

        if plane not in REQUIRED_PLANES:
            issues.append(
                ArchitectureIssue(
                    code="invalid_plane",
                    subject=claim_id,
                    detail=f"plane must be one of {sorted(REQUIRED_PLANES)}",
                )
            )
        else:
            covered_planes.add(plane)

        if model not in REQUIRED_MODELS:
            issues.append(
                ArchitectureIssue(
                    code="invalid_model",
                    subject=claim_id,
                    detail=f"model must be one of {sorted(REQUIRED_MODELS)}",
                )
            )
        else:
            covered_models.add(model)

        if not isinstance(statement, str) or len(statement.strip()) < 20:
            issues.append(
                ArchitectureIssue(
                    code="invalid_statement",
                    subject=claim_id,
                    detail="statement must contain at least 20 non-whitespace characters",
                )
            )
        elif any(pattern.search(statement) for pattern in _DYNAMIC_ID_PATTERNS):
            issues.append(
                ArchitectureIssue(
                    code="stale_dynamic_identity",
                    subject=claim_id,
                    detail="claim statements must not embed dynamic production identities",
                )
            )

        if not isinstance(owner, str) or not owner.strip():
            issues.append(
                ArchitectureIssue(
                    code="missing_owner",
                    subject=claim_id,
                    detail="claim owner is required",
                )
            )

        reference, reference_issues = _validate_reference(root, claim_id, claim.get("reference"))
        issues.extend(reference_issues)
        if reference is not None:
            reference_paths.add(reference["path"])

        normalized_claims.append(
            {
                "claim_id": claim_id,
                "model": model,
                "owner": owner,
                "plane": plane,
                "reference": reference,
                "statement": statement,
            }
        )

    missing_planes = sorted(REQUIRED_PLANES - covered_planes)
    if missing_planes:
        issues.append(
            ArchitectureIssue(
                code="missing_plane_coverage",
                subject="registry",
                detail=f"missing plane coverage: {missing_planes}",
            )
        )
    missing_models = sorted(REQUIRED_MODELS - covered_models)
    if missing_models:
        issues.append(
            ArchitectureIssue(
                code="missing_model_coverage",
                subject="registry",
                detail=f"missing model coverage: {missing_models}",
            )
        )

    normalized_claims.sort(key=lambda item: str(item["claim_id"]))
    issues.sort(key=lambda item: (item.code, item.subject, item.detail))
    registry_sha256 = sha256_hex(canonical_json_bytes(registry))
    status = "passed" if not issues else "failed"
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "canonical_entry": canonical_entry_raw,
        "registry_path": registry_path.relative_to(root).as_posix(),
        "registry_sha256": registry_sha256,
        "counts": {
            "claims": len(normalized_claims),
            "documents": len(set(normalized_documents)),
            "issues": len(issues),
            "reference_paths": len(reference_paths),
        },
        "covered_planes": sorted(covered_planes),
        "covered_models": sorted(covered_models),
        "claims": normalized_claims,
        "issues": [item.to_dict() for item in issues],
        "artifact_sha256": None,
    }
    report["artifact_sha256"] = sha256_hex(canonical_json_bytes(report))
    return report


def verify_report_digest(report: dict[str, Any]) -> bool:
    claimed = report.get("artifact_sha256")
    if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed):
        return False
    payload = dict(report)
    payload["artifact_sha256"] = None
    return claimed == sha256_hex(canonical_json_bytes(payload))
