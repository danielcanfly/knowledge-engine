from __future__ import annotations

import argparse
import os
from pathlib import Path

from knowledge_engine.m23_7_5_live_shadow import COLLECTION
from knowledge_engine.m23_7_r2_latency_path import StrictModeSafeBatchLatencyClient
from knowledge_engine.m23_7_r3_bounded_live_reobservation import (
    DiagnosticWorkerFailure,
    HttpR3WorkerInvoker,
    build_diagnostic_failure_report,
    canonical_fixture_report,
    canonical_contract,
    canonical_json,
    run_bounded_live_reobservation,
    validate_wrangler_config,
)
from knowledge_engine.m23_cloudflare_qdrant import CloudflareConfig, QdrantConfig


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"M23.7-R3 missing required environment variable: {name}")
    return value


def _write(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M23.7 R3 bounded live retrieval-quality observation"
    )
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--output", required=True)
    parser.add_argument("--wrangler-config")
    parser.add_argument("--worker-origin", default="qdrant-placement-worker")
    args = parser.parse_args()

    output = Path(args.output)
    if args.mode == "fixture":
        report = canonical_fixture_report()
    else:
        if not args.wrangler_config:
            raise SystemExit("M23.7-R3 live mode requires --wrangler-config")
        cloudflare = CloudflareConfig(
            account_id=_required_env("CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required_env("CLOUDFLARE_API_TOKEN"),
            timeout_seconds=45.0,
        )
        qdrant_url = _required_env("QDRANT_URL")
        qdrant = QdrantConfig(
            base_url=qdrant_url,
            api_key=_required_env("QDRANT_API_KEY"),
            collection_name=COLLECTION,
            timeout_seconds=45.0,
        )
        placement_config = validate_wrangler_config(
            Path(args.wrangler_config),
            qdrant_url,
        )
        with StrictModeSafeBatchLatencyClient(cloudflare, qdrant) as client:
            samples = list(client.sample_points(8))
        with HttpR3WorkerInvoker(
            _required_env("M23_R3_WORKER_URL"),
            _required_env("M23_R3_OPERATOR_TOKEN"),
        ) as invoker:
            try:
                report = run_bounded_live_reobservation(
                    invoker,
                    samples=samples,
                    worker_origin=args.worker_origin,
                    placement_config=placement_config,
                )
            except DiagnosticWorkerFailure as exc:
                report = build_diagnostic_failure_report(
                    contract=canonical_contract(),
                    worker_origin=args.worker_origin,
                    placement_config=placement_config,
                    failure=exc,
                )

    _write(output, report)
    print(
        "M23.7_R3_BOUNDED_LIVE_REOBSERVATION "
        f"status={report['status']} "
        f"recall_at_5={report['metrics']['recall_at_5']:.6f} "
        f"mrr_at_10={report['metrics']['mrr_at_10']:.6f} "
        f"ndcg_at_10={report['metrics']['ndcg_at_10']:.6f} "
        f"shadow_ms={report['metrics']['worker_internal_shadow_ms']} "
        f"sha256={report['report_sha256']} "
        f"output={output}"
    )
    return 0 if report["status"] == "pass_bounded_live_reobservation" else 2


if __name__ == "__main__":
    raise SystemExit(main())
