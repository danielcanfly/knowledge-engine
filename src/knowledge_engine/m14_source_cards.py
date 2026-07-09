from __future__ import annotations

import hashlib
import ipaddress
import json
from collections import OrderedDict
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FORBIDDEN_QUERY_PARTS = {
    "access_key",
    "api_key",
    "auth",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
}
LOCATOR_FIELDS = {
    "heading",
    "page",
    "paragraph",
    "start_line",
    "end_line",
    "timecode",
    "anchor",
}


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    return f"{prefix}_{hashlib.sha256(_canonical_bytes(value)).hexdigest()[:32]}"


def _safe_host(hostname: str) -> bool:
    lowered = hostname.casefold().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        return False
    if lowered.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def safe_public_uri(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if not parsed.hostname or parsed.username or parsed.password:
        return None
    if not _safe_host(parsed.hostname):
        return None
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    for key, _ in query_items:
        normalized = key.casefold().replace("-", "_")
        if normalized in FORBIDDEN_QUERY_PARTS:
            return None
        if any(part in normalized for part in ("token", "secret", "signature")):
            return None
    canonical_query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            parsed.path or "/",
            canonical_query,
            "",
        )
    )


def _safe_locator(value: object) -> dict[str, str | int | float] | None:
    if not isinstance(value, dict):
        return None
    output: dict[str, str | int | float] = {}
    for key in sorted(LOCATOR_FIELDS):
        item = value.get(key)
        if isinstance(item, bool) or item is None:
            continue
        if isinstance(item, (int, float)):
            if item >= 0:
                output[key] = item
            continue
        if isinstance(item, str):
            compact = " ".join(item.split())
            if compact:
                output[key] = compact[:200]
    return output or None


