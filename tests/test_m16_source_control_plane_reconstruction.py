from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_security_contracts import M16Identity
from knowledge_engine.m16_source_control_plane_reconstruction import (
    M16SourceControlPlaneAuthority,
    ReconstructionComponentEvidence,
    ReconstructionComponentKind,
    ReconstructionComponentState,
    ReconstructionDecision,
    ReconstructionReason,
    SourceControlPlaneObservation,
    SourceIntegrityState,
    TrustedGitEvidence,
    TrustedGitState,
    evaluate_source_control_plane_reconstruction,
    finalize_source_control_plane_report,
)

ENGINE = "d9dd9cf63908fc352422b2184e7a4afc30eec0da"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
OTHER_SHA = "a" * 40
OTHER_MANIFEST = "b" * 64
NOW = datetime(2026, 7, 10, 8, 30, tzinfo=UTC)


def identity(*, engine_sha: str = ENGINE) -> M16Identity:
    return M16Identity(
        engine_sha=engine_sha,
        source_sha=SOURCE,
        release_id=RELEASE,
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
    )


def trusted_git(**updates: object) -> TrustedGitEvidence:
    payload: dict[str, object] = {
        "trusted_source_sha": SOURCE,
        "reachable_from_trusted_history": True,
        "review_evidence_complete": True,
        "commit_signature_verified": True,
        "trusted_history_intact": True,
        "evidence_codes": ["git.history.verified", "git.review.verified"],
    }
    payload.update(updates)
    return TrustedGitEvidence(**payload)


def component(
    kind: ReconstructionComponentKind,
    *,
    reconstructed: bool,
    evidence_present: bool = True,
    identity_verified: bool = True,
    complete: bool = True,
) -> ReconstructionComponentEvidence:
    return ReconstructionComponentEvidence(
        kind=kind,
        evidence_present=evidence_present,
        identity_verified=identity_verified,
        complete=complete,
        reconstructed=reconstructed,
        declared_ephemeral=kind == ReconstructionComponentKind.EPHEMERAL_STATE,
        evidence_codes=[f"component.{kind.value}.verified"] if evidence_present else [],
    )


def all_components(
    *,
    reconstructed: bool,
    ephemeral_present: bool = True,
) -> list[ReconstructionComponentEvidence]:
    values = [
        component(kind, reconstructed=reconstructed)
        for kind in (
            ReconstructionComponentKind.BATCH_REGISTRY,
            ReconstructionComponentKind.APPROVALS,
            ReconstructionComponentKind.LIFECYCLE_STATE,
            ReconstructionComponentKind.PRODUCTION_IDENTITY,
            ReconstructionComponentKind.POINTER_IDENTITY,
            ReconstructionComponentKind.ARTIFACT_INVENTORY,
            ReconstructionComponentKind.LEDGER_CONTINUITY,
        )
    ]
    values.append(
        component(
            ReconstructionComponentKind.EPHEMERAL_STATE,
            reconstructed=ephemeral_present and reconstructed,
            evidence_present=ephemeral_present,
            identity_verified=ephemeral_present,
            complete=ephemeral_present,
        )
    )
    return values


def observation(**updates: object) -> SourceControlPlaneObservation:
    payload: dict[str, object] = {
        "drill_id": "drill-m16-5-source",
        "operation_id": "operation-m16-5-source",
        "generated_at": NOW,
        "identity": identity(),
        "observed_source_head_sha": OTHER_SHA,
        "source_history_diverged": True,
        "trusted_git": trusted_git(),
        "source_restore_authorized": False,
        "source_restore_executed": False,
        "restored_source_sha": None,
        "rebuild_executed": False,
        "rebuilt_source_sha": None,
        "rebuilt_manifest_sha256": None,
        "components": all_components(reconstructed=False),
        "evidence_codes": ["incident.source.corruption", "control_plane.snapshot.loaded"],
    }
    payload.update(updates)
    return SourceControlPlaneObservation(**payload)


def fully_executed(**updates: object) -> SourceControlPlaneObservation:
    payload: dict[str, object] = {
        "source_restore_authorized": True,
        "source_restore_executed": True,
        "restored_source_sha": SOURCE,
        "rebuild_executed": True,
        "rebuilt_source_sha": SOURCE,
        "rebuilt_manifest_sha256": MANIFEST,
        "components": all_components(reconstructed=True),
    }
    payload.update(updates)
    return observation(**payload)


def evaluate(value: SourceControlPlaneObservation):
    return evaluate_source_control_plane_reconstruction(
        value,
        expected_identity=identity(),
    )


def test_corrupted_source_with_complete_evidence_is_ready_for_restore() -> None:
    report = evaluate(observation())

    assert report.source_state == SourceIntegrityState.CORRUPTED
    assert report.trusted_git_state == TrustedGitState.TRUSTED
    assert report.decision == ReconstructionDecision.READY_FOR_GOVERNED_RESTORE
    assert all(
        item.state
        in {
            ReconstructionComponentState.RECONSTRUCTABLE,
            ReconstructionComponentState.VERIFIED,
            ReconstructionComponentState.UNRECOVERABLE,
        }
        for item in report.components
    )
    assert report.artifact_sha256 is not None


