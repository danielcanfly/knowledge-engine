from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import uvicorn

from .errors import IntegrityError
from .m25_review_surface import (
    DecisionLedger,
    build_review_batch,
    create_review_app,
    load_json,
    validate_review_batch,
)


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise IntegrityError(f"M25-REVIEW-CLI-101 immutable output collision: {path}")
    path.write_text(payload, encoding="utf-8")


def _batch(args: argparse.Namespace) -> dict[str, Any]:
    return build_review_batch(
        load_json(args.suite),
        load_json(args.baseline),
        load_json(args.policy),
        load_json(args.report),
        load_json(args.acceptance),
    )


def build_command(args: argparse.Namespace) -> int:
    _write(args.output, _batch(args))
    return 0


def status_command(args: argparse.Namespace) -> int:
    batch = validate_review_batch(load_json(args.batch))
    audit = DecisionLedger(args.ledger).export(batch)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


def export_command(args: argparse.Namespace) -> int:
    batch = validate_review_batch(load_json(args.batch))
    _write(args.output, DecisionLedger(args.ledger).export(batch))
    return 0


def serve_command(args: argparse.Namespace) -> int:
    username = os.environ.get("M25_REVIEW_USERNAME", "")
    password = os.environ.get("M25_REVIEW_PASSWORD", "")
    batch = validate_review_batch(load_json(args.batch))
    app = create_review_app(
        batch,
        args.ledger,
        username=username,
        password=password,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="knowledge-m25-review-surface")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for name in ("suite", "baseline", "policy", "report", "acceptance"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=build_command)

    status = commands.add_parser("status")
    status.add_argument("--batch", type=Path, required=True)
    status.add_argument("--ledger", type=Path, required=True)
    status.set_defaults(func=status_command)

    export = commands.add_parser("export")
    export.add_argument("--batch", type=Path, required=True)
    export.add_argument("--ledger", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.set_defaults(func=export_command)

    serve = commands.add_parser("serve")
    serve.add_argument("--batch", type=Path, required=True)
    serve.add_argument("--ledger", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=serve_command)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
