from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    resolve_active_production_release,
)
from knowledge_engine.m26_admin_contract import AdminAPIError, IdempotencyCoordinator
from knowledge_engine.m26_admin_ingestion_sync import SyncBlogRequest, build_index_health
from knowledge_engine.m26_ask_api import build_owner_graph_dto
from knowledge_engine.m26_console_p05_ask_playground import (
    _active_release_id as playground_active_release_id,
)
from knowledge_engine.m26_console_p05_ask_playground import (
    _validate_release as validate_playground_release,
)
from knowledge_engine.m26_ingestion_candidate_writer import (
    CandidateVectorVerification,
    build_candidate_release_plan,
    stage_candidate_release,
)
from knowledge_engine.m26_ingestion_finalization import (
    AskEquivalentSpec,
    IsolatedIngestionFinalizer,
)
from knowledge_engine.m26_production_answer_bundle import (
    build_production_answer_compatibility_report,
    load_production_answer_bundle,
)
from knowledge_engine.m26_production_promotion import (
    REQUIRED_QDRANT_PAYLOAD_INDEXES,
    ProductionQdrantQualification,
    QdrantQualification,
    promotion_plan_from_payload,
    promotion_plan_to_payload,
)
from knowledge_engine.m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    active_manifest_observer_from_store,
    candidate_manifest_observer_from_store,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

SOURCE_A = "1" * 40
SOURCE_B = "2" * 40
ENGINE = "3" * 40
ADMISSION_A = "a" * 64
ADMISSION_B = "b" * 64
MARKER = "C3-SUCCESSOR-ONLY-NEBULA-7429"
PROMOTED_AT = "2026-09-12T09:00:00Z"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _artifact_bytes(
    release_id: str,
    *,
    marker: str,
    document_digest: str,
) -> dict[str, bytes]:
    concept_id = f"concepts/{release_id}"
    section_id = f"{concept_id}#proof"
    source_id = "proof-document"
    return {
        "document_pack_admission": _json_bytes(
            {"schema_version": "test-admission/v1", "release_id": release_id}
        ),
        "document_source_index": _json_bytes(
            {
                "schema_version": "knowledge-engine-document-source-index/v1",
                "release_id": release_id,
                "entries": [
                    {
                        "document_id": "proof-document",
                        "source_id": source_id,
                        "digest": document_digest,
                    }
                ],
            }
        ),
        "graph": _json_bytes(
            {
                "schema_version": "knowledge-engine-document-graph/v1",
                "release_id": release_id,
                "nodes": [{"concept_id": concept_id}],
                "edges": [],
            }
        ),
        "graph_v2": _json_bytes(
            {
                "schema_version": "knowledge-engine-graph-v2/v1",
                "release": {"release_id": release_id},
                "nodes": [{"concept_id": concept_id}],
                "edges": [],
            }
        ),
        "lexical_index": _json_bytes(
            {
                "schema_version": "knowledge-engine-lexical-index/v2",
                "release_id": release_id,
                "documents": [
                    {
                        "document_id": "proof-document",
                        "source_id": source_id,
                        "concept_id": concept_id,
                        "section_id": section_id,
                        "body": f"Finalization proof text {marker}",
                    }
                ],
            }
        ),
        "provenance": _json_bytes(
            {
                "schema_version": "knowledge-engine-document-provenance/v1",
                "release_id": release_id,
                "records": [],
            }
        ),
        "semantic_inputs": _json_bytes(
            {
                "schema_version": "knowledge-engine-semantic-inputs/v1",
                "release_id": release_id,
                "documents": [
                    {
                        "document_id": "proof-document",
                        "source_id": source_id,
                        "concept_id": concept_id,
                        "section_id": section_id,
                        "text": f"Finalization proof text {marker}",
                    }
                ],
            }
        ),
        "source_documents": _json_bytes(
            {
                "schema_version": "knowledge-engine-source-documents/v1",
                "release_id": release_id,
                "documents": [
                    {
                        "document_id": "proof-document",
                        "source_id": source_id,
                        "content_sha256": document_digest,
                        "text": f"Finalization proof text {marker}",
                    }
                ],
            }
        ),
    }


class _VectorMaterializer:
    def materialize_and_verify(
        self,
        *,
        collection_name: str,
        release_id: str,
        semantic_documents: Sequence[Mapping[str, Any]],
    ) -> CandidateVectorVerification:
        section_ids = tuple(sorted(str(item["section_id"]) for item in semantic_documents))
        return CandidateVectorVerification(
            collection_name=collection_name,
            release_id=release_id,
            point_count=len(section_ids),
            section_ids=section_ids,
            detail={"full_readback": True},
        )


