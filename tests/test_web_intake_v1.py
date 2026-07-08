from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from knowledge_engine.intake_v1 import AccessPolicy, EvidenceValue, verify_event
from knowledge_engine.storage import FileObjectStore
from knowledge_engine.web_intake_v1 import (
    HTTPExchangeResult,
    WebURLRequest,
    canonicalize_https_url,
    intake_web_url,
    validate_public_ips,
)

PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "151.101.1.69"


def _resolved(value: str) -> EvidenceValue:
    return EvidenceValue(
        status="resolved",
        value=value,
        observation_source="operator_asserted",
    )


def _request(
    *,
    url: str = "https://example.com/article",
    retrieved_at: str = "2026-07-08T08:30:00Z",
    source_id: str | None = None,
    audience: str = "public",
    access_policy: AccessPolicy | None = None,
    license_value: EvidenceValue | None = None,
    max_bytes: int = 1024 * 1024,
    max_compressed_bytes: int = 1024 * 1024,
    max_redirects: int = 5,
    max_retries: int = 2,
    max_compression_ratio: float = 100.0,
) -> WebURLRequest:
    return WebURLRequest(
        url=url,
        retrieved_at=retrieved_at,
        source_id=source_id,
        owner=_resolved("Daniel"),
        license=license_value or _resolved("owner-provided"),
        audience=audience,
        access_policy=access_policy
        or AccessPolicy(
            policy_type="public",
            principals=(),
            observation_source="observed",
        ),
        max_bytes=max_bytes,
        max_compressed_bytes=max_compressed_bytes,
        max_redirects=max_redirects,
        max_retries=max_retries,
        backoff_base_seconds=0,
        max_compression_ratio=max_compression_ratio,
    )


def _resolver(mapping: Mapping[str, Sequence[str]]):
    def resolve(host: str, port: int) -> Sequence[str]:
        assert port == 443
        return mapping[host]

    return resolve


def _response(
    *,
    body: bytes,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    connected_ip: str = PUBLIC_IP,
) -> HTTPExchangeResult:
    base_headers = {
        "content-type": "text/markdown; charset=utf-8",
        "content-length": str(len(body)),
        "content-encoding": "identity",
        "etag": '"v1"',
    }
    base_headers.update(headers or {})
    return HTTPExchangeResult(
        status=status,
        reason="OK",
        headers=base_headers,
        body=body,
        connected_ip=connected_ip,
    )


def _exchange_from_sequence(responses: Sequence[HTTPExchangeResult]):
    calls: list[tuple[str, str, float, int, dict[str, str]]] = []
    queue = list(responses)

    def exchange(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        calls.append(
            (url, connected_ip, timeout_seconds, max_compressed_bytes, dict(headers))
        )
        if not queue:
            raise AssertionError("unexpected exchange call")
        return queue.pop(0)

    return exchange, calls


def _json(store: FileObjectStore, key: str) -> dict:
    return json.loads(store.get(key))


def test_https_url_canonicalization_rejects_credentials_and_unsafe_schemes() -> None:
    assert canonicalize_https_url("HTTPS://Example.COM:443/a?q=1#fragment") == (
        "https://example.com/a?q=1"
    )
    assert canonicalize_https_url("https://example.com") == "https://example.com/"

    with pytest.raises(Exception, match="only HTTPS"):
        canonicalize_https_url("http://example.com/")
    with pytest.raises(Exception, match="userinfo"):
        canonicalize_https_url("https://user:pass@example.com/")
    with pytest.raises(Exception, match="sensitive query"):
        canonicalize_https_url("https://example.com/?access_token=secret")
    with pytest.raises(Exception, match="local hostnames"):
        canonicalize_https_url("https://localhost/")


def test_public_ip_validation_rejects_private_metadata_and_mixed_answers() -> None:
    assert validate_public_ips([PUBLIC_IP, SECOND_PUBLIC_IP]) == (
        SECOND_PUBLIC_IP,
        PUBLIC_IP,
    )
    for forbidden in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "0.0.0.0",
    ):
        with pytest.raises(Exception, match="non-public"):
            validate_public_ips([forbidden])
    with pytest.raises(Exception, match="non-public"):
        validate_public_ips([PUBLIC_IP, "10.0.0.1"])


