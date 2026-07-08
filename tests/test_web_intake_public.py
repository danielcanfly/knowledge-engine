from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from knowledge_engine.intake_v1 import AccessPolicy, EvidenceValue
from knowledge_engine.storage import FileObjectStore
from knowledge_engine.web_intake import HTTPExchangeResult, WebURLRequest, intake_web_url

PUBLIC_IP = "93.184.216.34"


def _resolved(value: str) -> EvidenceValue:
    return EvidenceValue(
        status="resolved",
        value=value,
        observation_source="operator_asserted",
    )


def _request(*, retrieved_at: str = "2026-07-08T09:00:00Z") -> WebURLRequest:
    return WebURLRequest(
        url="https://example.com/document.md",
        retrieved_at=retrieved_at,
        owner=_resolved("Daniel"),
        license=_resolved("owner-provided"),
        audience="public",
        access_policy=AccessPolicy(
            policy_type="public",
            principals=(),
            observation_source="observed",
        ),
        max_retries=0,
        backoff_base_seconds=0,
    )


def _resolver(host: str, port: int) -> Sequence[str]:
    assert host == "example.com"
    assert port == 443
    return (PUBLIC_IP,)


def test_public_request_rejects_non_utc_timestamp_before_exchange(tmp_path: Path) -> None:
    calls = 0

    def exchange(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        del url, connected_ip, timeout_seconds, max_compressed_bytes, headers
        nonlocal calls
        calls += 1
        raise AssertionError("exchange must not run")

    store = FileObjectStore(tmp_path / "store")
    result = intake_web_url(
        store=store,
        request=_request(retrieved_at="2026-07-08T09:00:00+09:00"),
        resolver=_resolver,
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "rejected"
    assert result.failure_code == "INVALID_TIMESTAMP"
    assert calls == 0
    rejection = json.loads(store.get(result.rejection_key or ""))
    assert rejection["raw_persisted"] is False


def test_public_boundary_rejects_oversized_or_control_character_headers(
    tmp_path: Path,
) -> None:
    responses = [
        HTTPExchangeResult(
            status=200,
            reason="OK",
            headers={
                "content-type": "text/markdown; charset=utf-8",
                "content-length": "5",
                "etag": "x" * 513,
            },
            body=b"# Hi\n",
            connected_ip=PUBLIC_IP,
        ),
        HTTPExchangeResult(
            status=200,
            reason="OK",
            headers={
                "content-type": "text/markdown; charset=utf-8\r\nset-cookie: secret",
                "content-length": "5",
            },
            body=b"# Hi\n",
            connected_ip=PUBLIC_IP,
        ),
    ]

    def exchange(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        del url, connected_ip, timeout_seconds, max_compressed_bytes, headers
        return responses.pop(0)

    store = FileObjectStore(tmp_path / "store")
    too_large = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver,
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )
    assert too_large.failure_code == "RESPONSE_HEADER_TOO_LARGE"

    invalid = intake_web_url(
        store=store,
        request=_request(retrieved_at="2026-07-08T09:01:00Z"),
        resolver=_resolver,
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )
    assert invalid.failure_code == "INVALID_RESPONSE_HEADER"


def test_public_api_accepts_bounded_markdown_response(tmp_path: Path) -> None:
    def exchange(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        del url, timeout_seconds, max_compressed_bytes, headers
        return HTTPExchangeResult(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/markdown; charset=utf-8",
                "Content-Length": "16",
                "ETag": '"safe-v1"',
            },
            body=b"# Public API\n\n",
            connected_ip=connected_ip,
        )

    store = FileObjectStore(tmp_path / "store")
    result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver,
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "accepted_for_compilation"
    snapshot = json.loads(store.get(result.snapshot_key or ""))
    assert snapshot["source_version"] == '"safe-v1"'
