from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from knowledge_engine.m15_observability_contracts import (
    EventFamily,
    FieldDisposition,
    GovernanceBoundary,
    MetricDefinition,
    ObservabilityContract,
    ObservabilityEvent,
    ObservabilityIdentity,
    ObservabilityReport,
    PrivacyFieldRule,
    PrivacyPolicy,
    RetentionClass,
    finalize_report,
)

ENGINE = "0d77598a530b59d5bb6006da282b7728bb21a751"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def identity() -> ObservabilityIdentity:
    return ObservabilityIdentity(
        engine_sha=ENGINE,
        canonical_source_sha=SOURCE,
        release_id="20260708T040116Z-69a9f445699a",
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
        request_id="req-12345678",
    )


def policy() -> PrivacyPolicy:
    return PrivacyPolicy(
        field_rules=[
            PrivacyFieldRule(field="raw_query", disposition=FieldDisposition.FORBIDDEN, transform="drop"),
            PrivacyFieldRule(field="raw_answer", disposition=FieldDisposition.FORBIDDEN, transform="drop"),
            PrivacyFieldRule(field="client_ip", disposition=FieldDisposition.FORBIDDEN, transform="drop"),
            PrivacyFieldRule(field="request_id", disposition=FieldDisposition.TRANSFORMED, transform="sha256"),
        ]
    )


def contract() -> ObservabilityContract:
    return ObservabilityContract(
        event_families=list(EventFamily),
        metrics=[
            MetricDefinition(
                name="knowledge_engine_request_total",
                unit="count",
                description="Bounded request count.",
                dimensions=["audience", "status", "surface"],
                max_series=256,
            ),
            MetricDefinition(
                name="knowledge_engine_request_latency_seconds",
                unit="seconds",
                description="End-to-end request latency.",
                dimensions=["status", "surface"],
                max_series=128,
            ),
        ],
        privacy=policy(),
    )


def test_contract_and_report_are_deterministic() -> None:
    report = ObservabilityReport(
        contract=contract(),
        generated_at=datetime(2026, 7, 10, 4, 30, tzinfo=timezone.utc),
        baseline=identity(),
    )
    first = finalize_report(report)
    second = finalize_report(report)
    assert first.artifact_sha256 == second.artifact_sha256
    assert len(first.artifact_sha256 or "") == 64


def test_event_accepts_only_bounded_privacy_safe_payload() -> None:
    event = ObservabilityEvent(
        family=EventFamily.RUNTIME_REQUEST,
        event_name="request_completed",
        occurred_at=datetime.now(timezone.utc),
        identity=identity(),
        retention=RetentionClass.OPERATIONAL_30D,
        dimensions={"audience": "public", "status": "answered"},
        measurements={"latency_seconds": 0.12},
        attributes={"citation_count": 2, "sample_class": "full"},
    )
    assert event.identity.engine_sha == ENGINE


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("raw_query", "secret question"),
        ("raw_answer", "private answer"),
        ("authorization", "Bearer abc.def.ghi"),
        ("client_ip", "203.0.113.4"),
        ("source_excerpt", "internal paragraph"),
    ],
)
def test_event_rejects_forbidden_fields(key: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ObservabilityEvent(
            family=EventFamily.RUNTIME_REQUEST,
            event_name="request_completed",
            occurred_at=datetime.now(timezone.utc),
            identity=identity(),
            retention=RetentionClass.OPERATIONAL_30D,
            attributes={key: value},
        )


@pytest.mark.parametrize("value", ["Bearer token-value", "eyJabc.def.ghi", "r2://private/key"])
def test_event_rejects_sensitive_values_even_under_allowed_key(value: str) -> None:
    with pytest.raises(ValidationError):
        ObservabilityEvent(
            family=EventFamily.CITATION,
            event_name="citation_rendered",
            occurred_at=datetime.now(timezone.utc),
            identity=identity(),
            retention=RetentionClass.OPERATIONAL_30D,
            attributes={"result": value},
        )


def test_metric_rejects_unbounded_dimensions() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            name="knowledge_engine_bad_total",
            unit="count",
            description="Bad high-cardinality metric.",
            dimensions=["request_id"],
            max_series=100,
        )


def test_event_rejects_non_utc_timestamp() -> None:
    with pytest.raises(ValidationError):
        ObservabilityEvent(
            family=EventFamily.RETRIEVAL,
            event_name="retrieval_completed",
            occurred_at=datetime(2026, 7, 10, 4, 30),
            identity=identity(),
            retention=RetentionClass.OPERATIONAL_30D,
        )


def test_release_requires_manifest_identity() -> None:
    with pytest.raises(ValidationError):
        ObservabilityIdentity(
            engine_sha=ENGINE,
            canonical_source_sha=SOURCE,
            release_id="release-without-manifest",
            request_id="req-12345678",
        )


def test_closed_event_family_set_cannot_drift() -> None:
    with pytest.raises(ValidationError):
        ObservabilityContract(
            event_families=[EventFamily.RUNTIME_REQUEST],
            metrics=[],
            privacy=policy(),
        )


def test_contract_only_slice_rejects_write_authority() -> None:
    with pytest.raises(ValidationError):
        GovernanceBoundary(production_write_allowed=True)
    with pytest.raises(ValidationError):
        GovernanceBoundary(permanent_ledger_append_allowed=True)


def test_privacy_switches_cannot_enable_raw_collection() -> None:
    with pytest.raises(ValidationError):
        PrivacyPolicy(raw_query_collected=True, field_rules=[])
    with pytest.raises(ValidationError):
        PrivacyFieldRule(field="jwt_claims", disposition=FieldDisposition.ALLOWED)
