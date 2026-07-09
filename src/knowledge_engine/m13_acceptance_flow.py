from __future__ import annotations

from typing import Any

from . import m13_registry as registry
from .compiler_contract_v1 import put_immutable
from .m13_acceptance_common import (
    ACCEPTANCE_SCHEMA,
    BUILDER_ID,
    FOUNDATION_SHA256,
    SHA40_RE,
    SOURCE_REPOSITORY,
    M13AcceptanceError,
    _Clock,
    _put_json,
    _Tracker,
)
from .m13_candidate_coordinator import acquire_candidate_slot, release_candidate_slot
from .m13_closeout import close_batch
from .m13_contracts import (
    ExpectedPreviousProduction,
    M13BatchRecord,
    M13BatchSeed,
    M13OperationRequest,
    M13OperationResult,
    OperationKind,
    ProductionIdentity,
    stable_json_bytes,
)
from .m13_coordination_common import M13CoordinatorError
from .m13_production_commit import (
    authorize_production_commit,
    complete_production_mutation,
    validate_commit_authorization,
)
from .m13_production_lease import acquire_production_lease
from .m13_production_permit import (
    issue_production_mutation_permit,
    transition_batch_to_promoting,
)
from .m13_release_comparison import (
    ReleaseComparisonRequest,
    ReleaseComparisonResult,
    create_release_comparison,
)
from .m13_release_inventory import (
    ARTIFACT_TYPES,
    INVENTORY_SCHEMA,
    ReleaseReference,
)
from .storage import ObjectStore, sha256_bytes


def _release_entries(stage: int) -> dict[str, list[dict[str, Any]]]:
    concept_entries = [
        {
            "concept_id": f"concept-{index:02d}",
            "title": f"Acceptance concept {index}",
            "stage": index,
        }
        for index in range(stage + 1)
    ]
    claim_entries = [
        {
            "claim_id": f"claim-{index:02d}",
            "text": f"Acceptance claim {index}",
            "citation_ids": [f"citation-{index:02d}"],
        }
        for index in range(stage + 1)
    ]
    citation_entries = [
        {
            "citation_id": f"citation-{index:02d}",
            "target": f"urn:m13-acceptance:{index}",
            "supports_claim_ids": [f"claim-{index:02d}"],
        }
        for index in range(stage + 1)
    ]
    return {
        "audience": [
            {
                "audience_id": "audience-main",
                "audience": "internal",
                "principals": ["acceptance-team"],
            }
        ],
        "citations": citation_entries,
        "claims": claim_entries,
        "concepts": concept_entries,
        "indexes": [
            {
                "index_id": "index-main",
                "input_release_stage": stage,
                "entry_count": stage + 1,
            }
        ],
        "registry": [
            {
                "registry_id": "registry-main",
                "release_stage": stage,
                "concept_count": stage + 1,
            }
        ],
    }


def _build_release(
    store: ObjectStore, *, release_id: str, source_commit_sha: str, stage: int
) -> ReleaseReference:
    if not SHA40_RE.fullmatch(source_commit_sha):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_SOURCE_SHA_INVALID", "fixture source SHA is invalid"
        )
    artifact_refs: list[dict[str, Any]] = []
    entries = _release_entries(stage)
    for artifact_type in ARTIFACT_TYPES:
        key = f"releases/{release_id}/{artifact_type}.json"
        schema = f"{ACCEPTANCE_SCHEMA}/{artifact_type}"
        value = {
            "schema_version": schema,
            "release_id": release_id,
            "entries": entries[artifact_type],
        }
        data = stable_json_bytes(value)
        put_immutable(store, key, data)
        artifact_refs.append(
            {
                "artifact_type": artifact_type,
                "key": key,
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "schema_version": schema,
            }
        )
    manifest_key = f"releases/{release_id}/manifest.json"
    manifest = {
        "schema_version": f"{INVENTORY_SCHEMA}/manifest",
        "release_id": release_id,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit_sha": source_commit_sha,
        "builder_id": BUILDER_ID,
        "foundation_sha256": FOUNDATION_SHA256,
        "stage": stage,
        "artifacts": sorted(artifact_refs, key=lambda item: (item["artifact_type"], item["key"])),
    }
    manifest_bytes = stable_json_bytes(manifest)
    put_immutable(store, manifest_key, manifest_bytes)
    return ReleaseReference(
        release_id=release_id,
        manifest_key=manifest_key,
        manifest_sha256=sha256_bytes(manifest_bytes),
        source_repository=SOURCE_REPOSITORY,
        source_commit_sha=source_commit_sha,
        builder_id=BUILDER_ID,
        foundation_sha256=FOUNDATION_SHA256,
    )


