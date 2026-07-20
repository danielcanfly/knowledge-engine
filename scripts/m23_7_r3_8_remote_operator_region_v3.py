from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts import m23_7_r3_8_remote_operator as base
from scripts import m23_7_r3_8_remote_operator_placement_v2 as placement_v2

REGION_CONTRACT_SHA256 = (
    "22c44268ac442a480ddf41d6c6e4197edae3ddbf79fdfeac546709d29b20d1db"
)
_PROVIDER_MAP = {"aws": "aws", "gcp": "gcp", "azure": "azure"}
_AWS_REGION = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)+-\d+$")
_GCP_REGION = re.compile(r"^[a-z]+(?:-[a-z]+)*\d$")
_AZURE_REGION = re.compile(r"^[a-z0-9]+$")
_QDRANT_SUFFIX = ("cloud", "qdrant", "io")


def _strip_qdrant_ordinal(label: str) -> str:
    head, separator, tail = label.rpartition("-")
    if separator and tail.isdigit() and head:
        return head
    return label


def derive_cloudflare_region(qdrant_url: str) -> str:
    parsed = urlparse(qdrant_url)
    hostname = (parsed.hostname or "").casefold()
    labels = hostname.split(".")
    if parsed.scheme != "https" or len(labels) < 6:
        raise base.RemoteOperatorError("placement_region_unresolved")
    if tuple(labels[-3:]) != _QDRANT_SUFFIX:
        raise base.RemoteOperatorError("placement_region_unresolved")
    provider_label = labels[-4]
    region_label = labels[-5]
    provider = _PROVIDER_MAP.get(provider_label)
    if provider is None:
        raise base.RemoteOperatorError("placement_provider_unsupported")
    region = _strip_qdrant_ordinal(region_label)
    valid = {
        "aws": _AWS_REGION,
        "gcp": _GCP_REGION,
        "azure": _AZURE_REGION,
    }[provider]
    if not valid.fullmatch(region):
        raise base.RemoteOperatorError("placement_region_unresolved")
    return f"{provider}:{region}"


def generate_wrangler_config(
    qdrant_url: str,
    worker_name: str,
    output: Path,
) -> dict[str, str | bool]:
    if not base._WORKER.fullmatch(worker_name):
        raise base.RemoteOperatorError("invalid_worker_name")
    region = derive_cloudflare_region(qdrant_url)
    config = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": worker_name,
        "main": "worker.mjs",
        "compatibility_date": "2026-07-16",
        "compatibility_flags": ["nodejs_compat"],
        "workers_dev": True,
        "ai": {"binding": "AI"},
        "placement": {"region": region},
        "observability": {
            "enabled": True,
            "head_sampling_rate": 1,
            "logs": {"invocation_logs": False},
        },
    }
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(raw, encoding="utf-8")
    region_digest = hashlib.sha256(region.encode()).hexdigest()
    return {
        "config_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "placement_hostname_sha256": region_digest,
        "placement_region_sha256": region_digest,
        "placement_target_type": "region",
        "generated_config_committed": False,
        "ai_binding": "AI",
    }


def normalise_region_receipt(value: dict[str, Any]) -> dict[str, Any]:
    remote_operator = value.get("remote_operator")
    if not isinstance(remote_operator, dict):
        raise base.RemoteOperatorError("remote_operator_receipt_missing")
    remote_operator["placement_target_type"] = "region"
    remote_operator["placement_region_persisted"] = False
    remote_operator["placement_hostname_persisted"] = False
    remote_operator["region_contract_sha256"] = REGION_CONTRACT_SHA256
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = base.canonical_sha256(value)
    return value


def execute(args: Any) -> int:
    original_generate = base.generate_wrangler_config
    original_write = base._write_json

    def write_json_v3(path: Path, value: dict[str, Any]) -> None:
        bounded = value
        if path.name == "latency-repair-receipt.json":
            bounded = normalise_region_receipt(dict(value))
        original_write(path, bounded)

    try:
        base.generate_wrangler_config = generate_wrangler_config
        base._write_json = write_json_v3
        return placement_v2.execute(args)
    finally:
        base.generate_wrangler_config = original_generate
        base._write_json = original_write


def main(argv: list[str] | None = None) -> int:
    return execute(base.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
