from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .m13_contracts import RELEASE_ID_RE, SHA256_RE, stable_json_bytes
from .storage import ObjectStore, sha256_bytes

INVENTORY_SCHEMA = "knowledge-engine-m13-release-inventory/v1"
ARTIFACT_TYPES = (
    "audience",
    "citations",
    "claims",
    "concepts",
    "indexes",
    "registry",
)
_ARTIFACT_TYPE_SET = frozenset(ARTIFACT_TYPES)
_KEY_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
_SHA40_RE = re.compile(r"^[a-f0-9]{40}$")


class M13ReleaseInventoryError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


@dataclass(frozen=True)
class ReleaseReference:
    release_id: str
    manifest_key: str
    manifest_sha256: str
    source_repository: str
    source_commit_sha: str
    builder_id: str
    foundation_sha256: str

    def __post_init__(self) -> None:
        if not RELEASE_ID_RE.fullmatch(self.release_id):
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ID_INVALID", "release_id is invalid"
            )
        _validate_key(self.manifest_key, "manifest_key")
        _validate_sha256(self.manifest_sha256, "manifest_sha256")
        if not self.source_repository or "/" not in self.source_repository:
            raise M13ReleaseInventoryError(
                "M13_SOURCE_REPOSITORY_INVALID", "source_repository must be owner/name"
            )
        if not _SHA40_RE.fullmatch(self.source_commit_sha):
            raise M13ReleaseInventoryError(
                "M13_SOURCE_SHA_INVALID", "source_commit_sha is invalid"
            )
        if not self.builder_id.strip():
            raise M13ReleaseInventoryError(
                "M13_BUILDER_ID_INVALID", "builder_id is required"
            )
        _validate_sha256(self.foundation_sha256, "foundation_sha256")

    def to_identity(self) -> dict[str, str]:
        return {
            "release_id": self.release_id,
            "manifest_key": self.manifest_key,
            "manifest_sha256": self.manifest_sha256,
            "source_repository": self.source_repository,
            "source_commit_sha": self.source_commit_sha,
            "builder_id": self.builder_id,
            "foundation_sha256": self.foundation_sha256,
        }


@dataclass(frozen=True)
class ReleaseArtifactReference:
    artifact_type: str
    key: str
    sha256: str
    bytes: int
    schema_version: str

    def __post_init__(self) -> None:
        if self.artifact_type not in _ARTIFACT_TYPE_SET:
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_TYPE_UNKNOWN",
                "artifact_type is not supported",
                artifact_type=self.artifact_type,
            )
        _validate_key(self.key, "artifact key")
        _validate_sha256(self.sha256, "artifact sha256")
        if not isinstance(self.bytes, int) or self.bytes < 0:
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_SIZE_INVALID", "artifact bytes is invalid"
            )
        if not self.schema_version.strip():
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_SCHEMA_INVALID",
                "artifact schema_version is required",
            )

    def to_identity(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "key": self.key,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LoadedRelease:
    reference: ReleaseReference
    manifest: dict[str, Any]
    manifest_bytes: bytes
    artifacts: tuple[ReleaseArtifactReference, ...]
    artifact_values: Mapping[str, dict[str, Any]]
    input_artifact_hashes: tuple[tuple[str, str], ...]

    def artifact(self, artifact_type: str) -> dict[str, Any]:
        try:
            return self.artifact_values[artifact_type]
        except KeyError as exc:
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_MISSING",
                "required release artifact is missing",
                artifact_type=artifact_type,
            ) from exc


def _validate_key(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_KEY_INVALID", f"{field_name} is invalid"
        )


def _validate_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_HASH_INVALID", f"{field_name} is invalid"
        )


def _read_exact(
    store: ObjectStore,
    *,
    key: str,
    expected_sha256: str,
    expected_bytes: int | None,
    label: str,
) -> bytes:
    try:
        data = store.get(key)
    except FileNotFoundError as exc:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_OBJECT_MISSING", f"{label} is missing", key=key
        ) from exc
    observed = sha256_bytes(data)
    if observed != expected_sha256:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_HASH_MISMATCH",
            f"{label} hash mismatch",
            key=key,
            expected=expected_sha256,
            observed=observed,
        )
    if expected_bytes is not None and len(data) != expected_bytes:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_SIZE_MISMATCH",
            f"{label} byte size mismatch",
            key=key,
            expected=expected_bytes,
            observed=len(data),
        )
    return data


def _canonical_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_JSON_INVALID", f"{label} is invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_JSON_INVALID", f"{label} must be an object"
        )
    if data != stable_json_bytes(value):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_JSON_NONCANONICAL",
            f"{label} bytes are not canonical JSON",
        )
    return value


