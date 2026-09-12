from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.errors import IntegrityError, ReleaseConflictError
from knowledge_engine.m26_active_production_release import (
    PRODUCTION_POINTER_KEY,
    resolve_active_production_release,
)
from knowledge_engine.m26_production_promotion import (
    REQUIRED_ARTIFACT_KINDS,
    REQUIRED_QDRANT_PAYLOAD_INDEXES,
    ProductionQdrantQualification,
    QdrantQualification,
    build_promotion_plan,
    build_rollback_plan,
    execute_promotion,
    execute_rollback,
    pretty_json_bytes,
    promotion_plan_receipt,
    rollback_plan_receipt,
)
from knowledge_engine.storage import FileObjectStore, ObjectMetadata, sha256_bytes

SOURCE_SHA = "1" * 40
ENGINE_SHA = "2" * 40
ADMISSION_SHA = "3" * 64
PREDECESSOR = "release-a"
CANDIDATE = "release-b-generic"
PROMOTED_AT = "2026-09-08T00:00:00Z"
AUTHORIZATION = "BP-4 qualification fixture; no live promotion authority"


def _put(store: FileObjectStore, key: str, value: Any) -> bytes:
    data = pretty_json_bytes(value)
    store.put(key, data, content_type="application/json", sha256=sha256_bytes(data))
    return data


def _candidate_manifest(store: FileObjectStore, release_id: str) -> tuple[str, bytes]:
    artifacts = []
    for index, kind in enumerate(sorted(REQUIRED_ARTIFACT_KINDS)):
        key = f"releases/{release_id}/artifacts/{kind}.json"
        data = pretty_json_bytes({"kind": kind, "ordinal": index})
        store.put(key, data, content_type="application/json", sha256=sha256_bytes(data))
        artifacts.append(
            {
                "kind": kind,
                "key": key,
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "content_type": "application/json",
            }
        )
    manifest = {
        "schema_version": "knowledge-engine-release/v1",
        "release_id": release_id,
        "status": "candidate",
        "qdrant_collection": f"qdrant_{release_id}",
        "identities": {
            "engine_commit_sha": ENGINE_SHA,
            "source_commit_sha": SOURCE_SHA,
            "admission_sha256": ADMISSION_SHA,
        },
        "counts": {"lexical_documents": 7, "semantic_documents": 7},
        "authority": {
            "candidate_only": True,
            "source_admitted": True,
            "candidate_release_authorized": True,
            "semantic_serving_authorized": True,
            "production_pointer_authorized": False,
            "public_production_traffic_authorized": False,
        },
        "artifacts": artifacts,
    }
    key = f"releases/{release_id}/manifest.json"
    return key, _put(store, key, manifest)


def _production_chain(store: FileObjectStore, release_id: str) -> bytes:
    candidate_key, candidate_bytes = _candidate_manifest(store, release_id)
    candidate_sha = sha256_bytes(candidate_bytes)
    production = json.loads(candidate_bytes)
    production["status"] = "production"
    production["authority"]["production_pointer_authorized"] = True
    production["production_promotion"] = {
        "production_pointer_authorized": True,
        "source_candidate_manifest_key": candidate_key,
        "source_candidate_manifest_sha256": candidate_sha,
        "qdrant_candidate_collection": f"qdrant_{release_id}",
    }
    production_key = f"releases/{release_id}/promotion/production-manifest.json"
    production_bytes = _put(store, production_key, production)
    return _put(
        store,
        PRODUCTION_POINTER_KEY,
        {
            "schema_version": "1.0",
            "channel": "production",
            "production_authority": True,
            "release_id": release_id,
            "manifest_key": production_key,
            "manifest_sha256": sha256_bytes(production_bytes),
        },
    )


def _qdrant(release_id: str = CANDIDATE) -> QdrantQualification:
    return QdrantQualification(
        collection=f"qdrant_{release_id}",
        status="green",
        points_count=7,
        filtered_point_count=7,
        vector_name="default",
        vector_dimension=1024,
        distance="Cosine",
        payload_indexes=tuple(sorted(REQUIRED_QDRANT_PAYLOAD_INDEXES)),
        alias_count=0,
        point_ids_sha256="a" * 64,
        section_ids_sha256="b" * 64,
        aggregate_identity_sha256="c" * 64,
        vector_fingerprint_sha256="d" * 64,
    )


