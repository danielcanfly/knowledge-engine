from __future__ import annotations

import hashlib
import ipaddress
import json
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .errors import IntegrityError

MAX_ITEMS = 500
MAX_REDIRECTS = 8
MAX_DECLARED_BYTES = 8_000_000
MAX_URL_LENGTH = 2_048
ALLOWED_MEDIA_TYPES = {
    "application/atom+xml",
    "application/feed+json",
    "application/json",
    "application/rss+xml",
    "text/html",
    "text/markdown",
}
ALLOWED_ACCESS = {"available", "blocked", "missing", "redirected"}
ALLOWED_INTAKE = {"discovered", "captured", "deferred", "rejected"}
ALLOWED_AUDIENCES = {"public", "internal"}
ALLOWED_SOURCE_KINDS = {"repository_markdown", "site_api", "site_feed", "https_url"}


@dataclass(frozen=True)
class ConnectorDescriptor:
    source_kind: str
    canonical_url: str
    host: str
    media_type: str
    max_bytes: int
    redirect_limit: int
    credentials_required: bool = False


@dataclass(frozen=True)
class InventoryIdentity:
    engine_sha: str
    source_sha: str
    foundation_sha: str
    captured_at: str


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise IntegrityError(f"M21-INV-101 invalid {label}")
    return value.lower()


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise IntegrityError(f"M21-INV-102 invalid {label}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise IntegrityError(f"M21-INV-102 invalid {label}") from exc
    return value.lower()


def _normalise_host(host: str) -> str:
    host = host.rstrip(".").lower()
    if not host:
        raise IntegrityError("M21-INV-103 URL lacks host")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    if not address.is_global:
        raise IntegrityError("M21-INV-104 private or non-global address is forbidden")
    return address.compressed


def canonicalize_url(value: str, *, allowed_hosts: set[str]) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH:
        raise IntegrityError("M21-INV-105 URL is empty or exceeds bounds")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise IntegrityError("M21-INV-106 only HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise IntegrityError("M21-INV-107 URL userinfo is forbidden")
    if parsed.fragment:
        raise IntegrityError("M21-INV-108 URL fragments are forbidden")
    if parsed.port not in (None, 443):
        raise IntegrityError("M21-INV-109 non-canonical ports are forbidden")
    host = _normalise_host(parsed.hostname or "")
    normalised_allowed = {_normalise_host(item) for item in allowed_hosts}
    if host not in normalised_allowed:
        raise IntegrityError("M21-INV-110 host is not allowlisted")
    path = posixpath.normpath(parsed.path or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    if parsed.path.endswith("/") and not path.endswith("/"):
        path = f"{path}/"
    netloc = host
    canonical = SplitResult("https", netloc, path, parsed.query, "")
    return urlunsplit(canonical)


def build_connector_descriptor(payload: dict[str, Any], *, allowed_hosts: set[str]) -> ConnectorDescriptor:
    if not isinstance(payload, dict):
        raise IntegrityError("M21-INV-111 connector descriptor must be an object")
    source_kind = payload.get("source_kind")
    media_type = payload.get("media_type")
    max_bytes = payload.get("max_bytes")
    redirect_limit = payload.get("redirect_limit", MAX_REDIRECTS)
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise IntegrityError("M21-INV-112 unsupported source kind")
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise IntegrityError("M21-INV-113 unsupported media type")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= MAX_DECLARED_BYTES:
        raise IntegrityError("M21-INV-114 max bytes exceeds bounds")
    if not isinstance(redirect_limit, int) or isinstance(redirect_limit, bool) or not 0 <= redirect_limit <= MAX_REDIRECTS:
        raise IntegrityError("M21-INV-115 redirect limit exceeds bounds")
    if payload.get("credentials_required") is True:
        raise IntegrityError("M21-INV-116 public blog inventory must not require credentials")
    canonical_url = canonicalize_url(payload.get("url"), allowed_hosts=allowed_hosts)
    return ConnectorDescriptor(
        source_kind=source_kind,
        canonical_url=canonical_url,
        host=urlsplit(canonical_url).hostname or "",
        media_type=media_type,
        max_bytes=max_bytes,
        redirect_limit=redirect_limit,
    )


def _parse_time(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M21-INV-117 invalid {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError(f"M21-INV-117 invalid {label}") from exc
    if parsed.tzinfo is None:
        raise IntegrityError(f"M21-INV-117 invalid {label}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_inventory_snapshot(
    identity_payload: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    allowed_hosts: set[str],
) -> dict[str, Any]:
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise IntegrityError("M21-INV-118 inventory item count exceeds bounds")
    identity = InventoryIdentity(
        engine_sha=_sha(identity_payload.get("engine_sha"), label="Engine SHA"),
        source_sha=_sha(identity_payload.get("source_sha"), label="Source SHA"),
        foundation_sha=_sha(identity_payload.get("foundation_sha"), label="Foundation SHA"),
        captured_at=_parse_time(identity_payload.get("captured_at"), label="capture time"),
    )
    canonical_seen: set[str] = set()
    digest_seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise IntegrityError("M21-INV-119 inventory item must be an object")
        canonical_url = canonicalize_url(raw.get("canonical_url"), allowed_hosts=allowed_hosts)
        if canonical_url in canonical_seen:
            raise IntegrityError("M21-INV-120 duplicate canonical URL")
        canonical_seen.add(canonical_url)
        content_sha256 = _digest(raw.get("content_sha256"), label="content digest")
        if content_sha256 in digest_seen:
            raise IntegrityError("M21-INV-121 duplicate content digest")
        digest_seen.add(content_sha256)
        redirects = raw.get("redirects", [])
        if not isinstance(redirects, list) or len(redirects) > MAX_REDIRECTS:
            raise IntegrityError("M21-INV-122 redirect chain exceeds bounds")
        canonical_redirects = [canonicalize_url(item, allowed_hosts=allowed_hosts) for item in redirects]
        if len(set(canonical_redirects)) != len(canonical_redirects) or canonical_url in canonical_redirects:
            raise IntegrityError("M21-INV-123 redirect loop detected")
        access_status = raw.get("access_status")
        intake_status = raw.get("intake_status")
        audience = raw.get("audience")
        if access_status not in ALLOWED_ACCESS or intake_status not in ALLOWED_INTAKE:
            raise IntegrityError("M21-INV-124 invalid inventory status")
        if audience not in ALLOWED_AUDIENCES:
            raise IntegrityError("M21-INV-125 invalid audience")
        source_kind = raw.get("source_kind")
        if source_kind not in ALLOWED_SOURCE_KINDS:
            raise IntegrityError("M21-INV-126 invalid source kind")
        locator = raw.get("locator")
        ownership_basis = raw.get("ownership_basis")
        if not isinstance(locator, str) or not locator or len(locator) > 2_048:
            raise IntegrityError("M21-INV-127 invalid locator")
        if not isinstance(ownership_basis, str) or not ownership_basis or len(ownership_basis) > 500:
            raise IntegrityError("M21-INV-128 invalid ownership basis")
        translated = raw.get("translated_counterpart")
        translated_url = None if translated is None else canonicalize_url(translated, allowed_hosts=allowed_hosts)
        published_at = raw.get("published_at")
        modified_at = raw.get("modified_at")
        records.append(
            {
                "canonical_url": canonical_url,
                "language": raw.get("language"),
                "slug": raw.get("slug"),
                "series": raw.get("series"),
                "part": raw.get("part"),
                "published_at": None if published_at is None else _parse_time(published_at, label="publication time"),
                "modified_at": None if modified_at is None else _parse_time(modified_at, label="modified time"),
                "content_sha256": content_sha256,
                "source_kind": source_kind,
                "locator": locator,
                "redirects": canonical_redirects,
                "translated_counterpart": translated_url,
                "access_status": access_status,
                "intake_status": intake_status,
                "ownership_basis": ownership_basis,
                "audience": audience,
            }
        )
    records.sort(key=lambda item: item["canonical_url"])
    snapshot = {
        "schema": "knowledge-engine-blog-inventory/v1",
        "identity": identity.__dict__,
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "items": records,
    }
    canonical_bytes = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot["snapshot_sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    return snapshot


__all__ = [
    "ConnectorDescriptor",
    "InventoryIdentity",
    "build_connector_descriptor",
    "build_inventory_snapshot",
    "canonicalize_url",
]
