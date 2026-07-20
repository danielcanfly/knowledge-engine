from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import (
    DEPLOYMENT_ROOT,
    P6_SCHEMA,
    P6AuthorityBoundary,
    build_p6_internal_product_deployment,
)
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

P7_SCHEMA = "knowledge-engine-m24-p7-authenticated-live-url-readiness/v1"
P7_ISSUE_NUMBER = 999
P7_ROOT = Path("pilot/m24/authenticated-live-url-readiness")
P7_REPORT_PATH = P7_ROOT / "m24-p7-authenticated-live-url-readiness.json"
P7_PROJECT_NAME = "llm-wiki-m24-internal"
P7_CUSTOM_HOSTNAME = "m24-internal.danielcanfly.com"


class P7CapabilityObservation(BaseModel):
    capability: str
    status_class: Literal["available", "forbidden", "missing", "not_attempted"]
    bounded_status: str
    evidence: dict[str, Any]


class P7RequiredAuthority(BaseModel):
    permission: str
    purpose: str
    currently_available: bool


class P7DeploymentPlan(BaseModel):
    pages_project_name: str
    custom_hostname: str
    source_package: str
    direct_upload_command: list[str]
    access_application_type: Literal["self_hosted"] = "self_hosted"
    access_policy: dict[str, Any]
    readiness_checks: list[str]
    public_exposure_controls: list[str]
    rollback: list[str]


class P7AcceptanceGate(BaseModel):
    status: Literal[
        "blocked_pending_cloudflare_pages_access_authority",
        "authenticated_live_url_ready",
    ]
    live_url_status: Literal[
        "pending_cloudflare_access_binding",
        "authenticated_live_url_bound",
    ]
    manual_daniel_acceptance: Literal[
        "pending_authenticated_url",
        "accepted_by_daniel",
    ]
    blocker: str | None
    required_next_authority: list[str]


class P7LiveUrlReadinessReport(BaseModel):
    schema_version: str = P7_SCHEMA
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    p6_schema_version: str
    p6_package_status: str
    capability_observations: list[P7CapabilityObservation]
    required_authority: list[P7RequiredAuthority]
    deployment_plan: P7DeploymentPlan
    acceptance_gate: P7AcceptanceGate
    authority: P6AuthorityBoundary
    bounded_evidence_rules: list[str]
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


def observed_p7_capabilities() -> list[P7CapabilityObservation]:
    return [
        P7CapabilityObservation(
            capability="cloudflare_token_verify",
            status_class="available",
            bounded_status="active",
            evidence={
                "token_value_recorded": False,
                "http_status_class": "2xx",
            },
        ),
        P7CapabilityObservation(
            capability="cloudflare_account_read",
            status_class="available",
            bounded_status="one_account_matches_env",
            evidence={
                "account_id_recorded": False,
                "account_count": 1,
            },
        ),
        P7CapabilityObservation(
            capability="cloudflare_zone_read",
            status_class="available",
            bounded_status="active_zones_available",
            evidence={
                "zone_count": 3,
                "candidate_zone": "danielcanfly.com",
            },
        ),
        P7CapabilityObservation(
            capability="cloudflare_pages_projects_read_write",
            status_class="forbidden",
            bounded_status="api_403_authentication_error",
            evidence={
                "http_status_class": "4xx",
                "raw_error_body_recorded": False,
            },
        ),
        P7CapabilityObservation(
            capability="cloudflare_access_apps_read_write",
            status_class="forbidden",
            bounded_status="api_403_authentication_error",
            evidence={
                "http_status_class": "4xx",
                "raw_error_body_recorded": False,
            },
        ),
        P7CapabilityObservation(
            capability="cloudflare_access_organization_read",
            status_class="forbidden",
            bounded_status="api_403_authentication_error",
            evidence={
                "http_status_class": "4xx",
                "raw_error_body_recorded": False,
            },
        ),
        P7CapabilityObservation(
            capability="github_cloudflare_pages_access_secret",
            status_class="missing",
            bounded_status="no_repo_secret_named_for_pages_or_access",
            evidence={
                "secret_values_read": False,
                "cloudflare_pages_or_access_secret_present": False,
            },
        ),
    ]


