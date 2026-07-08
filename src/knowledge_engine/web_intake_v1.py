from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from .intake_v1 import (
    AUDIENCES,
    SNAPSHOT_ID_RE,
    SOURCE_ID_RE,
    AccessPolicy,
    EvidenceValue,
    IntakeFailure,
    IntakeResult,
    _event,
    _event_keys,
    _normalize_markdown,
    _pretty_json_bytes,
    _prompt_findings,
    _put_immutable,
    _reject,
    _secret_matches,
    _storage_location,
    _write_event,
    _write_output,
    canonical_json_bytes,
    derivative_id_for,
    snapshot_id_for,
    stable_source_id,
)
from .storage import ObjectStore, sha256_bytes

CONNECTOR_TYPE = "web_url"
CONNECTOR_VERSION = "bounded-https/1.0.0"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_COMPRESSED_BYTES = 5 * 1024 * 1024
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
SAFE_RESPONSE_HEADERS = {
    "accept-ranges",
    "cache-control",
    "content-encoding",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "x-content-type-options",
    "x-robots-tag",
}
SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}
HTML_MIME_TYPES = {"text/html", "application/xhtml+xml"}
MARKDOWN_MIME_TYPES = {"text/markdown", "text/x-markdown"}

Resolver = Callable[[str, int], Sequence[str]]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class HTTPExchangeResult:
    status: int
    reason: str
    headers: dict[str, str]
    body: bytes
    connected_ip: str


class HTTPExchange(Protocol):
    def __call__(
        self,
        url: str,
        connected_ip: str,
        timeout_seconds: float,
        max_compressed_bytes: int,
        headers: Mapping[str, str],
    ) -> HTTPExchangeResult: ...


@dataclass(frozen=True)
class WebURLRequest:
    url: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES
    max_redirects: int = 5
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.25
    max_compression_ratio: float = 100.0

    def validate(self) -> None:
        canonicalize_https_url(self.url)
        self.owner.validate("owner")
        self.license.validate("license")
        if self.audience not in AUDIENCES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid audience")
        self.access_policy.validate(audience=self.audience)
        if self.source_id is not None and not SOURCE_ID_RE.fullmatch(self.source_id):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid source_id")
        if self.parent_snapshot is not None and not SNAPSHOT_ID_RE.fullmatch(
            self.parent_snapshot
        ):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid parent_snapshot")
        if self.max_bytes < 1 or self.max_compressed_bytes < 1:
            raise IntakeFailure("INVALID_METADATA", "request", "byte limits must be positive")
        if not 0 <= self.max_redirects <= 10:
            raise IntakeFailure(
                "INVALID_METADATA", "request", "max_redirects must be between 0 and 10"
            )
        if not 0 < self.timeout_seconds <= 60:
            raise IntakeFailure(
                "INVALID_METADATA", "request", "timeout_seconds must be between 0 and 60"
            )
        if not 0 <= self.max_retries <= 5:
            raise IntakeFailure(
                "INVALID_METADATA", "request", "max_retries must be between 0 and 5"
            )
        if not 0 <= self.backoff_base_seconds <= 5:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "backoff_base_seconds must be between 0 and 5",
            )
        if not 1 <= self.max_compression_ratio <= 1000:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_compression_ratio must be between 1 and 1000",
            )

    def attempt_id(self) -> str:
        seed = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "url_hash": sha256_bytes(self.url.encode("utf-8")),
            "retrieved_at": self.retrieved_at,
            "source_id": self.source_id,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "parent_snapshot": self.parent_snapshot,
            "max_bytes": self.max_bytes,
            "max_compressed_bytes": self.max_compressed_bytes,
            "max_redirects": self.max_redirects,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_compression_ratio": self.max_compression_ratio,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(seed))[:32]


@dataclass(frozen=True)
class WebAcquisition:
    canonical_locator: str
    original_uri: str
    final_uri: str
    source_version: str
    retrieved_at: str
    reported_mime_type: str | None
    observed_mime_type: str
    encoding: str
    data: bytes
    acquisition_evidence: dict[str, Any]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        connected_ip: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host=host, port=port, timeout=timeout, context=context)
        self._connected_ip = connected_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connected_ip, self.port),
            timeout=self.timeout,
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _header_map(headers: Sequence[tuple[str, str]]) -> dict[str, str]:
    collected: dict[str, list[str]] = {}
    for name, value in headers:
        key = name.lower().strip()
        collected.setdefault(key, []).append(value.strip())
    return {key: ", ".join(values) for key, values in collected.items()}


