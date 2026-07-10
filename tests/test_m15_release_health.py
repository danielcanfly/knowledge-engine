from datetime import UTC, datetime

from knowledge_engine.m15_observability_contracts import ObservabilityIdentity
from knowledge_engine.m15_release_health import (
    ExpectedObject,
    HealthBaseline,
    HealthIssueCode,
    HealthState,
    ObservedObject,
    evaluate_release_health,
)

ENGINE = "33dac39094071e7f057b1f9cb8bb78c9ab9b8fc3"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
RELEASE = "20260708T040116Z-69a9f445699a"
DIGEST = "a" * 64


def identity() -> ObservabilityIdentity:
    return ObservabilityIdentity(
        engine_sha=ENGINE,
        canonical_source_sha=SOURCE,
        release_id=RELEASE,
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
        operation_id="health-op-0001",
    )


def baseline() -> HealthBaseline:
    return HealthBaseline(RELEASE, MANIFEST, POINTER, RELEASE)


def test_healthy_report_is_deterministic() -> None:
    kwargs = dict(
        identity=identity(),
        expected=baseline(),
        observed_release_id=RELEASE,
        observed_manifest_sha256=MANIFEST,
        observed_pointer_sha256=POINTER,
        observed_cache_release_id=RELEASE,
        expected_objects=[ExpectedObject(object_id="release/manifest.json", size_bytes=10, sha256=DIGEST)],
        observed_objects=[ObservedObject(object_id="release/manifest.json", present=True, size_bytes=10, sha256=DIGEST)],
        generated_at=datetime(2026, 7, 10, 5, 0, tzinfo=UTC),
    )
    first = evaluate_release_health(**kwargs)
    second = evaluate_release_health(**kwargs)
    assert first.state == HealthState.HEALTHY
    assert first.artifact_sha256 == second.artifact_sha256


def test_identity_drift_and_stale_cache_are_reported() -> None:
    report = evaluate_release_health(
        identity=identity(), expected=baseline(), observed_release_id="wrong",
        observed_manifest_sha256="b" * 64, observed_pointer_sha256="c" * 64,
        observed_cache_release_id="stale", expected_objects=[], observed_objects=[]
    )
    codes = {issue.code for issue in report.issues}
    assert report.state == HealthState.UNHEALTHY
    assert {HealthIssueCode.RELEASE_DRIFT, HealthIssueCode.MANIFEST_DRIFT, HealthIssueCode.POINTER_DRIFT, HealthIssueCode.CACHE_STALE}.issubset(codes)


def test_missing_digest_mismatch_and_duplicate_are_reported() -> None:
    expected = [
        ExpectedObject(object_id="a.json", size_bytes=2, sha256=DIGEST),
        ExpectedObject(object_id="b.json", size_bytes=3, sha256=DIGEST),
    ]
    observed = [
        ObservedObject(object_id="a.json", present=True, size_bytes=2, sha256="b" * 64),
        ObservedObject(object_id="a.json", present=True, size_bytes=2, sha256="b" * 64),
    ]
    report = evaluate_release_health(
        identity=identity(), expected=baseline(), observed_release_id=RELEASE,
        observed_manifest_sha256=MANIFEST, observed_pointer_sha256=POINTER,
        observed_cache_release_id=RELEASE, expected_objects=expected, observed_objects=observed
    )
    codes = [issue.code for issue in report.issues]
    assert HealthIssueCode.OBJECT_MISSING in codes
    assert HealthIssueCode.OBJECT_DIGEST_MISMATCH in codes
    assert HealthIssueCode.DUPLICATE_OBJECT in codes


def test_probe_failure_is_unknown_not_healthy() -> None:
    report = evaluate_release_health(
        identity=identity(), expected=baseline(), observed_release_id=RELEASE,
        observed_manifest_sha256=MANIFEST, observed_pointer_sha256=POINTER,
        observed_cache_release_id=RELEASE, expected_objects=[], observed_objects=[], probe_failed=True
    )
    assert report.state == HealthState.UNKNOWN
    assert report.issues[0].code == HealthIssueCode.PROBE_FAILURE
