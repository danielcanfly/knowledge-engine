from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from knowledge_engine.intake_v1 import AccessPolicy, EvidenceValue, IntakeFailure, verify_event
from knowledge_engine.storage import FileObjectStore
from knowledge_engine.web_intake import (
    HTTPExchangeResult,
    WebURLRequest,
    canonicalize_https_url,
    intake_web_url,
    validate_public_ips,
)

PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "151.101.1.69"


def _resolved(value: str) -> EvidenceValue:
    return EvidenceValue("resolved", value, "operator_asserted")


def _request(
    *,
    url: str = "https://example.com/article",
    retrieved_at: str = "2026-07-08T08:30:00Z",
    source_id: str | None = None,
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
        audience="public",
        access_policy=AccessPolicy("public", (), "observed"),
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
    body: bytes,
    *,
    status: int = 200,
    connected_ip: str = PUBLIC_IP,
    headers: Mapping[str, str] | None = None,
) -> HTTPExchangeResult:
    values = {
        "content-type": "text/markdown; charset=utf-8",
        "content-length": str(len(body)),
        "content-encoding": "identity",
        "etag": '"v1"',
    }
    values.update(headers or {})
    return HTTPExchangeResult(status, "OK", values, body, connected_ip)


def _sequence_exchange(responses: Sequence[HTTPExchangeResult]):
    queue = list(responses)
    calls: list[tuple[str, str]] = []

    def exchange(
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult:
        del timeout_seconds, max_compressed_bytes, headers
        calls.append((url, connected_ip))
        if not queue:
            raise AssertionError("unexpected exchange call")
        return queue.pop(0)

    return exchange, calls


def _json(store: FileObjectStore, key: str) -> dict:
    return json.loads(store.get(key))


def _run(
    tmp_path: Path,
    responses: Sequence[HTTPExchangeResult],
    *,
    request: WebURLRequest | None = None,
    dns: Mapping[str, Sequence[str]] | None = None,
):
    store = FileObjectStore(tmp_path / "store")
    exchange, calls = _sequence_exchange(responses)
    result = intake_web_url(
        store=store,
        request=request or _request(),
        resolver=_resolver(dns or {"example.com": [PUBLIC_IP]}),
        exchange=exchange,
        sleeper=lambda _seconds: None,
    )
    return store, result, calls


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://example.com/", "UNSUPPORTED_SCHEME"),
        ("https://user:pass@example.com/", "CREDENTIAL_IN_URL"),
        ("https://example.com/?access_token=secret", "CREDENTIAL_IN_URL"),
        ("https://localhost/", "FORBIDDEN_DESTINATION"),
    ],
)
def test_url_policy_rejects_unsafe_inputs(url: str, code: str) -> None:
    with pytest.raises(IntakeFailure) as caught:
        canonicalize_https_url(url)
    assert caught.value.code == code


def test_url_canonicalization_removes_default_port_and_fragment() -> None:
    assert canonicalize_https_url("HTTPS://Example.COM:443/a?q=1#x") == (
        "https://example.com/a?q=1"
    )


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0"],
)
def test_non_public_addresses_are_rejected(address: str) -> None:
    with pytest.raises(IntakeFailure) as caught:
        validate_public_ips([address])
    assert caught.value.code == "FORBIDDEN_DESTINATION"


def test_mixed_dns_answer_fails_closed() -> None:
    with pytest.raises(IntakeFailure):
        validate_public_ips([PUBLIC_IP, "10.0.0.1"])


def test_html_success_preserves_raw_and_writes_evidence(tmp_path: Path) -> None:
    html = (
        b"<!doctype html><html><head><script>bad()</script></head>"
        b"<body><h1>Bounded Web</h1><p>Evidence first.</p>"
        b"<ul><li>Public IP only</li></ul></body></html>"
    )
    store, result, calls = _run(
        tmp_path,
        [
            _response(
                html,
                headers={
                    "content-type": "text/html; charset=utf-8",
                    "x-robots-tag": "index, follow",
                },
            )
        ],
    )

    assert result.status == "accepted_for_compilation"
    assert calls == [("https://example.com/article", PUBLIC_IP)]
    assert store.get(result.raw_blob_key or "") == html
    normalized = store.get(result.normalized_key or "").decode()
    assert "# Bounded Web" in normalized
    assert "- Public IP only" in normalized
    assert "bad()" not in normalized

    acquisition_key = f"intake/v1/attempts/{result.attempt_id}/acquisition.json"
    acquisition = _json(store, acquisition_key)
    assert acquisition["final_resolution"]["connected_ip"] == PUBLIC_IP
    assert acquisition["observed_mime_type"] == "text/html"
    assert acquisition["robots_header_observation"] == "index, follow"

    snapshot = _json(store, result.snapshot_key or "")
    assert snapshot["connector_type"] == "web_url"
    assert snapshot["connector_version"] == "bounded-https/1.0.0"
    derivative = _json(store, result.derivative_key or "")
    assert derivative["normalizer_id"] == "html_to_markdown"
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


