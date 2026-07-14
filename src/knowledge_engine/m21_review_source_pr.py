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
MAX_ITEMS = 1_000
MAX_PATHS = 8
MAX_TEXT = 20_000
MAX_GOVERNED_REFS = 64
AUDIENCES = {"public", "internal", "restricted"}
ALLOWED_ACTIONS = {
    "create_concept",
    "update_concept",
    "attach_alias",
    "add_claim",
    "add_definition",
    "add_term",
    "add_tag",
    "add_relationship",
}
ELIGIBLE_OUTCOMES = {
    "exact_existing_match",
    "attach_alias_candidate",
    "distinct_new_candidate",
}
BLOCKING_OUTCOMES = {"probable_duplicate", "ambiguous", "reject"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH = re.compile(r"^[a-zA-Z0-9._/-]+$")
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
        raise IntegrityError(f"M21-REVIEW-101 invalid {label}")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized or len(normalized) > maximum:
        raise IntegrityError(f"M21-REVIEW-101 invalid {label}")
    if any(pattern.search(normalized) for pattern in SECRET_PATTERNS):
        raise IntegrityError(f"M21-REVIEW-102 secret-like {label}")
    return normalized


def _hex(value: Any, size: int, label: str) -> str:
    pattern = HEX40 if size == 40 else HEX64
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityError(f"M21-REVIEW-103 invalid {label}")
    return value


def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _scan(child)
    elif isinstance(value, list):
        for child in value:
            _scan(child)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise IntegrityError("M21-REVIEW-104 secret-like payload")


def _evidence(values: Any) -> list[dict[str, Any]]:
    required = {
        "snapshot_id",
        "plan_sha256",
        "derivative_id",
        "start",
        "end",
        "excerpt_sha256",
    }
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise IntegrityError("M21-REVIEW-105 missing or unbounded evidence")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, str]] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != required:
            raise IntegrityError("M21-REVIEW-106 malformed evidence span")
        start, end = value["start"], value["end"]
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
        ):
            raise IntegrityError("M21-REVIEW-107 invalid evidence offsets")
        item = {
            "snapshot_id": _text(value["snapshot_id"], "snapshot id", 128),
            "plan_sha256": _hex(value["plan_sha256"], 64, "plan digest"),
            "derivative_id": _text(value["derivative_id"], "derivative id", 128),
            "start": start,
            "end": end,
            "excerpt_sha256": _hex(value["excerpt_sha256"], 64, "excerpt digest"),
        }
        key = (
            item["derivative_id"],
            item["start"],
            item["end"],
            item["excerpt_sha256"],
        )
        if key in seen:
            raise IntegrityError("M21-REVIEW-108 duplicate evidence span")
        seen.add(key)
        output.append(item)
    return sorted(output, key=lambda item: (item["derivative_id"], item["start"]))


def _validate_extraction(
    packet: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    if packet.get("schema") != "knowledge-engine-extraction-candidates/v1":
        raise IntegrityError("M21-REVIEW-109 invalid M21.3 schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-REVIEW-110 M21.3 digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
    ):
        raise IntegrityError("M21-REVIEW-111 M21.3 authority drift")
    identity = packet.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "engine_sha",
        "source_sha",
        "foundation_sha",
    }:
        raise IntegrityError("M21-REVIEW-112 invalid M21.3 identity")
    _hex(identity["engine_sha"], 40, "Engine SHA")
    if identity["source_sha"] != SOURCE_SHA or identity["foundation_sha"] != FOUNDATION_SHA:
        raise IntegrityError("M21-REVIEW-113 M21.3 identity mismatch")
    values = packet.get("candidates")
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= MAX_CANDIDATES
        or packet.get("candidate_count") != len(values)
    ):
        raise IntegrityError("M21-REVIEW-114 M21.3 coverage mismatch")
    candidates: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise IntegrityError("M21-REVIEW-115 malformed candidate")
        candidate_id = _text(value.get("candidate_id"), "candidate id", 128)
        if candidate_id in candidates:
            raise IntegrityError("M21-REVIEW-116 duplicate candidate id")
        if (
            value.get("status") != "pending_review"
            or value.get("authority") != "candidate_only"
            or value.get("canonical_knowledge") is not False
            or value.get("production_authority") is not False
        ):
            raise IntegrityError("M21-REVIEW-117 candidate authority drift")
        confidence = value.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise IntegrityError("M21-REVIEW-118 invalid candidate confidence")
        clean = dict(value)
        clean["evidence_spans"] = _evidence(value.get("evidence_spans"))
        clean["confidence"] = round(float(confidence), 6)
        candidates[candidate_id] = clean
    return packet_sha, candidates, identity


