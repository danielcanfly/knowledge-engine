from __future__ import annotations

import ast
from pathlib import Path

import pytest

from knowledge_engine import m13_contracts as contracts
from knowledge_engine import m13_coordinator as coordinator
from knowledge_engine import m13_registry as registry
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/knowledge_engine/m13_coordinator.py"
SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION = contracts.ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)


def _record(index: int) -> contracts.M13BatchRecord:
    seed = contracts.M13BatchSeed(
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=SOURCE_SHA,
        production=PRODUCTION,
        requested_by="reviewer@example.com",
        requested_at=f"2026-07-09T09:{index:02d}:00Z",
        purpose=f"M13.3 fixture batch {index}",
    )
    return contracts.M13BatchRecord.from_seed(seed)


def _operation_result(
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
            production=PRODUCTION,
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


def _register(store: FileObjectStore, record: contracts.M13BatchRecord, minute: int):
    return registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at=f"2026-07-09T10:{minute:02d}:00Z",
    )


def _advance_to_reviewing(
    store: FileObjectStore,
    record: contracts.M13BatchRecord,
    minute: int,
):
    registered = _register(store, record, minute)
    result = _operation_result(
        record=record,
        kind="source_review",
        requested_at=f"2026-07-09T10:{minute:02d}:10Z",
        result_at=f"2026-07-09T10:{minute:02d}:20Z",
    )
    recorded = registry.record_operation_result(
        store,
        result,
        expected_registry_version=registered.registry_version,
    )
    transitioned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T10:{minute:02d}:30Z",
        expected_registry_version=recorded.registry_version,
        expected_batch_version=1,
    )
    return transitioned


def _advance_to_awaiting(
    store: FileObjectStore,
    record: contracts.M13BatchRecord,
    minute: int,
):
    reviewing = _advance_to_reviewing(store, record, minute)
    candidate = _operation_result(
        record=record,
        kind="candidate_build",
        requested_at=f"2026-07-09T10:{minute:02d}:35Z",
        result_at=f"2026-07-09T10:{minute:02d}:40Z",
    )
    candidate_recorded = registry.record_operation_result(
        store,
        candidate,
        expected_registry_version=reviewing.registry_version,
    )
    candidate_ready = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="candidate_ready",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T10:{minute:02d}:45Z",
        expected_registry_version=candidate_recorded.registry_version,
        expected_batch_version=2,
        candidate_channel=f"candidate-m13-three-{minute}",
    )
    comparison = _operation_result(
        record=record,
        kind="release_comparison",
        requested_at=f"2026-07-09T10:{minute:02d}:46Z",
        result_at=f"2026-07-09T10:{minute:02d}:47Z",
    )
    comparison_recorded = registry.record_operation_result(
        store,
        comparison,
        expected_registry_version=candidate_ready.registry_version,
    )
    return registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="awaiting_production_slot",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T10:{minute:02d}:48Z",
        expected_registry_version=comparison_recorded.registry_version,
        expected_batch_version=3,
    )


def _candidate_request(
    record: contracts.M13BatchRecord,
    requested_at: str,
) -> contracts.M13OperationRequest:
    return contracts.M13OperationRequest(
        kind="candidate_build",
        batch_id=record.batch_id,
        requested_by="builder@example.com",
        requested_at=requested_at,
        expected_previous_production=contracts.ExpectedPreviousProduction(
            production=PRODUCTION,
            checked_at=requested_at,
        ),
        artifact_names=(f"m13/candidate/{record.batch_id}.json",),
    )


def _promotion_operation_id(record: contracts.M13BatchRecord, requested_at: str) -> str:
    request = contracts.M13OperationRequest(
        kind="production_promotion",
        batch_id=record.batch_id,
        requested_by="promoter@example.com",
        requested_at=requested_at,
        expected_previous_production=contracts.ExpectedPreviousProduction(
            production=PRODUCTION,
            checked_at=requested_at,
        ),
        planning_only=False,
        requires_production_slot=True,
    )
    return request.operation_id()