def test_redirect_revalidates_target_and_records_chain(tmp_path: Path) -> None:
    redirect = _response(
        b"",
        status=302,
        headers={"location": "https://cdn.example.net/final.md", "content-length": "0"},
    )
    final = _response(b"# Redirected\n", connected_ip=SECOND_PUBLIC_IP)
    store, result, calls = _run(
        tmp_path,
        [redirect, final],
        request=_request(url="https://example.com/start"),
        dns={"example.com": [PUBLIC_IP], "cdn.example.net": [SECOND_PUBLIC_IP]},
    )

    assert result.status == "accepted_for_compilation"
    assert calls == [
        ("https://example.com/start", PUBLIC_IP),
        ("https://cdn.example.net/final.md", SECOND_PUBLIC_IP),
    ]
    evidence = _json(store, f"intake/v1/attempts/{result.attempt_id}/acquisition.json")
    assert evidence["redirect_chain"][0]["connected_ip"] == PUBLIC_IP
    assert evidence["final_resolution"]["connected_ip"] == SECOND_PUBLIC_IP


def test_redirect_to_private_and_connected_ip_substitution_fail_closed(tmp_path: Path) -> None:
    redirect = _response(
        b"",
        status=302,
        headers={"location": "https://internal.example/a", "content-length": "0"},
    )
    _store, private_result, calls = _run(
        tmp_path / "private",
        [redirect],
        dns={"example.com": [PUBLIC_IP], "internal.example": ["10.0.0.8"]},
    )
    assert private_result.failure_code == "FORBIDDEN_DESTINATION"
    assert len(calls) == 1

    _store, rebound, _calls = _run(
        tmp_path / "rebound",
        [_response(b"# Wrong IP\n", connected_ip=SECOND_PUBLIC_IP)],
        request=_request(max_retries=0),
    )
    assert rebound.failure_code == "DNS_REBINDING_DETECTED"
    assert rebound.raw_blob_key is None


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_supported_compression_decodes_to_raw_representation(
    tmp_path: Path,
    encoding: str,
) -> None:
    source = b"# Compressed\n\nBounded transport.\n"
    compressed = gzip.compress(source) if encoding == "gzip" else zlib.compress(source)
    store, result, _calls = _run(
        tmp_path,
        [
            _response(
                compressed,
                headers={
                    "content-encoding": encoding,
                    "content-length": str(len(compressed)),
                },
            )
        ],
        request=_request(url=f"https://example.com/{encoding}.md"),
    )
    assert result.status == "accepted_for_compilation"
    assert store.get(result.raw_blob_key or "") == source


def test_size_ratio_and_content_length_limits(tmp_path: Path) -> None:
    _store, compressed, _calls = _run(
        tmp_path / "compressed",
        [_response(b"x" * 64)],
        request=_request(max_compressed_bytes=16),
    )
    assert compressed.failure_code == "SOURCE_TOO_LARGE"

    bomb = gzip.compress(b"A" * 4096)
    _store, decoded, _calls = _run(
        tmp_path / "decoded",
        [_response(bomb, headers={"content-encoding": "gzip"})],
        request=_request(max_bytes=1024),
    )
    assert decoded.failure_code == "SOURCE_TOO_LARGE"

    _store, ratio, _calls = _run(
        tmp_path / "ratio",
        [_response(bomb, headers={"content-encoding": "gzip"})],
        request=_request(max_bytes=8192, max_compression_ratio=2),
    )
    assert ratio.failure_code == "COMPRESSION_RATIO_EXCEEDED"

    _store, mismatch, _calls = _run(
        tmp_path / "length",
        [_response(b"short", headers={"content-length": "50"})],
    )
    assert mismatch.failure_code == "CONTENT_LENGTH_MISMATCH"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_response(b"partial", status=206), "TRUNCATED_RESPONSE"),
        (_response(b"encoded", headers={"content-encoding": "br"}), "UNSUPPORTED_CONTENT_ENCODING"),
        (
            _response(b"plain", headers={"content-type": "text/plain; charset=latin-1"}),
            "UNSUPPORTED_ENCODING",
        ),
        (_response(b"%PDF", headers={"content-type": "application/pdf"}), "UNSUPPORTED_MIME_TYPE"),
        (_response(b"", status=401), "AUTH_REQUIRED"),
        (_response(b"", status=403), "ACCESS_DENIED"),
        (_response(b"", status=404), "SOURCE_NOT_FOUND"),
    ],
)
def test_response_taxonomy(tmp_path: Path, response: HTTPExchangeResult, code: str) -> None:
    _store, result, _calls = _run(tmp_path, [response], request=_request(max_retries=0))
    assert result.failure_code == code