def _safe_sha256(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    lowered = value.casefold()
    if any(character not in "0123456789abcdef" for character in lowered):
        return None
    return lowered


def _display_host(uri: str) -> str:
    host = urlsplit(uri).hostname or ""
    return host[4:] if host.casefold().startswith("www.") else host


def _candidate_identity(candidate: dict[str, Any], uri: str) -> tuple[str, ...]:
    locator = _safe_locator(candidate.get("locator"))
    return (
        str(candidate.get("source_id") or ""),
        uri,
        str(candidate.get("concept_id") or ""),
        str(candidate.get("section_id") or ""),
        str(candidate.get("citation_scope") or "concept"),
        str(candidate.get("support") or "context"),
        json.dumps(locator or {}, ensure_ascii=False, sort_keys=True),
    )


def build_public_citation_payload(
    *,
    results: list[dict[str, Any]],
    release_id: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[tuple[str, str], list[int]],
]:
    grouped: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
    for result in results:
        candidates = result.get("citations", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            uri = safe_public_uri(candidate.get("uri"))
            if uri is None:
                continue
            identity = _candidate_identity(candidate, uri)
            item = grouped.get(identity)
            claim_id = candidate.get("claim_id")
            if item is None:
                source_id = identity[0]
                title = candidate.get("source_title")
                display_host = _display_host(uri)
                item = {
                    "source_id": source_id,
                    "source_kind": str(candidate.get("source_kind") or "web"),
                    "source_title": (
                        " ".join(title.split())[:240]
                        if isinstance(title, str) and title.strip()
                        else display_host or source_id
                    ),
                    "publisher": (
                        " ".join(candidate["publisher"].split())[:160]
                        if isinstance(candidate.get("publisher"), str)
                        and candidate["publisher"].strip()
                        else display_host
                    ),
                    "display_host": display_host,
                    "uri": uri,
                    "retrieved_at": str(candidate.get("retrieved_at") or ""),
                    "published_at": (
                        str(candidate["published_at"])
                        if candidate.get("published_at") is not None
                        else None
                    ),
                    "integrity_sha256": _safe_sha256(
                        candidate.get("content_sha256")
                    ),
                    "snapshot_available": bool(
                        candidate.get("snapshot_available", False)
                    ),
                    "concept_id": identity[2],
                    "section_id": identity[3],
                    "citation_scope": identity[4],
                    "support": identity[5],
                    "locator": _safe_locator(candidate.get("locator")),
                    "claim_ids": [],
                    "claim_confidence": candidate.get("claim_confidence"),
                    "review_status": candidate.get("review_status"),
                    "derivation_type": candidate.get("derivation_type"),
                }
                grouped[identity] = item
            if isinstance(claim_id, str) and claim_id and claim_id not in item["claim_ids"]:
                item["claim_ids"].append(claim_id)

    citations: list[dict[str, Any]] = []
    source_cards_by_identity: OrderedDict[tuple[str, str, str | None], dict[str, Any]] = (
        OrderedDict()
    )
    ordinals: dict[tuple[str, str], list[int]] = {}
    for ordinal, item in enumerate(grouped.values(), start=1):
        item["claim_ids"].sort()
        source_identity = (
            item["source_id"],
            item["uri"],
            item["integrity_sha256"],
        )
        source_card_id = _stable_id(
            "card",
            {
                "release_id": release_id,
                "source_id": item["source_id"],
                "uri": item["uri"],
                "integrity_sha256": item["integrity_sha256"],
            },
        )
        citation_id = _stable_id(
            "cite",
            {
                "release_id": release_id,
                "source_card_id": source_card_id,
                "concept_id": item["concept_id"],
                "section_id": item["section_id"],
                "citation_scope": item["citation_scope"],
                "support": item["support"],
                "locator": item["locator"],
                "claim_ids": item["claim_ids"],
            },
        )
        citation = {
            "schema_version": "knowledge-engine-public-citation/v1",
            "citation_id": citation_id,
            "ordinal": ordinal,
            "source_card_id": source_card_id,
            "source_id": item["source_id"],
            "source_kind": item["source_kind"],
            "uri": item["uri"],
            "retrieved_at": item["retrieved_at"],
            "concept_id": item["concept_id"],
            "section_id": item["section_id"],
            "citation_scope": item["citation_scope"],
            "claim_ids": item["claim_ids"],
            "support": item["support"],
            "locator": item["locator"],
            "claim_confidence": item["claim_confidence"],
            "review_status": item["review_status"],
            "derivation_type": item["derivation_type"],
        }
        citations.append(citation)
        result_key = (item["concept_id"], item["section_id"])
        ordinals.setdefault(result_key, []).append(ordinal)

        card = source_cards_by_identity.get(source_identity)
        if card is None:
            card = {
                "schema_version": "knowledge-engine-source-card/v1",
                "source_card_id": source_card_id,
                "ordinal": ordinal,
                "source_id": item["source_id"],
                "title": item["source_title"],
                "publisher": item["publisher"],
                "display_host": item["display_host"],
                "source_kind": item["source_kind"],
                "uri": item["uri"],
                "retrieved_at": item["retrieved_at"],
                "published_at": item["published_at"],
                "snapshot_available": item["snapshot_available"],
                "integrity_sha256": item["integrity_sha256"],
                "citation_ids": [],
                "concept_ids": [],
                "section_ids": [],
                "claim_ids": [],
            }
            source_cards_by_identity[source_identity] = card
        card["citation_ids"].append(citation_id)
        for field, value in (
            ("concept_ids", item["concept_id"]),
            ("section_ids", item["section_id"]),
        ):
            if value not in card[field]:
                card[field].append(value)
        for claim_id in item["claim_ids"]:
            if claim_id not in card["claim_ids"]:
                card["claim_ids"].append(claim_id)

    cards = list(source_cards_by_identity.values())
    for card in cards:
        card["concept_ids"].sort()
        card["section_ids"].sort()
        card["claim_ids"].sort()
    return citations, cards, ordinals
