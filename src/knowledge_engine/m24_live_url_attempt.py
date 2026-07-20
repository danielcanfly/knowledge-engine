from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import P6AuthorityBoundary
from .m24_live_url_readiness import P7_PROJECT_NAME
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)

P8_SCHEMA = "knowledge-engine-m24-p8-live-url-attempt/v1"
P8_ISSUE_NUMBER = 1001
P8_ROOT = Path("pilot/m24/live-url-attempt")
P8_REPORT_PATH = P8_ROOT / "m24-p8-live-url-attempt.json"


class P8LifecycleStep(BaseModel):
    step: str
    status: Literal["success", "blocked", "not_attempted"]
    bounded_evidence: dict[str, Any]


class P8RollbackEvidence(BaseModel):
    required: bool
    completed: bool
    reason: str
    absence_proof: dict[str, Any]


class P8AcceptanceState(BaseModel):
    status: Literal[
        "rolled_back_pending_cloudflare_access_enablement",
        "authenticated_live_url_accepted",
    ]
    live_url_status: Literal[
        "rolled_back_after_unprotected_pages_upload",
        "authenticated_live_url_bound",
    ]
    manual_daniel_acceptance: Literal[
        "pending_access_enablement",
        "accepted_by_daniel",
    ]
    required_next_action: str


class P8LiveUrlAttemptReport(BaseModel):
    schema_version: str = P8_SCHEMA
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    pages_project_name: str
    lifecycle: list[P8LifecycleStep]
    rollback: P8RollbackEvidence
    acceptance: P8AcceptanceState
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


def build_p8_live_url_attempt(
    *,
    output_path: Path = P8_REPORT_PATH,
    include_self_digest: bool = True,
) -> P8LiveUrlAttemptReport:
    report = P8LiveUrlAttemptReport(
        issue_number=P8_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        pages_project_name=P7_PROJECT_NAME,
        lifecycle=[
            P8LifecycleStep(
                step="token_capability_probe",
                status="success",
                bounded_evidence={
                    "token_verified": True,
                    "pages_project_create_authorized": True,
                    "pages_deploy_authorized": True,
                    "access_api_status": "not_enabled",
                    "token_value_recorded": False,
                },
            ),
            P8LifecycleStep(
                step="pages_project_create",
                status="success",
                bounded_evidence={
                    "project_name": P7_PROJECT_NAME,
                    "production_branch": "main",
                    "project_id_recorded": False,
                },
            ),
            P8LifecycleStep(
                step="pages_direct_upload",
                status="success",
                bounded_evidence={
                    "uploaded_file_count": 9,
                    "deployment_environment": "production",
                    "branch": "main",
                    "deployment_short_id": "6fbb3abe",
                    "preview_url_recorded": False,
                },
            ),
            P8LifecycleStep(
                step="access_application_binding",
                status="blocked",
                bounded_evidence={
                    "http_status_class": "4xx",
                    "cloudflare_error_code": 9999,
                    "blocker": "cloudflare_access_not_enabled",
                    "raw_error_body_recorded": False,
                },
            ),
            P8LifecycleStep(
                step="custom_hostname_dns_binding",
                status="not_attempted",
                bounded_evidence={
                    "reason": "access_application_binding_blocked_first",
                    "target_dns_records_created": 0,
                },
            ),
        ],
        rollback=P8RollbackEvidence(
            required=True,
            completed=True,
            reason="Pages upload produced an unprotected preview before Access was enabled.",
            absence_proof={
                "pages_project_get_after_delete": {
                    "http_status": 404,
                    "cloudflare_error_code": 8000007,
                    "state": "absent",
                },
                "custom_hostname_dns_records": {
                    "name": "m24-internal.danielcanfly.com",
                    "type": "CNAME",
                    "count": 0,
                },
                "access_api_after_rollback": {
                    "http_status_class": "4xx",
                    "cloudflare_error_code": 9999,
                    "state": "access_not_enabled",
                },
            },
        ),
        acceptance=P8AcceptanceState(
            status="rolled_back_pending_cloudflare_access_enablement",
            live_url_status="rolled_back_after_unprotected_pages_upload",
            manual_daniel_acceptance="pending_access_enablement",
            required_next_action=(
                "Enable Cloudflare Access in the dashboard, then rerun the Pages "
                "upload and Access self-hosted application binding."
            ),
        ),
        authority=P6AuthorityBoundary(),
        evidence_hygiene=[
            "no Cloudflare token values recorded",
            "no raw headers recorded",
            "no raw API error bodies recorded",
            "no preview URL committed",
            "no public deployment left active after Access blocker",
        ],
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
