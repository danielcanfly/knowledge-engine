from __future__ import annotations

import hashlib
import json
import math
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .errors import IntegrityError

CLOUDFLARE_MODEL = "@cf/baai/bge-m3"
CLOUDFLARE_PROVIDER = "cloudflare-workers-ai"
VECTOR_DIMENSION = 1024
MAX_BATCH_SIZE = 100
QDRANT_DISTANCE = "Cosine"
QDRANT_VECTOR_NAME = "default"
RECEIPT_SCHEMA = "knowledge-engine-m23-cloudflare-qdrant-receipt/v1"
POINT_NAMESPACE = uuid.UUID("e251e02f-81ef-4cd6-a9fb-d55cba1925ea")


@dataclass(frozen=True)
class SectionInput:
    section_id: str
    text: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CloudflareConfig:
    account_id: str
    api_token: str
    model: str = CLOUDFLARE_MODEL
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class QdrantConfig:
    base_url: str
    api_key: str
    collection_name: str
    timeout_seconds: float = 120.0


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError("M23-EMBED-101 text must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise IntegrityError("M23-EMBED-102 text must not be empty")
    return normalized


def _required_string(value: Any, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M23-EMBED-103 {label} must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise IntegrityError(
            f"M23-EMBED-104 {label} must contain 1 to {maximum} characters"
        )
    return candidate


def validate_sections(raw_sections: Sequence[Mapping[str, Any]]) -> list[SectionInput]:
    if not isinstance(raw_sections, list) or not raw_sections:
        raise IntegrityError("M23-EMBED-105 sections must be a non-empty array")
    seen: set[str] = set()
    sections: list[SectionInput] = []
    for raw in raw_sections:
        if not isinstance(raw, Mapping):
            raise IntegrityError("M23-EMBED-106 section must be an object")
        section_id = _required_string(raw.get("section_id"), "section_id", 300)
        if section_id in seen:
            raise IntegrityError(f"M23-EMBED-107 duplicate section_id: {section_id}")
        seen.add(section_id)
        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise IntegrityError("M23-EMBED-108 payload must be an object")
        sections.append(
            SectionInput(
                section_id=section_id,
                text=normalize_text(raw.get("text")),
                payload=dict(payload),
            )
        )
    return sections


def build_cloudflare_request(texts: Sequence[str]) -> dict[str, Any]:
    if not texts or len(texts) > MAX_BATCH_SIZE:
        raise IntegrityError(
            f"M23-EMBED-109 batch must contain 1 to {MAX_BATCH_SIZE} texts"
        )
    return {"text": [normalize_text(text) for text in texts]}


def _extract_embedding_rows(response: Mapping[str, Any]) -> list[Any]:
    result = response.get("result", response)
    data = result.get("data") if isinstance(result, Mapping) else None
    if isinstance(data, list):
        if data and isinstance(data[0], Mapping) and "embedding" in data[0]:
            return [item.get("embedding") for item in data]
        return data
    openai_data = response.get("data")
    if isinstance(openai_data, list):
        return [
            item.get("embedding")
            for item in openai_data
            if isinstance(item, Mapping)
        ]
    raise IntegrityError("M23-EMBED-110 Cloudflare response contains no embedding data")


def parse_cloudflare_embeddings(
    response: Mapping[str, Any], *, expected_count: int
) -> list[list[float]]:
    if response.get("success") is False:
        raise IntegrityError("M23-EMBED-111 Cloudflare provider returned failure")
    rows = _extract_embedding_rows(response)
    if len(rows) != expected_count:
        raise IntegrityError(
            f"M23-EMBED-112 expected {expected_count} embeddings, got {len(rows)}"
        )
    vectors: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != VECTOR_DIMENSION:
            raise IntegrityError(
                f"M23-EMBED-113 embedding dimension must be {VECTOR_DIMENSION}"
            )
        vector: list[float] = []
        for value in row:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise IntegrityError("M23-EMBED-114 embedding values must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise IntegrityError("M23-EMBED-115 embedding values must be finite")
            vector.append(number)
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if norm <= 0.0:
            raise IntegrityError("M23-EMBED-116 embedding norm must be positive")
        vectors.append([value / norm for value in vector])
    return vectors


def deterministic_point_id(section_id: str, model: str = CLOUDFLARE_MODEL) -> str:
    identity = f"{model}\n{_required_string(section_id, 'section_id', 300)}"
    return str(uuid.uuid5(POINT_NAMESPACE, identity))


def build_qdrant_points(
    sections: Sequence[SectionInput], vectors: Sequence[Sequence[float]]
) -> list[dict[str, Any]]:
    if len(sections) != len(vectors):
        raise IntegrityError("M23-EMBED-117 section/vector count mismatch")
    points: list[dict[str, Any]] = []
    for section, vector in zip(sections, vectors, strict=True):
        if len(vector) != VECTOR_DIMENSION:
            raise IntegrityError("M23-EMBED-118 invalid vector dimension")
        numeric = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in numeric):
            raise IntegrityError("M23-EMBED-119 vector values must be finite")
        payload = {
            **dict(section.payload),
            "section_id": section.section_id,
            "text_sha256": hashlib.sha256(section.text.encode("utf-8")).hexdigest(),
            "embedding_model": CLOUDFLARE_MODEL,
            "embedding_provider": CLOUDFLARE_PROVIDER,
            "vector_dimension": VECTOR_DIMENSION,
            "vector_name": QDRANT_VECTOR_NAME,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        points.append(
            {
                "id": deterministic_point_id(section.section_id),
                "vector": {QDRANT_VECTOR_NAME: numeric},
                "payload": payload,
            }
        )
    return points


def build_provider_contract(
    *, engine_sha: str, source_sha: str, foundation_sha: str
) -> dict[str, Any]:
    return {
        "schema_version": "knowledge-os-embedding-provider-contract/v1",
        "provider": {
            "name": CLOUDFLARE_PROVIDER,
            "implementation": "Cloudflare Workers AI REST API",
            "execution": "remote-batch-generation",
        },
        "model": {
            "id": CLOUDFLARE_MODEL,
            "revision": "cloudflare-managed",
            "vector_dimension": VECTOR_DIMENSION,
        },
        "tokenizer": {
            "id": "BAAI/bge-m3",
            "revision": "cloudflare-managed",
        },
        "preprocessing": {
            "pooling": "provider-native",
            "normalization": "l2",
            "input_template": "{text}",
            "query_template": "{text}",
            "maximum_input_length": 60_000,
            "truncation": "error",
            "unicode_normalization": "NFKC",
        },
        "batching": {
            "batch_size": MAX_BATCH_SIZE,
            "preserve_input_order": True,
            "deterministic": True,
        },
        "identities": {
            "engine_commit_sha": engine_sha,
            "source_commit_sha": source_sha,
            "foundation_commit_sha": foundation_sha,
        },
        "authority": {
            "canonical_source": "markdown",
            "vectors_are_derived": True,
            "runtime_network_required": False,
            "write_back": False,
            "production_authority": False,
        },
    }


def build_execution_plan(
    sections: Sequence[SectionInput], *, collection_name: str
) -> dict[str, Any]:
    collection = _required_string(collection_name, "collection_name", 255)
    plan = {
        "schema_version": "knowledge-engine-m23-cloudflare-qdrant-plan/v1",
        "provider": CLOUDFLARE_PROVIDER,
        "model": CLOUDFLARE_MODEL,
        "vector_dimension": VECTOR_DIMENSION,
        "qdrant": {
            "collection_name": collection,
            "vector_name": QDRANT_VECTOR_NAME,
            "distance": QDRANT_DISTANCE,
            "point_count": len(sections),
        },
        "sections": [
            {
                "section_id": section.section_id,
                "text_sha256": hashlib.sha256(section.text.encode("utf-8")).hexdigest(),
                "point_id": deterministic_point_id(section.section_id),
            }
            for section in sections
        ],
        "authority": {
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
            "r2_mutation": False,
            "pointer_mutation": False,
            "source_write": False,
        },
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def _chunks(values: Sequence[SectionInput], size: int) -> Iterable[Sequence[SectionInput]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def embed_sections(
    sections: Sequence[SectionInput],
    config: CloudflareConfig,
    *,
    client: httpx.Client | None = None,
) -> list[list[float]]:
    account_id = quote(_required_string(config.account_id, "account_id", 100), safe="")
    token = _required_string(config.api_token, "api_token", 10_000)
    model = quote(_required_string(config.model, "model", 300), safe="@/")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    owned_client = client is None
    http = client or httpx.Client(timeout=config.timeout_seconds)
    vectors: list[list[float]] = []
    try:
        for batch in _chunks(list(sections), MAX_BATCH_SIZE):
            response = http.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=build_cloudflare_request([section.text for section in batch]),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise IntegrityError("M23-EMBED-120 provider response must be an object")
            vectors.extend(
                parse_cloudflare_embeddings(payload, expected_count=len(batch))
            )
    finally:
        if owned_client:
            http.close()
    return vectors


def validate_qdrant_collection_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise IntegrityError("M23-EMBED-121 Qdrant collection response has no result")
    config = result.get("config")
    if not isinstance(config, Mapping):
        raise IntegrityError("M23-EMBED-122 Qdrant collection response has no config")
    params = config.get("params")
    if not isinstance(params, Mapping):
        raise IntegrityError("M23-EMBED-123 Qdrant collection response has no params")
    vectors = params.get("vectors")
    if not isinstance(vectors, Mapping):
        raise IntegrityError("M23-EMBED-124 Qdrant collection has no vectors")
    vector = vectors.get(QDRANT_VECTOR_NAME)
    if not isinstance(vector, Mapping):
        raise IntegrityError(
            f"M23-EMBED-125 Qdrant collection requires named vector {QDRANT_VECTOR_NAME}"
        )
    if vector.get("size") != VECTOR_DIMENSION:
        raise IntegrityError(
            f"M23-EMBED-126 Qdrant vector dimension must be {VECTOR_DIMENSION}"
        )
    if vector.get("distance") != QDRANT_DISTANCE:
        raise IntegrityError(
            f"M23-EMBED-127 Qdrant distance must be {QDRANT_DISTANCE}"
        )
    sparse = params.get("sparse_vectors")
    if sparse not in (None, {}):
        raise IntegrityError(
            "M23-EMBED-128 pilot collection must not contain sparse vectors"
        )
    if result.get("status") != "green":
        raise IntegrityError("M23-EMBED-129 Qdrant collection must be green")
    return {
        "status": result.get("status"),
        "points_count": result.get("points_count"),
        "indexed_vectors_count": result.get("indexed_vectors_count"),
        "vector_name": QDRANT_VECTOR_NAME,
        "vector_dimension": VECTOR_DIMENSION,
        "distance": QDRANT_DISTANCE,
        "sparse_vectors": sparse,
        "read_only": True,
    }


def preflight_qdrant_collection(
    config: QdrantConfig, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    base_url = _required_string(config.base_url, "base_url", 2_000).rstrip("/")
    api_key = _required_string(config.api_key, "api_key", 10_000)
    collection = quote(
        _required_string(config.collection_name, "collection_name", 255), safe=""
    )
    owned_client = client is None
    http = client or httpx.Client(timeout=config.timeout_seconds)
    try:
        response = http.get(
            f"{base_url}/collections/{collection}",
            headers={"api-key": api_key},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise IntegrityError("M23-EMBED-130 Qdrant preflight response must be an object")
        return validate_qdrant_collection_response(payload)
    finally:
        if owned_client:
            http.close()


def upsert_qdrant_points(
    points: Sequence[Mapping[str, Any]],
    config: QdrantConfig,
    *,
    allow_write: bool,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    if allow_write is not True:
        raise IntegrityError("M23-EMBED-131 Qdrant write requires explicit allow_write")
    base_url = _required_string(config.base_url, "base_url", 2_000).rstrip("/")
    api_key = _required_string(config.api_key, "api_key", 10_000)
    collection = quote(
        _required_string(config.collection_name, "collection_name", 255), safe=""
    )
    owned_client = client is None
    http = client or httpx.Client(timeout=config.timeout_seconds)
    try:
        preflight = preflight_qdrant_collection(config, client=http)
        if preflight.get("points_count") not in (0, None):
            raise IntegrityError(
                "M23-EMBED-132 first pilot write requires an empty collection"
            )
        response = http.put(
            f"{base_url}/collections/{collection}/points",
            params={"wait": "true", "ordering": "strong"},
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={"points": list(points)},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or payload.get("status") != "ok":
            raise IntegrityError("M23-EMBED-133 Qdrant upsert was not acknowledged")
        return {
            "status": "ok",
            "preflight": preflight,
            "upsert": dict(payload),
        }
    finally:
        if owned_client:
            http.close()


def build_receipt(
    *,
    plan: Mapping[str, Any],
    vectors: Sequence[Sequence[float]] | None,
    qdrant_response: Mapping[str, Any] | None,
    executed: bool,
    qdrant_write: bool,
) -> dict[str, Any]:
    vector_digest = None
    if vectors is not None:
        vector_digest = canonical_sha256(
            [[round(float(value), 8) for value in vector] for vector in vectors]
        )
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "plan_sha256": plan.get("plan_sha256"),
        "provider": CLOUDFLARE_PROVIDER,
        "model": CLOUDFLARE_MODEL,
        "executed": executed,
        "qdrant_write": qdrant_write,
        "vector_count": len(vectors) if vectors is not None else 0,
        "vector_dimension": VECTOR_DIMENSION,
        "qdrant_vector_name": QDRANT_VECTOR_NAME,
        "vector_digest_sha256": vector_digest,
        "qdrant_status": qdrant_response.get("status") if qdrant_response else None,
        "secrets_recorded": False,
        "authority": {
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
            "r2_mutation": False,
            "pointer_mutation": False,
            "source_write": False,
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt
