from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import P6AuthorityBoundary
from .m24_live_url_readiness import P7_CUSTOM_HOSTNAME, P7_PROJECT_NAME
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

P9_SCHEMA = "knowledge-engine-m24-p9-authenticated-live-url-binding/v1"
P9_ISSUE_NUMBER = 1003
P9_ROOT = Path("pilot/m24/authenticated-live-url-binding")
P9_REPORT_PATH = P9_ROOT / "m24-p9-authenticated-live-url-binding.json"
P9_DEPLOYMENT_SHORT_ID = "89eadd26"


class P9TokenCapabilityEvidence(BaseModel):
    token_verified: bool
    pages_projects_read_write_authorized: bool
    pages_deploy_authorized: bool
    access_apps_read_write_authorized: bool
    access_organization_read_authorized: bool
    zone_dns_edit_authorized: bool
    token_value_recorded: bool = False


class P9PagesDeploymentEvidence(BaseModel):
    project_name: str
    production_branch: Literal["main"]
    deployment_count_observed: int = Field(ge=1)
    latest_deployment_environment: Literal["production"]
    deployment_short_id: str
    static_asset_count: int = Field(ge=1)
    worker_bundle_uploaded: bool
    preview_full_url_recorded: bool = False


class P9AccessApplicationEvidence(BaseModel):
    domain_class: Literal["custom_hostname", "pages_dev_primary", "pages_dev_wildcard"]
    application_type: Literal["self_hosted"] = "self_hosted"
    policies_count: int = Field(ge=1)
    single_operator_allow_policy: bool
    operator_email_recorded: bool = False
    application_id_recorded: bool = False
    audience_tag_recorded: bool = False


class P9DnsBindingEvidence(BaseModel):
    hostname: str
    record_type: Literal["CNAME"]
    cname_count: int
    target_class: Literal["pages_dev", "other_or_missing"]
    proxied: bool
    zone_id_recorded: bool = False


class P9CustomDomainEvidence(BaseModel):
    hostname: str
    pages_domain_status: Literal["pending", "active", "verified"]
    external_access_wall_observed: bool
    activation_note: str


class P9UnauthenticatedProbe(BaseModel):
    host_class: Literal["custom_host", "pages_dev_primary", "pages_dev_preview"]
    http_status_class: Literal["2xx", "3xx", "4xx", "5xx", "network_error"]
    service_available: bool
    access_wall_observed: bool
    release_content_observed: bool


class P9LifecycleStep(BaseModel):
    step: str
    status: Literal["success", "pending_manual_acceptance"]
    bounded_evidence: dict[str, Any]


class P9AcceptanceState(BaseModel):
    status: Literal["access_protected_pending_daniel_acceptance"]
    live_url_status: Literal["authenticated_access_wall_bound"]
    manual_daniel_acceptance: Literal["pending_authenticated_browser_acceptance"]
    required_next_action: str


class P9AuthenticatedLiveUrlBindingReport(BaseModel):
    schema_version: str = P9_SCHEMA
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    token_capability: P9TokenCapabilityEvidence
    pages_deployment: P9PagesDeploymentEvidence
    access_applications: list[P9AccessApplicationEvidence]
    dns_binding: P9DnsBindingEvidence
    custom_domain: P9CustomDomainEvidence
    unauthenticated_probes: list[P9UnauthenticatedProbe]
    lifecycle: list[P9LifecycleStep]
    acceptance: P9AcceptanceState
    authority: P6AuthorityBoundary
    evidence_hygiene: list[str]
    self_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        return canonical_sha256(value.model_dump(mode="json"))
    return canonical_sha256(value)


