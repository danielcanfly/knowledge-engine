from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .m15_observability_contracts import (
    EventFamily,
    ObservabilityEvent,
    ObservabilityIdentity,
    RetentionClass,
)

M15_RUNTIME_TELEMETRY_SCHEMA = "knowledge-engine-runtime-telemetry/v1"
RUNTIME_EVENT_NAMES = frozenset(
    {
        "request_started",
        "retrieval_completed",
        "acl_filter_completed",
        "citations_assembled",
        "answer_completed",
        "feedback_received",
        "security_rejected",
        "telemetry_dropped",
    }
)
SECURITY_EVENT_NAMES = frozenset({"security_rejected"})
ALLOWED_ATTRIBUTES = frozenset(
    {
        "result_count_bucket",
        "citation_count_bucket",
        "latency_bucket",
        "drop_reason",
        "sample_key_hash",
    }
)


class TelemetrySink(Protocol):
    def write(self, event: ObservabilityEvent) -> None: ...


@dataclass
class InMemoryTelemetrySink:
    events: list[ObservabilityEvent] = field(default_factory=list)

    def write(self, event: ObservabilityEvent) -> None:
        self.events.append(event)


@dataclass
class JsonlTelemetrySink:
    path: Path

    def write(self, event: ObservabilityEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@dataclass(frozen=True)
class EmitResult:
    recorded: bool
    sampled: bool
    drop_reason: str | None = None


@dataclass
class RuntimeTelemetry:
    sink: TelemetrySink
    sampling_rate: float = 1.0
    counters: Counter[str] = field(default_factory=Counter)
    seen_event_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not 0.0 <= self.sampling_rate <= 1.0:
            raise ValueError("sampling_rate must be in [0, 1]")

    @staticmethod
    def _sample_value(sample_key: str) -> float:
        digest = hashlib.sha256(sample_key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)

    @staticmethod
    def _event_id(event: ObservabilityEvent) -> str:
        payload = event.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _should_sample(self, event_name: str, sample_key: str) -> bool:
        if event_name in SECURITY_EVENT_NAMES:
            return True
        return self._sample_value(sample_key) < self.sampling_rate

    def emit(
        self,
        *,
        family: EventFamily,
        event_name: str,
        identity: ObservabilityIdentity,
        dimensions: dict[str, str],
        measurements: dict[str, float | int] | None = None,
        attributes: dict[str, str | int | float | bool | None] | None = None,
        occurred_at: datetime | None = None,
        retention: RetentionClass = RetentionClass.OPERATIONAL_30D,
        sample_key: str | None = None,
    ) -> EmitResult:
        if event_name not in RUNTIME_EVENT_NAMES:
            raise ValueError(f"unknown runtime telemetry event: {event_name}")
        attrs = dict(attributes or {})
        unknown_attrs = sorted(set(attrs) - ALLOWED_ATTRIBUTES)
        if unknown_attrs:
            raise ValueError(f"unapproved telemetry attributes: {unknown_attrs}")
        key = sample_key or identity.request_id or identity.operation_id
        if key is None:
            raise ValueError("sampling requires request_id or operation_id")
        sampled = self._should_sample(event_name, key)
        if not sampled:
            self.counters["dropped_sampling"] += 1
            return EmitResult(recorded=False, sampled=False, drop_reason="sampling")
        event = ObservabilityEvent(
            family=family,
            event_name=event_name,
            occurred_at=occurred_at or datetime.now(UTC),
            identity=identity,
            retention=retention,
            sampled=True,
            dimensions=dimensions,
            measurements=measurements or {},
            attributes=attrs,
        )
        event_id = self._event_id(event)
        if event_id in self.seen_event_ids:
            self.counters["dropped_duplicate"] += 1
            return EmitResult(recorded=False, sampled=True, drop_reason="duplicate")
        try:
            self.sink.write(event)
        except Exception:
            self.counters["dropped_sink_failure"] += 1
            return EmitResult(recorded=False, sampled=True, drop_reason="sink_failure")
        self.seen_event_ids.add(event_id)
        self.counters[f"recorded_{event_name}"] += 1
        return EmitResult(recorded=True, sampled=True)

    def metric_snapshot(self) -> dict[str, int]:
        return dict(sorted(self.counters.items()))


def bucket_count(value: int) -> str:
    if value < 0:
        raise ValueError("count cannot be negative")
    if value == 0:
        return "0"
    if value <= 5:
        return "1_5"
    if value <= 20:
        return "6_20"
    return "21_plus"


def bucket_latency(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("latency cannot be negative")
    if seconds < 0.1:
        return "lt_100ms"
    if seconds < 0.5:
        return "100_499ms"
    if seconds < 2.0:
        return "500ms_1999ms"
    return "2s_plus"
