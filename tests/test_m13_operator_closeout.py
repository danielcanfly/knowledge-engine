from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine import m13_contracts as contracts
from knowledge_engine import m13_coordinator_v2 as coordinator
from knowledge_engine import m13_registry as registry
from knowledge_engine.compiler_contract_v1 import json_bytes
from knowledge_engine.m13_cli import main as m13_main
from knowledge_engine.m13_closeout import M13CloseoutError, close_batch
from knowledge_engine.m13_operator import (
    integrity_audit,
    ledger_summary,
    operator_lookup,
    operator_status,
    stale_report,
)
from knowledge_engine.storage import FileObjectStore, sha256_bytes

SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"


def _put_json(store: FileObjectStore, key: str, value: dict[str, Any]) -> bytes:
    data = json_bytes(value)
    store.put(
        key,
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
    )
    return data


def _production_payload(
    *,
    release_id: str,
    marker: str,
    promoted_at: str,
) -> tuple[contracts.ProductionIdentity, str, bytes, bytes]:
    manifest_key = f"releases/{release_id}/manifest.json"
    manifest_bytes = json_bytes(
        {
            "schema_version": "test-release/v1",
            "release_id": release_id,
            "marker": marker,
        }
    )
    manifest_sha = sha256_bytes(manifest_bytes)
    pointer_bytes = json_bytes(
        {
            "schema_version": "1.0",
            "channel": "production",
            "release_id": release_id,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha,
            "promoted_at": promoted_at,
        }
    )
    identity = contracts.ProductionIdentity(
        release_id=release_id,
        manifest_sha256=manifest_sha,
        pointer_sha256=sha256_bytes(pointer_bytes),
    )
    return identity, manifest_key, manifest_bytes, pointer_bytes


def _install_production(
    store: FileObjectStore,
    *,
    release_id: str,
    marker: str,
    promoted_at: str,
) -> contracts.ProductionIdentity:
    identity, manifest_key, manifest_bytes, pointer_bytes = _production_payload(
        release_id=release_id,
        marker=marker,
        promoted_at=promoted_at,
    )
    store.put(
        manifest_key,
        manifest_bytes,
        content_type="application/json",
        sha256=identity.manifest_sha256,
    )
    store.put(
        "channels/production.json",
        pointer_bytes,
        content_type="application/json",
        sha256=identity.pointer_sha256,
    )
    return identity


def _record(
    production: contracts.ProductionIdentity,
    *,
    minute: int,
) -> contracts.M13BatchRecord:
    return contracts.M13BatchRecord.from_seed(
        contracts.M13BatchSeed(
            source_repository="danielcanfly/knowledge-source",
            source_commit_sha=SOURCE_SHA,
            production=production,
            requested_by="reviewer@example.com",
            requested_at=f"2026-07-09T14:{minute:02d}:00Z",
            purpose=f"M13.6 fixture {minute}",
        )
    )


def _operation_result(
    *,
    record: contracts.M13BatchRecord,
    production: contracts.ProductionIdentity,
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
            production=production,
            checked_at=requested_at,
        ),
        artifact_names=(f"m13/evidence/{record.batch_id}/{kind}.json",),
    )
    evidence_key = f"m13/evidence/{record.batch_id}/{kind}.json"
    return contracts.M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=result_at,
        evidence_refs=(evidence_key,),
    )