def _candidate(
    store: FileObjectStore,
    release_id: str,
    *,
    source_sha: str,
    admission: str,
    marker: str,
    document_digest: str,
) -> tuple[dict[str, Any], Any]:
    plan = build_candidate_release_plan(
        release_id=release_id,
        engine_commit_sha=ENGINE,
        source_commit_sha=source_sha,
        source_repository_head_sha=source_sha,
        admission_sha256=admission,
        source_count=1,
        artifact_bytes=_artifact_bytes(
            release_id,
            marker=marker,
            document_digest=document_digest,
        ),
        created_at="2026-09-12T08:00:00Z",
    )
    receipt = stage_candidate_release(
        store=store,
        vector_materializer=_VectorMaterializer(),
        plan=plan,
    )
    return receipt, plan


def _bootstrap_production(store: FileObjectStore, plan: Any) -> bytes:
    candidate = json.loads(plan.manifest_bytes)
    production = copy.deepcopy(candidate)
    production["status"] = "production"
    production["channel"] = "production"
    production["authority"]["candidate_only"] = False
    production["authority"]["production_pointer_authorized"] = True
    production["authority"]["public_production_traffic_authorized"] = False
    production["production_promotion"] = {
        "production_pointer_authorized": True,
        "public_production_traffic_authorized": False,
        "source_candidate_manifest_key": plan.manifest_key,
        "source_candidate_manifest_sha256": plan.manifest_sha256,
        "qdrant_candidate_collection": plan.qdrant_collection,
    }
    production_key = f"releases/{plan.release_id}/promotion/bootstrap.json"
    production_bytes = _json_bytes(production)
    store.put(
        production_key,
        production_bytes,
        content_type="application/json",
        sha256=sha256_bytes(production_bytes),
    )
    pointer = _json_bytes(
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": plan.release_id,
            "manifest_key": production_key,
            "manifest_sha256": sha256_bytes(production_bytes),
            "production_authority": True,
            "public_production_traffic_mutated": False,
        }
    )
    store.put(
        PRODUCTION_POINTER_KEY,
        pointer,
        content_type="application/json",
        sha256=sha256_bytes(pointer),
    )
    return pointer


def _candidate_qdrant(release_id: str, collection: str) -> QdrantQualification:
    assert collection and release_id
    return QdrantQualification(
        collection=collection,
        status="green",
        points_count=1,
        filtered_point_count=1,
        vector_name="default",
        vector_dimension=3,
        distance="Cosine",
        payload_indexes=tuple(sorted(REQUIRED_QDRANT_PAYLOAD_INDEXES)),
        alias_count=0,
        point_ids_sha256="4" * 64,
        section_ids_sha256="5" * 64,
        aggregate_identity_sha256="6" * 64,
        vector_fingerprint_sha256="7" * 64,
    )


def _production_qdrant(active: Any) -> ProductionQdrantQualification:
    return ProductionQdrantQualification(
        collection=active.qdrant_collection,
        status="green",
        points_count=active.semantic_point_count,
        full_identity_count=active.semantic_point_count,
        vector_name="default",
        vector_dimension=3,
        distance="Cosine",
        aliases=(),
        point_ids_sha256="8" * 64,
        section_ids_sha256="9" * 64,
        aggregate_identity_sha256="c" * 64,
        vector_fingerprint_sha256="d" * 64,
    )


class _DenseChannel:
    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        del question, top_k
        active = bundle.active_release
        section_id = bundle.semantic_inputs["documents"][0]["section_id"]
        return {
            "backend_identity": {
                "authority_source": "resolved_production_pointer_chain",
                "release_id": active.release_id,
                "qdrant_collection": active.qdrant_collection,
                "production_pointer_sha256": active.pointer_sha256,
                "read_only": True,
            },
            "candidates": [
                {
                    "section_id": section_id,
                    "payload_release_id": active.release_id,
                    "score": 0.99,
                }
            ],
        }


def _source() -> dict[str, Any]:
    return {
        "source_revision": "git:" + SOURCE_B,
        "source_identity_digest": ADMISSION_B,
        "documents": [{"document_id": "proof-document", "digest": "f" * 64}],
    }


