from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_engine.m17_ga_acceptance import (
    assess_ga_acceptance,
    build_drill_transcript,
    canonical_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--contract",
        default="docs/ga/m17/independent-ga-contract.json",
    )
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--pointer-sha256", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--evaluator-id", required=True)
    parser.add_argument("--transcript-output", required=True)
    parser.add_argument("--report-output", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    contract = Path(args.contract)
    if not contract.is_absolute():
        contract = root / contract

    transcript = build_drill_transcript(
        root,
        contract,
        engine_sha=args.engine_sha,
        source_sha=args.source_sha,
        release_id=args.release_id,
        manifest_sha256=args.manifest_sha256,
        pointer_sha256=args.pointer_sha256,
        operator_id=args.operator_id,
    )
    transcript_path = Path(args.transcript_output)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_bytes(canonical_json(transcript) + b"\n")

    report = assess_ga_acceptance(
        root,
        contract,
        transcript,
        evaluator_id=args.evaluator_id,
    )
    report_path = Path(args.report_output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json(report) + b"\n")
    return 0 if report["ga_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
