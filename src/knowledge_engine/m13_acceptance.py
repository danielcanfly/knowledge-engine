from __future__ import annotations

import json
from typing import Any

from . import m13_registry as registry
from .compiler_contract_v1 import put_immutable
from .errors import IntegrityError
from .m13_abandonment import abandon_batch
from .m13_acceptance_common import (
    ACCEPTANCE_SCHEMA,
    BR_ID,
    CS_ID,
    P0_ID,
    P1_ID,
    P2_ID,
    P3_ID,
    RUN_ID_RE,
    S_ALPHA,
    S_BETA,
    S_C,
    S_D,
    S_E,
    SHA40_RE,
    AcceptanceRuntimeReceipt,
    IsolatedObjectStore,
    M13AcceptanceError,
    _Clock,
    _hash_identity,
    _put_json,
    _Tracker,
)
from .m13_acceptance_flow import (
    _activate_production,
    _batch_record,
    _build_release,
    _candidate_request,
    _compare_and_await,
    _complete_candidate,
    _prepare_fresh_batch,
    _promote_and_close,
    _promotion_request,
    _register_and_review,
    _versions,
)
from .m13_candidate_coordinator import acquire_candidate_slot
from .m13_closeout import CloseoutResult
from .m13_contracts import ProductionIdentity, stable_json_bytes
from .m13_coordination_common import M13CoordinatorError
from .m13_operator import (
    integrity_audit,
    ledger_summary,
    operator_lookup,
    operator_status,
    stale_report,
)
from .m13_production_lease import acquire_production_lease
from .m13_rebuild import register_rebuild_batch
from .m13_release_comparison import ReleaseComparisonResult
from .m13_release_inventory import ARTIFACT_TYPES, ReleaseReference
from .m13_retention import (
    RetentionArtifact,
    RetentionReferenceSnapshot,
    classify_artifact,
)
from .m13_supersession import supersede_batches
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes


def _retention_proof(
    *,
    generated_at: str,
    production: ProductionIdentity,
    comparisons: list[ReleaseComparisonResult],
    closeouts: list[tuple[CloseoutResult, str]],
    lifecycle_evidence: list[tuple[str, str]],
    coordination_keys: list[tuple[str, str]],
    release_refs: list[ReleaseReference],
    candidate_evidence: list[tuple[str, str, str, str]],
    registry_history: list[tuple[str, str]],
) -> dict[str, Any]:
    artifacts: list[RetentionArtifact] = []
    artifacts.extend(comparison.retention_artifact() for comparison in comparisons)
    artifacts.extend(
        closeout.retention_artifact(closed_at=closed_at)
        for closeout, closed_at in closeouts
    )
    artifacts.extend(
        RetentionArtifact(
            key=key,
            artifact_class="evidence",
            created_at=generated_at,
            sha256=digest,
            reference_ids=("m13-acceptance-lifecycle",),
        )
        for key, digest in lifecycle_evidence
    )
    artifacts.extend(
        RetentionArtifact(
            key=key,
            artifact_class="coordination_evidence",
            created_at=generated_at,
            sha256=digest,
            reference_ids=("m13-acceptance-coordination",),
        )
        for key, digest in coordination_keys
    )
    artifacts.extend(
        RetentionArtifact(
            key=release.manifest_key,
            artifact_class="release",
            created_at=generated_at,
            sha256=release.manifest_sha256,
            release_id=release.release_id,
            reference_ids=("m13-acceptance-release-chain",),
        )
        for release in release_refs
    )
    artifacts.extend(
        RetentionArtifact(
            key=key,
            artifact_class="candidate",
            created_at=generated_at,
            terminal_at=generated_at,
            sha256=digest,
            batch_id=batch_id,
            candidate_channel=channel,
        )
        for key, digest, batch_id, channel in candidate_evidence
    )
    artifacts.extend(
        RetentionArtifact(
            key=key,
            artifact_class="registry_history",
            created_at=generated_at,
            sha256=digest,
            reference_ids=("m13-acceptance-registry-history",),
        )
        for key, digest in registry_history
    )
    references = RetentionReferenceSnapshot(
        observed_at=generated_at,
        production=production,
        referenced_release_ids=tuple(
            sorted(release.release_id for release in release_refs)
        ),
        referenced_artifact_ids=tuple(
            sorted(artifact.artifact_id() for artifact in artifacts)
        ),
    )
    decisions = [
        classify_artifact(
            artifact,
            references=references,
            generated_at=generated_at,
        )
        for artifact in artifacts
    ]
    if any(decision.disposition == "deletion_candidate" for decision in decisions):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_RETENTION_FAILED",
            "acceptance evidence became a deletion candidate",
        )
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.disposition] = counts.get(decision.disposition, 0) + 1
    return {
        "artifact_count": len(artifacts),
        "disposition_counts": dict(sorted(counts.items())),
        "reference_snapshot_sha256": references.snapshot_sha256(),
        "deletion_candidate_count": 0,
        "physical_delete_performed": False,
    }