def required_p7_authority() -> list[P7RequiredAuthority]:
    return [
        P7RequiredAuthority(
            permission="Cloudflare Pages Write",
            purpose="Create or deploy the P6 static site as a Pages Direct Upload project.",
            currently_available=False,
        ),
        P7RequiredAuthority(
            permission="Cloudflare Access Apps and Policies Write",
            purpose="Create the self-hosted Access application and allow policy.",
            currently_available=False,
        ),
        P7RequiredAuthority(
            permission="Cloudflare Access Organization Read",
            purpose="Resolve the account's Access team domain and validate JWT issuer metadata.",
            currently_available=False,
        ),
        P7RequiredAuthority(
            permission="Zone DNS Edit for danielcanfly.com",
            purpose="Bind the internal custom hostname to the Pages project.",
            currently_available=False,
        ),
    ]


def p7_deployment_plan() -> P7DeploymentPlan:
    return P7DeploymentPlan(
        pages_project_name=P7_PROJECT_NAME,
        custom_hostname=P7_CUSTOM_HOSTNAME,
        source_package=DEPLOYMENT_ROOT.joinpath("site").as_posix(),
        direct_upload_command=[
            "wrangler",
            "pages",
            "deploy",
            DEPLOYMENT_ROOT.joinpath("site").as_posix(),
            "--project-name",
            P7_PROJECT_NAME,
            "--branch",
            "main",
        ],
        access_policy={
            "decision": "allow",
            "include": ["Daniel internal operator identity or approved internal group"],
            "session_duration": "8h",
            "unauthenticated_behavior": "403",
            "anonymous_access_allowed": False,
        },
        readiness_checks=[
            "unauthenticated request to custom hostname returns 403 or Access challenge",
            "authenticated request renders exact canonical release banner",
            "site artifacts match P6 sha256 manifest",
            "no network request leaves the static package except Access authentication",
            "Daniel opens the authenticated URL and records manual acceptance",
        ],
        public_exposure_controls=[
            "do not treat the pages.dev URL as accepted",
            "do not deploy until Pages and Access authority are available in the same run",
            "bind Access before declaring Daniel acceptance",
            "if Access binding fails after upload, delete or disable the Pages project",
        ],
        rollback=[
            "delete the Pages deployment or project",
            "remove the custom hostname binding",
            "disable the Access application",
            "keep production retrieval lexical",
            "verify no Source/R2/Qdrant/pointer/traffic mutation occurred",
        ],
    )


def build_p7_live_url_readiness(
    *,
    output_path: Path = P7_REPORT_PATH,
    include_self_digest: bool = True,
) -> P7LiveUrlReadinessReport:
    p6_report = build_p6_internal_product_deployment()
    observations = observed_p7_capabilities()
    missing_authority = [
        item.permission for item in required_p7_authority() if not item.currently_available
    ]
    report = P7LiveUrlReadinessReport(
        issue_number=P7_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        p6_schema_version=P6_SCHEMA,
        p6_package_status=p6_report.status,
        capability_observations=observations,
        required_authority=required_p7_authority(),
        deployment_plan=p7_deployment_plan(),
        acceptance_gate=P7AcceptanceGate(
            status="blocked_pending_cloudflare_pages_access_authority",
            live_url_status="pending_cloudflare_access_binding",
            manual_daniel_acceptance="pending_authenticated_url",
            blocker="Cloudflare API token lacks Pages and Access authority.",
            required_next_authority=missing_authority,
        ),
        authority=P6AuthorityBoundary(),
        bounded_evidence_rules=[
            "record status classes, counts, and permission names only",
            "never record API tokens, raw headers, full raw error bodies, or secret values",
            "do not record arbitrary exception text from live probes",
            "do not record a live URL as accepted until Access binding and Daniel acceptance pass",
        ],
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
