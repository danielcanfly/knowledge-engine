#!/usr/bin/env python3
"""Explicit-token Cloudflare preflight for the M25.9 full-population pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ROOT = "https://api.cloudflare.com/client/v4"
MAX_RESPONSE_BYTES = 512 * 1024
ACCOUNT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True)
class HttpResponse:
    status: int | None
    content_type: str | None
    body: bytes
    network_error: str | None = None


Requester = Callable[[str, str, dict[str, str], float], HttpResponse]


class PreflightFailure(RuntimeError):
    """Raised after sanitized evidence has enough information to reject the pilot."""


def bounded_read(stream: Any, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    body = stream.read(limit + 1)
    return body[:limit]


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
    except (urllib.error.URLError, TimeoutError) as exc:
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
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None
    value = errors[0].get("code")
    return value if isinstance(value, int | str) else None


def classify(response: HttpResponse, success: bool | None) -> tuple[str, bool]:
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


def request_json(
    *,
    label: str,
    endpoint: str,
    url: str,
    token: str,
    requester: Requester,
    timeout: float,
    max_attempts: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    records: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "knowledge-engine-m25.9-live-preflight/1",
    }
    for attempt in range(1, max_attempts + 1):
        response = requester("GET", url, headers, timeout)
        payload = parse_json_object(response.body)
        success_value = payload.get("success") if payload else None
        success = success_value if isinstance(success_value, bool) else None
        category, retryable = classify(response, success)
        records.append(
            {
                "credential_label": label,
                "endpoint": endpoint,
                "attempt": attempt,
                "http_method": "GET",
                "http_status": response.status,
                "content_type": response.content_type,
                "cloudflare_success": success,
                "cloudflare_error_code": first_error_code(payload),
                "cloudflare_error_category": category,
                "retryable": retryable,
                "response_bytes": len(response.body),
                "response_sha256": hashlib.sha256(response.body).hexdigest(),
                "network_error_category": response.network_error,
                "raw_response_recorded": False,
            }
        )
        if not retryable or attempt == max_attempts:
            break
        time.sleep(min(2 ** (attempt - 1), 4))
    return records, payload


def require_pass(records: list[dict[str, Any]], endpoint: str) -> None:
    if not records or records[-1]["cloudflare_error_category"] != "pass":
        raise PreflightFailure(f"{endpoint}_failed")


def result_list(payload: dict[str, Any] | None, endpoint: str) -> list[dict[str, Any]]:
    value = payload.get("result") if payload else None
    if not isinstance(value, list):
        raise PreflightFailure(f"{endpoint}_result_not_list")
    return [item for item in value if isinstance(item, dict)]


def result_object(payload: dict[str, Any] | None, endpoint: str) -> dict[str, Any]:
    value = payload.get("result") if payload else None
    if not isinstance(value, dict):
        raise PreflightFailure(f"{endpoint}_result_not_object")
    return value


def token_active(payload: dict[str, Any] | None) -> bool:
    result = payload.get("result") if payload else None
    return isinstance(result, dict) and result.get("status") == "active"


def write_env(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, value in values.items():
        if "\n" in value or "\r" in value:
            raise PreflightFailure(f"invalid_runtime_value_{name.lower()}")
    path.write_text("".join(f"{name}={value}\n" for name, value in values.items()))


def finalize_evidence(evidence: dict[str, Any], output: Path) -> None:
    evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def run_preflight(
    *,
    account_id: str,
    pages_project: str,
    internal_hostname: str,
    zone_name: str,
    pages_token: str,
    workers_token: str,
    access_token: str,
    evidence_output: Path,
    runtime_env_output: Path | None,
    requester: Requester = default_requester,
    timeout: float = 20.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": "knowledge-engine-m25-9-live-preflight/v1",
        "status": "blocked",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mutations": 0,
        "http_methods_used": ["GET"],
        "selected_credential_topology": "explicit_dedicated_tokens",
        "credential_labels": {
            "pages": "pages_dedicated",
            "workers": "workers_dedicated",
            "access": "access_dedicated",
        },
        "secret_values_recorded": False,
        "authorization_headers_recorded": False,
        "raw_response_bodies_recorded": False,
        "account_id_shape_valid": bool(ACCOUNT_ID_PATTERN.fullmatch(account_id)),
        "account_id_sha256": hashlib.sha256(account_id.encode()).hexdigest(),
        "pages_project": pages_project,
        "internal_hostname_sha256": hashlib.sha256(internal_hostname.encode()).hexdigest(),
        "zone_name": zone_name,
        "probes": [],
        "root_cause_classification": None,
        "resource_checks": {},
    }
    credentials = {
        "pages_dedicated": pages_token,
        "workers_dedicated": workers_token,
        "access_dedicated": access_token,
    }
    try:
        if not evidence["account_id_shape_valid"]:
            raise PreflightFailure("invalid_account_id_shape")
        if not pages_project or not internal_hostname or not zone_name:
            raise PreflightFailure("required_resource_identity_missing")
        missing = [label for label, value in credentials.items() if not value]
        if missing:
            evidence["missing_credential_labels"] = missing
            raise PreflightFailure("required_dedicated_credentials_missing")

        token_payloads: dict[str, dict[str, Any] | None] = {}
        for label, token in credentials.items():
            records, payload = request_json(
                label=label,
                endpoint="user_token_verify",
                url=f"{API_ROOT}/user/tokens/verify",
                token=token,
                requester=requester,
                timeout=timeout,
                max_attempts=max_attempts,
            )
            evidence["probes"].extend(records)
            require_pass(records, f"{label}_token_verify")
            if not token_active(payload):
                raise PreflightFailure(f"{label}_token_not_active")
            token_payloads[label] = payload

        records, pages_projects_payload = request_json(
            label="pages_dedicated",
            endpoint="pages_projects",
            url=f"{API_ROOT}/accounts/{account_id}/pages/projects?per_page=100",
            token=pages_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "pages_projects")
        projects = result_list(pages_projects_payload, "pages_projects")
        project_found = any(item.get("name") == pages_project for item in projects)
        evidence["resource_checks"]["target_pages_project_found"] = project_found
        if not project_found:
            raise PreflightFailure("target_pages_project_not_found")

        encoded_project = urllib.parse.quote(pages_project, safe="")
        records, deployments_payload = request_json(
            label="pages_dedicated",
            endpoint="pages_deployments",
            url=(
                f"{API_ROOT}/accounts/{account_id}/pages/projects/{encoded_project}/deployments"
                "?env=production&per_page=20"
            ),
            token=pages_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "pages_deployments")
        deployments = result_list(deployments_payload, "pages_deployments")
        previous_deployment_id = deployments[0].get("id") if deployments else None
        previous_present = isinstance(previous_deployment_id, str) and bool(previous_deployment_id)
        evidence["resource_checks"]["previous_pages_deployment_captured"] = previous_present
        if not previous_present:
            raise PreflightFailure("previous_pages_deployment_missing")

        records, scripts_payload = request_json(
            label="workers_dedicated",
            endpoint="workers_scripts",
            url=f"{API_ROOT}/accounts/{account_id}/workers/scripts",
            token=workers_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "workers_scripts")
        result_list(scripts_payload, "workers_scripts")
        evidence["resource_checks"]["workers_scripts_read"] = True

        zone_query = urllib.parse.urlencode(
            {"name": zone_name, "account.id": account_id, "status": "active", "per_page": 50}
        )
        records, zones_payload = request_json(
            label="workers_dedicated",
            endpoint="zones",
            url=f"{API_ROOT}/zones?{zone_query}",
            token=workers_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "zones")
        zones = result_list(zones_payload, "zones")
        zone_ids = [item.get("id") for item in zones if item.get("name") == zone_name]
        zone_id = next((value for value in zone_ids if isinstance(value, str) and value), None)
        evidence["resource_checks"]["target_zone_found"] = bool(zone_id)
        if not zone_id:
            raise PreflightFailure("target_zone_not_found")

        records, routes_payload = request_json(
            label="workers_dedicated",
            endpoint="workers_routes",
            url=f"{API_ROOT}/zones/{zone_id}/workers/routes",
            token=workers_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "workers_routes")
        result_list(routes_payload, "workers_routes")
        evidence["resource_checks"]["workers_routes_read"] = True

        app_query = urllib.parse.urlencode({"domain": internal_hostname, "exact": "true"})
        records, apps_payload = request_json(
            label="access_dedicated",
            endpoint="access_apps",
            url=f"{API_ROOT}/accounts/{account_id}/access/apps?{app_query}",
            token=access_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "access_apps")
        apps = result_list(apps_payload, "access_apps")
        exact_apps = [item for item in apps if item.get("domain") == internal_hostname]
        access_aud = next(
            (
                item.get("aud")
                for item in exact_apps
                if isinstance(item.get("aud"), str) and item.get("aud")
            ),
            None,
        )
        evidence["resource_checks"]["target_access_application_found"] = bool(exact_apps)
        evidence["resource_checks"]["access_audience_present"] = bool(access_aud)
        if not exact_apps or not access_aud:
            raise PreflightFailure("target_access_application_or_audience_missing")

        records, org_payload = request_json(
            label="access_dedicated",
            endpoint="access_organization",
            url=f"{API_ROOT}/accounts/{account_id}/access/organizations",
            token=access_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "access_organization")
        organization = result_object(org_payload, "access_organization")
        auth_domain = organization.get("auth_domain")
        auth_domain_present = isinstance(auth_domain, str) and bool(auth_domain)
        evidence["resource_checks"]["access_auth_domain_present"] = auth_domain_present
        if not auth_domain_present:
            raise PreflightFailure("access_auth_domain_missing")

        write_env(
            runtime_env_output,
            {
                "PREVIOUS_PAGES_DEPLOYMENT_ID": previous_deployment_id,
                "ACCESS_AUD": access_aud,
                "ACCESS_TEAM_DOMAIN": f"https://{auth_domain}",
            },
        )
        evidence["status"] = "pass"
        evidence["root_cause_classification"] = "all_explicit_dedicated_capabilities_pass"
    except PreflightFailure as exc:
        evidence["root_cause_classification"] = str(exc)
    finally:
        finalize_evidence(evidence, evidence_output)

    if evidence["status"] != "pass":
        raise PreflightFailure(str(evidence["root_cause_classification"]))
    return evidence


def run_pages_latest(
    *,
    account_id: str,
    pages_project: str,
    pages_token: str,
    evidence_output: Path,
    runtime_env_output: Path,
    requester: Requester = default_requester,
    timeout: float = 20.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": "knowledge-engine-m25-9-pages-latest/v1",
        "status": "blocked",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mutations": 0,
        "http_methods_used": ["GET"],
        "credential_label": "pages_dedicated",
        "secret_values_recorded": False,
        "authorization_headers_recorded": False,
        "raw_response_bodies_recorded": False,
        "probes": [],
        "root_cause_classification": None,
    }
    try:
        if not pages_token:
            raise PreflightFailure("pages_dedicated_credential_missing")
        encoded_project = urllib.parse.quote(pages_project, safe="")
        records, payload = request_json(
            label="pages_dedicated",
            endpoint="pages_deployments",
            url=(
                f"{API_ROOT}/accounts/{account_id}/pages/projects/{encoded_project}/deployments"
                "?env=production&per_page=20"
            ),
            token=pages_token,
            requester=requester,
            timeout=timeout,
            max_attempts=max_attempts,
        )
        evidence["probes"].extend(records)
        require_pass(records, "pages_deployments")
        deployments = result_list(payload, "pages_deployments")
        deployment_id = deployments[0].get("id") if deployments else None
        if not isinstance(deployment_id, str) or not deployment_id:
            raise PreflightFailure("latest_pages_deployment_missing")
        write_env(runtime_env_output, {"NEW_PAGES_DEPLOYMENT_ID": deployment_id})
        evidence["status"] = "pass"
        evidence["root_cause_classification"] = "latest_pages_deployment_captured"
        evidence["latest_pages_deployment_present"] = True
    except PreflightFailure as exc:
        evidence["root_cause_classification"] = str(exc)
    finally:
        finalize_evidence(evidence, evidence_output)
    if evidence["status"] != "pass":
        raise PreflightFailure(str(evidence["root_cause_classification"]))
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--evidence-output", type=Path, required=True)
    preflight.add_argument("--runtime-env-output", type=Path)
    preflight.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    preflight.add_argument("--pages-project", default=os.environ.get("PAGES_PROJECT", ""))
    preflight.add_argument("--internal-hostname", default=os.environ.get("INTERNAL_HOSTNAME", ""))
    preflight.add_argument("--zone-name", default=os.environ.get("CLOUDFLARE_ZONE_NAME", ""))
    preflight.add_argument("--pages-token", default=os.environ.get("CLOUDFLARE_PAGES_TOKEN", ""))
    preflight.add_argument(
        "--workers-token", default=os.environ.get("CLOUDFLARE_WORKERS_TOKEN", "")
    )
    preflight.add_argument(
        "--access-token", default=os.environ.get("CLOUDFLARE_ACCESS_READ_TOKEN", "")
    )
    preflight.add_argument("--timeout", type=float, default=20.0)
    preflight.add_argument("--max-attempts", type=int, default=3)

    pages_latest = subparsers.add_parser("pages-latest")
    pages_latest.add_argument("--evidence-output", type=Path, required=True)
    pages_latest.add_argument("--runtime-env-output", type=Path, required=True)
    pages_latest.add_argument(
        "--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    )
    pages_latest.add_argument("--pages-project", default=os.environ.get("PAGES_PROJECT", ""))
    pages_latest.add_argument(
        "--pages-token", default=os.environ.get("CLOUDFLARE_PAGES_TOKEN", "")
    )
    pages_latest.add_argument("--timeout", type=float, default=20.0)
    pages_latest.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "preflight":
            evidence = run_preflight(
                account_id=args.account_id,
                pages_project=args.pages_project,
                internal_hostname=args.internal_hostname,
                zone_name=args.zone_name,
                pages_token=args.pages_token,
                workers_token=args.workers_token,
                access_token=args.access_token,
                evidence_output=args.evidence_output,
                runtime_env_output=args.runtime_env_output,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            )
        else:
            evidence = run_pages_latest(
                account_id=args.account_id,
                pages_project=args.pages_project,
                pages_token=args.pages_token,
                evidence_output=args.evidence_output,
                runtime_env_output=args.runtime_env_output,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
            )
    except PreflightFailure as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "root_cause_classification": evidence["root_cause_classification"],
                "evidence_sha256": evidence["evidence_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
