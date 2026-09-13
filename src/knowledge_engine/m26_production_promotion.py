from __future__ import annotations

import base64
import copy
import json
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    ActiveProductionRelease,
    resolve_active_production_release,
)
from .storage import ObjectStore, sha256_bytes

SCHEMA_VERSION = "knowledge-engine-m26-production-promotion/v1"
REQUIRED_ARTIFACT_KINDS = frozenset(
    {
        "document_pack_admission",
        "document_source_index",
        "graph",
        "graph_v2",
        "lexical_index",
        "provenance",
        "semantic_inputs",
        "source_documents",
    }
)
REQUIRED_QDRANT_PAYLOAD_INDEXES = frozenset(
    {
        "release_id",
        "source_commit_sha",
        "admission_sha256",
        "candidate_release_eligible",
        "production_authority",
    }
)


@dataclass(frozen=True)
class QdrantQualification:
    collection: str
    status: str
    points_count: int
    filtered_point_count: int
    vector_name: str
    vector_dimension: int
    distance: str
    payload_indexes: tuple[str, ...]
    alias_count: int = 0
    point_ids_sha256: str = ""
    section_ids_sha256: str = ""
    aggregate_identity_sha256: str = ""
    vector_fingerprint_sha256: str = ""


@dataclass(frozen=True)
class ProductionQdrantQualification:
    collection: str
    status: str
    points_count: int
    full_identity_count: int
    vector_name: str
    vector_dimension: int
    distance: str
    aliases: tuple[str, ...] = ()
    point_ids_sha256: str = ""
    section_ids_sha256: str = ""
    aggregate_identity_sha256: str = ""
    vector_fingerprint_sha256: str = ""


@dataclass(frozen=True)
class PredecessorQualification:
    release_id: str
    production_manifest_key: str
    production_manifest_sha256: str
    candidate_manifest_key: str
    candidate_manifest_sha256: str
    source_commit_sha: str
    admission_sha256: str
    semantic_point_count: int
    artifact_count: int
    artifact_family: tuple[str, ...]
    qdrant: ProductionQdrantQualification


@dataclass(frozen=True)
class CandidateQualification:
    release_id: str
    manifest_key: str
    manifest_sha256: str
    artifact_count: int
    artifact_family: tuple[str, ...]
    source_commit_sha: str
    admission_sha256: str
    semantic_point_count: int
    qdrant: QdrantQualification


@dataclass(frozen=True)
class FrozenPointer:
    raw: bytes
    sha256: str
    etag: str
    release_id: str
    manifest_key: str
    manifest_sha256: str


@dataclass(frozen=True)
class PromotionPlan:
    candidate: CandidateQualification
    predecessor: FrozenPointer
    predecessor_qualification: PredecessorQualification
    production_manifest_key: str
    production_manifest_bytes: bytes
    production_manifest_sha256: str
    target_pointer_bytes: bytes
    target_pointer_sha256: str
    promoted_at: str
    owner_authorization: str


@dataclass(frozen=True)
class RollbackPlan:
    expected_promoted: FrozenPointer
    predecessor: FrozenPointer
    predecessor_qualification: PredecessorQualification


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def build_promotion_plan(
    *,
    store: ObjectStore,
    candidate_manifest_key: str,
    candidate_manifest_sha256: str,
    expected_predecessor_pointer_sha256: str,
    promoted_at: str,
    owner_authorization: str,
    qdrant: QdrantQualification,
    predecessor_qdrant: ProductionQdrantQualification,
) -> PromotionPlan:
    """Build an exact, deterministic A->B plan without mutating the store."""

    predecessor = _freeze_pointer(store)
    if predecessor.sha256 != expected_predecessor_pointer_sha256:
        raise IntegrityError("M26-PROMOTE-001 predecessor pointer digest drift")
    active = resolve_active_production_release(store)
    _match_active_pointer(active, predecessor, "predecessor")
    predecessor_qualification = _qualify_predecessor(
        store, active=active, qdrant=predecessor_qdrant
    )

    candidate_manifest, candidate = _qualify_candidate(
        store=store,
        manifest_key=candidate_manifest_key,
        expected_manifest_sha256=candidate_manifest_sha256,
        qdrant=qdrant,
    )
    release_id = candidate.release_id
    production_manifest_key = (
        f"releases/{release_id}/promotion/"
        f"m26-production-manifest-{candidate.manifest_sha256[:16]}.json"
    )
    production_manifest = _build_production_manifest(
        candidate_manifest,
        candidate=candidate,
        predecessor=predecessor_qualification,
        promoted_at=promoted_at,
        owner_authorization=owner_authorization,
    )
    production_manifest_bytes = pretty_json_bytes(production_manifest)
    production_manifest_sha256 = sha256_bytes(production_manifest_bytes)
    target_pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": release_id,
        "manifest_key": production_manifest_key,
        "manifest_sha256": production_manifest_sha256,
        "promoted_at": promoted_at,
        "promotion_schema_version": SCHEMA_VERSION,
        "source_candidate_manifest_key": candidate.manifest_key,
        "source_candidate_manifest_sha256": candidate.manifest_sha256,
        "production_authority": True,
        "public_production_traffic_mutated": False,
    }
    target_pointer_bytes = pretty_json_bytes(target_pointer)
    return PromotionPlan(
        candidate=candidate,
        predecessor=predecessor,
        predecessor_qualification=predecessor_qualification,
        production_manifest_key=production_manifest_key,
        production_manifest_bytes=production_manifest_bytes,
        production_manifest_sha256=production_manifest_sha256,
        target_pointer_bytes=target_pointer_bytes,
        target_pointer_sha256=sha256_bytes(target_pointer_bytes),
        promoted_at=promoted_at,
        owner_authorization=owner_authorization,
    )


