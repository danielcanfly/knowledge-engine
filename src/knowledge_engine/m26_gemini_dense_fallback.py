from __future__ import annotations

import hashlib
import math
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .errors import IntegrityError
from .m23_cloudflare_qdrant import SectionInput

GEMINI_PROVIDER = "google-gemini-api"
GEMINI_MODEL = "gemini-embedding-2"
GEMINI_DIMENSION = 768
GEMINI_QUERY_TASK_INTENT = "RETRIEVAL_QUERY"
GEMINI_DOCUMENT_TASK_INTENT = "RETRIEVAL_DOCUMENT"
GEMINI_QUERY_PROMPT_PREFIX = "task: search result | query: "
GEMINI_VECTOR_NAME = "gemini_embedding_2_768"
GEMINI_DISTANCE = "Cosine"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
GEMINI_AUTHORITY_HTTP_STATUSES = frozenset({401, 403})
GEMINI_POINT_NAMESPACE = uuid.UUID("80ca43e3-cbf1-4f31-a159-e427953ce39a")

# Frozen SM-GF candidate authority. This is deliberately not a production pointer.
M26_GEMINI_CANDIDATE_RELEASE_ID = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
M26_GEMINI_CANDIDATE_SOURCE_SHA = "f5e20062c1400d7320fe2dbecf6409a0a8c910a7"
M26_GEMINI_CANDIDATE_ADMISSION_SHA256 = (
    "ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d"
)
M26_GEMINI_CANDIDATE_SOURCE_COUNT = 180
M26_GEMINI_CANDIDATE_POINT_COUNT = 4424
M26_GEMINI_SOURCE_PR_HEAD = "a738f20b16f10925c8adfe4d625be8db30fb269c"
M26_GEMINI_SEMANTIC_INPUTS_SHA256 = (
    "0982aaa55893bb2f95a8c0e0571cf5bef8beffb56346c9edf05c5a2e83597012"
)
M26_GEMINI_LEXICAL_DOCUMENTS_SHA256 = (
    "1ee4e01ff7b08ef6f54b445112db25565eb8f72b932ec89473947fb7ba4dc3bf"
)
M26_GEMINI_SOURCE_INDEX_SHA256 = (
    "3b63e70b99b25cc0e83a2ceb56bf8b515402f92774af0a839839abd6cb0b864f"
)
M26_BGE_PRIMARY_COLLECTION = (
    "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440"
)
M26_GEMINI_COLLECTION = (
    "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440_gemini_e2_768"
)


