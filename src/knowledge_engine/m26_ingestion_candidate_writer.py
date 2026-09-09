from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectMetadata, ObjectStore, sha256_bytes

MANIFEST_SCHEMA = "knowledge-engine-release/v1"
RECEIPT_SCHEMA = "m26-ingestion-candidate-write-receipt/v1"
CANDIDATE_CHANNEL = "l3-ingestion-candidate"
REQUIRED_ARTIFACT_KINDS = frozenset(
    {"graph", "graph_v2", "lexical_index", "provenance", "semantic_inputs"}
)
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,199}$")
_SAFE_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ARTIFACT_KIND = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class CandidateWriteError(IntegrityError):
    """Fail-closed error while staging an immutable ingestion successor."""


@dataclass(frozen=True)
class CandidateVectorVerification:
    collection_name: str
    release_id: str
    point_count: int
    section_ids: tuple[str, ...]
    detail: Mapping[str, Any] | None = None


class CandidateVectorMaterializer(Protocol):
    def materialize_and_verify(
        self,
        *,
        collection_name: str,
        release_id: str,
        semantic_documents: Sequence[Mapping[str, Any]],
    ) -> CandidateVectorVerification: ...


@dataclass(frozen=True)
class CandidateReleasePlan:
    release_id: str
    source_commit_sha: str
    source_repository_head_sha: str
    admission_sha256: str
    source_count: int
    qdrant_collection: str
    artifact_bytes: Mapping[str, bytes]
    artifact_keys: Mapping[str, str]
    artifact_sha256: Mapping[str, str]
    lexical_section_ids: tuple[str, ...]
    semantic_section_ids: tuple[str, ...]
    semantic_documents: tuple[Mapping[str, Any], ...]
    manifest_key: str
    manifest_sha256: str
    manifest_bytes: bytes


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def candidate_qdrant_collection(release_id: str) -> str:
    release = _release_id(release_id)
    suffix = re.sub(r"[^a-z0-9_]+", "_", release.casefold()).strip("_")
    collection = f"m26_blog_{suffix}"
    if len(collection) > 255:
        raise CandidateWriteError("candidate Qdrant collection name is too long")
    return collection


