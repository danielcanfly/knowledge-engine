from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m17_ga_evidence import validate_ga_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the M17.6 v1 GA evidence matrix")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/ga/m17/ga-evidence-registry.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    registry = args.registry if args.registry.is_absolute() else root / args.registry
    report = validate_ga_evidence(root, registry)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