def _default_exchange(
    url: str,
    connected_ip: str,
    timeout_seconds: float,
    max_compressed_bytes: int,
    headers: Mapping[str, str],
) -> HTTPExchangeResult:
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise IntakeFailure("INVALID_URL", "request", "URL hostname is required")
    port = parsed.port or 443
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"

    connection = _PinnedHTTPSConnection(
        host,
        port,
        connected_ip,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("GET", target, headers=dict(headers))
        response = connection.getresponse()
        response_headers = _header_map(response.getheaders())
        if response.status in REDIRECT_STATUSES or response.status != 200:
            return HTTPExchangeResult(
                status=response.status,
                reason=response.reason or "",
                headers=response_headers,
                body=b"",
                connected_ip=connected_ip,
            )

        declared_length = _content_length(response_headers)
        if declared_length is not None and declared_length > max_compressed_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "acquire",
                "compressed response exceeds maximum bytes",
                safe_context={
                    "declared_bytes": declared_length,
                    "max_compressed_bytes": max_compressed_bytes,
                },
            )

        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = response.read(min(64 * 1024, max_compressed_bytes + 1 - observed))
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > max_compressed_bytes:
                raise IntakeFailure(
                    "SOURCE_TOO_LARGE",
                    "acquire",
                    "compressed response exceeds maximum bytes",
                    safe_context={
                        "observed_bytes": observed,
                        "max_compressed_bytes": max_compressed_bytes,
                    },
                )
        body = b"".join(chunks)
        if declared_length is not None and len(body) != declared_length:
            raise IntakeFailure(
                "CONTENT_LENGTH_MISMATCH",
                "acquire",
                "response body does not match Content-Length",
                safe_context={
                    "declared_bytes": declared_length,
                    "observed_bytes": len(body),
                },
            )
        return HTTPExchangeResult(
            status=response.status,
            reason=response.reason or "",
            headers=response_headers,
            body=body,
            connected_ip=connected_ip,
        )
    except http.client.IncompleteRead as exc:
        raise IntakeFailure(
            "TRUNCATED_RESPONSE",
            "acquire",
            "response ended before the declared body completed",
            transient=True,
        ) from exc
    except TimeoutError as exc:
        raise IntakeFailure("TIMEOUT", "acquire", "HTTPS request timed out", transient=True) from exc
    except ssl.SSLError as exc:
        raise IntakeFailure("TLS_ERROR", "acquire", "TLS verification failed") from exc
    except OSError as exc:
        raise IntakeFailure(
            "NETWORK_ERROR", "acquire", "HTTPS request failed", transient=True
        ) from exc
    finally:
        connection.close()