def test_html_success_writes_acquisition_snapshot_derivative_and_events(tmp_path: Path) -> None:
    html = b"""<!doctype html><html><head><title>Guide</title><script>steal()</script></head>
    <body><h1>Bounded Web</h1><p>Evidence <strong>first</strong>.</p>
    <ul><li>Public IP only</li><li>Immutable raw</li></ul></body></html>"""
    exchange, calls = _exchange_from_sequence(
        [
            _response(
                body=html,
                headers={
                    "content-type": "text/html; charset=utf-8",
                    "x-robots-tag": "index, follow",
                    "last-modified": "Wed, 08 Jul 2026 08:00:00 GMT",
                },
            )
        ]
    )
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
        output_dir=tmp_path / "output",
    )

    assert result.status == "accepted_for_compilation"
    assert result.idempotent is False
    assert result.raw_blob_reused is False
    assert len(calls) == 1
    assert calls[0][1] == PUBLIC_IP
    assert calls[0][4]["Accept-Encoding"] == "gzip, deflate, identity"

    raw = store.get(result.raw_blob_key or "")
    assert raw == html
    normalized = store.get(result.normalized_key or "").decode("utf-8")
    assert "# Bounded Web" in normalized
    assert "Evidence first." in normalized
    assert "- Public IP only" in normalized
    assert "steal()" not in normalized

    acquisition_key = f"intake/v1/attempts/{result.attempt_id}/acquisition.json"
    acquisition = _json(store, acquisition_key)
    assert acquisition["final_uri"] == "https://example.com/article"
    assert acquisition["final_resolution"]["connected_ip"] == PUBLIC_IP
    assert acquisition["observed_mime_type"] == "text/html"
    assert acquisition["transport_body"]["byte_size"] == len(html)
    assert acquisition["content_decoded_body"]["byte_size"] == len(html)
    assert acquisition["robots_header_observation"] == "index, follow"
    assert "set-cookie" not in acquisition["safe_response_headers"]

    snapshot = _json(store, result.snapshot_key or "")
    assert snapshot["connector_type"] == "web_url"
    assert snapshot["connector_version"] == "bounded-https/1.0.0"
    assert snapshot["mime_type"] == "text/html"
    assert snapshot["source_version"] == '"v1"'

    derivative = _json(store, result.derivative_key or "")
    assert derivative["normalizer_id"] == "html_to_markdown"
    assert derivative["normalizer_version"] == "1.0.0"
    assert derivative["acquisition_evidence_key"] == acquisition_key

    previous = None
    states = []
    for key in result.event_keys:
        event = _json(store, key)
        assert verify_event(event)
        assert event["previous_event_sha256"] == previous
        previous = event["event_sha256"]
        states.append(event["to_state"])
    assert states == [
        "discovered",
        "acquired",
        "snapshotted",
        "normalized",
        "accepted_for_compilation",
    ]
    assert (tmp_path / "output/acquisition.json").is_file()


def test_redirect_chain_revalidates_each_host_and_is_evidenced(tmp_path: Path) -> None:
    redirect = _response(
        body=b"",
        status=302,
        headers={
            "location": "https://cdn.example.net/final.md",
            "content-length": "0",
        },
    )
    final = _response(body=b"# Redirected\n", connected_ip=SECOND_PUBLIC_IP)
    exchange, calls = _exchange_from_sequence([redirect, final])
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(url="https://example.com/start"),
        resolver=_resolver(
            {
                "example.com": [PUBLIC_IP],
                "cdn.example.net": [SECOND_PUBLIC_IP],
            }
        ),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "accepted_for_compilation"
    assert [call[1] for call in calls] == [PUBLIC_IP, SECOND_PUBLIC_IP]
    acquisition = _json(
        store,
        f"intake/v1/attempts/{result.attempt_id}/acquisition.json",
    )
    assert acquisition["final_uri"] == "https://cdn.example.net/final.md"
    assert acquisition["redirect_chain"] == [
        {
            "connected_ip": PUBLIC_IP,
            "from": "https://example.com/start",
            "resolved_ips": [PUBLIC_IP],
            "status": 302,
            "to": "https://cdn.example.net/final.md",
        }
    ]


