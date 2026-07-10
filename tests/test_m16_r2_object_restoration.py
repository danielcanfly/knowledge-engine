from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_r2_object_restoration import (
    M16R2RestorationAuthority,
    ObjectCondition,
    ObservedReleaseObject,
    ReleaseObjectSpec,
    RestorationDecision,
    RestorationObservation,
    RestoreAction,
    RestoreItemState,
    RetainedReleaseEvidence,
    RetainedReleaseState,
    evaluate_r2_restoration,
    finalize_r2_restoration_report,
)
from knowledge_engine.m16_security_contracts import M16Identity

ENGINE = "872fe9989cf9302b59b81fae6009c7ebac8d4cac"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
SHA_A = "a" * 64
SHA_B = "b" * 64
ETAG_A = "1" * 32
ETAG_B = "2" * 32
NOW = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)


def identity(engine_sha: str = ENGINE) -> M16Identity:
    return M16Identity(
        engine_sha=engine_sha,
        source_sha=SOURCE,
        release_id=RELEASE,
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
    )


def expected_objects() -> list[ReleaseObjectSpec]:
    return [
        ReleaseObjectSpec(
            object_id="release/manifest.json",
            size_bytes=120,
            sha256=SHA_A,
            etag=ETAG_A,
        ),
        ReleaseObjectSpec(
            object_id="release/index.jsonl",
            size_bytes=240,
            sha256=SHA_B,
            etag=ETAG_B,
        ),
    ]


def observed(
    object_id: str,
    *,
    present: bool = True,
    size_bytes: int | None = None,
    sha256: str | None = None,
    etag: str | None = None,
    probe_succeeded: bool = True,
) -> ObservedReleaseObject:
    return ObservedReleaseObject(
        object_id=object_id,
        present=present,
        probe_succeeded=probe_succeeded,
        size_bytes=size_bytes,
        sha256=sha256,
        etag=etag,
    )


def healthy_inventory() -> list[ObservedReleaseObject]:
    return [
        observed(
            "release/manifest.json",
            size_bytes=120,
            sha256=SHA_A,
            etag=ETAG_A,
        ),
        observed(
            "release/index.jsonl",
            size_bytes=240,
            sha256=SHA_B,
            etag=ETAG_B,
        ),
    ]


def retained(*, trusted: bool = True) -> RetainedReleaseEvidence:
    return RetainedReleaseEvidence(
        retained_release_id="retained-20260708-a",
        retained_manifest_sha256=MANIFEST,
        immutable=trusted,
        inventory_complete=trusted,
        manifest_verified=trusted,
        source_sha_verified=trusted,
        objects=healthy_inventory(),
        evidence_codes=["m16.4.retained-release"],
    )


def restoration(
    *,
    observed_objects: list[ObservedReleaseObject] | None = None,
    retained_release: RetainedReleaseEvidence | None = None,
    restore_authorized: bool = False,
    restore_executed: bool = False,
    post_restore_objects: list[ObservedReleaseObject] | None = None,
    report_identity: M16Identity | None = None,
    manifest_reconciled: bool | None = None,
    pointer_unchanged: bool | None = None,
    cache_refreshed: bool | None = None,
    runtime_release_id: str | None = None,
    query_verified: bool | None = None,
    citation_verified: bool | None = None,
    acl_negative_verified: bool | None = None,
) -> RestorationObservation:
    return RestorationObservation(
        drill_id="m16.4-r2-loss-001",
        operation_id="m16.4-restore-001",
        generated_at=NOW,
        identity=report_identity or identity(),
        expected_objects=expected_objects(),
        observed_objects=observed_objects or healthy_inventory(),
        retained_release=retained_release or retained(),
        restore_authorized=restore_authorized,
        restore_executed=restore_executed,
        post_restore_objects=post_restore_objects or [],
        manifest_reconciled=manifest_reconciled,
        pointer_unchanged=pointer_unchanged,
        cache_refreshed=cache_refreshed,
        runtime_release_id=runtime_release_id,
        query_verified=query_verified,
        citation_verified=citation_verified,
        acl_negative_verified=acl_negative_verified,
        evidence_codes=["m16.4.damage-probe", "m16.4.restore-plan"],
    )


def missing_index() -> list[ObservedReleaseObject]:
    return [
        healthy_inventory()[0],
        observed("release/index.jsonl", present=False),
    ]


def test_healthy_release_needs_no_restore() -> None:
    report = evaluate_r2_restoration(restoration(), expected_identity=identity())

    assert report.decision == RestorationDecision.HEALTHY
    assert all(item.condition == ObjectCondition.HEALTHY for item in report.objects)
    assert all(item.action == RestoreAction.NO_ACTION for item in report.objects)


