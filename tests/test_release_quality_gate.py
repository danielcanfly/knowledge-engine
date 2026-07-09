from __future__ import annotations

from knowledge_engine.release_quality_gate import (
    GOVERNANCE_NO_WRITE,
    ReleaseQualityGatePolicy,
    evaluate_release_quality_gate,
)

RELEASE_ID = "20260708T040116Z-69a9f445699a"
MANIFEST_SHA = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
SOURCE_SHA = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
POINTER_SHA = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def _artifact(
    artifact_id: str,
    *,
    passed: bool = True,
    release_blocking: bool = False,
    release_id: str = RELEASE_ID,
    manifest_sha256: str = MANIFEST_SHA,
    audiences: list[str] | None = None,
    stale: bool = False,
) -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": artifact_id,
        "passed": passed,
        "release_blocking": release_blocking,
        "stale": stale,
        "release": {
            "release_id": release_id,
            "manifest_sha256": manifest_sha256,
        },
        "audiences": audiences or ["public", "internal"],
    }


def _policy() -> ReleaseQualityGatePolicy:
    return ReleaseQualityGatePolicy(
        gate_id="m12-4-reference-release-quality-gate",
        release_id=RELEASE_ID,
        manifest_sha256=MANIFEST_SHA,
        canonical_source_sha=SOURCE_SHA,
        production_release_id=RELEASE_ID,
        production_manifest_sha256=MANIFEST_SHA,
        production_pointer_sha256=POINTER_SHA,
        reviewer_identity="huaihsuanbusiness",
        reviewed_at="2026-07-09T00:00:00Z",
        notes="M12.4 bundles query evaluation, suite, and baseline checks as release evidence.",
        required_artifact_ids=frozenset(
            {
                "qeval_reference",
                "gqreport_reference",
                "gqbaselinecheck_reference",
            }
        ),
        approved_audiences=frozenset({"public", "internal"}),
    )


def test_release_quality_gate_passes_and_replays() -> None:
    policy = _policy()
    artifacts = [
        _artifact("qeval_reference"),
        _artifact("gqreport_reference"),
        _artifact("gqbaselinecheck_reference"),
    ]

    first = evaluate_release_quality_gate(policy=policy, artifacts=artifacts)
    second = evaluate_release_quality_gate(
        policy=policy, artifacts=list(reversed(artifacts))
    )

    assert first == second
    assert first["schema_version"] == "1.0"
    assert first["gate_policy_id"].startswith("rqgate_")
    assert first["gate_decision_id"].startswith("rqdecision_")
    assert first["passed"] is True
    assert first["release_blocking"] is False
    assert first["failure_reasons"] == []
    assert first["governance"] == GOVERNANCE_NO_WRITE
    assert first["release"]["canonical_source_sha"] == SOURCE_SHA


def test_release_quality_gate_fails_closed_on_missing_duplicate_and_blocking() -> None:
    check = evaluate_release_quality_gate(
        policy=_policy(),
        artifacts=[
            _artifact("qeval_reference"),
            _artifact("qeval_reference", passed=False, release_blocking=True),
            _artifact("gqreport_reference", stale=True),
        ],
    )

    assert check["passed"] is False
    assert check["release_blocking"] is True
    assert check["failure_reasons"] == [
        "artifact_failed",
        "artifact_release_blocking",
        "duplicate_artifact",
        "required_artifact_missing",
        "stale_artifact",
    ]
    assert check["duplicate_artifacts"] == ["qeval_reference"]
    assert check["missing_required_artifacts"] == ["gqbaselinecheck_reference"]


def test_release_quality_gate_fails_closed_on_release_manifest_or_audience_drift() -> None:
    check = evaluate_release_quality_gate(
        policy=_policy(),
        artifacts=[
            _artifact("qeval_reference", release_id="wrong"),
            _artifact("gqreport_reference", manifest_sha256="wrong"),
            _artifact("gqbaselinecheck_reference", audiences=["private"]),
        ],
    )

    assert check["passed"] is False
    assert check["failure_reasons"] == [
        "audience_broadening",
        "manifest_sha256_mismatch",
        "release_id_mismatch",
    ]
    assert check["audience_broadening"] == ["private"]
    assert check["release_mismatches"] == ["qeval_reference"]
    assert check["manifest_mismatches"] == ["gqreport_reference"]


def test_release_quality_gate_requires_complete_policy() -> None:
    try:
        ReleaseQualityGatePolicy(
            gate_id="",
            release_id=RELEASE_ID,
            manifest_sha256=MANIFEST_SHA,
            canonical_source_sha=SOURCE_SHA,
            production_release_id=RELEASE_ID,
            production_manifest_sha256=MANIFEST_SHA,
            production_pointer_sha256=POINTER_SHA,
            reviewer_identity="huaihsuanbusiness",
            reviewed_at="2026-07-09T00:00:00Z",
            notes="complete",
            required_artifact_ids=frozenset({"qeval_reference"}),
            approved_audiences=frozenset({"public"}),
        )
    except ValueError as exc:
        assert str(exc) == "gate_id is required"
    else:  # pragma: no cover
        raise AssertionError("release quality gate policy should fail closed")
