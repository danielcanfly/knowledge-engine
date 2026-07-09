from __future__ import annotations

import json
from typing import Any

from .errors import IntegrityError

AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def _normalized(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _source_audience(
    source: dict[str, Any],
    *,
    record: dict[str, Any],
    concept_audience: str,
) -> str:
    audience = source.get("audience")
    if audience is None:
        access = record.get("access")
        if isinstance(access, dict):
            source_audiences = access.get("source_audiences")
            if (
                isinstance(source_audiences, list)
                and len(source_audiences) == 1
                and source_audiences[0] in AUDIENCE_RANK
            ):
                audience = source_audiences[0]
            elif access.get("declassified") is True:
                audience = "restricted"
    if audience is None:
        audience = concept_audience
    if audience not in AUDIENCE_RANK:
        raise IntegrityError(
            "provenance source has invalid audience: "
            f"{source.get('source_id', 'unknown')}"
        )
    return str(audience)


def _source_catalog(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = record.get("sources", [])
    if not isinstance(sources, list):
        raise IntegrityError("provenance sources must be a list")
    catalog: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise IntegrityError("provenance source must be an object")
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise IntegrityError("provenance source is missing source_id")
        if source_id in catalog:
            raise IntegrityError(f"duplicate provenance source_id: {source_id}")
        catalog[source_id] = source
    return catalog


def _claim_matches_section(
    claim: dict[str, Any],
    *,
    section_id: str,
    section_title: str,
) -> bool:
    selector = claim.get("selector")
    if not isinstance(selector, dict):
        return False
    selected_section = selector.get("section_id")
    if isinstance(selected_section, str) and selected_section == section_id:
        return True
    heading = selector.get("heading")
    return isinstance(heading, str) and _normalized(heading) == _normalized(section_title)


def _locator_sort_key(locator: object) -> str:
    if not isinstance(locator, dict):
        return "{}"
    return json.dumps(locator, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_payload(
    source: dict[str, Any],
    *,
    concept_id: str,
    section_id: str,
    citation_scope: str,
    claim_id: str | None,
    support: str,
    locator: dict[str, Any] | None,
    claim: dict[str, Any] | None,
) -> dict[str, Any]:
    uri = source.get("uri") or source.get("locator")
    if not isinstance(uri, str) or not uri:
        raise IntegrityError(
            "provenance source is missing uri: "
            f"{source.get('source_id', 'unknown')}"
        )
    retrieved_at = source.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at:
        raise IntegrityError(
            "provenance source is missing retrieved_at: "
            f"{source.get('source_id', 'unknown')}"
        )
    content_sha256 = source.get("content_sha256")
    if content_sha256 is not None and not isinstance(content_sha256, str):
        raise IntegrityError("source content_sha256 must be a string")
    published_at = source.get("published_at")
    if published_at is not None and not isinstance(published_at, str):
        raise IntegrityError("source published_at must be a string")
    title = source.get("title") or source.get("name")
    publisher = source.get("publisher")
    source_kind = source.get("kind") or "web"
    if not isinstance(source_kind, str) or not source_kind:
        raise IntegrityError("source kind must be a non-empty string")
    if title is not None and not isinstance(title, str):
        raise IntegrityError("source title must be a string")
    if publisher is not None and not isinstance(publisher, str):
        raise IntegrityError("source publisher must be a string")
    return {
        "source_id": source["source_id"],
        "source_kind": source_kind,
        "source_title": title,
        "publisher": publisher,
        "uri": uri,
        "retrieved_at": retrieved_at,
        "published_at": published_at,
        "content_sha256": content_sha256,
        "snapshot_available": bool(source.get("snapshot_key")),
        "concept_id": concept_id,
        "section_id": section_id,
        "citation_scope": citation_scope,
        "claim_id": claim_id,
        "support": support,
        "locator": locator,
        "claim_confidence": claim.get("confidence") if claim else None,
        "review_status": claim.get("review_status") if claim else None,
        "derivation_type": claim.get("derivation_type") if claim else None,
    }


def citation_evidence_for_section(
    *,
    record: dict[str, Any],
    document: dict[str, Any],
    maximum_audience_rank: int,
) -> tuple[list[dict[str, Any]], int]:
    concept_id = str(document["concept_id"])
    section_id = str(document["section_id"])
    section_title = str(document["section_title"])
    concept_audience = str(document["audience"])
    catalog = _source_catalog(record)
    claims = record.get("claims", [])
    if not isinstance(claims, list):
        raise IntegrityError("provenance claims must be a list")
    matching_claims = [
        claim
        for claim in claims
        if isinstance(claim, dict)
        and _claim_matches_section(
            claim,
            section_id=section_id,
            section_title=section_title,
        )
    ]
    matching_claims.sort(key=lambda claim: str(claim.get("claim_id") or ""))

    output: list[dict[str, Any]] = []
    filtered_sources: set[str] = set()
    if matching_claims:
        for claim in matching_claims:
            claim_id = claim.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id:
                raise IntegrityError("matching provenance claim is missing claim_id")
            evidence = claim.get("evidence", [])
            if not isinstance(evidence, list):
                raise IntegrityError(f"claim evidence must be a list: {claim_id}")
            ordered_evidence = sorted(
                evidence,
                key=lambda item: (
                    str(item.get("source_ref") or "")
                    if isinstance(item, dict)
                    else "",
                    str(item.get("support") or "")
                    if isinstance(item, dict)
                    else "",
                    _locator_sort_key(item.get("locator"))
                    if isinstance(item, dict)
                    else "{}",
                ),
            )
            for item in ordered_evidence:
                if not isinstance(item, dict):
                    raise IntegrityError(f"claim evidence must be an object: {claim_id}")
                source_ref = item.get("source_ref")
                if not isinstance(source_ref, str) or source_ref not in catalog:
                    raise IntegrityError(
                        f"claim evidence references unknown source: {claim_id}"
                    )
                source = catalog[source_ref]
                audience = _source_audience(
                    source,
                    record=record,
                    concept_audience=concept_audience,
                )
                if AUDIENCE_RANK[audience] > maximum_audience_rank:
                    filtered_sources.add(source_ref)
                    continue
                locator = item.get("locator")
                if locator is not None and not isinstance(locator, dict):
                    raise IntegrityError(f"claim locator must be an object: {claim_id}")
                support = item.get("support") or "context"
                if not isinstance(support, str) or not support:
                    raise IntegrityError(f"claim support must be a string: {claim_id}")
                output.append(
                    _source_payload(
                        source,
                        concept_id=concept_id,
                        section_id=section_id,
                        citation_scope="claim",
                        claim_id=claim_id,
                        support=support,
                        locator=locator,
                        claim=claim,
                    )
                )
    else:
        for source_id in sorted(catalog):
            source = catalog[source_id]
            audience = _source_audience(
                source,
                record=record,
                concept_audience=concept_audience,
            )
            if AUDIENCE_RANK[audience] > maximum_audience_rank:
                filtered_sources.add(source_id)
                continue
            output.append(
                _source_payload(
                    source,
                    concept_id=concept_id,
                    section_id=section_id,
                    citation_scope="concept",
                    claim_id=None,
                    support="context",
                    locator=None,
                    claim=None,
                )
            )
    return output, len(filtered_sources)
