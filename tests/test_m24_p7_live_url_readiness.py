from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_live_url_readiness import (
    P7_CUSTOM_HOSTNAME,
    P7_ISSUE_NUMBER,
    P7_PROJECT_NAME,
    P7_REPORT_PATH,
    build_p7_live_url_readiness,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p7_readiness_report_is_digest_bound() -> None:
    report = _json(P7_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p7_report_matches_generated_evidence() -> None:
    report = build_p7_live_url_readiness()

    assert report.model_dump(mode="json") == _json(P7_REPORT_PATH)
    assert report.issue_number == P7_ISSUE_NUMBER
    assert report.p6_package_status == "internal_product_deployment_package_complete"


def test_m24_p7_records_current_cloudflare_authority_gap() -> None:
    report = build_p7_live_url_readiness()
    observations = {item.capability: item for item in report.capability_observations}

    assert observations["cloudflare_token_verify"].status_class == "available"
    assert observations["cloudflare_account_read"].status_class == "available"
    assert observations["cloudflare_zone_read"].status_class == "available"
    assert observations["cloudflare_pages_projects_read_write"].status_class == "forbidden"
    assert observations["cloudflare_access_apps_read_write"].status_class == "forbidden"
    assert observations["cloudflare_access_organization_read"].status_class == "forbidden"
    assert observations["github_cloudflare_pages_access_secret"].status_class == "missing"
    assert all(
        "token" not in json.dumps(item.evidence).lower()
        or item.evidence.get("token_value_recorded") is False
        for item in report.capability_observations
    )


def test_m24_p7_deployment_plan_is_exact_but_not_accepted() -> None:
    report = build_p7_live_url_readiness()

    assert report.deployment_plan.pages_project_name == P7_PROJECT_NAME
    assert report.deployment_plan.custom_hostname == P7_CUSTOM_HOSTNAME
    assert report.deployment_plan.direct_upload_command == [
        "wrangler",
        "pages",
        "deploy",
        "pilot/m24/internal-product-deployment/site",
        "--project-name",
        P7_PROJECT_NAME,
        "--branch",
        "main",
    ]
    assert report.acceptance_gate.status == (
        "blocked_pending_cloudflare_pages_access_authority"
    )
    assert report.acceptance_gate.live_url_status == "pending_cloudflare_access_binding"
    assert report.acceptance_gate.manual_daniel_acceptance == "pending_authenticated_url"
    assert "Cloudflare Pages Write" in report.acceptance_gate.required_next_authority
    assert "Cloudflare Access Apps and Policies Write" in (
        report.acceptance_gate.required_next_authority
    )


def test_m24_p7_preserves_non_production_authority_boundary() -> None:
    report = build_p7_live_url_readiness()

    assert report.authority.product_audience == "authenticated_internal"
    assert report.authority.browser_authority == "read_only"
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
    assert report.authority.raw_evidence_exposed is False


def test_m24_p7_public_exposure_controls_are_required() -> None:
    report = build_p7_live_url_readiness()

    assert "do not treat the pages.dev URL as accepted" in (
        report.deployment_plan.public_exposure_controls
    )
    assert "bind Access before declaring Daniel acceptance" in (
        report.deployment_plan.public_exposure_controls
    )
    assert "delete the Pages deployment or project" in report.deployment_plan.rollback
