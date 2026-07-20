from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_authenticated_live_url_binding import (
    P9_ISSUE_NUMBER,
    P9_REPORT_PATH,
    build_p9_authenticated_live_url_binding,
)
from knowledge_engine.m24_live_url_readiness import P7_CUSTOM_HOSTNAME, P7_PROJECT_NAME


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p9_authenticated_live_url_binding_report_is_digest_bound() -> None:
    report = _json(P9_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p9_report_matches_generated_live_binding_evidence() -> None:
    report = build_p9_authenticated_live_url_binding()

    assert report.model_dump(mode="json") == _json(P9_REPORT_PATH)
    assert report.issue_number == P9_ISSUE_NUMBER
    assert report.pages_deployment.project_name == P7_PROJECT_NAME
    assert report.dns_binding.hostname == P7_CUSTOM_HOSTNAME


def test_m24_p9_records_pages_access_and_dns_binding() -> None:
    report = build_p9_authenticated_live_url_binding()

    assert report.token_capability.pages_projects_read_write_authorized is True
    assert report.token_capability.access_apps_read_write_authorized is True
    assert report.token_capability.zone_dns_edit_authorized is True
    assert report.pages_deployment.latest_deployment_environment == "production"
    assert report.pages_deployment.static_asset_count == 9
    assert report.pages_deployment.worker_bundle_uploaded is True
    assert report.dns_binding.record_type == "CNAME"
    assert report.dns_binding.cname_count == 1
    assert report.dns_binding.target_class == "pages_dev"
    assert report.dns_binding.proxied is True


def test_m24_p9_protects_custom_primary_and_preview_hosts_with_access() -> None:
    report = build_p9_authenticated_live_url_binding()

    domain_classes = {app.domain_class for app in report.access_applications}
    assert domain_classes == {
        "custom_hostname",
        "pages_dev_primary",
        "pages_dev_wildcard",
    }
    assert all(app.policies_count == 1 for app in report.access_applications)
    assert all(app.single_operator_allow_policy for app in report.access_applications)
    assert all(not app.operator_email_recorded for app in report.access_applications)

    probes = {probe.host_class: probe for probe in report.unauthenticated_probes}
    assert set(probes) == {"custom_host", "pages_dev_primary", "pages_dev_preview"}
    assert all(probe.service_available for probe in probes.values())
    assert all(probe.access_wall_observed for probe in probes.values())
    assert all(not probe.release_content_observed for probe in probes.values())


def test_m24_p9_acceptance_is_only_pending_manual_browser_acceptance() -> None:
    report = build_p9_authenticated_live_url_binding()

    assert report.acceptance.status == "access_protected_pending_daniel_acceptance"
    assert report.acceptance.live_url_status == "authenticated_access_wall_bound"
    assert (
        report.acceptance.manual_daniel_acceptance
        == "pending_authenticated_browser_acceptance"
    )
    assert report.custom_domain.external_access_wall_observed is True
    assert report.custom_domain.pages_domain_status == "pending"


def test_m24_p9_preserves_non_production_authority_boundary() -> None:
    report = build_p9_authenticated_live_url_binding()

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


def test_m24_p9_evidence_does_not_commit_credentials_or_preview_full_url() -> None:
    report_text = P9_REPORT_PATH.read_text(encoding="utf-8")

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


def test_m24_p9_worker_blocks_pages_dev_hosts_as_defense_in_depth() -> None:
    worker = Path(
        "pilot/m24/internal-product-deployment/site/_worker.js"
    ).read_text(encoding="utf-8")

    assert "llm-wiki-m24-internal.pages.dev" in worker
    assert "host.endsWith" in worker
    assert 'return new Response("Forbidden"' in worker
    assert "env.ASSETS.fetch(request)" in worker
