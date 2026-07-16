from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

MAX_OUTPUT_BYTES = 65_536
WORKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DeployTargetError(ValueError):
    """Raised when Wrangler structured output cannot prove one safe target."""


def _validated_target(target: object, worker_name: str) -> str:
    if not isinstance(target, str):
        raise DeployTargetError("deploy target must be a string")
    parsed = urlsplit(target)
    if parsed.scheme != "https":
        raise DeployTargetError("deploy target must use HTTPS")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise DeployTargetError("deploy target authority is not allowed")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise DeployTargetError("deploy target must be an origin URL")
    hostname = parsed.hostname
    if hostname is None:
        raise DeployTargetError("deploy target hostname is missing")
    hostname = hostname.lower()
    prefix = f"{worker_name}."
    suffix = ".workers.dev"
    if not hostname.startswith(prefix) or not hostname.endswith(suffix):
        raise DeployTargetError("deploy target is not the exact workers.dev Worker")
    account_subdomain = hostname[len(prefix) : -len(suffix)]
    if not SUBDOMAIN_RE.fullmatch(account_subdomain):
        raise DeployTargetError("workers.dev account subdomain is invalid")
    return f"https://{hostname}"


def parse_deploy_target(path: Path, worker_name: str) -> str:
    if not WORKER_NAME_RE.fullmatch(worker_name):
        raise DeployTargetError("Worker name is invalid")
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise DeployTargetError("Wrangler output file is missing") from exc
    if size < 1 or size > MAX_OUTPUT_BYTES:
        raise DeployTargetError("Wrangler output file size is invalid")

    deploy_records: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DeployTargetError("Wrangler output entry must be an object")
                if value.get("type") == "deploy":
                    deploy_records.append(value)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeployTargetError("Wrangler output is malformed") from exc

    if len(deploy_records) != 1:
        raise DeployTargetError("Wrangler output must contain exactly one deploy record")
    record = deploy_records[0]
    if record.get("version") != 1:
        raise DeployTargetError("Wrangler deploy output version drifted")
    if record.get("worker_name") != worker_name:
        raise DeployTargetError("Wrangler deploy Worker name drifted")
    if record.get("worker_name_overridden") is not False:
        raise DeployTargetError("Wrangler deploy Worker name was overridden")
    version_id = record.get("version_id")
    if not isinstance(version_id, str) or not version_id:
        raise DeployTargetError("Wrangler deploy version identity is missing")
    targets = record.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise DeployTargetError("Wrangler deploy targets are ambiguous")
    return _validated_target(targets[0], worker_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-file", required=True, type=Path)
    parser.add_argument("--worker-name", required=True)
    args = parser.parse_args()
    try:
        target = parse_deploy_target(args.output_file, args.worker_name)
    except DeployTargetError as exc:
        print(f"R3.8 deploy target ERROR: {exc}", file=sys.stderr)
        return 23
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
