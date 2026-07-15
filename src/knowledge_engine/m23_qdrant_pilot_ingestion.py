from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    CLOUDFLARE_PROVIDER,
    QDRANT_DISTANCE,
    QDRANT_VECTOR_NAME,
    VECTOR_DIMENSION,
    deterministic_point_id,
)

EXPECTED_EVIDENCE_SHA256 = (
    "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
)
EXPECTED_SEMANTIC_ARTIFACT_ID = (
    "semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d"
)
EXPECTED_AUTHORITY_CONTRACT_SHA256 = (
    "c28a5d3503b24358c240283cfa1b4629c3e0bfeb6c854f72725481ff4c4a1941"
)
EXPECTED_DOCUMENT_COUNT = 107
EXPECTED_VECTOR_BYTES = EXPECTED_DOCUMENT_COUNT * VECTOR_DIMENSION * 4
QDRANT_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
BLOCKED_COLLECTION = "llamaindex_demo_hybrid"
SOURCE_MEMBERSHIP = "evaluation-only-pending-proposal"
PAYLOAD_SCHEMA = "knowledge-engine-m23-qdrant-payload/v1"
MANIFEST_SCHEMA = "knowledge-engine-m23-qdrant-ingestion-manifest/v1"
POINTS_SCHEMA = "knowledge-engine-m23-qdrant-points/v1"
RECEIPT_SCHEMA = "knowledge-engine-m23-qdrant-dry-run-receipt/v1"
CONTRACT_SCHEMA = "knowledge-engine-m23-qdrant-ingestion-contract/v1"
PILOT_RELEASE_SCHEMA = "knowledge-engine-m23-pilot-release-descriptor/v1"

REQUIRED_PAYLOAD_FIELDS = (
    "payload_schema_version",
    "section_id",
    "article_id",
    "document_id",
    "concept_id",
    "source_path",
    "source_sha256",
    "text_sha256",
    "audience",
    "source_membership",
    "release_id",
    "release_manifest_sha256",
    "graph_node_id",
    "embedding_provider",
    "embedding_model",
    "vector_dimension",
    "vector_name",
    "canonical_knowledge",
    "candidate_release_eligible",
    "production_authority",
)

_REQUIRED_ARCHIVE_FILES = {
    "benchmark-suite.json",
    "run-receipt.json",
    "pilot-document-vectors.f32",
    "semantic-artifact/semantic-metadata.json",
    "semantic-artifact/semantic-vectors.f32",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_string(value: Any, label: str, maximum: int = 1_000) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"M23-INGEST-101 {label} must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise IntegrityError(f"M23-INGEST-102 {label} is empty or too long")
    return candidate


def _sha256(value: Any, label: str) -> str:
    candidate = _required_string(value, label, 64)
    if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise IntegrityError(f"M23-INGEST-103 {label} must be lowercase SHA-256")
    return candidate


def _git_sha(value: Any, label: str) -> str:
    candidate = _required_string(value, label, 40)
    if len(candidate) != 40 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise IntegrityError(f"M23-INGEST-104 {label} must be lowercase git SHA")
    return candidate


def _self_digest(value: Mapping[str, Any], field: str, label: str) -> str:
    expected = _sha256(value.get(field), f"{label}.{field}")
    payload = dict(value)
    payload.pop(field, None)
    if canonical_sha256(payload) != expected:
        raise IntegrityError(f"M23-INGEST-105 {label} self-digest mismatch")
    return expected


def _read_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M23-INGEST-106 invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"M23-INGEST-107 {label} root must be an object")
    return value


def _archive_root(names: Sequence[str]) -> str:
    files = [name for name in names if name and not name.endswith("/")]
    roots = {name.split("/", 1)[0] for name in files if "/" in name}
    if len(roots) != 1 or any("/" not in name for name in files):
        raise IntegrityError("M23-INGEST-108 evidence ZIP must have exactly one root")
    return next(iter(roots))


