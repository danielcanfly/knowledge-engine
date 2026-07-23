from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .errors import KnowledgeEngineError
from .m25_controlled_pilot import (
    build_run_receipt,
    evaluate_readiness,
    load_json,
    validate_inventory,
    write_json_atomic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m25-pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    gate = subparsers.add_parser("evaluate-gate")
    gate.add_argument("--predecessor", type=Path, required=True)
    gate.add_argument("--output", type=Path, required=True)

    inventory = subparsers.add_parser("validate-inventory")
    inventory.add_argument("--inventory", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("validate-run")
    run.add_argument("--evidence", type=Path, required=True)
    run.add_argument("--inventory", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "evaluate-gate":
            result = evaluate_readiness(load_json(args.predecessor))
        elif args.command == "validate-inventory":
            result = validate_inventory(load_json(args.inventory))
        else:
            result = build_run_receipt(load_json(args.evidence), load_json(args.inventory))
        write_json_atomic(args.output, result)
    except KnowledgeEngineError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
