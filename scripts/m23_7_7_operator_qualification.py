from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_engine.m23_7_7_operator_qualification import (
    build_operator_qualification_report,
    canonical_bytes,
    canonical_operator_submission,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M23.7.7 cold-start operator qualification"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-output")
    args = parser.parse_args()

    submission = canonical_operator_submission()
    report = build_operator_qualification_report(submission)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(submission))

    if args.report_output:
        report_output = Path(args.report_output)
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_bytes(canonical_bytes(report))

    print(
        "M23.7.7_OPERATOR_QUALIFICATION_PASS "
        f"status={report['status']} score={report['score_percent']} "
        f"sha256={report['operator_qualification_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
