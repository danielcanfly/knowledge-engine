from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_8_final_decision import (
    build_decision_report,
    build_repair_handoff,
    canonical_decision_packet,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit the M23.7.8 final repair decision")
    parser.add_argument("--output", required=True)
    parser.add_argument("--handoff-output", required=True)
    args = parser.parse_args()

    packet = canonical_decision_packet()
    report = build_decision_report(packet)
    handoff = build_repair_handoff(packet)
    report_path = Path(args.output)
    handoff_path = Path(args.handoff_output)
    _write(report_path, report)
    _write(handoff_path, handoff)
    print(
        "M23.7.8_FINAL_DECISION_PASS "
        f"decision={report['decision']} "
        f"packet_sha256={report['decision_packet_sha256']} "
        f"report={report_path} handoff={handoff_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
