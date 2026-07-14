from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m21_extraction_candidates import build_candidate_packet
from .m21_governed_relations import FOUNDATION_SHA, build_governed_candidate_packet

ENGINE_SHA = "c9a91bfbe21ee107b80cd79644cb398c9abbed95"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
M23_BATCH_ID = "m23batch_d7a9c85f4ac8070448ccf7d96037d320"
M23_RECEIPT_SHA = "480b51aca822a2a28f36692edbb677eade77c93e2c85bf46def405878af3eae5"
ALLOWED_TAGS = [
    "agents", "evaluation", "knowledge-systems", "rag", "governance", "observability",
    "reliability", "security", "build", "design", "operations", "runtime", "planning",
    "retrieval", "routing", "verification",
]
TAG_DIMENSIONS = {
    "domain": ["agents", "evaluation", "knowledge-systems", "rag"],
    "concern": ["governance", "observability", "reliability", "security"],
    "lifecycle": ["build", "design", "operations", "runtime"],
    "technique": ["planning", "retrieval", "routing", "verification"],
}


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _m23_digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value) + b"\n").hexdigest()


def _signed(value: dict[str, Any], field: str, code: str) -> str:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or _digest(unsigned) != claimed:
        raise IntegrityError(code)
    return claimed


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M23-AI-101 cannot load {path.name}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M23-AI-102 {path.name} must be an object")
    return value


def _foundation_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    rows = [
        ("is_a", True, False, "has_subtype", "reviewed_structural", ["taxonomy"]),
        ("has_subtype", True, False, "is_a", "reviewed_structural", ["taxonomy"]),
        ("part_of", True, False, "has_part", "reviewed_structural", ["composition"]),
        ("has_part", True, False, "part_of", "reviewed_structural", ["composition"]),
        ("uses", True, False, "used_by", "required_or_reviewed_structural", ["dependency"]),
        ("used_by", True, False, "uses", "required_or_reviewed_structural", ["dependency"]),
        ("produces", True, False, "produced_by", "required_factual", ["production"]),
        ("produced_by", True, False, "produces", "required_factual", ["production"]),
        ("requires", True, False, "required_by", "required_factual", ["dependency"]),
        ("required_by", True, False, "requires", "required_factual", ["dependency"]),
        ("implements", True, False, "implemented_by", "required_or_reviewed_structural", ["implementation"]),
        ("implemented_by", True, False, "implements", "required_or_reviewed_structural", ["implementation"]),
        ("supports", True, False, "supported_by", "required_factual", ["dependency"]),
        ("supported_by", True, False, "supports", "required_factual", ["dependency"]),
        ("contrasts_with", False, True, "contrasts_with", "required_factual", ["comparison"]),
        ("complements", False, True, "complements", "required_factual", ["complement"]),
        ("alternative_to", False, True, "alternative_to", "required_factual", ["comparison"]),
        ("supersedes", True, False, "superseded_by", "required_factual", ["evolution"]),
        ("superseded_by", True, False, "supersedes", "required_factual", ["evolution"]),
        ("related_to", False, True, "related_to", "required_factual", ["generic"]),
    ]
    ontology = {
        "schema_version": "knowledge-os-relation-ontology/v0.1",
        "ontology_id": "daniel-knowledge-os/relation-ontology",
        "version": "0.1.0",
        "status": "normative_draft",
        "fallback_type": "related_to",
        "relation_types": [
            {
                "type": name,
                "directed": directed,
                "symmetric": symmetric,
                "inverse": inverse,
                "provenance_expectation": provenance,
                "allowed_qualifiers": ["scope", "context", "valid_from", "valid_to"],
                "retrieval_semantics": semantics,
                "description": f"Governed Knowledge OS relation type for {name.replace('_', ' ')} semantics.",
            }
            for name, directed, symmetric, inverse, provenance, semantics in rows
        ],
    }
    taxonomy = {
        "schema_version": "knowledge-os-tag-taxonomy/v0.1",
        "taxonomy_id": "daniel-knowledge-os/tag-taxonomy",
        "version": "0.1.0",
        "status": "active",
        "dimensions": TAG_DIMENSIONS,
        "tag_aliases": {
            "knowledge-system": "knowledge-systems",
            "observability-engineering": "observability",
            "retrieval-augmented-generation": "rag",
        },
    }
    return ontology, taxonomy