def build_rollback_plan(plan: PromotionPlan) -> RollbackPlan:
    target = _pointer_from_bytes(plan.target_pointer_bytes, etag="")
    if target.sha256 != plan.target_pointer_sha256:
        raise IntegrityError("M26-ROLLBACK-001 promoted pointer digest drift")
    return RollbackPlan(
        expected_promoted=target,
        predecessor=plan.predecessor,
        predecessor_qualification=plan.predecessor_qualification,
    )


def execute_promotion(
    *,
    store: ObjectStore,
    plan: PromotionPlan,
    revalidate_qdrant: Callable[[], QdrantQualification] | None = None,
    revalidate_predecessor_qdrant: Callable[[], ProductionQdrantQualification] | None = None,
) -> dict[str, Any]:
    """Execute a previously frozen plan. This is not called by BP-4 live qualification."""

    current = _freeze_pointer(store)
    if current.raw == plan.target_pointer_bytes:
        _verify_immutable(store, plan.production_manifest_key, plan.production_manifest_bytes)
        active = resolve_active_production_release(store)
        if active.release_id != plan.candidate.release_id:
            raise IntegrityError("M26-PROMOTE-002 idempotent target resolver mismatch")
        _, observed_candidate = _qualify_candidate(
            store=store,
            manifest_key=plan.candidate.manifest_key,
            expected_manifest_sha256=plan.candidate.manifest_sha256,
            qdrant=(revalidate_qdrant() if revalidate_qdrant else plan.candidate.qdrant),
        )
        if observed_candidate != plan.candidate:
            raise IntegrityError("M26-PROMOTE-003 idempotent candidate health drift")
        predecessor_store = _PointerOverlay(store, plan.predecessor.raw)
        predecessor_active = resolve_active_production_release(predecessor_store)
        _match_active_pointer(predecessor_active, plan.predecessor, "idempotent predecessor")
        predecessor_artifacts = _validate_active_artifacts(store, predecessor_active)
        observed_predecessor_qdrant = (
            revalidate_predecessor_qdrant()
            if revalidate_predecessor_qdrant
            else plan.predecessor_qualification.qdrant
        )
        _validate_production_qdrant(observed_predecessor_qdrant, predecessor_active)
        if (
            _predecessor_from_active(
                predecessor_active,
                artifact_family=predecessor_artifacts,
                qdrant=observed_predecessor_qdrant,
            )
            != plan.predecessor_qualification
        ):
            raise IntegrityError("M26-PROMOTE-004 idempotent predecessor health drift")
        return _promotion_result(plan, status="already_promoted", mutated=False)

    _require_same_pointer(current, plan.predecessor, "promotion predecessor")
    candidate_manifest, observed_candidate = _qualify_candidate(
        store=store,
        manifest_key=plan.candidate.manifest_key,
        expected_manifest_sha256=plan.candidate.manifest_sha256,
        qdrant=(revalidate_qdrant() if revalidate_qdrant else plan.candidate.qdrant),
    )
    del candidate_manifest
    if observed_candidate != plan.candidate:
        raise IntegrityError("M26-PROMOTE-003 candidate qualification drift")

    predecessor_store = _PointerOverlay(store, plan.predecessor.raw)
    predecessor_active = resolve_active_production_release(predecessor_store)
    _match_active_pointer(predecessor_active, plan.predecessor, "promotion predecessor")
    predecessor_artifacts = _validate_active_artifacts(store, predecessor_active)
    observed_predecessor_qdrant = (
        revalidate_predecessor_qdrant()
        if revalidate_predecessor_qdrant
        else plan.predecessor_qualification.qdrant
    )
    _validate_production_qdrant(observed_predecessor_qdrant, predecessor_active)
    if (
        _predecessor_from_active(
            predecessor_active,
            artifact_family=predecessor_artifacts,
            qdrant=observed_predecessor_qdrant,
        )
        != plan.predecessor_qualification
    ):
        raise IntegrityError("M26-PROMOTE-007 predecessor qualification drift")

    _put_immutable(store, plan.production_manifest_key, plan.production_manifest_bytes)
    store.put(
        PRODUCTION_POINTER_KEY,
        plan.target_pointer_bytes,
        content_type="application/json",
        sha256=plan.target_pointer_sha256,
        expected_etag=plan.predecessor.etag,
    )
    if store.get(PRODUCTION_POINTER_KEY) != plan.target_pointer_bytes:
        raise IntegrityError("M26-PROMOTE-004 pointer readback mismatch")
    active = resolve_active_production_release(store)
    if (
        active.release_id != plan.candidate.release_id
        or active.production_manifest_sha256 != plan.production_manifest_sha256
    ):
        raise IntegrityError("M26-PROMOTE-005 active resolver target mismatch")
    return _promotion_result(plan, status="production_pointer_promoted", mutated=True)


