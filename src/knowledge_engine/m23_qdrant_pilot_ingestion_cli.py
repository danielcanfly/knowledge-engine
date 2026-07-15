from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m23_qdrant_pilot_ingestion_real import build_dry_run, write_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the immutable M23.5 evidence ZIP and emit a deterministic, "
            "offline 107-point Qdrant ingestion dry run."
        )
    )
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument(
        "--authority-contract",
        type=Path,
        default=Path("pilot/m23/m23-6-1-authority-contract.json"),
    )
    parser.add_argument("--builder-engine-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_dry_run(
        evidence_zip=args.evidence_zip,
        authority_contract_path=args.authority_contract,
        builder_engine_sha=args.builder_engine_sha,
    )
    receipt = write_dry_run(args.output, result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "manifest_sha256": receipt["manifest_sha256"],
                "receipt_sha256": receipt["receipt_sha256"],
                "point_count": receipt["point_count"],
                "network_calls": 0,
                "qdrant_writes": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