def test_redirect_to_private_destination_fails_before_second_exchange(tmp_path: Path) -> None:
    redirect = _response(
        body=b"",
        status=302,
        headers={"location": "https://internal.example/private", "content-length": "0"},
    )
    exchange, calls = _exchange_from_sequence([redirect])
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver(
            {
                "example.com": [PUBLIC_IP],
                "internal.example": ["10.0.0.8"],
            }
        ),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "rejected"
    assert result.failure_code == "FORBIDDEN_DESTINATION"
    assert len(calls) == 1
    assert result.raw_blob_key is None


def test_exchange_cannot_switch_to_unvalidated_ip(tmp_path: Path) -> None:
    exchange, _calls = _exchange_from_sequence(
        [_response(body=b"# Rebound\n", connected_ip=SECOND_PUBLIC_IP)]
    )
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(max_retries=0),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "rejected"
    assert result.failure_code == "DNS_REBINDING_DETECTED"
    assert result.raw_blob_key is None


def test_gzip_and_deflate_are_bounded_and_deterministic(tmp_path: Path) -> None:
    source = b"# Compressed\n\nBounded transport.\n"
    gzip_body = gzip.compress(source)
    deflate_body = zlib.compress(source)
    store = FileObjectStore(tmp_path / "store")

    gzip_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=gzip_body,
                headers={
                    "content-encoding": "gzip",
                    "content-length": str(len(gzip_body)),
                },
            )
        ]
    )
    gzip_result = intake_web_url(
        store=store,
        request=_request(url="https://example.com/gzip.md"),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=gzip_exchange,
        sleeper=lambda _seconds: None,
    )
    assert gzip_result.status == "accepted_for_compilation"
    assert store.get(gzip_result.raw_blob_key or "") == source

    deflate_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=deflate_body,
                headers={
                    "content-encoding": "deflate",
                    "content-length": str(len(deflate_body)),
                },
            )
        ]
    )
    deflate_result = intake_web_url(
        store=store,
        request=_request(
            url="https://example.com/deflate.md",
            retrieved_at="2026-07-08T08:31:00Z",
        ),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=deflate_exchange,
        sleeper=lambda _seconds: None,
    )
    assert deflate_result.status == "accepted_for_compilation"
    assert deflate_result.raw_blob_key == gzip_result.raw_blob_key
    assert deflate_result.raw_blob_reused is True
    assert deflate_result.snapshot_id != gzip_result.snapshot_id


def test_compressed_decompressed_and_ratio_limits_fail_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")

    large_body = b"x" * 64
    large_exchange, _ = _exchange_from_sequence([_response(body=large_body)])
    compressed_limit = intake_web_url(
        store=store,
        request=_request(max_compressed_bytes=16),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=large_exchange,
        sleeper=lambda _seconds: None,
    )
    assert compressed_limit.status == "rejected"
    assert compressed_limit.failure_code == "SOURCE_TOO_LARGE"

    decoded_source = b"A" * 4096
    bomb = gzip.compress(decoded_source)
    decoded_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=bomb,
                headers={
                    "content-encoding": "gzip",
                    "content-length": str(len(bomb)),
                },
            )
        ]
    )
    decoded_limit = intake_web_url(
        store=store,
        request=_request(
            url="https://example.com/decoded.md",
            retrieved_at="2026-07-08T08:32:00Z",
            max_bytes=1024,
        ),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=decoded_exchange,
        sleeper=lambda _seconds: None,
    )
    assert decoded_limit.status == "rejected"
    assert decoded_limit.failure_code == "SOURCE_TOO_LARGE"

    ratio_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=bomb,
                headers={
                    "content-encoding": "gzip",
                    "content-length": str(len(bomb)),
                },
            )
        ]
    )
    ratio_limit = intake_web_url(
        store=store,
        request=_request(
            url="https://example.com/ratio.md",
            retrieved_at="2026-07-08T08:33:00Z",
            max_bytes=8192,
            max_compression_ratio=2,
        ),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=ratio_exchange,
        sleeper=lambda _seconds: None,
    )
    assert ratio_limit.status == "rejected"
    assert ratio_limit.failure_code == "COMPRESSION_RATIO_EXCEEDED"


