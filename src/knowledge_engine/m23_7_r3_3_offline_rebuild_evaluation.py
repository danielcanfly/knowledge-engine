from __future__ import annotations

import hashlib
import json
import math
import struct
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_repaired_ingestion_preview,
    compile_repaired_probe_plan,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-3-offline-rebuild-evaluation/v1"
REPORT_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-3-offline-rebuild-evaluation-report/v1"
)
CANDIDATE_SCHEMA_VERSION = "knowledge-engine-m23-7-r3-3-candidate-artifact/v1"
ENTRY_ENGINE_SHA = "2511269cb46cefd24c15636480e9592cdfcf8964"
IMPLEMENTATION_ISSUE = 487
PARENT_ISSUE = 474
R3_2_REPAIR_CONTRACT_SHA256 = (
    "9ed7a5bea7ce85aed67bf6f263c8b06420e1c67bd7cac62f9368f0f48c29c33e"
)
R3_2_RECONCILIATION_SHA = "2511269cb46cefd24c15636480e9592cdfcf8964"
EXPECTED_EVIDENCE_SHA256 = (
    "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
)
EXPECTED_SEMANTIC_ARTIFACT_ID = (
    "semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d"
)
EXPECTED_POINT_COUNT = 107
VECTOR_DIMENSION = 1024
SAMPLE_CAP = 8
TOP_K = 10
MIN_RECALL_AT_5 = 0.82
MIN_MRR_AT_10 = 0.68
MIN_NDCG_AT_10 = 0.72

_REQUIRED_FILES = {
    "benchmark-suite.json",
    "pilot-document-vectors.f32",
    "semantic-artifact/semantic-metadata.json",
    "semantic-artifact/semantic-vectors.f32",
}