def test_transient_retries_are_bounded_and_evidenced(tmp_path: Path) -> None:
    store, result, calls = _run(
        tmp_path,
        [
            _response(b"", status=503),
            _response(b"", status=429),
            _response(b"# Recovered\n"),
        ],
        request=_request(max_retries=2),
    )
    assert result.status == "accepted_for_compilation"
    assert len(calls) == 3
    evidence = _json(store, f"intake/v1/attempts/{result.attempt_id}/acquisition.json")
    assert [item["reason_code"] for item in evidence["retry_events"]] == [
        "UPSTREAM_UNAVAILABLE",
        "RATE_LIMITED",
    ]

    _store, exhausted, calls = _run(
        tmp_path / "exhausted",
        [_response(b"", status=503), _response(b"", status=503)],
        request=_request(max_retries=1),
    )
    assert exhausted.failure_code == "UPSTREAM_UNAVAILABLE"
    assert len(calls) == 2


def test_secret_rejection_and_license_quarantine(tmp_path: Path) -> None:
    store, secret, _calls = _run(
        tmp_path / "secret",
        [_response(b"api_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890\n")],
    )
    assert secret.failure_code == "SECRET_LIKE_CONTENT"
    assert secret.raw_blob_key is None
    acquisition_key = f"intake/v1/attempts/{secret.attempt_id}/acquisition.json"
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in json.dumps(_json(store, acquisition_key))

    unresolved = EvidenceValue("unresolved", None, "unresolved")
    store, quarantined, _calls = _run(
        tmp_path / "license",
        [_response(b"# Pending license\n")],
        request=_request(license_value=unresolved),
    )
    assert quarantined.failure_code == "LICENSE_UNRESOLVED"
    assert quarantined.raw_blob_key is not None
    assert quarantined.snapshot_key is not None
    assert _json(store, quarantined.rejection_key or "")["raw_persisted"] is True


def test_exact_replay_and_cross_url_raw_dedupe(tmp_path: Path) -> None:
    body = b"# Shared remote content\n"
    store = FileObjectStore(tmp_path / "store")
    request = _request()

    first_exchange, _ = _sequence_exchange([_response(body)])
    first = intake_web_url(
        store=store,
        request=request,
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=first_exchange,
        sleeper=lambda _seconds: None,
    )
    replay_exchange, _ = _sequence_exchange([_response(body)])
    replay = intake_web_url(
        store=store,
        request=request,
        resolver=_resolver({"example.com": [PUBLIC_IP]}),
        exchange=replay_exchange,
        sleeper=lambda _seconds: None,
    )
    assert replay.snapshot_id == first.snapshot_id
    assert replay.idempotent is True

    second_exchange, _ = _sequence_exchange(
        [_response(body, connected_ip=SECOND_PUBLIC_IP)]
    )
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
    assert second.status == "accepted_for_compilation"
    assert second.raw_blob_key == first.raw_blob_key
    assert second.raw_blob_reused is True
    assert second.source_id != first.source_id
    assert second.snapshot_id != first.snapshot_id


def test_redirect_loop_limit_and_namespace_boundary(tmp_path: Path) -> None:
    loop = _response(
        b"",
        status=302,
        headers={"location": "https://example.com/article", "content-length": "0"},
    )
    _store, loop_result, _calls = _run(tmp_path / "loop", [loop])
    assert loop_result.failure_code == "REDIRECT_LOOP"

    redirect = _response(
        b"",
        status=302,
        headers={"location": "https://other.example/final", "content-length": "0"},
    )
    _store, limited, _calls = _run(
        tmp_path / "limit",
        [redirect],
        request=_request(max_redirects=0),
    )
    assert limited.failure_code == "TOO_MANY_REDIRECTS"

    store_root = tmp_path / "boundary"
    store = FileObjectStore(store_root)
    exchange, _ = _sequence_exchange([_response(b"# Boundary\n")])
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
