from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m17_failure_atlas import validate_failure_registry


def main() -> int:
    parser = argparse.ArgumentParser(prog="m17-failure-atlas-acceptance")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/troubleshooting/m17/failure-registry.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".artifacts/m17/failure-atlas-acceptance.json"),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    registry = args.registry if args.registry.is_absolute() else root / args.registry
    output = args.output if args.output.is_absolute() else root / args.output
    report = validate_failure_registry(root=root, registry_path=registry)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