_NDCG_BY_RANK = (
    1.0,
    0.6309297535714575,
    0.5,
    0.43067655807339306,
    0.38685280723454163,
    0.3562071871080222,
    0.3333333333333333,
    0.31546487678572877,
    0.3010299956639812,
    0.2890648263178879,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.3-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _string(value: Any, label: str, maximum: int) -> str:
    _require(isinstance(value, str), 103, f"{label} must be a string")
    text = value.strip()
    _require(bool(text) and len(text) <= maximum, 104, f"{label} is empty or too long")
    return text


def _sha256(value: Any, label: str) -> str:
    text = _string(value, label, 64)
    _require(
        len(text) == 64 and all(char in "0123456789abcdef" for char in text),
        105,
        f"{label} must be lowercase SHA-256",
    )
    return text


def _json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M23.7-R3.3-106 invalid JSON in {label}") from exc
    _require(isinstance(value, dict), 107, f"{label} root must be an object")
    return value


def _archive_root(names: Sequence[str]) -> str:
    files = [name for name in names if name and not name.endswith("/")]
    roots = {name.split("/", 1)[0] for name in files if "/" in name}
    _require(
        len(roots) == 1 and all("/" in name for name in files),
        108,
        "evidence ZIP must have exactly one root",
    )
    return next(iter(roots))


def _validate_self_digest(value: Mapping[str, Any], field: str, label: str) -> str:
    digest = _sha256(value.get(field), f"{label}.{field}")
    unsigned = dict(value)
    unsigned.pop(field, None)
    _require(canonical_sha256(unsigned) == digest, 109, f"{label} self-digest mismatch")
    return digest


def _validate_receipt(
    archive: zipfile.ZipFile,
    root: str,
    receipt: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if "receipt_sha256" in receipt:
        _validate_self_digest(receipt, "receipt_sha256", "run receipt")
    for field in (
        "qdrant_write",
        "r2_mutation",
        "pointer_mutation",
        "source_write",
        "traffic_change",
        "production_authority",
    ):
        _require(receipt.get(field) is not True, 110, f"receipt carries forbidden {field}")

    raw_files = _mapping(receipt.get("files"), "receipt.files")
    validated: dict[str, dict[str, Any]] = {}
    for raw_name, raw_expected in raw_files.items():
        name = _string(raw_name, "receipt file name", 500)
        _require(
            not name.startswith("/") and ".." not in Path(name).parts,
            111,
            "unsafe receipt file path",
        )
        expected = _mapping(raw_expected, f"receipt.files[{name}]")
        expected_sha = _sha256(expected.get("sha256"), f"receipt.files[{name}].sha256")
        expected_bytes = expected.get("bytes")
        _require(
            isinstance(expected_bytes, int) and expected_bytes >= 0,
            112,
            "receipt file byte count invalid",
        )
        try:
            data = archive.read(f"{root}/{name}")
        except KeyError as exc:
            raise IntegrityError(f"M23.7-R3.3-113 receipt file missing: {name}") from exc
        _require(
            hashlib.sha256(data).hexdigest() == expected_sha and len(data) == expected_bytes,
            114,
            f"receipt file mismatch: {name}",
        )
        validated[name] = {"sha256": expected_sha, "bytes": expected_bytes}

    actual = {
        name.split("/", 1)[1]
        for name in archive.namelist()
        if name and not name.endswith("/") and name != f"{root}/run-receipt.json"
    }
    _require(actual == set(validated), 115, "archive and receipt coverage differ")
    _require(_REQUIRED_FILES <= set(validated), 116, "required evidence files are missing")
    return dict(sorted(validated.items()))


def _validated_documents(suite: Mapping[str, Any]) -> list[dict[str, Any]]:
    _require(
        suite.get("read_only") is True and suite.get("production_authority") is False,
        117,
        "benchmark suite authority drifted",
    )
    raw_documents = _sequence(suite.get("documents"), "benchmark documents")
    _require(len(raw_documents) == EXPECTED_POINT_COUNT, 118, "document count drifted")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row, raw in enumerate(raw_documents):
        document = _mapping(raw, f"documents[{row}]")
        section_id = _string(document.get("section_id"), "section_id", 500)
        _require(section_id not in seen, 119, "duplicate section ID")
        seen.add(section_id)
        text = _string(document.get("text"), "text", 200_000)
        output.append(
            {
                "row": row,
                "section_id": section_id,
                "concept_id": _string(document.get("concept_id"), "concept_id", 500),
                "language": _string(document.get("language"), "language", 40),
                "title": _string(document.get("title"), "title", 2_000),
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_path": _string(document.get("source_path"), "source_path", 2_000),
                "source_sha256": _sha256(document.get("source_sha256"), "source_sha256"),
                "audience": _string(document.get("audience"), "audience", 80),
            }
        )
    return output


def _validate_vector(vector: Sequence[Any], label: str) -> list[float]:
    _require(len(vector) == VECTOR_DIMENSION, 120, f"{label} dimension drifted")
    values: list[float] = []
    for item in vector:
        _require(
            not isinstance(item, bool) and isinstance(item, int | float),
            121,
            f"{label} contains a non-number",
        )
        value = float(item)
        _require(math.isfinite(value), 122, f"{label} contains non-finite data")
        values.append(value)
    norm = math.sqrt(math.fsum(value * value for value in values))
    _require(abs(norm - 1.0) <= 1e-4, 123, f"{label} is not L2-normalized")
    return values


def _unpack_vectors(data: bytes) -> list[list[float]]:
    expected_bytes = EXPECTED_POINT_COUNT * VECTOR_DIMENSION * 4
    _require(len(data) == expected_bytes, 124, "document vector byte length drifted")
    values = struct.unpack(f"<{EXPECTED_POINT_COUNT * VECTOR_DIMENSION}f", data)
    vectors: list[list[float]] = []
    for row in range(EXPECTED_POINT_COUNT):
        start = row * VECTOR_DIMENSION
        vector = [float(value) for value in values[start : start + VECTOR_DIMENSION]]
        _validate_vector(vector, f"document vector row {row}")
        vectors.append(vector)
    return vectors


def _validate_semantic_metadata(
    metadata: Mapping[str, Any],
    semantic_vectors: bytes,
    suite: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
) -> None:
    _require(
        metadata.get("schema_version") == "knowledge-engine-semantic/v2",
        125,
        "semantic metadata schema drifted",
    )
    _require(
        metadata.get("artifact_id") == EXPECTED_SEMANTIC_ARTIFACT_ID,
        126,
        "semantic artifact identity drifted",
    )
    _require(
        metadata.get("immutable") is True
        and metadata.get("read_only") is True
        and metadata.get("production_authority") is False,
        127,
        "semantic metadata authority drifted",
    )
    _validate_self_digest(metadata, "metadata_sha256", "semantic metadata")
    _require(
        metadata.get("benchmark_suite_sha256") == canonical_sha256(suite),
        128,
        "semantic benchmark digest drifted",
    )
    model = _mapping(metadata.get("model"), "semantic model")
    _require(
        model.get("provider") == "cloudflare-workers-ai"
        and model.get("model_id") == "@cf/baai/bge-m3"
        and model.get("dimension") == VECTOR_DIMENSION
        and model.get("normalized") is True
        and model.get("query_template") == "{text}",
        129,
        "semantic model contract drifted",
    )
    vectors = _mapping(metadata.get("vectors"), "semantic vectors")
    _require(
        vectors.get("sha256") == hashlib.sha256(semantic_vectors).hexdigest()
        and vectors.get("row_count") == EXPECTED_POINT_COUNT
        and vectors.get("dimension") == VECTOR_DIMENSION
        and vectors.get("normalized") is True,
        130,
        "semantic vector metadata drifted",
    )
    semantic_documents = _sequence(metadata.get("documents"), "semantic documents")
    _require(len(semantic_documents) == EXPECTED_POINT_COUNT, 131, "semantic row count drifted")
    for row, (semantic_raw, document) in enumerate(
        zip(semantic_documents, documents, strict=True)
    ):
        semantic = _mapping(semantic_raw, f"semantic documents[{row}]")
        expected = {
            "row": row,
            "concept_id": document["concept_id"],
            "section_id": document["section_id"],
            "language": document["language"],
            "audience": document["audience"],
            "source_path": document["source_path"],
            "source_sha256": document["source_sha256"],
        }
        _require(dict(semantic) == expected, 132, f"semantic row binding drifted at {row}")


def _release_descriptor(suite_sha256: str, vector_sha256: str) -> dict[str, Any]:
    base = {
        "schema_version": "knowledge-engine-m23-7-r3-3-candidate-release/v1",
        "entry_engine_sha": ENTRY_ENGINE_SHA,
        "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        "benchmark_suite_sha256": suite_sha256,
        "document_vectors_sha256": vector_sha256,
        "repair_contract_sha256": R3_2_REPAIR_CONTRACT_SHA256,
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "point_count": EXPECTED_POINT_COUNT,
        "embedding_provider": "cloudflare-workers-ai",
        "embedding_model": "@cf/baai/bge-m3",
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": "default",
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    digest = canonical_sha256(base)
    return {
        **base,
        "release_id": f"m23r33-{digest[:24]}",
        "release_manifest_sha256": digest,
    }


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_2_reconciliation_merge_sha": R3_2_RECONCILIATION_SHA,
            "r3_2_repair_contract_sha256": R3_2_REPAIR_CONTRACT_SHA256,
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        },
        "rebuild": {
            "mode": "offline-no-write",
            "point_count": EXPECTED_POINT_COUNT,
            "payload_schema": PAYLOAD_SCHEMA_V2,
            "sample_count": SAMPLE_CAP,
            "sample_order": "eligible-point-id-ascending-first-eight",
            "embedding_model": "@cf/baai/bge-m3",
            "embedding_model_changed": False,
            "query_prefix_changed": False,
            "local_full_corpus_cosine": True,
            "top_k": TOP_K,
        },
        "thresholds": {
            "min_recall_at_5": MIN_RECALL_AT_5,
            "min_mrr_at_10": MIN_MRR_AT_10,
            "min_ndcg_at_10": MIN_NDCG_AT_10,
            "thresholds_changed": False,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "account_id_persisted": False,
            "service_url_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "qdrant_read_authorized": False,
            "qdrant_write_authorized": False,
            "qdrant_delete_authorized": False,
            "r2_mutation_authorized": False,
            "pointer_mutation_authorized": False,
            "source_mutation_authorized": False,
            "promotion_eligibility_granted": False,
        },
        "exit": {
            "pass_authorizes": "separately_governed_candidate_qdrant_reingestion",
            "live_acceptance_still_required": True,
            "retrieval_quality_blocker_cleared": False,
        },
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def load_frozen_evidence(path: Path) -> dict[str, Any]:
    evidence_sha = file_sha256(path)
    _require(evidence_sha == EXPECTED_EVIDENCE_SHA256, 133, "evidence ZIP identity drifted")
    with zipfile.ZipFile(path) as archive:
        root = _archive_root(archive.namelist())
        receipt = _json_bytes(archive.read(f"{root}/run-receipt.json"), "run receipt")
        receipt_files = _validate_receipt(archive, root, receipt)
        suite_bytes = archive.read(f"{root}/benchmark-suite.json")
        vector_bytes = archive.read(f"{root}/pilot-document-vectors.f32")
        semantic_bytes = archive.read(f"{root}/semantic-artifact/semantic-metadata.json")
        semantic_vectors = archive.read(f"{root}/semantic-artifact/semantic-vectors.f32")

    _require(vector_bytes == semantic_vectors, 134, "pilot and semantic vectors differ")
    suite = _json_bytes(suite_bytes, "benchmark suite")
    documents = _validated_documents(suite)
    vectors = _unpack_vectors(vector_bytes)
    semantic_metadata = _json_bytes(semantic_bytes, "semantic metadata")
    _validate_semantic_metadata(
        semantic_metadata,
        semantic_vectors,
        suite,
        documents,
    )
    return {
        "evidence_zip_sha256": evidence_sha,
        "archive_root": root,
        "receipt_files": receipt_files,
        "suite": suite,
        "benchmark_suite_sha256": canonical_sha256(suite),
        "documents": documents,
        "vectors": vectors,
        "document_vectors_sha256": hashlib.sha256(vector_bytes).hexdigest(),
        "semantic_metadata_sha256": hashlib.sha256(semantic_bytes).hexdigest(),
        "semantic_artifact_id": semantic_metadata["artifact_id"],
    }


def build_offline_candidate(path: Path) -> dict[str, Any]:
    inputs = load_frozen_evidence(path)
    release = _release_descriptor(
        inputs["benchmark_suite_sha256"],
        inputs["document_vectors_sha256"],
    )
    preview = build_repaired_ingestion_preview(
        inputs["documents"],
        inputs["vectors"],
        release=release,
        expected_point_count=EXPECTED_POINT_COUNT,
    )
    eligible = sorted(
        (
            point
            for point in preview["points"]
            if point["payload"]["source_membership"]
            == "evaluation-only-pending-proposal"
            and point["payload"]["canonical_knowledge"] is False
            and point["payload"]["candidate_release_eligible"] is False
            and point["payload"]["production_authority"] is False
        ),
        key=lambda point: point["id"],
    )
    _require(len(eligible) == EXPECTED_POINT_COUNT, 135, "eligible point count drifted")
    samples = eligible[:SAMPLE_CAP]
    _require(
        all(sample["payload"]["audience"] == "public" for sample in samples),
        136,
        "bounded sample audience drifted",
    )
    probes = compile_repaired_probe_plan(samples)
    _require(
        len({probe["query_text_sha256"] for probe in probes}) == SAMPLE_CAP,
        137,
        "repaired query identities collided",
    )

    candidate: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "mode": "offline-no-write-candidate",
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence": {
            "evidence_zip_sha256": inputs["evidence_zip_sha256"],
            "benchmark_suite_sha256": inputs["benchmark_suite_sha256"],
            "document_vectors_sha256": inputs["document_vectors_sha256"],
            "semantic_metadata_sha256": inputs["semantic_metadata_sha256"],
            "semantic_artifact_id": inputs["semantic_artifact_id"],
        },
        "release": release,
        "point_count": len(preview["points"]),
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "preview_sha256": preview["preview_sha256"],
        "points": preview["points"],
        "bindings": preview["bindings"],
        "probe_plan": probes,
        "authority": {
            "qdrant_read_dispatched": False,
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
        },
    }
    unsigned = dict(candidate)
    unsigned["probe_plan"] = [
        {key: value for key, value in probe.items() if key != "query_text"}
        for probe in candidate["probe_plan"]
    ]
    candidate["candidate_artifact_sha256"] = canonical_sha256(unsigned)
    return candidate


