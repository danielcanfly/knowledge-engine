from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import IntegrityError
from .m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    ActiveProductionRelease,
    resolve_active_production_release,
)
from .m26_admin_contract import canonical_json_bytes
from .m26_production_answer_bundle import (
    ProductionAnswerBundle,
    load_production_answer_bundle,
)
from .m26_production_promotion import (
    CandidateQualification,
    ProductionQdrantQualification,
    PromotionPlan,
    QdrantQualification,
    build_promotion_plan,
    build_rollback_plan,
    execute_promotion,
    execute_rollback,
    promotion_plan_from_payload,
    promotion_plan_receipt,
    promotion_plan_to_payload,
)
from .storage import FileObjectStore, sha256_bytes

SCHEMA_VERSION = "knowledge-engine-m26-ingestion-finalization/v1"
ISOLATED_AUTHORITY_SCOPE = "l3_isolated_test"


class DenseReadChannel(Protocol):
    def search(
        self, *, question: str, bundle: ProductionAnswerBundle, top_k: int
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class AskEquivalentSpec:
    question: str
    successor_only_marker: str
    top_k: int = 8

    def __post_init__(self) -> None:
        if not self.question.strip() or not self.successor_only_marker.strip():
            raise ValueError("Ask-equivalent question and successor marker are required")
        if not 1 <= self.top_k <= 20:
            raise ValueError("Ask-equivalent top_k must be between 1 and 20")


CandidateQdrantObserver = Callable[[str, str], QdrantQualification]
PredecessorQdrantObserver = Callable[[ActiveProductionRelease], ProductionQdrantQualification]


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{label} must be a JSON object")
    return value


def _artifact_entry(manifest: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise IntegrityError("C3 finalization manifest artifacts are unavailable")
    matches = [item for item in artifacts if isinstance(item, Mapping) and item.get("kind") == kind]
    if len(matches) != 1:
        raise IntegrityError(f"C3 finalization artifact identity is invalid: {kind}")
    return matches[0]


def _load_documents(
    store: FileObjectStore,
    manifest: Mapping[str, Any],
    kind: str,
) -> list[Mapping[str, Any]]:
    entry = _artifact_entry(manifest, kind)
    key = str(entry.get("key") or "")
    data = store.get(key)
    if sha256_bytes(data) != entry.get("sha256") or len(data) != entry.get("bytes"):
        raise IntegrityError(f"C3 finalization artifact drift: {kind}")
    payload = _json_object(data, f"C3 {kind}")
    documents = payload.get("documents")
    if not isinstance(documents, list) or any(not isinstance(item, Mapping) for item in documents):
        raise IntegrityError(f"C3 finalization artifact documents invalid: {kind}")
    return documents


def _document_text(document: Mapping[str, Any]) -> str:
    return "\n".join(
        str(document.get(key) or "") for key in ("title", "heading", "body", "text", "content")
    )


def _marker_sections(
    store: FileObjectStore,
    manifest: Mapping[str, Any],
    marker: str,
) -> set[str]:
    lexical = _load_documents(store, manifest, "lexical_index")
    semantic = _load_documents(store, manifest, "semantic_inputs")
    lexical_ids = {
        str(item.get("section_id"))
        for item in lexical
        if marker in _document_text(item) and item.get("section_id")
    }
    semantic_ids = {
        str(item.get("section_id"))
        for item in semantic
        if marker in _document_text(item) and item.get("section_id")
    }
    return lexical_ids & semantic_ids


def run_successor_only_ask_equivalent(
    *,
    store: FileObjectStore,
    bundle: ProductionAnswerBundle,
    dense_channel: DenseReadChannel,
    spec: AskEquivalentSpec,
) -> dict[str, Any]:
    """Prove an Ask-equivalent read through the newly active authority chain."""

    active = bundle.active_release
    matching_sections = _marker_sections(store, bundle.manifest, spec.successor_only_marker)
    if not matching_sections:
        raise IntegrityError(
            "C3-ASK-001 successor-only marker is absent from active lexical/semantic artifacts"
        )
    dense = dict(
        dense_channel.search(
            question=spec.question,
            bundle=bundle,
            top_k=spec.top_k,
        )
    )
    backend = dense.get("backend_identity")
    candidates = dense.get("candidates")
    if not isinstance(backend, Mapping) or not isinstance(candidates, Sequence):
        raise IntegrityError("C3-ASK-002 dense result is malformed")
    if (
        backend.get("authority_source") != "resolved_production_pointer_chain"
        or backend.get("release_id") != active.release_id
        or backend.get("qdrant_collection") != active.qdrant_collection
        or backend.get("production_pointer_sha256") != active.pointer_sha256
        or backend.get("read_only") is not True
    ):
        raise IntegrityError("C3-ASK-003 dense authority is not the active successor")
    evidence = [
        dict(item)
        for item in candidates
        if isinstance(item, Mapping)
        and item.get("section_id") in matching_sections
        and item.get("payload_release_id") == active.release_id
    ]
    if not evidence:
        raise IntegrityError("C3-ASK-004 dense read did not return successor-only evidence")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "successor_only_ask_equivalent_proven",
        "successor_only": True,
        "question_sha256": sha256_bytes(spec.question.encode("utf-8")),
        "marker_sha256": sha256_bytes(spec.successor_only_marker.encode("utf-8")),
        "release_id": active.release_id,
        "production_pointer_sha256": active.pointer_sha256,
        "production_manifest_sha256": active.production_manifest_sha256,
        "candidate_manifest_sha256": active.candidate_manifest_sha256,
        "qdrant_collection": active.qdrant_collection,
        "matching_section_ids": sorted(matching_sections),
        "dense_evidence": evidence,
        "authority_source": "resolved_production_pointer_chain",
        "read_only": True,
    }


class IsolatedIngestionFinalizer:
    """Bounded L3 finalizer. Construction rejects every non-file object store."""

    def __init__(
        self,
        *,
        store: FileObjectStore,
        source_observer: Callable[[], Mapping[str, Any]],
        candidate_qdrant_observer: CandidateQdrantObserver,
        predecessor_qdrant_observer: PredecessorQdrantObserver,
        dense_channel: DenseReadChannel,
        ask_spec: AskEquivalentSpec,
        promoted_at: str,
        owner_authorization: str,
        authority_scope: str = ISOLATED_AUTHORITY_SCOPE,
    ) -> None:
        if type(store) is not FileObjectStore or authority_scope != ISOLATED_AUTHORITY_SCOPE:
            raise IntegrityError(
                "C3-AUTH-001 finalization requires exact isolated FileObjectStore authority"
            )
        if not promoted_at or not owner_authorization:
            raise ValueError("finalization time and authorization identity are required")
        self.store = store
        self.source_observer = source_observer
        self.candidate_qdrant_observer = candidate_qdrant_observer
        self.predecessor_qdrant_observer = predecessor_qdrant_observer
        self.dense_channel = dense_channel
        self.ask_spec = ask_spec
        self.promoted_at = promoted_at
        self.owner_authorization = owner_authorization
        self.authority_scope = authority_scope

    def prepare(
        self,
        *,
        candidate_receipt: Mapping[str, Any],
        source_observation: Mapping[str, Any],
        expected_predecessor_pointer_sha256: str,
    ) -> dict[str, Any]:
        if candidate_receipt.get("status") != "candidate_release_finalized":
            raise IntegrityError("C3-FINALIZE-001 candidate is not verified")
        candidate_key = str(candidate_receipt.get("manifest_key") or "")
        candidate_sha = str(candidate_receipt.get("manifest_sha256") or "")
        candidate_manifest = _json_object(self.store.get(candidate_key), "C3 candidate manifest")
        release_id = str(candidate_manifest.get("release_id") or "")
        collection = str(candidate_manifest.get("qdrant_collection") or "")
        if (
            candidate_receipt.get("release_id") != release_id
            or candidate_receipt.get("qdrant_collection") != collection
        ):
            raise IntegrityError("C3-FINALIZE-005 candidate receipt identity mismatch")
        qdrant = self.candidate_qdrant_observer(release_id, collection)
        predecessor_active = resolve_active_production_release(self.store)
        predecessor_bundle = load_production_answer_bundle(store=self.store)
        if _marker_sections(
            self.store,
            predecessor_bundle.manifest,
            self.ask_spec.successor_only_marker,
        ):
            raise IntegrityError("C3-ASK-005 successor-only marker already exists in predecessor")
        plan = build_promotion_plan(
            store=self.store,
            candidate_manifest_key=candidate_key,
            candidate_manifest_sha256=candidate_sha,
            expected_predecessor_pointer_sha256=expected_predecessor_pointer_sha256,
            promoted_at=self.promoted_at,
            owner_authorization=self.owner_authorization,
            qdrant=qdrant,
            predecessor_qdrant=self.predecessor_qdrant_observer(predecessor_active),
        )
        if not _marker_sections(
            self.store, candidate_manifest, self.ask_spec.successor_only_marker
        ):
            raise IntegrityError(
                "C3-ASK-006 successor-only marker is not in candidate lexical/semantic artifacts"
            )
        self._validate_source(plan.candidate, source_observation)
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "finalization_ready",
            "authority_scope": self.authority_scope,
            "public_production_traffic_authorized": False,
            "source_observation": dict(source_observation),
            "source_observation_sha256": _hash(source_observation),
            "candidate_receipt_sha256": _hash(candidate_receipt),
            "predecessor_marker_absent": True,
            "promotion_plan": promotion_plan_to_payload(plan),
            "promotion_plan_receipt": promotion_plan_receipt(plan),
            "ask_equivalent": {
                "question": self.ask_spec.question,
                "successor_only_marker": self.ask_spec.successor_only_marker,
                "top_k": self.ask_spec.top_k,
            },
        }

    def execute(self, durable_plan: Mapping[str, Any]) -> dict[str, Any]:
        if (
            durable_plan.get("schema_version") != SCHEMA_VERSION
            or durable_plan.get("authority_scope") != self.authority_scope
            or durable_plan.get("public_production_traffic_authorized") is not False
        ):
            raise IntegrityError("C3-AUTH-002 durable finalization authority mismatch")
        source = durable_plan.get("source_observation")
        if not isinstance(source, Mapping) or _hash(source) != durable_plan.get(
            "source_observation_sha256"
        ):
            raise IntegrityError("C3-FINALIZE-002 durable source identity mismatch")
        plan_payload = durable_plan.get("promotion_plan")
        if not isinstance(plan_payload, Mapping):
            raise IntegrityError("C3-FINALIZE-003 durable promotion plan missing")
        plan = promotion_plan_from_payload(plan_payload)
        ask = durable_plan.get("ask_equivalent")
        if not isinstance(ask, Mapping) or ask != {
            "question": self.ask_spec.question,
            "successor_only_marker": self.ask_spec.successor_only_marker,
            "top_k": self.ask_spec.top_k,
        }:
            raise IntegrityError("C3-ASK-007 durable Ask-equivalent identity mismatch")
        observed_source = dict(self.source_observer())
        if _hash(observed_source) != durable_plan.get("source_observation_sha256"):
            raise IntegrityError("C3-SOURCE-003 exact source observation drift")
        self._validate_source(plan.candidate, observed_source)

        current_pointer = self.store.get(PRODUCTION_POINTER_KEY)
        if current_pointer != plan.target_pointer_bytes:
            current_active = resolve_active_production_release(self.store)
            rebuilt = build_promotion_plan(
                store=self.store,
                candidate_manifest_key=plan.candidate.manifest_key,
                candidate_manifest_sha256=plan.candidate.manifest_sha256,
                expected_predecessor_pointer_sha256=plan.predecessor.sha256,
                promoted_at=plan.promoted_at,
                owner_authorization=plan.owner_authorization,
                qdrant=self.candidate_qdrant_observer(
                    plan.candidate.release_id, plan.candidate.qdrant.collection
                ),
                predecessor_qdrant=self.predecessor_qdrant_observer(current_active),
            )
            if rebuilt != plan:
                raise IntegrityError("C3-FINALIZE-004 deterministic plan drift")

        activation = execute_promotion(
            store=self.store,
            plan=plan,
            revalidate_qdrant=lambda: self.candidate_qdrant_observer(
                plan.candidate.release_id, plan.candidate.qdrant.collection
            ),
            revalidate_predecessor_qdrant=lambda: self.predecessor_qdrant_observer(
                resolve_active_production_release(
                    _ExactPointerView(self.store, plan.predecessor.raw)
                )
            ),
        )
        active = resolve_active_production_release(self.store)
        bundle = load_production_answer_bundle(store=self.store)
        self._validate_active_authority(plan, active, bundle)
        ask = run_successor_only_ask_equivalent(
            store=self.store,
            bundle=bundle,
            dense_channel=self.dense_channel,
            spec=self.ask_spec,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "active_successor",
            "release_id": plan.candidate.release_id,
            "manifest_key": plan.candidate.manifest_key,
            "manifest_sha256": plan.candidate.manifest_sha256,
            "candidate_release_id": plan.candidate.release_id,
            "candidate_manifest_key": plan.candidate.manifest_key,
            "candidate_manifest_sha256": plan.candidate.manifest_sha256,
            "predecessor_pointer_sha256": plan.predecessor.sha256,
            "production_pointer_sha256": active.pointer_sha256,
            "production_manifest_key": active.production_manifest_key,
            "production_manifest_sha256": active.production_manifest_sha256,
            "activation": activation,
            "active_resolver": {
                "release_id": active.release_id,
                "qdrant_collection": active.qdrant_collection,
                "source_commit_sha": active.source_commit_sha,
                "admission_sha256": active.admission_sha256,
            },
            "answer_bundle": {
                "release_id": bundle.release_id,
                "artifact_keys": dict(sorted(bundle.artifact_keys.items())),
                "artifact_sha256": dict(sorted(bundle.artifact_sha256.items())),
            },
            "ask_equivalent": ask,
            "authority": {
                "scope": self.authority_scope,
                "isolated": True,
                "production_object_store_writes": 0,
                "production_qdrant_writes": 0,
                "public_production_traffic_authorized": False,
                "public_production_traffic_mutated": False,
            },
        }

    def rollback(self, durable_plan: Mapping[str, Any]) -> dict[str, Any]:
        plan_payload = durable_plan.get("promotion_plan")
        if not isinstance(plan_payload, Mapping):
            raise IntegrityError("C3-ROLLBACK-001 durable promotion plan missing")
        plan = promotion_plan_from_payload(plan_payload)
        rollback = execute_rollback(
            store=self.store,
            plan=build_rollback_plan(plan),
            verify_predecessor_qdrant=self.predecessor_qdrant_observer,
        )
        if self.store.get(PRODUCTION_POINTER_KEY) != plan.predecessor.raw:
            raise IntegrityError("C3-ROLLBACK-002 predecessor bytes were not restored")
        restored = load_production_answer_bundle(store=self.store)
        if _marker_sections(self.store, restored.manifest, self.ask_spec.successor_only_marker):
            raise IntegrityError("C3-ROLLBACK-003 successor marker survived rollback")
        return {
            **rollback,
            "exact_predecessor_bytes_restored": True,
            "successor_only_marker_active_after_rollback": False,
            "authority_scope": self.authority_scope,
        }

    @staticmethod
    def _validate_source(
        candidate: CandidateQualification,
        source_observation: Mapping[str, Any],
    ) -> None:
        revision = str(source_observation.get("source_revision") or "")
        identity = str(source_observation.get("source_identity_digest") or "")
        if revision not in {candidate.source_commit_sha, "git:" + candidate.source_commit_sha}:
            raise IntegrityError("C3-SOURCE-001 source revision drift")
        if identity != candidate.admission_sha256:
            raise IntegrityError("C3-SOURCE-002 source identity drift")

    @staticmethod
    def _validate_active_authority(
        plan: PromotionPlan,
        active: ActiveProductionRelease,
        bundle: ProductionAnswerBundle,
    ) -> None:
        if (
            active.release_id != plan.candidate.release_id
            or active.pointer_sha256 != plan.target_pointer_sha256
            or bundle.release_id != plan.candidate.release_id
            or bundle.manifest_sha256 != plan.candidate.manifest_sha256
        ):
            raise IntegrityError("C3-FINALIZE-006 active successor identity mismatch")
        promotion_authority = active.production_manifest.get("authority")
        if (
            not isinstance(promotion_authority, Mapping)
            or promotion_authority.get("public_production_traffic_authorized") is not False
            or active.pointer.get("public_production_traffic_mutated") is not False
        ):
            raise IntegrityError("C3-AUTH-003 public production traffic authority widened")


class _ExactPointerView:
    def __init__(self, store: FileObjectStore, pointer: bytes) -> None:
        self.store = store
        self.pointer = pointer

    def get(self, key: str) -> bytes:
        return self.pointer if key == PRODUCTION_POINTER_KEY else self.store.get(key)


__all__ = [
    "AskEquivalentSpec",
    "ISOLATED_AUTHORITY_SCOPE",
    "IsolatedIngestionFinalizer",
    "run_successor_only_ask_equivalent",
]