def _advance_to_awaiting(
    store: FileObjectStore,
    record: contracts.M13BatchRecord,
    production: contracts.ProductionIdentity,
) -> registry.RegistryMutationResult:
    registered = registry.register_batch(
        store,
        record,
        actor="operator@example.com",
        registered_at="2026-07-09T15:00:00Z",
    )
    source_review = _operation_result(
        record=record,
        production=production,
        kind="source_review",
        requested_at="2026-07-09T15:00:10Z",
        result_at="2026-07-09T15:00:20Z",
    )
    source_recorded = registry.record_operation_result(
        store,
        source_review,
        expected_registry_version=registered.registry_version,
    )
    reviewing = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="operator@example.com",
        occurred_at="2026-07-09T15:00:30Z",
        expected_registry_version=source_recorded.registry_version,
        expected_batch_version=1,
    )
    candidate = _operation_result(
        record=record,
        production=production,
        kind="candidate_build",
        requested_at="2026-07-09T15:00:40Z",
        result_at="2026-07-09T15:00:50Z",
    )
    candidate_recorded = registry.record_operation_result(
        store,
        candidate,
        expected_registry_version=reviewing.registry_version,
    )
    ready = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="candidate_ready",
        actor="operator@example.com",
        occurred_at="2026-07-09T15:01:00Z",
        expected_registry_version=candidate_recorded.registry_version,
        expected_batch_version=2,
        candidate_channel="candidate-m13-six-fixture",
    )
    comparison = _operation_result(
        record=record,
        production=production,
        kind="release_comparison",
        requested_at="2026-07-09T15:01:10Z",
        result_at="2026-07-09T15:01:20Z",
    )
    comparison_recorded = registry.record_operation_result(
        store,
        comparison,
        expected_registry_version=ready.registry_version,
    )
    return registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="awaiting_production_slot",
        actor="operator@example.com",
        occurred_at="2026-07-09T15:01:30Z",
        expected_registry_version=comparison_recorded.registry_version,
        expected_batch_version=3,
    )


def _promotion_operation_id(
    record: contracts.M13BatchRecord,
    production: contracts.ProductionIdentity,
) -> str:
    return contracts.M13OperationRequest(
        kind="production_promotion",
        batch_id=record.batch_id,
        requested_by="promoter@example.com",
        requested_at="2026-07-09T15:02:00Z",
        expected_previous_production=contracts.ExpectedPreviousProduction(
            production=production,
            checked_at="2026-07-09T15:02:00Z",
        ),
        planning_only=False,
        requires_production_slot=True,
    ).operation_id()


def _completed_promotion(
    tmp_path: Path,
) -> tuple[
    FileObjectStore,
    contracts.M13BatchRecord,
    contracts.ProductionIdentity,
    contracts.ProductionIdentity,
]:
    store = FileObjectStore(tmp_path / "store")
    previous = _install_production(
        store,
        release_id="20260708T040116Z-69a9f445699a",
        marker="previous",
        promoted_at="2026-07-08T04:01:16Z",
    )
    record = _record(previous, minute=1)
    awaiting = _advance_to_awaiting(store, record, previous)
    lease = coordinator.acquire_production_lease(
        store,
        batch_id=record.batch_id,
        operation_id=_promotion_operation_id(record, previous),
        holder_id="promoter-1",
        acquired_at="2026-07-09T15:02:00Z",
        expires_at="2026-07-09T15:20:00Z",
        observed_production=previous,
        expected_registry_version=awaiting.registry_version,
        expected_batch_version=awaiting.batch_version,
    )
    permit = coordinator.issue_production_mutation_permit(
        store,
        lease_id=lease.lease_id,
        holder_id=lease.holder_id,
        fencing_token=lease.fencing_token,
        issued_at="2026-07-09T15:03:00Z",
        observed_production=previous,
    )
    coordinator.transition_batch_to_promoting(
        store,
        permit=permit,
        actor="promoter@example.com",
        occurred_at="2026-07-09T15:04:00Z",
        observed_production=previous,
    )
    authorization = coordinator.authorize_production_commit(
        store,
        permit=permit,
        holder_id=lease.holder_id,
        authorized_at="2026-07-09T15:05:00Z",
        observed_production=previous,
    )
    resulting, manifest_key, manifest_bytes, pointer_bytes = _production_payload(
        release_id="20260709T150600Z-aaaaaaaaaaaa",
        marker="resulting",
        promoted_at="2026-07-09T15:06:00Z",
    )
    coordinator.complete_production_mutation(
        store,
        authorization=authorization,
        holder_id=lease.holder_id,
        completed_at="2026-07-09T15:06:00Z",
        resulting_production=resulting,
        evidence_refs=(
            "m13/evidence/promotion-receipt.json",
            "m13/evidence/ledger-draft.json",
        ),
    )
    store.put(
        manifest_key,
        manifest_bytes,
        content_type="application/json",
        sha256=resulting.manifest_sha256,
    )
    store.put(
        "channels/production.json",
        pointer_bytes,
        content_type="application/json",
        sha256=resulting.pointer_sha256,
    )
    return store, record, previous, resulting