def _activate_production(
    store: ObjectStore, release: ReleaseReference, *, promoted_at: str
) -> ProductionIdentity:
    pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": release.release_id,
        "manifest_key": release.manifest_key,
        "manifest_sha256": release.manifest_sha256,
        "promoted_at": promoted_at,
    }
    data = stable_json_bytes(pointer)
    current = store.head("channels/production.json")
    store.put(
        "channels/production.json",
        data,
        content_type="application/json",
        sha256=sha256_bytes(data),
        expected_etag=current.etag if current is not None else None,
    )
    return ProductionIdentity(
        release_id=release.release_id,
        manifest_sha256=release.manifest_sha256,
        pointer_sha256=sha256_bytes(data),
    )


def _batch_record(
    *,
    label: str,
    source_sha: str,
    production: ProductionIdentity,
    requested_at: str,
    candidate_channel: str | None = None,
    supersedes: tuple[str, ...] = (),
    rebuilt_from: str | None = None,
) -> M13BatchRecord:
    seed = M13BatchSeed(
        source_repository=SOURCE_REPOSITORY,
        source_commit_sha=source_sha,
        production=production,
        requested_by="m13-acceptance@example.com",
        requested_at=requested_at,
        purpose=f"M13.7 acceptance batch {label}",
    )
    return M13BatchRecord.from_seed(
        seed,
        candidate_channel=candidate_channel,
        supersedes_batch_ids=supersedes,
        rebuilt_from_batch_id=rebuilt_from,
    )


def _versions(store: ObjectStore, batch_id: str) -> tuple[int, int]:
    status = registry.registry_status(store)
    snapshot = registry.get_batch(store, batch_id)
    return (int(status["registry_version"]), int(snapshot["batch_version"]))


def _operation_result(
    *,
    record: M13BatchRecord,
    kind: OperationKind,
    requested_at: str,
    result_at: str,
    evidence_key: str,
) -> M13OperationResult:
    request = M13OperationRequest(
        kind=kind,
        batch_id=record.batch_id,
        requested_by="m13-acceptance@example.com",
        requested_at=requested_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=record.seed.production, checked_at=requested_at
        ),
        artifact_names=(evidence_key,),
    )
    return M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=result_at,
        evidence_refs=(evidence_key,),
    )


def _record_operation(store: ObjectStore, tracker: _Tracker, result: M13OperationResult) -> None:
    registry_version = int(registry.registry_status(store)["registry_version"])
    mutation = registry.record_operation_result(
        store, result, expected_registry_version=registry_version
    )
    operation_key = (
        f"m13/v1/batches/{result.request.batch_id}/operations/"
        f"{result.operation_id}/result.json"
    )
    tracker.record(operation_key, mutation.snapshot_key)


