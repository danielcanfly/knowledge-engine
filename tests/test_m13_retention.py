from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.m13_contracts import ProductionIdentity
from knowledge_engine.m13_retention import (
    M13RetentionError,
    RetentionArtifact,
    RetentionReferenceSnapshot,
    RetentionReviewApproval,
    classify_artifact,
    create_retention_plan,
)
from knowledge_engine.storage import FileObjectStore

PRODUCTION = ProductionIdentity(
    release_id="20260708T040116Z-69a9f445699a",
    manifest_sha256="2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb",
    pointer_sha256="38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5",
)
BATCH_ID = "mbatch_" + "a" * 32
CHANNEL = "candidate-m13-retention-a"


def _references(**overrides):
    values = {
        "observed_at": "2026-07-09T09:00:00Z",
        "production": PRODUCTION,
        "open_batch_ids": (),
        "active_candidate_channels": (),
        "referenced_release_ids": (),
        "rollback_release_ids": (),
        "referenced_artifact_ids": (),
    }
    values.update(overrides)
    return RetentionReferenceSnapshot(**values)


def test_permanent_classes_can_never_become_deletion_candidates() -> None:
    references = _references()
    for artifact_class in (
        "evidence",
        "registry_history",
        "coordination_evidence",
        "production_identity",
    ):
        artifact = RetentionArtifact(
            key=f"m13/evidence/{artifact_class}.json",
            artifact_class=artifact_class,
            created_at="2020-01-01T00:00:00Z",
            sha256="a" * 64,
        )
        decision = classify_artifact(
            artifact,
            references=references,
            generated_at="2026-07-09T09:01:00Z",
        )
        assert decision.disposition == "permanent"
        assert decision.physical_delete_permitted is False


def test_current_production_and_rollback_release_are_protected() -> None:
    current = RetentionArtifact(
        key=f"releases/{PRODUCTION.release_id}/manifest.json",
        artifact_class="release",
        created_at="2020-01-01T00:00:00Z",
        sha256="b" * 64,
        release_id=PRODUCTION.release_id,
    )
    rollback_id = "20260701T010203Z-aaaaaaaaaaaa"
    rollback = RetentionArtifact(
        key=f"releases/{rollback_id}/manifest.json",
        artifact_class="rollback_target",
        created_at="2020-01-01T00:00:00Z",
        sha256="c" * 64,
        release_id=rollback_id,
    )
    references = _references(rollback_release_ids=(rollback_id,))
    current_decision = classify_artifact(
        current,
        references=references,
        generated_at="2026-07-09T09:01:00Z",
    )
    rollback_decision = classify_artifact(
        rollback,
        references=references,
        generated_at="2026-07-09T09:01:00Z",
    )
    assert current_decision.disposition == "protected"
    assert "release_is_current_production" in current_decision.reasons
    assert rollback_decision.disposition == "protected"
    assert "release_is_rollback_target" in rollback_decision.reasons


def test_active_candidate_and_open_batch_raw_snapshot_are_protected() -> None:
    candidate = RetentionArtifact(
        key=f"candidates/{CHANNEL}/manifest.json",
        artifact_class="candidate",
        created_at="2025-01-01T00:00:00Z",
        sha256="d" * 64,
        batch_id=BATCH_ID,
        candidate_channel=CHANNEL,
        terminal_at="2025-01-02T00:00:00Z",
    )
    raw = RetentionArtifact(
        key=f"raw/{BATCH_ID}/snapshot.json",
        artifact_class="raw_snapshot",
        created_at="2025-01-01T00:00:00Z",
        sha256="e" * 64,
        batch_id=BATCH_ID,
    )
    references = _references(
        open_batch_ids=(BATCH_ID,),
        active_candidate_channels=(CHANNEL,),
    )
    assert (
        classify_artifact(
            candidate,
            references=references,
            generated_at="2026-07-09T09:01:00Z",
        ).disposition
        == "protected"
    )
    assert (
        classify_artifact(
            raw,
            references=references,
            generated_at="2026-07-09T09:01:00Z",
        ).disposition
        == "protected"
    )


def test_elapsed_time_alone_never_authorizes_deletion() -> None:
    artifact = RetentionArtifact(
        key=f"candidates/{CHANNEL}/manifest.json",
        artifact_class="candidate",
        created_at="2025-01-01T00:00:00Z",
        sha256="f" * 64,
        batch_id=BATCH_ID,
        candidate_channel=CHANNEL,
        terminal_at="2025-01-02T00:00:00Z",
    )
    references = _references()
    decision = classify_artifact(
        artifact,
        references=references,
        generated_at="2026-07-09T09:01:00Z",
    )
    assert decision.disposition == "quarantine"
    assert decision.reasons == ("explicit_retention_review_required",)
    assert decision.physical_delete_permitted is False


