#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import sys
from pathlib import Path

try:
    from scripts.m26_pa7_named_backend_tunnel import (
        _query,
        _request,
        _require_hostname_under_zone,
    )
except ModuleNotFoundError:  # pragma: no cover - used when executed as scripts/foo.py.
    from m26_pa7_named_backend_tunnel import _query, _request, _require_hostname_under_zone


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_oracle_hostname(hostname: str) -> str:
    normalized = hostname.strip().rstrip(".").lower()
    if not normalized:
        raise SystemExit("oracle durable origin hostname is required")
    if "://" in normalized or "/" in normalized or "@" in normalized:
        raise SystemExit("oracle durable origin hostname must be host-only")
    if ":" in normalized:
        raise SystemExit("oracle durable origin hostname must not include a port")
    if normalized == "trycloudflare.com" or normalized.endswith(".trycloudflare.com"):
        raise SystemExit("trycloudflare quick tunnel hostnames are forbidden")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        raise SystemExit("oracle durable origin hostname must not be a raw IP address")
    if "." not in normalized:
        raise SystemExit("oracle durable origin hostname must be a DNS hostname")
    return normalized


def oracle_https_origin(hostname: str) -> tuple[dict[str, object], dict[str, str]]:
    normalized = _normalized_oracle_hostname(hostname)
    origin = f"https://{normalized}"
    evidence = {
        "schema_version": "knowledge-engine-m26-pa7-oracle-https-backend-origin/v1",
        "backend_hostname_sha256": _sha256(normalized),
        "backend_origin_sha256": _sha256(origin),
        "hostname_present": True,
        "origin_class": "oracle_stable_hostname_https_reverse_proxy",
        "raw_backend_origin_recorded": False,
        "raw_hostname_recorded": False,
        "status": "pass",
        "trycloudflare_rejected": True,
    }
    runtime = {
        "M26_ORACLE_BACKEND_TLS_HOSTNAME": normalized,
        "M26_QUERY_BACKEND_ORIGIN": origin,
    }
    return evidence, runtime


def _zone_id(*, token: str, zone_name: str) -> str:
    response = _request(
        method="GET",
        token=token,
        path=_query("/zones", {"name": zone_name, "status": "active", "per_page": "5"}),
    )
    zones = response.get("result", [])
    if len(zones) != 1:
        raise SystemExit(f"expected exactly one active zone for {zone_name}")
    return zones[0]["id"]


def cloudflare_dns_a_origin(
    *,
    token: str,
    zone_name: str,
    hostname: str,
    address: str,
) -> tuple[dict[str, object], dict[str, str]]:
    _require_hostname_under_zone(hostname, zone_name)
    ip = str(ipaddress.ip_address(address.strip()))
    zone_id = _zone_id(token=token, zone_name=zone_name)
    existing = _request(
        method="GET",
        token=token,
        path=_query(
            f"/zones/{zone_id}/dns_records",
            {"type": "A", "name": hostname, "per_page": "10"},
        ),
    ).get("result", [])
    payload = {
        "comment": "M26.PA.7 durable backend HTTPS origin",
        "content": ip,
        "name": hostname,
        "proxied": False,
        "ttl": 1,
        "type": "A",
    }
    if existing:
        record_id = existing[0]["id"]
        _request(
            method="PATCH",
            token=token,
            path=f"/zones/{zone_id}/dns_records/{record_id}",
            payload=payload,
        )
        dns_action = "updated"
    else:
        response = _request(
            method="POST",
            token=token,
            path=f"/zones/{zone_id}/dns_records",
            payload=payload,
        )
        record_id = response["result"]["id"]
        dns_action = "created"
    origin = f"https://{hostname}"
    evidence = {
        "schema_version": "knowledge-engine-m26-pa7-cloudflare-dns-a-backend-origin/v1",
        "backend_hostname_sha256": _sha256(hostname),
        "backend_origin_sha256": _sha256(origin),
        "dns_record_action": dns_action,
        "dns_record_id_sha256": _sha256(record_id),
        "hostname_present": True,
        "ip_address_sha256": _sha256(ip),
        "origin_class": "cloudflare_dns_a_to_oracle_https_reverse_proxy",
        "proxied": False,
        "raw_backend_origin_recorded": False,
        "raw_hostname_recorded": False,
        "raw_ip_recorded": False,
        "status": "pass",
        "trycloudflare_rejected": True,
    }
    runtime = {
        "M26_ORACLE_BACKEND_TLS_HOSTNAME": hostname,
        "M26_QUERY_BACKEND_ORIGIN": origin,
    }
    return evidence, runtime


def _write_env(path: Path, env: dict[str, str]) -> None:
    path.write_text("".join(f"{name}={value}\n" for name, value in sorted(env.items())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    oracle = subparsers.add_parser("oracle-https")
    oracle.add_argument("--hostname", required=True)
    oracle.add_argument("--evidence-output", required=True)
    oracle.add_argument("--runtime-env-output", required=True)
    dns_a = subparsers.add_parser("cloudflare-dns-a")
    dns_a.add_argument("--zone-name", required=True)
    dns_a.add_argument("--hostname", required=True)
    dns_a.add_argument("--address", required=True)
    dns_a.add_argument("--evidence-output", required=True)
    dns_a.add_argument("--runtime-env-output", required=True)
    args = parser.parse_args(argv)

    if args.command == "oracle-https":
        evidence, runtime = oracle_https_origin(args.hostname)
    else:
        token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get(
            "CLOUDFLARE_WORKERS_TOKEN"
        )
        if not token:
            raise SystemExit("CLOUDFLARE_API_TOKEN or CLOUDFLARE_WORKERS_TOKEN is required")
        evidence, runtime = cloudflare_dns_a_origin(
            token=token,
            zone_name=args.zone_name,
            hostname=args.hostname,
            address=args.address,
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