def _fixture(tmp_path: Path):
    store = FileObjectStore(tmp_path / "isolated-store")
    _, predecessor_plan = _candidate(
        store,
        "release-a",
        source_sha=SOURCE_A,
        admission=ADMISSION_A,
        marker="PREDECESSOR-CONTENT",
        document_digest="e" * 64,
    )
    predecessor = _bootstrap_production(store, predecessor_plan)
    candidate_receipt, _ = _candidate(
        store,
        "release-b-successor",
        source_sha=SOURCE_B,
        admission=ADMISSION_B,
        marker=MARKER,
        document_digest="f" * 64,
    )
    finalizer = IsolatedIngestionFinalizer(
        store=store,
        source_observer=_source,
        candidate_qdrant_observer=_candidate_qdrant,
        predecessor_qdrant_observer=_production_qdrant,
        dense_channel=_DenseChannel(),
        ask_spec=AskEquivalentSpec(
            question="What proves the C3 successor is active?",
            successor_only_marker=MARKER,
        ),
        promoted_at=PROMOTED_AT,
        owner_authorization="L3A C3 isolated qualification only",
    )
    return store, predecessor, candidate_receipt, finalizer


def test_isolated_activation_active_ask_and_exact_rollback(tmp_path: Path) -> None:
    store, predecessor, candidate_receipt, finalizer = _fixture(tmp_path)
    prepared = finalizer.prepare(
        candidate_receipt=candidate_receipt,
        source_observation=_source(),
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
    )
    restored = promotion_plan_from_payload(prepared["promotion_plan"])
    assert promotion_plan_to_payload(restored) == prepared["promotion_plan"]

    result = finalizer.execute(prepared)

    assert result["status"] == "active_successor"
    assert result["activation"]["production_pointer_mutated"] is True
    assert result["active_resolver"]["release_id"] == "release-b-successor"
    assert result["answer_bundle"]["release_id"] == "release-b-successor"
    assert result["ask_equivalent"]["successor_only"] is True
    assert result["authority"]["public_production_traffic_authorized"] is False
    assert resolve_active_production_release(store).release_id == "release-b-successor"
    bundle = load_production_answer_bundle(store=store)
    # C2 addendum: the canonical Ask and owner graph paths must accept the
    # pointer-selected successor instead of historical FULL_* identity.
    from knowledge_engine.m26_pa7_semantic_closure_runtime import (
        _assert_full_production_graph,
    )

    _assert_full_production_graph(bundle)
    graph_dto = build_owner_graph_dto(bundle)
    assert graph_dto["release_id"] == "release-b-successor"
    assert graph_dto["graph_v2_sha256"] == bundle.artifact_sha256["graph_v2"]
    assert graph_dto["binding"]["production_pointer_sha256"] == bundle.active_release.pointer_sha256
    assert playground_active_release_id(bundle) == "release-b-successor"
    validate_playground_release("release-b-successor", active_release_id="release-b-successor")
    with pytest.raises(AdminAPIError) as excinfo:
        validate_playground_release(
            "historical-full-release", active_release_id="release-b-successor"
        )
    assert excinfo.value.code == "PLAYGROUND_RELEASE_NOT_ACTIVE"
    compatibility = build_production_answer_compatibility_report(
        bundle,
        qdrant_point_count=1,
        qdrant_payload_samples=[
            {
                "section_id": "concepts/release-b-successor#proof",
                "release_id": "release-b-successor",
                "source_commit_sha": SOURCE_B,
                "admission_sha256": ADMISSION_B,
                "candidate_release_eligible": True,
                "production_authority": False,
            }
        ],
    )
    assert compatibility["status"] == "compatible"
    assert compatibility["expected"]["authority"] == ("resolved_production_pointer_chain")
    assert compatibility["qdrant"]["collection"] == ("m26_blog_release_b_successor")

    replay = finalizer.execute(prepared)
    assert replay["activation"]["status"] == "already_promoted"
    assert replay["activation"]["production_pointer_mutated"] is False

    rollback = finalizer.rollback(prepared)
    assert rollback["exact_predecessor_bytes_restored"] is True
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
    assert resolve_active_production_release(store).release_id == "release-a"


def test_source_drift_blocks_before_activation_write(tmp_path: Path) -> None:
    store, predecessor, candidate_receipt, finalizer = _fixture(tmp_path)
    prepared = finalizer.prepare(
        candidate_receipt=candidate_receipt,
        source_observation=_source(),
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
    )
    finalizer.source_observer = lambda: {
        **_source(),
        "documents": [{"document_id": "proof-document", "digest": "0" * 64}],
    }

    with pytest.raises(IntegrityError, match="exact source observation drift"):
        finalizer.execute(prepared)

    assert store.get(PRODUCTION_POINTER_KEY) == predecessor


