#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import sys
from pathlib import Path


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


def _write_env(path: Path, env: dict[str, str]) -> None:
    path.write_text("".join(f"{name}={value}\n" for name, value in sorted(env.items())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    oracle = subparsers.add_parser("oracle-https")
    oracle.add_argument("--hostname", required=True)
    oracle.add_argument("--evidence-output", required=True)
    oracle.add_argument("--runtime-env-output", required=True)
    args = parser.parse_args(argv)

    evidence, runtime = oracle_https_origin(args.hostname)
    evidence_path = Path(args.evidence_output)
    runtime_path = Path(args.runtime_env_output)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    _write_env(runtime_path, runtime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