def canonicalize_https_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise IntakeFailure("INVALID_URL", "request", "invalid URL") from exc
    if parsed.scheme.lower() != "https":
        raise IntakeFailure("UNSUPPORTED_SCHEME", "request", "only HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise IntakeFailure("CREDENTIAL_IN_URL", "request", "URL userinfo is forbidden")
    if parsed.hostname is None:
        raise IntakeFailure("INVALID_URL", "request", "URL hostname is required")

    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise IntakeFailure("INVALID_URL", "request", "invalid internationalized hostname") from exc
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise IntakeFailure("FORBIDDEN_DESTINATION", "request", "local hostnames are forbidden")

    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = key.strip().lower().replace("-", "_")
        if normalized_key in SENSITIVE_QUERY_NAMES or normalized_key.startswith("x_amz_"):
            raise IntakeFailure(
                "CREDENTIAL_IN_URL", "request", "sensitive query parameters are forbidden"
            )

    if port is not None and not 1 <= port <= 65535:
        raise IntakeFailure("INVALID_URL", "request", "invalid URL port")
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host if port in {None, 443} else f"{display_host}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def _default_resolver(host: str, port: int) -> Sequence[str]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return (str(literal),)
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise IntakeFailure("DNS_FAILED", "discover", "DNS resolution failed", transient=True) from exc
    return tuple(sorted({answer[4][0] for answer in answers}))


def validate_public_ips(addresses: Sequence[str]) -> tuple[str, ...]:
    if not addresses:
        raise IntakeFailure("DNS_FAILED", "discover", "DNS returned no addresses", transient=True)
    validated = []
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        except ValueError as exc:
            raise IntakeFailure("DNS_FAILED", "discover", "DNS returned an invalid address") from exc
        if not address.is_global:
            raise IntakeFailure(
                "FORBIDDEN_DESTINATION",
                "discover",
                "destination resolved to a non-public address",
                safe_context={"address_class": _address_class(address)},
            )
        validated.append(str(address))
    return tuple(sorted(set(validated)))


def _address_class(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if address.is_loopback:
        return "loopback"
    if address.is_link_local:
        return "link_local"
    if address.is_private:
        return "private"
    if address.is_multicast:
        return "multicast"
    if address.is_reserved:
        return "reserved"
    if address.is_unspecified:
        return "unspecified"
    return "non_global"


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("content-length")
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+", value.strip()):
        raise IntakeFailure(
            "INVALID_CONTENT_LENGTH", "acquire", "invalid Content-Length header"
        )
    return int(value)


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key in SAFE_RESPONSE_HEADERS}


def _parse_content_type(headers: Mapping[str, str]) -> tuple[str | None, str | None]:
    value = headers.get("content-type")
    if not value:
        return None, None
    parts = [part.strip() for part in value.split(";")]
    mime_type = parts[0].lower() or None
    charset = None
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip('"').lower()
    return mime_type, charset


def _decompress_body(
    body: bytes,
    *,
    content_encoding: str,
    max_bytes: int,
    max_compression_ratio: float,
) -> bytes:
    encoding = content_encoding.strip().lower()
    if encoding in {"", "identity"}:
        if len(body) > max_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "acquire",
                "response exceeds maximum bytes",
                safe_context={"observed_bytes": len(body), "max_bytes": max_bytes},
            )
        return body
    if encoding not in {"gzip", "deflate"}:
        raise IntakeFailure(
            "UNSUPPORTED_CONTENT_ENCODING",
            "acquire",
            "unsupported Content-Encoding",
            safe_context={"content_encoding": encoding[:64]},
        )

    if encoding == "gzip":
        decoded = _bounded_zlib(body, 16 + zlib.MAX_WBITS, max_bytes)
    else:
        try:
            decoded = _bounded_zlib(body, zlib.MAX_WBITS, max_bytes)
        except IntakeFailure as first_error:
            if first_error.code != "DECOMPRESSION_ERROR":
                raise
            decoded = _bounded_zlib(body, -zlib.MAX_WBITS, max_bytes)

    ratio = len(decoded) / max(1, len(body))
    if len(decoded) > 1024 and ratio > max_compression_ratio:
        raise IntakeFailure(
            "COMPRESSION_RATIO_EXCEEDED",
            "acquire",
            "decompression ratio exceeds policy",
            safe_context={
                "compressed_bytes": len(body),
                "decompressed_bytes": len(decoded),
            },
        )
    return decoded


def _bounded_zlib(body: bytes, window_bits: int, max_bytes: int) -> bytes:
    decompressor = zlib.decompressobj(window_bits)
    output: list[bytes] = []
    observed = 0
    try:
        for offset in range(0, len(body), 64 * 1024):
            remaining = max_bytes + 1 - observed
            chunk = decompressor.decompress(body[offset : offset + 64 * 1024], remaining)
            output.append(chunk)
            observed += len(chunk)
            if observed > max_bytes:
                raise IntakeFailure(
                    "SOURCE_TOO_LARGE",
                    "acquire",
                    "decompressed response exceeds maximum bytes",
                    safe_context={"max_bytes": max_bytes},
                )
        tail = decompressor.flush(max_bytes + 1 - observed)
        output.append(tail)
        observed += len(tail)
    except zlib.error as exc:
        raise IntakeFailure(
            "DECOMPRESSION_ERROR", "acquire", "compressed response is malformed"
        ) from exc
    if observed > max_bytes:
        raise IntakeFailure(
            "SOURCE_TOO_LARGE",
            "acquire",
            "decompressed response exceeds maximum bytes",
            safe_context={"max_bytes": max_bytes},
        )
    if not decompressor.eof or decompressor.unused_data:
        raise IntakeFailure(
            "DECOMPRESSION_ERROR",
            "acquire",
            "compressed response is truncated or contains trailing data",
        )
    return b"".join(output)


