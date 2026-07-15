from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_acceptance_contract import (
    build_acceptance_contract_report,
    canonical_acceptance_contract,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit the M23.7.1 acceptance contract.")
    parser.add_argument("--output", required=True, help="Path to write the report JSON.")
    args = parser.parse_args()

    report = build_acceptance_contract_report(canonical_acceptance_contract())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
