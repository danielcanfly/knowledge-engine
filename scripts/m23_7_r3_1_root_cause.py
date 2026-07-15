from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_engine.m23_7_r3_1_fixture import canonical_fixture
from knowledge_engine.m23_7_r3_1_root_cause import (
    build_preliminary_report,
    canonical_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R3.1 query-collision diagnostics")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    fixture = canonical_fixture()
    report = build_preliminary_report(fixture["samples"], fixture["cases"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(
        "M23.7_R3_1_QUERY_DIAGNOSTICS "
        f"status={report['status']} sha256={report['report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