def _reciprocal_rank(target: str, ranked: Sequence[str]) -> float:
    for index, section_id in enumerate(ranked[:TOP_K], start=1):
        if section_id == target:
            return 1.0 / index
    return 0.0


def _ndcg(target: str, ranked: Sequence[str]) -> float:
    for index, section_id in enumerate(ranked[:TOP_K], start=1):
        if section_id == target:
            return _NDCG_BY_RANK[index - 1]
    return 0.0


def evaluate_offline_candidate(
    candidate: Mapping[str, Any],
    query_vectors: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    points = list(_sequence(candidate.get("points"), "candidate points"))
    probes = list(_sequence(candidate.get("probe_plan"), "probe plan"))
    _require(len(points) == EXPECTED_POINT_COUNT, 138, "candidate point count drifted")
    _require(len(probes) == SAMPLE_CAP, 139, "probe count drifted")
    _require(len(query_vectors) == SAMPLE_CAP, 140, "query vector count drifted")

    corpus: list[tuple[str, list[float]]] = []
    for index, raw_point in enumerate(points):
        point = _mapping(raw_point, f"points[{index}]")
        payload = _mapping(point.get("payload"), f"points[{index}].payload")
        section_id = _string(payload.get("section_id"), "section_id", 500)
        vectors = _mapping(point.get("vector"), f"points[{index}].vector")
        corpus.append((section_id, _validate_vector(vectors.get("default"), "point vector")))

    cases: list[dict[str, Any]] = []
    hubness: Counter[str] = Counter()
    for index, (raw_probe, raw_query_vector) in enumerate(
        zip(probes, query_vectors, strict=True)
    ):
        probe = _mapping(raw_probe, f"probes[{index}]")
        query_vector = _validate_vector(raw_query_vector, f"query vector {index}")
        scored = sorted(
            (
                (math.fsum(left * right for left, right in zip(query_vector, vector)), section_id)
                for section_id, vector in corpus
            ),
            key=lambda item: (-item[0], item[1]),
        )
        ranked_ids = [section_id for _, section_id in scored[:TOP_K]]
        hubness.update(ranked_ids)
        target = _string(probe.get("target_section_id"), "target_section_id", 500)
        target_rank = next(
            rank
            for rank, (_, section_id) in enumerate(scored, start=1)
            if section_id == target
        )
        target_score = scored[target_rank - 1][0]
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "query_text_sha256": probe["query_text_sha256"],
                "query_digest": probe["query_digest"],
                "target_section_id": target,
                "ranked_section_ids": ranked_ids,
                "target_rank": target_rank,
                "target_in_top_5": target in ranked_ids[:5],
                "reciprocal_rank_at_10": round(_reciprocal_rank(target, ranked_ids), 12),
                "ndcg_at_10": round(_ndcg(target, ranked_ids), 12),
                "target_cosine": round(target_score, 12),
                "top_cosine": round(scored[0][0], 12),
                "target_margin_from_top": round(scored[0][0] - target_score, 12),
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )

    recall_at_5 = round(sum(case["target_in_top_5"] for case in cases) / SAMPLE_CAP, 12)
    mrr_at_10 = round(
        math.fsum(case["reciprocal_rank_at_10"] for case in cases) / SAMPLE_CAP,
        12,
    )
    ndcg_at_10 = round(
        math.fsum(case["ndcg_at_10"] for case in cases) / SAMPLE_CAP,
        12,
    )
    gates = {
        "evidence_identity": candidate["evidence"]["evidence_zip_sha256"]
        == EXPECTED_EVIDENCE_SHA256,
        "semantic_artifact_identity": candidate["evidence"]["semantic_artifact_id"]
        == EXPECTED_SEMANTIC_ARTIFACT_ID,
        "point_count": len(points) == EXPECTED_POINT_COUNT,
        "payload_schema_v2": all(
            point["payload"]["payload_schema_version"] == PAYLOAD_SCHEMA_V2
            for point in points
        ),
        "query_identity_unique": len({case["query_text_sha256"] for case in cases})
        == SAMPLE_CAP,
        "recall_at_5": recall_at_5 >= MIN_RECALL_AT_5,
        "mrr_at_10": mrr_at_10 >= MIN_MRR_AT_10,
        "ndcg_at_10": ndcg_at_10 >= MIN_NDCG_AT_10,
        "qdrant_io_zero": True,
        "protected_mutations_zero": True,
    }
    status = (
        "pass_offline_rebuild_evaluation"
        if all(gates.values())
        else "rejected_offline_rebuild_evaluation"
    )
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "status": status,
        "contract_sha256": canonical_contract()["contract_sha256"],
        "candidate_artifact_sha256": candidate["candidate_artifact_sha256"],
        "candidate_preview_sha256": candidate["preview_sha256"],
        "evidence": dict(candidate["evidence"]),
        "release": dict(candidate["release"]),
        "metrics": {
            "recall_at_5": recall_at_5,
            "mrr_at_10": mrr_at_10,
            "ndcg_at_10": ndcg_at_10,
        },
        "gates": gates,
        "cases": cases,
        "hubness_top_10": [
            {"section_id": section_id, "frequency": frequency}
            for section_id, frequency in sorted(
                hubness.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ],
        "external_calls": {
            "workers_ai_bge_m3_batches": 1,
            "qdrant_reads": 0,
            "qdrant_writes": 0,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "account_id_persisted": False,
            "service_url_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "qdrant_read_dispatched": False,
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
            "promotion_eligibility_granted": False,
        },
        "exit": {
            "offline_ready_for_candidate_reingestion": status
            == "pass_offline_rebuild_evaluation",
            "live_acceptance_still_required": True,
            "retrieval_quality_blocker_cleared": False,
            "next_gate": (
                "separately_governed_candidate_qdrant_reingestion"
                if status == "pass_offline_rebuild_evaluation"
                else "repair_iteration_required"
            ),
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def redacted_candidate_artifact(candidate: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(candidate)
    output["probe_plan"] = [
        {key: value for key, value in probe.items() if key != "query_text"}
        for probe in _sequence(candidate.get("probe_plan"), "probe plan")
    ]
    expected = candidate.get("candidate_artifact_sha256")
    unsigned = {key: value for key, value in output.items() if key != "candidate_artifact_sha256"}
    _require(
        canonical_sha256(unsigned) == expected,
        141,
        "candidate artifact digest drifted",
    )
    return output