def _close(
    store: FileObjectStore,
    record: contracts.M13BatchRecord,
    resulting: contracts.ProductionIdentity,
):
    status = registry.registry_status(store)
    snapshot = registry.get_batch(store, record.batch_id)
    return close_batch(
        store,
        batch_id=record.batch_id,
        actor="closer@example.com",
        closed_at="2026-07-09T15:07:00Z",
        observed_production=resulting,
        ledger_references=("issue-30/comment-100",),
        expected_registry_version=status["registry_version"],
        expected_batch_version=snapshot["batch_version"],
    )


def test_closeout_is_atomic_replayable_and_permanently_retained(
    tmp_path: Path,
) -> None:
    store, record, _, resulting = _completed_promotion(tmp_path)
    first = _close(store, record, resulting)
    replay = close_batch(
        store,
        batch_id=record.batch_id,
        actor="closer@example.com",
        closed_at="2026-07-09T15:07:00Z",
        observed_production=resulting,
        ledger_references=("issue-30/comment-100",),
        expected_registry_version=first.registry_version - 1,
        expected_batch_version=first.batch_version - 1,
    )
    snapshot = registry.get_batch(store, record.batch_id)
    summaries = snapshot["operation_summaries"]
    assert snapshot["record"]["state"] == "closed"
    assert any(
        item["kind"] == "production_promotion"
        and item["state"] == "completed"
        for item in summaries
    )
    assert any(
        item["kind"] == "closeout" and item["state"] == "completed"
        for item in summaries
    )
    assert replay.closeout_id == first.closeout_id
    assert replay.idempotent is True
    artifact = first.retention_artifact(closed_at="2026-07-09T15:07:00Z")
    assert artifact.artifact_class == "evidence"
    assert artifact.release_id == resulting.release_id


def test_closeout_requires_explicit_ledger_reference(tmp_path: Path) -> None:
    store, record, _, resulting = _completed_promotion(tmp_path)
    status = registry.registry_status(store)
    snapshot = registry.get_batch(store, record.batch_id)
    with pytest.raises(M13CloseoutError) as invalid:
        close_batch(
            store,
            batch_id=record.batch_id,
            actor="closer@example.com",
            closed_at="2026-07-09T15:07:00Z",
            observed_production=resulting,
            ledger_references=(),
            expected_registry_version=status["registry_version"],
            expected_batch_version=snapshot["batch_version"],
        )
    assert invalid.value.code == "M13_CLOSEOUT_LEDGER_REFERENCES_INVALID"


def test_closeout_rejects_stale_production_and_versions(tmp_path: Path) -> None:
    store, record, previous, resulting = _completed_promotion(tmp_path)
    status = registry.registry_status(store)
    snapshot = registry.get_batch(store, record.batch_id)
    with pytest.raises(M13CloseoutError) as stale_production:
        close_batch(
            store,
            batch_id=record.batch_id,
            actor="closer@example.com",
            closed_at="2026-07-09T15:07:00Z",
            observed_production=previous,
            ledger_references=("issue-30/comment-100",),
            expected_registry_version=status["registry_version"],
            expected_batch_version=snapshot["batch_version"],
        )
    assert stale_production.value.code == "M13_CLOSEOUT_PRODUCTION_STALE"
    with pytest.raises(M13CloseoutError) as stale_version:
        close_batch(
            store,
            batch_id=record.batch_id,
            actor="closer@example.com",
            closed_at="2026-07-09T15:07:00Z",
            observed_production=resulting,
            ledger_references=("issue-30/comment-100",),
            expected_registry_version=status["registry_version"] - 1,
            expected_batch_version=snapshot["batch_version"],
        )
    assert stale_version.value.code == "M13_CLOSEOUT_REGISTRY_VERSION_STALE"


