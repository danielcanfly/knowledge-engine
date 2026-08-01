#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareApiError(RuntimeError):
    pass


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(
    *,
    method: str,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - exercised only by live workflow.
        raise CloudflareApiError(f"{method} {path} failed: {exc}") from exc
    parsed = json.loads(body)
    if not parsed.get("success"):
        raise CloudflareApiError(f"{method} {path} returned Cloudflare API failure")
    return parsed


def _query(path: str, params: dict[str, str]) -> str:
    return f"{path}?{urllib.parse.urlencode(params)}"


def _require_hostname_under_zone(hostname: str, zone_name: str) -> None:
    normalized_host = hostname.rstrip(".").lower()
    normalized_zone = zone_name.rstrip(".").lower()
    if not normalized_host or not normalized_zone:
        raise SystemExit("hostname and zone name are required")
    if normalized_host == "trycloudflare.com" or normalized_host.endswith(".trycloudflare.com"):
        raise SystemExit("trycloudflare quick tunnel hostnames are forbidden")
    if normalized_host == normalized_zone:
        raise SystemExit("backend tunnel hostname must be a subdomain, not the zone apex")
    if not normalized_host.endswith(f".{normalized_zone}"):
        raise SystemExit("backend tunnel hostname must be within the configured zone")


def _zone_id(*, token: str, zone_name: str) -> str:
    response = _request(
        method="GET",
        token=token,
        path=_query("/zones", {"name": zone_name, "status": "active", "per_page": "5"}),
    )
    zones = response.get("result", [])
    if len(zones) != 1:
        raise CloudflareApiError(f"expected exactly one active zone for {zone_name}")
    return zones[0]["id"]


def _active_tunnel_by_name(
    *,
    token: str,
    account_id: str,
    tunnel_name: str,
) -> tuple[dict[str, Any] | None, int]:
    response = _request(
        method="GET",
        token=token,
        path=_query(
            f"/accounts/{account_id}/cfd_tunnel",
            {"is_deleted": "false", "per_page": "100"},
        ),
    )
    matches = [
        tunnel
        for tunnel in response.get("result", [])
        if tunnel.get("name") == tunnel_name and not tunnel.get("deleted_at")
    ]
    if not matches:
        return None, 0
    matches.sort(key=lambda tunnel: tunnel.get("created_at") or "", reverse=True)
    return matches[0], len(matches)


def _create_tunnel(*, token: str, account_id: str, tunnel_name: str) -> dict[str, Any]:
    response = _request(
        method="POST",
        token=token,
        path=f"/accounts/{account_id}/cfd_tunnel",
        payload={"config_src": "cloudflare", "name": tunnel_name},
    )
    return response["result"]


def _put_tunnel_config(
    *,
    token: str,
    account_id: str,
    tunnel_id: str,
    hostname: str,
    service: str,
) -> None:
    _request(
        method="PUT",
        token=token,
        path=f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
        payload={
            "config": {
                "ingress": [
                    {"hostname": hostname, "service": service},
                    {"service": "http_status:404"},
                ],
            },
        },
    )


def _tunnel_token(*, token: str, account_id: str, tunnel_id: str) -> str:
    response = _request(
        method="GET",
        token=token,
        path=f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token",
    )
    result = response["result"]
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and isinstance(result.get("token"), str):
        return result["token"]
    raise CloudflareApiError("Cloudflare tunnel token response did not contain a token")


def _upsert_dns_record(
    *,
    token: str,
    zone_id: str,
    hostname: str,
    tunnel_id: str,
) -> tuple[str, str]:
    target = f"{tunnel_id}.cfargotunnel.com"
    existing = _request(
        method="GET",
        token=token,
        path=_query(
            f"/zones/{zone_id}/dns_records",
            {"type": "CNAME", "name": hostname, "per_page": "10"},
        ),
    ).get("result", [])
    payload = {
        "comment": "M26.PA.7 durable backend origin",
        "content": target,
        "name": hostname,
        "proxied": True,
        "ttl": 1,
        "type": "CNAME",
    }
    if existing:
        record_id = existing[0]["id"]
        _request(
            method="PATCH",
            token=token,
            path=f"/zones/{zone_id}/dns_records/{record_id}",
            payload=payload,
        )
        return "updated", record_id
    response = _request(
        method="POST",
        token=token,
        path=f"/zones/{zone_id}/dns_records",
        payload=payload,
    )
    return "created", response["result"]["id"]


def ensure_named_backend_tunnel(
    *,
    token: str,
    account_id: str,
    zone_name: str,
    hostname: str,
    tunnel_name: str,
    service: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    _require_hostname_under_zone(hostname, zone_name)
    zone_id = _zone_id(token=token, zone_name=zone_name)
    tunnel, duplicate_count = _active_tunnel_by_name(
        token=token,
        account_id=account_id,
        tunnel_name=tunnel_name,
    )
    tunnel_reused = tunnel is not None
    if tunnel is None:
        tunnel = _create_tunnel(token=token, account_id=account_id, tunnel_name=tunnel_name)
    tunnel_id = tunnel["id"]
    _put_tunnel_config(
        token=token,
        account_id=account_id,
        tunnel_id=tunnel_id,
        hostname=hostname,
        service=service,
    )
    dns_action, dns_record_id = _upsert_dns_record(
        token=token,
        zone_id=zone_id,
        hostname=hostname,
        tunnel_id=tunnel_id,
    )
    token_value = _tunnel_token(token=token, account_id=account_id, tunnel_id=tunnel_id)
    origin = f"https://{hostname}"
    evidence = {
        "schema_version": "knowledge-engine-m26-pa7-named-backend-tunnel/v1",
        "backend_hostname_sha256": _sha256(hostname),
        "backend_origin_sha256": _sha256(origin),
        "config_src": "cloudflare",
        "dns_record_action": dns_action,
        "dns_record_id_sha256": _sha256(dns_record_id),
        "duplicate_named_tunnel_count": duplicate_count,
        "hostname_present": True,
        "ingress_service": "http_localhost_8080",
        "origin_class": "named_cloudflare_tunnel_https_origin",
        "raw_backend_origin_recorded": False,
        "raw_hostname_recorded": False,
        "status": "pass",
        "target_suffix": "cfargotunnel.com",
        "trycloudflare_rejected": True,
        "tunnel_id_sha256": _sha256(tunnel_id),
        "tunnel_name_sha256": _sha256(tunnel_name),
        "tunnel_reused": tunnel_reused,
        "tunnel_token_recorded": False,
    }
    runtime = {
        "M26_BACKEND_ORIGIN_CLASS": "named_cloudflare_tunnel_https_origin",
        "M26_BACKEND_TUNNEL_ID": tunnel_id,
        "M26_BACKEND_TUNNEL_TOKEN": token_value,
        "M26_QUERY_BACKEND_ORIGIN": origin,
    }
    return evidence, runtime


def _write_env(path: Path, env: dict[str, str]) -> None:
    path.write_text("".join(f"{name}={value}\n" for name, value in sorted(env.items())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    ensure = subparsers.add_parser("ensure")
    ensure.add_argument("--account-id", required=True)
    ensure.add_argument("--zone-name", required=True)
    ensure.add_argument("--hostname", required=True)
    ensure.add_argument("--tunnel-name", required=True)
    ensure.add_argument("--service", default="http://127.0.0.1:8080")
    ensure.add_argument("--evidence-output", required=True)
    ensure.add_argument("--runtime-env-output", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CLOUDFLARE_WORKERS_TOKEN")
    if not token:
        raise SystemExit("CLOUDFLARE_API_TOKEN or CLOUDFLARE_WORKERS_TOKEN is required")
    evidence, runtime = ensure_named_backend_tunnel(
        token=token,
        account_id=args.account_id,
        zone_name=args.zone_name,
        hostname=args.hostname,
        tunnel_name=args.tunnel_name,
        service=args.service,
    )
    evidence_path = Path(args.evidence_output)
    runtime_path = Path(args.runtime_env_output)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    _write_env(runtime_path, runtime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