def test_missing_object_produces_governed_restore_plan() -> None:
    report = evaluate_r2_restoration(
        restoration(observed_objects=missing_index()),
        expected_identity=identity(),
    )

    target = next(item for item in report.objects if item.object_id.endswith("index.jsonl"))
    assert report.decision == RestorationDecision.READY_FOR_GOVERNED_RESTORE
    assert target.condition == ObjectCondition.MISSING
    assert target.action == RestoreAction.COPY_FROM_RETAINED_RELEASE
    assert target.state == RestoreItemState.PLANNED


def test_completed_restore_requires_all_runtime_verification() -> None:
    report = evaluate_r2_restoration(
        restoration(
            observed_objects=missing_index(),
            restore_authorized=True,
            restore_executed=True,
            post_restore_objects=healthy_inventory(),
            manifest_reconciled=True,
            pointer_unchanged=True,
            cache_refreshed=True,
            runtime_release_id=RELEASE,
            query_verified=True,
            citation_verified=True,
            acl_negative_verified=True,
        ),
        expected_identity=identity(),
    )

    assert report.decision == RestorationDecision.RESTORED_AND_VERIFIED
    target = next(item for item in report.objects if item.object_id.endswith("index.jsonl"))
    assert target.state == RestoreItemState.VERIFIED


def test_bad_post_restore_digest_blocks_closeout() -> None:
    post = healthy_inventory()
    post[1] = post[1].model_copy(update={"sha256": "c" * 64})
    report = evaluate_r2_restoration(
        restoration(
            observed_objects=missing_index(),
            restore_authorized=True,
            restore_executed=True,
            post_restore_objects=post,
            manifest_reconciled=True,
            pointer_unchanged=True,
            cache_refreshed=True,
            runtime_release_id=RELEASE,
            query_verified=True,
            citation_verified=True,
            acl_negative_verified=True,
        ),
        expected_identity=identity(),
    )

    assert report.decision == RestorationDecision.BLOCKED
    target = next(item for item in report.objects if item.object_id.endswith("index.jsonl"))
    assert target.state == RestoreItemState.BLOCKED


def test_untrusted_retained_release_cannot_be_used() -> None:
    report = evaluate_r2_restoration(
        restoration(
            observed_objects=missing_index(),
            retained_release=retained(trusted=False),
        ),
        expected_identity=identity(),
    )

    assert report.retained_release_state == RetainedReleaseState.REJECTED
    assert report.decision == RestorationDecision.BLOCKED


def test_identity_drift_fails_closed() -> None:
    report = evaluate_r2_restoration(
        restoration(
            observed_objects=missing_index(),
            report_identity=identity(engine_sha="f" * 40),
        ),
        expected_identity=identity(),
    )

    assert report.decision == RestorationDecision.BLOCKED


def test_pointer_or_acl_verification_failure_blocks_restore() -> None:
    report = evaluate_r2_restoration(
        restoration(
            observed_objects=missing_index(),
            restore_authorized=True,
            restore_executed=True,
            post_restore_objects=healthy_inventory(),
            manifest_reconciled=True,
            pointer_unchanged=False,
            cache_refreshed=True,
            runtime_release_id=RELEASE,
            query_verified=True,
            citation_verified=True,
            acl_negative_verified=False,
        ),
        expected_identity=identity(),
    )

    assert report.decision == RestorationDecision.BLOCKED


def test_duplicate_object_ids_are_rejected() -> None:
    duplicate = healthy_inventory()
    duplicate.append(healthy_inventory()[0])
    with pytest.raises(ValidationError, match="duplicate object IDs"):
        restoration(observed_objects=duplicate)


def test_non_utc_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        restoration().model_copy(
            update={"generated_at": datetime(2026, 7, 10, 6, 0)},
        ).model_validate(
            restoration().model_dump() | {"generated_at": datetime(2026, 7, 10, 6, 0)},
        )


def test_private_object_uri_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReleaseObjectSpec(
            object_id="r2://private/object",
            size_bytes=1,
            sha256=SHA_A,
        )


def test_restore_execution_requires_authorization() -> None:
    with pytest.raises(ValidationError, match="without authorization"):
        restoration(
            observed_objects=missing_index(),
            restore_executed=True,
            post_restore_objects=healthy_inventory(),
        )


def test_no_write_authority_is_enforced() -> None:
    M16R2RestorationAuthority()
    with pytest.raises(ValidationError, match="evidence-only"):
        M16R2RestorationAuthority(r2_copy_allowed=True)


def test_report_digest_is_deterministic_and_tamper_evident() -> None:
    report = evaluate_r2_restoration(
        restoration(observed_objects=missing_index()),
        expected_identity=identity(),
    )
    reversed_observation = restoration(
        observed_objects=list(reversed(missing_index())),
    )
    reversed_observation = reversed_observation.model_copy(
        update={"expected_objects": list(reversed(expected_objects()))},
    )
    reversed_report = evaluate_r2_restoration(
        reversed_observation,
        expected_identity=identity(),
    )

    assert report.artifact_sha256 == reversed_report.artifact_sha256
    tampered = report.model_copy(update={"decision": RestorationDecision.BLOCKED})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_r2_restoration_report(tampered)