def _observe_mime(
    data: bytes,
    *,
    reported_mime_type: str | None,
    final_uri: str,
    charset: str | None,
) -> tuple[str, str]:
    if charset not in {None, "utf-8", "utf8"}:
        raise IntakeFailure(
            "UNSUPPORTED_ENCODING",
            "safety_gate",
            "only UTF-8 web content is supported",
            safe_context={"charset": charset[:64]},
        )
    if b"\x00" in data[:8192]:
        raise IntakeFailure("UNSUPPORTED_BINARY", "safety_gate", "binary web content is forbidden")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeFailure(
            "UNSUPPORTED_ENCODING", "safety_gate", "web content is not valid UTF-8"
        ) from exc

    prefix = text.lstrip()[:1024].lower()
    html_detected = (
        prefix.startswith("<!doctype html")
        or prefix.startswith("<html")
        or "<head" in prefix
        or "<body" in prefix
    )
    path = urlsplit(final_uri).path.lower()
    if reported_mime_type in HTML_MIME_TYPES or html_detected:
        return "text/html", text
    if reported_mime_type in MARKDOWN_MIME_TYPES or path.endswith((".md", ".markdown")):
        return "text/markdown", text
    if reported_mime_type is None or reported_mime_type == "text/plain":
        return "text/plain", text
    if reported_mime_type.startswith("text/"):
        return "text/plain", text
    raise IntakeFailure(
        "UNSUPPORTED_MIME_TYPE",
        "safety_gate",
        "web response MIME type is unsupported",
        safe_context={"reported_mime_type": reported_mime_type[:128]},
    )


class _HTMLToMarkdownParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    _BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "div",
        "footer",
        "header",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append(f"\n{'#' * int(tag[1])} ")
        elif tag == "pre":
            self.pre_depth += 1
            self.parts.append("\n```\n")
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in self._BLOCK_TAGS or tag in {"li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")
        elif tag == "pre":
            self.parts.append("\n```\n")
            self.pre_depth = max(0, self.pre_depth - 1)
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not data:
            return
        if self.pre_depth:
            self.parts.append(data)
            return
        collapsed = re.sub(r"\s+", " ", data)
        if collapsed.strip():
            self.parts.append(collapsed)

    def markdown(self) -> bytes:
        text = "".join(self.parts)
        lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
        output: list[str] = []
        blank = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if output and not blank:
                    output.append("")
                blank = True
                continue
            output.append(stripped if not line.startswith("    ") else line)
            blank = False
        normalized = "\n".join(output).strip()
        if not normalized:
            raise IntakeFailure("EMPTY_SOURCE", "normalize", "HTML contains no readable text")
        return (normalized + "\n").encode("utf-8")


def _normalize_web_content(data: bytes, observed_mime_type: str) -> tuple[bytes, str, str]:
    if observed_mime_type == "text/html":
        parser = _HTMLToMarkdownParser()
        try:
            parser.feed(data.decode("utf-8-sig"))
            parser.close()
        except Exception as exc:
            raise IntakeFailure("NORMALIZATION_FAILED", "normalize", "HTML parsing failed") from exc
        return parser.markdown(), "html_to_markdown", "1.0.0"
    normalizer_id = "markdown" if observed_mime_type == "text/markdown" else "plain_text_to_markdown"
    return _normalize_markdown(data), normalizer_id, "1.0.0"


