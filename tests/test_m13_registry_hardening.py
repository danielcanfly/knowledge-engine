from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine import m13_contracts as contracts
from knowledge_engine import m13_registry as registry
from knowledge_engine.storage import FileObjectStore

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
PRODUCTION = contracts.ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)


def _record() -> contracts.M13BatchRecord:
    return contracts.M13BatchRecord.from_seed(
        contracts.M13BatchSeed(
            source_repository="danielcanfly/knowledge-source",
            source_commit_sha=SOURCE_SHA,
            production=PRODUCTION,
            requested_by="reviewer@example.com",
            requested_at="2026-07-09T08:00:00Z",
            purpose="M13.2 adversarial fixture",
        )
    )


def _source_review(record: contracts.M13BatchRecord) -> contracts.M13OperationResult:
    request = contracts.M13OperationRequest(
        kind="source_review",
        batch_id=record.batch_id,
        requested_by="operator@example.com",
        requested_at="2026-07-09T08:01:00Z",
        expected_previous_production=contracts.ExpectedPreviousProduction(
            production=PRODUCTION,
            checked_at="2026-07-09T08:01:00Z",
        ),
        artifact_names=("m13/evidence/adversarial-source-review.json",),
    )
    return contracts.M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at="2026-07-09T08:02:00Z",
        evidence_refs=("m13/evidence/adversarial-source-review.json",),
    )


def test_original_registration_replays_after_batch_progress(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record()
    registered = registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at="2026-07-09T08:00:30Z",
    )
    operation = registry.record_operation_result(
        store,
        _source_review(record),
        expected_registry_version=registered.registry_version,
    )
    transitioned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at="2026-07-09T08:03:00Z",
        expected_registry_version=operation.registry_version,
        expected_batch_version=1,
    )
    replay = registry.register_batch(
        store,
        record,
        actor="another@example.com",
        registered_at="2026-07-09T08:04:00Z",
    )
    assert replay.idempotent is True
    assert replay.state == "reviewing_source"
    assert replay.batch_version == transitioned.batch_version
    assert replay.registry_version == transitioned.registry_version


def test_historical_snapshot_tampering_is_detected(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record()
    registered = registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at="2026-07-09T08:10:00Z",
    )
    operation = registry.record_operation_result(
        store,
        _source_review(record),
        expected_registry_version=registered.registry_version,
    )
    registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at="2026-07-09T08:11:00Z",
        expected_registry_version=operation.registry_version,
        expected_batch_version=1,
    )
    current = registry.get_batch(store, record.batch_id)
    first_event = json.loads(store.get(current["event_keys"][0]))
    historical_key = first_event["snapshot_key"]
    historical = json.loads(store.get(historical_key))
    historical["record"]["state"] = "abandoned"
    store.put(
        historical_key,
        json.dumps(historical).encode(),
        content_type="application/json",
    )
    with pytest.raises(registry.M13RegistryError) as failure:
        registry.get_batch(store, record.batch_id)
    assert failure.value.code == "M13_EVENT_CHAIN_INVALID"


def test_planner_rejects_invalid_candidate_channel_input(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    record = _record()
    registered = registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at="2026-07-09T08:20:00Z",
    )
    operation = registry.record_operation_result(
        store,
        _source_review(record),
        expected_registry_version=registered.registry_version,
    )
    registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at="2026-07-09T08:21:00Z",
        expected_registry_version=operation.registry_version,
        expected_batch_version=1,
    )
    plan = registry.plan_batch_lifecycle(
        snapshot=registry.get_batch(store, record.batch_id),
        observed_production=PRODUCTION,
        actor="operator@example.com",
        planned_at="2026-07-09T08:22:00Z",
        proposed_candidate_channel="INVALID CHANNEL",
    )
    assert plan.ready is False
    assert "candidate_channel_invalid" in plan.blockers