def _predecessor_qdrant(_active: Any = None) -> ProductionQdrantQualification:
    return ProductionQdrantQualification(
        collection=f"qdrant_{PREDECESSOR}",
        status="green",
        points_count=7,
        full_identity_count=7,
        vector_name="default",
        vector_dimension=1024,
        distance="Cosine",
        aliases=(),
        point_ids_sha256="a" * 64,
        section_ids_sha256="b" * 64,
        aggregate_identity_sha256="c" * 64,
        vector_fingerprint_sha256="d" * 64,
    )


def _seed(tmp_path: Path):
    store = FileObjectStore(tmp_path)
    predecessor_bytes = _production_chain(store, PREDECESSOR)
    candidate_key, candidate_bytes = _candidate_manifest(store, CANDIDATE)
    plan = build_promotion_plan(
        store=store,
        candidate_manifest_key=candidate_key,
        candidate_manifest_sha256=sha256_bytes(candidate_bytes),
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor_bytes),
        promoted_at=PROMOTED_AT,
        owner_authorization=AUTHORIZATION,
        qdrant=_qdrant(),
        predecessor_qdrant=_predecessor_qdrant(),
    )
    return store, predecessor_bytes, plan


def test_plan_is_generic_deterministic_and_read_only(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file())
    second = build_promotion_plan(
        store=store,
        candidate_manifest_key=plan.candidate.manifest_key,
        candidate_manifest_sha256=plan.candidate.manifest_sha256,
        expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
        promoted_at=PROMOTED_AT,
        owner_authorization=AUTHORIZATION,
        qdrant=_qdrant(),
        predecessor_qdrant=_predecessor_qdrant(),
    )
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file())
    assert second == plan
    assert before == after
    assert plan.candidate.release_id == CANDIDATE
    assert plan.predecessor.release_id == PREDECESSOR
    production_manifest = json.loads(plan.production_manifest_bytes)
    assert production_manifest["status"] == "production"
    assert production_manifest["channel"] == "production"
    assert production_manifest["authority"]["candidate_only"] is False
    assert production_manifest["authority"]["production_pointer_authorized"] is True
    assert json.loads(plan.target_pointer_bytes)["release_id"] == CANDIDATE


def test_plan_fails_on_artifact_digest_drift(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    artifact_key = f"releases/{CANDIDATE}/artifacts/graph.json"
    _put(store, artifact_key, {"tampered": True})
    with pytest.raises(IntegrityError, match="artifact integrity"):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=plan.candidate.manifest_sha256,
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=_qdrant(),
            predecessor_qdrant=_predecessor_qdrant(),
        )


def test_plan_fails_on_candidate_manifest_hash_mismatch(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    with pytest.raises(IntegrityError, match="manifest digest"):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256="0" * 64,
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=_qdrant(),
            predecessor_qdrant=_predecessor_qdrant(),
        )


def test_plan_fails_on_candidate_status_and_authority(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    raw = json.loads(store.get(plan.candidate.manifest_key))
    raw["status"] = "production"
    changed = _put(store, plan.candidate.manifest_key, raw)
    with pytest.raises(IntegrityError, match="status mismatch"):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=sha256_bytes(changed),
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=_qdrant(),
            predecessor_qdrant=_predecessor_qdrant(),
        )
    raw["status"] = "candidate"
    raw["authority"]["production_pointer_authorized"] = True
    changed = _put(store, plan.candidate.manifest_key, raw)
    with pytest.raises(IntegrityError, match="authority mismatch"):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=sha256_bytes(changed),
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=_qdrant(),
            predecessor_qdrant=_predecessor_qdrant(),
        )


def test_plan_fails_on_missing_candidate_artifact(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    store.delete(f"releases/{CANDIDATE}/artifacts/graph.json")
    with pytest.raises(FileNotFoundError):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=plan.candidate.manifest_sha256,
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=_qdrant(),
            predecessor_qdrant=_predecessor_qdrant(),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("filtered_point_count", 6, "point count"),
        ("alias_count", 1, "aliases"),
        ("status", "yellow", "not green"),
    ],
)
def test_plan_fails_on_qdrant_ineligibility(
    tmp_path: Path, field: str, value: Any, message: str
) -> None:
    store, predecessor, plan = _seed(tmp_path)
    qdrant_values = _qdrant().__dict__ | {field: value}
    with pytest.raises(IntegrityError, match=message):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=plan.candidate.manifest_sha256,
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=QdrantQualification(**qdrant_values),
            predecessor_qdrant=_predecessor_qdrant(),
        )


