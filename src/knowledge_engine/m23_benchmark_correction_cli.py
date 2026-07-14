from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m23_benchmark_correction import run_offline_rebenchmark


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Re-evaluate immutable M23.5 vectors with corrected parent-article "
            "gold without network or Qdrant writes."
        )
    )
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    result = run_offline_rebenchmark(
        evidence_zip=args.evidence_zip,
        gold_path=args.gold,
        expected_evidence_sha256=args.expected_evidence_sha256,
    )
    args.output.mkdir(parents=True)
    _write_json(args.output / "corrected-gold.json", result["gold"])
    _write_json(
        args.output / "corrected-benchmark-result.json", result["result"]
    )
    _write_json(
        args.output / "model-selection-decision.json", result["decision"]
    )
    _write_json(
        args.output / "offline-rebenchmark-receipt.json", result["receipt"]
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
