from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError

ALIAS_WEIGHT = 120
TAG_WEIGHT = 20
RELATION_WEIGHT = 10
MAX_TAG_SCORE = 60
MAX_RELATION_SCORE = 40
MAX_CANDIDATES = 40
MAX_ALIASES = 20
MAX_TAGS = 30
MAX_RELATIONS = 20
MAX_TOKEN_LENGTH = 160
MAX_QUERY_LENGTH = 8_000

_TOKEN_RE = re.compile(r"[\w-]+", flags=re.UNICODE)


@dataclass(frozen=True)
class RelationSignal:
    relation_type: str
    target_concept_id: str


@dataclass(frozen=True)
class EnrichmentRow:
    section_id: str
    concept_id: str
    audience: str
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    relations: tuple[RelationSignal, ...]


@dataclass(frozen=True)
class EnrichmentBundle:
    release_id: str
    manifest_sha256: str
    rows: tuple[EnrichmentRow, ...]


def _normalise(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M20-ENRICH-101 {label} must be a string")
    normalised = unicodedata.normalize("NFKC", value).casefold().strip()
    if not normalised or len(normalised) > MAX_TOKEN_LENGTH:
        raise IntegrityError(f"M20-ENRICH-102 {label} is empty or exceeds bounds")
    return normalised


def _stable_values(values: Any, *, label: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(values, list) or len(values) > maximum:
        raise IntegrityError(f"M20-ENRICH-103 {label} must be a bounded list")
    normalised = tuple(_normalise(value, label=label) for value in values)
    if len(set(normalised)) != len(normalised):
        raise IntegrityError(f"M20-ENRICH-104 duplicate {label} value")
    return tuple(sorted(normalised))


def _parse_relation(value: Any) -> RelationSignal:
    if not isinstance(value, Mapping):
        raise IntegrityError("M20-ENRICH-105 relation must be an object")
    relation_type = _normalise(value.get("type"), label="relation type")
    target = _normalise(value.get("target_concept_id"), label="relation target")
    return RelationSignal(relation_type=relation_type, target_concept_id=target)


def parse_enrichment_bundle(payload: Mapping[str, Any]) -> EnrichmentBundle:
    if not isinstance(payload, Mapping):
        raise IntegrityError("M20-ENRICH-106 enrichment bundle must be an object")
    release_id = payload.get("release_id")
    manifest_sha256 = payload.get("manifest_sha256")
    rows = payload.get("rows")
    if not isinstance(release_id, str) or not release_id:
        raise IntegrityError("M20-ENRICH-107 bundle lacks release ID")
    if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
        raise IntegrityError("M20-ENRICH-108 bundle lacks manifest SHA-256")
    if not isinstance(rows, list) or len(rows) > MAX_CANDIDATES:
        raise IntegrityError("M20-ENRICH-109 rows must be a bounded list")

    parsed: list[EnrichmentRow] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise IntegrityError("M20-ENRICH-110 row must be an object")
        section_id = _normalise(row.get("section_id"), label="section ID")
        concept_id = _normalise(row.get("concept_id"), label="concept ID")
        audience = _normalise(row.get("audience"), label="audience")
        if section_id in seen:
            raise IntegrityError(f"M20-ENRICH-111 duplicate section row: {section_id}")
        seen.add(section_id)
        aliases = _stable_values(
            row.get("aliases", []),
            label="alias",
            maximum=MAX_ALIASES,
        )
        tags = _stable_values(
            row.get("tags", []),
            label="tag",
            maximum=MAX_TAGS,
        )
        raw_relations = row.get("relations", [])
        if not isinstance(raw_relations, list) or len(raw_relations) > MAX_RELATIONS:
            raise IntegrityError("M20-ENRICH-112 relations must be a bounded list")
        relations = tuple(sorted(
            (_parse_relation(value) for value in raw_relations),
            key=lambda item: (item.relation_type, item.target_concept_id),
        ))
        relation_keys = {
            (item.relation_type, item.target_concept_id) for item in relations
        }
        if len(relation_keys) != len(relations):
            raise IntegrityError("M20-ENRICH-113 duplicate relation signal")
        parsed.append(
            EnrichmentRow(
                section_id=section_id,
                concept_id=concept_id,
                audience=audience,
                aliases=aliases,
                tags=tags,
                relations=relations,
            )
        )
    parsed.sort(key=lambda row: row.section_id)
    return EnrichmentBundle(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        rows=tuple(parsed),
    )


def _release_identity(result: Mapping[str, Any]) -> tuple[str, str]:
    release = result.get("release")
    if not isinstance(release, Mapping):
        raise IntegrityError("M20-ENRICH-114 lexical result lacks release identity")
    release_id = release.get("release_id")
    manifest_sha256 = release.get("manifest_sha256")
    if not isinstance(release_id, str) or not isinstance(manifest_sha256, str):
        raise IntegrityError("M20-ENRICH-114 lexical result lacks release identity")
    return release_id, manifest_sha256


def _candidate_identity(item: Mapping[str, Any]) -> tuple[str, str, str]:
    values = []
    for key in ("section_id", "concept_id", "audience"):
        value = item.get(key)
        values.append(_normalise(value, label=key))
    return values[0], values[1], values[2]


def _query_terms(query: str) -> tuple[str, set[str]]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise IntegrityError("M20-ENRICH-115 query must contain 1 to 8000 characters")
    normalised = unicodedata.normalize("NFKC", query).casefold().strip()
    terms = {_normalise(token, label="query token") for token in _TOKEN_RE.findall(normalised)}
    return normalised, terms


def _relation_matches(
    relation: RelationSignal,
    query_text: str,
    query_terms: set[str],
) -> bool:
    relation_tokens = {
        relation.relation_type,
        relation.target_concept_id,
    }
    relation_tokens.update(_TOKEN_RE.findall(relation.target_concept_id))
    return any(token in query_terms or token in query_text for token in relation_tokens)


def enrich_lexical_results(
    lexical_result: Mapping[str, Any],
    query: str,
    allowed_audiences: set[str],
    bundle_payload: Mapping[str, Any],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise IntegrityError("M20-ENRICH-116 limit must be an integer between 1 and 20")
    if not allowed_audiences:
        raise IntegrityError("M20-ENRICH-117 allowed audiences must be non-empty")

    result = copy.deepcopy(dict(lexical_result))
    candidates = result.get("results")
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise IntegrityError("M20-ENRICH-118 lexical results must be a bounded list")
    bundle = parse_enrichment_bundle(bundle_payload)
    if _release_identity(result) != (bundle.release_id, bundle.manifest_sha256):
        raise IntegrityError("M20-ENRICH-119 lexical and enrichment release identities differ")

    query_text, query_terms = _query_terms(query)
    rows = {row.section_id: row for row in bundle.rows}
    seen: set[str] = set()
    enriched: list[dict[str, Any]] = []

    for rank, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, Mapping):
            raise IntegrityError("M20-ENRICH-120 lexical candidate must be an object")
        section_id, concept_id, audience = _candidate_identity(candidate)
        if section_id in seen:
            raise IntegrityError(f"M20-ENRICH-121 duplicate lexical section: {section_id}")
        seen.add(section_id)
        if audience not in {value.casefold() for value in allowed_audiences}:
            raise IntegrityError(f"M20-ENRICH-122 unauthorised lexical row: {section_id}")
        row = rows.get(section_id)
        if row is None:
            raise IntegrityError(f"M20-ENRICH-123 missing enrichment row: {section_id}")
        if row.concept_id != concept_id or row.audience != audience:
            raise IntegrityError(f"M20-ENRICH-124 identity drift for section: {section_id}")

        matched_aliases = tuple(alias for alias in row.aliases if alias == query_text)
        matched_tags = tuple(tag for tag in row.tags if tag in query_terms)
        matched_relations = tuple(
            relation
            for relation in row.relations
            if _relation_matches(relation, query_text, query_terms)
        )
        alias_score = ALIAS_WEIGHT if matched_aliases else 0
        tag_score = min(MAX_TAG_SCORE, len(matched_tags) * TAG_WEIGHT)
        relation_score = min(
            MAX_RELATION_SCORE,
            len(matched_relations) * RELATION_WEIGHT,
        )
        signal_score = alias_score + tag_score + relation_score
        enriched.append(
            {
                "section_id": section_id,
                "concept_id": concept_id,
                "audience": audience,
                "signal_score": signal_score,
                "base_lexical_rank": rank,
                "matched_aliases": list(matched_aliases),
                "matched_tags": list(matched_tags),
                "matched_relations": [
                    {
                        "type": item.relation_type,
                        "target_concept_id": item.target_concept_id,
                    }
                    for item in matched_relations
                ],
                "alias_score": alias_score,
                "tag_score": tag_score,
                "relation_score": relation_score,
                "lexical_result": copy.deepcopy(dict(candidate)),
            }
        )

    extra_rows = sorted(set(rows) - seen)
    if extra_rows:
        raise IntegrityError("M20-ENRICH-125 bundle contains unknown lexical sections")

    enriched.sort(
        key=lambda item: (
            -item["signal_score"],
            item["base_lexical_rank"],
            item["section_id"],
        )
    )
    retrieval = result.setdefault("retrieval", {})
    retrieval.update(
        {
            "lexical_enrichment_applied": True,
            "lexical_enrichment_authoritative": False,
            "alias_weight": ALIAS_WEIGHT,
            "tag_weight": TAG_WEIGHT,
            "relation_weight": RELATION_WEIGHT,
            "production_authority": False,
        }
    )
    result["enriched_lexical_candidates"] = enriched[:limit]
    return result


__all__ = [
    "ALIAS_WEIGHT",
    "EnrichmentBundle",
    "EnrichmentRow",
    "RELATION_WEIGHT",
    "RelationSignal",
    "TAG_WEIGHT",
    "enrich_lexical_results",
    "parse_enrichment_bundle",
]
