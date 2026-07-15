from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from knowledge_engine.m23_7_5_latency_diagnostic import run_latency_diagnostic
from knowledge_engine.m23_7_5_qdrant_strict_mode import (
    StrictModeSafeHttpLiveShadowClient,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7.5 missing required secret: {name}")
    return value


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture a redacted M23.7.5 live latency acceptance receipt"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cloudflare = CloudflareConfig(
        account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
        api_token=_required_env("CLOUDFLARE_API_TOKEN"),
        timeout_seconds=5.0,
    )
    qdrant = QdrantConfig(
        base_url=_required_env("QDRANT_URL"),
        api_key=_required_env("QDRANT_API_KEY"),
        collection_name="llm_wiki_m23_pilot_bge_m3_1024",
        timeout_seconds=5.0,
    )
    with StrictModeSafeHttpLiveShadowClient(cloudflare, qdrant) as client:
        report = run_latency_diagnostic(client)
    output = Path(args.output)
    _write(output, report)
    metrics = report["metrics"]
    print(
        "M23.7.5_LATENCY_DIAGNOSTIC "
        f"status={report['status']} samples={metrics['sample_count']} "
        f"provider_p95_ms={metrics['provider_p95_ms']} "
        f"qdrant_p95_ms={metrics['qdrant_p95_ms']} "
        f"shadow_p95_ms={metrics['shadow_p95_ms']} "
        f"sha256={report['latency_diagnostic_sha256']} output={output}"
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
