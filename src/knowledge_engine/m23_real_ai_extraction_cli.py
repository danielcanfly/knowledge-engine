from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m23_real_ai_extraction import execute_real_ai_extraction


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m23-extract")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = execute_real_ai_extraction(
        evidence_root=args.evidence_root,
        request_path=args.request,
        response_path=args.response,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, key in (
        ("execution-receipt.json", "receipt"),
        ("extraction-packet.json", "extraction_packet"),
        ("governed-packet.json", "governed_packet"),
    ):
        (args.output_dir / filename).write_text(
            json.dumps(output[key], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(output["receipt"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
