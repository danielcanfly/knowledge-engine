from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine import m13_registry as registry
from knowledge_engine.m13_contracts import (
    ExpectedPreviousProduction,
    M13BatchRecord,
    M13BatchSeed,
    M13OperationRequest,
    M13OperationResult,
    OperationKind,
    ProductionIdentity,
)
from knowledge_engine.m13_coordinator_v2 import acquire_production_lease
from knowledge_engine.m13_lifecycle_rules import (
    M13LifecycleError,
    abandon_batch,
    register_rebuild_batch,
    supersede_batches,
)
from knowledge_engine.storage import FileObjectStore

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION = ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)


def _record(
    index: int,
    *,
    source_sha: str = SOURCE_SHA,
    candidate_channel: str | None = None,
    supersedes: tuple[str, ...] = (),
    rebuilt_from: str | None = None,
) -> M13BatchRecord:
    seed = M13BatchSeed(
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha=source_sha,
        production=PRODUCTION,
        requested_by="reviewer@example.com",
        requested_at=f"2026-07-09T10:{index:02d}:00Z",
        purpose=f"M13.4 fixture batch {index}",
    )
    return M13BatchRecord.from_seed(
        seed,
        candidate_channel=candidate_channel,
        supersedes_batch_ids=supersedes,
        rebuilt_from_batch_id=rebuilt_from,
    )


def _operation_result(
    *,
    record: M13BatchRecord,
    kind: OperationKind,
    requested_at: str,
    result_at: str,
) -> M13OperationResult:
    request = M13OperationRequest(
        kind=kind,
        batch_id=record.batch_id,
        requested_by="operator@example.com",
        requested_at=requested_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=PRODUCTION,
            checked_at=requested_at,
        ),
        artifact_names=(f"m13/evidence/{record.batch_id}/{kind}.json",),
    )
    return M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=result_at,
        evidence_refs=(f"m13/evidence/{record.batch_id}/{kind}.json",),
    )


def _register(store: FileObjectStore, record: M13BatchRecord, minute: int):
    return registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at=f"2026-07-09T11:{minute:02d}:00Z",
    )


def _advance_to_reviewing(
    store: FileObjectStore,
    record: M13BatchRecord,
    minute: int,
):
    registered = _register(store, record, minute)
    review = _operation_result(
        record=record,
        kind="source_review",
        requested_at=f"2026-07-09T11:{minute:02d}:10Z",
        result_at=f"2026-07-09T11:{minute:02d}:20Z",
    )
    recorded = registry.record_operation_result(
        store,
        review,
        expected_registry_version=registered.registry_version,
    )
    return registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T11:{minute:02d}:30Z",
        expected_registry_version=recorded.registry_version,
        expected_batch_version=1,
    )


def _advance_to_candidate_ready(
    store: FileObjectStore,
    record: M13BatchRecord,
    minute: int,
):
    reviewing = _advance_to_reviewing(store, record, minute)
    candidate = _operation_result(
        record=record,
        kind="candidate_build",
        requested_at=f"2026-07-09T11:{minute:02d}:35Z",
        result_at=f"2026-07-09T11:{minute:02d}:40Z",
    )
    recorded = registry.record_operation_result(
        store,
        candidate,
        expected_registry_version=reviewing.registry_version,
    )
    return registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="candidate_ready",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T11:{minute:02d}:45Z",
        expected_registry_version=recorded.registry_version,
        expected_batch_version=2,
        candidate_channel=f"candidate-m13-four-{minute}",
    )


def _advance_to_awaiting(
    store: FileObjectStore,
    record: M13BatchRecord,
    minute: int,
):
    ready = _advance_to_candidate_ready(store, record, minute)
    comparison = _operation_result(
        record=record,
        kind="release_comparison",
        requested_at=f"2026-07-09T11:{minute:02d}:46Z",
        result_at=f"2026-07-09T11:{minute:02d}:47Z",
    )
    recorded = registry.record_operation_result(
        store,
        comparison,
        expected_registry_version=ready.registry_version,
    )
    return registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="awaiting_production_slot",
        actor="operator@example.com",
        occurred_at=f"2026-07-09T11:{minute:02d}:48Z",
        expected_registry_version=recorded.registry_version,
        expected_batch_version=3,
    )


def _snapshot(store: FileObjectStore, batch_id: str) -> dict:
    return registry.get_batch(store, batch_id)


def _promotion_operation_id(record: M13BatchRecord, requested_at: str) -> str:
    request = M13OperationRequest(
        kind="production_promotion",
        batch_id=record.batch_id,
        requested_by="promoter@example.com",
        requested_at=requested_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=PRODUCTION,
            checked_at=requested_at,
        ),
        planning_only=False,
        requires_production_slot=True,
    )
    return request.operation_id()


