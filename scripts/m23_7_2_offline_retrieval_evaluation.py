from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_offline_retrieval_evaluation import (
    build_report,
    canonical_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    evidence = canonical_evidence()
    report = build_report(evidence)
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    args.report_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
