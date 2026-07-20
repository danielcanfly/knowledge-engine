from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_final_product_closure import (
    P10_HANDOFF_PACKAGE,
    P10_ISSUE_NUMBER,
    P10_REPORT_PATH,
    build_p10_final_product_closure,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p10_final_closure_report_is_digest_bound() -> None:
    report = _json(P10_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p10_report_matches_generated_closure_evidence() -> None:
    report = build_p10_final_product_closure()

    assert report.model_dump(mode="json") == _json(P10_REPORT_PATH)
    assert report.issue_number == P10_ISSUE_NUMBER
    assert report.handoff_package.package_name == P10_HANDOFF_PACKAGE


def test_m24_p10_audits_handoff_package_manifest() -> None:
    report = build_p10_final_product_closure()
    package = report.handoff_package

    assert package.zip_file_count == 34
    assert package.manifest_entry_count == 32
    assert package.manifest_verified_locally is True
    assert package.selected_entry_sha256["00_COMPLETION_DEFINITION.md"] == (
        "7393763b7d94700c8088f717463e9c97f22175a54792290130361d2af22be813"
    )
    assert package.selected_entry_sha256["17_P10_FINAL_CLOSURE.md"] == (
        "b17573820a5c8dec685cb5f3f0c4396fcc4678525da6bb58bfd961de7cedb0ec"
    )


def test_m24_p10_covers_every_programme_phase_exactly_once() -> None:
    report = build_p10_final_product_closure()

    phases = [item.phase for item in report.programme]
    assert phases == [f"P{index}" for index in range(1, 11)]
    assert len(set(phases)) == 10
    assert all(item.repo_evidence for item in report.programme)


def test_m24_p10_does_not_falsely_claim_production_or_independent_closure() -> None:
    report = build_p10_final_product_closure()
    phases = {item.phase: item for item in report.programme}

    assert phases["P7"].status == "governed_deferred"
    assert phases["P8"].status == "governed_deferred"
    assert phases["P10"].status == "pending_external_acceptance"
    assert phases["P7"].remaining_trigger is not None
    assert phases["P8"].remaining_trigger is not None
    assert phases["P10"].remaining_trigger is not None
    assert report.closure_decision.status == "operator_ready_pending_external_acceptance"
    assert report.closure_decision.production_retrieval == "lexical"
    assert report.closure_decision.production_semantic_or_hybrid_status == "not_authorized"
    assert report.closure_decision.large_scale_ingestion_status == "not_authorized"
    assert report.closure_decision.independent_operator_exercise_status == "pending"


def test_m24_p10_remaining_items_are_explicit_and_unauthorized_now() -> None:
    report = build_p10_final_product_closure()
    remaining = {item.item: item for item in report.remaining_items}

    assert set(remaining) == {
        "daniel_authenticated_browser_acceptance",
        "independent_operator_final_exercise",
        "production_semantic_hybrid_retrieval",
        "production_answer_serving",
        "large_scale_ingestion",
    }
    assert remaining["daniel_authenticated_browser_acceptance"].status == (
        "pending_external_acceptance"
    )
    assert remaining["independent_operator_final_exercise"].status == (
        "pending_external_acceptance"
    )
    assert remaining["production_semantic_hybrid_retrieval"].status == (
        "governed_deferred"
    )
    assert remaining["production_answer_serving"].status == "governed_deferred"
    assert remaining["large_scale_ingestion"].status == "governed_deferred"
    assert all(item.trigger_to_complete for item in remaining.values())
    assert all(not item.authorized_now for item in remaining.values())


def test_m24_p10_feedback_maintenance_contract_is_complete_but_gated() -> None:
    contract = build_p10_final_product_closure().maintenance_contract

    assert contract.feedback_lifecycle_defined is True
    assert contract.freshness_checks_defined is True
    assert contract.deletion_tombstones_defined is True
    assert contract.supersession_defined is True
    assert contract.contradiction_discovery_defined is True
    assert contract.alias_duplicate_cleanup_defined is True
    assert contract.embedding_migration_requires_gate is True
    assert contract.qdrant_rebuild_requires_gate is True
    assert contract.graph_schema_migration_requires_gate is True
    assert contract.rollback_drills_defined is True
    assert contract.review_throughput_reporting_defined is True


def test_m24_p10_preserves_non_production_authority_boundary() -> None:
    report = build_p10_final_product_closure()

    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_answer_serving_enabled is False
    assert report.authority.source_mutation is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False
    assert report.authority.permanent_ledger_mutation is False


def test_m24_p10_evidence_does_not_commit_sensitive_values_or_preview_urls() -> None:
    report_text = P10_REPORT_PATH.read_text(encoding="utf-8")

    assert "Bearer" not in report_text
    assert "CFPAT-" not in report_text
    assert "token values" in report_text
    assert "operator email" in report_text
    assert "raw headers" in report_text
    assert "raw response bodies" in report_text
    assert not re.search(
        r"https://[a-z0-9]+\\.llm-wiki-m24-internal\\.pages\\.dev",
        report_text,
    )
    assert not re.search(r"[^\\s@]+@[^\\s@]+", report_text)