def _validate_m23_inputs(plan: dict[str, Any], checkpoint: dict[str, Any], receipt: dict[str, Any]) -> None:
    plan_unsigned = {k: v for k, v in plan.items() if k != "plan_sha256"}
    checkpoint_unsigned = {k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"}
    receipt_unsigned = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if plan.get("schema_version") != "knowledge-engine-m23-live-intake-plan/v1":
        raise IntegrityError("M23-AI-103 invalid M23.2 plan")
    if _m23_digest(plan_unsigned) != plan.get("plan_sha256"):
        raise IntegrityError("M23-AI-104 plan digest mismatch")
    if plan.get("plan_sha256") != checkpoint.get("plan_sha256"):
        raise IntegrityError("M23-AI-105 checkpoint plan mismatch")
    if _m23_digest(checkpoint_unsigned) != checkpoint.get("checkpoint_sha256"):
        raise IntegrityError("M23-AI-106 checkpoint digest mismatch")
    if plan.get("batch_id") != M23_BATCH_ID or checkpoint.get("batch_id") != M23_BATCH_ID:
        raise IntegrityError("M23-AI-107 batch identity mismatch")
    if plan.get("engine_sha") != "3e69058e94b3ba039601e64895d3d17265391750":
        raise IntegrityError("M23-AI-108 M23.2 Engine identity mismatch")
    if plan.get("source_sha") != SOURCE_SHA or plan.get("foundation_sha") != FOUNDATION_SHA:
        raise IntegrityError("M23-AI-109 Source or Foundation identity mismatch")
    if receipt.get("receipt_sha256") != M23_RECEIPT_SHA or _m23_digest(receipt_unsigned) != M23_RECEIPT_SHA:
        raise IntegrityError("M23-AI-110 receipt identity mismatch")
    if any(item.get("status") != "completed" for item in checkpoint.get("items", [])):
        raise IntegrityError("M23-AI-111 incomplete M23.2 item")


def _bridge(plan: dict[str, Any], source_root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    identity = {"engine_sha": ENGINE_SHA, "source_sha": SOURCE_SHA, "foundation_sha": FOUNDATION_SHA}
    items = []
    derivatives = []
    batch_id = _digest({"m23_batch": M23_BATCH_ID, "engine": ENGINE_SHA})
    for item in plan["items"]:
        document_id = item["document_id"]
        text_path = source_root / document_id / "normalized.md"
        try:
            text = text_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise IntegrityError(f"M23-AI-112 missing normalized derivative: {document_id}") from exc
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        result = _load(source_root / document_id / "intake-result.json")
        if text_sha != result.get("normalized_sha256"):
            raise IntegrityError(f"M23-AI-113 normalized derivative drift: {document_id}")
        item_key = _digest({"document_id": document_id, "raw_sha256": item["raw_sha256"]})
        items.append({
            "item_key": item_key,
            "canonical_url": item["source_uri"],
            "content_sha256": item["raw_sha256"],
            "source_kind": "markdown",
            "locator": item["original_filename"],
            "audience": item["audience"],
            "expected_action": "verify",
        })
        derivatives.append({
            "schema": "knowledge-engine-normalized-derivative/v1",
            "derivative_id": f"derivative_{document_id}",
            "item_key": item_key,
            "batch_id": batch_id,
            "audience": item["audience"],
            "source_content_sha256": item["raw_sha256"],
            "normalized": True,
            "language": item["language"],
            "text": text,
            "text_sha256": text_sha,
        })
    m21_plan = {
        "schema": "knowledge-engine-resumable-batch/v1",
        "authority": "evidence_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "inventory_sha256": plan["corpus_manifest_digest"],
        "identity": identity,
        "batch_size": 6,
        "item_count": 6,
        "batches": [{"batch_index": 0, "batch_id": batch_id, "items": items}],
    }
    m21_plan["plan_sha256"] = _digest(m21_plan)
    states = [{
        "item_key": item["item_key"], "batch_id": batch_id, "status": "completed",
        "attempts": 1, "failure_code": None, "retry_at": None,
        "updated_at": plan["retrieved_at"],
    } for item in items]
    checkpoint = {
        "schema": "knowledge-engine-batch-checkpoint/v1",
        "plan_sha256": m21_plan["plan_sha256"],
        "identity": identity,
        "revision": 12,
        "states": states,
        "resume_cursor": None,
    }
    checkpoint["checkpoint_sha256"] = _digest(checkpoint)
    return m21_plan, checkpoint, derivatives


def _validate_provider(request: dict[str, Any], response: dict[str, Any], derivatives: list[dict[str, Any]]) -> None:
    if request.get("schema_version") != "knowledge-engine-m23-provider-request/v1":
        raise IntegrityError("M23-AI-114 invalid provider request")
    if _signed(request, "request_sha256", "M23-AI-115 request digest mismatch") != response.get("request_sha256"):
        raise IntegrityError("M23-AI-116 provider response request mismatch")
    if response.get("schema_version") != "knowledge-engine-m23-provider-response/v1":
        raise IntegrityError("M23-AI-117 invalid provider response")
    _signed(response, "response_sha256", "M23-AI-118 response digest mismatch")
    if response.get("provider") != request.get("provider"):
        raise IntegrityError("M23-AI-119 provider identity drift")
    if response.get("authority") != "candidate_only" or response.get("review_required") is not True:
        raise IntegrityError("M23-AI-120 provider authority drift")
    expected = {item["derivative_id"]: item["text_sha256"] for item in derivatives}
    observed = {item.get("derivative_id"): item.get("text_sha256") for item in request.get("inputs", [])}
    if observed != expected:
        raise IntegrityError("M23-AI-121 provider input derivative mismatch")


def execute_real_ai_extraction(*, evidence_root: Path, request_path: Path, response_path: Path) -> dict[str, Any]:
    batch_root = evidence_root / "batches" / M23_BATCH_ID
    plan = _load(batch_root / "plan.json")
    checkpoint = _load(batch_root / "checkpoint.json")
    receipt = _load(batch_root / "execution-receipt.json")
    _validate_m23_inputs(plan, checkpoint, receipt)
    m21_plan, m21_checkpoint, derivatives = _bridge(plan, evidence_root / "review-packets")
    request, response = _load(request_path), _load(response_path)
    _validate_provider(request, response, derivatives)
    extraction = build_candidate_packet(
        m21_plan, m21_checkpoint, derivatives, response["proposals"], allowed_tags=ALLOWED_TAGS
    )
    candidates = extraction["candidates"]
    endpoints = {c["label"]: c for c in candidates if c["kind"] in {"concept", "entity"}}
    hints = {(c["source_label"], c["target_label"], c["predicate"]): c for c in candidates if c["kind"] == "relation_hint"}
    relation_mappings = []
    for value in response["relation_mappings"]:
        hint = hints.get((value["source_label"], value["target_label"], value["predicate"]))
        source, target = endpoints.get(value["source_label"]), endpoints.get(value["target_label"])
        if hint is None or source is None or target is None:
            raise IntegrityError("M23-AI-122 unresolved provider relation mapping")
        relation_mappings.append({
            "hint_candidate_id": hint["candidate_id"],
            "source_candidate_id": source["candidate_id"],
            "target_candidate_id": target["candidate_id"],
            "relation_type": value["relation_type"],
            "direction": value["direction"],
            "confidence": value["confidence"],
            "qualifiers": value["qualifiers"],
        })
    tag_mappings = []
    for value in response["tag_mappings"]:
        endpoint = endpoints.get(value["label"])
        if endpoint is None:
            raise IntegrityError("M23-AI-123 unresolved provider tag mapping")
        tag_mappings.append({
            "candidate_id": endpoint["candidate_id"],
            "source_tag": value["source_tag"],
            "dimension": value["dimension"],
            "confidence": value["confidence"],
        })
    ontology, taxonomy = _foundation_contracts()
    governed = build_governed_candidate_packet(
        extraction, relation_mappings, tag_mappings, foundation_sha=FOUNDATION_SHA,
        relation_ontology=ontology, tag_taxonomy=taxonomy,
    )
    result = {
        "schema_version": "knowledge-engine-m23-real-ai-extraction-receipt/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "engine_sha": ENGINE_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "m23_2_batch_id": M23_BATCH_ID,
        "m23_2_receipt_sha256": M23_RECEIPT_SHA,
        "provider": response["provider"],
        "request_sha256": request["request_sha256"],
        "response_sha256": response["response_sha256"],
        "document_count": len(derivatives),
        "candidate_count": extraction["candidate_count"],
        "typed_relation_count": governed["typed_relation_count"],
        "governed_tag_count": governed["governed_tag_count"],
        "extraction_packet_sha256": extraction["packet_sha256"],
        "governed_packet_sha256": governed["packet_sha256"],
    }
    result["receipt_sha256"] = _digest(result)
    return {"receipt": result, "extraction_packet": extraction, "governed_packet": governed}


__all__ = ["execute_real_ai_extraction"]
