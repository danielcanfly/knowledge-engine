from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m23_live_intake import execute_live_intake


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m23-intake")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    receipt = execute_live_intake(
        corpus_manifest=manifest,
        source_root=args.source_root,
        evidence_root=args.evidence_root,
        retrieved_at=args.retrieved_at,
        owner=args.owner,
        license_name=args.license_name,
        retry_failed=args.retry_failed,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
