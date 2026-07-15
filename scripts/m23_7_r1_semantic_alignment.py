from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_r1_semantic_alignment import (
    canonical_alignment_report,
    canonical_manifest,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit deterministic M23.7 repair R1 semantic alignment evidence"
    )
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()

    manifest = canonical_manifest()
    report = canonical_alignment_report()
    _write(args.manifest_output, manifest)
    _write(args.report_output, report)
    print(
        "M23.7_R1_SEMANTIC_ALIGNMENT_PASS "
        f"manifest_sha256={manifest['manifest_sha256']} "
        f"report_sha256={report['report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
