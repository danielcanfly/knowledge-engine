from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m17_operator_qualification import (
    canonical_bytes,
    validate_training_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="m17-operator-qualification-acceptance")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/operations/m17/training-registry.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = validate_training_registry(args.root, args.registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