def test_content_length_mismatch_and_partial_status_are_rejected(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    mismatch_exchange, _ = _exchange_from_sequence(
        [_response(body=b"short", headers={"content-length": "50"})]
    )
    mismatch = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=mismatch_exchange,
        sleeper=lambda _seconds: None,
    )
    assert mismatch.status == "rejected"
    assert mismatch.failure_code == "CONTENT_LENGTH_MISMATCH"

    partial_exchange, _ = _exchange_from_sequence(
        [_response(body=b"partial", status=206)]
    )
    partial = intake_web_url(
        store=store,
        request=_request(retrieved_at="2026-07-08T08:34:00Z"),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=partial_exchange,
        sleeper=lambda _seconds: None,
    )
    assert partial.status == "rejected"
    assert partial.failure_code == "TRUNCATED_RESPONSE"


def test_unsupported_content_encoding_charset_and_mime_are_rejected(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")

    br_exchange, _ = _exchange_from_sequence(
        [_response(body=b"encoded", headers={"content-encoding": "br"})]
    )
    br_result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=br_exchange,
        sleeper=lambda _seconds: None,
    )
    assert br_result.failure_code == "UNSUPPORTED_CONTENT_ENCODING"

    charset_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=b"plain",
                headers={"content-type": "text/plain; charset=iso-8859-1"},
            )
        ]
    )
    charset_result = intake_web_url(
        store=store,
        request=_request(retrieved_at="2026-07-08T08:35:00Z"),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=charset_exchange,
        sleeper=lambda _seconds: None,
    )
    assert charset_result.failure_code == "UNSUPPORTED_ENCODING"

    binary_exchange, _ = _exchange_from_sequence(
        [
            _response(
                body=b"%PDF-1.7\n",
                headers={"content-type": "application/pdf"},
            )
        ]
    )
    binary_result = intake_web_url(
        store=store,
        request=_request(retrieved_at="2026-07-08T08:36:00Z"),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=binary_exchange,
        sleeper=lambda _seconds: None,
    )
    assert binary_result.failure_code == "UNSUPPORTED_MIME_TYPE"


def test_transient_retry_is_bounded_evidenced_and_can_recover(tmp_path: Path) -> None:
    responses = [
        _response(body=b"", status=503),
        _response(body=b"", status=429),
        _response(body=b"# Recovered\n"),
    ]
    exchange, calls = _exchange_from_sequence(responses)
    sleeps: list[float] = []
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(max_retries=2),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=sleeps.append,
    )

    assert result.status == "accepted_for_compilation"
    assert len(calls) == 3
    assert sleeps == [0, 0]
    acquisition = _json(
        store,
        f"intake/v1/attempts/{result.attempt_id}/acquisition.json",
    )
    assert [event["reason_code"] for event in acquisition["retry_events"]] == [
        "UPSTREAM_UNAVAILABLE",
        "RATE_LIMITED",
    ]


