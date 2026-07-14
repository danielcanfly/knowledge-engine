from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .m23_benchmark_correction import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    VECTOR_DIMENSION,
    BenchmarkCorrectionError,
    canonical_sha256,
    file_sha256,
    read_float32_vectors,
    required_string,
    validate_gold,
)
from .m23_benchmark_decision import build_decision
from .m23_benchmark_evaluation import (
    calibrate_threshold,
    evaluate_article_rankings,
    evaluate_exact_section_diagnostic,
    evaluate_held_out_abstention,
    reciprocal_rank_fusion,
    semantic_top_scores,
    vector_rankings,
)


def _read_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    value = json.loads(archive.read(name))
    if not isinstance(value, dict):
        raise BenchmarkCorrectionError(
            f"{name} must contain a JSON object"
        )
    return value


def _archive_root(names: Sequence[str]) -> str:
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(roots) != 1:
        raise BenchmarkCorrectionError(
            "evidence ZIP must contain exactly one root directory"
        )
    return next(iter(roots))


def verify_receipt_files(
    archive: zipfile.ZipFile,
    root: str,
    receipt: Mapping[str, Any],
) -> None:
    files = receipt.get("files")
    if not isinstance(files, Mapping):
        raise BenchmarkCorrectionError(
            "source receipt has no file manifest"
        )
    for relative_name, expected in files.items():
        if not isinstance(expected, Mapping):
            raise BenchmarkCorrectionError(
                "source receipt file entry must be an object"
            )
        data = archive.read(f"{root}/{relative_name}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected.get("sha256") or len(data) != expected.get(
            "bytes"
        ):
            raise BenchmarkCorrectionError(
                f"source evidence manifest mismatch for {relative_name}"
            )


def run_offline_rebenchmark(
    *,
    evidence_zip: Path,
    gold_path: Path,
    expected_evidence_sha256: str,
) -> dict[str, Any]:
    evidence_sha = file_sha256(evidence_zip)
    if evidence_sha != expected_evidence_sha256:
        raise BenchmarkCorrectionError(
            "source evidence ZIP digest mismatch"
        )
    raw_gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(raw_gold, dict):
        raise BenchmarkCorrectionError(
            "corrected gold root must be an object"
        )

    with zipfile.ZipFile(evidence_zip) as archive:
        names = archive.namelist()
        root = _archive_root(names)
        suite = _read_json(archive, f"{root}/benchmark-suite.json")
        benchmark = _read_json(
            archive, f"{root}/benchmark-results.json"
        )
        receipt = _read_json(archive, f"{root}/run-receipt.json")
        semantic_metadata = _read_json(
            archive,
            f"{root}/semantic-artifact/semantic-metadata.json",
        )
        verify_receipt_files(archive, root, receipt)
        if receipt.get("qdrant_write") is not False:
            raise BenchmarkCorrectionError(
                "source evidence must not contain a Qdrant write"
            )
        if receipt.get("production_authority") is True:
            raise BenchmarkCorrectionError(
                "source evidence cannot carry production authority"
            )
        gold = validate_gold(suite, raw_gold)
        document_vectors = read_float32_vectors(
            archive.read(f"{root}/pilot-document-vectors.f32"),
            row_count=len(suite["documents"]),
        )
        query_vectors = read_float32_vectors(
            archive.read(f"{root}/pilot-query-vectors.f32"),
            row_count=len(suite["queries"]),
        )

    top_scores = semantic_top_scores(
        suite,
        gold,
        document_vectors,
        query_vectors,
    )
    calibration = calibrate_threshold(gold, top_scores)
    vector = vector_rankings(
        suite,
        document_vectors,
        query_vectors,
        threshold=calibration["threshold"],
    )
    lexical_source = benchmark.get("rankings", {}).get("lexical")
    if not isinstance(lexical_source, Mapping):
        raise BenchmarkCorrectionError(
            "source evidence contains no lexical rankings"
        )
    lexical = {key: list(value) for key, value in lexical_source.items()}
    hybrid = reciprocal_rank_fusion(lexical, vector)
    methods = {
        "lexical": evaluate_article_rankings(
            suite, gold, lexical
        ),
        "vector": evaluate_article_rankings(
            suite, gold, vector
        ),
        "rrf_hybrid_k60": evaluate_article_rankings(
            suite, gold, hybrid
        ),
    }
    held_out = evaluate_held_out_abstention(
        gold,
        top_scores,
        threshold=calibration["threshold"],
    )
    result = {
        "schema_version": RESULT_SCHEMA,
        "source_evidence_sha256": evidence_sha,
        "source_benchmark_suite_sha256": canonical_sha256(suite),
        "corrected_gold_sha256": canonical_sha256(gold),
        "model": {
            "provider": "cloudflare-workers-ai",
            "id": "@cf/baai/bge-m3",
            "dimension": VECTOR_DIMENSION,
        },
        "threshold_calibration": calibration,
        "held_out_abstention": held_out,
        "methods": methods,
        "exact_section_diagnostic": {
            "lexical": evaluate_exact_section_diagnostic(
                suite, lexical
            ),
            "vector": evaluate_exact_section_diagnostic(
                suite, vector
            ),
            "rrf_hybrid_k60": evaluate_exact_section_diagnostic(
                suite, hybrid
            ),
        },
        "top_scores": top_scores,
        "rankings": {
            "lexical": lexical,
            "vector": vector,
            "rrf_hybrid_k60": hybrid,
        },
        "read_only": True,
        "qdrant_write": False,
        "production_authority": False,
    }
    result["result_sha256"] = canonical_sha256(result)
    decision = build_decision(
        source_evidence_sha256=evidence_sha,
        source_semantic_artifact_id=required_string(
            semantic_metadata.get("artifact_id"),
            "semantic artifact ID",
            200,
        ),
        corrected_gold_sha256=result["corrected_gold_sha256"],
        methods=methods,
        calibration=calibration,
        held_out=held_out,
    )
    receipt_out = {
        "schema_version": RECEIPT_SCHEMA,
        "source_evidence_sha256": evidence_sha,
        "corrected_gold_sha256": result["corrected_gold_sha256"],
        "result_sha256": result["result_sha256"],
        "decision_sha256": decision["decision_sha256"],
        "network_calls": 0,
        "cloudflare_calls": 0,
        "qdrant_reads": 0,
        "qdrant_writes": 0,
        "r2_mutation": False,
        "source_write": False,
        "pointer_mutation": False,
        "traffic_change": False,
        "retrieval_default": "lexical",
        "production_authority": False,
    }
    receipt_out["receipt_sha256"] = canonical_sha256(receipt_out)
    return {
        "gold": gold,
        "result": result,
        "decision": decision,
        "receipt": receipt_out,
    }
