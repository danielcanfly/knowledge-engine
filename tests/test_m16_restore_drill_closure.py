from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_restore_drill_closure import (
    CloseoutDecision,
    DrillReason,
    DrillStage,
    DrillStageEvidence,
    M16RestoreDrillAuthority,
    ObjectiveState,
    RestoreDrillObservation,
    StageState,
    evaluate_restore_drill,
    finalize_restore_drill_report,
)
from knowledge_engine.m16_security_contracts import M16Identity

ENGINE = "17727eddf1a6e15e4265c49b79d1f116f0e09090"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
OBJECT = "a" * 64
OTHER = "b" * 64
NOW = datetime(2026, 7, 10, 9, 45, tzinfo=UTC)


def identity(*, engine_sha: str = ENGINE) -> M16Identity:
    return M16Identity(
        engine_sha=engine_sha,
        source_sha=SOURCE,
        release_id=RELEASE,
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
    )


def stages() -> list[DrillStageEvidence]:
    start = NOW - timedelta(minutes=10)
    return [
        DrillStageEvidence(
            stage=stage,
            occurred_at=start + timedelta(minutes=index),
            state=StageState.VERIFIED,
            evidence_codes=[f"stage.{stage.value}.verified"],
        )
        for index, stage in enumerate(DrillStage)
    ]


def observation(**updates: object) -> RestoreDrillObservation:
    payload: dict[str, object] = {
        "drill_id": "drill-m16-7-r2-loss",
        "incident_id": "incident-m16-7-r2-loss",
        "operation_id": "operation-m16-7-r2-restore",
        "generated_at": NOW,
        "identity": identity(),
        "expected_previous_pointer_sha256": POINTER,
        "affected_object_id": "releases/production/search-index.json",
        "stages": stages(),
        "incident_detected": True,
        "blast_radius_bounded": True,
        "production_writes_disabled": True,
        "production_pointer_unchanged": True,
        "authorization_approved": True,
        "authorization_id": "approval-m16-7-isolated",
        "authorization_scope_verified": True,
        "restore_executed": True,
        "expected_object_sha256": OBJECT,
        "restored_object_sha256": OBJECT,
        "restored_manifest_sha256": MANIFEST,
        "restored_release_id": RELEASE,
        "restored_pointer_sha256": POINTER,
        "runtime_release_id": RELEASE,
        "runtime_pointer_sha256": POINTER,
        "cache_release_id": RELEASE,
        "public_query_verified": True,
        "citation_verified": True,
        "acl_negative_denied": True,
        "replay_compliant": True,
        "idempotency_verified": True,
        "expected_previous_verified": True,
        "rto_state": ObjectiveState.PASSED,
        "rpo_state": ObjectiveState.PASSED,
        "release_unavailability_state": ObjectiveState.PASSED,
        "rollback_state": ObjectiveState.NOT_APPLICABLE,
        "evidence_recovery_state": ObjectiveState.PASSED,
        "audit_continuity_verified": True,
        "permanent_ledger_open": True,
        "expected_permanent_ledger_comments": 13,
        "observed_permanent_ledger_comments": 13,
        "permanent_ledger_appended": False,
        "closeout_approved": True,
        "evidence_codes": [
            "drill.detected",
            "drill.restored",
            "drill.runtime.verified",
            "drill.closeout.approved",
        ],
    }
    payload.update(updates)
    return RestoreDrillObservation(**payload)


def test_complete_restore_drill_is_ready_to_close_and_deterministic() -> None:
    first = evaluate_restore_drill(observation(), expected_identity=identity())
    second = evaluate_restore_drill(
        observation(
            stages=list(reversed(stages())),
            evidence_codes=list(
                reversed(
                    [
                        "drill.detected",
                        "drill.restored",
                        "drill.runtime.verified",
                        "drill.closeout.approved",
                    ]
                )
            ),
        ),
        expected_identity=identity(),
    )
    assert first.decision == CloseoutDecision.READY_TO_CLOSE
    assert first.artifact_sha256 == second.artifact_sha256
    assert [item.stage for item in first.stages] == list(DrillStage)
    assert finalize_restore_drill_report(first) == first


def test_missing_stage_blocks_closeout() -> None:
    report = evaluate_restore_drill(
        observation(stages=stages()[:-1]),
        expected_identity=identity(),
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.STAGE_MISSING in report.reasons


def test_out_of_order_timestamps_block_closeout() -> None:
    values = stages()
    values[5] = values[5].model_copy(update={"occurred_at": values[3].occurred_at})
    report = evaluate_restore_drill(observation(stages=values), expected_identity=identity())
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.STAGE_OUT_OF_ORDER in report.reasons


def test_blocked_or_unknown_stage_fails_closed() -> None:
    blocked_values = stages()
    blocked_values[3] = blocked_values[3].model_copy(update={"state": StageState.BLOCKED})
    blocked = evaluate_restore_drill(
        observation(stages=blocked_values), expected_identity=identity()
    )
    assert blocked.decision == CloseoutDecision.BLOCKED
    unknown_values = stages()
    unknown_values[6] = unknown_values[6].model_copy(update={"state": StageState.UNKNOWN})
    unknown = evaluate_restore_drill(
        observation(stages=unknown_values), expected_identity=identity()
    )
    assert unknown.decision == CloseoutDecision.UNKNOWN


def test_authorization_and_restore_are_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requires approved authorization"):
        observation(authorization_approved=False)
    report = evaluate_restore_drill(
        observation(restore_executed=False), expected_identity=identity()
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.RESTORE_NOT_EXECUTED in report.reasons


def test_checksum_release_manifest_and_pointer_mismatch_block() -> None:
    report = evaluate_restore_drill(
        observation(
            restored_object_sha256=OTHER,
            restored_manifest_sha256=OTHER,
            restored_release_id="other-release",
            restored_pointer_sha256=OTHER,
        ),
        expected_identity=identity(),
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.OBJECT_DIGEST_MISMATCH in report.reasons
    assert DrillReason.MANIFEST_MISMATCH in report.reasons
    assert DrillReason.RELEASE_IDENTITY_MISMATCH in report.reasons
    assert DrillReason.POINTER_IDENTITY_MISMATCH in report.reasons


def test_runtime_query_citation_acl_and_cache_must_all_verify() -> None:
    report = evaluate_restore_drill(
        observation(
            runtime_release_id="other-release",
            runtime_pointer_sha256=OTHER,
            cache_release_id="other-release",
            public_query_verified=False,
            citation_verified=False,
            acl_negative_denied=False,
        ),
        expected_identity=identity(),
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.QUERY_VERIFICATION_FAILED in report.reasons
    assert DrillReason.CITATION_VERIFICATION_FAILED in report.reasons
    assert DrillReason.ACL_VERIFICATION_FAILED in report.reasons
    assert DrillReason.CACHE_IDENTITY_MISMATCH in report.reasons


def test_replay_and_expected_previous_must_verify() -> None:
    report = evaluate_restore_drill(
        observation(
            replay_compliant=False,
            idempotency_verified=False,
            expected_previous_verified=False,
            expected_previous_pointer_sha256=OTHER,
        ),
        expected_identity=identity(),
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.REPLAY_SAFETY_FAILED in report.reasons
    assert DrillReason.IDEMPOTENCY_FAILED in report.reasons
    assert DrillReason.EXPECTED_PREVIOUS_FAILED in report.reasons


def test_recovery_objective_failure_and_unknown_are_distinct() -> None:
    failed = evaluate_restore_drill(
        observation(rto_state=ObjectiveState.FAILED), expected_identity=identity()
    )
    assert failed.decision == CloseoutDecision.BLOCKED
    unknown = evaluate_restore_drill(
        observation(rpo_state=ObjectiveState.UNKNOWN), expected_identity=identity()
    )
    assert unknown.decision == CloseoutDecision.UNKNOWN


def test_audit_and_permanent_ledger_invariants_are_required() -> None:
    report = evaluate_restore_drill(
        observation(
            audit_continuity_verified=False,
            permanent_ledger_open=False,
            observed_permanent_ledger_comments=14,
            permanent_ledger_appended=True,
        ),
        expected_identity=identity(),
    )
    assert report.decision == CloseoutDecision.BLOCKED
    assert DrillReason.AUDIT_CONTINUITY_FAILED in report.reasons
    assert DrillReason.LEDGER_INVARIANT_FAILED in report.reasons


def test_identity_drift_stale_evidence_and_closeout_block() -> None:
    drift = evaluate_restore_drill(
        observation(), expected_identity=identity(engine_sha="f" * 40)
    )
    assert drift.decision == CloseoutDecision.BLOCKED
    old_stages = [
        item.model_copy(update={"occurred_at": NOW - timedelta(days=3)})
        for item in stages()
    ]
    stale = evaluate_restore_drill(
        observation(stages=old_stages), expected_identity=identity()
    )
    assert DrillReason.EVIDENCE_STALE in stale.reasons
    closeout = evaluate_restore_drill(
        observation(closeout_approved=False), expected_identity=identity()
    )
    assert DrillReason.CLOSEOUT_NOT_APPROVED in closeout.reasons


def test_duplicate_stage_private_payload_extra_and_non_utc_are_rejected() -> None:
    duplicate = stages()
    duplicate.append(duplicate[0])
    with pytest.raises(ValidationError, match="must be unique"):
        observation(stages=duplicate)
    with pytest.raises(ValidationError):
        RestoreDrillObservation(**observation().model_dump(), raw_query="private")
    with pytest.raises(ValidationError, match="bounded public codes"):
        observation(evidence_codes=["https://private.example"])
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        observation(generated_at=NOW.replace(tzinfo=None))


def test_report_tampering_and_authority_are_rejected() -> None:
    report = evaluate_restore_drill(observation(), expected_identity=identity())
    tampered = report.model_copy(update={"decision": CloseoutDecision.BLOCKED})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_restore_drill_report(tampered)
    authority = M16RestoreDrillAuthority()
    assert not any(authority.model_dump().values())
    for field_name in M16RestoreDrillAuthority.model_fields:
        with pytest.raises(ValidationError, match="evidence-only"):
            M16RestoreDrillAuthority(**{field_name: True})
