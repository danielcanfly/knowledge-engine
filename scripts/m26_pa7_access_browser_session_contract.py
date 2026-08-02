#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

API_ROOT = "https://api.cloudflare.com/client/v4"
SCHEMA = "knowledge-engine-m26-pa7-access-browser-session-contract/v1"
TARGET_PATHS = ("/ask", "/full-graph")
READONLY_FIELDS = {
    "aud",
    "created_at",
    "domain_type",
    "id",
    "uid",
    "updated_at",
}


class AccessContractFailure(RuntimeError):
    pass


class CloudflareApiFailure(RuntimeError):
    pass


Requester = Callable[
    [str, str, dict[str, str], bytes | None, float],
    tuple[int | None, dict[str, Any] | None, str | None],
]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def default_requester(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None,
    timeout: float,
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    request = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload if isinstance(payload, dict) else None, None
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        return exc.code, payload if isinstance(payload, dict) else None, None
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return None, None, type(reason).__name__


def request_json(
    *,
    method: str,
    url: str,
    token: str,
    requester: Requester,
    timeout: float,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "knowledge-engine-m26-pa7-access-session-contract/1",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, response, network_error = requester(method, url, headers, data, timeout)
    if network_error or status is None:
        raise CloudflareApiFailure(f"network_error:{network_error}")
    if not response or response.get("success") is not True:
        code = None
        errors = response.get("errors") if response else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            code = errors[0].get("code")
        raise CloudflareApiFailure(f"http_{status}:cloudflare_error_{code}")
    result = response.get("result")
    if not isinstance(result, (dict, list)):
        raise CloudflareApiFailure("cloudflare_result_shape_invalid")
    return response


def list_access_apps(
    *,
    account_id: str,
    token: str,
    requester: Requester = default_requester,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    for page in range(1, 11):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        payload = request_json(
            method="GET",
            url=f"{API_ROOT}/accounts/{account_id}/access/apps?{query}",
            token=token,
            requester=requester,
            timeout=timeout,
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise CloudflareApiFailure("access_apps_result_not_list")
        apps.extend(item for item in result if isinstance(item, dict))
        info = payload.get("result_info")
        total_pages = int(info.get("total_pages", page)) if isinstance(info, dict) else page
        if page >= total_pages:
            break
    return apps


def get_access_app(
    *,
    account_id: str,
    token: str,
    app_id: str,
    requester: Requester = default_requester,
    timeout: float = 20.0,
) -> dict[str, Any]:
    payload = request_json(
        method="GET",
        url=f"{API_ROOT}/accounts/{account_id}/access/apps/{urllib.parse.quote(app_id, safe='')}",
        token=token,
        requester=requester,
        timeout=timeout,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise CloudflareApiFailure("access_app_result_not_object")
    return result


def get_zone_id(
    *,
    zone_name: str,
    token: str,
    requester: Requester = default_requester,
    timeout: float = 20.0,
) -> str:
    query = urllib.parse.urlencode({"name": zone_name, "per_page": 50})
    payload = request_json(
        method="GET",
        url=f"{API_ROOT}/zones?{query}",
        token=token,
        requester=requester,
        timeout=timeout,
    )
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 1:
        raise CloudflareApiFailure("zone_lookup_not_unique")
    zone_id = result[0].get("id") if isinstance(result[0], dict) else None
    if not isinstance(zone_id, str) or not zone_id:
        raise CloudflareApiFailure("zone_lookup_missing_id")
    return zone_id


def _domain_values(app: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    domain = app.get("domain")
    if isinstance(domain, str) and domain.strip():
        values.append(domain.strip())
    for key in ("self_hosted_domains", "self_hosted_domain"):
        value = app.get(key)
        if isinstance(value, list):
            values.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
        elif isinstance(value, str) and value.strip():
            values.append(value.strip())
    return sorted(set(values))


def _split_access_domain(value: str) -> tuple[str, str]:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlparse(candidate)
    host = (parsed.hostname or "").strip().lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/") and not path.endswith("*/"):
        path = path.rstrip("/")
    if "*" in value and parsed.path in {"", "/"}:
        path = "/*"
    return host, path or "/"


def _path_matches(app_path: str, target_path: str) -> bool:
    if app_path in {"", "/", "/*"}:
        return True
    normalized = app_path.rstrip("/")
    if normalized.endswith("*"):
        prefix = normalized[:-1].rstrip("/")
        return target_path == prefix or target_path.startswith(prefix + "/")
    return target_path == normalized or target_path.startswith(normalized + "/")


def _host_matches(app_host: str, target_host: str) -> bool:
    if app_host == target_host:
        return True
    if app_host.startswith("*."):
        suffix = app_host[1:]
        return target_host.endswith(suffix)
    return False


def _domain_class(value: str, target_host: str) -> str:
    host, path = _split_access_domain(value)
    if host == target_host and path in {"", "/", "/*"}:
        return "target_host_root"
    if host == target_host:
        return "target_host_path_specific"
    if _host_matches(host, target_host):
        return "wildcard_host_match"
    return "non_target"


def _matches_path(app: Mapping[str, Any], target_host: str, target_path: str) -> bool:
    for domain in _domain_values(app):
        host, path = _split_access_domain(domain)
        if _host_matches(host, target_host) and _path_matches(path, target_path):
            return True
    return False


def _is_root_target_app(app: Mapping[str, Any], target_host: str) -> bool:
    return any(
        _split_access_domain(domain) == (target_host, "/")
        or _domain_class(domain, target_host) == "target_host_root"
        for domain in _domain_values(app)
    )


def _session_duration_class(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if len(text) > 32:
        return "present_long"
    return "present"


def _sanitized_app(app: Mapping[str, Any], target_host: str) -> dict[str, Any]:
    app_id = str(app.get("id") or "")
    same_site = str(app.get("same_site_cookie_attribute") or "").strip().lower()
    path_cookie = app.get("path_cookie_attribute")
    path_cookie_raw_class = "boolean" if isinstance(path_cookie, bool) else "omitted_or_null"
    path_cookie_effective = bool(path_cookie) if isinstance(path_cookie, bool) else False
    domains = _domain_values(app)
    return {
        "app_id_sha256": sha256_text(app_id) if app_id else None,
        "app_type": str(app.get("type") or ""),
        "domain_count": len(domains),
        "domain_classes": sorted({_domain_class(domain, target_host) for domain in domains}),
        "same_site_cookie_attribute": same_site or "missing",
        "path_cookie_attribute": bool(path_cookie) if isinstance(path_cookie, bool) else None,
        "path_cookie_attribute_effective": path_cookie_effective,
        "path_cookie_attribute_raw_class": path_cookie_raw_class,
        "session_duration_class": _session_duration_class(app.get("session_duration")),
        "aud_sha256": sha256_text(str(app.get("aud"))) if app.get("aud") else None,
    }


def build_contract_evidence(
    *,
    apps: Sequence[Mapping[str, Any]],
    target_hostname: str,
    target_paths: Sequence[str] = TARGET_PATHS,
) -> dict[str, Any]:
    target_host = target_hostname.strip().lower().rstrip(".")
    root_apps = [app for app in apps if _is_root_target_app(app, target_host)]
    root_app = root_apps[0] if root_apps else None
    path_matches = {
        path: [app for app in apps if _matches_path(app, target_host, path)]
        for path in target_paths
    }
    path_specific_overlaps = {
        path: [
            _sanitized_app(app, target_host)
            for app in matches
            if any(
                _domain_class(domain, target_host) == "target_host_path_specific"
                for domain in _domain_values(app)
            )
        ]
        for path, matches in path_matches.items()
    }
    root_sanitized = _sanitized_app(root_app, target_host) if root_app else None
    reason = None
    if len(root_apps) != 1:
        reason = "target_access_root_application_not_unique"
    elif root_sanitized is None:
        reason = "target_access_root_application_missing"
    else:
        same_site = str(root_sanitized["same_site_cookie_attribute"]).lower()
        if same_site == "strict":
            reason = "same_site_strict_confirmed_redirect_loop_risk"
        elif same_site not in {"lax", "none"}:
            reason = "same_site_cookie_attribute_not_machine_readable_or_not_allowed"
        elif root_sanitized["path_cookie_attribute_effective"] is not False:
            reason = "path_cookie_attribute_must_be_disabled_for_ask_full_graph_session"
        elif any(path_specific_overlaps[path] for path in target_paths):
            reason = "path_specific_access_application_overlap"
        elif any(len(matches) != 1 for matches in path_matches.values()):
            reason = "target_path_access_application_match_not_unique"

    return {
        "schema_version": SCHEMA,
        "status": "pass" if reason is None else "blocked",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target_hostname_sha256": sha256_text(target_host),
        "target_paths": list(target_paths),
        "target_root_app_count": len(root_apps),
        "target_root_app": root_sanitized,
        "target_path_match_counts": {
            path: len(matches) for path, matches in path_matches.items()
        },
        "path_specific_overlap_counts": {
            path: len(path_specific_overlaps[path]) for path in target_paths
        },
        "path_specific_overlaps": path_specific_overlaps,
        "matching_app_count": len(
            {
                str(app.get("id") or id(app))
                for matches in path_matches.values()
                for app in matches
            }
        ),
        "raw_domains_recorded": False,
        "raw_cookie_values_recorded": False,
        "raw_login_urls_recorded": False,
        "raw_tokens_recorded": False,
        "http_methods_used": ["GET"],
        "mutations": 0,
        "root_cause_classification": reason or "access_browser_session_contract_pass",
        "documentation_basis": {
            "same_site_strict_redirect_loop_documented": True,
            "path_cookie_reauth_between_paths_documented": True,
        },
    }


def evidence_with_sha(evidence: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(evidence)
    data["evidence_sha256"] = sha256_text(
        json.dumps(data, sort_keys=True, separators=(",", ":"))
    )
    return data


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    data = evidence_with_sha(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def inspect_contract(
    *,
    account_id: str,
    access_token: str,
    target_hostname: str,
    evidence_output: Path,
    requester: Requester = default_requester,
    timeout: float = 20.0,
) -> dict[str, Any]:
    apps = list_access_apps(
        account_id=account_id,
        token=access_token,
        requester=requester,
        timeout=timeout,
    )
    evidence = build_contract_evidence(apps=apps, target_hostname=target_hostname)
    evidence = write_evidence(evidence_output, evidence)
    if evidence["status"] != "pass":
        raise AccessContractFailure(str(evidence["root_cause_classification"]))
    return evidence


def _update_payload(app: Mapping[str, Any], *, same_site: str, path_cookie: bool) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in app.items()
        if key not in READONLY_FIELDS and value is not None
    }
    payload["same_site_cookie_attribute"] = same_site
    payload["path_cookie_attribute"] = path_cookie
    return payload


def repair_contract(
    *,
    account_id: str,
    read_token: str,
    write_token: str,
    target_hostname: str,
    before_output: Path,
    repair_output: Path,
    after_output: Path,
    requester: Requester = default_requester,
    timeout: float = 20.0,
    preferred_same_site: str = "lax",
    zone_name: str = "",
) -> dict[str, Any]:
    apps = list_access_apps(
        account_id=account_id,
        token=read_token,
        requester=requester,
        timeout=timeout,
    )
    before = build_contract_evidence(apps=apps, target_hostname=target_hostname)
    write_evidence(before_output, before)
    root = before.get("target_root_app") or {}
    reason = str(before.get("root_cause_classification"))
    if before["status"] == "pass":
        repair = {
            "schema_version": SCHEMA,
            "status": "noop_contract_already_passed",
            "mutations": 0,
            "root_cause_classification": reason,
            "raw_domains_recorded": False,
            "raw_tokens_recorded": False,
        }
        write_evidence(repair_output, repair)
        before = write_evidence(after_output, before)
        return before
    if reason not in {
        "same_site_strict_confirmed_redirect_loop_risk",
        "path_cookie_attribute_must_be_disabled_for_ask_full_graph_session",
    }:
        repair = {
            "schema_version": SCHEMA,
            "status": "blocked_unrepaired_readonly_diagnosis_required",
            "mutations": 0,
            "root_cause_classification": reason,
            "raw_domains_recorded": False,
            "raw_tokens_recorded": False,
        }
        write_evidence(repair_output, repair)
        raise AccessContractFailure(reason)
    root_apps = [app for app in apps if _is_root_target_app(app, target_hostname.strip().lower())]
    if len(root_apps) != 1 or not root.get("app_id_sha256"):
        raise AccessContractFailure("target_access_root_application_not_unique")
    target_app = root_apps[0]
    app_id = str(target_app["id"])
    try:
        detailed = get_access_app(
            account_id=account_id,
            token=read_token,
            app_id=app_id,
            requester=requester,
            timeout=timeout,
        )
        detail_read_token_class = "read_token"
    except CloudflareApiFailure as read_exc:
        try:
            detailed = get_access_app(
                account_id=account_id,
                token=write_token,
                app_id=app_id,
                requester=requester,
                timeout=timeout,
            )
            detail_read_token_class = "write_token"
        except CloudflareApiFailure as write_exc:
            repair = {
                "schema_version": SCHEMA,
                "status": "blocked_access_application_detail_read_failed",
                "mutations": 0,
                "root_cause_classification": reason,
                "read_detail_error_class": str(read_exc),
                "write_detail_error_class": str(write_exc),
                "raw_domains_recorded": False,
                "raw_tokens_recorded": False,
            }
            write_evidence(repair_output, repair)
            raise
    update_payload = _update_payload(
        detailed,
        same_site=preferred_same_site,
        path_cookie=False,
    )
    update_scope = "account"
    account_update_error = None
    try:
        update_access_application(
            scope_kind="accounts",
            scope_id=account_id,
            app_id=app_id,
            token=write_token,
            requester=requester,
            timeout=timeout,
            payload=update_payload,
        )
    except CloudflareApiFailure as exc:
        account_update_error = str(exc)
        if not zone_name:
            repair = {
                "schema_version": SCHEMA,
                "status": "blocked_access_application_update_failed",
                "mutations": 0,
                "root_cause_classification": reason,
                "update_error_class": account_update_error,
                "detail_read_token_class": detail_read_token_class,
                "target_app_id_sha256": sha256_text(app_id),
                "raw_domains_recorded": False,
                "raw_tokens_recorded": False,
                "zone_name_recorded": False,
            }
            write_evidence(repair_output, repair)
            raise
        try:
            zone_id = get_zone_id(
                zone_name=zone_name,
                token=write_token,
                requester=requester,
                timeout=timeout,
            )
            update_access_application(
                scope_kind="zones",
                scope_id=zone_id,
                app_id=app_id,
                token=write_token,
                requester=requester,
                timeout=timeout,
                payload=update_payload,
            )
            update_scope = "zone"
        except CloudflareApiFailure as zone_exc:
            repair = {
                "schema_version": SCHEMA,
                "status": "blocked_access_application_update_failed",
                "mutations": 0,
                "root_cause_classification": reason,
                "account_update_error_class": account_update_error,
                "zone_update_error_class": str(zone_exc),
                "detail_read_token_class": detail_read_token_class,
                "target_app_id_sha256": sha256_text(app_id),
                "raw_domains_recorded": False,
                "raw_tokens_recorded": False,
                "zone_name_recorded": False,
            }
            write_evidence(repair_output, repair)
            raise
    repair = {
        "schema_version": SCHEMA,
        "status": "access_browser_session_contract_repaired",
        "mutations": 1,
        "mutation_kind": "cloudflare_access_application_update",
        "detail_read_token_class": detail_read_token_class,
        "update_scope": update_scope,
        "target_app_id_sha256": sha256_text(app_id),
        "before_same_site_cookie_attribute": root.get("same_site_cookie_attribute"),
        "after_same_site_cookie_attribute": preferred_same_site,
        "before_path_cookie_attribute": root.get("path_cookie_attribute"),
        "after_path_cookie_attribute": False,
        "raw_domains_recorded": False,
        "raw_tokens_recorded": False,
        "zone_name_recorded": False,
    }
    write_evidence(repair_output, repair)
    after_apps = list_access_apps(
        account_id=account_id,
        token=read_token,
        requester=requester,
        timeout=timeout,
    )
    after = build_contract_evidence(apps=after_apps, target_hostname=target_hostname)
    write_evidence(after_output, after)
    if after["status"] != "pass":
        raise AccessContractFailure(str(after["root_cause_classification"]))
    return after


def update_access_application(
    *,
    scope_kind: str,
    scope_id: str,
    app_id: str,
    token: str,
    requester: Requester,
    timeout: float,
    payload: Mapping[str, Any],
) -> None:
    if scope_kind not in {"accounts", "zones"}:
        raise CloudflareApiFailure("access_application_update_scope_invalid")
    request_json(
        method="PUT",
        url=(
            f"{API_ROOT}/{scope_kind}/{urllib.parse.quote(scope_id, safe='')}/"
            f"access/apps/{urllib.parse.quote(app_id, safe='')}"
        ),
        token=token,
        requester=requester,
        timeout=timeout,
        payload=payload,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    inspect.add_argument(
        "--access-token",
        default=os.environ.get("CLOUDFLARE_ACCESS_READ_TOKEN", ""),
    )
    inspect.add_argument("--target-hostname", default=os.environ.get("INTERNAL_HOSTNAME", ""))
    inspect.add_argument("--evidence-output", type=Path, required=True)
    inspect.add_argument("--timeout", type=float, default=20.0)
    repair = subparsers.add_parser("repair")
    repair.add_argument("--account-id", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""))
    repair.add_argument("--read-token", default=os.environ.get("CLOUDFLARE_ACCESS_READ_TOKEN", ""))
    repair.add_argument(
        "--write-token",
        default=os.environ.get("CLOUDFLARE_ACCESS_WRITE_TOKEN")
        or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
    )
    repair.add_argument("--target-hostname", default=os.environ.get("INTERNAL_HOSTNAME", ""))
    repair.add_argument("--before-output", type=Path, required=True)
    repair.add_argument("--repair-output", type=Path, required=True)
    repair.add_argument("--after-output", type=Path, required=True)
    repair.add_argument("--preferred-same-site", choices=("lax", "none"), default="lax")
    repair.add_argument("--zone-name", default=os.environ.get("CLOUDFLARE_ZONE_NAME", ""))
    repair.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def _require(value: str, label: str) -> str:
    if not value:
        raise AccessContractFailure(f"{label}_missing")
    return value


def main() -> int:
    args = parse_args()
    try:
        if args.command == "inspect":
            evidence = inspect_contract(
                account_id=_require(args.account_id, "account_id"),
                access_token=_require(args.access_token, "access_read_token"),
                target_hostname=_require(args.target_hostname, "target_hostname"),
                evidence_output=args.evidence_output,
                timeout=args.timeout,
            )
        else:
            evidence = repair_contract(
                account_id=_require(args.account_id, "account_id"),
                read_token=_require(args.read_token, "access_read_token"),
                write_token=_require(args.write_token, "access_write_token"),
                target_hostname=_require(args.target_hostname, "target_hostname"),
                before_output=args.before_output,
                repair_output=args.repair_output,
                after_output=args.after_output,
                preferred_same_site=args.preferred_same_site,
                zone_name=args.zone_name,
                timeout=args.timeout,
            )
    except (AccessContractFailure, CloudflareApiFailure) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "root_cause_classification": evidence["root_cause_classification"],
                "evidence_sha256": evidence.get("evidence_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