def _artifact_reference(value: Any) -> ReleaseArtifactReference:
    if not isinstance(value, dict):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_INVENTORY_INVALID",
            "artifact inventory entry must be an object",
        )
    try:
        return ReleaseArtifactReference(
            artifact_type=str(value["artifact_type"]),
            key=str(value["key"]),
            sha256=str(value["sha256"]),
            bytes=value["bytes"],
            schema_version=str(value["schema_version"]),
        )
    except KeyError as exc:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_INVENTORY_INVALID", "artifact inventory entry is incomplete"
        ) from exc


def _validate_manifest_identity(
    manifest: Mapping[str, Any], reference: ReleaseReference
) -> None:
    checks = {
        "release_id": reference.release_id,
        "source_repository": reference.source_repository,
        "source_commit_sha": reference.source_commit_sha,
        "builder_id": reference.builder_id,
        "foundation_sha256": reference.foundation_sha256,
    }
    for field_name, expected in checks.items():
        observed = manifest.get(field_name)
        if observed != expected:
            code = {
                "release_id": "M13_RELEASE_ID_MISMATCH",
                "source_repository": "M13_RELEASE_SOURCE_IDENTITY_DRIFT",
                "source_commit_sha": "M13_RELEASE_SOURCE_IDENTITY_DRIFT",
                "builder_id": "M13_RELEASE_BUILDER_IDENTITY_DRIFT",
                "foundation_sha256": "M13_RELEASE_FOUNDATION_IDENTITY_DRIFT",
            }[field_name]
            raise M13ReleaseInventoryError(
                code,
                f"manifest {field_name} does not match the exact reference",
                field=field_name,
                expected=expected,
                observed=observed,
            )


def load_release(
    store: ObjectStore,
    reference: ReleaseReference,
) -> LoadedRelease:
    manifest_bytes = _read_exact(
        store,
        key=reference.manifest_key,
        expected_sha256=reference.manifest_sha256,
        expected_bytes=None,
        label="release manifest",
    )
    manifest = _canonical_object(manifest_bytes, "release manifest")
    if manifest.get("schema_version") != f"{INVENTORY_SCHEMA}/manifest":
        raise M13ReleaseInventoryError(
            "M13_RELEASE_MANIFEST_SCHEMA_INVALID", "release manifest schema is invalid"
        )
    _validate_manifest_identity(manifest, reference)

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_INVENTORY_INVALID", "manifest artifacts must be a list"
        )
    artifacts = tuple(_artifact_reference(item) for item in raw_artifacts)
    identities = [(item.artifact_type, item.key) for item in artifacts]
    if identities != sorted(identities):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_INVENTORY_UNSORTED",
            "artifact inventory must be sorted by artifact_type and key",
        )
    if len(identities) != len(set(identities)):
        raise M13ReleaseInventoryError(
            "M13_RELEASE_INVENTORY_DUPLICATE", "artifact inventory contains duplicates"
        )
    type_counts = {artifact_type: 0 for artifact_type in ARTIFACT_TYPES}
    for artifact in artifacts:
        type_counts[artifact.artifact_type] += 1
    missing = sorted(name for name, count in type_counts.items() if count == 0)
    repeated = sorted(name for name, count in type_counts.items() if count > 1)
    if missing:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_ARTIFACT_MISSING",
            "manifest is missing required artifact types",
            artifact_types=missing,
        )
    if repeated:
        raise M13ReleaseInventoryError(
            "M13_RELEASE_ARTIFACT_DUPLICATE",
            "manifest contains multiple artifacts for a singleton type",
            artifact_types=repeated,
        )

    values: dict[str, dict[str, Any]] = {}
    hashes: list[tuple[str, str]] = [
        (reference.manifest_key, reference.manifest_sha256)
    ]
    for artifact in artifacts:
        data = _read_exact(
            store,
            key=artifact.key,
            expected_sha256=artifact.sha256,
            expected_bytes=artifact.bytes,
            label=f"{artifact.artifact_type} artifact",
        )
        value = _canonical_object(data, f"{artifact.artifact_type} artifact")
        if value.get("schema_version") != artifact.schema_version:
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_SCHEMA_MISMATCH",
                "artifact schema_version does not match inventory",
                artifact_type=artifact.artifact_type,
            )
        if value.get("release_id") != reference.release_id:
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_RELEASE_MISMATCH",
                "artifact release_id does not match manifest",
                artifact_type=artifact.artifact_type,
            )
        entries = value.get("entries")
        if not isinstance(entries, list):
            raise M13ReleaseInventoryError(
                "M13_RELEASE_ARTIFACT_INVALID",
                "artifact entries must be a list",
                artifact_type=artifact.artifact_type,
            )
        values[artifact.artifact_type] = value
        hashes.append((artifact.key, artifact.sha256))

    return LoadedRelease(
        reference=reference,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        artifacts=artifacts,
        artifact_values=values,
        input_artifact_hashes=tuple(sorted(hashes)),
    )