def _verify_report_evidence(store: ObjectStore, report: dict[str, Any]) -> None:
    immutable = report.get("immutable_evidence")
    if not isinstance(immutable, dict):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_REPORT_COLLISION",
            "acceptance report lacks immutable evidence",
        )
    hashes = immutable.get("object_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_REPORT_COLLISION",
            "acceptance report object hashes are invalid",
        )
    for key, expected in sorted(hashes.items()):
        if not isinstance(key, str) or not isinstance(expected, str):
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_REPORT_COLLISION",
                "acceptance report object hash entry is invalid",
            )
        try:
            observed = sha256_bytes(store.get(key))
        except FileNotFoundError as exc:
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_EVIDENCE_MISSING",
                "acceptance evidence is missing during replay",
                key=key,
            ) from exc
        if observed != expected:
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_EVIDENCE_OVERWRITTEN",
                "acceptance evidence changed before replay",
                key=key,
                expected=expected,
                observed=observed,
            )


def _track_lifecycle_result(tracker: _Tracker, result: Any) -> None:
    tracker.record(
        result.evidence_key,
        *result.event_keys.values(),
        *result.snapshot_keys.values(),
    )


def _scenario_identity(engine_sha: str, canonical_source_sha: str) -> dict[str, Any]:
    return {
        "schema_version": f"{ACCEPTANCE_SCHEMA}/scenario",
        "engine_sha": engine_sha,
        "canonical_source_sha": canonical_source_sha,
        "scenario_version": 1,
        "fixture_release_ids": [P0_ID, P1_ID, P2_ID, P3_ID, BR_ID, CS_ID],
        "candidate_capacity": 2,
        "required_promoted_batches": 3,
        "real_production_mutation_authorized": False,
        "permanent_ledger_append_authorized": False,
    }


