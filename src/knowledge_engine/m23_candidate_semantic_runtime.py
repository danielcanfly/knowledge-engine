from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from knowledge_engine.errors import IntegrityError

QUERY_SCHEMA = "knowledge-engine-m23-candidate-semantic-query/v1"
RESPONSE_SCHEMA = "knowledge-engine-m23-candidate-semantic-response/v1"
SHADOW_SCHEMA = "knowledge-engine-m23-candidate-shadow-response/v1"
COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
VECTOR_NAME = "default"
VECTOR_DIMENSION = 1024
SOURCE_MEMBERSHIP = "evaluation-only-pending-proposal"
RELEASE_ID = "m23pilot-a07eb79e381ca7e635cc9139"
RELEASE_MANIFEST_SHA256 = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
MAX_QUERY_CHARS = 2_000
MAX_TOP_K = 20
DEFAULT_TOP_K = 8
MAX_LEXICAL_IDS = 20
MAX_RESPONSE_RESULTS = 20


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_string(value: object, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > max_length:
        raise IntegrityError(f"{field} length is invalid")
    return text


def validate_request(raw: Mapping[str, object], *, shadow: bool = False) -> dict[str, Any]:
    if raw.get("schema_version") != QUERY_SCHEMA:
        raise IntegrityError("unsupported query schema")
    query = _required_string(raw.get("query"), "query", max_length=MAX_QUERY_CHARS)
    top_k_raw = raw.get("top_k", DEFAULT_TOP_K)
    if isinstance(top_k_raw, bool) or not isinstance(top_k_raw, int):
        raise IntegrityError("top_k must be an integer")
    if not 1 <= top_k_raw <= MAX_TOP_K:
        raise IntegrityError("top_k is outside the bounded range")
    request_id = raw.get("request_id")
    if request_id is None:
        request_id = f"m23qry-{sha256_hex(query.encode('utf-8'))[:24]}"
    request_id = _required_string(request_id, "request_id", max_length=128)

    normalized: dict[str, Any] = {
        "schema_version": QUERY_SCHEMA,
        "request_id": request_id,
        "query": query,
        "top_k": top_k_raw,
    }
    if shadow:
        lexical = raw.get("lexical_point_ids")
        if not isinstance(lexical, Sequence) or isinstance(lexical, (str, bytes)):
            raise IntegrityError("lexical_point_ids must be an array")
        if len(lexical) > MAX_LEXICAL_IDS:
            raise IntegrityError("lexical_point_ids exceeds the bounded range")
        lexical_ids = [
            _required_string(item, "lexical_point_id", max_length=128) for item in lexical
        ]
        if len(set(lexical_ids)) != len(lexical_ids):
            raise IntegrityError("lexical_point_ids must be unique")
        normalized["lexical_point_ids"] = lexical_ids
    elif "lexical_point_ids" in raw:
        raise IntegrityError("lexical_point_ids is only valid for shadow requests")
    return normalized


def validate_embedding(vector: Sequence[object]) -> list[float]:
    if len(vector) != VECTOR_DIMENSION:
        raise IntegrityError("query embedding dimension mismatch")
    values: list[float] = []
    for item in vector:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise IntegrityError("query embedding contains a non-number")
        number = float(item)
        if not math.isfinite(number):
            raise IntegrityError("query embedding contains a non-finite number")
        values.append(number)
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0:
        raise IntegrityError("query embedding has invalid norm")
    return [value / norm for value in values]


def _validate_sha256(value: object, field: str) -> str:
    text = _required_string(value, field, max_length=64)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise IntegrityError(f"{field} is not a lowercase sha256")
    return text


@dataclass(frozen=True)
class CandidateResult:
    point_id: str
    score: float
    section_id: str
    article_id: str
    document_id: str
    concept_id: str
    source_path: str
    source_sha256: str
    text_sha256: str
    graph_node_id: str
    release_id: str
    release_manifest_sha256: str

    def as_dict(self, rank: int) -> dict[str, Any]:
        return {
            "rank": rank,
            "point_id": self.point_id,
            "score": self.score,
            "section_id": self.section_id,
            "article_id": self.article_id,
            "document_id": self.document_id,
            "concept_id": self.concept_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "text_sha256": self.text_sha256,
            "graph_node_id": self.graph_node_id,
            "release_id": self.release_id,
            "release_manifest_sha256": self.release_manifest_sha256,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }


def _parse_point(raw: Mapping[str, object]) -> CandidateResult:
    point_id = _required_string(raw.get("id"), "point id", max_length=128)
    score_raw = raw.get("score")
    if isinstance(score_raw, bool) or not isinstance(score_raw, (int, float)):
        raise IntegrityError("point score must be numeric")
    score = float(score_raw)
    if not math.isfinite(score) or not -1.0 <= score <= 1.0:
        raise IntegrityError("point score is outside cosine bounds")
    payload = raw.get("payload")
    if not isinstance(payload, Mapping):
        raise IntegrityError("point payload is missing")
    if payload.get("source_membership") != SOURCE_MEMBERSHIP:
        raise IntegrityError("point source membership is not candidate-only")
    if payload.get("release_id") != RELEASE_ID:
        raise IntegrityError("point release identity mismatch")
    if payload.get("release_manifest_sha256") != RELEASE_MANIFEST_SHA256:
        raise IntegrityError("point release manifest mismatch")
    if (
        payload.get("canonical_knowledge") is not False
        or payload.get("candidate_release_eligible") is not False
        or payload.get("production_authority") is not False
    ):
        raise IntegrityError("point authority flags are not fail-closed")
    if payload.get("vector_name") != VECTOR_NAME or payload.get("vector_dimension") != VECTOR_DIMENSION:
        raise IntegrityError("point vector contract mismatch")
    if payload.get("embedding_model") != "@cf/baai/bge-m3":
        raise IntegrityError("point embedding model mismatch")
    return CandidateResult(
        point_id=point_id,
        score=score,
        section_id=_required_string(payload.get("section_id"), "section_id", max_length=500),
        article_id=_required_string(payload.get("article_id"), "article_id", max_length=500),
        document_id=_required_string(payload.get("document_id"), "document_id", max_length=500),
        concept_id=_required_string(payload.get("concept_id"), "concept_id", max_length=500),
        source_path=_required_string(payload.get("source_path"), "source_path", max_length=2_000),
        source_sha256=_validate_sha256(payload.get("source_sha256"), "source_sha256"),
        text_sha256=_validate_sha256(payload.get("text_sha256"), "text_sha256"),
        graph_node_id=_required_string(payload.get("graph_node_id"), "graph_node_id", max_length=500),
        release_id=RELEASE_ID,
        release_manifest_sha256=RELEASE_MANIFEST_SHA256,
    )


def shape_response(request: Mapping[str, object], raw_points: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    normalized = validate_request(request)
    if len(raw_points) > MAX_RESPONSE_RESULTS:
        raise IntegrityError("qdrant result count exceeds response ceiling")
    parsed = [_parse_point(point) for point in raw_points]
    if len({item.point_id for item in parsed}) != len(parsed):
        raise IntegrityError("qdrant response contains duplicate point ids")
    ordered = sorted(parsed, key=lambda item: (-item.score, item.point_id))
    if len(ordered) > normalized["top_k"]:
        ordered = ordered[: normalized["top_k"]]
    query_sha = sha256_hex(normalized["query"].encode("utf-8"))
    body: dict[str, Any] = {
        "schema_version": RESPONSE_SCHEMA,
        "milestone": "M23.6.5",
        "request_id": normalized["request_id"],
        "query_sha256": query_sha,
        "collection": COLLECTION,
        "vector_name": VECTOR_NAME,
        "embedding_model": "@cf/baai/bge-m3",
        "result_count": len(ordered),
        "results": [item.as_dict(rank) for rank, item in enumerate(ordered, start=1)],
        "authority": {
            "read_only": True,
            "candidate_only": True,
            "lexical_production_authority_unchanged": True,
            "semantic_output_production_authority": False,
            "answer_generation_dispatched": False,
            "qdrant_write_dispatched": False,
            "source_mutation_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "production_mutation_dispatched": False,
        },
    }
    body["response_sha256"] = sha256_hex(canonical_json_bytes(body))
    return body


def shape_shadow_response(
    request: Mapping[str, object], raw_points: Sequence[Mapping[str, object]]
) -> dict[str, Any]:
    normalized = validate_request(request, shadow=True)
    semantic_request = {
        "schema_version": QUERY_SCHEMA,
        "request_id": normalized["request_id"],
        "query": normalized["query"],
        "top_k": normalized["top_k"],
    }
    semantic = shape_response(semantic_request, raw_points)
    lexical_ids = list(normalized["lexical_point_ids"])
    semantic_ids = [result["point_id"] for result in semantic["results"]]
    lexical_rank = {point_id: rank for rank, point_id in enumerate(lexical_ids, start=1)}
    semantic_rank = {point_id: rank for rank, point_id in enumerate(semantic_ids, start=1)}
    overlap = [point_id for point_id in lexical_ids if point_id in semantic_rank]
    diagnostics = [
        {
            "point_id": point_id,
            "lexical_rank": lexical_rank[point_id],
            "semantic_rank": semantic_rank[point_id],
            "rank_delta": semantic_rank[point_id] - lexical_rank[point_id],
        }
        for point_id in overlap
    ]
    body: dict[str, Any] = {
        "schema_version": SHADOW_SCHEMA,
        "milestone": "M23.6.5",
        "request_id": normalized["request_id"],
        "query_sha256": semantic["query_sha256"],
        "lexical_point_ids": lexical_ids,
        "semantic_point_ids": semantic_ids,
        "overlap_count": len(overlap),
        "overlap_at_k": len(overlap) / max(1, min(len(lexical_ids), len(semantic_ids))),
        "rank_diagnostics": diagnostics,
        "lexical_only_point_ids": [point_id for point_id in lexical_ids if point_id not in semantic_rank],
        "semantic_only_point_ids": [point_id for point_id in semantic_ids if point_id not in lexical_rank],
        "semantic_response_sha256": semantic["response_sha256"],
        "authority": {
            "lexical_output_authoritative": True,
            "semantic_output_served_to_production": False,
            "shadow_only": True,
            "answer_generation_dispatched": False,
            "qdrant_write_dispatched": False,
            "production_mutation_dispatched": False,
        },
    }
    body["shadow_sha256"] = sha256_hex(canonical_json_bytes(body))
    return body
