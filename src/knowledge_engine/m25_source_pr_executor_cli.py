from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m25_source_pr_executor import (
    authorize_source_pr_opening,
    build_source_pr_plan,
    load_json,
    materialize_test_plan,
    validate_plan,
    write_json_atomic,
)


def _write(path: Path, value: dict[str, Any]) -> None:
    write_json_atomic(path, value)
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _prepare(args: argparse.Namespace) -> None:
    plan = build_source_pr_plan(
        load_json(args.batch),
        load_json(args.audit),
        load_json(args.acceptance),
        load_json(args.source_baseline),
        load_json(args.authority),
    )
    _write(args.output, plan)


def _authorize(args: argparse.Namespace) -> None:
    receipt = authorize_source_pr_opening(load_json(args.plan), load_json(args.approval))
    _write(args.output, receipt)


def _materialize_test(args: argparse.Namespace) -> None:
    receipt = materialize_test_plan(
        load_json(args.plan),
        load_json(args.source_baseline),
        args.output_root,
    )
    if args.receipt is not None:
        write_json_atomic(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))


def _status(args: argparse.Namespace) -> None:
    plan = validate_plan(load_json(args.plan))
    status = {
        "status": plan["status"],
        "mode": plan["mode"],
        "plan_sha256": plan["plan_sha256"],
        "item_count": plan["item_count"],
        "operation_count": plan["operation_count"],
        "write_operation_count": plan["write_operation_count"],
        "no_write_operation_count": plan["no_write_operation_count"],
        "source_branch_write_permitted": plan["source_branch_write_permitted"],
        "github_pr_creation_permitted": plan["github_pr_creation_permitted"],
        "source_pr_merge_permitted": plan["source_pr_merge_permitted"],
        "m25_8_authorized": plan["m25_8_authorized"],
    }
    print(json.dumps(status, indent=2, sort_keys=True))


def _path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m25-source-pr")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="build a deterministic Source PR plan")
    prepare.add_argument("--batch", type=_path, required=True)
    prepare.add_argument("--audit", type=_path, required=True)
    prepare.add_argument("--acceptance", type=_path, required=True)
    prepare.add_argument("--source-baseline", type=_path, required=True)
    prepare.add_argument("--authority", type=_path, required=True)
    prepare.add_argument("--output", type=_path, required=True)
    prepare.set_defaults(func=_prepare)

    authorize = commands.add_parser(
        "authorize-opening",
        help="verify a separate exact-plan approval for Source branch and PR opening",
    )
    authorize.add_argument("--plan", type=_path, required=True)
    authorize.add_argument("--approval", type=_path, required=True)
    authorize.add_argument("--output", type=_path, required=True)
    authorize.set_defaults(func=_authorize)

    materialize = commands.add_parser(
        "materialize-test",
        help="materialize only a test_only plan into an isolated local directory",
    )
    materialize.add_argument("--plan", type=_path, required=True)
    materialize.add_argument("--source-baseline", type=_path, required=True)
    materialize.add_argument("--output-root", type=_path, required=True)
    materialize.add_argument("--receipt", type=_path)
    materialize.set_defaults(func=_materialize_test)

    status = commands.add_parser("status", help="show authority and plan status")
    status.add_argument("--plan", type=_path, required=True)
    status.set_defaults(func=_status)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
