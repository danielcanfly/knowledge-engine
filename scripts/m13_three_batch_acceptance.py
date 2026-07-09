from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.config import Settings
from knowledge_engine.m13_acceptance import run_isolated_acceptance
from knowledge_engine.storage import create_object_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated M13 three-batch acceptance against ObjectStore."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--canonical-source-sha", required=True)
    parser.add_argument("--expected-production-pointer-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = create_object_store(Settings.from_env())
    report, receipt = run_isolated_acceptance(
        store,
        run_id=args.run_id,
        engine_sha=args.engine_sha,
        canonical_source_sha=args.canonical_source_sha,
        expected_real_production_pointer_sha256=(
            args.expected_production_pointer_sha256
        ),
    )
    payload = {
        "report": report,
        "runtime_receipt": receipt.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
