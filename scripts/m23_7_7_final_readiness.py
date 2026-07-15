from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_7_final_readiness import (
    build_readiness_report,
    canonical_readiness_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit M23.7.7 final readiness report")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = build_readiness_report(canonical_readiness_packet())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "M23.7.7_FINAL_READINESS_PASS "
        f"decision={report['readiness_decision']} "
        f"packet_sha256={report['packet_sha256']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