def build_p9_authenticated_live_url_binding(
    *,
    output_path: Path = P9_REPORT_PATH,
    include_self_digest: bool = True,
) -> P9AuthenticatedLiveUrlBindingReport:
    probes = [
        P9UnauthenticatedProbe(
            host_class="custom_host",
            http_status_class="2xx",
            service_available=True,
            access_wall_observed=True,
            release_content_observed=False,
        ),
        P9UnauthenticatedProbe(
            host_class="pages_dev_primary",
            http_status_class="2xx",
            service_available=True,
            access_wall_observed=True,
            release_content_observed=False,
        ),
        P9UnauthenticatedProbe(
            host_class="pages_dev_preview",
            http_status_class="2xx",
            service_available=True,
            access_wall_observed=True,
            release_content_observed=False,
        ),
    ]
    report = P9AuthenticatedLiveUrlBindingReport(
        issue_number=P9_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        token_capability=P9TokenCapabilityEvidence(
            token_verified=True,
            pages_projects_read_write_authorized=True,
            pages_deploy_authorized=True,
            access_apps_read_write_authorized=True,
            access_organization_read_authorized=True,
            zone_dns_edit_authorized=True,
        ),
        pages_deployment=P9PagesDeploymentEvidence(
            project_name=P7_PROJECT_NAME,
            production_branch="main",
            deployment_count_observed=2,
            latest_deployment_environment="production",
            deployment_short_id=P9_DEPLOYMENT_SHORT_ID,
            static_asset_count=9,
            worker_bundle_uploaded=True,
        ),
        access_applications=[
            P9AccessApplicationEvidence(
                domain_class="custom_hostname",
                policies_count=1,
                single_operator_allow_policy=True,
            ),
            P9AccessApplicationEvidence(
                domain_class="pages_dev_primary",
                policies_count=1,
                single_operator_allow_policy=True,
            ),
            P9AccessApplicationEvidence(
                domain_class="pages_dev_wildcard",
                policies_count=1,
                single_operator_allow_policy=True,
            ),
        ],
        dns_binding=P9DnsBindingEvidence(
            hostname=P7_CUSTOM_HOSTNAME,
            record_type="CNAME",
            cname_count=1,
            target_class="pages_dev",
            proxied=True,
        ),
        custom_domain=P9CustomDomainEvidence(
            hostname=P7_CUSTOM_HOSTNAME,
            pages_domain_status="pending",
            external_access_wall_observed=True,
            activation_note=(
                "Pages custom-domain API still reports pending, but external "
                "unauthenticated HTTPS observation already reaches Cloudflare Access."
            ),
        ),
        unauthenticated_probes=probes,
        lifecycle=[
            P9LifecycleStep(
                step="token_capability_probe",
                status="success",
                bounded_evidence={
                    "cloudflare_pages_access_token_used": True,
                    "token_value_recorded": False,
                },
            ),
            P9LifecycleStep(
                step="pages_project_and_production_deploy",
                status="success",
                bounded_evidence={
                    "project_name": P7_PROJECT_NAME,
                    "deployment_short_id": P9_DEPLOYMENT_SHORT_ID,
                    "preview_full_url_recorded": False,
                    "worker_bundle_uploaded": True,
                },
            ),
            P9LifecycleStep(
                step="access_application_binding",
                status="success",
                bounded_evidence={
                    "applications_created": 3,
                    "domains_protected": [
                        "custom_hostname",
                        "pages_dev_primary",
                        "pages_dev_wildcard",
                    ],
                    "operator_email_recorded": False,
                },
            ),
            P9LifecycleStep(
                step="dns_custom_hostname_binding",
                status="success",
                bounded_evidence={
                    "record_type": "CNAME",
                    "cname_count": 1,
                    "proxied": True,
                    "target_class": "pages_dev",
                },
            ),
            P9LifecycleStep(
                step="unauthenticated_access_observation",
                status="success",
                bounded_evidence={
                    "probe_count": len(probes),
                    "all_observed_access_wall": True,
                    "release_content_observed": False,
                    "raw_headers_recorded": False,
                    "raw_response_bodies_recorded": False,
                },
            ),
            P9LifecycleStep(
                step="daniel_authenticated_browser_acceptance",
                status="pending_manual_acceptance",
                bounded_evidence={
                    "manual_acceptance_recorded": False,
                    "authenticated_release_render_observed_by_codex": False,
                },
            ),
        ],
        acceptance=P9AcceptanceState(
            status="access_protected_pending_daniel_acceptance",
            live_url_status="authenticated_access_wall_bound",
            manual_daniel_acceptance="pending_authenticated_browser_acceptance",
            required_next_action=(
                "Daniel opens the protected custom hostname in a browser, completes "
                "Cloudflare Access login, and accepts the rendered canonical release."
            ),
        ),
        authority=P6AuthorityBoundary(),
        evidence_hygiene=[
            "no Cloudflare token values recorded",
            "no operator email recorded",
            "no raw headers recorded",
            "no raw response bodies recorded",
            "no raw API error bodies recorded",
            "no preview full URL committed",
            "no Access application ids or audience tags committed",
        ],
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
