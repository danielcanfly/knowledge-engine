from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m21_entity_resolution import build_resolution_candidate_packet
from .m21_review_source_pr import build_review_source_pr_preparation

ENGINE_SHA = "5de0327501a8584098e5304160462c9c7e92daba"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
EXTRACTION_SHA = "32f29be6fa4a90d6495b0844fbe0e8a2003dec25d3adf5328a0fd0b2232ce402"
GOVERNED_SHA = "bc4a3c366d84baebd93982a39831fa7766e43a38018b0e0680e5b1c9f33c4875"
ENDPOINT_KINDS = {"concept", "entity"}
DECISIONS = {"approve_new", "map_existing", "edit", "reject", "defer"}
SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _signed(value: dict[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or claimed != _digest(unsigned):
        raise IntegrityError(code)
    return claimed


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _slug(value: str) -> str:
    slug = SAFE_SLUG.sub("-", _norm(value)).strip("-")
    if not slug:
        slug = f"concept-{hashlib.sha256(value.encode()).hexdigest()[:12]}"
    return slug[:96]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M23-REVIEW-101 cannot load {path.name}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M23-REVIEW-102 {path.name} must be an object")
    return value


def build_source_index(concepts: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(concepts, list) or not concepts:
        raise IntegrityError("M23-REVIEW-103 Source index requires concepts")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for concept in concepts:
        required = {
            "x_kos_id",
            "concept_path",
            "title",
            "aliases",
            "bilingual_terms",
            "tags",
            "audience",
            "source_sha256",
        }
        if not isinstance(concept, dict) or set(concept) != required:
            raise IntegrityError("M23-REVIEW-104 malformed Source concept")
        x_kos_id = concept["x_kos_id"]
        path = concept["concept_path"]
        if x_kos_id in seen_ids or path in seen_paths:
            raise IntegrityError("M23-REVIEW-105 duplicate Source identity")
        seen_ids.add(x_kos_id)
        seen_paths.add(path)
        row = dict(concept)
        row["normalized_title"] = _norm(concept["title"])
        rows.append(row)
    rows.sort(key=lambda item: item["x_kos_id"])
    index = {
        "schema": "knowledge-engine-source-resolution-index/v1",
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "authority": "reviewed_source_index",
        "concept_count": len(rows),
        "concepts": rows,
    }
    index["index_sha256"] = _digest(index)
    return index


def _validate_packets(
    extraction: dict[str, Any],
    governed: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    extraction_sha = _signed(
        extraction,
        "packet_sha256",
        "M23-REVIEW-106 extraction digest mismatch",
    )
    governed_sha = _signed(
        governed,
        "packet_sha256",
        "M23-REVIEW-107 governed digest mismatch",
    )
    if extraction_sha != EXTRACTION_SHA or governed_sha != GOVERNED_SHA:
        raise IntegrityError("M23-REVIEW-108 M23.3 packet identity mismatch")
    if governed.get("extraction_packet_sha256") != extraction_sha:
        raise IntegrityError("M23-REVIEW-109 cross-packet binding mismatch")
    for packet in (extraction, governed):
        if (
            packet.get("authority") != "candidate_only"
            or packet.get("canonical_knowledge") is not False
            or packet.get("production_authority") is not False
            or packet.get("review_required") is not True
        ):
            raise IntegrityError("M23-REVIEW-110 authority drift")
    identity = extraction.get("identity")
    if identity != governed.get("identity") or not isinstance(identity, dict):
        raise IntegrityError("M23-REVIEW-111 release identity mismatch")
    if (
        identity.get("source_sha") != SOURCE_SHA
        or identity.get("foundation_sha") != FOUNDATION_SHA
    ):
        raise IntegrityError("M23-REVIEW-112 Source or Foundation drift")
    candidates = extraction.get("candidates")
    relations = governed.get("typed_relation_candidates")
    tags = governed.get("governed_tag_candidates")
    if not isinstance(candidates, list) or extraction.get("candidate_count") != len(candidates):
        raise IntegrityError("M23-REVIEW-113 candidate coverage mismatch")
    if not isinstance(relations, list) or governed.get("typed_relation_count") != len(relations):
        raise IntegrityError("M23-REVIEW-114 relation coverage mismatch")
    if not isinstance(tags, list) or governed.get("governed_tag_count") != len(tags):
        raise IntegrityError("M23-REVIEW-115 tag coverage mismatch")
    return candidates, relations, tags


def _attachment_target(candidate: dict[str, Any]) -> str | None:
    kind = candidate.get("kind")
    if kind in {"alias", "definition"}:
        value = candidate.get("target_label")
    elif kind == "claim":
        value = candidate.get("subject_label")
    elif kind == "term":
        value = candidate.get("label")
        counterpart = candidate.get("counterpart_label")
        if isinstance(counterpart, str):
            return _norm(counterpart)
    else:
        return None
    return _norm(value) if isinstance(value, str) else None


def _review_items(
    candidates: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    tags: list[dict[str, Any]],
    resolution: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    endpoints = {
        _norm(candidate["label"]): candidate
        for candidate in candidates
        if candidate.get("kind") in ENDPOINT_KINDS
    }
    resolution_by_candidate: dict[str, dict[str, Any]] = {}
    for row in resolution["resolutions"]:
        for candidate_id in row["candidate_ids"]:
            resolution_by_candidate[candidate_id] = row

    tags_by_endpoint: dict[str, list[dict[str, Any]]] = {}
    for tag in tags:
        tags_by_endpoint.setdefault(tag["source_candidate_id"], []).append(tag)
    relations_by_endpoint: dict[str, list[dict[str, Any]]] = {}
    accounted: set[str] = set()
    for relation in relations:
        for endpoint_key in ("source_candidate_id", "target_candidate_id"):
            endpoint_id = relation[endpoint_key]
            relations_by_endpoint.setdefault(endpoint_id, []).append(relation)
        accounted.add(relation["hint_candidate_id"])

    attachments: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        target = _attachment_target(candidate)
        if target is not None and target in endpoints:
            endpoint_id = endpoints[target]["candidate_id"]
            attachments.setdefault(endpoint_id, []).append(candidate)
            accounted.add(candidate["candidate_id"])

    items: list[dict[str, Any]] = []
    for endpoint in sorted(endpoints.values(), key=lambda item: item["candidate_id"]):
        candidate_id = endpoint["candidate_id"]
        row = resolution_by_candidate.get(candidate_id)
        if row is None:
            raise IntegrityError("M23-REVIEW-116 endpoint lacks M21.5 resolution")
        endpoint_tags = sorted(
            tags_by_endpoint.get(candidate_id, []),
            key=lambda item: item["tag_candidate_id"],
        )
        endpoint_relations = sorted(
            relations_by_endpoint.get(candidate_id, []),
            key=lambda item: item["relation_candidate_id"],
        )
        endpoint_attachments = sorted(
            attachments.get(candidate_id, []),
            key=lambda item: item["candidate_id"],
        )
        accounted.add(candidate_id)
        item = {
            "review_item_id": f"m23review_{_digest({'candidate': candidate_id})[:32]}",
            "candidate_id": candidate_id,
            "label": endpoint["label"],
            "language": endpoint["language"],
            "definition": endpoint.get("definition"),
            "confidence": endpoint["confidence"],
            "evidence_spans": endpoint["evidence_spans"],
            "resolution": row,
            "governed_tags": endpoint_tags,
            "typed_relations": endpoint_relations,
            "attachments": endpoint_attachments,
            "proposed_paths": [
                f"bundle/concepts/{_slug(endpoint['label'])}.md",
                f"provenance/{_slug(endpoint['label'])}.json",
            ],
            "decision": "pending",
            "allowed_decisions": sorted(DECISIONS),
            "human_approval_required": True,
            "canonical_write_permitted": False,
        }
        item["review_item_sha256"] = _digest(item)
        items.append(item)

    unassigned = sorted(set(by_id) - accounted)
    return items, unassigned


def _m21_6_items(
    candidates: list[dict[str, Any]],
    resolution: dict[str, Any],
    review_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    output: list[dict[str, Any]] = []
    for item in review_items:
        row = item["resolution"]
        if row["outcome"] != "distinct_new_candidate":
            continue
        candidate = by_id[item["candidate_id"]]
        body = (
            f"---\ntype: Concept\ntitle: {candidate['label']}\n"
            "x-kos-status: draft\nx-kos-audience: public\n---\n\n"
            f"# {candidate['label']}\n\n{candidate.get('definition', '')}\n"
        )
        output.append(
            {
                "resolution_id": row["resolution_id"],
                "action": "create_concept",
                "candidate_ids": row["candidate_ids"],
                "target_paths": item["proposed_paths"],
                "proposed_concept_body": body,
                "proposed_change": None,
                "governed_tag_candidate_ids": [
                    value["tag_candidate_id"] for value in item["governed_tags"]
                ],
                "typed_relation_candidate_ids": [
                    value["relation_candidate_id"] for value in item["typed_relations"]
                ],
                "existing_comparison": {
                    "x_kos_id": None,
                    "concept_path": None,
                    "comparison_summary": "No exact existing Source concept match.",
                },
                "duplicate_conflict_analysis": {
                    "duplicate": False,
                    "ambiguity": False,
                    "contradiction": False,
                    "acl_conflict": False,
                    "notes": [],
                },
                "audience": "public",
                "confidence": min(float(candidate["confidence"]), float(row["confidence"])),
            }
        )
    return output


def build_human_review_package(
    extraction: dict[str, Any],
    governed: dict[str, Any],
    source_concepts: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates, relations, tags = _validate_packets(extraction, governed)
    source_index = build_source_index(source_concepts)
    candidate_audiences = {
        candidate["candidate_id"]: "public" for candidate in candidates
    }
    resolution = build_resolution_candidate_packet(
        extraction,
        governed,
        source_index,
        candidate_audiences=candidate_audiences,
        claim_assertions=[],
    )
    review_items, unassigned = _review_items(candidates, relations, tags, resolution)
    m21_6 = None
    m21_6_status = "blocked_by_m21_5"
    if resolution["packaging_blocked"] is False:
        proposed_items = _m21_6_items(candidates, resolution, review_items)
        m21_6 = build_review_source_pr_preparation(
            extraction,
            governed,
            resolution,
            proposed_items,
        )
        m21_6_status = "prepared"

    decision_template = {
        "schema_version": "knowledge-engine-m23-human-decisions/v1",
        "engine_sha": ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "human_actor": None,
        "reviewed_at": None,
        "items": [
            {
                "review_item_id": item["review_item_id"],
                "decision": "pending",
                "mapped_x_kos_id": None,
                "edited_title": None,
                "notes": None,
            }
            for item in review_items
        ],
    }
    decision_template["template_sha256"] = _digest(decision_template)
    manual_packet = {
        "schema_version": "knowledge-engine-m23-human-review/v1",
        "authority": "human_review_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_index_sha256": source_index["index_sha256"],
        "extraction_packet_sha256": EXTRACTION_SHA,
        "governed_packet_sha256": GOVERNED_SHA,
        "resolution_packet_sha256": resolution["packet_sha256"],
        "m21_6_status": m21_6_status,
        "review_item_count": len(review_items),
        "unassigned_candidate_ids": unassigned,
        "items": review_items,
    }
    manual_packet["packet_sha256"] = _digest(manual_packet)
    receipt = {
        "schema_version": "knowledge-engine-m23-human-review-receipt/v1",
        "authority": "review_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "human_approval_recorded": False,
        "engine_sha": ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "candidate_count": len(candidates),
        "endpoint_count": len(review_items),
        "typed_relation_count": len(relations),
        "governed_tag_count": len(tags),
        "resolution_count": resolution["resolution_count"],
        "resolution_packaging_blocked": resolution["packaging_blocked"],
        "m21_6_status": m21_6_status,
        "manual_review_packet_sha256": manual_packet["packet_sha256"],
        "decision_template_sha256": decision_template["template_sha256"],
        "source_pr_required_state": "draft",
        "source_pr_merge_permitted": False,
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return {
        "source_index": source_index,
        "resolution_packet": resolution,
        "manual_review_packet": manual_packet,
        "decision_template": decision_template,
        "m21_6_preparation": m21_6,
        "receipt": receipt,
    }


__all__ = ["build_human_review_package", "build_source_index", "load_json"]
