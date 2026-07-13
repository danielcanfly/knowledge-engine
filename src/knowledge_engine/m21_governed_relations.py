from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any

from .errors import IntegrityError

FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
MAX_MAPPINGS = 1_000
MAX_QUALIFIERS = 4
ENDPOINT_KINDS = {"concept", "entity"}
PRIMARY_TYPES = {
    "is_a",
    "part_of",
    "uses",
    "produces",
    "requires",
    "implements",
    "supports",
    "contrasts_with",
    "complements",
    "alternative_to",
    "supersedes",
    "related_to",
}
QUALIFIERS = {"scope", "context", "valid_from", "valid_to"}
RELATIONS = [
    ("is_a", True, False, "has_subtype", "reviewed_structural", ("taxonomy",)),
    ("has_subtype", True, False, "is_a", "reviewed_structural", ("taxonomy",)),
    ("part_of", True, False, "has_part", "reviewed_structural", ("composition",)),
    ("has_part", True, False, "part_of", "reviewed_structural", ("composition",)),
    (
        "uses",
        True,
        False,
        "used_by",
        "required_or_reviewed_structural",
        ("dependency",),
    ),
    (
        "used_by",
        True,
        False,
        "uses",
        "required_or_reviewed_structural",
        ("dependency",),
    ),
    ("produces", True, False, "produced_by", "required_factual", ("production",)),
    ("produced_by", True, False, "produces", "required_factual", ("production",)),
    ("requires", True, False, "required_by", "required_factual", ("dependency",)),
    ("required_by", True, False, "requires", "required_factual", ("dependency",)),
    (
        "implements",
        True,
        False,
        "implemented_by",
        "required_or_reviewed_structural",
        ("implementation",),
    ),
    (
        "implemented_by",
        True,
        False,
        "implements",
        "required_or_reviewed_structural",
        ("implementation",),
    ),
    ("supports", True, False, "supported_by", "required_factual", ("dependency",)),
    ("supported_by", True, False, "supports", "required_factual", ("dependency",)),
    (
        "contrasts_with",
        False,
        True,
        "contrasts_with",
        "required_factual",
        ("comparison",),
    ),
    ("complements", False, True, "complements", "required_factual", ("complement",)),
    (
        "alternative_to",
        False,
        True,
        "alternative_to",
        "required_factual",
        ("comparison",),
    ),
    ("supersedes", True, False, "superseded_by", "required_factual", ("evolution",)),
    ("superseded_by", True, False, "supersedes", "required_factual", ("evolution",)),
    ("related_to", False, True, "related_to", "required_factual", ("generic",)),
]
TAG_DIMENSIONS = {
    "domain": ["agents", "evaluation", "knowledge-systems", "rag"],
    "concern": ["governance", "observability", "reliability", "security"],
    "lifecycle": ["build", "design", "operations", "runtime"],
    "technique": ["planning", "retrieval", "routing", "verification"],
}
TAG_ALIASES = {
    "knowledge-system": "knowledge-systems",
    "observability-engineering": "observability",
    "retrieval-augmented-generation": "rag",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S{8,}"),
)


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _signed(value: dict[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or _digest(unsigned) != claimed:
        raise IntegrityError(code)
    return claimed


def _text(value: Any, label: str, maximum: int = 300) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M21-GOV-101 invalid {label}")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M21-GOV-101 invalid {label}")
    if any(pattern.search(normalized) for pattern in SECRET_PATTERNS):
        raise IntegrityError(f"M21-GOV-102 secret-like {label}")
    return normalized


def _confidence(value: Any, ceiling: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntegrityError(f"M21-GOV-103 invalid {label} confidence")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1 or number > ceiling:
        raise IntegrityError(f"M21-GOV-103 invalid {label} confidence")
    return round(number, 6)


def _validate_packet(packet: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    if packet.get("schema") != "knowledge-engine-extraction-candidates/v1":
        raise IntegrityError("M21-GOV-104 invalid M21.3 packet schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-GOV-105 packet digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
    ):
        raise IntegrityError("M21-GOV-106 packet authority drift")
    identity = packet.get("identity")
    if not isinstance(identity, dict) or identity.get("foundation_sha") != FOUNDATION_SHA:
        raise IntegrityError("M21-GOV-107 Foundation identity mismatch")
    candidates = packet.get("candidates")
    if not isinstance(candidates, list) or packet.get("candidate_count") != len(candidates):
        raise IntegrityError("M21-GOV-108 candidate coverage mismatch")
    output: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise IntegrityError("M21-GOV-109 malformed candidate")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in output:
            raise IntegrityError("M21-GOV-110 duplicate candidate id")
        if (
            candidate.get("authority") != "candidate_only"
            or candidate.get("canonical_knowledge") is not False
            or candidate.get("production_authority") is not False
            or candidate.get("status") != "pending_review"
        ):
            raise IntegrityError("M21-GOV-111 candidate authority drift")
        evidence = candidate.get("evidence_spans")
        if not isinstance(evidence, list) or not evidence:
            raise IntegrityError("M21-GOV-112 candidate evidence missing")
        output[candidate_id] = candidate
    return packet_sha, output


def _validate_ontology(value: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    if set(value) != {
        "schema_version",
        "ontology_id",
        "version",
        "status",
        "fallback_type",
        "relation_types",
    }:
        raise IntegrityError("M21-GOV-113 ontology shape drift")
    if (
        value.get("schema_version") != "knowledge-os-relation-ontology/v0.1"
        or value.get("ontology_id") != "daniel-knowledge-os/relation-ontology"
        or value.get("version") != "0.1.0"
        or value.get("status") != "normative_draft"
        or value.get("fallback_type") != "related_to"
    ):
        raise IntegrityError("M21-GOV-114 ontology identity drift")
    entries = value.get("relation_types")
    if not isinstance(entries, list) or len(entries) != len(RELATIONS):
        raise IntegrityError("M21-GOV-115 ontology relation coverage drift")
    output: dict[str, dict[str, Any]] = {}
    for entry, expected in zip(entries, RELATIONS, strict=True):
        if not isinstance(entry, dict) or set(entry) != {
            "type",
            "directed",
            "symmetric",
            "inverse",
            "provenance_expectation",
            "allowed_qualifiers",
            "retrieval_semantics",
            "description",
        }:
            raise IntegrityError("M21-GOV-116 relation ontology entry drift")
        relation_type, directed, symmetric, inverse, provenance, retrieval = expected
        if (
            entry.get("type") != relation_type
            or entry.get("directed") is not directed
            or entry.get("symmetric") is not symmetric
            or entry.get("inverse") != inverse
            or entry.get("provenance_expectation") != provenance
            or entry.get("allowed_qualifiers") != [
                "scope",
                "context",
                "valid_from",
                "valid_to",
            ]
            or tuple(entry.get("retrieval_semantics", ())) != retrieval
            or not isinstance(entry.get("description"), str)
            or not 20 <= len(entry["description"]) <= 300
        ):
            raise IntegrityError("M21-GOV-117 relation ontology semantics drift")
        if relation_type in output:
            raise IntegrityError("M21-GOV-118 duplicate ontology relation")
        output[relation_type] = entry
    for relation_type, entry in output.items():
        inverse = output.get(entry["inverse"])
        if inverse is None or inverse.get("inverse") != relation_type:
            raise IntegrityError("M21-GOV-119 non-reciprocal inverse")
        if entry["directed"] == entry["symmetric"]:
            raise IntegrityError("M21-GOV-120 invalid direction invariant")
        if entry["symmetric"] and entry["inverse"] != relation_type:
            raise IntegrityError("M21-GOV-121 symmetric relation is not self-inverse")
    return _digest(value), output


def _validate_taxonomy(value: dict[str, Any]) -> tuple[str, dict[str, str]]:
    if set(value) != {
        "schema_version",
        "taxonomy_id",
        "version",
        "status",
        "dimensions",
        "tag_aliases",
    }:
        raise IntegrityError("M21-GOV-122 taxonomy shape drift")
    if (
        value.get("schema_version") != "knowledge-os-tag-taxonomy/v0.1"
        or value.get("taxonomy_id") != "daniel-knowledge-os/tag-taxonomy"
        or value.get("version") != "0.1.0"
        or value.get("status") != "active"
        or value.get("dimensions") != TAG_DIMENSIONS
        or value.get("tag_aliases") != TAG_ALIASES
    ):
        raise IntegrityError("M21-GOV-123 taxonomy semantics drift")
    canonical: dict[str, str] = {}
    for dimension, tags in TAG_DIMENSIONS.items():
        for tag in tags:
            if tag in canonical:
                raise IntegrityError("M21-GOV-124 duplicate canonical tag")
            canonical[tag] = dimension
    for alias, target in TAG_ALIASES.items():
        if alias in canonical or target not in canonical or target in TAG_ALIASES:
            raise IntegrityError("M21-GOV-125 invalid governed tag alias")
    return _digest(value), canonical


def _names(candidate: dict[str, Any]) -> set[str]:
    values = [candidate.get("label"), candidate.get("normalized_label")]
    values.extend(candidate.get("aliases", []))
    return {
        _text(value, "endpoint name", 200).casefold()
        for value in values
        if isinstance(value, str)
    }


def _qualifiers(value: Any, allowed: list[str]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_QUALIFIERS:
        raise IntegrityError("M21-GOV-126 invalid qualifiers")
    if set(value) - set(allowed) or set(value) - QUALIFIERS:
        raise IntegrityError("M21-GOV-127 unsupported qualifier")
    return {key: _text(value[key], f"qualifier {key}", 300) for key in sorted(value)}


def _relation_candidate(
    mapping: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    ontology: dict[str, dict[str, Any]],
    packet_sha: str,
) -> dict[str, Any]:
    if not isinstance(mapping, dict) or set(mapping) != {
        "hint_candidate_id",
        "source_candidate_id",
        "target_candidate_id",
        "relation_type",
        "direction",
        "confidence",
        "qualifiers",
    }:
        raise IntegrityError("M21-GOV-128 malformed relation mapping")
    hint = candidates.get(mapping["hint_candidate_id"])
    source = candidates.get(mapping["source_candidate_id"])
    target = candidates.get(mapping["target_candidate_id"])
    if hint is None or hint.get("kind") != "relation_hint":
        raise IntegrityError("M21-GOV-129 unresolved relation hint")
    if source is None or target is None:
        raise IntegrityError("M21-GOV-130 unresolved relation endpoint")
    if source.get("kind") not in ENDPOINT_KINDS or target.get("kind") not in ENDPOINT_KINDS:
        raise IntegrityError("M21-GOV-131 invalid relation endpoint kind")
    if mapping["source_candidate_id"] == mapping["target_candidate_id"]:
        raise IntegrityError("M21-GOV-132 relation self-loop forbidden")
    if hint.get("source_label", "").casefold() not in _names(source):
        raise IntegrityError("M21-GOV-133 source label does not resolve")
    if hint.get("target_label", "").casefold() not in _names(target):
        raise IntegrityError("M21-GOV-134 target label does not resolve")
    relation_type = mapping.get("relation_type")
    entry = ontology.get(relation_type)
    if relation_type not in PRIMARY_TYPES or entry is None:
        raise IntegrityError("M21-GOV-135 unknown or inverse-only relation type")
    expected_direction = "directed" if entry["directed"] else "undirected"
    if mapping.get("direction") != expected_direction:
        raise IntegrityError("M21-GOV-136 relation direction mismatch")
    confidence = _confidence(mapping.get("confidence"), float(hint["confidence"]), "relation")
    qualifiers = _qualifiers(mapping.get("qualifiers"), entry["allowed_qualifiers"])
    candidate = {
        "hint_candidate_id": hint["candidate_id"],
        "source_candidate_id": source["candidate_id"],
        "target_candidate_id": target["candidate_id"],
        "relation_type": relation_type,
        "direction": expected_direction,
        "inverse_type": entry["inverse"],
        "provenance_expectation": entry["provenance_expectation"],
        "retrieval_semantics": entry["retrieval_semantics"],
        "qualifiers": qualifiers,
        "confidence": confidence,
        "evidence_spans": hint["evidence_spans"],
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    candidate["relation_candidate_id"] = (
        f"typedrelcand_{_digest({'packet': packet_sha, 'candidate': candidate})[:32]}"
    )
    return candidate


def _tag_candidate(
    mapping: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    canonical: dict[str, str],
    packet_sha: str,
) -> dict[str, Any]:
    if not isinstance(mapping, dict) or set(mapping) != {
        "candidate_id",
        "source_tag",
        "dimension",
        "confidence",
    }:
        raise IntegrityError("M21-GOV-137 malformed tag mapping")
    source = candidates.get(mapping["candidate_id"])
    if source is None or source.get("kind") not in ENDPOINT_KINDS:
        raise IntegrityError("M21-GOV-138 unresolved tag candidate")
    source_tag = _text(mapping.get("source_tag"), "source tag", 80)
    source_tags = source.get("controlled_tags", [])
    if source_tag not in source_tags:
        raise IntegrityError("M21-GOV-139 tag lacks M21.3 evidence")
    canonical_tag = TAG_ALIASES.get(source_tag, source_tag)
    dimension = canonical.get(canonical_tag)
    if dimension is None:
        raise IntegrityError("M21-GOV-140 unknown governed tag")
    if mapping.get("dimension") != dimension:
        raise IntegrityError("M21-GOV-141 governed tag dimension mismatch")
    candidate = {
        "source_candidate_id": source["candidate_id"],
        "source_tag": source_tag,
        "canonical_tag": canonical_tag,
        "dimension": dimension,
        "confidence": _confidence(mapping.get("confidence"), float(source["confidence"]), "tag"),
        "evidence_spans": source["evidence_spans"],
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    candidate["tag_candidate_id"] = (
        f"tagcand_{_digest({'packet': packet_sha, 'candidate': candidate})[:32]}"
    )
    return candidate


def build_governed_candidate_packet(
    extraction_packet: dict[str, Any],
    relation_mappings: list[dict[str, Any]],
    tag_mappings: list[dict[str, Any]],
    *,
    foundation_sha: str,
    relation_ontology: dict[str, Any],
    tag_taxonomy: dict[str, Any],
) -> dict[str, Any]:
    if foundation_sha != FOUNDATION_SHA:
        raise IntegrityError("M21-GOV-142 unpinned Foundation identity")
    packet_sha, candidates = _validate_packet(extraction_packet)
    ontology_sha, ontology = _validate_ontology(relation_ontology)
    taxonomy_sha, canonical_tags = _validate_taxonomy(tag_taxonomy)
    if (
        not isinstance(relation_mappings, list)
        or not isinstance(tag_mappings, list)
        or len(relation_mappings) > MAX_MAPPINGS
        or len(tag_mappings) > MAX_MAPPINGS
        or not relation_mappings and not tag_mappings
    ):
        raise IntegrityError("M21-GOV-143 mapping count exceeds bounds")
    relations = [
        _relation_candidate(mapping, candidates, ontology, packet_sha)
        for mapping in relation_mappings
    ]
    relation_keys: set[tuple[str, str, str]] = set()
    relation_ids: set[str] = set()
    for relation in relations:
        source = relation["source_candidate_id"]
        target = relation["target_candidate_id"]
        if relation["direction"] == "undirected" and target < source:
            source, target = target, source
        key = (source, target, relation["relation_type"])
        if key in relation_keys or relation["relation_candidate_id"] in relation_ids:
            raise IntegrityError("M21-GOV-144 duplicate normalized relation")
        relation_keys.add(key)
        relation_ids.add(relation["relation_candidate_id"])
    tags = [
        _tag_candidate(mapping, candidates, canonical_tags, packet_sha)
        for mapping in tag_mappings
    ]
    tag_keys: set[tuple[str, str]] = set()
    tag_ids: set[str] = set()
    for tag in tags:
        key = (tag["source_candidate_id"], tag["canonical_tag"])
        if key in tag_keys or tag["tag_candidate_id"] in tag_ids:
            raise IntegrityError("M21-GOV-145 duplicate governed tag candidate")
        tag_keys.add(key)
        tag_ids.add(tag["tag_candidate_id"])
    relations.sort(key=lambda value: value["relation_candidate_id"])
    tags.sort(key=lambda value: value["tag_candidate_id"])
    packet = {
        "schema": "knowledge-engine-governed-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "foundation_sha": FOUNDATION_SHA,
        "extraction_packet_sha256": packet_sha,
        "identity": extraction_packet["identity"],
        "relation_ontology": {
            "schema_version": relation_ontology["schema_version"],
            "ontology_id": relation_ontology["ontology_id"],
            "version": relation_ontology["version"],
            "sha256": ontology_sha,
        },
        "tag_taxonomy": {
            "schema_version": tag_taxonomy["schema_version"],
            "taxonomy_id": tag_taxonomy["taxonomy_id"],
            "version": tag_taxonomy["version"],
            "sha256": taxonomy_sha,
        },
        "typed_relation_count": len(relations),
        "governed_tag_count": len(tags),
        "typed_relation_candidates": relations,
        "governed_tag_candidates": tags,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


__all__ = ["FOUNDATION_SHA", "build_governed_candidate_packet"]
