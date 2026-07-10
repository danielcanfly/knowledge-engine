from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m17_operator_runbooks import validate_runbook_registry


def main() -> int:
    parser = argparse.ArgumentParser(prog="m17-operator-runbook-acceptance")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/operations/m17/runbook-registry.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    registry = args.registry
    if not registry.is_absolute():
        registry = root / registry
    report = validate_runbook_registry(root=root, registry_path=registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