def _run_three_batch_acceptance(
    store: IsolatedObjectStore,
    *,
    engine_sha: str,
    canonical_source_sha: str,
) -> dict[str, Any]:
    if not isinstance(store, IsolatedObjectStore):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_ISOLATION_REQUIRED",
            "three-batch acceptance requires an isolated object store",
        )
    if not SHA40_RE.fullmatch(engine_sha):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_ENGINE_SHA_INVALID",
            "engine SHA is invalid",
        )
    if not SHA40_RE.fullmatch(canonical_source_sha):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_SOURCE_SHA_INVALID",
            "canonical Source SHA is invalid",
        )
    scenario = _scenario_identity(engine_sha, canonical_source_sha)
    acceptance_id = _hash_identity(scenario, "m13accept")
    report_key = f"m13/v3/acceptance/{acceptance_id}/report.json"
    existing = store.head(report_key)
    if existing is not None:
        report_bytes = store.get(report_key)
        try:
            value = json.loads(report_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_REPORT_COLLISION",
                "existing acceptance report is invalid JSON",
                report_key=report_key,
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("acceptance_id") != acceptance_id
            or value.get("scenario") != scenario
        ):
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_REPORT_COLLISION",
                "existing acceptance report has divergent identity",
                report_key=report_key,
            )
        if report_bytes != stable_json_bytes(value):
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_REPORT_COLLISION",
                "existing acceptance report is not canonical JSON",
                report_key=report_key,
            )
        _verify_report_evidence(store, value)
        return {
            **value,
            "report_sha256": sha256_bytes(report_bytes),
            "idempotent": True,
        }

    clock = _Clock()
    tracker = _Tracker(store)
    releases = {
        "p0": _build_release(
            store,
            release_id=P0_ID,
            source_commit_sha="0" * 40,
            stage=0,
        ),
        "p1": _build_release(
            store,
            release_id=P1_ID,
            source_commit_sha=S_ALPHA,
            stage=1,
        ),
        "p2": _build_release(
            store,
            release_id=P2_ID,
            source_commit_sha=S_D,
            stage=2,
        ),
        "p3": _build_release(
            store,
            release_id=P3_ID,
            source_commit_sha=S_E,
            stage=3,
        ),
        "br": _build_release(
            store,
            release_id=BR_ID,
            source_commit_sha=S_BETA,
            stage=1,
        ),
        "cs": _build_release(
            store,
            release_id=CS_ID,
            source_commit_sha=S_C,
            stage=1,
        ),
    }
    for release in releases.values():
        tracker.record(
            release.manifest_key,
            *(
                f"releases/{release.release_id}/{artifact_type}.json"
                for artifact_type in ARTIFACT_TYPES
            ),
        )
    p0 = _activate_production(store, releases["p0"], promoted_at=clock.next())

    alpha = _batch_record(
        label="alpha",
        source_sha=S_ALPHA,
        production=p0,
        requested_at=clock.next(),
    )
    beta = _batch_record(
        label="beta",
        source_sha=S_BETA,
        production=p0,
        requested_at=clock.next(),
    )
    gamma = _batch_record(
        label="gamma",
        source_sha=S_C,
        production=p0,
        requested_at=clock.next(),
    )
    for record, label in ((alpha, "alpha"), (beta, "beta"), (gamma, "gamma")):
        _register_and_review(store, tracker, clock, record, label=label)

    alpha_candidate_key = (
        f"m13/acceptance/evidence/{alpha.batch_id}/candidate.json"
    )
    beta_candidate_key = f"m13/acceptance/evidence/{beta.batch_id}/candidate.json"
    gamma_candidate_key = (
        f"m13/acceptance/evidence/{gamma.batch_id}/candidate.json"
    )
    alpha_request = _candidate_request(
        alpha,
        requested_at=clock.next(),
        evidence_key=alpha_candidate_key,
    )
    beta_request = _candidate_request(
        beta,
        requested_at=clock.next(),
        evidence_key=beta_candidate_key,
    )
    gamma_request = _candidate_request(
        gamma,
        requested_at=clock.next(),
        evidence_key=gamma_candidate_key,
    )
    alpha_slot = acquire_candidate_slot(
        store,
        request=alpha_request,
        holder_id="builder-alpha",
        acquired_at=clock.next(),
        expires_at=clock.future(120),
        capacity=2,
    )
    beta_slot = acquire_candidate_slot(
        store,
        request=beta_request,
        holder_id="builder-beta",
        acquired_at=clock.next(),
        expires_at=clock.future(120),
        capacity=2,
    )
    tracker.record(alpha_slot.artifact_key, beta_slot.artifact_key)
    capacity_code = None
    try:
        acquire_candidate_slot(
            store,
            request=gamma_request,
            holder_id="builder-gamma",
            acquired_at=clock.next(),
            expires_at=clock.future(120),
            capacity=2,
        )
    except M13CoordinatorError as exc:
        capacity_code = exc.code
    if capacity_code != "M13_CANDIDATE_CAPACITY_EXHAUSTED":
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_CANDIDATE_CAPACITY_FAILED",
            "third concurrent candidate was not rejected",
            observed_code=capacity_code,
        )
    alpha_candidate = _complete_candidate(
        store,
        tracker,
        clock,
        alpha,
        label="alpha",
        candidate_channel="candidate-accept-alpha",
        request=alpha_request,
        pre_acquired_slot=alpha_slot,
    )
    beta_candidate = _complete_candidate(
        store,
        tracker,
        clock,
        beta,
        label="beta",
        candidate_channel="candidate-accept-beta",
        request=beta_request,
        pre_acquired_slot=beta_slot,
    )
    gamma_candidate = _complete_candidate(
        store,
        tracker,
        clock,
        gamma,
        label="gamma",
        candidate_channel="candidate-accept-gamma",
        request=gamma_request,
    )

    beta_registry, beta_version = _versions(store, beta.batch_id)
    abandoned = abandon_batch(
        store,
        batch_id=beta.batch_id,
        reason="rebuild_requested",
        rationale="exercise explicit abandonment before rebuild",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        observed_production=p0,
        expected_registry_version=beta_registry,
        expected_batch_version=beta_version,
    )
    abandoned_replay = abandon_batch(
        store,
        batch_id=beta.batch_id,
        reason="rebuild_requested",
        rationale="exercise explicit abandonment before rebuild",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(0),
        observed_production=p0,
        expected_registry_version=beta_registry,
        expected_batch_version=beta_version,
    )
    if not abandoned_replay.idempotent:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_ABANDON_REPLAY_FAILED",
            "abandonment replay was not idempotent",
        )
    _track_lifecycle_result(tracker, abandoned)

    beta_rebuild = _batch_record(
        label="beta-rebuild",
        source_sha=S_BETA,
        production=p0,
        requested_at=clock.next(),
        candidate_channel="candidate-accept-beta-r",
        supersedes=(beta.batch_id,),
        rebuilt_from=beta.batch_id,
    )
    rebuild_registry = int(registry.registry_status(store)["registry_version"])
    beta_snapshot = registry.get_batch(store, beta.batch_id)
    rebuilt = register_rebuild_batch(
        store,
        new_record=beta_rebuild,
        rationale="exercise strict rebuild lineage",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        observed_production=p0,
        expected_registry_version=rebuild_registry,
        expected_ancestor_batch_version=int(beta_snapshot["batch_version"]),
    )
    rebuilt_replay = register_rebuild_batch(
        store,
        new_record=beta_rebuild,
        rationale="exercise strict rebuild lineage",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(0),
        observed_production=p0,
        expected_registry_version=rebuild_registry,
        expected_ancestor_batch_version=int(beta_snapshot["batch_version"]),
    )
    if not rebuilt_replay.idempotent:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_REBUILD_REPLAY_FAILED",
            "rebuild replay was not idempotent",
        )
    _track_lifecycle_result(tracker, rebuilt)
    _register_and_review(store, tracker, clock, beta_rebuild, label="beta-rebuild")
    beta_rebuild_candidate = _complete_candidate(
        store,
        tracker,
        clock,
        beta_rebuild,
        label="beta-rebuild",
        candidate_channel="candidate-accept-beta-r",
    )

    gamma_super = _batch_record(
        label="gamma-super",
        source_sha=S_C,
        production=p0,
        requested_at=clock.next(),
        candidate_channel="candidate-accept-gamma-s",
        supersedes=(gamma.batch_id,),
    )
    gamma_registry = int(registry.registry_status(store)["registry_version"])
    gamma_snapshot = registry.get_batch(store, gamma.batch_id)
    superseded = supersede_batches(
        store,
        new_record=gamma_super,
        expected_batch_versions={
            gamma.batch_id: int(gamma_snapshot["batch_version"])
        },
        rationale="exercise atomic supersession",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(),
        observed_production=p0,
        expected_registry_version=gamma_registry,
    )
    superseded_replay = supersede_batches(
        store,
        new_record=gamma_super,
        expected_batch_versions={
            gamma.batch_id: int(gamma_snapshot["batch_version"])
        },
        rationale="exercise atomic supersession",
        actor="m13-acceptance@example.com",
        occurred_at=clock.next(0),
        observed_production=p0,
        expected_registry_version=gamma_registry,
    )
    if not superseded_replay.idempotent:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_SUPERSESSION_REPLAY_FAILED",
            "supersession replay was not idempotent",
        )
    _track_lifecycle_result(tracker, superseded)
    _register_and_review(store, tracker, clock, gamma_super, label="gamma-super")
    gamma_super_candidate = _complete_candidate(
        store,
        tracker,
        clock,
        gamma_super,
        label="gamma-super",
        candidate_channel="candidate-accept-gamma-s",
    )

    alpha_comparison = _compare_and_await(
        store,
        tracker,
        clock,
        alpha,
        base=releases["p0"],
        target=releases["p1"],
    )
    beta_comparison = _compare_and_await(
        store,
        tracker,
        clock,
        beta_rebuild,
        base=releases["p0"],
        target=releases["br"],
    )
    gamma_comparison = _compare_and_await(
        store,
        tracker,
        clock,
        gamma_super,
        base=releases["p0"],
        target=releases["cs"],
    )
    first = _promote_and_close(
        store,
        tracker,
        clock,
        alpha,
        target=releases["p1"],
        label="alpha",
        busy_probe=beta_rebuild,
    )
    p1 = first["production"]
    stale_registry, stale_batch_version = _versions(store, beta_rebuild.batch_id)
    stale_request = _promotion_request(beta_rebuild, requested_at=clock.next())
    stale_code = None
    try:
        acquire_production_lease(
            store,
            batch_id=beta_rebuild.batch_id,
            operation_id=stale_request.operation_id(),
            holder_id="promoter-stale-probe",
            acquired_at=clock.next(),
            expires_at=clock.future(300),
            observed_production=p1,
            expected_registry_version=stale_registry,
            expected_batch_version=stale_batch_version,
        )
    except M13CoordinatorError as exc:
        stale_code = exc.code
    if stale_code != "M13_PRODUCTION_EXPECTED_PREVIOUS_STALE":
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_STALE_REJECTION_FAILED",
            "stale expected-previous production was not rejected",
            observed_code=stale_code,
        )
    for stale_record in (beta_rebuild, gamma_super):
        stale_registry, stale_batch_version = _versions(
            store,
            stale_record.batch_id,
        )
        rejected = registry.transition_batch(
            store,
            batch_id=stale_record.batch_id,
            target_state="rejected",
            actor="m13-acceptance@example.com",
            occurred_at=clock.next(),
            expected_registry_version=stale_registry,
            expected_batch_version=stale_batch_version,
        )
        tracker.record(rejected.event_key, rejected.snapshot_key)

    delta, delta_comparison, delta_candidate = _prepare_fresh_batch(
        store,
        tracker,
        clock,
        label="delta",
        source_sha=S_D,
        production=p1,
        base_release=releases["p1"],
        target_release=releases["p2"],
        candidate_channel="candidate-accept-delta",
    )
    second = _promote_and_close(
        store,
        tracker,
        clock,
        delta,
        target=releases["p2"],
        label="delta",
    )
    p2 = second["production"]

    epsilon, epsilon_comparison, epsilon_candidate = _prepare_fresh_batch(
        store,
        tracker,
        clock,
        label="epsilon",
        source_sha=S_E,
        production=p2,
        base_release=releases["p2"],
        target_release=releases["p3"],
        candidate_channel="candidate-accept-epsilon",
    )
    third = _promote_and_close(
        store,
        tracker,
        clock,
        epsilon,
        target=releases["p3"],
        label="epsilon",
    )
    p3 = third["production"]

    status = operator_status(store, observed_at=clock.next())
    audit = integrity_audit(store, observed_at=clock.next())
    stale = stale_report(store, observed_at=clock.next())
    ledger = ledger_summary(store, observed_at=clock.next())
    lookup = operator_lookup(store, identity=third["closeout"].closeout_id)
    if not audit["passed"]:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_OPERATOR_AUDIT_FAILED",
            "operator integrity audit failed",
            issues=audit["issues"],
        )
    if stale["finding_count"] != 0:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_STALE_WORK_REMAINS",
            "stale-work report is not empty after reconciliation",
            findings=stale["findings"],
        )
    if status["state_counts"].get("closed") != 3:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_CLOSED_BATCH_COUNT_INVALID",
            "three batches were not closed",
            state_counts=status["state_counts"],
        )
    if ledger["closed_batch_count"] != 3:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_LEDGER_SUMMARY_INVALID",
            "ledger summary did not reconstruct three closed batches",
        )
    if ledger["closed_batches_missing_ledger_references"]:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_LEDGER_REFERENCE_MISSING",
            "closed batch lacks a ledger reference",
        )
    if lookup["matches"][0]["kind"] != "closeout":
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_LOOKUP_FAILED",
            "exact closeout lookup did not resolve",
        )

    tracker.verify()
    lifecycle_keys = [
        (abandoned.evidence_key, tracker.hashes[abandoned.evidence_key]),
        (rebuilt.evidence_key, tracker.hashes[rebuilt.evidence_key]),
        (superseded.evidence_key, tracker.hashes[superseded.evidence_key]),
    ]
    coordination_keys = [
        (key, digest)
        for key, digest in tracker.hashes.items()
        if "/concurrency/" in key
    ]
    registry_history = [
        (key, digest)
        for key, digest in tracker.hashes.items()
        if "/events/" in key or "/snapshots/" in key
    ]
    candidate_items = [
        (
            item["evidence_key"],
            tracker.hashes[item["evidence_key"]],
            batch_id,
            item["candidate_channel"],
        )
        for batch_id, item in (
            (alpha.batch_id, alpha_candidate),
            (beta.batch_id, beta_candidate),
            (gamma.batch_id, gamma_candidate),
            (beta_rebuild.batch_id, beta_rebuild_candidate),
            (gamma_super.batch_id, gamma_super_candidate),
            (delta.batch_id, delta_candidate),
            (epsilon.batch_id, epsilon_candidate),
        )
    ]
    retention = _retention_proof(
        generated_at=clock.next(),
        production=p3,
        comparisons=[
            alpha_comparison,
            beta_comparison,
            gamma_comparison,
            delta_comparison,
            epsilon_comparison,
        ],
        closeouts=[
            (first["closeout"], first["closed_at"]),
            (second["closeout"], second["closed_at"]),
            (third["closeout"], third["closed_at"]),
        ],
        lifecycle_evidence=lifecycle_keys,
        coordination_keys=coordination_keys,
        release_refs=list(releases.values()),
        candidate_evidence=candidate_items,
        registry_history=registry_history,
    )

    promoted = [first, second, third]
    report = {
        "schema_version": f"{ACCEPTANCE_SCHEMA}/report",
        "acceptance_id": acceptance_id,
        "scenario": scenario,
        "result": "passed",
        "promoted_batch_count": 3,
        "promoted_batches": [
            {
                "batch_id": item["batch_id"],
                "lease_id": item["lease_id"],
                "lease_generation": item["lease_generation"],
                "permit_id": item["permit_id"],
                "authorization_id": item["authorization_id"],
                "completion_key": item["completion_key"],
                "closeout_id": item["closeout"].closeout_id,
                "closeout_key": item["closeout"].evidence_key,
                "release_id": item["production"].release_id,
                "manifest_sha256": item["production"].manifest_sha256,
                "pointer_sha256": item["production"].pointer_sha256,
            }
            for item in promoted
        ],
        "lifecycle_cases": {
            "abandonment_action_id": abandoned.action_id,
            "rebuild_action_id": rebuilt.action_id,
            "supersession_action_id": superseded.action_id,
            "capacity_rejection_code": capacity_code,
            "production_busy_code": first["busy_probe_code"],
            "stale_expected_previous_code": stale_code,
            "abandoned_batch_ids": sorted([beta.batch_id, gamma.batch_id]),
            "rejected_batch_ids": sorted(
                [beta_rebuild.batch_id, gamma_super.batch_id]
            ),
        },
        "comparison_ids": sorted(
            comparison.comparison_id
            for comparison in (
                alpha_comparison,
                beta_comparison,
                gamma_comparison,
                delta_comparison,
                epsilon_comparison,
            )
        ),
        "operator_reconstruction": {
            "registry_version": status["registry_version"],
            "batch_count": status["batch_count"],
            "state_counts": status["state_counts"],
            "audit_passed": audit["passed"],
            "audit_checked_object_count": audit["checked_object_count"],
            "stale_finding_count": stale["finding_count"],
            "ledger_closed_batch_count": ledger["closed_batch_count"],
            "lookup_match_count": lookup["match_count"],
        },
        "retention": retention,
        "immutable_evidence": {
            "tracked_object_count": len(tracker.hashes),
            "all_hashes_reverified": True,
            "overwritten_object_count": 0,
            "object_hashes": dict(sorted(tracker.hashes.items())),
        },
        "production_chain": [
            p0.to_identity(),
            p1.to_identity(),
            p2.to_identity(),
            p3.to_identity(),
        ],
        "governance": {
            **GOVERNANCE_NO_WRITE,
            "isolated_acceptance_write_permitted": True,
            "real_production_write_performed": False,
            "canonical_source_write_performed": False,
            "permanent_ledger_append_performed": False,
            "rollback_performed": False,
            "physical_delete_performed": False,
        },
        "report_key": report_key,
    }
    report_bytes = stable_json_bytes(report)
    try:
        put_immutable(store, report_key, report_bytes)
    except IntegrityError as exc:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_REPORT_COLLISION",
            "acceptance report identity has divergent bytes",
            report_key=report_key,
        ) from exc
    return {
        **report,
        "report_sha256": sha256_bytes(report_bytes),
        "idempotent": False,
    }