class GeminiDenseFallbackError(IntegrityError):
    """Fail-closed Gemini dense fallback contract error."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


@dataclass(frozen=True)
class GeminiEmbeddingConfig:
    api_key: str
    model: str = GEMINI_MODEL
    output_dimension: int = GEMINI_DIMENSION
    timeout_seconds: float = 10.0
    api_base: str = GEMINI_API_BASE


@dataclass(frozen=True)
class GeminiDenseConfig:
    embedding: GeminiEmbeddingConfig
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str = M26_GEMINI_COLLECTION
    vector_name: str = GEMINI_VECTOR_NAME
    expected_release_id: str = M26_GEMINI_CANDIDATE_RELEASE_ID
    expected_source_sha: str = M26_GEMINI_CANDIDATE_SOURCE_SHA
    expected_admission_sha256: str = M26_GEMINI_CANDIDATE_ADMISSION_SHA256
    timeout_seconds: float = 10.0
    primary_qdrant_collection: str | None = None


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise GeminiDenseFallbackError("GEMINI_TEXT_INVALID", "text must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise GeminiDenseFallbackError("GEMINI_TEXT_INVALID", "text must not be empty")
    return normalized


def format_retrieval_query(query: str) -> str:
    """Map RETRIEVAL_QUERY intent to the Gemini Embedding 2 search-query format."""
    return GEMINI_QUERY_PROMPT_PREFIX + normalize_text(query)


def format_retrieval_document(text: str, *, title: str | None = None) -> str:
    """Map RETRIEVAL_DOCUMENT intent to the Gemini Embedding 2 document format."""
    normalized_title = "none" if title is None or not title.strip() else normalize_text(title)
    return f"title: {normalized_title} | text: {normalize_text(text)}"


def _embedding_url(config: GeminiEmbeddingConfig, *, batch: bool = False) -> str:
    suffix = "batchEmbedContents" if batch else "embedContent"
    return f"{config.api_base.rstrip('/')}/models/{quote(config.model, safe='')}:{suffix}"


def _parse_embedding_values(raw: Any, *, expected_dimension: int) -> list[float]:
    if isinstance(raw, Mapping) and "values" in raw:
        raw = raw.get("values")
    if not isinstance(raw, list) or len(raw) != expected_dimension:
        raise GeminiDenseFallbackError(
            "GEMINI_EMBEDDING_DIMENSION_INVALID",
            f"expected {expected_dimension} values",
        )
    vector: list[float] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GeminiDenseFallbackError(
                "GEMINI_EMBEDDING_VALUE_INVALID", "embedding values must be numeric"
            )
        number = float(value)
        if not math.isfinite(number):
            raise GeminiDenseFallbackError(
                "GEMINI_EMBEDDING_VALUE_INVALID", "embedding values must be finite"
            )
        vector.append(number)
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm <= 0.0:
        raise GeminiDenseFallbackError(
            "GEMINI_EMBEDDING_NORM_INVALID", "embedding norm must be positive"
        )
    # Gemini Embedding 2 auto-normalizes non-default dimensions. Keep provider output
    # unchanged; only reject pathological values rather than silently altering its space.
    if not 0.90 <= norm <= 1.10:
        raise GeminiDenseFallbackError(
            "GEMINI_EMBEDDING_NORM_INVALID",
            f"expected provider-normalized vector, observed norm={norm:.6f}",
        )
    return vector


def parse_embed_content_response(
    payload: Mapping[str, Any], *, expected_dimension: int = GEMINI_DIMENSION
) -> list[float]:
    embedding = payload.get("embedding")
    if embedding is None:
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and len(embeddings) == 1:
            embedding = embeddings[0]
    if embedding is None:
        raise GeminiDenseFallbackError(
            "GEMINI_RESPONSE_INVALID", "embedContent response contains no embedding"
        )
    return _parse_embedding_values(embedding, expected_dimension=expected_dimension)


def parse_batch_embed_response(
    payload: Mapping[str, Any], *, expected_count: int, expected_dimension: int = GEMINI_DIMENSION
) -> list[list[float]]:
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        raise GeminiDenseFallbackError(
            "GEMINI_BATCH_RESPONSE_INVALID",
            f"expected {expected_count} embeddings",
        )
    return [
        _parse_embedding_values(item, expected_dimension=expected_dimension)
        for item in embeddings
    ]


class GeminiEmbeddingClient:
    def __init__(self, config: GeminiEmbeddingConfig) -> None:
        if not config.api_key.strip():
            raise GeminiDenseFallbackError(
                "GEMINI_API_KEY_MISSING", "GEMINI_API_KEY is required"
            )
        if config.model != GEMINI_MODEL:
            raise GeminiDenseFallbackError(
                "GEMINI_MODEL_MISMATCH", f"expected model {GEMINI_MODEL}"
            )
        if config.output_dimension != GEMINI_DIMENSION:
            raise GeminiDenseFallbackError(
                "GEMINI_DIMENSION_MISMATCH", f"expected dimension {GEMINI_DIMENSION}"
            )
        self.config = config

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.config.api_key,
        }

    def embed_query(self, query: str) -> list[float]:
        return self.embed_text(format_retrieval_query(query))

    def embed_document(self, text: str, *, title: str | None = None) -> list[float]:
        return self.embed_text(format_retrieval_document(text, title=title))

    def embed_text(self, formatted_text: str) -> list[float]:
        response = httpx.post(
            _embedding_url(self.config),
            headers=self._headers(),
            json={
                "content": {"parts": [{"text": normalize_text(formatted_text)}]},
                "output_dimensionality": self.config.output_dimension,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise GeminiDenseFallbackError(
                "GEMINI_RESPONSE_INVALID", "Gemini response must be an object"
            )
        return parse_embed_content_response(
            payload, expected_dimension=self.config.output_dimension
        )

    def embed_documents(self, sections: Sequence[SectionInput]) -> list[list[float]]:
        if not sections:
            raise GeminiDenseFallbackError(
                "GEMINI_BATCH_INPUT_INVALID", "at least one section is required"
            )
        requests: list[dict[str, Any]] = []
        for section in sections:
            title = section.payload.get("title") if isinstance(section.payload, Mapping) else None
            formatted = format_retrieval_document(
                section.text,
                title=str(title) if isinstance(title, str) else None,
            )
            requests.append(
                {
                    "model": f"models/{self.config.model}",
                    "content": {"parts": [{"text": formatted}]},
                    "output_dimensionality": self.config.output_dimension,
                }
            )
        response = httpx.post(
            _embedding_url(self.config, batch=True),
            headers=self._headers(),
            json={"requests": requests},
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise GeminiDenseFallbackError(
                "GEMINI_BATCH_RESPONSE_INVALID", "Gemini batch response must be an object"
            )
        return parse_batch_embed_response(
            payload,
            expected_count=len(sections),
            expected_dimension=self.config.output_dimension,
        )


def deterministic_point_id(section_id: str) -> str:
    identity = f"{GEMINI_MODEL}\n{normalize_text(section_id)}"
    return str(uuid.uuid5(GEMINI_POINT_NAMESPACE, identity))


def build_gemini_qdrant_points(
    sections: Sequence[SectionInput], vectors: Sequence[Sequence[float]]
) -> list[dict[str, Any]]:
    if len(sections) != len(vectors):
        raise GeminiDenseFallbackError(
            "GEMINI_POINT_COUNT_MISMATCH", "section/vector count mismatch"
        )
    points: list[dict[str, Any]] = []
    for section, vector in zip(sections, vectors, strict=True):
        numeric = _parse_embedding_values(
            list(vector), expected_dimension=GEMINI_DIMENSION
        )
        payload = {
            **dict(section.payload),
            "section_id": section.section_id,
            "release_id": M26_GEMINI_CANDIDATE_RELEASE_ID,
            "source_commit_sha": M26_GEMINI_CANDIDATE_SOURCE_SHA,
            "admission_sha256": M26_GEMINI_CANDIDATE_ADMISSION_SHA256,
            "text_sha256": hashlib.sha256(section.text.encode("utf-8")).hexdigest(),
            "embedding_model": GEMINI_MODEL,
            "embedding_provider": GEMINI_PROVIDER,
            "embedding_task_intent": GEMINI_DOCUMENT_TASK_INTENT,
            "embedding_prompt_contract": "gemini_embedding_2_asymmetric_retrieval_v1",
            "vector_dimension": GEMINI_DIMENSION,
            "vector_name": GEMINI_VECTOR_NAME,
            "canonical_knowledge": False,
            "candidate_release_eligible": True,
            "production_authority": False,
        }
        points.append(
            {
                "id": deterministic_point_id(section.section_id),
                "vector": {GEMINI_VECTOR_NAME: numeric},
                "payload": payload,
            }
        )
    return points


def qdrant_collection_create_payload() -> dict[str, Any]:
    return {
        "vectors": {
            GEMINI_VECTOR_NAME: {
                "size": GEMINI_DIMENSION,
                "distance": GEMINI_DISTANCE,
            }
        }
    }


def _qdrant_search_url(base_url: str, collection: str) -> str:
    return f"{base_url.rstrip('/')}/collections/{quote(collection, safe='')}/points/search"


def candidate_identity_filter(config: GeminiDenseConfig) -> dict[str, Any]:
    return {
        "must": [
            {"key": "release_id", "match": {"value": config.expected_release_id}},
            {
                "key": "source_commit_sha",
                "match": {"value": config.expected_source_sha},
            },
            {
                "key": "admission_sha256",
                "match": {"value": config.expected_admission_sha256},
            },
            {"key": "candidate_release_eligible", "match": {"value": True}},
            {"key": "production_authority", "match": {"value": False}},
            {"key": "embedding_provider", "match": {"value": GEMINI_PROVIDER}},
            {"key": "embedding_model", "match": {"value": GEMINI_MODEL}},
            {"key": "vector_dimension", "match": {"value": GEMINI_DIMENSION}},
        ]
    }


def _validate_dense_config(config: GeminiDenseConfig) -> None:
    if not config.qdrant_url.strip() or not config.qdrant_api_key.strip():
        raise GeminiDenseFallbackError(
            "GEMINI_QDRANT_CONFIG_MISSING", "Qdrant URL and read API key are required"
        )
    if config.qdrant_collection != M26_GEMINI_COLLECTION:
        raise GeminiDenseFallbackError(
            "GEMINI_COLLECTION_MISMATCH",
            "Gemini fallback must use the frozen separate candidate collection",
        )
    if config.primary_qdrant_collection and (
        config.qdrant_collection == config.primary_qdrant_collection
    ):
        raise GeminiDenseFallbackError(
            "GEMINI_VECTOR_SPACE_COLLISION",
            "Gemini and Cloudflare BGE vectors must never share a collection",
        )
    if config.expected_release_id != M26_GEMINI_CANDIDATE_RELEASE_ID:
        raise GeminiDenseFallbackError(
            "GEMINI_RELEASE_MISMATCH", "Gemini fallback is candidate-release scoped"
        )


def _validate_candidate_payload(payload: Mapping[str, Any], config: GeminiDenseConfig) -> None:
    expected = {
        "release_id": config.expected_release_id,
        "source_commit_sha": config.expected_source_sha,
        "admission_sha256": config.expected_admission_sha256,
        "candidate_release_eligible": True,
        "production_authority": False,
        "embedding_provider": GEMINI_PROVIDER,
        "embedding_model": GEMINI_MODEL,
        "vector_dimension": GEMINI_DIMENSION,
        "vector_name": GEMINI_VECTOR_NAME,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise GeminiDenseFallbackError(
                "GEMINI_QDRANT_PAYLOAD_IDENTITY_MISMATCH",
                f"Gemini Qdrant payload identity mismatch: {key}",
            )
    text_sha = str(payload.get("text_sha256", ""))
    if len(text_sha) != 64 or any(ch not in "0123456789abcdef" for ch in text_sha):
        raise GeminiDenseFallbackError(
            "GEMINI_QDRANT_PAYLOAD_IDENTITY_MISMATCH",
            "Gemini Qdrant payload text digest is invalid",
        )


class GeminiQdrantDenseChannel:
    """Read-only Gemini query embedding + isolated Qdrant dense retrieval channel."""

    def __init__(self, config: GeminiDenseConfig) -> None:
        _validate_dense_config(config)
        self.config = config
        self.client = GeminiEmbeddingClient(config.embedding)

    def search(self, *, question: str, bundle: Any, top_k: int) -> dict[str, Any]:
        release_id = str(getattr(bundle, "release_id", ""))
        if release_id != self.config.expected_release_id:
            raise GeminiDenseFallbackError(
                "GEMINI_BUNDLE_RELEASE_MISMATCH",
                "Gemini dense query bundle is not the frozen candidate release",
            )
        vector = self.client.embed_query(question)
        response = httpx.post(
            _qdrant_search_url(self.config.qdrant_url, self.config.qdrant_collection),
            headers={
                "api-key": self.config.qdrant_api_key,
                "Content-Type": "application/json",
            },
            json={
                "vector": {"name": self.config.vector_name, "vector": vector},
                "limit": max(1, min(top_k, 20)),
                "filter": candidate_identity_filter(self.config),
                "with_payload": [
                    "concept_id",
                    "section_id",
                    "source_id",
                    "release_id",
                    "source_commit_sha",
                    "admission_sha256",
                    "candidate_release_eligible",
                    "production_authority",
                    "text_sha256",
                    "embedding_provider",
                    "embedding_model",
                    "embedding_task_intent",
                    "vector_dimension",
                    "vector_name",
                ],
                "with_vector": False,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("result"), list):
            raise GeminiDenseFallbackError(
                "GEMINI_QDRANT_RESPONSE_INVALID", "Qdrant response shape"
            )
        candidates: list[dict[str, Any]] = []
        for raw in payload["result"]:
            if not isinstance(raw, Mapping):
                continue
            point_payload = raw.get("payload")
            if not isinstance(point_payload, Mapping):
                continue
            _validate_candidate_payload(point_payload, self.config)
            section_id = str(point_payload.get("section_id", "")).strip()
            if not section_id:
                continue
            score = raw.get("score", 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            candidates.append(
                {
                    "channel": "dense",
                    "section_id": section_id,
                    "concept_id": str(
                        point_payload.get("concept_id")
                        or point_payload.get("article_node_id")
                        or ""
                    ),
                    "score": round(float(score), 6),
                    "point_id_sha256": hashlib.sha256(
                        str(raw.get("id", "")).encode("utf-8")
                    ).hexdigest(),
                    "payload_release_id": str(point_payload.get("release_id", "")),
                    "payload_text_sha256": str(point_payload.get("text_sha256", "")),
                }
            )
        manifest_sha = str(getattr(bundle, "manifest_sha256", ""))
        return {
            "backend_identity": {
                "backend": "qdrant_gemini_dense_read_only",
                "dense_provider": GEMINI_PROVIDER,
                "dense_model": GEMINI_MODEL,
                "dense_dimension": GEMINI_DIMENSION,
                "embedding_task_intent": GEMINI_QUERY_TASK_INTENT,
                "embedding_prompt_contract": "gemini_embedding_2_asymmetric_retrieval_v1",
                "qdrant_collection": self.config.qdrant_collection,
                "qdrant_url_sha256": hashlib.sha256(
                    self.config.qdrant_url.rstrip("/").encode("utf-8")
                ).hexdigest(),
                "vector_name": self.config.vector_name,
                "release_id": release_id,
                "manifest_sha256": manifest_sha,
                "remote": True,
                "vectors_persisted": False,
                "identity_filter": candidate_identity_filter(self.config),
                "identity_checked": True,
                "production_authority": False,
            },
            "candidates": candidates[:top_k],
        }


def canonical_manifest_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-engine-m26-gemini-index-manifest/v1",
        "release_id": M26_GEMINI_CANDIDATE_RELEASE_ID,
        "source_commit_sha": M26_GEMINI_CANDIDATE_SOURCE_SHA,
        "admission_sha256": M26_GEMINI_CANDIDATE_ADMISSION_SHA256,
        "source_count": M26_GEMINI_CANDIDATE_SOURCE_COUNT,
        "expected_point_count": M26_GEMINI_CANDIDATE_POINT_COUNT,
        "source_pr_head": M26_GEMINI_SOURCE_PR_HEAD,
        "semantic_inputs_sha256": M26_GEMINI_SEMANTIC_INPUTS_SHA256,
        "lexical_documents_sha256": M26_GEMINI_LEXICAL_DOCUMENTS_SHA256,
        "source_index_sha256": M26_GEMINI_SOURCE_INDEX_SHA256,
        "primary_bge_collection": M26_BGE_PRIMARY_COLLECTION,
        "provider": GEMINI_PROVIDER,
        "model": GEMINI_MODEL,
        "dimension": GEMINI_DIMENSION,
        "document_task_intent": GEMINI_DOCUMENT_TASK_INTENT,
        "query_task_intent": GEMINI_QUERY_TASK_INTENT,
        "api_task_type_parameter": None,
        "prompt_contract": {
            "query": "task: search result | query: {content}",
            "document": "title: {title-or-none} | text: {content}",
        },
        "collection": M26_GEMINI_COLLECTION,
        "vector_name": GEMINI_VECTOR_NAME,
        "distance": GEMINI_DISTANCE,
        "candidate_release_eligible": True,
        "production_authority": False,
        "separate_from_cloudflare_bge_collection": True,
    }