def test_plan_requires_all_exact_filter_indexes(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    indexes = tuple(sorted(REQUIRED_QDRANT_PAYLOAD_INDEXES - {"release_id"}))
    with pytest.raises(IntegrityError, match="payload indexes missing"):
        build_promotion_plan(
            store=store,
            candidate_manifest_key=plan.candidate.manifest_key,
            candidate_manifest_sha256=plan.candidate.manifest_sha256,
            expected_predecessor_pointer_sha256=sha256_bytes(predecessor),
            promoted_at=PROMOTED_AT,
            owner_authorization=AUTHORIZATION,
            qdrant=QdrantQualification(**(_qdrant().__dict__ | {"payload_indexes": indexes})),
            predecessor_qdrant=_predecessor_qdrant(),
        )


def test_promotion_cas_and_active_resolver_compatibility(tmp_path: Path) -> None:
    store, _, plan = _seed(tmp_path)
    result = execute_promotion(store=store, plan=plan, revalidate_qdrant=_qdrant)
    assert result["status"] == "production_pointer_promoted"
    assert result["production_pointer_mutated"] is True
    assert store.get(PRODUCTION_POINTER_KEY) == plan.target_pointer_bytes
    active = resolve_active_production_release(store)
    assert active.release_id == CANDIDATE
    assert active.candidate_manifest_sha256 == plan.candidate.manifest_sha256
    assert active.qdrant_collection == _qdrant().collection


def test_promotion_exact_replay_is_idempotent(tmp_path: Path) -> None:
    store, _, plan = _seed(tmp_path)
    execute_promotion(store=store, plan=plan)
    result = execute_promotion(store=store, plan=plan)
    assert result["status"] == "already_promoted"
    assert result["production_pointer_mutated"] is False


def test_promotion_stale_pointer_fails_before_manifest_write(tmp_path: Path) -> None:
    store, _, plan = _seed(tmp_path)
    _production_chain(store, "release-c")
    with pytest.raises(IntegrityError, match="promotion predecessor"):
        execute_promotion(store=store, plan=plan)
    assert store.head(plan.production_manifest_key) is None


class _FailPointerCas:
    def __init__(self, store: FileObjectStore) -> None:
        self.store = store
        self.pointer_put_attempts = 0

    def get(self, key: str) -> bytes:
        return self.store.get(key)

    def head(self, key: str) -> ObjectMetadata | None:
        return self.store.head(key)

    def put(self, key: str, data: bytes, **kwargs: Any) -> ObjectMetadata:
        if key == PRODUCTION_POINTER_KEY:
            self.pointer_put_attempts += 1
            raise ReleaseConflictError("injected CAS failure")
        return self.store.put(key, data, **kwargs)

    def delete(self, key: str) -> None:
        self.store.delete(key)


class _BadPointerReadback(_FailPointerCas):
    def __init__(self, store: FileObjectStore) -> None:
        super().__init__(store)
        self.after_pointer_put = False

    def get(self, key: str) -> bytes:
        data = self.store.get(key)
        if key == PRODUCTION_POINTER_KEY and self.after_pointer_put:
            self.after_pointer_put = False
            return data + b" "
        return data

    def put(self, key: str, data: bytes, **kwargs: Any) -> ObjectMetadata:
        result = self.store.put(key, data, **kwargs)
        if key == PRODUCTION_POINTER_KEY:
            self.after_pointer_put = True
        return result


def test_partial_failure_leaves_only_inert_orphan_manifest(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    failing = _FailPointerCas(store)
    with pytest.raises(ReleaseConflictError, match="injected"):
        execute_promotion(store=failing, plan=plan)
    assert failing.pointer_put_attempts == 1
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
    assert store.get(plan.production_manifest_key) == plan.production_manifest_bytes
    assert resolve_active_production_release(store).release_id == PREDECESSOR


def test_promotion_pointer_readback_mismatch_is_detected(tmp_path: Path) -> None:
    store, _, plan = _seed(tmp_path)
    with pytest.raises(IntegrityError, match="pointer readback mismatch"):
        execute_promotion(store=_BadPointerReadback(store), plan=plan)


def test_promotion_revalidation_failure_stops_before_write(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)

    def unavailable() -> QdrantQualification:
        raise IntegrityError("candidate Qdrant unavailable")

    with pytest.raises(IntegrityError, match="Qdrant unavailable"):
        execute_promotion(store=store, plan=plan, revalidate_qdrant=unavailable)
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
    assert store.head(plan.production_manifest_key) is None


def test_immutable_manifest_collision_fails_before_pointer_write(tmp_path: Path) -> None:
    store, predecessor, plan = _seed(tmp_path)
    _put(store, plan.production_manifest_key, {"collision": True})
    with pytest.raises(IntegrityError, match="immutable object collision"):
        execute_promotion(store=store, plan=plan)
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor


def test_rollback_inverse_cas_restores_exact_predecessor_bytes(tmp_path: Path) -> None:
    store, predecessor, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    checked: list[str] = []

    def verify(active: Any) -> ProductionQdrantQualification:
        checked.append(active.release_id)
        return _predecessor_qdrant()

    result = execute_rollback(store=store, plan=rollback, verify_predecessor_qdrant=verify)
    assert result["status"] == "production_pointer_restored"
    assert result["production_pointer_mutated"] is True
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
    assert checked == [PREDECESSOR]


def test_rollback_exact_replay_is_idempotent(tmp_path: Path) -> None:
    store, predecessor, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    execute_rollback(store=store, plan=rollback, verify_predecessor_qdrant=_predecessor_qdrant)
    result = execute_rollback(
        store=store, plan=rollback, verify_predecessor_qdrant=_predecessor_qdrant
    )
    assert result["status"] == "already_rolled_back"
    assert result["production_pointer_mutated"] is False
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor


def test_rollback_a_to_b_to_c_fails_close_without_c_to_a(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    pointer_c = _production_chain(store, "release-c")
    rollback = build_rollback_plan(promotion)
    with pytest.raises(IntegrityError, match="rollback promoted target"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == pointer_c
    assert resolve_active_production_release(store).release_id == "release-c"


def test_rollback_rejects_expected_target_hash_tamper(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    tampered = replace(
        rollback,
        expected_promoted=replace(rollback.expected_promoted, sha256="0" * 64),
    )
    with pytest.raises(IntegrityError, match="rollback promoted target"):
        execute_rollback(
            store=store,
            plan=tampered,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_rejects_predecessor_hash_tamper(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    tampered = replace(
        rollback,
        predecessor=replace(rollback.predecessor, sha256="0" * 64),
    )
    with pytest.raises(IntegrityError, match="rollback predecessor"):
        execute_rollback(
            store=store,
            plan=tampered,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_predecessor_chain_failure_stops_before_write(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    store.delete(rollback.predecessor.manifest_key)
    with pytest.raises(IntegrityError, match="production manifest missing"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_predecessor_candidate_failure_stops_before_write(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    store.delete(f"releases/{PREDECESSOR}/manifest.json")
    with pytest.raises(IntegrityError, match="candidate manifest missing"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_predecessor_artifact_failure_stops_before_write(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    manifest = json.loads(store.get(f"releases/{PREDECESSOR}/manifest.json"))
    manifest["artifacts"] = [row for row in manifest["artifacts"] if row["kind"] != "lexical_index"]
    changed = _put(store, f"releases/{PREDECESSOR}/manifest.json", manifest)
    production = json.loads(store.get(rollback.predecessor.manifest_key))
    production["artifacts"] = manifest["artifacts"]
    production["production_promotion"]["source_candidate_manifest_sha256"] = sha256_bytes(changed)
    production_bytes = _put(store, rollback.predecessor.manifest_key, production)
    predecessor_value = json.loads(rollback.predecessor.raw)
    predecessor_value["manifest_sha256"] = sha256_bytes(production_bytes)
    predecessor_raw = pretty_json_bytes(predecessor_value)
    tampered = replace(
        rollback,
        predecessor=replace(
            rollback.predecessor,
            raw=predecessor_raw,
            sha256=sha256_bytes(predecessor_raw),
            manifest_sha256=sha256_bytes(production_bytes),
        ),
    )
    with pytest.raises(IntegrityError, match="required runtime artifacts missing"):
        execute_rollback(
            store=store,
            plan=tampered,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_missing_predecessor_artifact_object_stops_before_write(
    tmp_path: Path,
) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    store.delete(f"releases/{PREDECESSOR}/artifacts/graph.json")
    with pytest.raises(IntegrityError, match="artifact missing"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_predecessor_qdrant_failure_stops_before_write(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)

    def unavailable(_active: Any) -> ProductionQdrantQualification:
        raise IntegrityError("predecessor Qdrant unavailable")

    with pytest.raises(IntegrityError, match="Qdrant unavailable"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=unavailable,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_cas_conflict_fails_without_restore(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    with pytest.raises(ReleaseConflictError, match="injected"):
        execute_rollback(
            store=_FailPointerCas(store),
            plan=build_rollback_plan(promotion),
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
    assert store.get(PRODUCTION_POINTER_KEY) == promotion.target_pointer_bytes


def test_rollback_readback_mismatch_is_detected(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    with pytest.raises(IntegrityError, match="pointer readback mismatch"):
        execute_rollback(
            store=_BadPointerReadback(store),
            plan=build_rollback_plan(promotion),
            verify_predecessor_qdrant=_predecessor_qdrant,
        )


def test_dry_run_receipts_are_explicitly_zero_write(tmp_path: Path) -> None:
    _, _, promotion = _seed(tmp_path)
    promotion_receipt = promotion_plan_receipt(promotion)
    rollback_receipt = rollback_plan_receipt(build_rollback_plan(promotion))
    assert promotion_receipt["mode"] == "deterministic_dry_run"
    assert rollback_receipt["mode"] == "deterministic_dry_run"
    assert promotion_receipt["writes_performed"] == 0
    assert rollback_receipt["writes_performed"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "point_ids_sha256",
        "section_ids_sha256",
        "aggregate_identity_sha256",
        "vector_fingerprint_sha256",
    ],
)
def test_promotion_revalidation_fails_on_exact_qdrant_identity_drift(
    tmp_path: Path, field: str
) -> None:
    store, predecessor, plan = _seed(tmp_path)
    drifted = replace(plan.candidate.qdrant, **{field: "f" * 64})
    with pytest.raises(IntegrityError, match="candidate qualification drift"):
        execute_promotion(store=store, plan=plan, revalidate_qdrant=lambda: drifted)
    assert store.get(PRODUCTION_POINTER_KEY) == predecessor
    assert store.head(plan.production_manifest_key) is None


def test_already_promoted_revalidates_candidate_and_predecessor_qdrant(
    tmp_path: Path,
) -> None:
    store, _, plan = _seed(tmp_path)
    execute_promotion(store=store, plan=plan)
    drifted = replace(plan.candidate.qdrant, vector_fingerprint_sha256="e" * 64)
    with pytest.raises(IntegrityError, match="idempotent candidate health drift"):
        execute_promotion(store=store, plan=plan, revalidate_qdrant=lambda: drifted)
    result = execute_promotion(
        store=store,
        plan=plan,
        revalidate_qdrant=lambda: plan.candidate.qdrant,
        revalidate_predecessor_qdrant=lambda: plan.predecessor_qualification.qdrant,
    )
    assert result["status"] == "already_promoted"


def test_already_rolled_back_revalidates_predecessor_qdrant(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    execute_rollback(store=store, plan=rollback, verify_predecessor_qdrant=_predecessor_qdrant)
    drifted = replace(
        rollback.predecessor_qualification.qdrant,
        aggregate_identity_sha256="d" * 64,
    )
    with pytest.raises(IntegrityError, match="idempotent predecessor health drift"):
        execute_rollback(
            store=store,
            plan=rollback,
            verify_predecessor_qdrant=lambda _active: drifted,
        )


def test_predecessor_missing_required_artifact_family_fails_closed(tmp_path: Path) -> None:
    store, _, promotion = _seed(tmp_path)
    execute_promotion(store=store, plan=promotion)
    rollback = build_rollback_plan(promotion)
    manifest_key = f"releases/{PREDECESSOR}/manifest.json"
    manifest = json.loads(store.get(manifest_key))
    manifest["artifacts"] = [
        row for row in manifest["artifacts"] if row["kind"] != "semantic_inputs"
    ]
    changed = _put(store, manifest_key, manifest)
    production = json.loads(store.get(rollback.predecessor.manifest_key))
    production["artifacts"] = manifest["artifacts"]
    production["production_promotion"]["source_candidate_manifest_sha256"] = sha256_bytes(changed)
    production_bytes = _put(store, rollback.predecessor.manifest_key, production)
    pointer = json.loads(rollback.predecessor.raw)
    pointer["manifest_sha256"] = sha256_bytes(production_bytes)
    raw = pretty_json_bytes(pointer)
    tampered = replace(
        rollback,
        predecessor=replace(
            rollback.predecessor,
            raw=raw,
            sha256=sha256_bytes(raw),
            manifest_sha256=sha256_bytes(production_bytes),
        ),
    )
    with pytest.raises(IntegrityError, match="required artifact family missing"):
        execute_rollback(
            store=store,
            plan=tampered,
            verify_predecessor_qdrant=_predecessor_qdrant,
        )