def execute_rollback(
    *,
    store: ObjectStore,
    plan: RollbackPlan,
    verify_predecessor_qdrant: Callable[[ActiveProductionRelease], ProductionQdrantQualification],
) -> dict[str, Any]:
    """Execute B->A only; A retries are idempotent and any C fails before write."""

    current = _freeze_pointer(store)
    if current.raw == plan.predecessor.raw:
        active = resolve_active_production_release(store)
        _match_active_pointer(active, plan.predecessor, "restored predecessor")
        predecessor_artifacts = _validate_active_artifacts(store, active)
        observed_qdrant = verify_predecessor_qdrant(active)
        _validate_production_qdrant(observed_qdrant, active)
        if (
            _predecessor_from_active(
                active, artifact_family=predecessor_artifacts, qdrant=observed_qdrant
            )
            != plan.predecessor_qualification
        ):
            raise IntegrityError("M26-ROLLBACK-004 idempotent predecessor health drift")
        return _rollback_result(plan, status="already_rolled_back", mutated=False)
    _require_same_pointer(
        current,
        plan.expected_promoted,
        "rollback promoted target",
        require_etag=False,
    )

    active_target = resolve_active_production_release(store)
    _match_active_pointer(active_target, plan.expected_promoted, "promoted target")
    predecessor_store = _PointerOverlay(store, plan.predecessor.raw)
    predecessor_active = resolve_active_production_release(predecessor_store)
    _match_active_pointer(predecessor_active, plan.predecessor, "rollback predecessor")
    predecessor_artifacts = _validate_active_artifacts(store, predecessor_active)
    observed_qdrant = verify_predecessor_qdrant(predecessor_active)
    _validate_production_qdrant(observed_qdrant, predecessor_active)
    observed_predecessor = _predecessor_from_active(
        predecessor_active,
        artifact_family=predecessor_artifacts,
        qdrant=observed_qdrant,
    )
    if observed_predecessor != plan.predecessor_qualification:
        raise IntegrityError("M26-ROLLBACK-003 predecessor qualification drift")

    store.put(
        PRODUCTION_POINTER_KEY,
        plan.predecessor.raw,
        content_type="application/json",
        sha256=plan.predecessor.sha256,
        expected_etag=current.etag,
    )
    if store.get(PRODUCTION_POINTER_KEY) != plan.predecessor.raw:
        raise IntegrityError("M26-ROLLBACK-002 pointer readback mismatch")
    restored = resolve_active_production_release(store)
    _match_active_pointer(restored, plan.predecessor, "restored predecessor")
    return _rollback_result(plan, status="production_pointer_restored", mutated=True)


def promotion_plan_receipt(plan: PromotionPlan) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "deterministic_dry_run",
        "writes_performed": 0,
        "candidate": _jsonable_dataclass(plan.candidate),
        "predecessor": _pointer_receipt(plan.predecessor),
        "predecessor_qualification": _jsonable_dataclass(plan.predecessor_qualification),
        "proposed_production_manifest": {
            "key": plan.production_manifest_key,
            "sha256": plan.production_manifest_sha256,
            "bytes": len(plan.production_manifest_bytes),
        },
        "proposed_production_pointer": {
            "key": PRODUCTION_POINTER_KEY,
            "sha256": plan.target_pointer_sha256,
            "bytes": len(plan.target_pointer_bytes),
        },
        "ordered_future_steps": [
            "revalidate exact predecessor pointer bytes/hash/etag and resolver chain",
            "revalidate exact candidate manifest/artifacts and Qdrant collection",
            "create-or-verify immutable production manifest",
            "CAS production pointer from frozen predecessor to exact target",
            "read back exact target and resolve active release",
        ],
    }


def rollback_plan_receipt(plan: RollbackPlan) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "deterministic_dry_run",
        "writes_performed": 0,
        "expected_current_promoted_pointer": _pointer_receipt(plan.expected_promoted),
        "exact_predecessor_pointer": _pointer_receipt(plan.predecessor),
        "predecessor_qualification": _jsonable_dataclass(plan.predecessor_qualification),
        "ordered_future_steps": [
            "require current pointer bytes/hash/identity to equal expected promoted target",
            "resolve expected promoted target chain",
            "resolve frozen predecessor chain and revalidate predecessor Qdrant",
            "CAS production pointer from expected promoted target to exact predecessor bytes",
            "read back exact predecessor and resolve active release",
        ],
    }


