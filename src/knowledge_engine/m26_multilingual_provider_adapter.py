from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ProviderPurpose = Literal[
    "multilingual_canonicalization",
    "multilingual_requested_language_realization",
    "multilingual_equivalence_review",
]


@dataclass(frozen=True)
class LanguageProviderCall:
    purpose: ProviderPurpose
    provider: str
    model: str
    status: str
    latency_ms: int
    error_class: str = ""

    def as_event(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "model.completed",
            "role": self.purpose,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "latency_ms": self.latency_ms,
        }
        if self.error_class:
            payload["error_class"] = self.error_class
        return payload


@dataclass
class LanguageProviderTelemetry:
    calls: list[LanguageProviderCall] = field(default_factory=list)

    def record(
        self,
        *,
        purpose: ProviderPurpose,
        provider: str,
        model: str,
        status: str,
        latency_ms: int,
        error_class: str = "",
    ) -> None:
        self.calls.append(
            LanguageProviderCall(
                purpose=purpose,
                provider=provider,
                model=model,
                status=status,
                latency_ms=latency_ms,
                error_class=error_class,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_calls": [
                {
                    "purpose": call.purpose,
                    "provider": call.provider,
                    "model": call.model,
                    "status": call.status,
                    "latency_ms": call.latency_ms,
                    "error_class": call.error_class,
                }
                for call in self.calls
            ],
            "provider_call_purposes": [call.purpose for call in self.calls],
        }


class PurposeRecordingAdapter:
    def __init__(
        self,
        *,
        purpose: ProviderPurpose,
        callable_: Callable[[Any], Any],
        telemetry: LanguageProviderTelemetry,
        provider: str = "configured-internal",
        model: str = "configured-internal",
    ) -> None:
        self.purpose = purpose
        self.callable = callable_
        self.telemetry = telemetry
        self.provider = provider
        self.model = model

    def __call__(self, request: Any) -> Any:
        started = time.monotonic()
        try:
            result = self.callable(request)
        except Exception as exc:
            self.telemetry.record(
                purpose=self.purpose,
                provider=self.provider,
                model=self.model,
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                error_class=type(exc).__name__,
            )
            raise
        self.telemetry.record(
            purpose=self.purpose,
            provider=self.provider,
            model=self.model,
            status="completed",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def canonicalize(self, request: Any) -> Any:
        return self(request)


def sanitized_provider_event(
    *,
    purpose: ProviderPurpose,
    status: str,
    provider: str = "configured-internal",
    model: str = "configured-internal",
    latency_ms: int = 0,
) -> Mapping[str, Any]:
    return {
        "type": "model.completed",
        "role": purpose,
        "provider": provider,
        "model": model,
        "status": status,
        "latency_ms": latency_ms,
    }