def test_abandonment_is_reasoned_immutable_and_replayable(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record(1)
    reviewing = _advance_to_reviewing(store, record, 1)
    result = abandon_batch(
        store,
        batch_id=record.batch_id,
        reason="operator_cancelled",
        rationale="The source review was withdrawn before candidate build.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:00:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=reviewing.registry_version,
        expected_batch_version=reviewing.batch_version,
    )
    replay = abandon_batch(
        store,
        batch_id=record.batch_id,
        reason="operator_cancelled",
        rationale="The source review was withdrawn before candidate build.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:00:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=reviewing.registry_version,
        expected_batch_version=reviewing.batch_version,
    )
    assert result.states[record.batch_id] == "abandoned"
    assert replay.idempotent is True
    assert store.head(result.evidence_key) is not None
    assert _snapshot(store, record.batch_id)["record"]["candidate_channel"] is None


def test_abandonment_rejects_stale_version_and_terminal_state(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record(2)
    registered = _register(store, record, 2)
    with pytest.raises(M13LifecycleError) as stale:
        abandon_batch(
            store,
            batch_id=record.batch_id,
            reason="operator_cancelled",
            rationale="Stale request.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:01:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=registered.registry_version - 1,
            expected_batch_version=registered.batch_version,
        )
    assert stale.value.code == "M13_LIFECYCLE_REGISTRY_VERSION_STALE"
    abandoned = abandon_batch(
        store,
        batch_id=record.batch_id,
        reason="operator_cancelled",
        rationale="Stop the batch.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:02:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=registered.registry_version,
        expected_batch_version=registered.batch_version,
    )
    with pytest.raises(M13LifecycleError) as terminal:
        abandon_batch(
            store,
            batch_id=record.batch_id,
            reason="failed_review",
            rationale="A different terminal action is forbidden.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:03:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=abandoned.registry_version,
            expected_batch_version=2,
        )
    assert terminal.value.code == "M13_LIFECYCLE_ABANDON_STATE_INVALID"


def test_supersession_is_atomic_and_replayable(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    first = _record(3)
    second = _record(4)
    first_ready = _advance_to_reviewing(store, first, 3)
    second_ready = _advance_to_candidate_ready(store, second, 4)
    target_ids = tuple(sorted((first.batch_id, second.batch_id)))
    new_record = _record(5, supersedes=target_ids)
    current_version = registry.registry_status(store)["registry_version"]
    result = supersede_batches(
        store,
        new_record=new_record,
        expected_batch_versions={
            first.batch_id: first_ready.batch_version,
            second.batch_id: second_ready.batch_version,
        },
        rationale="A consolidated source review replaces both pending batches.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:10:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=current_version,
    )
    replay = supersede_batches(
        store,
        new_record=new_record,
        expected_batch_versions={
            first.batch_id: first_ready.batch_version,
            second.batch_id: second_ready.batch_version,
        },
        rationale="A consolidated source review replaces both pending batches.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:10:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=current_version,
    )
    assert result.states[new_record.batch_id] == "planned"
    assert result.states[first.batch_id] == "abandoned"
    assert result.states[second.batch_id] == "abandoned"
    assert replay.idempotent is True
    assert len(set(result.snapshot_keys.values())) == 3
    assert store.head(result.evidence_key) is not None


def test_supersession_rejects_cycle_and_candidate_channel_reuse(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    future = _record(6)
    target = _record(7, supersedes=(future.batch_id,))
    target_registered = _register(store, target, 7)
    cyclic = M13BatchRecord.from_seed(
        future.seed,
        supersedes_batch_ids=(target.batch_id,),
    )
    with pytest.raises(M13LifecycleError) as cycle:
        supersede_batches(
            store,
            new_record=cyclic,
            expected_batch_versions={target.batch_id: target_registered.batch_version},
            rationale="This would create a cycle.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:20:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=target_registered.registry_version,
        )
    assert cycle.value.code == "M13_LIFECYCLE_SUPERSESSION_CYCLE"

    owner = _record(8, candidate_channel="candidate-m13-four-reserved")
    owner_registered = _register(store, owner, 8)
    replacement = _record(
        9,
        candidate_channel="candidate-m13-four-reserved",
        supersedes=(owner.batch_id,),
    )
    with pytest.raises(M13LifecycleError) as reused:
        supersede_batches(
            store,
            new_record=replacement,
            expected_batch_versions={owner.batch_id: owner_registered.batch_version},
            rationale="Candidate channels cannot be reused.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:21:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=owner_registered.registry_version,
        )
    assert reused.value.code == "M13_LIFECYCLE_CANDIDATE_CHANNEL_REUSED"


def test_rebuild_requires_terminal_candidate_ancestry_and_new_channel(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    ancestor = _record(10)
    ready = _advance_to_candidate_ready(store, ancestor, 10)
    abandoned = abandon_batch(
        store,
        batch_id=ancestor.batch_id,
        reason="rebuild_requested",
        rationale="Candidate bytes are invalid and require a deterministic rebuild.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:30:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=ready.registry_version,
        expected_batch_version=ready.batch_version,
    )
    rebuilt = _record(
        11,
        candidate_channel="candidate-m13-four-rebuild-11",
        supersedes=(ancestor.batch_id,),
        rebuilt_from=ancestor.batch_id,
    )
    result = register_rebuild_batch(
        store,
        new_record=rebuilt,
        rationale="Rebuild from the same source and production baseline.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:31:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=abandoned.registry_version,
        expected_ancestor_batch_version=abandoned.states and 5,
    )
    replay = register_rebuild_batch(
        store,
        new_record=rebuilt,
        rationale="Rebuild from the same source and production baseline.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:31:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=abandoned.registry_version,
        expected_ancestor_batch_version=5,
    )
    assert result.states[rebuilt.batch_id] == "planned"
    assert replay.idempotent is True
    snapshot = _snapshot(store, rebuilt.batch_id)
    assert snapshot["record"]["rebuilt_from_batch_id"] == ancestor.batch_id
    assert snapshot["record"]["candidate_channel"] == "candidate-m13-four-rebuild-11"


def test_rebuild_rejects_nonterminal_ancestor_and_reused_channel(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    ancestor = _record(12)
    ready = _advance_to_candidate_ready(store, ancestor, 12)
    invalid = _record(
        13,
        candidate_channel="candidate-m13-four-rebuild-13",
        supersedes=(ancestor.batch_id,),
        rebuilt_from=ancestor.batch_id,
    )
    with pytest.raises(M13LifecycleError) as nonterminal:
        register_rebuild_batch(
            store,
            new_record=invalid,
            rationale="Ancestor is still active.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:40:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=ready.registry_version,
            expected_ancestor_batch_version=ready.batch_version,
        )
    assert nonterminal.value.code == "M13_LIFECYCLE_REBUILD_ANCESTOR_STATE_INVALID"

    abandoned = abandon_batch(
        store,
        batch_id=ancestor.batch_id,
        reason="rebuild_requested",
        rationale="Prepare rebuild ancestry.",
        actor="operator@example.com",
        occurred_at="2026-07-09T12:41:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=ready.registry_version,
        expected_batch_version=ready.batch_version,
    )
    reused = _record(
        14,
        candidate_channel="candidate-m13-four-12",
        supersedes=(ancestor.batch_id,),
        rebuilt_from=ancestor.batch_id,
    )
    with pytest.raises(M13LifecycleError) as channel:
        register_rebuild_batch(
            store,
            new_record=reused,
            rationale="The ancestor channel cannot be reused.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:42:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=abandoned.registry_version,
            expected_ancestor_batch_version=5,
        )
    assert channel.value.code in {
        "M13_LIFECYCLE_CANDIDATE_CHANNEL_REUSED",
        "M13_LIFECYCLE_REBUILD_CHANNEL_REUSED",
    }


def test_active_production_lease_blocks_lifecycle_mutation(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    production_batch = _record(15)
    awaiting = _advance_to_awaiting(store, production_batch, 15)
    other = _record(16)
    other_registered = _register(store, other, 16)
    current_version = registry.registry_status(store)["registry_version"]
    acquire_production_lease(
        store,
        batch_id=production_batch.batch_id,
        operation_id=_promotion_operation_id(
            production_batch,
            "2026-07-09T12:50:00Z",
        ),
        holder_id="promoter-1",
        acquired_at="2026-07-09T12:50:00Z",
        expires_at="2026-07-09T13:00:00Z",
        observed_production=PRODUCTION,
        expected_registry_version=current_version,
        expected_batch_version=awaiting.batch_version,
    )
    with pytest.raises(M13LifecycleError) as active:
        abandon_batch(
            store,
            batch_id=other.batch_id,
            reason="operator_cancelled",
            rationale="Lifecycle changes wait for the production lane.",
            actor="operator@example.com",
            occurred_at="2026-07-09T12:51:00Z",
            observed_production=PRODUCTION,
            expected_registry_version=current_version,
            expected_batch_version=other_registered.batch_version,
        )
    assert active.value.code == "M13_LIFECYCLE_PRODUCTION_LEASE_ACTIVE"