def _receipt_files(
    archive: zipfile.ZipFile, root: str, receipt: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    files = receipt.get("files")
    if not isinstance(files, Mapping) or not files:
        raise IntegrityError("M23-INGEST-109 run receipt has no file manifest")
    validated: dict[str, dict[str, Any]] = {}
    for raw_name, raw_expected in files.items():
        name = _required_string(raw_name, "receipt.files key", 500)
        if name.startswith("/") or ".." in Path(name).parts or name == "run-receipt.json":
            raise IntegrityError("M23-INGEST-110 unsafe or circular receipt file path")
        if not isinstance(raw_expected, Mapping):
            raise IntegrityError("M23-INGEST-111 receipt file entry must be an object")
        expected_sha = _sha256(
            raw_expected.get("sha256"), f"receipt.files[{name}].sha256"
        )
        expected_bytes = raw_expected.get("bytes")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise IntegrityError(
                "M23-INGEST-112 receipt file byte count must be non-negative"
            )
        try:
            data = archive.read(f"{root}/{name}")
        except KeyError as exc:
            raise IntegrityError(f"M23-INGEST-113 receipt file missing: {name}") from exc
        if bytes_sha256(data) != expected_sha or len(data) != expected_bytes:
            raise IntegrityError(f"M23-INGEST-114 receipt file mismatch: {name}")
        validated[name] = {"sha256": expected_sha, "bytes": expected_bytes}

    actual = {
        name.split("/", 1)[1]
        for name in archive.namelist()
        if name and not name.endswith("/") and name != f"{root}/run-receipt.json"
    }
    if actual != set(validated):
        missing = sorted(set(validated) - actual)
        extra = sorted(actual - set(validated))
        raise IntegrityError(
            f"M23-INGEST-115 archive/receipt coverage mismatch; missing={missing}, extra={extra}"
        )
    if not (_REQUIRED_ARCHIVE_FILES - {"run-receipt.json"}) <= set(validated):
        raise IntegrityError("M23-INGEST-116 evidence ZIP lacks required ingestion files")
    return dict(sorted(validated.items()))


def _validate_receipt(receipt: Mapping[str, Any]) -> None:
    if "receipt_sha256" in receipt:
        _self_digest(receipt, "receipt_sha256", "run receipt")
    for field in (
        "qdrant_write",
        "r2_mutation",
        "pointer_mutation",
        "source_write",
        "traffic_change",
        "production_authority",
    ):
        if receipt.get(field) is True:
            raise IntegrityError(f"M23-INGEST-117 source receipt carries forbidden {field}")


def load_authority_contract(
    path: Path, *, expected_sha256: str = EXPECTED_AUTHORITY_CONTRACT_SHA256
) -> dict[str, Any]:
    raw = _read_json_bytes(path.read_bytes(), "authority contract")
    digest = _self_digest(raw, "contract_sha256", "authority contract")
    if digest != _sha256(expected_sha256, "expected authority contract SHA-256"):
        raise IntegrityError("M23-INGEST-118 unexpected authority contract")
    qdrant = raw.get("qdrant")
    adoption = raw.get("source_adoption")
    if not isinstance(qdrant, Mapping) or not isinstance(adoption, Mapping):
        raise IntegrityError("M23-INGEST-119 authority contract lacks qdrant/source adoption")
    if qdrant.get("collection") != QDRANT_COLLECTION:
        raise IntegrityError("M23-INGEST-120 wrong Qdrant collection")
    if qdrant.get("blocked_collection") != BLOCKED_COLLECTION:
        raise IntegrityError("M23-INGEST-121 unrelated collection guard missing")
    if qdrant.get("vector_name") != QDRANT_VECTOR_NAME:
        raise IntegrityError("M23-INGEST-122 wrong named vector")
    if (
        qdrant.get("dimension") != VECTOR_DIMENSION
        or qdrant.get("distance") != QDRANT_DISTANCE
    ):
        raise IntegrityError("M23-INGEST-123 Qdrant vector contract mismatch")
    if tuple(qdrant.get("payload_fields", ())) != REQUIRED_PAYLOAD_FIELDS:
        raise IntegrityError("M23-INGEST-124 Qdrant payload field contract mismatch")
    if (
        qdrant.get("first_write_authorized") is not False
        or qdrant.get("write_default") != "deny"
    ):
        raise IntegrityError("M23-INGEST-125 authority contract must deny writes")
    if adoption.get("lane") != SOURCE_MEMBERSHIP:
        raise IntegrityError("M23-INGEST-126 source adoption lane mismatch")
    if adoption.get("pending_proposal_point_count") != EXPECTED_DOCUMENT_COUNT:
        raise IntegrityError("M23-INGEST-127 pending point count mismatch")
    if any(
        adoption.get(field) is not False
        for field in (
            "source_merge_authorized",
            "pending_canonical_knowledge",
            "pending_candidate_release_eligible",
            "pending_production_authority",
        )
    ):
        raise IntegrityError("M23-INGEST-128 pending proposal authority must remain false")
    if adoption.get("candidate_requires_canonical_rebuild") is not True:
        raise IntegrityError("M23-INGEST-129 Source adoption must require full rebuild")
    authority = raw.get("authority")
    if not isinstance(authority, Mapping) or any(
        value is not False for value in authority.values()
    ):
        raise IntegrityError("M23-INGEST-130 protected mutation authority must be false")
    return raw


def validate_ingestion_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != CONTRACT_SCHEMA or raw.get("milestone") != "M23.6.2":
        raise IntegrityError("M23-INGEST-131 unsupported ingestion contract")
    _self_digest(raw, "contract_sha256", "ingestion contract")
    identities = raw.get("identities")
    qdrant = raw.get("qdrant")
    source = raw.get("source_membership")
    outputs = raw.get("outputs")
    authority = raw.get("authority")
    if not all(
        isinstance(item, Mapping)
        for item in (identities, qdrant, source, outputs, authority)
    ):
        raise IntegrityError("M23-INGEST-132 ingestion contract sections must be objects")
    _git_sha(identities.get("engine_entry_sha"), "engine_entry_sha")
    _git_sha(identities.get("source_sha"), "source_sha")
    _git_sha(identities.get("foundation_sha"), "foundation_sha")
    if identities.get("evidence_zip_sha256") != EXPECTED_EVIDENCE_SHA256:
        raise IntegrityError("M23-INGEST-133 ingestion contract evidence mismatch")
    if identities.get("semantic_artifact_id") != EXPECTED_SEMANTIC_ARTIFACT_ID:
        raise IntegrityError("M23-INGEST-134 ingestion contract semantic artifact mismatch")
    if identities.get("authority_contract_sha256") != EXPECTED_AUTHORITY_CONTRACT_SHA256:
        raise IntegrityError("M23-INGEST-135 ingestion contract authority mismatch")
    if qdrant != {
        "blocked_collection": BLOCKED_COLLECTION,
        "collection": QDRANT_COLLECTION,
        "dimension": VECTOR_DIMENSION,
        "distance": QDRANT_DISTANCE,
        "payload_fields": list(REQUIRED_PAYLOAD_FIELDS),
        "point_count": EXPECTED_DOCUMENT_COUNT,
        "vector_name": QDRANT_VECTOR_NAME,
        "write_authorized": False,
    }:
        raise IntegrityError("M23-INGEST-136 ingestion Qdrant contract mismatch")
    if (
        source.get("membership") != SOURCE_MEMBERSHIP
        or source.get("point_count") != EXPECTED_DOCUMENT_COUNT
    ):
        raise IntegrityError("M23-INGEST-137 ingestion membership mismatch")
    if source.get("rebuild_after_adoption") is not True:
        raise IntegrityError("M23-INGEST-138 rebuild-after-adoption must be true")
    if set(outputs) != {"dry_run_receipt", "ingestion_manifest", "qdrant_points"}:
        raise IntegrityError("M23-INGEST-139 output contract mismatch")
    if any(value is not False for value in authority.values()):
        raise IntegrityError("M23-INGEST-140 ingestion contract authority must be false")
    return dict(raw)


def _validate_suite(
    raw: Mapping[str, Any], authority: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if raw.get("read_only") is not True or raw.get("production_authority") is not False:
        raise IntegrityError("M23-INGEST-141 benchmark suite must be read-only/non-production")
    documents = raw.get("documents")
    if not isinstance(documents, list) or len(documents) != EXPECTED_DOCUMENT_COUNT:
        raise IntegrityError("M23-INGEST-142 benchmark suite must contain exactly 107 documents")
    identities = raw.get("identities")
    if not isinstance(identities, Mapping):
        raise IntegrityError("M23-INGEST-143 benchmark suite lacks identities")
    expected = authority["identities"]
    if identities.get("source_commit_sha") != expected.get("source_commit_sha"):
        raise IntegrityError("M23-INGEST-144 benchmark Source identity mismatch")
    if identities.get("foundation_commit_sha") != expected.get("foundation_commit_sha"):
        raise IntegrityError("M23-INGEST-145 benchmark Foundation identity mismatch")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(documents):
        if not isinstance(item, Mapping):
            raise IntegrityError("M23-INGEST-146 benchmark document must be an object")
        section_id = _required_string(
            item.get("section_id"), f"documents[{index}].section_id", 500
        )
        if section_id in seen:
            raise IntegrityError(f"M23-INGEST-147 duplicate section_id: {section_id}")
        seen.add(section_id)
        text = _required_string(item.get("text"), f"documents[{index}].text", 200_000)
        source_sha = _sha256(
            item.get("source_sha256"), f"documents[{index}].source_sha256"
        )
        validated.append(
            {
                "row": index,
                "section_id": section_id,
                "concept_id": _required_string(
                    item.get("concept_id"), f"documents[{index}].concept_id", 500
                ),
                "language": _required_string(
                    item.get("language"), f"documents[{index}].language", 40
                ),
                "title": _required_string(
                    item.get("title"), f"documents[{index}].title", 2_000
                ),
                "text": text,
                "text_sha256": bytes_sha256(text.encode("utf-8")),
                "source_path": _required_string(
                    item.get("source_path"), f"documents[{index}].source_path", 2_000
                ),
                "source_sha256": source_sha,
                "audience": _required_string(
                    item.get("audience"), f"documents[{index}].audience", 80
                ),
            }
        )
    return validated


def _unpack_vectors(data: bytes, row_count: int) -> list[tuple[float, ...]]:
    expected = row_count * VECTOR_DIMENSION * 4
    if len(data) != expected:
        raise IntegrityError(
            f"M23-INGEST-148 vector byte length mismatch: {len(data)} != {expected}"
        )
    values = struct.unpack(f"<{row_count * VECTOR_DIMENSION}f", data)
    vectors: list[tuple[float, ...]] = []
    for row in range(row_count):
        vector = tuple(values[row * VECTOR_DIMENSION : (row + 1) * VECTOR_DIMENSION])
        if not all(math.isfinite(value) for value in vector):
            raise IntegrityError(f"M23-INGEST-149 vector row {row} contains non-finite value")
        norm = math.sqrt(math.fsum(value * value for value in vector))
        if abs(norm - 1.0) > 1e-4:
            raise IntegrityError(f"M23-INGEST-150 vector row {row} is not L2-normalized")
        vectors.append(vector)
    return vectors


def _validate_semantic_metadata(
    metadata: Mapping[str, Any],
    semantic_vectors: bytes,
    suite: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    *,
    expected_artifact_id: str,
) -> None:
    if metadata.get("schema_version") != "knowledge-engine-semantic/v2":
        raise IntegrityError("M23-INGEST-151 unsupported semantic metadata schema")
    if metadata.get("artifact_id") != expected_artifact_id:
        raise IntegrityError("M23-INGEST-152 semantic artifact ID mismatch")
    if metadata.get("immutable") is not True or metadata.get("read_only") is not True:
        raise IntegrityError("M23-INGEST-153 semantic artifact must be immutable/read-only")
    if metadata.get("production_authority") is not False:
        raise IntegrityError("M23-INGEST-154 semantic artifact cannot carry production authority")
    _self_digest(metadata, "metadata_sha256", "semantic metadata")
    if metadata.get("benchmark_suite_sha256") != canonical_sha256(suite):
        raise IntegrityError("M23-INGEST-155 semantic benchmark digest mismatch")
    model = metadata.get("model")
    vectors = metadata.get("vectors")
    semantic_documents = metadata.get("documents")
    if (
        not isinstance(model, Mapping)
        or not isinstance(vectors, Mapping)
        or not isinstance(semantic_documents, list)
    ):
        raise IntegrityError("M23-INGEST-156 incomplete semantic metadata")
    expected_model = {
        "provider": CLOUDFLARE_PROVIDER,
        "model_id": CLOUDFLARE_MODEL,
        "dimension": VECTOR_DIMENSION,
        "dtype": "float32",
        "endianness": "little",
        "normalized": True,
    }
    for key, value in expected_model.items():
        if model.get(key) != value:
            raise IntegrityError(f"M23-INGEST-157 semantic model mismatch: {key}")
    expected_vectors = {
        "filename": "semantic-vectors.f32",
        "sha256": bytes_sha256(semantic_vectors),
        "byte_length": EXPECTED_VECTOR_BYTES,
        "row_count": EXPECTED_DOCUMENT_COUNT,
        "dimension": VECTOR_DIMENSION,
        "dtype": "float32",
        "endianness": "little",
        "normalized": True,
    }
    if dict(vectors) != expected_vectors:
        raise IntegrityError("M23-INGEST-158 semantic vector metadata mismatch")
    if len(semantic_documents) != EXPECTED_DOCUMENT_COUNT:
        raise IntegrityError("M23-INGEST-159 semantic document count mismatch")
    for row, (semantic, document) in enumerate(
        zip(semantic_documents, documents, strict=True)
    ):
        expected = {
            "row": row,
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        if semantic != expected:
            raise IntegrityError(f"M23-INGEST-160 semantic row order mismatch at row {row}")


def _article_id(section_id: str) -> str:
    if "/chunk-" in section_id:
        return section_id.split("/chunk-", 1)[0]
    if "#" in section_id:
        return section_id.split("#", 1)[0]
    return section_id


def _release_descriptor(
    *,
    builder_engine_sha: str,
    authority: Mapping[str, Any],
    suite_sha256: str,
    vector_sha256: str,
    semantic_metadata_sha256: str,
    expected_evidence_sha256: str,
    expected_semantic_artifact_id: str,
) -> dict[str, Any]:
    base = {
        "schema_version": PILOT_RELEASE_SCHEMA,
        "builder_engine_commit_sha": _git_sha(builder_engine_sha, "builder_engine_sha"),
        "source_commit_sha": authority["identities"]["source_commit_sha"],
        "foundation_commit_sha": authority["identities"]["foundation_commit_sha"],
        "source_membership": SOURCE_MEMBERSHIP,
        "evidence_zip_sha256": expected_evidence_sha256,
        "benchmark_suite_sha256": suite_sha256,
        "document_vectors_sha256": vector_sha256,
        "semantic_metadata_sha256": semantic_metadata_sha256,
        "semantic_artifact_id": expected_semantic_artifact_id,
        "authority_contract_sha256": authority["contract_sha256"],
        "embedding_provider": CLOUDFLARE_PROVIDER,
        "embedding_model": CLOUDFLARE_MODEL,
        "vector_dimension": VECTOR_DIMENSION,
        "qdrant_collection": QDRANT_COLLECTION,
        "qdrant_vector_name": QDRANT_VECTOR_NAME,
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    digest = canonical_sha256(base)
    return {
        **base,
        "release_id": f"m23pilot-{digest[:24]}",
        "release_manifest_sha256": digest,
    }


def decide_content_action(existing_content_hash: str | None, planned_content_hash: str) -> str:
    planned = _sha256(planned_content_hash, "planned_content_hash")
    if existing_content_hash is None:
        return "insert"
    existing = _sha256(existing_content_hash, "existing_content_hash")
    return "skip" if existing == planned else "replace"


def build_dry_run(
    *,
    evidence_zip: Path,
    authority_contract_path: Path,
    builder_engine_sha: str,
    expected_evidence_sha256: str = EXPECTED_EVIDENCE_SHA256,
    expected_semantic_artifact_id: str = EXPECTED_SEMANTIC_ARTIFACT_ID,
    expected_authority_contract_sha256: str = EXPECTED_AUTHORITY_CONTRACT_SHA256,
) -> dict[str, Any]:
    evidence_sha = file_sha256(evidence_zip)
    if evidence_sha != _sha256(expected_evidence_sha256, "expected_evidence_sha256"):
        raise IntegrityError("M23-INGEST-161 evidence ZIP digest mismatch")
    authority = load_authority_contract(
        authority_contract_path, expected_sha256=expected_authority_contract_sha256
    )
    with zipfile.ZipFile(evidence_zip) as archive:
        root = _archive_root(archive.namelist())
        receipt = _read_json_bytes(
            archive.read(f"{root}/run-receipt.json"), "run-receipt.json"
        )
        _validate_receipt(receipt)
        files = _receipt_files(archive, root, receipt)
        suite = _read_json_bytes(
            archive.read(f"{root}/benchmark-suite.json"), "benchmark-suite.json"
        )
        documents = _validate_suite(suite, authority)
        vector_bytes = archive.read(f"{root}/pilot-document-vectors.f32")
        semantic_metadata_bytes = archive.read(
            f"{root}/semantic-artifact/semantic-metadata.json"
        )
        semantic_metadata = _read_json_bytes(
            semantic_metadata_bytes, "semantic-artifact/semantic-metadata.json"
        )
        semantic_vectors = archive.read(
            f"{root}/semantic-artifact/semantic-vectors.f32"
        )

    if len(vector_bytes) != EXPECTED_VECTOR_BYTES:
        raise IntegrityError("M23-INGEST-162 frozen document vector byte count mismatch")
    if vector_bytes != semantic_vectors:
        raise IntegrityError("M23-INGEST-163 pilot and semantic vector files differ")
    vectors = _unpack_vectors(vector_bytes, EXPECTED_DOCUMENT_COUNT)
    _validate_semantic_metadata(
        semantic_metadata,
        semantic_vectors,
        suite,
        documents,
        expected_artifact_id=expected_semantic_artifact_id,
    )
    suite_sha = canonical_sha256(suite)
    vector_sha = bytes_sha256(vector_bytes)
    semantic_metadata_sha = bytes_sha256(semantic_metadata_bytes)
    release = _release_descriptor(
        builder_engine_sha=builder_engine_sha,
        authority=authority,
        suite_sha256=suite_sha,
        vector_sha256=vector_sha,
        semantic_metadata_sha256=semantic_metadata_sha,
        expected_evidence_sha256=evidence_sha,
        expected_semantic_artifact_id=expected_semantic_artifact_id,
    )

    point_summaries: list[dict[str, Any]] = []
    qdrant_points: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for document, vector in zip(documents, vectors, strict=True):
        row = document["row"]
        offset = row * VECTOR_DIMENSION * 4
        vector_row_bytes = vector_bytes[offset : offset + VECTOR_DIMENSION * 4]
        vector_row_sha = bytes_sha256(vector_row_bytes)
        point_id = deterministic_point_id(document["section_id"])
        if point_id in seen_ids:
            raise IntegrityError("M23-INGEST-164 duplicate deterministic point ID")
        seen_ids.add(point_id)
        article_id = _article_id(document["section_id"])
        payload = {
            "payload_schema_version": PAYLOAD_SCHEMA,
            "section_id": document["section_id"],
            "article_id": article_id,
            "document_id": article_id,
            "concept_id": document["concept_id"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
            "text_sha256": document["text_sha256"],
            "audience": document["audience"],
            "source_membership": SOURCE_MEMBERSHIP,
            "release_id": release["release_id"],
            "release_manifest_sha256": release["release_manifest_sha256"],
            "graph_node_id": document["concept_id"],
            "embedding_provider": CLOUDFLARE_PROVIDER,
            "embedding_model": CLOUDFLARE_MODEL,
            "vector_dimension": VECTOR_DIMENSION,
            "vector_name": QDRANT_VECTOR_NAME,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        if tuple(payload) != REQUIRED_PAYLOAD_FIELDS:
            raise IntegrityError("M23-INGEST-165 payload field ordering drift")
        content_hash = canonical_sha256(
            {"point_id": point_id, "payload": payload, "vector_sha256": vector_row_sha}
        )
        point_summaries.append(
            {
                "row": row,
                "section_id": document["section_id"],
                "point_id": point_id,
                "vector_byte_offset": offset,
                "vector_byte_length": VECTOR_DIMENSION * 4,
                "vector_sha256": vector_row_sha,
                "content_hash_sha256": content_hash,
                "source_membership": SOURCE_MEMBERSHIP,
                "canonical_knowledge": False,
                "candidate_release_eligible": False,
                "production_authority": False,
            }
        )
        qdrant_points.append(
            {
                "id": point_id,
                "vector": {QDRANT_VECTOR_NAME: list(vector)},
                "payload": payload,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "milestone": "M23.6.2",
        "mode": "offline-dry-run",
        "builder_engine_commit_sha": builder_engine_sha,
        "source_evidence": {
            "archive_root": root,
            "evidence_zip_sha256": evidence_sha,
            "receipt_files": files,
            "benchmark_suite_sha256": suite_sha,
            "document_vectors_filename": "pilot-document-vectors.f32",
            "document_vectors_sha256": vector_sha,
            "document_vectors_byte_length": len(vector_bytes),
            "semantic_metadata_sha256": semantic_metadata_sha,
            "semantic_artifact_id": expected_semantic_artifact_id,
        },
        "authority_contract_sha256": authority["contract_sha256"],
        "release": release,
        "source_membership": {
            "membership": SOURCE_MEMBERSHIP,
            "point_count": EXPECTED_DOCUMENT_COUNT,
            "all_points_noncanonical": True,
            "candidate_release_eligible": False,
            "production_authority": False,
            "full_rebuild_required_after_source_adoption": True,
        },
        "qdrant": {
            "collection": QDRANT_COLLECTION,
            "blocked_collection": BLOCKED_COLLECTION,
            "vector_name": QDRANT_VECTOR_NAME,
            "dimension": VECTOR_DIMENSION,
            "distance": QDRANT_DISTANCE,
            "point_count": EXPECTED_DOCUMENT_COUNT,
            "payload_schema_version": PAYLOAD_SCHEMA,
            "payload_fields": list(REQUIRED_PAYLOAD_FIELDS),
            "write_authorized": False,
        },
        "content_hash_policy": {
            "missing": "insert",
            "equal": "skip",
            "different": "replace",
            "network_read_required_by_m23_6_2": False,
        },
        "points": point_summaries,
        "authority": {
            "network_calls": False,
            "cloudflare_calls": False,
            "qdrant_reads": False,
            "qdrant_writes": False,
            "r2_mutation": False,
            "pointer_mutation": False,
            "source_mutation": False,
            "production_traffic_change": False,
            "production_authority": False,
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    points_document = {
        "schema_version": POINTS_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "collection": QDRANT_COLLECTION,
        "vector_name": QDRANT_VECTOR_NAME,
        "point_count": EXPECTED_DOCUMENT_COUNT,
        "points": qdrant_points,
        "qdrant_write_authorized": False,
        "production_authority": False,
    }
    return {"manifest": manifest, "points": points_document}


def write_dry_run(output_dir: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    target = Path(output_dir)
    if target.exists():
        raise IntegrityError(f"M23-INGEST-166 immutable output already exists: {target}")
    manifest = result.get("manifest")
    points = result.get("points")
    if not isinstance(manifest, Mapping) or not isinstance(points, Mapping):
        raise IntegrityError("M23-INGEST-167 dry-run result is incomplete")
    manifest_bytes = canonical_bytes(manifest)
    points_bytes = canonical_bytes(points)
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "outputs": {
            "ingestion-manifest.json": {
                "sha256": bytes_sha256(manifest_bytes),
                "bytes": len(manifest_bytes),
            },
            "qdrant-points.json": {
                "sha256": bytes_sha256(points_bytes),
                "bytes": len(points_bytes),
            },
        },
        "point_count": EXPECTED_DOCUMENT_COUNT,
        "network_calls": 0,
        "cloudflare_calls": 0,
        "qdrant_reads": 0,
        "qdrant_writes": 0,
        "r2_mutation": False,
        "pointer_mutation": False,
        "source_mutation": False,
        "production_traffic_change": False,
        "production_authority": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_bytes = canonical_bytes(receipt)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        outputs = {
            "ingestion-manifest.json": manifest_bytes,
            "qdrant-points.json": points_bytes,
            "dry-run-receipt.json": receipt_bytes,
        }
        for name, data in outputs.items():
            path = staging / name
            path.write_bytes(data)
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
            path.chmod(0o444)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return receipt
