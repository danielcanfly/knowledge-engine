from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_controlled_ingestion_pilot import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    MAX_SOURCES_PER_BATCH,
    P4_BATCH_IDS,
    P4_ISSUE_NUMBER,
    build_p4_batch_manifests,
    build_p4_controlled_ingestion_report,
    build_p4_source_inventory,
    execute_p4_pilot_batch,
)

P4_ROOT = Path("pilot/m24/controlled-ingestion-pilot")
REPORT_PATH = P4_ROOT / "m24-p4-controlled-ingestion-pilot.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p4_report_and_batch_manifests_are_digest_bound() -> None:
    report = _json(REPORT_PATH)
    unsigned_report = dict(report)
    report_digest = unsigned_report.pop("self_sha256")

    assert canonical_sha256(unsigned_report) == report_digest
    for batch_id in P4_BATCH_IDS:
        manifest = _json(P4_ROOT / "batches" / f"{batch_id}.json")
        unsigned_manifest = dict(manifest)
        manifest_digest = unsigned_manifest.pop("manifest_sha256_self")
        assert canonical_sha256(unsigned_manifest) == manifest_digest
        assert manifest_digest in report["batch_manifest_sha256"]


def test_m24_p4_builds_three_generic_candidate_only_batches() -> None:
    inventory = build_p4_source_inventory()
    manifests = build_p4_batch_manifests()

    assert len(inventory) == 7
    assert [item.batch_id for item in manifests] == list(P4_BATCH_IDS)
    assert [item.source_count for item in manifests] == [3, 2, 2]
    assert all(item.source_count <= MAX_SOURCES_PER_BATCH for item in manifests)
    assert all(item.release_id == CANONICAL_RELEASE_ID for item in manifests)
    assert all(item.manifest_sha256 == CANONICAL_MANIFEST_SHA256 for item in manifests)
    assert all(item.idempotency_key is not None for item in manifests)
    assert all("write_canonical_source" in item.disallowed_actions for item in manifests)
    assert all(
        item.review_capacity.automatic_canonicalization_allowed is False
        for item in manifests
    )


def test_m24_p4_batch_receipts_are_completed_and_replayable_without_recovery() -> None:
    receipts = [execute_p4_pilot_batch(manifest) for manifest in build_p4_batch_manifests()]

    assert [item.batch_id for item in receipts] == list(P4_BATCH_IDS)
    assert all(item.status == "completed" for item in receipts)
    assert all(item.immutable_snapshot_success for item in receipts)
    assert all(item.normalization_success for item in receipts)
    assert all(item.parser_success for item in receipts)
    assert all(item.evidence_locator_validity for item in receipts)
    assert all(item.duplicate_rate == 0.0 for item in receipts)
    assert all(item.contradiction_count == 0 for item in receipts)
    assert all(item.manual_recovery_required is False for item in receipts)
    assert all(item.unbounded_repair_required is False for item in receipts)
    assert all(item.authority.candidate_only_ai is True for item in receipts)
    assert all(item.authority.canonical_source_mutation is False for item in receipts)


def test_m24_p4_report_matches_committed_evidence_and_blocks_large_scale() -> None:
    report = build_p4_controlled_ingestion_report()
    evidence = _json(REPORT_PATH)

    assert report.model_dump(mode="json") == evidence
    assert report.issue_number == P4_ISSUE_NUMBER
    assert report.status == "controlled_ingestion_pilot_complete"
    assert report.pilot_batch_count == 3
    assert report.consecutive_completed_batches == 3
    assert report.total_source_count == 7
    assert report.total_candidate_count == 146
    assert {item.drill for item in report.drills} == {
        "failure_recovery",
        "rollback",
        "deletion_tombstone",
    }
    assert all(item.status == "passed" for item in report.drills)
    assert all(item.mutation_dispatched is False for item in report.drills)
    assert report.large_scale_gate.status == "blocked"
    assert "measured human review throughput" in report.large_scale_gate.required_before_scale
    assert report.authority.large_scale_ingestion_authorized is False
    assert report.authority.source_pr_content_write is False
    assert report.authority.candidate_release_rebuild is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.permanent_ledger_mutation is False
