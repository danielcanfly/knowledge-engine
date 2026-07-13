from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
MAX_CANDIDATES = 1_000
MAX_SOURCE_CONCEPTS = 10_000
MAX_RESOLUTIONS = 1_000
MAX_CLUSTER_MEMBERS = 100
MAX_CONTRADICTIONS = 1_000
MAX_ALIASES = 32
MAX_TERMS = 32
MAX_TAGS = 32
MAX_SIGNALS = 20
MAX_SCOPE_FIELDS = 8
AUDIENCES = {"public", "internal", "restricted"}
ENDPOINT_KINDS = {"concept", "entity"}
OUTCOMES = {
    "exact_existing_match",
    "attach_alias_candidate",
    "probable_duplicate",
    "distinct_new_candidate",
    "ambiguous",
    "reject",
}
BLOCKING_OUTCOMES = {"probable_duplicate", "ambiguous", "reject"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
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
        raise IntegrityError(f"M21-RESOLVE-101 invalid {label}")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M21-RESOLVE-101 invalid {label}")
    if any(pattern.search(normalized) for pattern in SECRET_PATTERNS):
        raise IntegrityError(f"M21-RESOLVE-102 secret-like {label}")
    return normalized


def _norm(value: Any, label: str = "value", maximum: int = 300) -> str:
    return _text(value, label, maximum).casefold()


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX40 if size == 40 else HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityError(f"M21-RESOLVE-103 invalid {label}")
    return value


def _strings(values: Any, label: str, maximum: int) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > maximum:
        raise IntegrityError(f"M21-RESOLVE-104 invalid {label}")
    normalized = [_text(value, label) for value in values]
    folded = [_norm(value, label) for value in normalized]
    if len(folded) != len(set(folded)):
        raise IntegrityError(f"M21-RESOLVE-105 duplicate normalized {label}")
    return sorted(normalized, key=lambda item: (_norm(item, label), item))


def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _scan(child)
    elif isinstance(value, list):
        for child in value:
            _scan(child)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise IntegrityError("M21-RESOLVE-106 secret-like payload")


def _evidence(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not values or len(values) > 16:
        raise IntegrityError("M21-RESOLVE-107 missing or unbounded evidence")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    required = {
        "snapshot_id",
        "plan_sha256",
        "derivative_id",
        "start",
        "end",
        "excerpt_sha256",
    }
    for value in values:
        if not isinstance(value, dict) or set(value) != required:
            raise IntegrityError("M21-RESOLVE-108 malformed evidence span")
        snapshot_id = _text(value["snapshot_id"], "snapshot id", 128)
        plan_sha = _hex(value["plan_sha256"], 64, "plan digest")
        derivative_id = _text(value["derivative_id"], "derivative id", 128)
        start, end = value["start"], value["end"]
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
        ):
            raise IntegrityError("M21-RESOLVE-109 invalid evidence offsets")
        excerpt_sha = _hex(value["excerpt_sha256"], 64, "excerpt digest")
        key = (derivative_id, start, end, excerpt_sha)
        if key in seen:
            raise IntegrityError("M21-RESOLVE-110 duplicate evidence span")
        seen.add(key)
        output.append(
            {
                "snapshot_id": snapshot_id,
                "plan_sha256": plan_sha,
                "derivative_id": derivative_id,
                "start": start,
                "end": end,
                "excerpt_sha256": excerpt_sha,
            }
        )
    return sorted(output, key=lambda item: (item["derivative_id"], item["start"]))


def _validate_extraction(
    packet: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    if packet.get("schema") != "knowledge-engine-extraction-candidates/v1":
        raise IntegrityError("M21-RESOLVE-111 invalid M21.3 packet schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-RESOLVE-112 M21.3 digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
    ):
        raise IntegrityError("M21-RESOLVE-113 M21.3 authority drift")
    identity = packet.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "engine_sha",
        "source_sha",
        "foundation_sha",
    }:
        raise IntegrityError("M21-RESOLVE-114 invalid M21.3 identity")
    _hex(identity["engine_sha"], 40, "Engine SHA")
    if identity["source_sha"] != SOURCE_SHA or identity["foundation_sha"] != FOUNDATION_SHA:
        raise IntegrityError("M21-RESOLVE-115 M21.3 release identity mismatch")
    candidates = packet.get("candidates")
    if (
        not isinstance(candidates, list)
        or not 1 <= len(candidates) <= MAX_CANDIDATES
        or packet.get("candidate_count") != len(candidates)
    ):
        raise IntegrityError("M21-RESOLVE-116 M21.3 candidate coverage mismatch")
    output: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise IntegrityError("M21-RESOLVE-117 malformed M21.3 candidate")
        candidate_id = _text(candidate.get("candidate_id"), "candidate id", 128)
        if candidate_id in output:
            raise IntegrityError("M21-RESOLVE-118 duplicate candidate id")
        if (
            candidate.get("authority") != "candidate_only"
            or candidate.get("canonical_knowledge") is not False
            or candidate.get("production_authority") is not False
            or candidate.get("status") != "pending_review"
        ):
            raise IntegrityError("M21-RESOLVE-119 candidate authority drift")
        kind = candidate.get("kind")
        if kind not in {
            "concept",
            "entity",
            "alias",
            "definition",
            "claim",
            "term",
            "duplicate_hint",
            "relation_hint",
        }:
            raise IntegrityError("M21-RESOLVE-120 unsupported candidate kind")
        normalized = _norm(candidate.get("label"), "candidate label")
        if candidate.get("normalized_label") != normalized:
            raise IntegrityError("M21-RESOLVE-121 candidate normalization drift")
        confidence = candidate.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise IntegrityError("M21-RESOLVE-122 invalid candidate confidence")
        clean = dict(candidate)
        clean["confidence"] = round(float(confidence), 6)
        clean["evidence_spans"] = _evidence(candidate.get("evidence_spans"))
        output[candidate_id] = clean
    return packet_sha, output, identity


def _validate_governed(
    packet: dict[str, Any],
    extraction_sha: str,
    identity: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, set[str]]]:
    if packet.get("schema") != "knowledge-engine-governed-candidates/v1":
        raise IntegrityError("M21-RESOLVE-122 invalid M21.4 packet schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-RESOLVE-123 M21.4 digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
    ):
        raise IntegrityError("M21-RESOLVE-124 M21.4 authority drift")
    if (
        packet.get("extraction_packet_sha256") != extraction_sha
        or packet.get("identity") != identity
        or packet.get("foundation_sha") != FOUNDATION_SHA
    ):
        raise IntegrityError("M21-RESOLVE-125 cross-release M21.4 binding")
    ontology = packet.get("relation_ontology")
    taxonomy = packet.get("tag_taxonomy")
    if (
        not isinstance(ontology, dict)
        or ontology.get("schema_version") != "knowledge-os-relation-ontology/v0.1"
        or ontology.get("ontology_id") != "daniel-knowledge-os/relation-ontology"
        or ontology.get("version") != "0.1.0"
        or not isinstance(taxonomy, dict)
        or taxonomy.get("schema_version") != "knowledge-os-tag-taxonomy/v0.1"
        or taxonomy.get("taxonomy_id") != "daniel-knowledge-os/tag-taxonomy"
        or taxonomy.get("version") != "0.1.0"
    ):
        raise IntegrityError("M21-RESOLVE-126 governed registry identity drift")
    _hex(ontology.get("sha256"), 64, "ontology digest")
    _hex(taxonomy.get("sha256"), 64, "taxonomy digest")
    tags = packet.get("governed_tag_candidates")
    relations = packet.get("typed_relation_candidates")
    if (
        not isinstance(tags, list)
        or not isinstance(relations, list)
        or packet.get("governed_tag_count") != len(tags)
        or packet.get("typed_relation_count") != len(relations)
        or len(tags) > MAX_CANDIDATES
        or len(relations) > MAX_CANDIDATES
    ):
        raise IntegrityError("M21-RESOLVE-127 governed coverage mismatch")
    by_candidate: dict[str, set[str]] = defaultdict(set)
    seen_tags: set[str] = set()
    for tag in tags:
        if not isinstance(tag, dict):
            raise IntegrityError("M21-RESOLVE-127 malformed governed tag")
        tag_id = _text(tag.get("tag_candidate_id"), "tag candidate id", 128)
        if tag_id in seen_tags:
            raise IntegrityError("M21-RESOLVE-128 duplicate governed tag id")
        seen_tags.add(tag_id)
        if (
            tag.get("authority") != "candidate_only"
            or tag.get("canonical_knowledge") is not False
            or tag.get("production_authority") is not False
            or tag.get("status") != "pending_review"
        ):
            raise IntegrityError("M21-RESOLVE-129 governed tag authority drift")
        source_id = _text(tag.get("source_candidate_id"), "source candidate id", 128)
        if source_id not in candidates:
            raise IntegrityError("M21-RESOLVE-130 governed tag source missing")
        canonical_tag = _norm(tag.get("canonical_tag"), "canonical tag", 80)
        _evidence(tag.get("evidence_spans"))
        by_candidate[source_id].add(canonical_tag)
    seen_relations: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict):
            raise IntegrityError("M21-RESOLVE-130 malformed governed relation")
        relation_id = _text(relation.get("relation_candidate_id"), "relation id", 128)
        if relation_id in seen_relations:
            raise IntegrityError("M21-RESOLVE-131 duplicate governed relation id")
        seen_relations.add(relation_id)
        if (
            relation.get("authority") != "candidate_only"
            or relation.get("canonical_knowledge") is not False
            or relation.get("production_authority") is not False
            or relation.get("status") != "pending_review"
        ):
            raise IntegrityError("M21-RESOLVE-132 governed relation authority drift")
        source_id = _text(relation.get("source_candidate_id"), "relation source", 128)
        target_id = _text(relation.get("target_candidate_id"), "relation target", 128)
        if source_id not in candidates or target_id not in candidates:
            raise IntegrityError("M21-RESOLVE-134 governed relation endpoint missing")
        _evidence(relation.get("evidence_spans"))
    return packet_sha, by_candidate