def test_exact_review_can_only_create_non_destructive_deletion_candidate() -> None:
    artifact = RetentionArtifact(
        key=f"candidates/{CHANNEL}/manifest.json",
        artifact_class="candidate",
        created_at="2025-01-01T00:00:00Z",
        sha256="1" * 64,
        batch_id=BATCH_ID,
        candidate_channel=CHANNEL,
        terminal_at="2025-01-02T00:00:00Z",
    )
    references = _references()
    approval = RetentionReviewApproval(
        reviewed_by="reviewer@example.com",
        reviewed_at="2026-07-09T08:59:00Z",
        reference_snapshot_sha256=references.snapshot_sha256(),
        approved_artifact_ids=(artifact.artifact_id(),),
        rationale="No live references remain after the quarantine period.",
    )
    decision = classify_artifact(
        artifact,
        references=references,
        generated_at="2026-07-09T09:01:00Z",
        approval=approval,
    )
    assert decision.disposition == "deletion_candidate"
    assert decision.review_id == approval.review_id()
    assert decision.physical_delete_permitted is False


def test_stale_reference_snapshot_rejects_review() -> None:
    artifact = RetentionArtifact(
        key="raw/archive/snapshot.json",
        artifact_class="raw_snapshot",
        created_at="2025-01-01T00:00:00Z",
        sha256="2" * 64,
    )
    references = _references()
    approval = RetentionReviewApproval(
        reviewed_by="reviewer@example.com",
        reviewed_at="2026-07-09T08:59:00Z",
        reference_snapshot_sha256="3" * 64,
        approved_artifact_ids=(artifact.artifact_id(),),
        rationale="Review used an older inventory snapshot.",
    )
    with pytest.raises(M13RetentionError) as stale:
        classify_artifact(
            artifact,
            references=references,
            generated_at="2026-07-09T09:01:00Z",
            approval=approval,
        )
    assert stale.value.code == "M13_RETENTION_REFERENCE_SNAPSHOT_STALE"


def test_retention_plan_is_immutable_and_replayable(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    artifact = RetentionArtifact(
        key="raw/archive/snapshot.json",
        artifact_class="raw_snapshot",
        created_at="2025-01-01T00:00:00Z",
        sha256="4" * 64,
    )
    references = _references()
    approval = RetentionReviewApproval(
        reviewed_by="reviewer@example.com",
        reviewed_at="2026-07-09T08:59:00Z",
        reference_snapshot_sha256=references.snapshot_sha256(),
        approved_artifact_ids=(artifact.artifact_id(),),
        rationale="Artifact is unreferenced and outside minimum retention.",
    )
    first = create_retention_plan(
        store,
        artifacts=(artifact,),
        references=references,
        generated_at="2026-07-09T09:01:00Z",
        approval=approval,
    )
    replay = create_retention_plan(
        store,
        artifacts=(artifact,),
        references=references,
        generated_at="2026-07-09T09:01:00Z",
        approval=approval,
    )
    assert first.plan_id == replay.plan_id
    assert replay.idempotent is True
    assert store.head(first.artifact_key) is not None
    assert replay.decisions[0].physical_delete_permitted is False


def test_review_cannot_approve_artifact_outside_plan(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    artifact = RetentionArtifact(
        key="raw/archive/snapshot.json",
        artifact_class="raw_snapshot",
        created_at="2025-01-01T00:00:00Z",
        sha256="5" * 64,
    )
    references = _references()
    approval = RetentionReviewApproval(
        reviewed_by="reviewer@example.com",
        reviewed_at="2026-07-09T08:59:00Z",
        reference_snapshot_sha256=references.snapshot_sha256(),
        approved_artifact_ids=("martifact_" + "6" * 32,),
        rationale="Incorrect approval scope.",
    )
    with pytest.raises(M13RetentionError) as unknown:
        create_retention_plan(
            store,
            artifacts=(artifact,),
            references=references,
            generated_at="2026-07-09T09:01:00Z",
            approval=approval,
        )
    assert unknown.value.code == "M13_RETENTION_APPROVAL_UNKNOWN_ARTIFACT"