def test_operator_status_lookup_audit_and_ledger_summary(tmp_path: Path) -> None:
    store, record, _, resulting = _completed_promotion(tmp_path)
    closed = _close(store, record, resulting)
    status = operator_status(store, observed_at="2026-07-09T15:08:00Z")
    audit = integrity_audit(store, observed_at="2026-07-09T15:08:00Z")
    batch_lookup = operator_lookup(store, identity=record.batch_id)
    operation_lookup = operator_lookup(store, identity=closed.operation_id)
    closeout_lookup = operator_lookup(store, identity=closed.closeout_id)
    ledger = ledger_summary(store, observed_at="2026-07-09T15:08:00Z")
    assert status["state_counts"] == {"closed": 1}
    assert status["production"] == resulting.to_identity()
    assert audit["passed"] is True
    assert batch_lookup["matches"][0]["kind"] == "batch"
    assert operation_lookup["matches"][0]["kind"] == "operation"
    assert closeout_lookup["matches"][0]["kind"] == "closeout"
    assert ledger["closed_batch_count"] == 1
    assert ledger["closed_batches_missing_ledger_references"] == []
    assert ledger["batches"][0]["ledger_references"] == [
        "issue-30/comment-100"
    ]
    assert ledger["ledger_append_performed"] is False


def test_stale_report_detects_stale_batch_and_expired_candidate_slot(
    tmp_path: Path,
) -> None:
    store, _, previous, resulting = _completed_promotion(tmp_path)
    stale_record = _record(previous, minute=2)
    registry.register_batch(
        store,
        stale_record,
        actor="operator@example.com",
        registered_at="2026-07-09T15:07:10Z",
    )
    slot_key = "m13/v2/concurrency/candidate/leases/mcslot_" + "a" * 32 + ".json"
    _put_json(
        store,
        slot_key,
        {
            "schema_version": "knowledge-engine-m13-coordinator/v2/candidate-lease",
            "slot_id": "mcslot_" + "a" * 32,
            "batch_id": stale_record.batch_id,
            "operation_id": "mop_" + "b" * 32,
        },
    )
    _put_json(
        store,
        "m13/v2/concurrency/candidate/head.json",
        {
            "schema_version": "knowledge-engine-m13-coordinator/v2/candidate-head",
            "head_version": 1,
            "capacity": 2,
            "updated_at": "2026-07-09T15:07:20Z",
            "active": {
                "1": {
                    "slot_id": "mcslot_" + "a" * 32,
                    "batch_id": stale_record.batch_id,
                    "operation_id": "mop_" + "b" * 32,
                    "holder_id": "builder-1",
                    "expires_at": "2026-07-09T15:07:30Z",
                    "artifact_key": slot_key,
                }
            },
        },
    )
    report = stale_report(store, observed_at="2026-07-09T15:08:00Z")
    codes = {item["code"] for item in report["findings"]}
    assert resulting != previous
    assert "expected_previous_production_stale" in codes
    assert "candidate_slot_expired" in codes


def test_audit_detects_divergent_operation_identity(tmp_path: Path) -> None:
    store, record, _, resulting = _completed_promotion(tmp_path)
    closed = _close(store, record, resulting)
    _put_json(
        store,
        closed.operation_key,
        {
            "schema_version": "corrupted/v1",
            "operation_id": "mop_" + "f" * 32,
        },
    )
    audit = integrity_audit(store, observed_at="2026-07-09T15:08:00Z")
    assert audit["passed"] is False
    assert "operation_identity_mismatch" in {
        item["code"] for item in audit["issues"]
    }


def test_cli_status_uses_filesystem_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, record, _, resulting = _completed_promotion(tmp_path)
    _close(store, record, resulting)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("FILESYSTEM_STORE_ROOT", str(tmp_path / "store"))
    assert m13_main(["status", "--observed-at", "2026-07-09T15:08:00Z"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"].endswith("/status")
    assert output["state_counts"] == {"closed": 1}
