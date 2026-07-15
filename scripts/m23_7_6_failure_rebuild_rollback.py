from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_6_failure_rebuild_rollback import (
    build_m23_7_6_report,
    canonical_m23_7_6_payload,
)


def _write(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the deterministic M23.7.6 failure, rebuild and rollback receipt"
        )
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = build_m23_7_6_report(canonical_m23_7_6_payload())
    output = Path(args.output)
    _write(output, report)
    print(
        "M23.7.6_FAILURE_REBUILD_ROLLBACK_PASS "
        f"faults={report['fault_scenario_count']} "
        f"sha256={report['m23_7_6_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
