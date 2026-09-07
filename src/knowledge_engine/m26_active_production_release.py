from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from .errors import IntegrityError
from .storage import sha256_bytes

PRODUCTION_POINTER_KEY = "channels/production.json"
RUNTIME_REQUIRED_ARTIFACT_KINDS = frozenset(
    {"graph", "graph_v2", "lexical_index", "provenance"}
)


class ActiveProductionReleaseError(IntegrityError):
    """Fail-closed error while resolving the active production release."""


class ReadOnlyObjectGetter(Protocol):
    def get(self, key: str) -> bytes: ...


@dataclass(frozen=True)
class ActiveProductionRelease:
    release_id: str
    production_manifest_key: str
    production_manifest_sha256: str
    candidate_manifest_key: str
    candidate_manifest_sha256: str
    qdrant_collection: str
    source_commit_sha: str
    admission_sha256: str
    semantic_point_count: int
    pointer: dict[str, Any]
    pointer_sha256: str
    production_manifest: dict[str, Any]
    candidate_manifest: dict[str, Any]


def resolve_active_production_release(
    store: ReadOnlyObjectGetter,
    *,
    pointer_key: str = PRODUCTION_POINTER_KEY,
) -> ActiveProductionRelease:
    """Resolve active runtime identity from the immutable production pointer chain.

    The production pointer is the only selector. Historical Python constants,
    environment variables, latest-object guesses, and candidate channels are not
    accepted as active-release authority. Any broken authority or digest link
    fails closed.
    """

    pointer_bytes = _get_required(store, pointer_key, "production pointer")
    pointer = _json_object(pointer_bytes, "production pointer")
    pointer_sha256 = sha256_bytes(pointer_bytes)

    if pointer.get("schema_version") != "1.0":
        raise ActiveProductionReleaseError("production pointer schema mismatch")
    if pointer.get("channel") != "production":
        raise ActiveProductionReleaseError("production pointer channel mismatch")
    if pointer.get("production_authority") is not True:
        raise ActiveProductionReleaseError("production pointer authority missing")

    release_id = _required_string(pointer, "release_id", "production pointer")
    production_manifest_key = _required_string(
        pointer, "manifest_key", "production pointer"
    )
    production_manifest_sha256 = _required_sha256(
        pointer, "manifest_sha256", "production pointer"
    )
    _validate_release_key(production_manifest_key, release_id, "production manifest")
    if not production_manifest_key.startswith(f"releases/{release_id}/promotion/"):
        raise ActiveProductionReleaseError(
            "production manifest key is outside promotion namespace"
        )

    production_manifest_bytes = _get_required(
        store, production_manifest_key, "production manifest"
    )
    if sha256_bytes(production_manifest_bytes) != production_manifest_sha256:
        raise ActiveProductionReleaseError("production manifest digest mismatch")
    production_manifest = _json_object(
        production_manifest_bytes, "production manifest"
    )
    if production_manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise ActiveProductionReleaseError("production manifest schema mismatch")
    if production_manifest.get("release_id") != release_id:
        raise ActiveProductionReleaseError("production manifest release mismatch")
    if production_manifest.get("status") != "production":
        raise ActiveProductionReleaseError("production manifest status mismatch")

    authority = _mapping(production_manifest.get("authority"), "production authority")
    if authority.get("production_pointer_authorized") is not True:
        raise ActiveProductionReleaseError(
            "production manifest is not pointer-authorized"
        )

    promotion = _mapping(
        production_manifest.get("production_promotion"), "production promotion"
    )
    if promotion.get("production_pointer_authorized") is not True:
        raise ActiveProductionReleaseError("production promotion authority mismatch")

    candidate_manifest_key = _required_string(
        promotion, "source_candidate_manifest_key", "production promotion"
    )
    candidate_manifest_sha256 = _required_sha256(
        promotion, "source_candidate_manifest_sha256", "production promotion"
    )
    _validate_release_key(candidate_manifest_key, release_id, "candidate manifest")
    if candidate_manifest_key != f"releases/{release_id}/manifest.json":
        raise ActiveProductionReleaseError("candidate manifest path is not canonical")

    candidate_manifest_bytes = _get_required(
        store, candidate_manifest_key, "candidate manifest"
    )
    if sha256_bytes(candidate_manifest_bytes) != candidate_manifest_sha256:
        raise ActiveProductionReleaseError("candidate manifest digest mismatch")
    candidate_manifest = _json_object(candidate_manifest_bytes, "candidate manifest")
    if candidate_manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise ActiveProductionReleaseError("candidate manifest schema mismatch")
    if candidate_manifest.get("release_id") != release_id:
        raise ActiveProductionReleaseError("candidate manifest release mismatch")
    if candidate_manifest.get("status") != "candidate":
        raise ActiveProductionReleaseError("candidate manifest status mismatch")

    candidate_artifacts = _artifacts_by_kind(candidate_manifest, release_id)
    _require_runtime_artifact_family(candidate_artifacts)
    _validate_production_artifact_family(
        production_manifest=production_manifest,
        candidate_manifest=candidate_manifest,
        release_id=release_id,
    )

    identities = _mapping(candidate_manifest.get("identities"), "candidate identities")
    source_commit_sha = _required_git_sha(
        identities, "source_commit_sha", "candidate identities"
    )
    admission_sha256 = _required_sha256(
        identities, "admission_sha256", "candidate identities"
    )
    counts = _mapping(candidate_manifest.get("counts"), "candidate counts")
    semantic_point_count = _required_positive_int(
        counts, "semantic_documents", "candidate counts"
    )

    qdrant_collection = _required_string(
        promotion, "qdrant_candidate_collection", "production promotion"
    )

    return ActiveProductionRelease(
        release_id=release_id,
        production_manifest_key=production_manifest_key,
        production_manifest_sha256=production_manifest_sha256,
        candidate_manifest_key=candidate_manifest_key,
        candidate_manifest_sha256=candidate_manifest_sha256,
        qdrant_collection=qdrant_collection,
        source_commit_sha=source_commit_sha,
        admission_sha256=admission_sha256,
        semantic_point_count=semantic_point_count,
        pointer=pointer,
        pointer_sha256=pointer_sha256,
        production_manifest=production_manifest,
        candidate_manifest=candidate_manifest,
    )


