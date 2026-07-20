from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_live_url_attempt import (
    P8_ISSUE_NUMBER,
    P8_REPORT_PATH,
    build_p8_live_url_attempt,
)
from knowledge_engine.m24_live_url_readiness import P7_PROJECT_NAME


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p8_live_url_attempt_report_is_digest_bound() -> None:
    report = _json(P8_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p8_report_matches_generated_attempt_evidence() -> None:
    report = build_p8_live_url_attempt()

    assert report.model_dump(mode="json") == _json(P8_REPORT_PATH)
    assert report.issue_number == P8_ISSUE_NUMBER
    assert report.pages_project_name == P7_PROJECT_NAME


def test_m24_p8_records_pages_deploy_then_access_enablement_blocker() -> None:
    report = build_p8_live_url_attempt()
    steps = {item.step: item for item in report.lifecycle}

    assert steps["token_capability_probe"].status == "success"
    assert steps["pages_project_create"].status == "success"
    assert steps["pages_direct_upload"].status == "success"
    assert steps["pages_direct_upload"].bounded_evidence["uploaded_file_count"] == 9
    assert steps["pages_direct_upload"].bounded_evidence["preview_url_recorded"] is False
    assert steps["access_application_binding"].status == "blocked"
    assert steps["access_application_binding"].bounded_evidence["cloudflare_error_code"] == 9999
    assert (
        steps["access_application_binding"].bounded_evidence["blocker"]
        == "cloudflare_access_not_enabled"
    )
    assert steps["custom_hostname_dns_binding"].status == "not_attempted"


def test_m24_p8_rollback_and_absence_proof_are_explicit() -> None:
    report = build_p8_live_url_attempt()

    assert report.rollback.required is True
    assert report.rollback.completed is True
    assert (
        report.rollback.absence_proof["pages_project_get_after_delete"]["state"]
        == "absent"
    )
    assert (
        report.rollback.absence_proof["pages_project_get_after_delete"][
            "cloudflare_error_code"
        ]
        == 8000007
    )
    assert report.rollback.absence_proof["custom_hostname_dns_records"]["count"] == 0
    assert (
        report.rollback.absence_proof["access_api_after_rollback"]["state"]
        == "access_not_enabled"
    )


def test_m24_p8_acceptance_remains_pending_until_access_is_enabled() -> None:
    report = build_p8_live_url_attempt()

    assert report.acceptance.status == "rolled_back_pending_cloudflare_access_enablement"
    assert report.acceptance.live_url_status == (
        "rolled_back_after_unprotected_pages_upload"
    )
    assert report.acceptance.manual_daniel_acceptance == "pending_access_enablement"
    assert "Enable Cloudflare Access" in report.acceptance.required_next_action


def test_m24_p8_preserves_non_production_authority_boundary() -> None:
    report = build_p8_live_url_attempt()

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


def test_m24_p8_evidence_does_not_commit_preview_url_or_secrets() -> None:
    report_text = P8_REPORT_PATH.read_text(encoding="utf-8")

    assert "pages.dev" not in report_text
    assert "https://" not in report_text
    assert "Bearer" not in report_text
    assert "token values" in report_text
    assert "raw headers" in report_text
