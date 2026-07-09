from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from knowledge_engine import m13_contracts as contracts
from knowledge_engine import m13_registry as registry
from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/knowledge_engine/m13_registry.py"
SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION = contracts.ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)


class ConflictOnceStore(FileObjectStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.conflict_once = True

    def put(self, key: str, data: bytes, **kwargs):  # type: ignore[no-untyped-def]
        if key == registry.REGISTRY_HEAD_KEY and self.conflict_once:
            self.conflict_once = False
            raise ReleaseConflictError("fixture conflict")
        return super().put(key, data, **kwargs)


def _record(suffix: str = "a") -> contracts.M13BatchRecord:
    seed = contracts.M13BatchSeed(
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=SOURCE_SHA,
        production=PRODUCTION,
        requested_by="reviewer@example.com",
        requested_at=f"2026-07-09T06:0{suffix}:00Z",
        purpose=f"M13.2 fixture batch {suffix}",
    )
    return contracts.M13BatchRecord.from_seed(seed)


def _completed_result(
    *,
    record: contracts.M13BatchRecord,
    kind: contracts.OperationKind,
    requested_at: str,
    result_at: str,
) -> contracts.M13OperationResult:
    request = contracts.M13OperationRequest(
        kind=kind,
        batch_id=record.batch_id,
        requested_by="operator@example.com",
        requested_at=requested_at,
        expected_previous_production=contracts.ExpectedPreviousProduction(
            production=record.seed.production,
            checked_at=requested_at,
        ),
        artifact_names=(f"m13/evidence/{record.batch_id}/{kind}.json",),
    )
    return contracts.M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=result_at,
        evidence_refs=(f"m13/evidence/{record.batch_id}/{kind}.json",),
    )


def _head(store: FileObjectStore) -> dict[str, object]:
    return json.loads(store.get(registry.REGISTRY_HEAD_KEY))


def test_register_replay_list_and_status_are_deterministic(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record_b = _record("2")
    record_a = _record("1")
    first = registry.register_batch(
        store, record_b, actor="operator@example.com", registered_at="2026-07-09T06:10:00Z"
    )
    second = registry.register_batch(
        store, record_a, actor="operator@example.com", registered_at="2026-07-09T06:11:00Z"
    )
    replay = registry.register_batch(
        store, record_b, actor="other@example.com", registered_at="2026-07-09T06:12:00Z"
    )
    assert first.idempotent is False
    assert second.registry_version == 2
    assert replay.idempotent is True
    assert replay.registry_version == 2
    listed = registry.list_batches(store)
    assert [item["batch_id"] for item in listed] == sorted(
        [record_a.batch_id, record_b.batch_id]
    )
    status = registry.registry_status(store)
    assert status["batch_count"] == 2
    assert status["state_counts"] == {"planned": 2}
    snapshot = registry.get_batch(store, record_a.batch_id)
    assert snapshot["batch_version"] == 1
    assert registry.verify_registry_event(
        json.loads(store.get(snapshot["event_keys"][0]))
    )


def test_registry_conflict_leaves_replayable_immutable_evidence(tmp_path: Path) -> None:
    store = ConflictOnceStore(tmp_path / "store")
    record = _record("3")
    with pytest.raises(registry.M13RegistryError) as failure:
        registry.register_batch(
            store,
            record,
            actor="operator@example.com",
            registered_at="2026-07-09T06:13:00Z",
        )
    assert failure.value.code == "M13_REGISTRY_CONFLICT"
    result = registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at="2026-07-09T06:13:00Z",
    )
    assert result.registry_version == 1
    assert result.idempotent is True