def _validate_production_artifact_family(
    *,
    production_manifest: Mapping[str, Any],
    candidate_manifest: Mapping[str, Any],
    release_id: str,
) -> None:
    production = _artifacts_by_kind(production_manifest, release_id)
    candidate = _artifacts_by_kind(candidate_manifest, release_id)
    _require_runtime_artifact_family(production)
    _require_runtime_artifact_family(candidate)
    if set(production) != set(candidate):
        raise ActiveProductionReleaseError(
            "production/candidate artifact family mismatch"
        )
    for kind, candidate_entry in candidate.items():
        production_entry = production[kind]
        for field in ("key", "sha256", "bytes"):
            if production_entry.get(field) != candidate_entry.get(field):
                raise ActiveProductionReleaseError(
                    f"production/candidate artifact mismatch: {kind}:{field}"
                )


def _require_runtime_artifact_family(
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    missing = sorted(RUNTIME_REQUIRED_ARTIFACT_KINDS - set(artifacts))
    if missing:
        raise ActiveProductionReleaseError(
            "required runtime artifacts missing: " + ",".join(missing)
        )


def _artifacts_by_kind(
    manifest: Mapping[str, Any], release_id: str
) -> dict[str, Mapping[str, Any]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ActiveProductionReleaseError("release manifest artifacts must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in artifacts:
        entry = _mapping(raw, "release artifact")
        kind = _required_string(entry, "kind", "release artifact")
        if kind in result:
            raise ActiveProductionReleaseError(f"duplicate release artifact kind: {kind}")
        key = _required_string(entry, "key", f"release artifact {kind}")
        _validate_release_key(key, release_id, f"release artifact {kind}")
        _required_sha256(entry, "sha256", f"release artifact {kind}")
        expected_bytes = entry.get("bytes")
        if (
            expected_bytes is not None
            and (
                not isinstance(expected_bytes, int)
                or isinstance(expected_bytes, bool)
                or expected_bytes < 0
            )
        ):
            raise ActiveProductionReleaseError(
                f"release artifact bytes invalid: {kind}"
            )
        result[kind] = entry
    return result


def _validate_release_key(key: str, release_id: str, label: str) -> None:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != key:
        raise ActiveProductionReleaseError(f"{label} key is not canonical")
    expected_prefix = f"releases/{release_id}/"
    if not key.startswith(expected_prefix):
        raise ActiveProductionReleaseError(f"{label} key escapes release namespace")


def _get_required(store: ReadOnlyObjectGetter, key: str, label: str) -> bytes:
    try:
        return store.get(key)
    except (FileNotFoundError, KeyError) as exc:
        raise ActiveProductionReleaseError(f"{label} missing: {key}") from exc


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActiveProductionReleaseError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ActiveProductionReleaseError(f"{label} must be a JSON object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActiveProductionReleaseError(f"{label} must be an object")
    return value


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    observed = value.get(key)
    if not isinstance(observed, str) or not observed:
        raise ActiveProductionReleaseError(f"{label} missing {key}")
    return observed


def _required_git_sha(value: Mapping[str, Any], key: str, label: str) -> str:
    observed = _required_string(value, key, label)
    if len(observed) != 40 or any(ch not in "0123456789abcdef" for ch in observed):
        raise ActiveProductionReleaseError(f"{label} {key} must be lowercase git sha")
    return observed


def _required_sha256(value: Mapping[str, Any], key: str, label: str) -> str:
    observed = _required_string(value, key, label)
    if len(observed) != 64 or any(ch not in "0123456789abcdef" for ch in observed):
        raise ActiveProductionReleaseError(f"{label} {key} must be lowercase sha256")
    return observed


def _required_positive_int(
    value: Mapping[str, Any], key: str, label: str
) -> int:
    observed = value.get(key)
    if isinstance(observed, bool) or not isinstance(observed, int) or observed <= 0:
        raise ActiveProductionReleaseError(f"{label} {key} must be a positive integer")
    return observed
