from __future__ import annotations

from pathlib import Path

from knowledge_engine.m26_production_answer_bundle import (
    build_production_answer_compatibility_report,
)
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_full_production_answer_bundle_compatibility_report_binds_expected_identity() -> None:
    report = build_production_answer_compatibility_report(
        synthetic_full_production_answer_bundle(),
        root=ROOT,
    )

    assert report["status"] == "compatible"
    assert report["release"]["release_id"] == (
        "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
    )
    assert report["expected"]["graph_v2_sha256"] == (
        "ddaceb89bfda15618fdf9360953d9f66a5c8b33c3853480c1db7abe41ba32869"
    )
    assert report["counts"]["graph_nodes"] == 4222
    assert report["counts"]["graph_edges"] == 8525
    assert report["counts"]["outside_old_m24_concepts"] == 4222
    assert all(value == 0 for value in report["mismatch_counts"].values())
    assert report["authority"] == {
        "answer_to_canonical_writes": 0,
        "canonical_writes": 0,
        "production_pointer_writes": 0,
        "qdrant_writes": 0,
        "r2_writes": 0,
        "read_only": True,
        "source_writes": 0,
    }
