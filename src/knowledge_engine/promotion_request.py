from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .promotion import PromotionRequest

SCHEMA_VERSION = "production-promotion-request/v1"
REQUEST_ROOT = Path("production_promotions")

REQUIRED_FIELDS = (
    "schema_version",
    "operation_id",
    "candidate_channel",
    "release_id",
    "manifest_sha256",
    "source_repository",
    "source_sha",
    "builder_sha",
    "foundation_sha",
    "expected_previous_release_id",
    "expected_previous_manifest_sha256",
    "reason",
    "actor",
    "post_promote_public_query",
    "expected_public_status",
    "expected_citation_url",
)

OPTIONAL_FIELDS = (
    "post_promote_acl_query",
    "expected_acl_status",
)

GITHUB_ENV_FIELDS = (
    "operation_id",
    "candidate_channel",
    "release_id",
    "manifest_sha256",
    "source_repository",
    "source_sha",
    "builder_sha",
    "foundation_sha",
    "expected_previous_release_id",
    "expected_previous_manifest_sha256",
    "reason",
    "actor",
    "post_promote_public_query",
    "expected_public_status",
    "expected_citation_url",
    "post_promote_acl_query",
    "expected_acl_status",
)


@dataclass(frozen=True)
class PromotionRequestSpec:
    raw: dict[str, Any]
    request: PromotionRequest
    post_promote_public_query: str
    expected_public_status: str
    expected_citation_url: str
    post_promote_acl_query: str | None = None
    expected_acl_status: str | None = None

    def normalized(self) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": self.request.operation_id,
            "candidate_channel": self.request.candidate_channel,
            "release_id": self.request.expected_release_id,
            "manifest_sha256": self.request.expected_manifest_sha256,
            "source_repository": self.request.expected_source_repository,
            "source_sha": self.request.expected_source_sha,
            "builder_sha": self.request.expected_builder_sha,
            "foundation_sha": self.request.expected_foundation_sha,
            "expected_previous_release_id": self.request.expected_previous_release_id,
            "expected_previous_manifest_sha256": (
                self.request.expected_previous_manifest_sha256
            ),
            "control_plane_sha": self.request.control_plane_sha,
            "reason": self.request.reason,
            "actor": self.request.actor,
            "post_promote_public_query": self.post_promote_public_query,
            "expected_public_status": self.expected_public_status,
            "expected_citation_url": self.expected_citation_url,
        }
        if self.post_promote_acl_query is not None:
            payload["post_promote_acl_query"] = self.post_promote_acl_query
        if self.expected_acl_status is not None:
            payload["expected_acl_status"] = self.expected_acl_status
        return payload

    def env(self) -> dict[str, str]:
        normalized = self.normalized()
        return {
            key.upper(): str(normalized[key])
            for key in GITHUB_ENV_FIELDS
            if key in normalized and normalized[key] is not None
        }


def validate_request_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise IntegrityError("request_path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise IntegrityError("request_path must not contain empty, current, or parent parts")
    if path.parent != REQUEST_ROOT:
        raise IntegrityError("request_path must match production_promotions/*.json")
    if path.suffix != ".json":
        raise IntegrityError("request_path must be a JSON file")
    if not path.is_file():
        raise IntegrityError(f"request_path does not exist: {path}")
    return path


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"promotion request is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError("promotion request must be a JSON object")
    return payload


def _require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"promotion request field is required: {field}")
    return value.strip()


def load_promotion_request_spec(
    *,
    request_path: str | Path,
    control_plane_sha: str,
) -> PromotionRequestSpec:
    path = validate_request_path(request_path)
    payload = _read_json_object(path)

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise IntegrityError(
            "promotion request is missing required fields: " + ", ".join(missing)
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise IntegrityError(
            f"promotion request schema_version must be {SCHEMA_VERSION!r}"
        )
    if "control_plane_sha" in payload:
        raise IntegrityError(
            "control_plane_sha must be supplied by the workflow runtime, "
            "not the committed request spec"
        )

    request = PromotionRequest(
        operation_id=_require_string(payload, "operation_id"),
        candidate_channel=_require_string(payload, "candidate_channel"),
        expected_release_id=_require_string(payload, "release_id"),
        expected_manifest_sha256=_require_string(payload, "manifest_sha256"),
        expected_source_repository=_require_string(payload, "source_repository"),
        expected_source_sha=_require_string(payload, "source_sha"),
        expected_builder_sha=_require_string(payload, "builder_sha"),
        expected_foundation_sha=_require_string(payload, "foundation_sha"),
        expected_previous_release_id=_require_string(
            payload,
            "expected_previous_release_id",
        ),
        expected_previous_manifest_sha256=_require_string(
            payload,
            "expected_previous_manifest_sha256",
        ),
        control_plane_sha=control_plane_sha,
        reason=_require_string(payload, "reason"),
        actor=_require_string(payload, "actor"),
    )
    request.validate()

    expected_public_status = _require_string(payload, "expected_public_status")
    if expected_public_status not in {"answered", "not_found"}:
        raise IntegrityError("expected_public_status must be answered or not_found")

    expected_citation_url = _require_string(payload, "expected_citation_url")
    post_promote_public_query = _require_string(payload, "post_promote_public_query")

    post_promote_acl_query = payload.get("post_promote_acl_query")
    if post_promote_acl_query is not None:
        post_promote_acl_query = _require_string(payload, "post_promote_acl_query")

    expected_acl_status = payload.get("expected_acl_status")
    if expected_acl_status is not None:
        expected_acl_status = _require_string(payload, "expected_acl_status")
        if expected_acl_status not in {"answered", "not_found"}:
            raise IntegrityError("expected_acl_status must be answered or not_found")

    return PromotionRequestSpec(
        raw=dict(payload),
        request=request,
        post_promote_public_query=post_promote_public_query,
        expected_public_status=expected_public_status,
        expected_citation_url=expected_citation_url,
        post_promote_acl_query=post_promote_acl_query,
        expected_acl_status=expected_acl_status,
    )


def write_github_env(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value.replace(chr(10), ' ')}\n")


def write_request_evidence(
    *,
    spec: PromotionRequestSpec,
    evidence_dir: Path,
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    request_json = spec.raw
    normalized_json = spec.normalized()
    (evidence_dir / "request.json").write_text(
        json.dumps(request_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "request.normalized.json").write_text(
        json.dumps(normalized_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "valid",
        "request": normalized_json,
        "github_env": spec.env(),
    }
