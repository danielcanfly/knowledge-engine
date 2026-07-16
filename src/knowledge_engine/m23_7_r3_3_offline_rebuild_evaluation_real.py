from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import m23_7_r3_3_offline_rebuild_evaluation as base
from .errors import IntegrityError
from .m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_repaired_ingestion_preview,
    compile_repaired_probe_plan,
)
from .m23_qdrant_pilot_ingestion import (
    EXPECTED_VECTOR_BYTES,
    _archive_root,
    _read_json_bytes,
    _receipt_files,
    _unpack_vectors,
    _validate_receipt,
    _validate_suite,
    bytes_sha256,
    canonical_sha256,
    file_sha256,
)
from .m23_qdrant_pilot_ingestion_real import _validate_semantic_sidecar

EXPECTED_EVIDENCE_SHA256 = base.EXPECTED_EVIDENCE_SHA256
EXPECTED_SEMANTIC_ARTIFACT_ID = base.EXPECTED_SEMANTIC_ARTIFACT_ID
EXPECTED_POINT_COUNT = base.EXPECTED_POINT_COUNT
VECTOR_DIMENSION = base.VECTOR_DIMENSION
SAMPLE_CAP = base.SAMPLE_CAP

canonical_json = base.canonical_json
canonical_contract = base.canonical_contract
evaluate_offline_candidate = base.evaluate_offline_candidate
redacted_candidate_artifact = base.redacted_candidate_artifact


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.3A-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _load_inputs(path: Path) -> dict[str, Any]:
    _require(file_sha256(path) == EXPECTED_EVIDENCE_SHA256, 102, "evidence ZIP drifted")
    with zipfile.ZipFile(path) as archive:
        root = _archive_root(archive.namelist())
        receipt = _read_json_bytes(
            archive.read(f"{root}/run-receipt.json"),
            "run-receipt.json",
        )
        _validate_receipt(receipt)
        receipt_files = _receipt_files(archive, root, receipt)
        suite = _read_json_bytes(
            archive.read(f"{root}/benchmark-suite.json"),
            "benchmark-suite.json",
        )
        vector_bytes = archive.read(f"{root}/pilot-document-vectors.f32")
        semantic_bytes = archive.read(
            f"{root}/semantic-artifact/semantic-metadata.json"
        )
        semantic = _read_json_bytes(semantic_bytes, "semantic-metadata.json")
        semantic_vectors = archive.read(
            f"{root}/semantic-artifact/semantic-vectors.f32"
        )
        benchmark_results: dict[str, Any] | None = None
        benchmark_results_name = f"{root}/benchmark-results.json"
        if benchmark_results_name in archive.namelist():
            benchmark_results = _read_json_bytes(
                archive.read(benchmark_results_name),
                "benchmark-results.json",
            )

    identities = _mapping(suite.get("identities"), "suite identities")
    authority = {
        "identities": {
            "source_commit_sha": identities.get("source_commit_sha"),
            "foundation_commit_sha": identities.get("foundation_commit_sha"),
        }
    }
    documents = _validate_suite(suite, authority)
    _require(len(documents) == EXPECTED_POINT_COUNT, 103, "document count drifted")
    _require(
        len(vector_bytes) == EXPECTED_VECTOR_BYTES,
        104,
        "pilot document vector byte count drifted",
    )
    _require(
        len(semantic_vectors) == EXPECTED_VECTOR_BYTES,
        105,
        "semantic vector byte count drifted",
    )

    vectors = _unpack_vectors(vector_bytes, EXPECTED_POINT_COUNT)
    _unpack_vectors(semantic_vectors, EXPECTED_POINT_COUNT)
    _validate_semantic_sidecar(
        semantic,
        semantic_vectors,
        suite,
        benchmark_results,
        documents,
        expected_artifact_id=EXPECTED_SEMANTIC_ARTIFACT_ID,
    )
    return {
        "receipt_files": receipt_files,
        "suite_sha256": canonical_sha256(suite),
        "vector_sha256": bytes_sha256(vector_bytes),
        "semantic_vector_sha256": bytes_sha256(semantic_vectors),
        "semantic_metadata_sha256": bytes_sha256(semantic_bytes),
        "documents": documents,
        "vectors": vectors,
    }


def _release(inputs: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": "knowledge-engine-m23-7-r3-3-candidate-release/v1",
        "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
        "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        "benchmark_suite_sha256": inputs["suite_sha256"],
        "document_vectors_sha256": inputs["vector_sha256"],
        "repair_contract_sha256": base.R3_2_REPAIR_CONTRACT_SHA256,
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "point_count": EXPECTED_POINT_COUNT,
        "embedding_model": "@cf/baai/bge-m3",
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": "default",
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    digest = canonical_sha256(body)
    return {
        **body,
        "release_id": f"m23r33-{digest[:24]}",
        "release_manifest_sha256": digest,
    }


def _redacted_probes(probes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in probe.items() if key != "query_text"}
        for probe in probes
    ]


def build_offline_candidate(path: Path) -> dict[str, Any]:
    inputs = _load_inputs(path)
    preview = build_repaired_ingestion_preview(
        inputs["documents"],
        inputs["vectors"],
        release=_release(inputs),
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
    _require(len(eligible) == EXPECTED_POINT_COUNT, 106, "eligible count drifted")
    samples = eligible[:SAMPLE_CAP]
    _require(
        all(sample["payload"]["audience"] == "public" for sample in samples),
        107,
        "bounded sample audience drifted",
    )
    probes = compile_repaired_probe_plan(samples)
    _require(
        len({probe["query_text_sha256"] for probe in probes}) == SAMPLE_CAP,
        108,
        "query identity collision",
    )
    candidate: dict[str, Any] = {
        "schema_version": base.CANDIDATE_SCHEMA_VERSION,
        "milestone": "M23.7-R3.3",
        "mode": "offline-no-write-candidate",
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence": {
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "benchmark_suite_sha256": inputs["suite_sha256"],
            "document_vectors_sha256": inputs["vector_sha256"],
            "semantic_vectors_sha256": inputs["semantic_vector_sha256"],
            "semantic_metadata_sha256": inputs["semantic_metadata_sha256"],
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
            "vector_generation_policy": "independent-provider-generations",
            "ranking_vector_source": "pilot-document-vectors.f32",
        },
        "release": _release(inputs),
        "point_count": len(preview["points"]),
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "preview_sha256": preview["preview_sha256"],
        "points": preview["points"],
        "bindings": preview["bindings"],
        "probe_plan": probes,
        "authority": preview["authority"],
    }
    unsigned = {**candidate, "probe_plan": _redacted_probes(probes)}
    candidate["candidate_artifact_sha256"] = canonical_sha256(unsigned)
    return candidate
