from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import IntegrityError

PRODUCTION_POINTER_KEY = "channels/production.json"
RUNTIME_REQUIRED_ARTIFACT_KINDS = frozenset({"graph", "graph_v2", "lexical_index", "provenance"})


class ActiveReleaseBindingError(IntegrityError):
    """Fail-closed error while resolving the production release authority chain."""


class ReadOnlyObjectGetter(Protocol):
    def get(self, key: str) -> bytes: ...


@dataclass(frozen=True)
class ActiveReleaseBinding:
    release_id: str
    pointer_key: str
    pointer: dict[str, Any]
    pointer_sha256: str
    production_manifest_key: str
    production_manifest: dict[str, Any]
    production_manifest_sha256: str
    candidate_manifest_key: str
    candidate_manifest: dict[str, Any]
    candidate_manifest_sha256: str
    qdrant_collection: str
    qdrant_point_count: int
    source_commit_sha: str
    admission_sha256: str
    artifact_entries: dict[str, dict[str, Any]]
    identity_sha256: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_value(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_JSON: {label}") from exc
    if not isinstance(value, dict):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_NOT_OBJECT: {label}")
    return value


def _required_string(value: Any, label: str, *, maximum: int = 1000) -> str:
    if not isinstance(value, str):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_STRING: {label}")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_STRING: {label}")
    return text


def _required_sha256(value: Any, label: str) -> str:
    text = _required_string(value, label, maximum=64)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_SHA256: {label}")
    return text


def _required_git_sha(value: Any, label: str) -> str:
    text = _required_string(value, label, maximum=40)
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_GIT_SHA: {label}")
    return text


def _required_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_INVALID_COUNT: {label}")
    return value


def _release_scoped_key(
    value: Any,
    *,
    release_id: str,
    label: str,
    require_promotion: bool = False,
) -> str:
    key = _required_string(value, label, maximum=2000)
    expected_prefix = f"releases/{release_id}/"
    if not key.startswith(expected_prefix):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_PATH_ESCAPE: {label}")
    parts = key.split("/")
    if ".." in parts or "." in parts or "" in parts:
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_PATH_ESCAPE: {label}")
    if require_promotion and not key.startswith(f"releases/{release_id}/promotion/"):
        raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_PROMOTION_PATH_INVALID: {label}")
    return key


def _artifact_entries(manifest: Mapping[str, Any], release_id: str) -> dict[str, dict[str, Any]]:
    raw = manifest.get("artifacts")
    if not isinstance(raw, list):
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_ARTIFACTS_INVALID")
    entries: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_ARTIFACT_INVALID: {index}")
        kind = _required_string(item.get("kind"), f"artifact[{index}].kind", maximum=100)
        if kind in entries:
            raise ActiveReleaseBindingError(f"ACTIVE_RELEASE_ARTIFACT_DUPLICATE: {kind}")
        key = _release_scoped_key(
            item.get("key"),
            release_id=release_id,
            label=f"artifact[{kind}].key",
        )
        digest = _required_sha256(item.get("sha256"), f"artifact[{kind}].sha256")
        entry = dict(item)
        entry["key"] = key
        entry["sha256"] = digest
        entries[kind] = entry
    missing = sorted(RUNTIME_REQUIRED_ARTIFACT_KINDS - set(entries))
    if missing:
        raise ActiveReleaseBindingError(
            "ACTIVE_RELEASE_REQUIRED_ARTIFACT_MISSING: " + ",".join(missing)
        )
    return entries


