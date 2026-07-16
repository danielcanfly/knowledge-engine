from __future__ import annotations

import argparse
import os
from pathlib import Path

from knowledge_engine.m23_7_r3_5_rank_quality_calibration import (
    build_calibration_candidate,
    canonical_json,
    evaluate_calibration_candidate,
    redacted_candidate_artifact,
)
from knowledge_engine.m23_cloudflare_qdrant import (
    CloudflareConfig,
    SectionInput,
    embed_sections,
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"R3.5 missing environment variable: {name}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M23.7-R3.5 rank-quality calibration evaluation"
    )
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()

    candidate = build_calibration_candidate(args.evidence_zip)
    sections = [
        SectionInput(
            section_id=variant["variant_id"],
            text=variant["query_text"],
            payload={},
        )
        for probe in candidate["probe_plan"]
        for variant in probe["variants"]
    ]
    config = CloudflareConfig(
        account_id=_required_environment("CLOUDFLARE_ACCOUNT_ID"),
        api_token=_required_environment("CLOUDFLARE_API_TOKEN"),
        timeout_seconds=60.0,
    )
    query_vectors = embed_sections(sections, config)
    report = evaluate_calibration_candidate(candidate, query_vectors)

    _write_json(args.candidate_output, redacted_candidate_artifact(candidate))
    _write_json(args.report_output, report)
    print(
        "M23.7_R3.5_RANK_QUALITY_CALIBRATION "
        f"status={report['status']} "
        f"recall_at_5={report['metrics']['recall_at_5']} "
        f"mrr_at_10={report['metrics']['mrr_at_10']} "
        f"ndcg_at_10={report['metrics']['ndcg_at_10']} "
        f"maximum_hub={report['maximum_top10_hub_frequency']} "
        f"report_sha256={report['report_sha256']}"
    )
    return 0 if report["status"] == "pass_rank_quality_calibration" else 30


if __name__ == "__main__":
    raise SystemExit(main())