class BoundedHTTPSConnector:
    def __init__(
        self,
        *,
        resolver: Resolver = _default_resolver,
        exchange: HTTPExchange = _default_exchange,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._exchange = exchange
        self._sleeper = sleeper

    def acquire(self, request: WebURLRequest) -> WebAcquisition:
        initial_uri = canonicalize_https_url(request.url)
        current_uri = initial_uri
        visited = {current_uri}
        redirect_chain: list[dict[str, Any]] = []
        retry_events: list[dict[str, Any]] = []

        for redirect_index in range(request.max_redirects + 1):
            parsed = urlsplit(current_uri)
            host = parsed.hostname
            if host is None:
                raise IntakeFailure("INVALID_URL", "discover", "URL hostname is required")
            port = parsed.port or 443
            resolved_ips = validate_public_ips(self._resolver(host, port))
            response = self._request_with_retries(
                current_uri,
                resolved_ips,
                request=request,
                retry_events=retry_events,
            )

            if response.status in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise IntakeFailure(
                        "INVALID_REDIRECT", "acquire", "redirect response is missing Location"
                    )
                if redirect_index >= request.max_redirects:
                    raise IntakeFailure(
                        "TOO_MANY_REDIRECTS", "acquire", "redirect limit exceeded"
                    )
                next_uri = canonicalize_https_url(urljoin(current_uri, location))
                if next_uri in visited:
                    raise IntakeFailure("REDIRECT_LOOP", "acquire", "redirect loop detected")
                redirect_chain.append(
                    {
                        "from": current_uri,
                        "status": response.status,
                        "to": next_uri,
                        "resolved_ips": list(resolved_ips),
                        "connected_ip": response.connected_ip,
                    }
                )
                visited.add(next_uri)
                current_uri = next_uri
                continue

            _raise_for_status(response.status)
            declared_length = _content_length(response.headers)
            if declared_length is not None and declared_length != len(response.body):
                raise IntakeFailure(
                    "CONTENT_LENGTH_MISMATCH",
                    "acquire",
                    "response body does not match Content-Length",
                    safe_context={
                        "declared_bytes": declared_length,
                        "observed_bytes": len(response.body),
                    },
                )
            if len(response.body) > request.max_compressed_bytes:
                raise IntakeFailure(
                    "SOURCE_TOO_LARGE",
                    "acquire",
                    "compressed response exceeds maximum bytes",
                    safe_context={
                        "observed_bytes": len(response.body),
                        "max_compressed_bytes": request.max_compressed_bytes,
                    },
                )

            content_encoding = response.headers.get("content-encoding", "identity")
            decoded = _decompress_body(
                response.body,
                content_encoding=content_encoding,
                max_bytes=request.max_bytes,
                max_compression_ratio=request.max_compression_ratio,
            )
            reported_mime_type, charset = _parse_content_type(response.headers)
            observed_mime_type, _text = _observe_mime(
                decoded,
                reported_mime_type=reported_mime_type,
                final_uri=current_uri,
                charset=charset,
            )
            decoded_hash = sha256_bytes(decoded)
            compressed_hash = sha256_bytes(response.body)
            source_version = (
                response.headers.get("etag")
                or response.headers.get("last-modified")
                or f"sha256:{decoded_hash}"
            )
            evidence = {
                "schema_version": "web-acquisition/v1",
                "connector_type": CONNECTOR_TYPE,
                "connector_version": CONNECTOR_VERSION,
                "original_uri": initial_uri,
                "final_uri": current_uri,
                "redirect_chain": redirect_chain,
                "retry_events": retry_events,
                "final_resolution": {
                    "resolved_ips": list(resolved_ips),
                    "connected_ip": response.connected_ip,
                },
                "response_status": response.status,
                "safe_response_headers": _safe_headers(response.headers),
                "reported_mime_type": reported_mime_type,
                "observed_mime_type": observed_mime_type,
                "mime_mismatch": reported_mime_type not in {None, observed_mime_type},
                "charset": charset,
                "content_encoding": content_encoding.lower(),
                "transport_body": {
                    "sha256": compressed_hash,
                    "byte_size": len(response.body),
                },
                "content_decoded_body": {
                    "sha256": decoded_hash,
                    "byte_size": len(decoded),
                },
                "source_version": source_version,
                "robots_header_observation": response.headers.get("x-robots-tag"),
                "transport_content_decoding": "connector",
            }
            return WebAcquisition(
                canonical_locator=initial_uri,
                original_uri=initial_uri,
                final_uri=current_uri,
                source_version=source_version,
                retrieved_at=request.retrieved_at,
                reported_mime_type=reported_mime_type,
                observed_mime_type=observed_mime_type,
                encoding="utf-8",
                data=decoded,
                acquisition_evidence=evidence,
            )

        raise IntakeFailure("TOO_MANY_REDIRECTS", "acquire", "redirect limit exceeded")

    def _request_with_retries(
        self,
        url: str,
        resolved_ips: Sequence[str],
        *,
        request: WebURLRequest,
        retry_events: list[dict[str, Any]],
    ) -> HTTPExchangeResult:
        headers = {
            "Accept": "text/html, text/markdown, text/plain;q=0.9",
            "Accept-Encoding": "gzip, deflate, identity",
            "Connection": "close",
            "User-Agent": "KnowledgeOS-Intake/1.0",
        }
        last_failure: IntakeFailure | None = None
        for attempt in range(request.max_retries + 1):
            connected_ip = resolved_ips[attempt % len(resolved_ips)]
            try:
                response = self._exchange(
                    url,
                    connected_ip,
                    request.timeout_seconds,
                    request.max_compressed_bytes,
                    headers,
                )
                if response.connected_ip != connected_ip:
                    raise IntakeFailure(
                        "DNS_REBINDING_DETECTED",
                        "acquire",
                        "exchange connected to an unvalidated address",
                    )
                if response.status not in TRANSIENT_STATUSES:
                    return response
                failure = IntakeFailure(
                    "RATE_LIMITED" if response.status == 429 else "UPSTREAM_UNAVAILABLE",
                    "acquire",
                    "upstream returned a transient status",
                    transient=True,
                    safe_context={"status": response.status},
                )
            except IntakeFailure as exc:
                failure = exc

            last_failure = failure
            if not failure.transient or attempt >= request.max_retries:
                raise failure
            delay = request.backoff_base_seconds * (2**attempt)
            retry_events.append(
                {
                    "url": url,
                    "attempt": attempt + 1,
                    "reason_code": failure.code,
                    "delay_seconds": delay,
                    "connected_ip": connected_ip,
                }
            )
            self._sleeper(delay)
        assert last_failure is not None
        raise last_failure


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 206:
        raise IntakeFailure("TRUNCATED_RESPONSE", "acquire", "partial responses are forbidden")
    if status == 401:
        raise IntakeFailure("AUTH_REQUIRED", "acquire", "source requires authentication")
    if status == 403:
        raise IntakeFailure("ACCESS_DENIED", "acquire", "source access was denied")
    if status == 404:
        raise IntakeFailure("SOURCE_NOT_FOUND", "acquire", "source was not found")
    raise IntakeFailure(
        "HTTP_STATUS_REJECTED",
        "acquire",
        "upstream returned an unsupported status",
        safe_context={"status": status},
    )


def intake_web_url(
    *,
    store: ObjectStore,
    request: WebURLRequest,
    output_dir: Path | None = None,
    resolver: Resolver = _default_resolver,
    exchange: HTTPExchange = _default_exchange,
    sleeper: Sleeper = time.sleep,
) -> IntakeResult:
    """Acquire one bounded HTTPS source into the immutable M10 intake namespace."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None

    try:
        request.validate()
        initial_uri = canonicalize_https_url(request.url)
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, initial_uri)
        artifacts["source_id"] = source_id

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[f"url_sha256:{sha256_bytes(initial_uri.encode('utf-8'))}"],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        acquisition = BoundedHTTPSConnector(
            resolver=resolver,
            exchange=exchange,
            sleeper=sleeper,
        ).acquire(request)
        raw_hash = sha256_bytes(acquisition.data)
        acquisition_key = f"intake/v1/attempts/{attempt_id}/acquisition.json"
        acquisition_evidence = {
            **acquisition.acquisition_evidence,
            "attempt_id": attempt_id,
            "source_id": source_id,
        }
        acquisition_bytes = _pretty_json_bytes(acquisition_evidence)
        object_states.append(
            _put_immutable(
                store,
                acquisition_key,
                acquisition_bytes,
                content_type="application/json",
            )
        )
        artifacts["acquisition_key"] = acquisition_key

        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[
                acquisition_key,
                f"sha256:{raw_hash}",
                f"bytes:{len(acquisition.data)}",
            ],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        matches = _secret_matches(acquisition.data.decode("utf-8-sig"))
        if matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "source contains secret-like content",
                safe_context={
                    "patterns": matches,
                    "observed_sha256": raw_hash,
                    "observed_bytes": len(acquisition.data),
                },
            )

        raw_blob_key = f"intake/v1/raw/sha256/{raw_hash[:2]}/{raw_hash}"
        raw_reused = _put_immutable(
            store,
            raw_blob_key,
            acquisition.data,
            content_type=acquisition.observed_mime_type,
        )
        object_states.append(raw_reused)
        artifacts.update(raw_blob_key=raw_blob_key, raw_blob_reused=raw_reused)

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            else "resolved"
        )
        identity = {
            "schema_version": "intake-snapshot/v1",
            "source_id": source_id,
            "original_uri": acquisition.original_uri,
            "connector_type": CONNECTOR_TYPE,
            "connector_version": CONNECTOR_VERSION,
            "retrieved_at": request.retrieved_at,
            "content_hash": raw_hash,
            "byte_size": len(acquisition.data),
            "mime_type": acquisition.observed_mime_type,
            "encoding": acquisition.encoding,
            "license": request.license.to_dict(),
            "owner": request.owner.to_dict(),
            "audience": request.audience,
            "access_policy": request.access_policy.to_dict(),
            "source_version": acquisition.source_version,
            "parent_snapshot": request.parent_snapshot,
        }
        snapshot_id = snapshot_id_for(identity)
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot = {
            **identity,
            "snapshot_id": snapshot_id,
            "acl_status": acl_status,
            "storage_location": _storage_location(store, raw_blob_key, raw_hash),
        }
        snapshot_bytes = _pretty_json_bytes(snapshot)
        object_states.append(
            _put_immutable(store, snapshot_key, snapshot_bytes, content_type="application/json")
        )
        artifacts.update(snapshot_id=snapshot_id, snapshot_key=snapshot_key)

        snapshotted = _event(
            attempt_id=attempt_id,
            sequence=3,
            occurred_at=request.retrieved_at,
            from_state="acquired",
            to_state="snapshotted",
            reason_code="SNAPSHOT_WRITTEN",
            evidence_refs=[raw_blob_key, snapshot_key, acquisition_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        normalized, normalizer_id, normalizer_version = _normalize_web_content(
            acquisition.data,
            acquisition.observed_mime_type,
        )
        if len(normalized) > request.max_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "normalize",
                "normalized derivative exceeds maximum bytes",
                safe_context={"max_bytes": request.max_bytes},
            )
        normalized_hash = sha256_bytes(normalized)
        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=normalizer_id,
            normalizer_version=normalizer_version,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{normalizer_id}/"
            f"{normalizer_version}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{normalizer_id}/"
            f"{normalizer_version}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = {
            "schema_version": "intake-derivative/v1",
            "derivative_id": derivative_id,
            "snapshot_id": snapshot_id,
            "normalizer_id": normalizer_id,
            "normalizer_version": normalizer_version,
            "normalized_content_hash": normalized_hash,
            "normalized_key": normalized_key,
            "byte_size": len(normalized),
            "mime_type": "text/markdown",
            "warnings": _prompt_findings(normalized.decode("utf-8")),
            "acquisition_evidence_key": acquisition_key,
        }
        derivative_bytes = _pretty_json_bytes(derivative)
        object_states.append(
            _put_immutable(
                store,
                derivative_key,
                derivative_bytes,
                content_type="application/json",
            )
        )
        artifacts.update(
            derivative_id=derivative_id,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
        )

        normalized_event = _event(
            attempt_id=attempt_id,
            sequence=4,
            occurred_at=request.retrieved_at,
            from_state="snapshotted",
            to_state="normalized",
            reason_code="DERIVATIVE_WRITTEN",
            evidence_refs=[normalized_key, derivative_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, normalized_event)
        events.append(normalized_event)
        object_states.append(reused)
        current_state = "normalized"

        if acl_status != "resolved" or request.owner.status != "resolved":
            raise IntakeFailure(
                "ACL_UNRESOLVED",
                "admission",
                "ACL or ownership is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )
        if request.license.status != "resolved":
            raise IntakeFailure(
                "LICENSE_UNRESOLVED",
                "admission",
                "license is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )

        accepted = _event(
            attempt_id=attempt_id,
            sequence=5,
            occurred_at=request.retrieved_at,
            from_state="normalized",
            to_state="accepted_for_compilation",
            reason_code="COMPILATION_ADMISSION_ACCEPTED",
            evidence_refs=[snapshot_key, derivative_key, acquisition_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, accepted)
        events.append(accepted)
        object_states.append(reused)

        result_key = f"intake/v1/attempts/{attempt_id}/result.json"
        result = IntakeResult(
            attempt_id=attempt_id,
            status="accepted_for_compilation",
            source_id=source_id,
            snapshot_id=snapshot_id,
            derivative_id=derivative_id,
            raw_blob_key=raw_blob_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=raw_reused,
            event_keys=_event_keys(attempt_id, events),
        )
        object_states.append(
            _put_immutable(
                store,
                result_key,
                _pretty_json_bytes(result.evidence_dict()),
                content_type="application/json",
            )
        )
        result = replace(result, idempotent=all(object_states))
        _write_output(output_dir, "acquisition.json", acquisition_bytes)
        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        return _reject(
            store=store,
            request=request,
            attempt_id=attempt_id,
            failure=failure,
            current_state=current_state,
            events=events,
            object_states=object_states,
            artifacts=artifacts,
            output_dir=output_dir,
        )
