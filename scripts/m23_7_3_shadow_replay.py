from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_3_shadow_replay import (
    build_shadow_replay_report,
    canonical_shadow_replay_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit the M23.7.3 shadow replay report.")
    parser.add_argument("--output", required=True, help="Path to write the report JSON.")
    args = parser.parse_args()

    report = build_shadow_replay_report(canonical_shadow_replay_payload())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
