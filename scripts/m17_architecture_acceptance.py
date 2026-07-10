from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m17_architecture_canon import (
    validate_architecture_registry,
    verify_report_digest,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="m17-architecture-acceptance")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="repository root",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/architecture/m17/architecture-claims.json"),
        help="repository-relative architecture claim registry",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    registry = args.registry if args.registry.is_absolute() else root / args.registry
    report = validate_architecture_registry(root=root, registry_path=registry)
    if not verify_report_digest(report):
        raise SystemExit("architecture report digest verification failed")

    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
