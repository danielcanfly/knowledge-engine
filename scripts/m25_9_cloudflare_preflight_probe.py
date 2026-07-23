#!/usr/bin/env python3
"""Read-only Cloudflare credential and resource-identity diagnostic for M25.9."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

API_ROOT = "https://api.cloudflare.com/client/v4"
MAX_RESPONSE_BYTES = 512 * 1024
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
ACCOUNT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True)
class HttpResponse:
    status: int | None
    content_type: str | None
    body: bytes
    network_error: str | None = None


Requester = Callable[[str, str, dict[str, str], float], HttpResponse]


def bounded_read(stream: Any, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    body = stream.read(limit + 1)
    if len(body) > limit:
        return body[:limit]
    return body


def default_requester(
    method: str,
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> HttpResponse:
    request = urllib.request.Request(url=url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                content_type=response.headers.get_content_type(),
                body=bounded_read(response),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            content_type=exc.headers.get_content_type() if exc.headers else None,
            body=bounded_read(exc),
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        return HttpResponse(
            status=None,
            content_type=None,
            body=b"",
            network_error=type(reason).__name__,
        )


def parse_json_object(body: bytes) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def first_error_code(payload: dict[str, Any] | None) -> int | str | None:
    if not payload:
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    code = first.get("code")
    return code if isinstance(code, (int, str)) else None


def classify_response(response: HttpResponse, success: bool | None) -> tuple[str, bool]:
    status = response.status
    if status is None:
        return "network_error", True
    if status == 401:
        return "token_invalid_expired_disabled_or_malformed", False
    if status == 403:
        return "permission_or_resource_scope_failure", False
    if status == 404:
        return "resource_identity_or_permission_concealment", False
    if status == 429:
        return "rate_limited", True
    if status >= 500:
        return "cloudflare_upstream_failure", True
    if 200 <= status < 300 and success is True:
        return "pass", False
    if 200 <= status < 300:
        return "cloudflare_success_false_or_invalid_json", False
    return "http_failure", False


def endpoint_details(endpoint: str, payload: dict[str, Any] | None, project: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not payload:
        return result
    value = payload.get("result")
    if endpoint.endswith("token_verify") and isinstance(value, dict):
        status = value.get("status")
        if status in {"active", "disabled", "expired"}:
            result["token_status"] = status
    elif endpoint == "pages_projects" and isinstance(value, list):
        names = {
            item.get("name")
            for item in value
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        result["result_count"] = len(value)
        result["target_project_found"] = project in names
    elif endpoint == "pages_deployments" and isinstance(value, list):
        result["result_count"] = len(value)
        if value and isinstance(value[0], dict):
            deployment_id = value[0].get("id")
            if isinstance(deployment_id, str) and deployment_id:
                result["latest_deployment_id"] = deployment_id
    elif endpoint == "access_apps" and isinstance(value, list):
        result["target_application_found"] = bool(value)
        result["target_match_count"] = len(value)
    elif endpoint == "access_organization" and isinstance(value, dict):
        result["auth_domain_present"] = bool(value.get("auth_domain"))
    return result


def probe_endpoint(
    *,
    credential_label: str,
    endpoint: str,
    url: str,
    token: str,
    project: str,
    requester: Requester,
    timeout: float,
    max_attempts: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    final_record: dict[str, Any] = {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "knowledge-engine-m25.9-read-only-preflight/1",
    }
    for attempt in range(1, max_attempts + 1):
        response = requester("GET", url, headers, timeout)
        payload = parse_json_object(response.body)
        success = payload.get("success") if payload else None
        success_bool = success if isinstance(success, bool) else None
        decision, retryable = classify_response(response, success_bool)
        record: dict[str, Any] = {
            "credential_label": credential_label,
            "endpoint": endpoint,
            "attempt": attempt,
            "http_method": "GET",
            "http_status": response.status,
            "content_type": response.content_type,
            "cloudflare_success": success_bool,
            "cloudflare_error_code": first_error_code(payload),
            "cloudflare_error_category": decision,
            "retryable": retryable,
            "response_bytes": len(response.body),
            "response_sha256": hashlib.sha256(response.body).hexdigest(),
            "raw_response_recorded": False,
            "network_error_category": response.network_error,
        }
        record.update(endpoint_details(endpoint, payload, project))
        records.append(record)
        final_record = record
        if not retryable or attempt == max_attempts:
            break
        time.sleep(min(2 ** (attempt - 1), 4))
    return records, final_record


def capability_pass(record: dict[str, Any] | None) -> bool:
    return bool(record and record.get("cloudflare_error_category") == "pass")


def token_active(records: dict[str, dict[str, Any]]) -> bool:
    for endpoint in ("account_token_verify", "user_token_verify"):
        record = records.get(endpoint)
        if capability_pass(record) and record.get("token_status") == "active":
            return True
    return False


def build_credential_summary(
    label: str,
    present: bool,
    final_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pages_deployments = final_records.get("pages_deployments")
    pages_projects = final_records.get("pages_projects")
    access_apps = final_records.get("access_apps")
    access_org = final_records.get("access_organization")
    return {
        "credential_label": label,
        "secret_present": present,
        "token_active": token_active(final_records),
        "pages_projects_read": capability_pass(pages_projects),
        "target_pages_project_found": bool(
            pages_projects and pages_projects.get("target_project_found")
        ),
        "pages_deployments_read": capability_pass(pages_deployments),
        "previous_pages_deployment_captured": bool(
            pages_deployments and pages_deployments.get("latest_deployment_id")
        ),
        "access_apps_read": capability_pass(access_apps),
        "target_access_application_found": bool(
            access_apps and access_apps.get("target_application_found")
        ),
        "access_organization_read": capability_pass(access_org),
        "access_auth_domain_present": bool(access_org and access_org.get("auth_domain_present")),
    }


def choose_topology(summaries: dict[str, dict[str, Any]]) -> tuple[str, str]:
    pages = summaries["pages_dedicated"]
    access = summaries["access_dedicated"]
    generic = summaries["generic_cloudflare"]
    pages_ready = pages["pages_deployments_read"] and pages["target_pages_project_found"]
    access_ready = (
        access["access_apps_read"]
        and access["target_access_application_found"]
        and access["access_organization_read"]
        and access["access_auth_domain_present"]
    )
    generic_pages_ready = (
        generic["pages_deployments_read"] and generic["target_pages_project_found"]
    )
    generic_access_ready = (
        generic["access_apps_read"]
        and generic["target_access_application_found"]
        and generic["access_organization_read"]
        and generic["access_auth_domain_present"]
    )
    if pages_ready and access_ready:
        return "explicit_dedicated_tokens", "dedicated_pages_and_access_credentials_pass"
    if generic_pages_ready and generic_access_ready:
        if pages["secret_present"] or access["secret_present"]:
            return (
                "verified_generic_temporary",
                "dedicated_credential_failure_or_scope_mismatch_generic_passes",
            )
        return "verified_generic_temporary", "dedicated_credentials_absent_generic_passes"
    if pages_ready and generic_access_ready:
        return "explicit_mixed", "dedicated_pages_and_generic_access_pass"
    if generic_pages_ready and access_ready:
        return "explicit_mixed", "generic_pages_and_dedicated_access_pass"
    return "blocked", infer_blocker(summaries)


def infer_blocker(summaries: dict[str, dict[str, Any]]) -> str:
    present = [summary for summary in summaries.values() if summary["secret_present"]]
    if not present:
        return "all_effective_cloudflare_secrets_missing"
    if not any(summary["token_active"] for summary in present):
        return "no_effective_credential_verified_active"
    if not any(summary["pages_deployments_read"] for summary in present):
        return "pages_permission_resource_or_identity_failure"
    if not any(summary["target_pages_project_found"] for summary in present):
        return "target_pages_project_not_observable"
    if not any(summary["access_apps_read"] for summary in present):
        return "access_apps_permission_or_resource_failure"
    if not any(summary["target_access_application_found"] for summary in present):
        return "target_access_application_not_observable"
    if not any(summary["access_organization_read"] for summary in present):
        return "access_organization_permission_or_resource_failure"
    return "credential_topology_incomplete"


def run_diagnostic(
    *,
    account_id: str,
    project: str,
    internal_hostname: str,
    credentials: dict[str, str],
    requester: Requester = default_requester,
    timeout: float = 20.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    account_valid = bool(ACCOUNT_ID_PATTERN.fullmatch(account_id))
    probes: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    encoded_project = urllib.parse.quote(project, safe="")
    encoded_domain = urllib.parse.urlencode({"domain": internal_hostname, "exact": "true"})
    endpoints = {
        "user_token_verify": f"{API_ROOT}/user/tokens/verify",
        "account_token_verify": f"{API_ROOT}/accounts/{account_id}/tokens/verify",
        "pages_projects": f"{API_ROOT}/accounts/{account_id}/pages/projects?per_page=100",
        "pages_deployments": (
            f"{API_ROOT}/accounts/{account_id}/pages/projects/{encoded_project}/deployments"
            "?env=production&per_page=20"
        ),
        "access_apps": f"{API_ROOT}/accounts/{account_id}/access/apps?{encoded_domain}",
        "access_organization": f"{API_ROOT}/accounts/{account_id}/access/organizations",
    }
    for label, token in credentials.items():
        final_records: dict[str, dict[str, Any]] = {}
        if token:
            for endpoint, url in endpoints.items():
                endpoint_records, final_record = probe_endpoint(
                    credential_label=label,
                    endpoint=endpoint,
                    url=url,
                    token=token,
                    project=project,
                    requester=requester,
                    timeout=timeout,
                    max_attempts=max_attempts,
                )
                probes.extend(endpoint_records)
                final_records[endpoint] = final_record
        summaries[label] = build_credential_summary(label, bool(token), final_records)
    topology, root_cause = choose_topology(summaries)
    evidence: dict[str, Any] = {
        "schema_version": "knowledge-engine-m25-9-cloudflare-preflight/v1",
        "status": "diagnostic_complete",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mutations": 0,
        "http_methods_used": ["GET"],
        "raw_response_bodies_recorded": False,
        "authorization_headers_recorded": False,
        "secret_values_recorded": False,
        "account_id_shape_valid": account_valid,
        "account_id_sha256": hashlib.sha256(account_id.encode()).hexdigest(),
        "pages_project": project,
        "internal_hostname_sha256": hashlib.sha256(internal_hostname.encode()).hexdigest(),
        "credential_summaries": summaries,
        "probes": probes,
        "recommended_credential_topology": topology,
        "root_cause_classification": root_cause,
    }
    evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    parser.add_argument("--project", default=os.environ.get("PAGES_PROJECT", ""))
    parser.add_argument("--internal-hostname", default=os.environ.get("INTERNAL_HOSTNAME", ""))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    credentials = {
        "pages_dedicated": os.environ.get("CLOUDFLARE_PAGES_ACCESS_TOKEN", ""),
        "access_dedicated": os.environ.get("CLOUDFLARE_ACCESS_READ_TOKEN", ""),
        "generic_cloudflare": os.environ.get("CLOUDFLARE_API_TOKEN", ""),
    }
    evidence = run_diagnostic(
        account_id=args.account_id,
        project=args.project,
        internal_hostname=args.internal_hostname,
        credentials=credentials,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "mutations": evidence["mutations"],
                "recommended_credential_topology": evidence[
                    "recommended_credential_topology"
                ],
                "root_cause_classification": evidence["root_cause_classification"],
                "evidence_sha256": evidence["evidence_sha256"],
            },
            sort_keys=True,
        )
    )
    if not evidence["account_id_shape_valid"] or not args.project or not args.internal_hostname:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
