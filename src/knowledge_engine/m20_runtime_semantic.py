from __future__ import annotations

import hashlib
import json
import math
import mmap
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from .errors import IntegrityError
from .m20_embedding_contract import canonical_sha256
from .m20_semantic_artifacts import (
    FLOAT32_DTYPE,
    LITTLE_ENDIAN,
    SEMANTIC_METADATA_SCHEMA,
    SEMANTIC_VECTOR_FILENAME,
    UNIT_NORM_TOLERANCE,
)

MAX_DIAGNOSTIC_RESULTS = 20
MAX_RUNTIME_ROWS = 1_000_000
MAX_RUNTIME_DIMENSION = 65_536
_GIT_SHA_LENGTH = 40


class SemanticRuntimeError(IntegrityError):
    """Runtime semantic artifact verification or diagnostic query failed."""


def _git_sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _GIT_SHA_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SemanticRuntimeError(f"{label} must be a lowercase 40-character git SHA")
    return value


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise SemanticRuntimeError(f"cannot read semantic artifact: {path.name}") from exc


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticRuntimeError("semantic metadata is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SemanticRuntimeError("semantic metadata must be an object")
    return value


def _metadata_digest(metadata: Mapping[str, Any]) -> str:
    payload = dict(metadata)
    payload.pop("metadata_sha256", None)
    return canonical_sha256(payload)


def _normalised_float32_vector(
    raw: Sequence[float], dimension: int, label: str
) -> tuple[float, ...]:
    if isinstance(raw, (str, bytes, bytearray)) or len(raw) != dimension:
        raise SemanticRuntimeError(f"{label} must contain exactly {dimension} values")
    values: list[float] = []
    for index, item in enumerate(raw):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SemanticRuntimeError(f"{label}[{index}] must be numeric")
        value = struct.unpack("<f", struct.pack("<f", float(item)))[0]
        if not math.isfinite(value):
            raise SemanticRuntimeError(f"{label}[{index}] must be finite")
        values.append(value)
    norm = math.sqrt(math.fsum(value * value for value in values))
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise SemanticRuntimeError(f"{label} must be L2-normalized; norm={norm:.8f}")
    return tuple(values)


def _lexical_documents(lexical_index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    documents = lexical_index.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SemanticRuntimeError("lexical index must contain section documents")
    by_section: dict[str, Mapping[str, Any]] = {}
    for item in documents:
        if not isinstance(item, Mapping):
            raise SemanticRuntimeError("lexical document must be an object")
        section_id = item.get("section_id")
        if not isinstance(section_id, str) or not section_id:
            raise SemanticRuntimeError("lexical document section_id is missing")
        if section_id in by_section:
            raise SemanticRuntimeError(f"duplicate lexical section ID: {section_id}")
        by_section[section_id] = item
    return by_section


def _verify_model(
    model: Any,
    *,
    expected_model_id: str | None,
    expected_dimension: int | None,
) -> dict[str, Any]:
    if not isinstance(model, dict):
        raise SemanticRuntimeError("semantic model metadata must be an object")
    required_strings = (
        "provider",
        "provider_implementation",
        "model_id",
        "tokenizer_id",
        "pooling",
        "input_template",
        "query_template",
        "truncation",
        "unicode_normalization",
    )
    for field in required_strings:
        if not isinstance(model.get(field), str) or not model[field]:
            raise SemanticRuntimeError(f"semantic model {field} is missing")
    dimension = model.get("dimension")
    if (
        not isinstance(dimension, int)
        or isinstance(dimension, bool)
        or not 1 <= dimension <= MAX_RUNTIME_DIMENSION
    ):
        raise SemanticRuntimeError("semantic vector dimension is outside Runtime bounds")
    if model.get("dtype") != FLOAT32_DTYPE:
        raise SemanticRuntimeError("semantic Runtime requires float32 vectors")
    if model.get("endianness") != LITTLE_ENDIAN:
        raise SemanticRuntimeError("semantic Runtime requires little-endian vectors")
    if model.get("normalized") is not True:
        raise SemanticRuntimeError("semantic Runtime requires normalized vectors")
    maximum_input_length = model.get("maximum_input_length")
    if not isinstance(maximum_input_length, int) or not 1 <= maximum_input_length <= 1_000_000:
        raise SemanticRuntimeError("semantic model maximum_input_length is invalid")
    if expected_model_id is not None and model["model_id"] != expected_model_id:
        raise SemanticRuntimeError("semantic model ID does not match Runtime policy")
    if expected_dimension is not None and dimension != expected_dimension:
        raise SemanticRuntimeError("semantic dimension does not match Runtime policy")
    return model


def verify_runtime_semantic_artifacts(
    metadata_path: str | Path,
    vectors_path: str | Path,
    *,
    manifest: Mapping[str, Any],
    lexical_index: Mapping[str, Any],
    expected_model_id: str | None = None,
    expected_dimension: int | None = None,
) -> dict[str, Any]:
    metadata_file = Path(metadata_path)
    vector_file = Path(vectors_path)
    metadata = _load_metadata(metadata_file)
    if metadata.get("schema_version") != SEMANTIC_METADATA_SCHEMA:
        raise SemanticRuntimeError("unsupported semantic metadata schema")
    if metadata.get("immutable") is not True or metadata.get("read_only") is not True:
        raise SemanticRuntimeError("semantic artifacts must be immutable and read-only")
    if metadata.get("production_authority") is not False:
        raise SemanticRuntimeError("semantic artifacts cannot carry production authority")
    if metadata.get("metadata_sha256") != _metadata_digest(metadata):
        raise SemanticRuntimeError("semantic metadata digest mismatch")

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise SemanticRuntimeError("release manifest source identity is missing")
    identities = metadata.get("identities")
    if not isinstance(identities, dict):
        raise SemanticRuntimeError("semantic artifact identities are missing")
    for field in (
        "builder_engine_commit_sha",
        "provider_contract_engine_commit_sha",
        "source_commit_sha",
        "foundation_commit_sha",
    ):
        _git_sha(identities.get(field), f"semantic identities.{field}")
    if identities["source_commit_sha"] != source.get("commit_sha"):
        raise SemanticRuntimeError("semantic Source identity does not match release manifest")
    if identities["foundation_commit_sha"] != source.get("foundation_commit_sha"):
        raise SemanticRuntimeError("semantic Foundation identity does not match release manifest")
    for digest_field in ("provider_contract_sha256", "benchmark_suite_sha256"):
        value = metadata.get(digest_field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise SemanticRuntimeError(f"semantic {digest_field} is invalid")

    model = _verify_model(
        metadata.get("model"),
        expected_model_id=expected_model_id,
        expected_dimension=expected_dimension,
    )
    dimension = model["dimension"]
    vectors = metadata.get("vectors")
    if not isinstance(vectors, dict):
        raise SemanticRuntimeError("semantic vectors metadata must be an object")
    if vectors.get("filename") != SEMANTIC_VECTOR_FILENAME:
        raise SemanticRuntimeError("semantic vector filename mismatch")
    row_count = vectors.get("row_count")
    byte_length = vectors.get("byte_length")
    if (
        not isinstance(row_count, int)
        or isinstance(row_count, bool)
        or not 1 <= row_count <= MAX_RUNTIME_ROWS
    ):
        raise SemanticRuntimeError("semantic row count is outside Runtime bounds")
    expected_bytes = row_count * dimension * 4
    try:
        actual_size = vector_file.stat().st_size
    except OSError as exc:
        raise SemanticRuntimeError("cannot stat semantic vector artifact") from exc
    if byte_length != expected_bytes or actual_size != expected_bytes:
        raise SemanticRuntimeError("semantic vector byte length mismatch")
    if vectors.get("dimension") != dimension:
        raise SemanticRuntimeError("semantic vector dimension metadata mismatch")
    if vectors.get("dtype") != FLOAT32_DTYPE or vectors.get("endianness") != LITTLE_ENDIAN:
        raise SemanticRuntimeError("semantic vector encoding metadata mismatch")
    if vectors.get("normalized") is not True:
        raise SemanticRuntimeError("semantic vectors must be normalized")
    if vectors.get("sha256") != _sha256_file(vector_file):
        raise SemanticRuntimeError("semantic vector digest mismatch")

    documents = metadata.get("documents")
    if not isinstance(documents, list) or len(documents) != row_count:
        raise SemanticRuntimeError("semantic document row count mismatch")
    lexical = _lexical_documents(lexical_index)
    semantic_ids: set[str] = set()
    for expected_row, document in enumerate(documents):
        if not isinstance(document, Mapping) or document.get("row") != expected_row:
            raise SemanticRuntimeError("semantic document rows must be contiguous and ordered")
        section_id = document.get("section_id")
        if not isinstance(section_id, str) or not section_id:
            raise SemanticRuntimeError("semantic section ID is missing")
        if section_id in semantic_ids:
            raise SemanticRuntimeError(f"duplicate semantic section ID: {section_id}")
        semantic_ids.add(section_id)
        lexical_document = lexical.get(section_id)
        if lexical_document is None:
            raise SemanticRuntimeError(
                f"semantic section does not exist in lexical index: {section_id}"
            )
        if document.get("concept_id") != lexical_document.get("concept_id"):
            raise SemanticRuntimeError(f"semantic concept identity mismatch: {section_id}")
        if document.get("audience") != lexical_document.get("audience"):
            raise SemanticRuntimeError(f"semantic audience mismatch: {section_id}")
        if document.get("source_path") != lexical_document.get("path"):
            raise SemanticRuntimeError(f"semantic source path mismatch: {section_id}")
        body = lexical_document.get("body")
        if not isinstance(body, str):
            raise SemanticRuntimeError(f"lexical section body is missing: {section_id}")
        expected_source_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if document.get("source_sha256") != expected_source_sha:
            raise SemanticRuntimeError(f"semantic source digest mismatch: {section_id}")
    if semantic_ids != set(lexical):
        missing = sorted(set(lexical) - semantic_ids)
        extra = sorted(semantic_ids - set(lexical))
        raise SemanticRuntimeError(
            f"semantic and lexical section coverage mismatch; missing={missing}, extra={extra}"
        )

    try:
        with vector_file.open("rb") as handle:
            mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                for row in range(row_count):
                    offset = row * dimension * 4
                    vector = struct.unpack_from(f"<{dimension}f", mapping, offset)
                    if any(not math.isfinite(value) for value in vector):
                        raise SemanticRuntimeError(
                            f"semantic vector row {row} contains non-finite values"
                        )
                    norm = math.sqrt(math.fsum(value * value for value in vector))
                    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
                        raise SemanticRuntimeError(
                            f"semantic vector row {row} is not normalized; norm={norm:.8f}"
                        )
            finally:
                mapping.close()
    except OSError as exc:
        raise SemanticRuntimeError("semantic vector memory-map verification failed") from exc
    return metadata


@dataclass
class SemanticRuntimeIndex:
    metadata: dict[str, Any]
    vector_path: Path
    _handle: BinaryIO
    _mapping: mmap.mmap

    @classmethod
    def open(
        cls,
        metadata_path: str | Path,
        vectors_path: str | Path,
        *,
        manifest: Mapping[str, Any],
        lexical_index: Mapping[str, Any],
        expected_model_id: str | None = None,
        expected_dimension: int | None = None,
    ) -> SemanticRuntimeIndex:
        metadata = verify_runtime_semantic_artifacts(
            metadata_path,
            vectors_path,
            manifest=manifest,
            lexical_index=lexical_index,
            expected_model_id=expected_model_id,
            expected_dimension=expected_dimension,
        )
        vector_path = Path(vectors_path)
        try:
            handle = vector_path.open("rb")
            mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        except OSError as exc:
            raise SemanticRuntimeError("semantic vector memory map failed") from exc
        return cls(metadata=metadata, vector_path=vector_path, _handle=handle, _mapping=mapping)

    def close(self) -> None:
        self._mapping.close()
        self._handle.close()

    def capability(self, *, diagnostic_enabled: bool) -> dict[str, Any]:
        vectors = self.metadata["vectors"]
        model = self.metadata["model"]
        return {
            "status": "ready",
            "memory_mapped": True,
            "diagnostic_enabled": diagnostic_enabled,
            "artifact_id": self.metadata["artifact_id"],
            "row_count": vectors["row_count"],
            "dimension": vectors["dimension"],
            "provider": model["provider"],
            "model_id": model["model_id"],
        }

    def rank(
        self,
        query_vector: Sequence[float],
        *,
        allowed_audiences: set[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_DIAGNOSTIC_RESULTS
        ):
            raise SemanticRuntimeError(
                f"limit must be an integer between 1 and {MAX_DIAGNOSTIC_RESULTS}"
            )
        if not allowed_audiences or any(
            not isinstance(audience, str) or not audience for audience in allowed_audiences
        ):
            raise SemanticRuntimeError("allowed_audiences must contain non-empty strings")
        dimension = self.metadata["vectors"]["dimension"]
        query = _normalised_float32_vector(query_vector, dimension, "query_vector")
        results: list[dict[str, Any]] = []
        for document in self.metadata["documents"]:
            if document["audience"] not in allowed_audiences:
                continue
            offset = document["row"] * dimension * 4
            vector = struct.unpack_from(f"<{dimension}f", self._mapping, offset)
            score = math.fsum(
                left * right for left, right in zip(query, vector, strict=True)
            )
            results.append(
                {
                    "row": document["row"],
                    "section_id": document["section_id"],
                    "concept_id": document["concept_id"],
                    "audience": document["audience"],
                    "score": round(score, 8),
                }
            )
        results.sort(key=lambda item: (-item["score"], item["section_id"]))
        return results[:limit]


__all__ = [
    "MAX_DIAGNOSTIC_RESULTS",
    "SemanticRuntimeError",
    "SemanticRuntimeIndex",
    "verify_runtime_semantic_artifacts",
]