def _register_and_review(
    store: ObjectStore,
    tracker: _Tracker,
    clock: _Clock,
    record: M13BatchRecord,
    *,
    label: str,
) -> None:
    registered = registry.register_batch(
        store, record, actor="m13-acceptance@example.com", registered_at=clock.next()
    )
    tracker.record(registered.event_key, registered.snapshot_key)
    evidence_key = f"m13/acceptance/evidence/{record.batch_id}/source-review.json"
    _put_json(
        store,
        evidence_key,
        {
            "schema_version": f"{ACCEPTANCE_SCHEMA}/source-review",
            "batch_id": record.batch_id,
            "label": label,
            "approved": True,
        },
    )
    tracker.record(evidence_key)
    result = _operation_result(
        record=record,
        kind="source_review",
        requested_at=clock.next(),
        result_at=clock.next(),
        evidence_key=evidence_key,
    )
    _record_operation(store, tracker, result)
    registry_version, batch_version = _versions(store, record.batch_id)
    transitioned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="reviewing_source",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        expected_registry_version=registry_version,
        expected_batch_version=batch_version,
    )
    tracker.record(transitioned.event_key, transitioned.snapshot_key)


def _candidate_request(
    record: M13BatchRecord, *, requested_at: str, evidence_key: str
) -> M13OperationRequest:
    return M13OperationRequest(
        kind="candidate_build",
        batch_id=record.batch_id,
        requested_by="m13-acceptance@example.com",
        requested_at=requested_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=record.seed.production, checked_at=requested_at
        ),
        artifact_names=(evidence_key,),
    )


def _complete_candidate(
    store: ObjectStore,
    tracker: _Tracker,
    clock: _Clock,
    record: M13BatchRecord,
    *,
    label: str,
    candidate_channel: str,
    request: M13OperationRequest | None = None,
    pre_acquired_slot: Any | None = None,
    capacity: int = 2,
) -> dict[str, Any]:
    evidence_key = f"m13/acceptance/evidence/{record.batch_id}/candidate.json"
    request = request or _candidate_request(
        record, requested_at=clock.next(), evidence_key=evidence_key
    )
    slot = pre_acquired_slot
    if slot is None:
        slot = acquire_candidate_slot(
            store,
            request=request,
            holder_id=f"builder-{label}",
            acquired_at=clock.next(),
            expires_at=clock.future(120),
            capacity=capacity,
        )
    tracker.record(slot.artifact_key)
    _put_json(
        store,
        evidence_key,
        {
            "schema_version": f"{ACCEPTANCE_SCHEMA}/candidate",
            "batch_id": record.batch_id,
            "candidate_channel": candidate_channel,
            "slot_id": slot.slot_id,
            "label": label,
        },
    )
    tracker.record(evidence_key)
    result = M13OperationResult(
        operation_id=request.operation_id(),
        request=request,
        state="completed",
        result_at=clock.next(),
        evidence_refs=(evidence_key,),
    )
    _record_operation(store, tracker, result)
    released = release_candidate_slot(
        store,
        slot_id=slot.slot_id,
        holder_id=f"builder-{label}",
        released_at=clock.next(),
        reason="M13.7 candidate fixture completed",
        capacity=capacity,
    )
    release_key = f"m13/v2/concurrency/candidate/releases/{slot.slot_id}.json"
    tracker.record(release_key)
    registry_version, batch_version = _versions(store, record.batch_id)
    transitioned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="candidate_ready",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        expected_registry_version=registry_version,
        expected_batch_version=batch_version,
        candidate_channel=candidate_channel,
    )
    tracker.record(transitioned.event_key, transitioned.snapshot_key)
    return {
        "slot_id": slot.slot_id,
        "candidate_channel": candidate_channel,
        "release": released,
        "evidence_key": evidence_key,
    }