def _validate_source_index(
    index: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, dict[str, set[str]]]]:
    if index.get("schema") != "knowledge-engine-source-resolution-index/v1":
        raise IntegrityError("M21-RESOLVE-133 invalid Source index schema")
    index_sha = _signed(index, "index_sha256", "M21-RESOLVE-134 Source index digest mismatch")
    if (
        index.get("source_sha") != SOURCE_SHA
        or index.get("foundation_sha") != FOUNDATION_SHA
        or index.get("authority") != "reviewed_source_index"
    ):
        raise IntegrityError("M21-RESOLVE-135 Source index identity drift")
    concepts = index.get("concepts")
    if (
        not isinstance(concepts, list)
        or len(concepts) > MAX_SOURCE_CONCEPTS
        or index.get("concept_count") != len(concepts)
    ):
        raise IntegrityError("M21-RESOLVE-136 Source index coverage mismatch")
    required = {
        "x_kos_id",
        "concept_path",
        "title",
        "normalized_title",
        "aliases",
        "bilingual_terms",
        "tags",
        "audience",
        "source_sha256",
    }
    output: list[dict[str, Any]] = []
    owners: dict[str, dict[str, set[str]]] = {
        "id": defaultdict(set),
        "path": defaultdict(set),
        "title": defaultdict(set),
        "alias": defaultdict(set),
        "term": defaultdict(set),
    }
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for raw in concepts:
        if not isinstance(raw, dict) or set(raw) != required:
            raise IntegrityError("M21-RESOLVE-137 Source concept shape drift")
        _scan(raw)
        x_kos_id = _text(raw["x_kos_id"], "x-kos-id", 160)
        concept_path = _text(raw["concept_path"], "concept path", 500)
        title = _text(raw["title"], "title")
        normalized_title = _norm(raw["normalized_title"], "normalized title")
        if normalized_title != _norm(title, "title"):
            raise IntegrityError("M21-RESOLVE-138 Source title normalization drift")
        normalized_id = _norm(x_kos_id, "x-kos-id", 160)
        normalized_path = _norm(concept_path, "concept path", 500)
        if normalized_id in seen_ids or normalized_path in seen_paths:
            raise IntegrityError("M21-RESOLVE-139 duplicate immutable Source identity")
        seen_ids.add(normalized_id)
        seen_paths.add(normalized_path)
        aliases = _strings(raw["aliases"], "alias", MAX_ALIASES)
        terms = _strings(raw["bilingual_terms"], "bilingual term", MAX_TERMS)
        tags = [_norm(value, "tag", 80) for value in _strings(raw["tags"], "tag", MAX_TAGS)]
        audience = raw["audience"]
        if audience not in AUDIENCES:
            raise IntegrityError("M21-RESOLVE-140 invalid Source audience")
        source_sha256 = _hex(raw["source_sha256"], 64, "Source file digest")
        concept = {
            "x_kos_id": x_kos_id,
            "concept_path": concept_path,
            "title": title,
            "normalized_title": normalized_title,
            "aliases": aliases,
            "bilingual_terms": terms,
            "tags": sorted(tags),
            "audience": audience,
            "source_sha256": source_sha256,
        }
        output.append(concept)
        owners["id"][_norm(x_kos_id, "x-kos-id", 160)].add(x_kos_id)
        owners["path"][_norm(concept_path, "concept path", 500)].add(x_kos_id)
        owners["title"][normalized_title].add(x_kos_id)
        for alias in aliases:
            owners["alias"][_norm(alias, "alias")].add(x_kos_id)
        for term in terms:
            owners["term"][_norm(term, "bilingual term")].add(x_kos_id)
    for name, values in owners["alias"].items():
        if len(values) > 1:
            raise IntegrityError("M21-RESOLVE-141 Source alias ownership collision")
        if owners["title"].get(name, set()) - values:
            raise IntegrityError("M21-RESOLVE-142 Source alias/title collision")
    output.sort(key=lambda item: item["x_kos_id"])
    return index_sha, output, owners


