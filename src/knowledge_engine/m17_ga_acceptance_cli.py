from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m17_ga_acceptance import (
    assess_ga_acceptance,
    build_drill_transcript,
    canonical_json,
)


def _write_or_print(payload: dict[str, Any], output: str | None) -> None:
    text = canonical_json(payload).decode("utf-8")
    if output is None:
        print(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-ga")
    commands = parser.add_subparsers(dest="command", required=True)

    drill = commands.add_parser("drill")
    drill.add_argument("--root", default=".")
    drill.add_argument(
        "--contract",
        default="docs/ga/m17/independent-ga-contract.json",
    )
    drill.add_argument("--engine-sha", required=True)
    drill.add_argument("--source-sha", required=True)
    drill.add_argument("--release-id", required=True)
    drill.add_argument("--manifest-sha256", required=True)
    drill.add_argument("--pointer-sha256", required=True)
    drill.add_argument("--operator-id", required=True)
    drill.add_argument("--output")

    assess = commands.add_parser("assess")
    assess.add_argument("--root", default=".")
    assess.add_argument(
        "--contract",
        default="docs/ga/m17/independent-ga-contract.json",
    )
    assess.add_argument("--transcript", required=True)
    assess.add_argument("--evaluator-id", required=True)
    assess.add_argument("--output")
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = Path(args.root)
    contract = Path(args.contract)
    if not contract.is_absolute():
        contract = root / contract

    if args.command == "drill":
        payload = build_drill_transcript(
            root,
            contract,
            engine_sha=args.engine_sha,
            source_sha=args.source_sha,
            release_id=args.release_id,
            manifest_sha256=args.manifest_sha256,
            pointer_sha256=args.pointer_sha256,
            operator_id=args.operator_id,
        )
        _write_or_print(payload, args.output)
        return 0

    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    payload = assess_ga_acceptance(
        root,
        contract,
        transcript,
        evaluator_id=args.evaluator_id,
    )
    _write_or_print(payload, args.output)
    return 0 if payload["ga_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