def _compare_and_await(
    store: ObjectStore,
    tracker: _Tracker,
    clock: _Clock,
    record: M13BatchRecord,
    *,
    base: ReleaseReference,
    target: ReleaseReference,
) -> ReleaseComparisonResult:
    snapshot = registry.get_batch(store, record.batch_id)
    current = registry._record_from_identity(snapshot["record"])
    request = ReleaseComparisonRequest(
        batch_id=record.batch_id,
        base_release=base,
        target_release=target,
        expected_previous_production=record.seed.production,
        requested_by="m13-acceptance@example.com",
        requested_at=clock.next(),
        generated_at=clock.next(),
        candidate_channel=current.candidate_channel,
    )
    comparison = create_release_comparison(
        store, request, observed_production=record.seed.production, batch=current
    )
    replay = create_release_comparison(
        store, request, observed_production=record.seed.production, batch=current
    )
    if not replay.idempotent or replay.comparison_id != comparison.comparison_id:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_COMPARISON_REPLAY_FAILED",
            "release comparison did not replay exactly",
            batch_id=record.batch_id,
        )
    if comparison.release_blockers:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_COMPARISON_BLOCKED",
            "acceptance release comparison unexpectedly blocked",
            blockers=list(comparison.release_blockers),
        )
    tracker.record(comparison.artifact_key)
    _record_operation(store, tracker, comparison.operation_result())
    registry_version, batch_version = _versions(store, record.batch_id)
    transitioned = registry.transition_batch(
        store,
        batch_id=record.batch_id,
        target_state="awaiting_production_slot",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        expected_registry_version=registry_version,
        expected_batch_version=batch_version,
    )
    tracker.record(transitioned.event_key, transitioned.snapshot_key)
    return comparison


def _promotion_request(record: M13BatchRecord, *, requested_at: str) -> M13OperationRequest:
    return M13OperationRequest(
        kind="production_promotion",
        batch_id=record.batch_id,
        requested_by="m13-acceptance@example.com",
        requested_at=requested_at,
        expected_previous_production=ExpectedPreviousProduction(
            production=record.seed.production, checked_at=requested_at
        ),
        planning_only=False,
        requires_production_slot=True,
    )