def _candidate_names(candidate: dict[str, Any]) -> list[str]:
    values = [candidate["label"]]
    values.extend(candidate.get("aliases", []))
    if candidate.get("kind") == "term":
        values.extend(
            value
            for value in (candidate.get("counterpart_label"),)
            if isinstance(value, str)
        )
    return sorted({_norm(value, "candidate name") for value in values})


def _audiences(value: Any, candidates: dict[str, dict[str, Any]]) -> tuple[dict[str, str], str]:
    if not isinstance(value, dict) or set(value) != set(candidates):
        raise IntegrityError("M21-RESOLVE-142 audience binding coverage mismatch")
    output: dict[str, str] = {}
    for candidate_id, audience in value.items():
        if audience not in AUDIENCES:
            raise IntegrityError("M21-RESOLVE-143 invalid candidate audience")
        output[candidate_id] = audience
    return output, _digest({key: output[key] for key in sorted(output)})


def _source_by_id(concepts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {concept["x_kos_id"]: concept for concept in concepts}


def _target_signals(
    candidate: dict[str, Any], owners: dict[str, dict[str, set[str]]]
) -> dict[str, set[str]]:
    signals: dict[str, set[str]] = defaultdict(set)
    label = _norm(candidate["label"], "candidate label")
    for signal, owner_type in (
        ("exact_x_kos_id", "id"),
        ("exact_concept_path", "path"),
        ("exact_normalized_title", "title"),
        ("exact_approved_alias", "alias"),
        ("exact_bilingual_term", "term"),
    ):
        for target in owners[owner_type].get(label, set()):
            signals[target].add(signal)
    for alias in candidate.get("aliases", []):
        alias_norm = _norm(alias, "candidate alias")
        for owner_type, signal in (
            ("title", "candidate_alias_matches_title"),
            ("alias", "exact_approved_alias"),
            ("term", "exact_bilingual_term"),
        ):
            for target in owners[owner_type].get(alias_norm, set()):
                signals[target].add(signal)
    return signals


def _combine_evidence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for candidate in candidates:
        for span in candidate["evidence_spans"]:
            key = (
                span["derivative_id"],
                span["start"],
                span["end"],
                span["excerpt_sha256"],
            )
            values[key] = span
    return [values[key] for key in sorted(values)]


def _record(
    *,
    extraction_sha: str,
    governed_sha: str,
    index_sha: str,
    candidate_ids: list[str],
    outcome: str,
    candidates: dict[str, dict[str, Any]],
    audience: str,
    existing: dict[str, Any] | None = None,
    strong_signals: list[str] | None = None,
    weak_signals: list[str] | None = None,
    cluster_id: str | None = None,
    proposed_alias: str | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise IntegrityError("M21-RESOLVE-144 invalid resolution outcome")
    candidate_ids = sorted(candidate_ids)
    if not 1 <= len(candidate_ids) <= MAX_CLUSTER_MEMBERS:
        raise IntegrityError("M21-RESOLVE-145 invalid resolution cluster size")
    strong = sorted(set(strong_signals or []))
    weak = sorted(set(weak_signals or []))
    if len(strong) > MAX_SIGNALS or len(weak) > MAX_SIGNALS:
        raise IntegrityError("M21-RESOLVE-146 signal bound exceeded")
    evidence = _combine_evidence([candidates[item] for item in candidate_ids])
    confidence = min(float(candidates[item].get("confidence", 0.0)) for item in candidate_ids)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise IntegrityError("M21-RESOLVE-147 invalid candidate confidence")
    record: dict[str, Any] = {
        "candidate_ids": candidate_ids,
        "outcome": outcome,
        "existing_x_kos_id": existing["x_kos_id"] if existing else None,
        "existing_concept_path": existing["concept_path"] if existing else None,
        "strong_signals": strong,
        "weak_signals": weak,
        "evidence_spans": evidence,
        "audience": audience,
        "confidence": round(confidence, 6),
        "status": "pending_review",
        "blocks_packaging": outcome in BLOCKING_OUTCOMES,
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    if cluster_id is not None:
        record["cluster_id"] = cluster_id
    if proposed_alias is not None:
        record["proposed_alias"] = proposed_alias
        record["ownership_unique"] = outcome == "attach_alias_candidate"
    identity = {
        "schema": "knowledge-engine-resolution-candidates/v1",
        "extraction": extraction_sha,
        "governed": governed_sha,
        "source_index": index_sha,
        "candidate_ids": candidate_ids,
        "outcome": outcome,
        "existing_x_kos_id": record["existing_x_kos_id"],
        "strong_signals": strong,
        "weak_signals": weak,
        "cluster_id": cluster_id,
        "proposed_alias": proposed_alias,
    }
    record["resolution_id"] = f"resolcand_{_digest(identity)[:32]}"
    return record


class _UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        first, second = sorted((root_left, root_right))
        self.parent[second] = first


def _clusters(
    candidates: dict[str, dict[str, Any]], audiences: dict[str, str]
) -> tuple[list[list[str]], dict[str, list[str]]]:
    endpoint_ids = sorted(
        candidate_id
        for candidate_id, candidate in candidates.items()
        if candidate["kind"] in ENDPOINT_KINDS
    )
    union = _UnionFind(endpoint_ids)
    by_label: dict[str, list[str]] = defaultdict(list)
    for candidate_id in endpoint_ids:
        by_label[_norm(candidates[candidate_id]["label"], "candidate label")].append(candidate_id)
    cross_audience: dict[str, list[str]] = {}
    for label, members in by_label.items():
        member_audiences = {audiences[item] for item in members}
        if len(member_audiences) > 1:
            cross_audience[label] = sorted(members)
            continue
        for member in members[1:]:
            union.union(members[0], member)
    by_names: dict[str, list[str]] = defaultdict(list)
    for candidate_id in endpoint_ids:
        for name in _candidate_names(candidates[candidate_id]):
            by_names[name].append(candidate_id)
    for hint in candidates.values():
        if hint["kind"] != "duplicate_hint":
            continue
        left = by_names.get(_norm(hint["label"], "duplicate label"), [])
        right = by_names.get(_norm(hint.get("target_label"), "duplicate target"), [])
        for left_id in left:
            for right_id in right:
                if audiences[left_id] == audiences[right_id]:
                    union.union(left_id, right_id)
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate_id in endpoint_ids:
        groups[union.find(candidate_id)].append(candidate_id)
    ordered = sorted(
        (sorted(group) for group in groups.values()), key=lambda group: group[0]
    )
    return ordered, cross_audience


def _cluster_id(extraction_sha: str, members: list[str]) -> str:
    identity = {"extraction_packet_sha256": extraction_sha, "members": sorted(members)}
    return f"cluster_{_digest(identity)[:32]}"


def _scope(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > MAX_SCOPE_FIELDS:
        raise IntegrityError("M21-RESOLVE-148 invalid contradiction scope")
    output = {str(key): _text(child, f"scope {key}") for key, child in value.items()}
    return {key: output[key] for key in sorted(output)}


def _claim_assertions(
    values: Any, candidates: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    if values is None:
        return [], _digest([])
    if not isinstance(values, list) or len(values) > MAX_CANDIDATES:
        raise IntegrityError("M21-RESOLVE-149 invalid claim assertions")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "candidate_id",
            "predicate",
            "scope",
            "polarity",
            "value",
        }:
            raise IntegrityError("M21-RESOLVE-150 malformed claim assertion")
        candidate_id = _text(value["candidate_id"], "claim candidate id", 128)
        candidate = candidates.get(candidate_id)
        if candidate is None or candidate["kind"] != "claim" or candidate_id in seen:
            raise IntegrityError("M21-RESOLVE-151 invalid claim candidate binding")
        seen.add(candidate_id)
        polarity = value["polarity"]
        if polarity not in {"positive", "negative"}:
            raise IntegrityError("M21-RESOLVE-152 invalid claim polarity")
        normalized_value = None
        if value["value"] is not None:
            normalized_value = _norm(value["value"], "claim value", 1_000)
        output.append(
            {
                "candidate_id": candidate_id,
                "predicate": _norm(value["predicate"], "predicate", 120),
                "scope": _scope(value["scope"]),
                "polarity": polarity,
                "value": normalized_value,
            }
        )
    output.sort(key=lambda item: item["candidate_id"])
    return output, _digest(output)


def _resolve_subject(
    label: str,
    resolution_by_name: dict[str, set[str]],
    owners: dict[str, dict[str, set[str]]],
) -> str | None:
    normalized = _norm(label, "claim subject")
    targets = set(resolution_by_name.get(normalized, set()))
    for owner_type in ("title", "alias", "term", "id", "path"):
        targets.update(owners[owner_type].get(normalized, set()))
    if len(targets) == 1:
        return next(iter(targets))
    return None


def _contradictions(
    assertions: list[dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
    resolution_by_name: dict[str, set[str]],
    owners: dict[str, dict[str, set[str]]],
    extraction_sha: str,
    governed_sha: str,
    index_sha: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for assertion in assertions:
        candidate = candidates[assertion["candidate_id"]]
        subject = _resolve_subject(candidate.get("subject_label"), resolution_by_name, owners)
        if subject is None:
            continue
        scope_sha = _digest(assertion["scope"])
        groups[(subject, assertion["predicate"], scope_sha)].append(assertion)
    output: list[dict[str, Any]] = []
    for (subject, predicate, _scope_sha), group in sorted(groups.items()):
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                opposite = left["polarity"] != right["polarity"]
                incompatible_value = (
                    left["value"] is not None
                    and right["value"] is not None
                    and left["value"] != right["value"]
                )
                if not opposite and not incompatible_value:
                    continue
                left_id, right_id = sorted((left["candidate_id"], right["candidate_id"]))
                incompatibility = "opposite_polarity" if opposite else "incompatible_value"
                record = {
                    "outcome": "contradiction_candidate",
                    "subject_x_kos_id": subject,
                    "predicate": predicate,
                    "left_candidate_id": left_id,
                    "right_candidate_id": right_id,
                    "overlapping_scope": left["scope"],
                    "incompatibility": incompatibility,
                    "left_evidence_spans": candidates[left_id]["evidence_spans"],
                    "right_evidence_spans": candidates[right_id]["evidence_spans"],
                    "status": "pending_review",
                    "blocks_packaging": True,
                    "authority": "candidate_only",
                    "canonical_knowledge": False,
                    "production_authority": False,
                }
                identity = {
                    "schema": "knowledge-engine-resolution-candidates/v1",
                    "extraction": extraction_sha,
                    "governed": governed_sha,
                    "source_index": index_sha,
                    "subject": subject,
                    "predicate": predicate,
                    "scope": left["scope"],
                    "left": left_id,
                    "right": right_id,
                    "incompatibility": incompatibility,
                }
                record["contradiction_id"] = f"contracand_{_digest(identity)[:32]}"
                output.append(record)
                if len(output) > MAX_CONTRADICTIONS:
                    raise IntegrityError("M21-RESOLVE-153 contradiction bound exceeded")
    return sorted(output, key=lambda item: item["contradiction_id"])


def build_resolution_candidate_packet(
    extraction_packet: dict[str, Any],
    governed_packet: dict[str, Any],
    source_index: dict[str, Any],
    *,
    candidate_audiences: dict[str, str],
    claim_assertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _scan(candidate_audiences)
    _scan(claim_assertions or [])
    extraction_sha, candidates, identity = _validate_extraction(extraction_packet)
    governed_sha, governed_tags = _validate_governed(
        governed_packet, extraction_sha, identity, candidates
    )
    index_sha, concepts, owners = _validate_source_index(source_index)
    audiences, audience_sha = _audiences(candidate_audiences, candidates)
    assertions, assertions_sha = _claim_assertions(claim_assertions, candidates)
    source_by_id = _source_by_id(concepts)
    clusters, cross_audience = _clusters(candidates, audiences)
    resolutions: list[dict[str, Any]] = []
    consumed: set[str] = set()
    resolution_by_name: dict[str, set[str]] = defaultdict(set)

    for members in cross_audience.values():
        member_candidates = [candidates[item] for item in members]
        resolutions.append(
            _record(
                extraction_sha=extraction_sha,
                governed_sha=governed_sha,
                index_sha=index_sha,
                candidate_ids=members,
                outcome="reject",
                candidates=candidates,
                audience="mixed",
                weak_signals=["cross_audience_candidate_collision"],
                cluster_id=_cluster_id(extraction_sha, members),
            )
        )
        consumed.update(candidate["candidate_id"] for candidate in member_candidates)

    for members in clusters:
        members = [item for item in members if item not in consumed]
        if not members:
            continue
        candidate_group = [candidates[item] for item in members]
        audience = audiences[members[0]]
        targets: dict[str, set[str]] = defaultdict(set)
        for candidate in candidate_group:
            for target, signals in _target_signals(candidate, owners).items():
                targets[target].update(signals)
        if len(targets) > 1:
            resolutions.append(
                _record(
                    extraction_sha=extraction_sha,
                    governed_sha=governed_sha,
                    index_sha=index_sha,
                    candidate_ids=members,
                    outcome="ambiguous",
                    candidates=candidates,
                    audience=audience,
                    strong_signals=sorted(
                        {signal for signals in targets.values() for signal in signals}
                    ),
                    cluster_id=(
                        _cluster_id(extraction_sha, members) if len(members) > 1 else None
                    ),
                )
            )
            consumed.update(members)
            continue
        if len(targets) == 1:
            target_id = next(iter(targets))
            target = source_by_id[target_id]
            outcome = "exact_existing_match" if target["audience"] == audience else "reject"
            weak = [] if outcome == "exact_existing_match" else ["audience_acl_mismatch"]
            resolutions.append(
                _record(
                    extraction_sha=extraction_sha,
                    governed_sha=governed_sha,
                    index_sha=index_sha,
                    candidate_ids=members,
                    outcome=outcome,
                    candidates=candidates,
                    audience=audience,
                    existing=target,
                    strong_signals=sorted(targets[target_id]),
                    weak_signals=weak,
                    cluster_id=(
                        _cluster_id(extraction_sha, members) if len(members) > 1 else None
                    ),
                )
            )
            if outcome == "exact_existing_match":
                for candidate in candidate_group:
                    for name in _candidate_names(candidate):
                        resolution_by_name[name].add(target_id)
            consumed.update(members)
            continue
        tag_targets: dict[str, int] = defaultdict(int)
        group_tags = set().union(*(governed_tags.get(item, set()) for item in members))
        if group_tags:
            for concept in concepts:
                overlap = group_tags & set(concept["tags"])
                if overlap:
                    tag_targets[concept["x_kos_id"]] = len(overlap)
        if len(members) > 1:
            resolutions.append(
                _record(
                    extraction_sha=extraction_sha,
                    governed_sha=governed_sha,
                    index_sha=index_sha,
                    candidate_ids=members,
                    outcome="probable_duplicate",
                    candidates=candidates,
                    audience=audience,
                    weak_signals=["within_batch_exact_label_or_explicit_hint"],
                    cluster_id=_cluster_id(extraction_sha, members),
                )
            )
        elif tag_targets:
            best_score = max(tag_targets.values())
            best = sorted(target for target, score in tag_targets.items() if score == best_score)
            existing = source_by_id[best[0]] if len(best) == 1 else None
            resolutions.append(
                _record(
                    extraction_sha=extraction_sha,
                    governed_sha=governed_sha,
                    index_sha=index_sha,
                    candidate_ids=members,
                    outcome="probable_duplicate",
                    candidates=candidates,
                    audience=audience,
                    existing=existing,
                    weak_signals=["shared_governed_tags_only"],
                )
            )
        else:
            resolutions.append(
                _record(
                    extraction_sha=extraction_sha,
                    governed_sha=governed_sha,
                    index_sha=index_sha,
                    candidate_ids=members,
                    outcome="distinct_new_candidate",
                    candidates=candidates,
                    audience=audience,
                )
            )
        consumed.update(members)

    source_names: dict[str, set[str]] = defaultdict(set)
    for owner_type in ("title", "alias", "term", "id", "path"):
        for name, values in owners[owner_type].items():
            source_names[name].update(values)
    alias_candidates = sorted(
        (
            candidate
            for candidate in candidates.values()
            if candidate["kind"] == "alias"
        ),
        key=lambda item: item["candidate_id"],
    )
    alias_labels = {_norm(candidate["label"], "alias label") for candidate in alias_candidates}
    for alias in alias_candidates:
        alias_id = alias["candidate_id"]
        audience = audiences[alias_id]
        proposed = _text(alias["label"], "proposed alias")
        target_name = _norm(alias.get("target_label"), "alias target")
        if target_name in alias_labels:
            outcome, target = "reject", None
            strong: list[str] = []
            weak = ["alias_chain_forbidden"]
        else:
            targets = set(source_names.get(target_name, set()))
            targets.update(resolution_by_name.get(target_name, set()))
            proposed_norm = _norm(proposed, "proposed alias")
            collisions = set(source_names.get(proposed_norm, set()))
            if len(targets) != 1 or collisions - targets:
                outcome, target = "ambiguous", None
                strong = []
                weak = ["alias_target_or_ownership_ambiguous"]
            else:
                target_id = next(iter(targets))
                target = source_by_id[target_id]
                if target["audience"] != audience:
                    outcome = "reject"
                    weak = ["audience_acl_mismatch"]
                    strong = []
                elif target_id in collisions:
                    outcome = "exact_existing_match"
                    strong = ["alias_already_approved"]
                    weak = []
                else:
                    outcome = "attach_alias_candidate"
                    strong = ["unique_alias_target"]
                    weak = []
        resolutions.append(
            _record(
                extraction_sha=extraction_sha,
                governed_sha=governed_sha,
                index_sha=index_sha,
                candidate_ids=[alias_id],
                outcome=outcome,
                candidates=candidates,
                audience=audience,
                existing=target,
                strong_signals=strong,
                weak_signals=weak,
                proposed_alias=proposed,
            )
        )
        consumed.add(alias_id)

    if len(resolutions) > MAX_RESOLUTIONS:
        raise IntegrityError("M21-RESOLVE-154 resolution bound exceeded")
    resolutions.sort(key=lambda item: item["resolution_id"])
    contradictions = _contradictions(
        assertions,
        candidates,
        resolution_by_name,
        owners,
        extraction_sha,
        governed_sha,
        index_sha,
    )
    packet = {
        "schema": "knowledge-engine-resolution-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "identity": identity,
        "extraction_packet_sha256": extraction_sha,
        "governed_packet_sha256": governed_sha,
        "source_index_sha256": index_sha,
        "candidate_audience_sha256": audience_sha,
        "claim_assertions_sha256": assertions_sha,
        "resolution_count": len(resolutions),
        "contradiction_count": len(contradictions),
        "packaging_blocked": any(item["blocks_packaging"] for item in resolutions)
        or bool(contradictions),
        "resolutions": resolutions,
        "contradictions": contradictions,
    }
    packet["packet_sha256"] = _digest(packet)
    return packet


__all__ = [
    "FOUNDATION_SHA",
    "SOURCE_SHA",
    "build_resolution_candidate_packet",
]
