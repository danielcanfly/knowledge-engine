from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_6_acceptance import (
    build_m23_6_acceptance_report,
    canonical_acceptance_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_m23_6_acceptance_report(canonical_acceptance_evidence())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