def _promote_and_close(
    store: ObjectStore,
    tracker: _Tracker,
    clock: _Clock,
    record: M13BatchRecord,
    *,
    target: ReleaseReference,
    label: str,
    busy_probe: M13BatchRecord | None = None,
) -> dict[str, Any]:
    registry_version, batch_version = _versions(store, record.batch_id)
    request = _promotion_request(record, requested_at=clock.next())
    lease = acquire_production_lease(
        store,
        batch_id=record.batch_id,
        operation_id=request.operation_id(),
        holder_id=f"promoter-{label}",
        acquired_at=clock.next(),
        expires_at=clock.future(300),
        observed_production=record.seed.production,
        expected_registry_version=registry_version,
        expected_batch_version=batch_version,
    )
    tracker.record(lease.acquisition_key)
    busy_code = None
    if busy_probe is not None:
        probe_registry, probe_batch = _versions(store, busy_probe.batch_id)
        probe_request = _promotion_request(busy_probe, requested_at=clock.next())
        try:
            acquire_production_lease(
                store,
                batch_id=busy_probe.batch_id,
                operation_id=probe_request.operation_id(),
                holder_id="promoter-busy-probe",
                acquired_at=clock.next(),
                expires_at=clock.future(300),
                observed_production=busy_probe.seed.production,
                expected_registry_version=probe_registry,
                expected_batch_version=probe_batch,
            )
        except M13CoordinatorError as exc:
            busy_code = exc.code
        if busy_code != "M13_PRODUCTION_LEASE_BUSY":
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_PRODUCTION_SERIALIZATION_FAILED",
                "second production lease was not rejected as busy",
                observed_code=busy_code,
            )
    permit = issue_production_mutation_permit(
        store,
        lease_id=lease.lease_id,
        holder_id=lease.holder_id,
        fencing_token=lease.fencing_token,
        issued_at=clock.next(),
        observed_production=record.seed.production,
    )
    tracker.record(permit.permit_key)
    promoting = transition_batch_to_promoting(
        store,
        permit=permit,
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        observed_production=record.seed.production,
    )
    tracker.record(promoting.event_key, promoting.snapshot_key)
    authorization = authorize_production_commit(
        store,
        permit=permit,
        holder_id=lease.holder_id,
        authorized_at=clock.next(),
        observed_production=record.seed.production,
    )
    tracker.record(authorization.authorization_key)
    validate_commit_authorization(
        store,
        authorization=authorization,
        holder_id=lease.holder_id,
        checked_at=clock.next(),
        observed_production=record.seed.production,
    )
    promotion_receipt_key = f"m13/acceptance/evidence/{record.batch_id}/promotion-receipt.json"
    ledger_draft_key = f"m13/acceptance/evidence/{record.batch_id}/ledger-draft.json"
    _put_json(
        store,
        promotion_receipt_key,
        {
            "schema_version": f"{ACCEPTANCE_SCHEMA}/promotion-receipt",
            "batch_id": record.batch_id,
            "lease_id": lease.lease_id,
            "authorization_id": authorization.authorization_id,
            "target_release_id": target.release_id,
            "isolated_namespace_only": True,
        },
    )
    _put_json(
        store,
        ledger_draft_key,
        {
            "schema_version": f"{ACCEPTANCE_SCHEMA}/ledger-draft",
            "batch_id": record.batch_id,
            "append_performed": False,
        },
    )
    tracker.record(promotion_receipt_key, ledger_draft_key)
    resulting = _activate_production(store, target, promoted_at=clock.next())
    completed = complete_production_mutation(
        store,
        authorization=authorization,
        holder_id=lease.holder_id,
        completed_at=clock.next(),
        resulting_production=resulting,
        evidence_refs=(promotion_receipt_key, ledger_draft_key),
    )
    tracker.record(completed.completion_key)
    close_registry, close_batch_version = _versions(store, record.batch_id)
    closeout = close_batch(
        store,
        batch_id=record.batch_id,
        actor="m13-acceptance@example.com",
        closed_at=(closed_at := clock.next()),
        observed_production=resulting,
        ledger_references=(f"ledger_m13-acceptance-{label}",),
        expected_registry_version=close_registry,
        expected_batch_version=close_batch_version,
    )
    replay = close_batch(
        store,
        batch_id=record.batch_id,
        actor="m13-acceptance@example.com",
        closed_at=clock.next(0),
        observed_production=resulting,
        ledger_references=(f"ledger_m13-acceptance-{label}",),
        expected_registry_version=close_registry,
        expected_batch_version=close_batch_version,
    )
    if not replay.idempotent or replay.closeout_id != closeout.closeout_id:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_CLOSEOUT_REPLAY_FAILED",
            "closeout did not replay exactly",
            batch_id=record.batch_id,
        )
    tracker.record(
        closeout.evidence_key,
        closeout.operation_key,
        closeout.event_key,
        closeout.snapshot_key,
    )
    return {
        "batch_id": record.batch_id,
        "lease_id": lease.lease_id,
        "lease_generation": lease.generation,
        "permit_id": permit.permit_id,
        "authorization_id": authorization.authorization_id,
        "completion_key": completed.completion_key,
        "closeout": closeout,
        "closed_at": closed_at,
        "production": resulting,
        "busy_probe_code": busy_code,
    }


def _prepare_fresh_batch(
    store: ObjectStore,
    tracker: _Tracker,
    clock: _Clock,
    *,
    label: str,
    source_sha: str,
    production: ProductionIdentity,
    base_release: ReleaseReference,
    target_release: ReleaseReference,
    candidate_channel: str,
) -> tuple[M13BatchRecord, ReleaseComparisonResult, dict[str, Any]]:
    record = _batch_record(
        label=label,
        source_sha=source_sha,
        production=production,
        requested_at=clock.next(),
    )
    _register_and_review(store, tracker, clock, record, label=label)
    candidate = _complete_candidate(
        store, tracker, clock, record, label=label, candidate_channel=candidate_channel
    )
    comparison = _compare_and_await(
        store, tracker, clock, record, base=base_release, target=target_release
    )
    return (record, comparison, candidate)
