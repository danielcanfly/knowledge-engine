from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .intake_v1 import IntakeFailure, IntakeResult, _validate_utc
from .storage import ObjectStore
from .web_intake_v1 import (
    HTTPExchange,
    HTTPExchangeResult,
    Resolver,
    Sleeper,
    WebURLRequest as _WebURLRequest,
    _default_exchange,
    _default_resolver,
    canonicalize_https_url,
    intake_web_url as _intake_web_url,
    validate_public_ips,
)

MAX_RESPONSE_HEADERS = 64
MAX_HEADER_VALUE_BYTES = 2048
MAX_LOCATION_BYTES = 4096
MAX_VERSION_HEADER_BYTES = 512


@dataclass(frozen=True)
class WebURLRequest(_WebURLRequest):
    """Public M10.3 request contract with UTC validation."""

    def validate(self) -> None:
        _validate_utc(self.retrieved_at)
        super().validate()


def _guarded_exchange(exchange: HTTPExchange) -> HTTPExchange:
    def guarded(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        result = exchange(
            url,
            connected_ip,
            timeout_seconds,
            max_compressed_bytes,
            headers,
        )
        if len(result.headers) > MAX_RESPONSE_HEADERS:
            raise IntakeFailure(
                "RESPONSE_HEADERS_TOO_LARGE",
                "acquire",
                "response contains too many headers",
            )
        normalized: dict[str, str] = {}
        for raw_name, raw_value in result.headers.items():
            name = raw_name.lower().strip()
            value = raw_value.strip()
            if not name or "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise IntakeFailure(
                    "INVALID_RESPONSE_HEADER",
                    "acquire",
                    "response header contains forbidden control characters",
                )
            limit = MAX_LOCATION_BYTES if name == "location" else MAX_HEADER_VALUE_BYTES
            if name in {"etag", "last-modified"}:
                limit = MAX_VERSION_HEADER_BYTES
            if len(value.encode("utf-8")) > limit:
                raise IntakeFailure(
                    "RESPONSE_HEADER_TOO_LARGE",
                    "acquire",
                    "response header exceeds maximum bytes",
                    safe_context={"header": name[:64], "max_bytes": limit},
                )
            normalized[name] = value
        return replace(result, headers=normalized)

    return guarded


def intake_web_url(
    *,
    store: ObjectStore,
    request: WebURLRequest,
    output_dir: Path | None = None,
    resolver: Resolver = _default_resolver,
    exchange: HTTPExchange = _default_exchange,
    sleeper: Sleeper = time.sleep,
) -> IntakeResult:
    """Run the supported bounded HTTPS intake path."""

    return _intake_web_url(
        store=store,
        request=request,
        output_dir=output_dir,
        resolver=resolver,
        exchange=_guarded_exchange(exchange),
        sleeper=sleeper,
    )


__all__ = [
    "HTTPExchangeResult",
    "WebURLRequest",
    "canonicalize_https_url",
    "intake_web_url",
    "validate_public_ips",
]