def test_full_external_restore_and_reconstruction_is_verified() -> None:
    report = evaluate(fully_executed())

    assert report.decision == ReconstructionDecision.RECONSTRUCTED_AND_VERIFIED
    assert all(item.state == ReconstructionComponentState.VERIFIED for item in report.components)


def test_unrecoverable_ephemeral_state_is_visible() -> None:
    report = evaluate(
        fully_executed(components=all_components(reconstructed=True, ephemeral_present=False))
    )

    assert report.decision == ReconstructionDecision.PARTIALLY_RECONSTRUCTED
    ephemeral = next(
        item
        for item in report.components
        if item.kind == ReconstructionComponentKind.EPHEMERAL_STATE
    )
    assert ephemeral.state == ReconstructionComponentState.UNRECOVERABLE
    assert ReconstructionReason.EPHEMERAL_STATE_UNRECOVERABLE in ephemeral.reasons


def test_untrusted_git_restoration_point_blocks_reconstruction() -> None:
    report = evaluate(
        observation(trusted_git=trusted_git(commit_signature_verified=False))
    )

    assert report.trusted_git_state == TrustedGitState.REJECTED
    assert report.decision == ReconstructionDecision.BLOCKED


def test_missing_ledger_continuity_blocks_reconstruction() -> None:
    components = [
        component(
            item.kind,
            reconstructed=False,
            evidence_present=False,
            identity_verified=False,
            complete=False,
        )
        if item.kind == ReconstructionComponentKind.LEDGER_CONTINUITY
        else item
        for item in all_components(reconstructed=True)
    ]
    report = evaluate(fully_executed(components=components))

    assert report.decision == ReconstructionDecision.BLOCKED
    ledger = next(
        item
        for item in report.components
        if item.kind == ReconstructionComponentKind.LEDGER_CONTINUITY
    )
    assert ReconstructionReason.LEDGER_CONTINUITY_FAILED in ledger.reasons


def test_deterministic_rebuild_mismatch_blocks_completion() -> None:
    report = evaluate(fully_executed(rebuilt_manifest_sha256=OTHER_MANIFEST))
    assert report.decision == ReconstructionDecision.BLOCKED


def test_identity_drift_blocks_even_with_other_evidence() -> None:
    report = evaluate_source_control_plane_reconstruction(
        observation(),
        expected_identity=identity(engine_sha="f" * 40),
    )
    assert report.decision == ReconstructionDecision.BLOCKED


def test_healthy_source_and_verified_control_plane_is_healthy() -> None:
    report = evaluate(
        observation(
            observed_source_head_sha=SOURCE,
            source_history_diverged=False,
            components=all_components(reconstructed=True),
        )
    )

    assert report.source_state == SourceIntegrityState.HEALTHY
    assert report.decision == ReconstructionDecision.HEALTHY


def test_restore_execution_requires_authorization() -> None:
    with pytest.raises(ValidationError, match="without authorization"):
        observation(source_restore_executed=True, restored_source_sha=SOURCE)


def test_missing_or_duplicate_critical_components_are_rejected() -> None:
    missing = [
        item
        for item in all_components(reconstructed=False)
        if item.kind != ReconstructionComponentKind.APPROVALS
    ]
    with pytest.raises(ValidationError, match="missing critical reconstruction components"):
        observation(components=missing)

    duplicate = all_components(reconstructed=False)
    duplicate.append(component(ReconstructionComponentKind.APPROVALS, reconstructed=False))
    with pytest.raises(ValidationError, match="must be unique"):
        observation(components=duplicate)


def test_private_payload_and_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceControlPlaneObservation(
            **observation().model_dump(),
            raw_query="private data",
        )
    with pytest.raises(ValidationError):
        observation(evidence_codes=["https://private.example"])


def test_report_is_deterministic_and_tamper_evident() -> None:
    first = evaluate(observation())
    second = evaluate(
        observation(
            components=list(reversed(all_components(reconstructed=False))),
            evidence_codes=list(
                reversed(["incident.source.corruption", "control_plane.snapshot.loaded"])
            ),
        )
    )

    assert first.artifact_sha256 == second.artifact_sha256
    tampered = first.model_copy(update={"decision": ReconstructionDecision.BLOCKED})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_source_control_plane_report(tampered)


def test_authority_model_rejects_every_mutation_permission() -> None:
    authority = M16SourceControlPlaneAuthority()
    assert not any(authority.model_dump().values())

    for field_name in M16SourceControlPlaneAuthority.model_fields:
        with pytest.raises(ValidationError, match="evidence-only"):
            M16SourceControlPlaneAuthority(**{field_name: True})
