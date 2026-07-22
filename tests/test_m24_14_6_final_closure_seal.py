from __future__ import annotations

import hashlib
import json

from knowledge_engine.m24_14_6_authenticated_performance import (
    BENCHMARK_EVIDENCE_METADATA_PATH,
    BENCHMARK_EVIDENCE_PATH,
    M24_14_6_BENCHMARK_FILE_SHA256,
    M24_14_6_BENCHMARK_SELF_SHA256,
)
from knowledge_engine.m24_14_6_final_closure_seal import (
    FINAL_STATUS,
    build_m25_final_entry_baseline,
    build_post_merge_attestation,
    payload_self_sha256,
    validate_committed_closure_artifacts,
)


def _json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_14_6_committed_benchmark_evidence_is_portable() -> None:
    result = validate_committed_closure_artifacts()
    metadata = _json_file(BENCHMARK_EVIDENCE_METADATA_PATH)

    assert hashlib.sha256(BENCHMARK_EVIDENCE_PATH.read_bytes()).hexdigest() == (
        M24_14_6_BENCHMARK_FILE_SHA256
    )
    assert metadata["repository_path"] == BENCHMARK_EVIDENCE_PATH.as_posix()
    assert metadata["sha256"] == M24_14_6_BENCHMARK_FILE_SHA256
    assert metadata["benchmark_self_sha256"] == M24_14_6_BENCHMARK_SELF_SHA256
    metadata_material = dict(metadata)
    metadata_self_sha256 = metadata_material["metadata_self_sha256"]
    metadata_material["metadata_self_sha256"] = ""
    assert hashlib.sha256(
        json.dumps(
            metadata_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest() == metadata_self_sha256
    assert metadata["no_local_source_path"] is True
    assert result["benchmark"]["decision"] == "pass"
    assert result["benchmark"]["reason_codes"] == []
    assert result["benchmark"]["sensitive_scan"]["passed"] is True


def test_m24_14_6_post_merge_baseline_uses_literal_final_sha() -> None:
    final_sha = "c" * 40
    baseline = build_m25_final_entry_baseline(
        issue_number=1034,
        pr_number=1035,
        pr_head_sha="d" * 40,
        merge_sha=final_sha,
        tag_target_sha=final_sha,
        ci_runs=["CI=29920000001", "closure-seal=29920000002"],
    )

    assert baseline["schema_version"] == "knowledge-engine-m24-14-6-m25-entry-baseline/v2"
    assert baseline["engine_main_sha"] == final_sha
    assert baseline["closure_seal_merge_sha"] == final_sha
    assert baseline["closure_seal_tag_target_sha"] == final_sha
    assert baseline["closure_seal_ref"] == "refs/tags/m24-14-6-final-closure"
    assert baseline["production_retrieval"] == "lexical"
    assert baseline["semantic_serving_enabled"] is False
    assert baseline["hybrid_retrieval_enabled"] is False
    assert baseline["production_answer_serving_enabled"] is False
    assert baseline["large_scale_ingestion_enabled"] is False
    assert baseline["self_sha256"] == payload_self_sha256(baseline)


def test_m24_14_6_post_merge_attestation_is_self_digested() -> None:
    final_sha = "e" * 40
    attestation = build_post_merge_attestation(
        issue_number=1034,
        pr_number=1035,
        pr_head_sha="f" * 40,
        merge_sha=final_sha,
        tag_target_sha=final_sha,
        ci_runs=["CI=29920000001"],
    )

    assert attestation["final_status"] == FINAL_STATUS
    assert attestation["git"]["engine_main_sha"] == final_sha
    assert attestation["git"]["closure_seal_tag_target_sha"] == final_sha
    assert attestation["benchmark_file_sha256"] == M24_14_6_BENCHMARK_FILE_SHA256
    assert attestation["benchmark_self_sha256"] == M24_14_6_BENCHMARK_SELF_SHA256
    assert attestation["self_sha256"] == payload_self_sha256(attestation)