def run_isolated_acceptance(
    base_store: ObjectStore,
    *,
    run_id: str,
    engine_sha: str,
    canonical_source_sha: str,
    expected_real_production_pointer_sha256: str,
) -> tuple[dict[str, Any], AcceptanceRuntimeReceipt]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_RUN_ID_INVALID",
            "run_id is invalid",
        )
    before = base_store.get("channels/production.json")
    before_sha = sha256_bytes(before)
    if before_sha != expected_real_production_pointer_sha256:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_REAL_PRODUCTION_STALE",
            "real production pointer differs from expected identity",
            expected=expected_real_production_pointer_sha256,
            observed=before_sha,
        )
    prefix = f"m13/acceptance-runs/{run_id}"
    isolated = IsolatedObjectStore(base_store, prefix)
    try:
        report = _run_three_batch_acceptance(
            isolated,
            engine_sha=engine_sha,
            canonical_source_sha=canonical_source_sha,
        )
    finally:
        after = base_store.get("channels/production.json")
        after_sha = sha256_bytes(after)
        if before != after:
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_REAL_PRODUCTION_MUTATED",
                "real production pointer changed during isolated acceptance",
                before_sha256=before_sha,
                after_sha256=after_sha,
            )
    receipt = AcceptanceRuntimeReceipt(
        run_id=run_id,
        isolation_prefix=prefix,
        acceptance_id=str(report["acceptance_id"]),
        report_key=isolated.physical_key(str(report["report_key"])),
        report_sha256=str(report["report_sha256"]),
        real_production_pointer_sha256_before=before_sha,
        real_production_pointer_sha256_after=after_sha,
        real_production_pointer_unchanged=True,
        engine_sha=engine_sha,
        canonical_source_sha=canonical_source_sha,
    )
    receipt_key = (
        f"m13/v3/acceptance/{report['acceptance_id']}/runtime-receipt.json"
    )
    _put_json(isolated, receipt_key, receipt.to_dict())
    return (report, receipt)
