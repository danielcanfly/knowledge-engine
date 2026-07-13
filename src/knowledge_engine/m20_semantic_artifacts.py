from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .m20_embedding_contract import (
    ContractError,
    canonical_sha256,
    validate_benchmark_suite,
    validate_provider_contract,
)

SEMANTIC_METADATA_SCHEMA = "knowledge-engine-semantic/v2"
SEMANTIC_VECTOR_FILENAME = "semantic-vectors.f32"
SEMANTIC_METADATA_FILENAME = "semantic-metadata.json"
FLOAT32_DTYPE = "float32"
LITTLE_ENDIAN = "little"
MAX_SEMANTIC_ROWS = 1_000_000
MAX_VECTOR_DIMENSION = 65_536
UNIT_NORM_TOLERANCE = 1e-4
_GIT_SHA_LENGTH = 40


class SemanticArtifactError(ContractError):
    """Raised when a semantic artifact is invalid or unsafe to create."""


def _git_sha(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _GIT_SHA_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SemanticArtifactError(f"{label} must be a lowercase 40-character git SHA")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _metadata_digest(metadata: Mapping[str, Any]) -> str:
    payload = dict(metadata)
    payload.pop("metadata_sha256", None)
    return canonical_sha256(payload)


def _float32_vector(raw: Sequence[float], dimension: int, label: str) -> tuple[float, ...]:
    if isinstance(raw, (str, bytes, bytearray)) or len(raw) != dimension:
        raise SemanticArtifactError(f"{label} must contain exactly {dimension} values")
    values: list[float] = []
    for index, item in enumerate(raw):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SemanticArtifactError(f"{label}[{index}] must be numeric")
        value = struct.unpack("<f", struct.pack("<f", float(item)))[0]
        if not math.isfinite(value):
            raise SemanticArtifactError(f"{label}[{index}] must be finite")
        values.append(value)
    norm = math.sqrt(math.fsum(value * value for value in values))
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise SemanticArtifactError(f"{label} must be L2-normalized; norm={norm:.8f}")
    return tuple(values)


def _validate_identities(
    suite: Mapping[str, Any],
    contract: Mapping[str, Any],
    builder_engine_sha: str,
) -> dict[str, str]:
    suite_identities = suite["identities"]
    contract_identities = contract["identities"]
    expected_contract = {
        "engine_commit_sha": suite_identities["engine_baseline_sha"],
        "source_commit_sha": suite_identities["source_commit_sha"],
        "foundation_commit_sha": suite_identities["foundation_commit_sha"],
    }
    if contract_identities != expected_contract:
        raise SemanticArtifactError("provider contract and benchmark suite identities do not match")
    return {
        "builder_engine_commit_sha": _git_sha(builder_engine_sha, "builder_engine_commit_sha"),
        "provider_contract_engine_commit_sha": contract_identities["engine_commit_sha"],
        "source_commit_sha": contract_identities["source_commit_sha"],
        "foundation_commit_sha": contract_identities["foundation_commit_sha"],
    }


def _model_metadata(contract: Mapping[str, Any]) -> dict[str, Any]:
    model = contract["model"]
    tokenizer = contract["tokenizer"]
    preprocessing = contract["preprocessing"]
    if preprocessing["normalization"] != "l2":
        raise SemanticArtifactError("M20.2 canonical vectors require L2 normalization")
    dimension = model["vector_dimension"]
    if not isinstance(dimension, int) or not 1 <= dimension <= MAX_VECTOR_DIMENSION:
        raise SemanticArtifactError("model vector dimension is outside M20.2 bounds")
    return {
        "provider": contract["provider"]["name"],
        "provider_implementation": contract["provider"]["implementation"],
        "model_id": model["id"],
        **({"model_revision": model["revision"]} if "revision" in model else {}),
        **({"model_digest_sha256": model["digest_sha256"]} if "digest_sha256" in model else {}),
        "tokenizer_id": tokenizer["id"],
        **({"tokenizer_revision": tokenizer["revision"]} if "revision" in tokenizer else {}),
        **(
            {"tokenizer_digest_sha256": tokenizer["digest_sha256"]}
            if "digest_sha256" in tokenizer
            else {}
        ),
        "dimension": dimension,
        "dtype": FLOAT32_DTYPE,
        "endianness": LITTLE_ENDIAN,
        "normalized": True,
        "pooling": preprocessing["pooling"],
        "input_template": preprocessing["input_template"],
        "query_template": preprocessing["query_template"],
        "maximum_input_length": preprocessing["maximum_input_length"],
        "truncation": preprocessing["truncation"],
        "unicode_normalization": preprocessing["unicode_normalization"],
    }


def build_semantic_artifacts(
    suite_raw: Mapping[str, Any],
    provider_contract_raw: Mapping[str, Any],
    vectors: Mapping[str, Sequence[float]],
    output_dir: str | Path,
    *,
    builder_engine_sha: str,
) -> dict[str, Any]:
    suite = validate_benchmark_suite(suite_raw)
    contract = validate_provider_contract(provider_contract_raw)
    if suite["read_only"] is not True or suite["production_authority"] is not False:
        raise SemanticArtifactError("benchmark suite must remain read-only and non-production")
    if contract["authority"] != {
        "canonical_source": "markdown",
        "vectors_are_derived": True,
        "runtime_network_required": False,
        "write_back": False,
        "production_authority": False,
    }:
        raise SemanticArtifactError("provider authority must remain derived and read-only")

    identities = _validate_identities(suite, contract, builder_engine_sha)
    model = _model_metadata(contract)
    documents = suite["documents"]
    if not 1 <= len(documents) <= MAX_SEMANTIC_ROWS:
        raise SemanticArtifactError("semantic row count is outside M20.2 bounds")
    section_ids = [document["section_id"] for document in documents]
    if set(vectors) != set(section_ids):
        missing = sorted(set(section_ids) - set(vectors))
        extra = sorted(set(vectors) - set(section_ids))
        raise SemanticArtifactError(f"vector coverage mismatch; missing={missing}, extra={extra}")

    binary = bytearray()
    rows: list[dict[str, Any]] = []
    dimension = model["dimension"]
    for row, document in enumerate(documents):
        section_id = document["section_id"]
        vector = _float32_vector(vectors[section_id], dimension, f"vector[{section_id}]")
        binary.extend(struct.pack(f"<{dimension}f", *vector))
        rows.append(
            {
                "row": row,
                "concept_id": document["concept_id"],
                "section_id": section_id,
                "language": document["language"],
                "audience": document["audience"],
                "source_path": document["source_path"],
                "source_sha256": document["source_sha256"],
            }
        )

    vector_bytes = bytes(binary)
    vectors_sha256 = _sha256_bytes(vector_bytes)
    provider_contract_sha256 = canonical_sha256(contract)
    benchmark_suite_sha256 = canonical_sha256(suite)
    artifact_id = "semantic-" + canonical_sha256(
        {
            "identities": identities,
            "provider_contract_sha256": provider_contract_sha256,
            "benchmark_suite_sha256": benchmark_suite_sha256,
            "vectors_sha256": vectors_sha256,
        }
    )
    metadata: dict[str, Any] = {
        "schema_version": SEMANTIC_METADATA_SCHEMA,
        "artifact_id": artifact_id,
        "immutable": True,
        "read_only": True,
        "production_authority": False,
        "identities": identities,
        "provider_contract_sha256": provider_contract_sha256,
        "benchmark_suite_sha256": benchmark_suite_sha256,
        "model": model,
        "vectors": {
            "filename": SEMANTIC_VECTOR_FILENAME,
            "sha256": vectors_sha256,
            "byte_length": len(vector_bytes),
            "row_count": len(rows),
            "dimension": dimension,
            "dtype": FLOAT32_DTYPE,
            "endianness": LITTLE_ENDIAN,
            "normalized": True,
        },
        "documents": rows,
    }
    metadata["metadata_sha256"] = _metadata_digest(metadata)
    metadata_bytes = (
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    target = Path(output_dir)
    if target.exists():
        raise SemanticArtifactError(f"immutable output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        vector_path = staging / SEMANTIC_VECTOR_FILENAME
        metadata_path = staging / SEMANTIC_METADATA_FILENAME
        vector_path.write_bytes(vector_bytes)
        metadata_path.write_bytes(metadata_bytes)
        with vector_path.open("rb") as handle:
            os.fsync(handle.fileno())
        with metadata_path.open("rb") as handle:
            os.fsync(handle.fileno())
        vector_path.chmod(0o444)
        metadata_path.chmod(0o444)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return metadata


def _read_metadata(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SemanticArtifactError("semantic metadata root must be an object")
    return value


def verify_semantic_artifacts(
    metadata_path: str | Path,
    vectors_path: str | Path,
    suite_raw: Mapping[str, Any],
    provider_contract_raw: Mapping[str, Any],
    *,
    expected_builder_engine_sha: str | None = None,
) -> dict[str, Any]:
    suite = validate_benchmark_suite(suite_raw)
    contract = validate_provider_contract(provider_contract_raw)
    metadata = _read_metadata(metadata_path)
    if metadata.get("schema_version") != SEMANTIC_METADATA_SCHEMA:
        raise SemanticArtifactError("unsupported semantic metadata schema")
    if metadata.get("immutable") is not True or metadata.get("read_only") is not True:
        raise SemanticArtifactError("semantic artifacts must be immutable and read-only")
    if metadata.get("production_authority") is not False:
        raise SemanticArtifactError("semantic artifacts cannot carry production authority")
    if metadata.get("metadata_sha256") != _metadata_digest(metadata):
        raise SemanticArtifactError("semantic metadata digest mismatch")

    expected_identities = _validate_identities(
        suite,
        contract,
        metadata.get("identities", {}).get("builder_engine_commit_sha", ""),
    )
    if metadata.get("identities") != expected_identities:
        raise SemanticArtifactError("semantic artifact identity mismatch")
    if expected_builder_engine_sha is not None:
        expected = _git_sha(expected_builder_engine_sha, "expected_builder_engine_sha")
        if expected_identities["builder_engine_commit_sha"] != expected:
            raise SemanticArtifactError("semantic artifact builder Engine SHA mismatch")
    if metadata.get("provider_contract_sha256") != canonical_sha256(contract):
        raise SemanticArtifactError("provider contract digest mismatch")
    if metadata.get("benchmark_suite_sha256") != canonical_sha256(suite):
        raise SemanticArtifactError("benchmark suite digest mismatch")
    if metadata.get("model") != _model_metadata(contract):
        raise SemanticArtifactError("semantic artifact model metadata mismatch")

    vectors_metadata = metadata.get("vectors")
    if not isinstance(vectors_metadata, dict):
        raise SemanticArtifactError("semantic vectors metadata must be an object")
    vector_bytes = Path(vectors_path).read_bytes()
    if vectors_metadata.get("filename") != SEMANTIC_VECTOR_FILENAME:
        raise SemanticArtifactError("semantic vector filename mismatch")
    if vectors_metadata.get("sha256") != _sha256_bytes(vector_bytes):
        raise SemanticArtifactError("semantic vector digest mismatch")
    dimension = metadata["model"]["dimension"]
    expected_bytes = len(suite["documents"]) * dimension * 4
    if len(vector_bytes) != expected_bytes or vectors_metadata.get("byte_length") != expected_bytes:
        raise SemanticArtifactError("semantic vector byte length mismatch")
    if vectors_metadata != {
        "filename": SEMANTIC_VECTOR_FILENAME,
        "sha256": _sha256_bytes(vector_bytes),
        "byte_length": expected_bytes,
        "row_count": len(suite["documents"]),
        "dimension": dimension,
        "dtype": FLOAT32_DTYPE,
        "endianness": LITTLE_ENDIAN,
        "normalized": True,
    }:
        raise SemanticArtifactError("semantic vectors metadata fields are inconsistent")

    expected_documents = [
        {
            "row": row,
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        for row, document in enumerate(suite["documents"])
    ]
    if metadata.get("documents") != expected_documents:
        raise SemanticArtifactError("semantic row-to-section metadata mismatch")

    values = struct.iter_unpack(f"<{dimension}f", vector_bytes)
    row_count = 0
    for row_count, unpacked in enumerate(values, start=1):
        if any(not math.isfinite(value) for value in unpacked):
            raise SemanticArtifactError("semantic vector contains non-finite values")
        norm = math.sqrt(math.fsum(value * value for value in unpacked))
        if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
            raise SemanticArtifactError(
                f"semantic vector row {row_count - 1} is not normalized; norm={norm:.8f}"
            )
    if row_count != len(expected_documents):
        raise SemanticArtifactError("semantic vector row count mismatch")
    return metadata


def flat_cosine_rank(
    metadata: Mapping[str, Any],
    vector_bytes: bytes,
    query_vector: Sequence[float],
    *,
    allowed_audiences: set[str],
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise SemanticArtifactError("limit must be an integer between 1 and 100")
    if not allowed_audiences or any(
        not isinstance(audience, str) or not audience for audience in allowed_audiences
    ):
        raise SemanticArtifactError("allowed_audiences must contain non-empty strings")
    model = metadata.get("model")
    documents = metadata.get("documents")
    if not isinstance(model, Mapping) or not isinstance(documents, list):
        raise SemanticArtifactError("verified semantic metadata is required")
    dimension = model.get("dimension")
    if not isinstance(dimension, int):
        raise SemanticArtifactError("semantic dimension is invalid")
    query = _float32_vector(query_vector, dimension, "query_vector")
    if len(vector_bytes) != len(documents) * dimension * 4:
        raise SemanticArtifactError("semantic vector byte length mismatch")

    results: list[dict[str, Any]] = []
    for document in documents:
        if document["audience"] not in allowed_audiences:
            continue
        row = document["row"]
        offset = row * dimension * 4
        vector = struct.unpack_from(f"<{dimension}f", vector_bytes, offset)
        score = math.fsum(left * right for left, right in zip(query, vector, strict=True))
        results.append(
            {
                "row": row,
                "section_id": document["section_id"],
                "concept_id": document["concept_id"],
                "audience": document["audience"],
                "score": round(score, 8),
            }
        )
    results.sort(key=lambda item: (-item["score"], item["section_id"]))
    return results[:limit]


def load_verified_semantic_artifacts(
    artifact_dir: str | Path,
    suite_raw: Mapping[str, Any],
    provider_contract_raw: Mapping[str, Any],
    *,
    expected_builder_engine_sha: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    root = Path(artifact_dir)
    metadata_path = root / SEMANTIC_METADATA_FILENAME
    vectors_path = root / SEMANTIC_VECTOR_FILENAME
    metadata = verify_semantic_artifacts(
        metadata_path,
        vectors_path,
        suite_raw,
        provider_contract_raw,
        expected_builder_engine_sha=expected_builder_engine_sha,
    )
    return metadata, vectors_path.read_bytes()


__all__ = [
    "FLOAT32_DTYPE",
    "LITTLE_ENDIAN",
    "SEMANTIC_METADATA_FILENAME",
    "SEMANTIC_METADATA_SCHEMA",
    "SEMANTIC_VECTOR_FILENAME",
    "SemanticArtifactError",
    "build_semantic_artifacts",
    "flat_cosine_rank",
    "load_verified_semantic_artifacts",
    "verify_semantic_artifacts",
]
