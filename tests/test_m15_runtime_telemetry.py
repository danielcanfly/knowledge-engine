from datetime import UTC, datetime

import pytest

from knowledge_engine.m15_observability_contracts import EventFamily, ObservabilityIdentity
from knowledge_engine.m15_runtime_telemetry import (
    InMemoryTelemetrySink,
    RuntimeTelemetry,
    bucket_count,
    bucket_latency,
)

ENGINE = "252e345a7ee01af10d9151a33a318531629c8eda"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"


def identity(request_id: str = "request-0001") -> ObservabilityIdentity:
    return ObservabilityIdentity(
        engine_sha=ENGINE,
        canonical_source_sha=SOURCE,
        release_id="20260708T040116Z-69a9f445699a",
        manifest_sha256=MANIFEST,
        pointer_sha256=POINTER,
        request_id=request_id,
    )


def test_records_privacy_safe_runtime_event() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = RuntimeTelemetry(sink=sink)
    result = telemetry.emit(
        family=EventFamily.RUNTIME_REQUEST,
        event_name="request_started",
        identity=identity(),
        dimensions={"audience": "public", "surface": "api", "transport": "json"},
        occurred_at=datetime(2026, 7, 10, 4, 40, tzinfo=UTC),
    )
    assert result.recorded is True
    assert len(sink.events) == 1
    payload = sink.events[0].model_dump(mode="json")
    assert "query" not in str(payload).lower()
    assert telemetry.metric_snapshot() == {"recorded_request_started": 1}


@pytest.mark.parametrize(
    "attributes",
    [
        {"raw_query": "secret"},
        {"answer": "private"},
        {"authorization": "Bearer abc.def.ghi"},
        {"private_source_excerpt": "internal"},
        {"url": "r2://private/object"},
    ],
)
def test_rejects_unapproved_or_sensitive_attributes(attributes: dict[str, str]) -> None:
    telemetry = RuntimeTelemetry(sink=InMemoryTelemetrySink())
    with pytest.raises(ValueError):
        telemetry.emit(
            family=EventFamily.RUNTIME_REQUEST,
            event_name="request_started",
            identity=identity(),
            dimensions={"audience": "public"},
            attributes=attributes,
        )


def test_sink_failure_is_fail_open_and_counted() -> None:
    class BrokenSink:
        def write(self, event: object) -> None:
            raise RuntimeError("Bearer should never leak")

    telemetry = RuntimeTelemetry(sink=BrokenSink())
    answer = {"status": "answered", "answer": "unchanged"}
    result = telemetry.emit(
        family=EventFamily.RUNTIME_REQUEST,
        event_name="answer_completed",
        identity=identity(),
        dimensions={"status": "answered"},
    )
    assert answer == {"status": "answered", "answer": "unchanged"}
    assert result.recorded is False
    assert result.drop_reason == "sink_failure"
    assert telemetry.metric_snapshot() == {"dropped_sink_failure": 1}


def test_security_events_are_never_sampled_out() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = RuntimeTelemetry(sink=sink, sampling_rate=0.0)
    ordinary = telemetry.emit(
        family=EventFamily.RUNTIME_REQUEST,
        event_name="request_started",
        identity=identity("request-ordinary"),
        dimensions={"audience": "public"},
    )
    security = telemetry.emit(
        family=EventFamily.ACL_FILTERING,
        event_name="security_rejected",
        identity=identity("request-security"),
        dimensions={"status": "rejected", "severity": "high"},
    )
    assert ordinary.recorded is False
    assert security.recorded is True
    assert len(sink.events) == 1


def test_duplicate_event_is_dropped_deterministically() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = RuntimeTelemetry(sink=sink)
    kwargs = dict(
        family=EventFamily.CITATION,
        event_name="citations_assembled",
        identity=identity(),
        dimensions={"status": "success"},
        occurred_at=datetime(2026, 7, 10, 4, 45, tzinfo=UTC),
    )
    first = telemetry.emit(**kwargs)
    second = telemetry.emit(**kwargs)
    assert first.recorded is True
    assert second.drop_reason == "duplicate"
    assert len(sink.events) == 1


def test_metric_snapshot_has_no_high_cardinality_identity() -> None:
    telemetry = RuntimeTelemetry(sink=InMemoryTelemetrySink())
    telemetry.emit(
        family=EventFamily.RETRIEVAL,
        event_name="retrieval_completed",
        identity=identity("request-high-cardinality"),
        dimensions={"status": "success"},
        attributes={"result_count_bucket": bucket_count(7)},
    )
    snapshot = telemetry.metric_snapshot()
    text = str(snapshot)
    assert "request-high-cardinality" not in text
    assert "20260708T040116Z" not in text


def test_unknown_event_and_dimensions_fail_closed() -> None:
    telemetry = RuntimeTelemetry(sink=InMemoryTelemetrySink())
    with pytest.raises(ValueError):
        telemetry.emit(
            family=EventFamily.RUNTIME_REQUEST,
            event_name="raw_prompt_logged",
            identity=identity(),
            dimensions={"audience": "public"},
        )
    with pytest.raises(ValueError):
        telemetry.emit(
            family=EventFamily.RUNTIME_REQUEST,
            event_name="request_started",
            identity=identity(),
            dimensions={"request_id": "request-0001"},
        )


def test_buckets_are_closed_and_deterministic() -> None:
    assert [bucket_count(v) for v in (0, 1, 6, 21)] == ["0", "1_5", "6_20", "21_plus"]
    assert [bucket_latency(v) for v in (0.01, 0.2, 1.0, 3.0)] == [
        "lt_100ms",
        "100_499ms",
        "500ms_1999ms",
        "2s_plus",
    ]
    with pytest.raises(ValueError):
        bucket_count(-1)
    with pytest.raises(ValueError):
        bucket_latency(-0.1)