def promotion_plan_to_payload(plan: PromotionPlan) -> dict[str, Any]:
    """Serialize every byte and identity needed for exact restart-safe replay."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "durable_exact_promotion_plan",
        "candidate": _jsonable_dataclass(plan.candidate),
        "predecessor": {
            **_pointer_receipt(plan.predecessor),
            "raw_base64": base64.b64encode(plan.predecessor.raw).decode("ascii"),
        },
        "predecessor_qualification": _jsonable_dataclass(plan.predecessor_qualification),
        "production_manifest_key": plan.production_manifest_key,
        "production_manifest_base64": base64.b64encode(plan.production_manifest_bytes).decode(
            "ascii"
        ),
        "production_manifest_sha256": plan.production_manifest_sha256,
        "target_pointer_base64": base64.b64encode(plan.target_pointer_bytes).decode("ascii"),
        "target_pointer_sha256": plan.target_pointer_sha256,
        "promoted_at": plan.promoted_at,
        "owner_authorization": plan.owner_authorization,
    }


def promotion_plan_from_payload(value: Mapping[str, Any]) -> PromotionPlan:
    """Restore a durable plan without consulting latest-candidate state."""

    payload = _mapping(value, "durable promotion plan")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != "durable_exact_promotion_plan"
    ):
        raise IntegrityError("M26-PROMOTE-008 durable plan schema mismatch")

    candidate_raw = _mapping(payload.get("candidate"), "durable candidate")
    candidate_qdrant_raw = _mapping(candidate_raw.get("qdrant"), "durable candidate Qdrant")
    candidate = CandidateQualification(
        release_id=_required_string(candidate_raw, "release_id", "durable candidate"),
        manifest_key=_required_string(candidate_raw, "manifest_key", "durable candidate"),
        manifest_sha256=_hex(identity_value=candidate_raw.get("manifest_sha256"), length=64),
        artifact_count=_positive_int(
            candidate_raw.get("artifact_count"), "durable candidate artifact_count"
        ),
        artifact_family=_string_tuple(
            candidate_raw.get("artifact_family"), "durable candidate artifact_family"
        ),
        source_commit_sha=_hex(identity_value=candidate_raw.get("source_commit_sha"), length=40),
        admission_sha256=_hex(identity_value=candidate_raw.get("admission_sha256"), length=64),
        semantic_point_count=_positive_int(
            candidate_raw.get("semantic_point_count"),
            "durable candidate semantic_point_count",
        ),
        qdrant=_candidate_qdrant_from_payload(candidate_qdrant_raw),
    )

    predecessor_raw = _mapping(payload.get("predecessor"), "durable predecessor")
    predecessor_bytes = _base64_bytes(
        predecessor_raw.get("raw_base64"), "durable predecessor raw bytes"
    )
    predecessor = _pointer_from_bytes(
        predecessor_bytes,
        _required_string(predecessor_raw, "etag", "durable predecessor"),
    )
    if predecessor.sha256 != _hex(identity_value=predecessor_raw.get("sha256"), length=64):
        raise IntegrityError("M26-PROMOTE-009 durable predecessor digest mismatch")

    predecessor_qualification_raw = _mapping(
        payload.get("predecessor_qualification"), "durable predecessor qualification"
    )
    predecessor_qdrant_raw = _mapping(
        predecessor_qualification_raw.get("qdrant"), "durable predecessor Qdrant"
    )
    predecessor_qualification = PredecessorQualification(
        release_id=_required_string(
            predecessor_qualification_raw,
            "release_id",
            "durable predecessor qualification",
        ),
        production_manifest_key=_required_string(
            predecessor_qualification_raw,
            "production_manifest_key",
            "durable predecessor qualification",
        ),
        production_manifest_sha256=_hex(
            identity_value=predecessor_qualification_raw.get("production_manifest_sha256"),
            length=64,
        ),
        candidate_manifest_key=_required_string(
            predecessor_qualification_raw,
            "candidate_manifest_key",
            "durable predecessor qualification",
        ),
        candidate_manifest_sha256=_hex(
            identity_value=predecessor_qualification_raw.get("candidate_manifest_sha256"),
            length=64,
        ),
        source_commit_sha=_hex(
            identity_value=predecessor_qualification_raw.get("source_commit_sha"),
            length=40,
        ),
        admission_sha256=_hex(
            identity_value=predecessor_qualification_raw.get("admission_sha256"),
            length=64,
        ),
        semantic_point_count=_positive_int(
            predecessor_qualification_raw.get("semantic_point_count"),
            "durable predecessor semantic_point_count",
        ),
        artifact_count=_positive_int(
            predecessor_qualification_raw.get("artifact_count"),
            "durable predecessor artifact_count",
        ),
        artifact_family=_string_tuple(
            predecessor_qualification_raw.get("artifact_family"),
            "durable predecessor artifact_family",
        ),
        qdrant=_production_qdrant_from_payload(predecessor_qdrant_raw),
    )
    if predecessor_qualification.release_id != predecessor.release_id:
        raise IntegrityError("M26-PROMOTE-010 durable predecessor identity mismatch")

    production_manifest_bytes = _base64_bytes(
        payload.get("production_manifest_base64"), "durable production manifest"
    )
    production_manifest_sha256 = _hex(
        identity_value=payload.get("production_manifest_sha256"), length=64
    )
    if sha256_bytes(production_manifest_bytes) != production_manifest_sha256:
        raise IntegrityError("M26-PROMOTE-011 durable production manifest digest mismatch")
    target_pointer_bytes = _base64_bytes(
        payload.get("target_pointer_base64"), "durable target pointer"
    )
    target_pointer_sha256 = _hex(identity_value=payload.get("target_pointer_sha256"), length=64)
    if sha256_bytes(target_pointer_bytes) != target_pointer_sha256:
        raise IntegrityError("M26-PROMOTE-012 durable target pointer digest mismatch")
    target = _pointer_from_bytes(target_pointer_bytes, etag="")
    production_manifest_key = _required_string(
        payload, "production_manifest_key", "durable promotion plan"
    )
    if (
        target.release_id != candidate.release_id
        or target.manifest_key != production_manifest_key
        or target.manifest_sha256 != production_manifest_sha256
    ):
        raise IntegrityError("M26-PROMOTE-013 durable target pointer identity mismatch")

    return PromotionPlan(
        candidate=candidate,
        predecessor=predecessor,
        predecessor_qualification=predecessor_qualification,
        production_manifest_key=production_manifest_key,
        production_manifest_bytes=production_manifest_bytes,
        production_manifest_sha256=production_manifest_sha256,
        target_pointer_bytes=target_pointer_bytes,
        target_pointer_sha256=target_pointer_sha256,
        promoted_at=_required_string(payload, "promoted_at", "durable promotion plan"),
        owner_authorization=_required_string(
            payload, "owner_authorization", "durable promotion plan"
        ),
    )


def _qualify_candidate(
    *,
    store: ObjectStore,
    manifest_key: str,
    expected_manifest_sha256: str,
    qdrant: QdrantQualification,
) -> tuple[dict[str, Any], CandidateQualification]:
    manifest_bytes = store.get(manifest_key)
    if sha256_bytes(manifest_bytes) != expected_manifest_sha256:
        raise IntegrityError("M26-CANDIDATE-001 manifest digest mismatch")
    manifest = _json_object(manifest_bytes, "candidate manifest")
    release_id = _required_string(manifest, "release_id", "candidate manifest")
    if manifest_key != f"releases/{release_id}/manifest.json":
        raise IntegrityError("M26-CANDIDATE-002 manifest key is not canonical")
    if manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise IntegrityError("M26-CANDIDATE-003 schema mismatch")
    if manifest.get("status") != "candidate":
        raise IntegrityError("M26-CANDIDATE-004 status mismatch")
    authority = _mapping(manifest.get("authority"), "candidate authority")
    required_authority = {
        "source_admitted": True,
        "candidate_release_authorized": True,
        "semantic_serving_authorized": True,
        "production_pointer_authorized": False,
        "public_production_traffic_authorized": False,
    }
    for key, expected in required_authority.items():
        if authority.get(key) is not expected:
            raise IntegrityError(f"M26-CANDIDATE-005 authority mismatch: {key}")

    identities = _mapping(manifest.get("identities"), "candidate identities")
    source_commit_sha = _hex(identity_value=identities.get("source_commit_sha"), length=40)
    admission_sha256 = _hex(identity_value=identities.get("admission_sha256"), length=64)
    _hex(identity_value=identities.get("engine_commit_sha"), length=40)
    counts = _mapping(manifest.get("counts"), "candidate counts")
    semantic_count = _positive_int(counts.get("semantic_documents"), "semantic_documents")
    lexical_count = _positive_int(counts.get("lexical_documents"), "lexical_documents")
    if lexical_count != semantic_count:
        raise IntegrityError("M26-CANDIDATE-006 lexical/semantic count mismatch")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise IntegrityError("M26-CANDIDATE-007 artifacts missing")
    kinds: set[str] = set()
    for raw in artifacts:
        entry = _mapping(raw, "candidate artifact")
        kind = _required_string(entry, "kind", "candidate artifact")
        if kind in kinds:
            raise IntegrityError(f"M26-CANDIDATE-008 duplicate artifact kind: {kind}")
        kinds.add(kind)
        key = _required_string(entry, "key", f"artifact {kind}")
        _release_key(key, release_id, f"artifact {kind}")
        digest = _hex(identity_value=entry.get("sha256"), length=64)
        expected_bytes = entry.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise IntegrityError(f"M26-CANDIDATE-009 invalid artifact size: {kind}")
        data = store.get(key)
        if len(data) != expected_bytes or sha256_bytes(data) != digest:
            raise IntegrityError(f"M26-CANDIDATE-010 artifact integrity mismatch: {kind}")
    missing = sorted(REQUIRED_ARTIFACT_KINDS - kinds)
    if missing:
        raise IntegrityError("M26-CANDIDATE-011 required artifacts missing: " + ",".join(missing))

    collection = _required_string(manifest, "qdrant_collection", "candidate manifest")
    _validate_qdrant(
        qdrant,
        expected_collection=collection,
        expected_points=semantic_count,
    )
    return manifest, CandidateQualification(
        release_id=release_id,
        manifest_key=manifest_key,
        manifest_sha256=expected_manifest_sha256,
        artifact_count=len(kinds),
        artifact_family=tuple(sorted(kinds)),
        source_commit_sha=source_commit_sha,
        admission_sha256=admission_sha256,
        semantic_point_count=semantic_count,
        qdrant=qdrant,
    )


def _qualify_predecessor(
    store: ObjectStore,
    *,
    active: ActiveProductionRelease,
    qdrant: ProductionQdrantQualification,
) -> PredecessorQualification:
    artifacts = _validate_active_artifacts(store, active)
    _validate_production_qdrant(qdrant, active)
    return _predecessor_from_active(active, artifact_family=artifacts, qdrant=qdrant)


def _predecessor_from_active(
    active: ActiveProductionRelease,
    *,
    artifact_family: tuple[str, ...],
    qdrant: ProductionQdrantQualification,
) -> PredecessorQualification:
    return PredecessorQualification(
        release_id=active.release_id,
        production_manifest_key=active.production_manifest_key,
        production_manifest_sha256=active.production_manifest_sha256,
        candidate_manifest_key=active.candidate_manifest_key,
        candidate_manifest_sha256=active.candidate_manifest_sha256,
        source_commit_sha=active.source_commit_sha,
        admission_sha256=active.admission_sha256,
        semantic_point_count=active.semantic_point_count,
        artifact_count=len(artifact_family),
        artifact_family=artifact_family,
        qdrant=qdrant,
    )


def _validate_active_artifacts(
    store: ObjectStore, active: ActiveProductionRelease
) -> tuple[str, ...]:
    artifacts = active.candidate_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise IntegrityError("M26-PREDECESSOR-001 artifact family missing")
    kinds: set[str] = set()
    for raw in artifacts:
        entry = _mapping(raw, "predecessor artifact")
        kind = _required_string(entry, "kind", "predecessor artifact")
        if kind in kinds:
            raise IntegrityError(f"M26-PREDECESSOR-002 duplicate artifact: {kind}")
        kinds.add(kind)
        key = _required_string(entry, "key", f"predecessor artifact {kind}")
        _release_key(key, active.release_id, f"predecessor artifact {kind}")
        expected_sha = _hex(identity_value=entry.get("sha256"), length=64)
        expected_bytes = entry.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise IntegrityError(f"M26-PREDECESSOR-003 invalid artifact size: {kind}")
        try:
            data = store.get(key)
        except (FileNotFoundError, KeyError) as exc:
            raise IntegrityError(f"M26-PREDECESSOR-004 artifact missing: {kind}") from exc
        if len(data) != expected_bytes or sha256_bytes(data) != expected_sha:
            raise IntegrityError(f"M26-PREDECESSOR-005 artifact integrity mismatch: {kind}")
    missing = sorted(REQUIRED_ARTIFACT_KINDS - kinds)
    if missing:
        raise IntegrityError(
            "M26-PREDECESSOR-006 required artifact family missing: " + ",".join(missing)
        )
    return tuple(sorted(kinds))


def _validate_production_qdrant(
    qdrant: ProductionQdrantQualification, active: ActiveProductionRelease
) -> None:
    if qdrant.collection != active.qdrant_collection:
        raise IntegrityError("M26-PREDECESSOR-006 Qdrant collection mismatch")
    if qdrant.status.casefold() != "green":
        raise IntegrityError("M26-PREDECESSOR-007 Qdrant collection is not green")
    if (
        qdrant.points_count != active.semantic_point_count
        or qdrant.full_identity_count != active.semantic_point_count
    ):
        raise IntegrityError("M26-PREDECESSOR-008 Qdrant identity count mismatch")
    if qdrant.vector_name != "default" or qdrant.vector_dimension <= 0:
        raise IntegrityError("M26-PREDECESSOR-009 Qdrant vector shape mismatch")
    if qdrant.distance.casefold() != "cosine":
        raise IntegrityError("M26-PREDECESSOR-010 Qdrant distance mismatch")
    for value in (
        qdrant.point_ids_sha256,
        qdrant.section_ids_sha256,
        qdrant.aggregate_identity_sha256,
        qdrant.vector_fingerprint_sha256,
    ):
        _hex(identity_value=value, length=64)


def _predecessor_qualification_sha256(value: PredecessorQualification) -> str:
    data = json.dumps(
        _jsonable_dataclass(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(data)


def _validate_qdrant(
    qdrant: QdrantQualification,
    *,
    expected_collection: str,
    expected_points: int,
) -> None:
    if qdrant.collection != expected_collection:
        raise IntegrityError("M26-QDRANT-001 collection mismatch")
    if qdrant.status.casefold() != "green":
        raise IntegrityError("M26-QDRANT-002 collection is not green")
    if qdrant.points_count != expected_points or qdrant.filtered_point_count != expected_points:
        raise IntegrityError("M26-QDRANT-003 point count mismatch")
    if qdrant.vector_name != "default" or qdrant.vector_dimension <= 0:
        raise IntegrityError("M26-QDRANT-004 vector shape mismatch")
    if qdrant.distance.casefold() != "cosine":
        raise IntegrityError("M26-QDRANT-005 distance mismatch")
    missing = sorted(REQUIRED_QDRANT_PAYLOAD_INDEXES - set(qdrant.payload_indexes))
    if missing:
        raise IntegrityError("M26-QDRANT-006 payload indexes missing: " + ",".join(missing))
    if qdrant.alias_count != 0:
        raise IntegrityError("M26-QDRANT-007 candidate collection has aliases")
    for value in (
        qdrant.point_ids_sha256,
        qdrant.section_ids_sha256,
        qdrant.aggregate_identity_sha256,
        qdrant.vector_fingerprint_sha256,
    ):
        _hex(identity_value=value, length=64)


def _build_production_manifest(
    candidate_manifest: Mapping[str, Any],
    *,
    candidate: CandidateQualification,
    predecessor: PredecessorQualification,
    promoted_at: str,
    owner_authorization: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(candidate_manifest))
    result["status"] = "production"
    result["channel"] = "production"
    authority = _mapping(result.get("authority"), "production authority")
    authority["candidate_only"] = False
    authority["production_pointer_authorized"] = True
    authority["public_production_traffic_authorized"] = False
    result["production_promotion"] = {
        "schema_version": SCHEMA_VERSION,
        "status": "production_pointer_authorized",
        "owner_authorization": owner_authorization,
        "promoted_at": promoted_at,
        "source_candidate_manifest_key": candidate.manifest_key,
        "source_candidate_manifest_sha256": candidate.manifest_sha256,
        "production_pointer_authorized": True,
        "public_production_traffic_authorized": False,
        "public_production_traffic_target": None,
        "qdrant_candidate_collection": candidate.qdrant.collection,
        "qdrant_candidate_identity": _jsonable_dataclass(candidate.qdrant),
        "qdrant_candidate_authority_filter": {
            "candidate_release_eligible": True,
            "production_authority": False,
        },
        "predecessor_qualification_sha256": _predecessor_qualification_sha256(predecessor),
    }
    return result


def _put_immutable(store: ObjectStore, key: str, data: bytes) -> None:
    digest = sha256_bytes(data)
    with suppress(ReleaseConflictError):
        store.put(
            key,
            data,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
    _verify_immutable(store, key, data)


def _verify_immutable(store: ObjectStore, key: str, expected: bytes) -> None:
    if store.get(key) != expected:
        raise IntegrityError(f"M26-PROMOTE-006 immutable object collision: {key}")


def _freeze_pointer(store: ObjectStore) -> FrozenPointer:
    metadata = store.head(PRODUCTION_POINTER_KEY)
    if metadata is None:
        raise IntegrityError("M26-POINTER-001 production pointer missing")
    raw = store.get(PRODUCTION_POINTER_KEY)
    return _pointer_from_bytes(raw, metadata.etag)


def _pointer_from_bytes(raw: bytes, etag: str) -> FrozenPointer:
    value = _json_object(raw, "production pointer")
    if value.get("schema_version") != "1.0" or value.get("channel") != "production":
        raise IntegrityError("M26-POINTER-002 production pointer shape mismatch")
    if value.get("production_authority") is not True:
        raise IntegrityError("M26-POINTER-003 production pointer authority missing")
    return FrozenPointer(
        raw=raw,
        sha256=sha256_bytes(raw),
        etag=etag,
        release_id=_required_string(value, "release_id", "production pointer"),
        manifest_key=_required_string(value, "manifest_key", "production pointer"),
        manifest_sha256=_hex(identity_value=value.get("manifest_sha256"), length=64),
    )


def _require_same_pointer(
    observed: FrozenPointer,
    expected: FrozenPointer,
    label: str,
    *,
    require_etag: bool = True,
) -> None:
    if observed.raw != expected.raw or observed.sha256 != expected.sha256:
        raise IntegrityError(f"M26-POINTER-004 {label} raw identity mismatch")
    if (
        observed.release_id,
        observed.manifest_key,
        observed.manifest_sha256,
    ) != (expected.release_id, expected.manifest_key, expected.manifest_sha256):
        raise IntegrityError(f"M26-POINTER-005 {label} parsed identity mismatch")
    if require_etag and observed.etag != expected.etag:
        raise IntegrityError(f"M26-POINTER-006 {label} ETag drift")


def _match_active_pointer(
    active: ActiveProductionRelease, pointer: FrozenPointer, label: str
) -> None:
    if (
        active.pointer_sha256 != pointer.sha256
        or active.release_id != pointer.release_id
        or active.production_manifest_key != pointer.manifest_key
        or active.production_manifest_sha256 != pointer.manifest_sha256
    ):
        raise IntegrityError(f"M26-POINTER-007 {label} resolver identity mismatch")


class _PointerOverlay:
    def __init__(self, store: ObjectStore, pointer: bytes) -> None:
        self.store = store
        self.pointer = pointer

    def get(self, key: str) -> bytes:
        if key == PRODUCTION_POINTER_KEY:
            return self.pointer
        return self.store.get(key)


def _promotion_result(plan: PromotionPlan, *, status: str, mutated: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "release_id": plan.candidate.release_id,
        "production_manifest_key": plan.production_manifest_key,
        "production_manifest_sha256": plan.production_manifest_sha256,
        "production_pointer_key": PRODUCTION_POINTER_KEY,
        "production_pointer_sha256": plan.target_pointer_sha256,
        "predecessor_pointer_sha256": plan.predecessor.sha256,
        "production_pointer_mutated": mutated,
        "public_production_traffic_mutated": False,
    }


def _rollback_result(plan: RollbackPlan, *, status: str, mutated: bool) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "expected_promoted_pointer_sha256": plan.expected_promoted.sha256,
        "production_pointer_sha256": plan.predecessor.sha256,
        "production_pointer_mutated": mutated,
        "public_production_traffic_mutated": False,
    }


def _pointer_receipt(pointer: FrozenPointer) -> dict[str, Any]:
    return {
        "key": PRODUCTION_POINTER_KEY,
        "sha256": pointer.sha256,
        "etag": pointer.etag,
        "bytes": len(pointer.raw),
        "release_id": pointer.release_id,
        "manifest_key": pointer.manifest_key,
        "manifest_sha256": pointer.manifest_sha256,
    }


def _jsonable_dataclass(value: Any) -> dict[str, Any]:
    result = asdict(value)

    def normalize(value: Any) -> Any:
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(result)


def _base64_bytes(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"{label} is missing")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise IntegrityError(f"{label} is not canonical base64") from exc


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise IntegrityError(f"{label} is invalid")
    return tuple(value)


def _candidate_qdrant_from_payload(value: Mapping[str, Any]) -> QdrantQualification:
    return QdrantQualification(
        collection=_required_string(value, "collection", "durable candidate Qdrant"),
        status=_required_string(value, "status", "durable candidate Qdrant"),
        points_count=_positive_int(value.get("points_count"), "durable candidate points_count"),
        filtered_point_count=_positive_int(
            value.get("filtered_point_count"), "durable candidate filtered_point_count"
        ),
        vector_name=_required_string(value, "vector_name", "durable candidate Qdrant"),
        vector_dimension=_positive_int(
            value.get("vector_dimension"), "durable candidate vector_dimension"
        ),
        distance=_required_string(value, "distance", "durable candidate Qdrant"),
        payload_indexes=_string_tuple(
            value.get("payload_indexes"), "durable candidate payload_indexes"
        ),
        alias_count=int(value.get("alias_count", 0)),
        point_ids_sha256=_hex(identity_value=value.get("point_ids_sha256"), length=64),
        section_ids_sha256=_hex(identity_value=value.get("section_ids_sha256"), length=64),
        aggregate_identity_sha256=_hex(
            identity_value=value.get("aggregate_identity_sha256"), length=64
        ),
        vector_fingerprint_sha256=_hex(
            identity_value=value.get("vector_fingerprint_sha256"), length=64
        ),
    )


def _production_qdrant_from_payload(
    value: Mapping[str, Any],
) -> ProductionQdrantQualification:
    aliases = value.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
        raise IntegrityError("durable predecessor Qdrant aliases are invalid")
    return ProductionQdrantQualification(
        collection=_required_string(value, "collection", "durable predecessor Qdrant"),
        status=_required_string(value, "status", "durable predecessor Qdrant"),
        points_count=_positive_int(value.get("points_count"), "durable predecessor points_count"),
        full_identity_count=_positive_int(
            value.get("full_identity_count"), "durable predecessor full_identity_count"
        ),
        vector_name=_required_string(value, "vector_name", "durable predecessor Qdrant"),
        vector_dimension=_positive_int(
            value.get("vector_dimension"), "durable predecessor vector_dimension"
        ),
        distance=_required_string(value, "distance", "durable predecessor Qdrant"),
        aliases=tuple(aliases),
        point_ids_sha256=_hex(identity_value=value.get("point_ids_sha256"), length=64),
        section_ids_sha256=_hex(identity_value=value.get("section_ids_sha256"), length=64),
        aggregate_identity_sha256=_hex(
            identity_value=value.get("aggregate_identity_sha256"), length=64
        ),
        vector_fingerprint_sha256=_hex(
            identity_value=value.get("vector_fingerprint_sha256"), length=64
        ),
    )


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    observed = value.get(key)
    if not isinstance(observed, str) or not observed:
        raise IntegrityError(f"{label} missing {key}")
    return observed


def _hex(*, identity_value: Any, length: int) -> str:
    if (
        not isinstance(identity_value, str)
        or len(identity_value) != length
        or any(character not in "0123456789abcdef" for character in identity_value)
    ):
        raise IntegrityError(f"identity must be lowercase {length}-character hex")
    return identity_value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IntegrityError(f"{label} must be a positive integer")
    return value


def _release_key(key: str, release_id: str, label: str) -> None:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != key:
        raise IntegrityError(f"{label} key is not canonical")
    if not key.startswith(f"releases/{release_id}/"):
        raise IntegrityError(f"{label} key escapes release namespace")