def test_retry_exhaustion_and_http_status_taxonomy(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    unavailable_exchange, calls = _exchange_from_sequence(
        [_response(body=b"", status=503), _response(body=b"", status=503)]
    )
    unavailable = intake_web_url(
        store=store,
        request=_request(max_retries=1),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=unavailable_exchange,
        sleeper=lambda _seconds: None,
    )
    assert unavailable.status == "rejected"
    assert unavailable.failure_code == "UPSTREAM_UNAVAILABLE"
    assert len(calls) == 2

    for index, (status, code) in enumerate(
        ((401, "AUTH_REQUIRED"), (403, "ACCESS_DENIED"), (404, "SOURCE_NOT_FOUND"))
    ):
        exchange, _ = _exchange_from_sequence([_response(body=b"", status=status)])
        result = intake_web_url(
            store=store,
            request=_request(retrieved_at=f"2026-07-08T08:{40 + index}:00Z"),
            resolver=_resolver({"example.com": [PUBLIC_IP]}),
            exchange=exchange,
            sleeper=lambda _seconds: None,
        )
        assert result.failure_code == code


def test_secret_is_rejected_before_raw_but_after_sanitized_acquisition_evidence(
    tmp_path: Path,
) -> None:
    body = b"# Unsafe\n\napi_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n"
    exchange, _ = _exchange_from_sequence([_response(body=body)])
    store_root = tmp_path / "store"
    store = FileObjectStore(store_root)

    result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "rejected"
    assert result.failure_code == "SECRET_LIKE_CONTENT"
    assert result.raw_blob_key is None
    acquisition_key = f"intake/v1/attempts/{result.attempt_id}/acquisition.json"
    acquisition = _json(store, acquisition_key)
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in json.dumps(acquisition)
    rejection = _json(store, result.rejection_key or "")
    assert rejection["raw_persisted"] is False
    assert acquisition_key in _json(store, result.event_keys[-1])["evidence_refs"]
    assert not (store_root / "intake/v1/raw").exists()


def test_unresolved_license_is_post_snapshot_quarantine(tmp_path: Path) -> None:
    exchange, _ = _exchange_from_sequence([_response(body=b"# Pending license\n")])
    store = FileObjectStore(tmp_path / "store")

    result = intake_web_url(
        store=store,
        request=_request(
            license_value=EvidenceValue(
                status="unresolved",
                value=None,
                observation_source="unresolved",
            )
        ),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "rejected"
    assert result.failure_code == "LICENSE_UNRESOLVED"
    assert result.raw_blob_key is not None
    assert result.snapshot_key is not None
    assert result.derivative_key is not None
    rejection = _json(store, result.rejection_key or "")
    assert rejection["raw_persisted"] is True


def test_exact_replay_and_cross_url_raw_dedupe(tmp_path: Path) -> None:
    body = b"# Shared remote content\n"
    store = FileObjectStore(tmp_path / "store")
    first_exchange, _ = _exchange_from_sequence([_response(body=body)])
    request = _request()

    first = intake_web_url(
        store=store,
        request=request,
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=first_exchange,
        sleeper=lambda _seconds: None,
    )
    replay_exchange, _ = _exchange_from_sequence([_response(body=body)])
    replay = intake_web_url(
        store=store,
        request=request,
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=replay_exchange,
        sleeper=lambda _seconds: None,
    )
    assert first.snapshot_id == replay.snapshot_id
    assert replay.idempotent is True
    assert replay.raw_blob_reused is True

    second_exchange, _ = _exchange_from_sequence([_response(body=body)])
    second = intake_web_url(
        store=store,
        request=_request(
            url="https://other.example/shared.md",
            retrieved_at="2026-07-08T08:50:00Z",
        ),
        resolver=_resolver({"other.example": [SECOND_PUBLIC_IP]}),
        exchange=second_exchange,
        sleeper=lambda _seconds: None,
    )
    assert second.raw_blob_key == first.raw_blob_key
    assert second.raw_blob_reused is True
    assert second.source_id != first.source_id
    assert second.snapshot_id != first.snapshot_id


def test_redirect_loop_and_limit_are_rejected(tmp_path: Path) -> None:
    loop_response = _response(
        body=b"",
        status=302,
        headers={"location": "https://example.com/article", "content-length": "0"},
    )
    loop_exchange, _ = _exchange_from_sequence([loop_response])
    store = FileObjectStore(tmp_path / "store")
    loop = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=loop_exchange,
        sleeper=lambda _seconds: None,
    )
    assert loop.failure_code == "REDIRECT_LOOP"

    redirect = _response(
        body=b"",
        status=302,
        headers={"location": "https://other.example/final", "content-length": "0"},
    )
    limit_exchange, _ = _exchange_from_sequence([redirect])
    limit = intake_web_url(
        store=store,
        request=_request(
            retrieved_at="2026-07-08T08:51:00Z",
            max_redirects=0,
        ),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=limit_exchange,
        sleeper=lambda _seconds: None,
    )
    assert limit.failure_code == "TOO_MANY_REDIRECTS"


def test_web_intake_writes_only_intake_v1_namespace(tmp_path: Path) -> None:
    exchange, _ = _exchange_from_sequence([_response(body=b"# Boundary\n")])
    store_root = tmp_path / "store"
    store = FileObjectStore(store_root)

    result = intake_web_url(
        store=store,
        request=_request(),
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "accepted_for_compilation"
    object_paths = [
        path.relative_to(store_root).as_posix()
        for path in store_root.rglob("*")
        if path.is_file() and ".metadata/" not in path.as_posix()
    ]
    assert object_paths
    assert all(path.startswith("intake/v1/") for path in object_paths)
    assert not (store_root / "channels/production.json").exists()
    assert not (store_root / "raw/captures").exists()
    assert not (store_root / "review/packets").exists()