def _release_id(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_RELEASE_ID.fullmatch(value):
        raise CandidateWriteError("candidate release_id is malformed")
    return value


def _git_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_GIT_SHA.fullmatch(value):
        raise CandidateWriteError(f"{label} must be a lowercase 40-character git SHA")
    return value


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_SHA256.fullmatch(value):
        raise CandidateWriteError(f"{label} must be a lowercase SHA256")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateWriteError(f"{label} must be a positive integer")
    return value


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateWriteError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise CandidateWriteError(f"{label} must be a JSON object")
    return value


def _documents(data: bytes, label: str) -> list[dict[str, Any]]:
    value = _json_object(data, label)
    documents = value.get("documents")
    if not isinstance(documents, list) or not documents:
        raise CandidateWriteError(f"{label} documents must be a non-empty array")
    if any(not isinstance(item, dict) for item in documents):
        raise CandidateWriteError(f"{label} documents must contain objects")
    return [dict(item) for item in documents]


def _section_ids(
    documents: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> tuple[str, ...]:
    ids: list[str] = []
    for document in documents:
        section_id = document.get("section_id")
        if not isinstance(section_id, str) or not section_id.strip():
            raise CandidateWriteError(f"{label} contains a missing section_id")
        ids.append(section_id)
    if len(ids) != len(set(ids)):
        raise CandidateWriteError(f"{label} contains duplicate section_id values")
    return tuple(sorted(ids))


def build_candidate_release_plan(
    *,
    release_id: str,
    source_commit_sha: str,
    source_repository_head_sha: str,
    admission_sha256: str,
    source_count: int,
    artifact_bytes: Mapping[str, bytes],
    created_at: str,
) -> CandidateReleasePlan:
    release = _release_id(release_id)
    source_sha = _git_sha(source_commit_sha, "source_commit_sha")
    source_head = _git_sha(source_repository_head_sha, "source_repository_head_sha")
    admission = _sha256(admission_sha256, "admission_sha256")
    sources = _positive_int(source_count, "source_count")
    if not isinstance(created_at, str) or not created_at.strip():
        raise CandidateWriteError("created_at is required")

    kinds = set(artifact_bytes)
    missing = sorted(REQUIRED_ARTIFACT_KINDS - kinds)
    if missing:
        raise CandidateWriteError("candidate runtime artifacts are missing: " + ",".join(missing))
    if not kinds or any(not _SAFE_ARTIFACT_KIND.fullmatch(kind) for kind in kinds):
        raise CandidateWriteError("candidate artifact kind is malformed")
    if any(not isinstance(data, bytes) or not data for data in artifact_bytes.values()):
        raise CandidateWriteError("candidate artifact bytes must be non-empty")

    lexical_documents = _documents(
        artifact_bytes["lexical_index"],
        "lexical_index",
    )
    semantic_documents = _documents(
        artifact_bytes["semantic_inputs"],
        "semantic_inputs",
    )
    lexical_ids = _section_ids(lexical_documents, label="lexical_index")
    semantic_ids = _section_ids(semantic_documents, label="semantic_inputs")
    if lexical_ids != semantic_ids:
        raise CandidateWriteError("lexical and semantic section_id sets are not exactly equal")

    collection = candidate_qdrant_collection(release)
    keys = {kind: f"releases/{release}/artifacts/{kind}.json" for kind in sorted(kinds)}
    digests = {kind: sha256_bytes(artifact_bytes[kind]) for kind in sorted(kinds)}
    manifest_artifacts = [
        {
            "kind": kind,
            "key": keys[kind],
            "sha256": digests[kind],
            "bytes": len(artifact_bytes[kind]),
            "content_type": "application/json",
        }
        for kind in sorted(kinds)
    ]
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "release_id": release,
        "status": "candidate",
        "channel": CANDIDATE_CHANNEL,
        "created_at": created_at,
        "identities": {
            "source_commit_sha": source_sha,
            "source_repository_head_sha": source_head,
            "admission_sha256": admission,
        },
        "qdrant_collection": collection,
        "artifacts": manifest_artifacts,
        "counts": {
            "source_documents": sources,
            "lexical_documents": len(lexical_ids),
            "semantic_documents": len(semantic_ids),
        },
        "authority": {
            "candidate_only": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
            "production_pointer_writes": 0,
        },
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_key = f"releases/{release}/manifest.json"
    return CandidateReleasePlan(
        release_id=release,
        source_commit_sha=source_sha,
        source_repository_head_sha=source_head,
        admission_sha256=admission,
        source_count=sources,
        qdrant_collection=collection,
        artifact_bytes=dict(artifact_bytes),
        artifact_keys=keys,
        artifact_sha256=digests,
        lexical_section_ids=lexical_ids,
        semantic_section_ids=semantic_ids,
        semantic_documents=tuple(semantic_documents),
        manifest_key=manifest_key,
        manifest_sha256=sha256_bytes(manifest_bytes),
        manifest_bytes=manifest_bytes,
    )


def _verify_remote_exact(
    store: ObjectStore,
    *,
    key: str,
    expected: bytes,
    digest: str,
) -> ObjectMetadata:
    metadata = store.head(key)
    if metadata is None:
        raise CandidateWriteError(f"candidate object is missing after write: {key}")
    remote = store.get(key)
    if len(remote) != len(expected) or sha256_bytes(remote) != digest:
        raise CandidateWriteError(f"candidate object digest mismatch: {key}")
    return metadata


def _put_immutable_exact(
    store: ObjectStore,
    *,
    key: str,
    data: bytes,
) -> bool:
    digest = sha256_bytes(data)
    current = store.head(key)
    if current is not None:
        _verify_remote_exact(store, key=key, expected=data, digest=digest)
        return False

    created = False
    try:
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
        created = True
    except ReleaseConflictError:
        pass
    _verify_remote_exact(store, key=key, expected=data, digest=digest)
    return created


def _verify_vector_result(
    result: CandidateVectorVerification,
    *,
    plan: CandidateReleasePlan,
) -> None:
    if result.collection_name != plan.qdrant_collection:
        raise CandidateWriteError("candidate Qdrant collection identity mismatch")
    if result.release_id != plan.release_id:
        raise CandidateWriteError("candidate Qdrant release identity mismatch")
    if result.point_count != len(plan.semantic_section_ids):
        raise CandidateWriteError("candidate Qdrant point count mismatch")
    observed = tuple(sorted(result.section_ids))
    if len(observed) != len(set(observed)):
        raise CandidateWriteError("candidate Qdrant readback contains duplicate section_id")
    if observed != plan.semantic_section_ids:
        raise CandidateWriteError(
            "candidate Qdrant section_id set does not match lexical/semantic artifacts"
        )


def stage_candidate_release(
    *,
    store: ObjectStore,
    vector_materializer: CandidateVectorMaterializer,
    plan: CandidateReleasePlan,
) -> dict[str, Any]:
    existing_manifest = store.head(plan.manifest_key)
    if existing_manifest is not None:
        _verify_remote_exact(
            store,
            key=plan.manifest_key,
            expected=plan.manifest_bytes,
            digest=plan.manifest_sha256,
        )

    artifact_created: list[str] = []
    artifact_reused: list[str] = []
    for kind in sorted(plan.artifact_bytes):
        key = plan.artifact_keys[kind]
        created = _put_immutable_exact(
            store,
            key=key,
            data=plan.artifact_bytes[kind],
        )
        (artifact_created if created else artifact_reused).append(kind)

    vector_result = vector_materializer.materialize_and_verify(
        collection_name=plan.qdrant_collection,
        release_id=plan.release_id,
        semantic_documents=plan.semantic_documents,
    )
    _verify_vector_result(vector_result, plan=plan)

    manifest_created = _put_immutable_exact(
        store,
        key=plan.manifest_key,
        data=plan.manifest_bytes,
    )
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "candidate_release_finalized",
        "release_id": plan.release_id,
        "manifest_key": plan.manifest_key,
        "manifest_sha256": plan.manifest_sha256,
        "qdrant_collection": plan.qdrant_collection,
        "source_count": plan.source_count,
        "lexical_document_count": len(plan.lexical_section_ids),
        "semantic_document_count": len(plan.semantic_section_ids),
        "artifacts_created": artifact_created,
        "artifacts_reused_exact": artifact_reused,
        "manifest_created": manifest_created,
        "vector": {
            "point_count": vector_result.point_count,
            "section_id_count": len(vector_result.section_ids),
            "detail": dict(vector_result.detail or {}),
        },
        "authority": {
            "candidate_only": True,
            "production_pointer_writes": 0,
            "public_production_traffic_mutations": 0,
        },
    }


__all__ = [
    "CANDIDATE_CHANNEL",
    "CandidateReleasePlan",
    "CandidateVectorMaterializer",
    "CandidateVectorVerification",
    "CandidateWriteError",
    "build_candidate_release_plan",
    "candidate_qdrant_collection",
    "stage_candidate_release",
]