def _validate_governed(
    packet: dict[str, Any],
    extraction_sha: str,
    identity: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if packet.get("schema") != "knowledge-engine-governed-candidates/v1":
        raise IntegrityError("M21-REVIEW-119 invalid M21.4 schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-REVIEW-120 M21.4 digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
        or packet.get("extraction_packet_sha256") != extraction_sha
        or packet.get("identity") != identity
        or packet.get("foundation_sha") != FOUNDATION_SHA
    ):
        raise IntegrityError("M21-REVIEW-121 M21.4 binding or authority drift")
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
        raise IntegrityError("M21-REVIEW-122 governed coverage mismatch")
    tag_map: dict[str, dict[str, Any]] = {}
    for tag in tags:
        if not isinstance(tag, dict):
            raise IntegrityError("M21-REVIEW-123 malformed governed tag")
        tag_id = _text(tag.get("tag_candidate_id"), "tag id", 128)
        source_id = _text(tag.get("source_candidate_id"), "tag source", 128)
        if tag_id in tag_map or source_id not in candidates:
            raise IntegrityError("M21-REVIEW-124 invalid governed tag binding")
        if (
            tag.get("status") != "pending_review"
            or tag.get("authority") != "candidate_only"
            or tag.get("canonical_knowledge") is not False
            or tag.get("production_authority") is not False
        ):
            raise IntegrityError("M21-REVIEW-125 governed tag authority drift")
        _evidence(tag.get("evidence_spans"))
        tag_map[tag_id] = tag
    relation_map: dict[str, dict[str, Any]] = {}
    for relation in relations:
        if not isinstance(relation, dict):
            raise IntegrityError("M21-REVIEW-126 malformed governed relation")
        relation_id = _text(relation.get("relation_candidate_id"), "relation id", 128)
        source_id = _text(relation.get("source_candidate_id"), "relation source", 128)
        target_id = _text(relation.get("target_candidate_id"), "relation target", 128)
        if (
            relation_id in relation_map
            or source_id not in candidates
            or target_id not in candidates
        ):
            raise IntegrityError("M21-REVIEW-127 invalid governed relation binding")
        if (
            relation.get("status") != "pending_review"
            or relation.get("authority") != "candidate_only"
            or relation.get("canonical_knowledge") is not False
            or relation.get("production_authority") is not False
        ):
            raise IntegrityError("M21-REVIEW-128 governed relation authority drift")
        _evidence(relation.get("evidence_spans"))
        relation_map[relation_id] = relation
    return packet_sha, tag_map, relation_map


def _validate_resolution(
    packet: dict[str, Any],
    extraction_sha: str,
    governed_sha: str,
    identity: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    if packet.get("schema") != "knowledge-engine-resolution-candidates/v1":
        raise IntegrityError("M21-REVIEW-129 invalid M21.5 schema")
    packet_sha = _signed(packet, "packet_sha256", "M21-REVIEW-130 M21.5 digest mismatch")
    if (
        packet.get("authority") != "candidate_only"
        or packet.get("canonical_knowledge") is not False
        or packet.get("production_authority") is not False
        or packet.get("review_required") is not True
        or packet.get("source_sha") != SOURCE_SHA
        or packet.get("foundation_sha") != FOUNDATION_SHA
        or packet.get("identity") != identity
        or packet.get("extraction_packet_sha256") != extraction_sha
        or packet.get("governed_packet_sha256") != governed_sha
    ):
        raise IntegrityError("M21-REVIEW-131 M21.5 binding or authority drift")
    values = packet.get("resolutions")
    contradictions = packet.get("contradictions")
    if (
        not isinstance(values, list)
        or not isinstance(contradictions, list)
        or packet.get("resolution_count") != len(values)
        or packet.get("contradiction_count") != len(contradictions)
        or len(values) > MAX_ITEMS
    ):
        raise IntegrityError("M21-REVIEW-132 M21.5 coverage mismatch")
    if packet.get("packaging_blocked") is not False or contradictions:
        raise IntegrityError("M21-REVIEW-133 M21.5 packaging blocked")
    resolutions: dict[str, dict[str, Any]] = {}
    covered_candidates: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise IntegrityError("M21-REVIEW-134 malformed resolution")
        resolution_id = _text(value.get("resolution_id"), "resolution id", 128)
        candidate_ids = value.get("candidate_ids")
        if (
            resolution_id in resolutions
            or not isinstance(candidate_ids, list)
            or not candidate_ids
            or candidate_ids != sorted(candidate_ids)
            or any(item not in candidates for item in candidate_ids)
        ):
            raise IntegrityError("M21-REVIEW-135 invalid resolution binding")
        if set(candidate_ids) & covered_candidates:
            raise IntegrityError("M21-REVIEW-136 candidate covered by multiple resolutions")
        covered_candidates.update(candidate_ids)
        outcome = value.get("outcome")
        if outcome in BLOCKING_OUTCOMES or outcome not in ELIGIBLE_OUTCOMES:
            raise IntegrityError("M21-REVIEW-137 ineligible resolution outcome")
        if (
            value.get("blocks_packaging") is not False
            or value.get("status") != "pending_review"
            or value.get("authority") != "candidate_only"
            or value.get("canonical_knowledge") is not False
            or value.get("production_authority") is not False
            or value.get("audience") not in AUDIENCES
        ):
            raise IntegrityError("M21-REVIEW-138 resolution authority or ACL drift")
        _evidence(value.get("evidence_spans"))
        resolutions[resolution_id] = value
    return packet_sha, resolutions


def _paths(values: Any) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_PATHS:
        raise IntegrityError("M21-REVIEW-139 invalid Source path count")
    output: list[str] = []
    for value in values:
        path = _text(value, "Source path", 240)
        if (
            path.startswith("/")
            or ".." in path.split("/")
            or "//" in path
            or SAFE_PATH.fullmatch(path) is None
            or not path.endswith((".md", ".json"))
            or not path.startswith(("bundle/concepts/", "provenance/", "registry/", "reviews/"))
        ):
            raise IntegrityError("M21-REVIEW-140 unsafe Source path")
        output.append(path)
    if len(output) != len(set(output)):
        raise IntegrityError("M21-REVIEW-141 duplicate Source path in item")
    return sorted(output)


def _analysis(value: Any) -> dict[str, Any]:
    required = {"duplicate", "ambiguity", "contradiction", "acl_conflict", "notes"}
    if not isinstance(value, dict) or set(value) != required:
        raise IntegrityError("M21-REVIEW-142 malformed conflict analysis")
    for key in ("duplicate", "ambiguity", "contradiction", "acl_conflict"):
        if value[key] is not False:
            raise IntegrityError("M21-REVIEW-143 unresolved conflict blocks packaging")
    notes = value["notes"]
    if not isinstance(notes, list) or len(notes) > 16:
        raise IntegrityError("M21-REVIEW-144 invalid conflict notes")
    return {
        **{key: False for key in required - {"notes"}},
        "notes": sorted(_text(item, "analysis note", 300) for item in notes),
    }


def _governed_refs(
    ids: Any,
    source_candidates: set[str],
    values: dict[str, dict[str, Any]],
    kind: str,
) -> list[dict[str, Any]]:
    if not isinstance(ids, list) or len(ids) > MAX_GOVERNED_REFS or len(ids) != len(set(ids)):
        raise IntegrityError(f"M21-REVIEW-145 invalid {kind} references")
    output: list[dict[str, Any]] = []
    for item_id in sorted(ids):
        item = values.get(item_id)
        if item is None:
            raise IntegrityError(f"M21-REVIEW-146 unknown {kind} reference")
        if kind == "tag":
            linked = {item["source_candidate_id"]}
        else:
            linked = {item["source_candidate_id"], item["target_candidate_id"]}
        if not linked & source_candidates:
            raise IntegrityError(f"M21-REVIEW-147 unrelated {kind} reference")
        output.append(item)
    return output


def _validate_action(
    action: str,
    resolution: dict[str, Any],
    paths: list[str],
    proposed_body: str | None,
    proposed_change: str | None,
) -> None:
    outcome = resolution["outcome"]
    existing_path = resolution.get("existing_concept_path")
    if action == "create_concept":
        if outcome != "distinct_new_candidate" or existing_path is not None:
            raise IntegrityError("M21-REVIEW-148 create action target drift")
        if not any(path.startswith("bundle/concepts/") and path.endswith(".md") for path in paths):
            raise IntegrityError("M21-REVIEW-149 create concept path missing")
        if proposed_body is None:
            raise IntegrityError("M21-REVIEW-150 proposed concept body missing")
    elif action == "attach_alias":
        if outcome != "attach_alias_candidate" or not isinstance(existing_path, str):
            raise IntegrityError("M21-REVIEW-151 alias action target drift")
        if paths != [existing_path]:
            raise IntegrityError("M21-REVIEW-152 alias path must equal existing concept")
        if proposed_change is None:
            raise IntegrityError("M21-REVIEW-153 alias change missing")
    else:
        if outcome != "exact_existing_match" or not isinstance(existing_path, str):
            raise IntegrityError("M21-REVIEW-154 update action target drift")
        if existing_path not in paths:
            raise IntegrityError("M21-REVIEW-155 exact existing path missing")
        if action == "update_concept" and proposed_body is None:
            raise IntegrityError("M21-REVIEW-156 updated concept body missing")
        if action != "update_concept" and proposed_change is None:
            raise IntegrityError("M21-REVIEW-157 proposed change missing")


def build_review_source_pr_preparation(
    extraction_packet: dict[str, Any],
    governed_packet: dict[str, Any],
    resolution_packet: dict[str, Any],
    review_items: list[dict[str, Any]],
) -> dict[str, Any]:
    _scan(review_items)
    extraction_sha, candidates, identity = _validate_extraction(extraction_packet)
    governed_sha, tags, relations = _validate_governed(
        governed_packet, extraction_sha, identity, candidates
    )
    resolution_sha, resolutions = _validate_resolution(
        resolution_packet, extraction_sha, governed_sha, identity, candidates
    )
    if not isinstance(review_items, list) or not 1 <= len(review_items) <= MAX_ITEMS:
        raise IntegrityError("M21-REVIEW-158 invalid review item count")
    seen_resolutions: set[str] = set()
    path_owner: dict[str, str] = {}
    packets: list[dict[str, Any]] = []
    required = {
        "resolution_id",
        "action",
        "candidate_ids",
        "target_paths",
        "proposed_concept_body",
        "proposed_change",
        "governed_tag_candidate_ids",
        "typed_relation_candidate_ids",
        "existing_comparison",
        "duplicate_conflict_analysis",
        "audience",
        "confidence",
    }
    for item in review_items:
        if not isinstance(item, dict) or set(item) != required:
            raise IntegrityError("M21-REVIEW-159 malformed review item")
        resolution_id = _text(item["resolution_id"], "resolution id", 128)
        resolution = resolutions.get(resolution_id)
        if resolution is None or resolution_id in seen_resolutions:
            raise IntegrityError("M21-REVIEW-160 missing or duplicate resolution item")
        seen_resolutions.add(resolution_id)
        candidate_ids = item["candidate_ids"]
        if candidate_ids != resolution["candidate_ids"]:
            raise IntegrityError("M21-REVIEW-161 candidate coverage mismatch")
        candidate_set = set(candidate_ids)
        action = item["action"]
        if action not in ALLOWED_ACTIONS:
            raise IntegrityError("M21-REVIEW-162 unsupported review action")
        target_paths = _paths(item["target_paths"])
        for path in target_paths:
            owner = path_owner.setdefault(path, resolution_id)
            if owner != resolution_id:
                raise IntegrityError("M21-REVIEW-163 cross-item Source path collision")
        body = item["proposed_concept_body"]
        change = item["proposed_change"]
        if body is not None:
            body = _text(body, "proposed concept body", MAX_TEXT)
        if change is not None:
            change = _text(change, "proposed change", MAX_TEXT)
        _validate_action(action, resolution, target_paths, body, change)
        audience = item["audience"]
        if audience != resolution["audience"] or audience not in AUDIENCES:
            raise IntegrityError("M21-REVIEW-164 audience mismatch")
        confidence = item["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= float(resolution["confidence"])
        ):
            raise IntegrityError("M21-REVIEW-165 confidence escalation")
        comparison = item["existing_comparison"]
        if not isinstance(comparison, dict) or set(comparison) != {
            "x_kos_id",
            "concept_path",
            "comparison_summary",
        }:
            raise IntegrityError("M21-REVIEW-166 malformed existing comparison")
        if (
            comparison["x_kos_id"] != resolution.get("existing_x_kos_id")
            or comparison["concept_path"] != resolution.get("existing_concept_path")
        ):
            raise IntegrityError("M21-REVIEW-167 existing comparison identity mismatch")
        comparison_summary = _text(
            comparison["comparison_summary"], "comparison summary", 2_000
        )
        tag_values = _governed_refs(
            item["governed_tag_candidate_ids"], candidate_set, tags, "tag"
        )
        relation_values = _governed_refs(
            item["typed_relation_candidate_ids"], candidate_set, relations, "relation"
        )
        packet: dict[str, Any] = {
            "schema": "knowledge-engine-human-review-item/v1",
            "resolution_id": resolution_id,
            "action": action,
            "candidate_ids": candidate_ids,
            "target_paths": target_paths,
            "proposed_concept_body": body,
            "proposed_change": change,
            "evidence_spans": _evidence(resolution["evidence_spans"]),
            "governed_tags": tag_values,
            "typed_relationships": relation_values,
            "existing_comparison": {
                **comparison,
                "comparison_summary": comparison_summary,
            },
            "duplicate_conflict_analysis": _analysis(item["duplicate_conflict_analysis"]),
            "audience": audience,
            "confidence": round(float(confidence), 6),
            "status": "pending_human_review",
            "approval_granted": False,
            "source_write_permitted": False,
            "github_pr_creation_permitted": False,
            "authority": "review_preparation_only",
            "canonical_knowledge": False,
            "production_authority": False,
        }
        identity_payload = {
            "extraction_packet_sha256": extraction_sha,
            "governed_packet_sha256": governed_sha,
            "resolution_packet_sha256": resolution_sha,
            "packet": packet,
        }
        packet["review_packet_id"] = f"reviewpkt_{_digest(identity_payload)[:32]}"
        packet["packet_sha256"] = _digest(packet)
        packets.append(packet)
    if seen_resolutions != set(resolutions):
        raise IntegrityError("M21-REVIEW-168 incomplete resolution review coverage")
    packets.sort(key=lambda item: item["review_packet_id"])
    review_bundle: dict[str, Any] = {
        "schema": "knowledge-engine-human-review-packets/v1",
        "authority": "review_preparation_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "approval_granted": False,
        "source_write_permitted": False,
        "github_pr_creation_permitted": False,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "identity": identity,
        "extraction_packet_sha256": extraction_sha,
        "governed_packet_sha256": governed_sha,
        "resolution_packet_sha256": resolution_sha,
        "item_count": len(packets),
        "items": packets,
    }
    review_bundle["packet_sha256"] = _digest(review_bundle)
    operations = [
        {
            "review_packet_id": packet["review_packet_id"],
            "review_packet_sha256": packet["packet_sha256"],
            "resolution_id": packet["resolution_id"],
            "action": packet["action"],
            "target_paths": packet["target_paths"],
            "audience": packet["audience"],
        }
        for packet in packets
    ]
    path_counts: dict[str, int] = defaultdict(int)
    for operation in operations:
        for path in operation["target_paths"]:
            path_counts[path] += 1
    bulk: dict[str, Any] = {
        "schema": "knowledge-engine-bulk-source-pr-preparation/v1",
        "authority": "review_preparation_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "all_items_individually_reviewable": True,
        "all_items_explicitly_approved": False,
        "source_write_permitted": False,
        "github_pr_creation_permitted": False,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "identity": identity,
        "review_bundle_sha256": review_bundle["packet_sha256"],
        "operation_count": len(operations),
        "target_file_count": len(path_counts),
        "operations": operations,
        "target_paths": sorted(path_counts),
        "review_instructions": [
            "Review every item independently against its exact evidence spans.",
            (
                "Reject the whole preparation if any path, audience, identity, "
                "or evidence binding drifts."
            ),
            (
                "A later governed human decision is required before any Source write "
                "or GitHub PR creation."
            ),
        ],
    }
    bulk["packet_sha256"] = _digest(bulk)
    return {"review_packets": review_bundle, "bulk_preparation": bulk}


__all__ = [
    "FOUNDATION_SHA",
    "SOURCE_SHA",
    "build_review_source_pr_preparation",
]