def test_candidate_slots_are_bounded_replayable_and_recoverable(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    records = [_record(index) for index in (1, 2, 3)]
    for index, record in enumerate(records, 1):
        _advance_to_reviewing(store, record, index)
    first = coordinator.acquire_candidate_slot(
        store,
        request=_candidate_request(records[0], "2026-07-09T11:00:00Z"),
        holder_id="builder-1",
        acquired_at="2026-07-09T11:00:00Z",
        expires_at="2026-07-09T11:10:00Z",
        capacity=2,
    )
    second = coordinator.acquire_candidate_slot(
        store,
        request=_candidate_request(records[1], "2026-07-09T11:01:00Z"),
        holder_id="builder-2",
        acquired_at="2026-07-09T11:01:00Z",
        expires_at="2026-07-09T11:11:00Z",
        capacity=2,
    )
    replay = coordinator.acquire_candidate_slot(
        store,
        request=_candidate_request(records[0], "2026-07-09T11:00:00Z"),
        holder_id="builder-1",
        acquired_at="2026-07-09T11:00:00Z",
        expires_at="2026-07-09T11:10:00Z",
        capacity=2,
    )
    assert {first.slot_number, second.slot_number} == {1, 2}
    assert replay.idempotent is True
    with pytest.raises(coordinator.M13CoordinatorError) as exhausted:
        coordinator.acquire_candidate_slot(
            store,
            request=_candidate_request(records[2], "2026-07-09T11:02:00Z"),
            holder_id="builder-3",
            acquired_at="2026-07-09T11:02:00Z",
            expires_at="2026-07-09T11:12:00Z",
            capacity=2,
        )
    assert exhausted.value.code == "M13_CANDIDATE_CAPACITY_EXHAUSTED"
    recovered = coordinator.recover_expired_candidate_slots(
        store,
        recovered_at="2026-07-09T11:10:30Z",
        actor="recovery@example.com",
        capacity=2,
    )
    assert recovered["slot_ids"] == [first.slot_id]
    third = coordinator.acquire_candidate_slot(
        store,
        request=_candidate_request(records[2], "2026-07-09T11:10:40Z"),
        holder_id="builder-3",
        acquired_at="2026-07-09T11:10:40Z",
        expires_at="2026-07-09T11:20:00Z",
        capacity=2,
    )
    assert third.slot_number == first.slot_number
    released = coordinator.release_candidate_slot(
        store,
        slot_id=second.slot_id,
        holder_id="builder-2",
        released_at="2026-07-09T11:12:00Z",
        reason="candidate build completed",
        capacity=2,
    )
    assert released["slot_id"] == second.slot_id


def test_exactly_one_production_lease_and_explicit_recovery(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    first_record = _record(4)
    second_record = _record(5)
    first_ready = _advance_to_awaiting(store, first_record, 10)
    second_ready = _advance_to_awaiting(store, second_record, 20)
    first = coordinator.acquire_production_lease(
        store,
        batch_id=first_record.batch_id,
        operation_id=_promotion_operation_id(first_record, "2026-07-09T12:00:00Z"),
        holder_id="promoter-1",
        acquired_at="2026-07-09T12:00:00Z",
        expires_at="2026-07-09T12:10:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=first_ready.registry_version,
        expected_batch_version=first_ready.batch_version,
    )
    with pytest.raises(coordinator.M13CoordinatorError) as busy:
        coordinator.acquire_production_lease(
            store,
            batch_id=second_record.batch_id,
            operation_id=_promotion_operation_id(second_record, "2026-07-09T12:01:00Z"),
            holder_id="promoter-2",
            acquired_at="2026-07-09T12:01:00Z",
            expires_at="2026-07-09T12:11:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=second_ready.registry_version,
            expected_batch_version=second_ready.batch_version,
        )
    assert busy.value.code == "M13_PRODUCTION_LEASE_BUSY"
    with pytest.raises(coordinator.M13CoordinatorError) as recovery_required:
        coordinator.acquire_production_lease(
            store,
            batch_id=second_record.batch_id,
            operation_id=_promotion_operation_id(second_record, "2026-07-09T12:10:01Z"),
            holder_id="promoter-2",
            acquired_at="2026-07-09T12:10:01Z",
            expires_at="2026-07-09T12:20:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=second_ready.registry_version,
            expected_batch_version=second_ready.batch_version,
        )
    assert recovery_required.value.code == "M13_PRODUCTION_RECOVERY_REQUIRED"
    recovered = coordinator.recover_expired_production_lease(
        store,
        recovered_at="2026-07-09T12:10:02Z",
        actor="recovery@example.com",
        reason="holder heartbeat expired before permit",
    )
    assert recovered.state == "recovered"
    second = coordinator.acquire_production_lease(
        store,
        batch_id=second_record.batch_id,
        operation_id=_promotion_operation_id(second_record, "2026-07-09T12:10:03Z"),
        holder_id="promoter-2",
        acquired_at="2026-07-09T12:10:03Z",
        expires_at="2026-07-09T12:20:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=second_ready.registry_version,
        expected_batch_version=second_ready.batch_version,
    )
    assert second.generation == first.generation + 1
    assert second.fencing_token != first.fencing_token
    with pytest.raises(coordinator.M13CoordinatorError) as stale_fence:
        coordinator.renew_production_lease(
            store,
            lease_id=first.lease_id,
            holder_id="promoter-1",
            fencing_token=first.fencing_token,
            renewed_at="2026-07-09T12:11:00Z",
            expires_at="2026-07-09T12:21:00Z",
        )
    assert stale_fence.value.code == "M13_PRODUCTION_LEASE_STALE"


def test_permit_transition_and_commit_authorization_are_fenced(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record(6)
    ready = _advance_to_awaiting(store, record, 30)
    operation_id = _promotion_operation_id(record, "2026-07-09T13:00:00Z")
    lease = coordinator.acquire_production_lease(
        store,
        batch_id=record.batch_id,
        operation_id=operation_id,
        holder_id="promoter-1",
        acquired_at="2026-07-09T13:00:00Z",
        expires_at="2026-07-09T13:20:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=ready.registry_version,
        expected_batch_version=ready.batch_version,
    )
    permit = coordinator.issue_production_mutation_permit(
        store,
        lease_id=lease.lease_id,
        holder_id=lease.holder_id,
        fencing_token=lease.fencing_token,
        issued_at="2026-07-09T13:01:00Z",
        observed_production=PRODUCTION,
    )
    transitioned = coordinator.transition_batch_to_promoting(
        store,
        permit=permit,
        actor="promoter@example.com",
        occurred_at="2026-07-09T13:02:00Z",
        observed_production=PRODUCTION,
    )
    assert transitioned.state == "promoting"
    with pytest.raises(registry.M13RegistryError) as bypass:
        registry.transition_batch(
            store,
            batch_id=record.batch_id,
            target_state="closed",
            actor="bypass@example.com",
            occurred_at="2026-07-09T13:02:30Z",
            expected_registry_version=transitioned.registry_version,
            expected_batch_version=transitioned.batch_version,
        )
    assert bypass.value.code == "M13_BATCH_TRANSITION_INVALID"
    authorization = coordinator.authorize_production_commit(
        store,
        permit=permit,
        holder_id=lease.holder_id,
        authorized_at="2026-07-09T13:03:00Z",
        observed_production=PRODUCTION,
    )
    coordinator.validate_commit_authorization(
        store,
        authorization=authorization,
        holder_id=lease.holder_id,
        checked_at="2026-07-09T13:04:00Z",
        observed_production=PRODUCTION,
    )
    stale_production = contracts.ProductionIdentity(
        release_id=PRODUCTION.release_id,
        manifest_sha256=PRODUCTION.manifest_sha256,
        pointer_sha256="f" * 64,
    )
    with pytest.raises(coordinator.M13CoordinatorError) as drift:
        coordinator.validate_commit_authorization(
            store,
            authorization=authorization,
            holder_id=lease.holder_id,
            checked_at="2026-07-09T13:05:00Z",
            observed_production=stale_production,
        )
    assert drift.value.code == "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE"
    resulting = contracts.ProductionIdentity(
        release_id="20260709T130600Z-aaaaaaaaaaaa",
        manifest_sha256="b" * 64,
        pointer_sha256="c" * 64,
    )
    completed = coordinator.complete_production_mutation(
        store,
        authorization=authorization,
        holder_id=lease.holder_id,
        completed_at="2026-07-09T13:06:00Z",
        resulting_production=resulting,
        evidence_refs=("m13/evidence/promotion.json", "m13/evidence/ledger.json"),
    )
    assert completed.state == "released"
    assert completed.completion_key is not None


def test_commit_authorized_expiry_requires_manual_reconciliation(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record(7)
    ready = _advance_to_awaiting(store, record, 40)
    lease = coordinator.acquire_production_lease(
        store,
        batch_id=record.batch_id,
        operation_id=_promotion_operation_id(record, "2026-07-09T14:00:00Z"),
        holder_id="promoter-1",
        acquired_at="2026-07-09T14:00:00Z",
        expires_at="2026-07-09T14:05:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=ready.registry_version,
        expected_batch_version=ready.batch_version,
    )
    permit = coordinator.issue_production_mutation_permit(
        store,
        lease_id=lease.lease_id,
        holder_id=lease.holder_id,
        fencing_token=lease.fencing_token,
        issued_at="2026-07-09T14:01:00Z",
        observed_production=PRODUCTION,
    )
    coordinator.transition_batch_to_promoting(
        store,
        permit=permit,
        actor="promoter@example.com",
        occurred_at="2026-07-09T14:02:00Z",
        observed_production=PRODUCTION,
    )
    coordinator.authorize_production_commit(
        store,
        permit=permit,
        holder_id=lease.holder_id,
        authorized_at="2026-07-09T14:03:00Z",
        observed_production=PRODUCTION,
    )
    with pytest.raises(coordinator.M13CoordinatorError) as manual:
        coordinator.recover_expired_production_lease(
            store,
            recovered_at="2026-07-09T14:05:01Z",
            actor="recovery@example.com",
            reason="lease expired after commit authorization",
        )
    assert manual.value.code == "M13_PRODUCTION_MANUAL_RECONCILIATION_REQUIRED"


def test_wrong_holder_stale_versions_and_production_drift_fail_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record(8)
    ready = _advance_to_awaiting(store, record, 50)
    with pytest.raises(coordinator.M13CoordinatorError) as stale_registry:
        coordinator.acquire_production_lease(
            store,
            batch_id=record.batch_id,
            operation_id=_promotion_operation_id(record, "2026-07-09T15:00:00Z"),
            holder_id="promoter-1",
            acquired_at="2026-07-09T15:00:00Z",
            expires_at="2026-07-09T15:10:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=ready.registry_version - 1,
            expected_batch_version=ready.batch_version,
        )
    assert stale_registry.value.code == "M13_PRODUCTION_REGISTRY_VERSION_STALE"
    drifted = contracts.ProductionIdentity(
        release_id=PRODUCTION.release_id,
        manifest_sha256=PRODUCTION.manifest_sha256,
        pointer_sha256="e" * 64,
    )
    with pytest.raises(coordinator.M13CoordinatorError) as stale_production:
        coordinator.acquire_production_lease(
            store,
            batch_id=record.batch_id,
            operation_id=_promotion_operation_id(record, "2026-07-09T15:01:00Z"),
            holder_id="promoter-1",
            acquired_at="2026-07-09T15:01:00Z",
            expires_at="2026-07-09T15:11:00Z",
            observed_production=drifted,
            expected_registry_version=ready.registry_version,
            expected_batch_version=ready.batch_version,
        )
    assert stale_production.value.code == "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE"
    lease = coordinator.acquire_production_lease(
        store,
        batch_id=record.batch_id,
        operation_id=_promotion_operation_id(record, "2026-07-09T15:02:00Z"),
        holder_id="promoter-1",
        acquired_at="2026-07-09T15:02:00Z",
        expires_at="2026-07-09T15:12:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=ready.registry_version,
        expected_batch_version=ready.batch_version,
    )
    with pytest.raises(coordinator.M13CoordinatorError) as holder:
        coordinator.issue_production_mutation_permit(
            store,
            lease_id=lease.lease_id,
            holder_id="promoter-2",
            fencing_token=lease.fencing_token,
            issued_at="2026-07-09T15:03:00Z",
            observed_production=PRODUCTION,
        )
    assert holder.value.code == "M13_PRODUCTION_HOLDER_MISMATCH"


def test_coordinator_module_has_no_network_or_direct_release_surface() -> None:
    forbidden_imports = {"boto3", "httpx", "requests", "socket", "subprocess"}
    forbidden_calls = {"create_release", "promote_release", "rollback_release", "delete"}
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