def test_full_planning_path_to_production_slot_boundary(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record("4")
    registered = registry.register_batch(
        store, record, actor="operator@example.com", registered_at="2026-07-09T06:20:00Z"
    )
    snapshot = registry.get_batch(store, record.batch_id)
    plan = registry.plan_batch_lifecycle(
        snapshot=snapshot,
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T06:21:00Z",
    )
    assert plan.ready is True
    assert plan.next_action == "run_source_review"
    assert plan.operation_request is not None

    source_review = _completed_result(
        record=record,
        kind="source_review",
        requested_at="2026-07-09T06:21:00Z",
        result_at="2026-07-09T06:22:00Z",
    )
    source_recorded = registry.record_operation_result(
        store, source_review, expected_registry_version=registered.registry_version
    )
    assert source_recorded.operation_id == source_review.operation_id
    replay = registry.record_operation_result(
        store, source_review, expected_registry_version=0
    )
    assert replay.idempotent is True

    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T06:23:00Z",
    )
    assert plan.next_action == "transition_to_reviewing_source"
    assert plan.ready is True
    reviewing = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at="2026-07-09T06:24:00Z",
        expected_registry_version=source_recorded.registry_version,
        expected_batch_version=1,
    )
    assert reviewing.state == "reviewing_source"

    candidate_build = _completed_result(
        record=record,
        kind="candidate_build",
        requested_at="2026-07-09T06:25:00Z",
        result_at="2026-07-09T06:26:00Z",
    )
    candidate_recorded = registry.record_operation_result(
        store, candidate_build, expected_registry_version=reviewing.registry_version
    )
    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T06:27:00Z",
        proposed_candidate_channel="candidate-m13-batch-four",
    )
    assert plan.next_action == "transition_to_candidate_ready"
    assert plan.ready is True
    candidate_ready = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="candidate_ready",
        actor="operator@example.com",
        occurred_at="2026-07-09T06:28:00Z",
        expected_registry_version=candidate_recorded.registry_version,
        expected_batch_version=2,
        candidate_channel="candidate-m13-batch-four",
    )
    assert candidate_ready.state == "candidate_ready"

    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T06:29:00Z",
    )
    assert plan.next_action == "run_release_comparison"
    comparison = _completed_result(
        record=record,
        kind="release_comparison",
        requested_at="2026-07-09T06:29:00Z",
        result_at="2026-07-09T06:30:00Z",
    )
    comparison_recorded = registry.record_operation_result(
        store, comparison, expected_registry_version=candidate_ready.registry_version
    )
    awaiting = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="awaiting_production_slot",
        actor="operator@example.com",
        occurred_at="2026-07-09T06:31:00Z",
        expected_registry_version=comparison_recorded.registry_version,
        expected_batch_version=3,
    )
    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T06:32:00Z",
    )
    assert awaiting.state == "awaiting_production_slot"
    assert plan.ready is False
    assert plan.operation_request is None
    assert plan.blockers == ("m13_3_coordinator_required",)
    assert plan.next_action == "acquire_production_slot"


def test_transition_prerequisites_and_versions_fail_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record("5")
    registered = registry.register_batch(
        store, record, actor="operator@example.com", registered_at="2026-07-09T06:40:00Z"
    )
    with pytest.raises(registry.M13RegistryError) as missing:
        registry.transition_batch(
            store,
            batch_id=record.batch_id,
            target_state="reviewing_source",
            actor="operator@example.com",
            occurred_at="2026-07-09T06:41:00Z",
            expected_registry_version=registered.registry_version,
            expected_batch_version=1,
        )
    assert missing.value.code == "M13_SOURCE_REVIEW_EVIDENCE_MISSING"
    with pytest.raises(registry.M13RegistryError) as stale:
        registry.transition_batch(
            store,
            batch_id=record.batch_id,
            target_state="abandoned",
            actor="operator@example.com",
            occurred_at="2026-07-09T06:42:00Z",
            expected_registry_version=0,
            expected_batch_version=1,
        )
    assert stale.value.code == "M13_REGISTRY_VERSION_STALE"


def test_planner_blocks_stale_production_and_missing_candidate_input(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record("6")
    registry.register_batch(
        store, record, actor="operator@example.com", registered_at="2026-07-09T06:50:00Z"
    )
    stale_production = contracts.ProductionIdentity(
        release_id=PRODUCTION.release_id,
        manifest_sha256=PRODUCTION.manifest_sha256,
        pointer_sha256="f" * 64,
    )
    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=stale_production,
        actor="operator@example.com",
        planned_at="2026-07-09T06:51:00Z",
    )
    assert plan.ready is False
    assert plan.operation_request is None
    assert plan.stale_expected_previous is True
    assert "expected_previous_production_stale" in plan.blockers


def test_event_chain_tampering_and_terminal_operation_write_are_rejected(
    tmp_path: Path,
) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record("7")
    registered = registry.register_batch(
        store, record, actor="operator@example.com", registered_at="2026-07-09T07:00:00Z"
    )
    abandoned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="abandoned",
        actor="operator@example.com",
        occurred_at="2026-07-09T07:01:00Z",
        expected_registry_version=registered.registry_version,
        expected_batch_version=1,
    )
    operation = _completed_result(
        record=record,
        kind="source_review",
        requested_at="2026-07-09T07:02:00Z",
        result_at="2026-07-09T07:03:00Z",
    )
    with pytest.raises(registry.M13RegistryError) as terminal:
        registry.record_operation_result(
            store, operation, expected_registry_version=abandoned.registry_version
        )
    assert terminal.value.code == "M13_BATCH_TERMINAL"

    snapshot = registry.get_batch(store, record.batch_id)
    event_key = snapshot["event_keys"][0]
    bad = json.loads(store.get(event_key))
    bad["actor"] = "tampered@example.com"
    store.put(event_key, json.dumps(bad).encode(), content_type="application/json")
    with pytest.raises(registry.M13RegistryError) as tampered:
        registry.get_batch(store, record.batch_id)
    assert tampered.value.code == "M13_EVENT_CHAIN_INVALID"


def test_registry_module_has_no_network_or_production_surface() -> None:
    forbidden_imports = {"boto3", "httpx", "requests", "socket", "subprocess"}
    forbidden_calls = {"delete", "promote", "rollback"}
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert imported.isdisjoint(forbidden_imports)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(forbidden_calls)