def load_active_release_binding(
    store: ReadOnlyObjectGetter,
    *,
    pointer_key: str = PRODUCTION_POINTER_KEY,
) -> ActiveReleaseBinding:
    """Resolve the active release only through the production pointer digest chain.

    There is deliberately no fallback to a hard-coded release, latest object, or candidate
    channel. Missing, stale, path-escaping, or digest-mismatched authority fails closed.
    """

    try:
        pointer_bytes = store.get(pointer_key)
    except (FileNotFoundError, KeyError) as exc:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_POINTER_MISSING") from exc
    pointer = _json_object(pointer_bytes, "production pointer")
    pointer_sha256 = _sha256_bytes(pointer_bytes)

    if pointer.get("schema_version") != "1.0" or pointer.get("channel") != "production":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_POINTER_SCHEMA_INVALID")
    if pointer.get("production_authority") is not True:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_POINTER_AUTHORITY_INVALID")

    release_id = _required_string(pointer.get("release_id"), "pointer.release_id", maximum=300)
    production_manifest_key = _release_scoped_key(
        pointer.get("manifest_key"),
        release_id=release_id,
        label="pointer.manifest_key",
        require_promotion=True,
    )
    expected_production_sha = _required_sha256(
        pointer.get("manifest_sha256"), "pointer.manifest_sha256"
    )

    try:
        production_manifest_bytes = store.get(production_manifest_key)
    except (FileNotFoundError, KeyError) as exc:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_MISSING") from exc
    production_manifest_sha256 = _sha256_bytes(production_manifest_bytes)
    if production_manifest_sha256 != expected_production_sha:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_DIGEST_MISMATCH")
    production_manifest = _json_object(production_manifest_bytes, "production manifest")
    if production_manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_SCHEMA_INVALID")
    if production_manifest.get("release_id") != release_id:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_RELEASE_MISMATCH")
    if production_manifest.get("status") != "production":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_STATUS_INVALID")
    authority = production_manifest.get("authority")
    if not isinstance(authority, Mapping) or authority.get("production_pointer_authorized") is not True:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PRODUCTION_MANIFEST_AUTHORITY_INVALID")

    promotion = production_manifest.get("production_promotion")
    if not isinstance(promotion, Mapping):
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PROMOTION_METADATA_MISSING")
    if promotion.get("production_pointer_authorized") is not True:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_PROMOTION_AUTHORITY_INVALID")
    qdrant_collection = _required_string(
        promotion.get("qdrant_candidate_collection"),
        "production_promotion.qdrant_candidate_collection",
        maximum=500,
    )
    candidate_manifest_key = _release_scoped_key(
        promotion.get("source_candidate_manifest_key"),
        release_id=release_id,
        label="production_promotion.source_candidate_manifest_key",
    )
    if candidate_manifest_key != f"releases/{release_id}/manifest.json":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_PATH_INVALID")
    expected_candidate_sha = _required_sha256(
        promotion.get("source_candidate_manifest_sha256"),
        "production_promotion.source_candidate_manifest_sha256",
    )

    try:
        candidate_manifest_bytes = store.get(candidate_manifest_key)
    except (FileNotFoundError, KeyError) as exc:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_MISSING") from exc
    candidate_manifest_sha256 = _sha256_bytes(candidate_manifest_bytes)
    if candidate_manifest_sha256 != expected_candidate_sha:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_DIGEST_MISMATCH")
    candidate_manifest = _json_object(candidate_manifest_bytes, "candidate manifest")
    if candidate_manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_SCHEMA_INVALID")
    if candidate_manifest.get("release_id") != release_id:
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_RELEASE_MISMATCH")
    if candidate_manifest.get("status") != "candidate":
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_CANDIDATE_MANIFEST_STATUS_INVALID")

    production_entries = _artifact_entries(production_manifest, release_id)
    candidate_entries = _artifact_entries(candidate_manifest, release_id)
    for kind in RUNTIME_REQUIRED_ARTIFACT_KINDS:
        if production_entries[kind]["sha256"] != candidate_entries[kind]["sha256"]:
            raise ActiveReleaseBindingError(
                f"ACTIVE_RELEASE_ARTIFACT_FAMILY_MISMATCH: {kind}"
            )
        if production_entries[kind]["key"] != candidate_entries[kind]["key"]:
            raise ActiveReleaseBindingError(
                f"ACTIVE_RELEASE_ARTIFACT_KEY_MISMATCH: {kind}"
            )

    identities = candidate_manifest.get("identities")
    if not isinstance(identities, Mapping):
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_IDENTITIES_MISSING")
    source_commit_sha = _required_git_sha(
        identities.get("source_commit_sha"), "candidate.identities.source_commit_sha"
    )
    admission_sha256 = _required_sha256(
        identities.get("admission_sha256"), "candidate.identities.admission_sha256"
    )
    counts = candidate_manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise ActiveReleaseBindingError("ACTIVE_RELEASE_COUNTS_MISSING")
    qdrant_point_count = _required_positive_int(
        counts.get("semantic_documents"), "candidate.counts.semantic_documents"
    )

    identity = {
        "release_id": release_id,
        "pointer_sha256": pointer_sha256,
        "production_manifest_key": production_manifest_key,
        "production_manifest_sha256": production_manifest_sha256,
        "candidate_manifest_key": candidate_manifest_key,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "qdrant_collection": qdrant_collection,
        "qdrant_point_count": qdrant_point_count,
        "source_commit_sha": source_commit_sha,
        "admission_sha256": admission_sha256,
        "runtime_artifacts": {
            kind: {
                "key": candidate_entries[kind]["key"],
                "sha256": candidate_entries[kind]["sha256"],
            }
            for kind in sorted(RUNTIME_REQUIRED_ARTIFACT_KINDS)
        },
    }

    return ActiveReleaseBinding(
        release_id=release_id,
        pointer_key=pointer_key,
        pointer=pointer,
        pointer_sha256=pointer_sha256,
        production_manifest_key=production_manifest_key,
        production_manifest=production_manifest,
        production_manifest_sha256=production_manifest_sha256,
        candidate_manifest_key=candidate_manifest_key,
        candidate_manifest=candidate_manifest,
        candidate_manifest_sha256=candidate_manifest_sha256,
        qdrant_collection=qdrant_collection,
        qdrant_point_count=qdrant_point_count,
        source_commit_sha=source_commit_sha,
        admission_sha256=admission_sha256,
        artifact_entries=candidate_entries,
        identity_sha256=_sha256_value(identity),
    )