def test_durable_plan_tamper_fails_closed(tmp_path: Path) -> None:
    _, predecessor, candidate_receipt, finalizer = _fixture(tmp_path)
    prepared = finalizer.prepare(
        candidate_receipt=candidate_receipt,
        source_observation=_source(),
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
    )
    tampered = copy.deepcopy(prepared["promotion_plan"])
    tampered["target_pointer_sha256"] = "0" * 64

    with pytest.raises(IntegrityError, match="durable target pointer digest mismatch"):
        promotion_plan_from_payload(tampered)


class _CrashAfterActivation:
    def __init__(self, delegate: IsolatedIngestionFinalizer) -> None:
        self.delegate = delegate
        self.crashed = False

    def prepare(self, **kwargs: Any) -> dict[str, Any]:
        return self.delegate.prepare(**kwargs)

    def execute(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        result = self.delegate.execute(plan)
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("injected process exit after isolated CAS")
        return result


def test_restart_resumes_exact_plan_and_health_reports_active_successor(
    tmp_path: Path,
) -> None:
    store, predecessor, candidate_receipt, finalizer = _fixture(tmp_path)
    db_path = tmp_path / "ingestion.sqlite3"
    ledger = SQLiteIngestionLedger(db_path)
    source = _source
    active = active_manifest_observer_from_store(store)
    adapter = SQLiteIngestionAdapter(
        ledger,
        source_observer=source,
        active_manifest_observer=active,
        candidate_manifest_observer=candidate_manifest_observer_from_store(store),
        candidate_executor=lambda *_args: candidate_receipt,
        finalization_executor=_CrashAfterActivation(finalizer),
    )
    request = SyncBlogRequest()
    lease = IdempotencyCoordinator(ledger).begin_stateful(
        actor_id="owner",
        method="POST",
        path="/v1/admin/ingestion/sync",
        idempotency_key="c3-restart-proof",
        request_payload=request.model_dump(exclude_none=True),
    )
    with pytest.raises(RuntimeError, match="process exit"):
        adapter.sync_blog(lease.operation_id, request, lease)
    job_id = "syncjob_" + lease.operation_id.removeprefix("admop_")
    failed = ledger.get_job(job_id)
    assert failed is not None
    assert failed["finalization_state"] == "FINALIZATION_BLOCKED"
    assert failed["finalization_plan_digest"]
    assert resolve_active_production_release(store).release_id == "release-b-successor"

    restarted = SQLiteIngestionAdapter(
        SQLiteIngestionLedger(db_path),
        source_observer=source,
        active_manifest_observer=active,
        candidate_manifest_observer=candidate_manifest_observer_from_store(store),
        candidate_executor=lambda *_args: (_ for _ in ()).throw(
            AssertionError("candidate must not rebuild during finalization resume")
        ),
        finalization_executor=finalizer,
    )
    completed = restarted.retry_job(job_id, owner="restarted-worker")
    assert completed["status"] == "SUCCEEDED"
    assert completed["result"]["activation"]["status"] == "already_promoted"
    assert completed["active_successor_release_id"] == "release-b-successor"
    assert completed["predecessor_pointer_sha256"] == sha256_bytes(predecessor)

    health = build_index_health(restarted.current_index()).data
    assert health["mode"] == "isolated_finalization"
    assert health["finalization"]["status"] == "active_successor"
    assert health["finalization"]["public_production_traffic_authorized"] is False


def test_isolated_authority_rejects_non_file_store(tmp_path: Path) -> None:
    class StoreProxy:
        def __init__(self) -> None:
            self.store = FileObjectStore(tmp_path / "proxy")

    with pytest.raises(IntegrityError, match="exact isolated FileObjectStore"):
        IsolatedIngestionFinalizer(
            store=StoreProxy(),  # type: ignore[arg-type]
            source_observer=_source,
            candidate_qdrant_observer=_candidate_qdrant,
            predecessor_qdrant_observer=_production_qdrant,
            dense_channel=_DenseChannel(),
            ask_spec=AskEquivalentSpec(question="proof?", successor_only_marker=MARKER),
            promoted_at=PROMOTED_AT,
            owner_authorization="isolated test",
        )


def test_predecessor_qdrant_drift_is_revalidated_before_pointer_write(
    tmp_path: Path,
) -> None:
    store, predecessor, candidate_receipt, finalizer = _fixture(tmp_path)
    prepared = finalizer.prepare(
        candidate_receipt=candidate_receipt,
        source_observation=_source(),
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
    )
    original = finalizer.predecessor_qdrant_observer
    finalizer.predecessor_qdrant_observer = lambda active: replace(
        original(active), aggregate_identity_sha256="0" * 64
    )

    with pytest.raises(IntegrityError, match="deterministic plan drift"):
        finalizer.execute(prepared)

    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
