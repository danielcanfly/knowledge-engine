from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_pilot_authority import (
    build_acceptance_report,
    canonical_json,
    load_authority_contract,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate M23.6.1 pilot authority contract")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_authority_contract(args.contract)
    report = build_acceptance_report(contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
