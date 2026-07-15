from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_quality_contract import (
    build_acceptance_report,
    canonical_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    contract = canonical_contract()
    report = build_acceptance_report(contract)
    args.contract_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.contract_output.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    args.report_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
