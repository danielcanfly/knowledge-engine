from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from knowledge_engine.m23_7_r2_latency_path import StrictModeSafeBatchLatencyClient
from knowledge_engine.m23_7_r2_regional_binding import (
    HttpRegionalWorkerInvoker,
    build_fixture_report,
    run_regional_binding_comparison,
    validate_report,
    validate_wrangler_config,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7-R2.1 missing required secret: {name}")
    return value


def _write(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run M23.7 R2.1 direct batch versus placed Worker comparison"
    )
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--direct-origin", default="mac-mini-local")
    parser.add_argument("--worker-origin", default="qdrant-placement-worker")
    parser.add_argument("--wrangler-config")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.mode == "fixture":
        report = build_fixture_report()
    else:
        if not args.wrangler_config:
            raise SystemExit("M23.7-R2.1 --wrangler-config is required in live mode")
        qdrant_url = _required_env("QDRANT_URL")
        placement_config = validate_wrangler_config(Path(args.wrangler_config), qdrant_url)
        cloudflare = CloudflareConfig(
            account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required_env("CLOUDFLARE_API_TOKEN"),
            timeout_seconds=10.0,
        )
        qdrant = QdrantConfig(
            base_url=qdrant_url,
            api_key=_required_env("QDRANT_API_KEY"),
            collection_name="llm_wiki_m23_pilot_bge_m3_1024",
            timeout_seconds=10.0,
        )
        with StrictModeSafeBatchLatencyClient(cloudflare, qdrant) as direct_client:
            with HttpRegionalWorkerInvoker(
                endpoint=_required_env("M23_R2_WORKER_URL"),
                operator_token=_required_env("M23_R2_OPERATOR_TOKEN"),
            ) as worker_invoker:
                report = run_regional_binding_comparison(
                    direct_client,
                    worker_invoker,
                    direct_origin=args.direct_origin,
                    worker_origin=args.worker_origin,
                    placement_config=placement_config,
                )

    validate_report(report)
    output = Path(args.output)
    _write(output, report)
    baseline = report["paths"]["baseline"]
    candidate = report["paths"]["candidate"]
    print(
        "M23.7_R2_1_REGIONAL_BINDING "
        f"status={report['status']} "
        f"direct_shadow_ms={baseline['shadow_ms']} "
        f"worker_shadow_ms={candidate['shadow_ms']} "
        f"worker_provider_ms={candidate['provider_ms']} "
        f"worker_qdrant_ms={candidate['qdrant_ms']} "
        f"sha256={report['report_sha256']} output={output}"
    )
    return 0 if report["status"] == "pass_regional_path_qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
