from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m25_intake_orchestrator import (
    build_plan_bundle,
    build_source_inventory,
    load_plan_bundle,
    persist_plan_bundle,
    resume_orchestrator,
)
from .storage import FileObjectStore


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _prepare(args: argparse.Namespace) -> int:
    descriptors = _load(args.descriptors)
    if not isinstance(descriptors, dict) or not isinstance(descriptors.get("items"), list):
        raise ValueError("descriptor document must contain an items array")
    inventory = build_source_inventory(
        descriptors["items"],
        captured_at=args.captured_at,
        allowed_root=args.allowed_root,
    )
    bundle = build_plan_bundle(
        inventory,
        max_sources_per_batch=args.max_sources_per_batch,
        max_bytes_per_batch=args.max_bytes_per_batch,
        max_attempts=args.max_attempts,
        created_at=args.created_at,
    )
    store = FileObjectStore(args.store_root)
    receipt = persist_plan_bundle(store, bundle)
    if args.output_dir is not None:
        _write(args.output_dir / "inventory.json", bundle["inventory"])
        _write(args.output_dir / "admission-plan.json", bundle["admission_plan"])
        _write(args.output_dir / "batch-plan.json", bundle["batch_plan"])
        _write(args.output_dir / "checkpoint.json", bundle["checkpoint"])
        _write(args.output_dir / "prepare-receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _resume(args: argparse.Namespace) -> int:
    result = resume_orchestrator(
        FileObjectStore(args.store_root),
        args.plan_id,
        allowed_root=args.allowed_root,
        run_at=args.run_at,
        max_items=args.max_items,
    )
    if args.output_dir is not None:
        _write(args.output_dir / "checkpoint.json", result["checkpoint"])
        _write(args.output_dir / "orchestrator-report.json", result["report"])
    print(json.dumps(result["report"], sort_keys=True))
    return 0


def _status(args: argparse.Namespace) -> int:
    bundle = load_plan_bundle(FileObjectStore(args.store_root), args.plan_id)
    print(json.dumps(bundle["checkpoint"], sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m25-admission")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--descriptors", type=Path, required=True)
    prepare.add_argument("--allowed-root", type=Path, required=True)
    prepare.add_argument("--store-root", type=Path, required=True)
    prepare.add_argument("--captured-at", required=True)
    prepare.add_argument("--created-at", required=True)
    prepare.add_argument("--max-sources-per-batch", type=int, default=25)
    prepare.add_argument("--max-bytes-per-batch", type=int, default=200_000)
    prepare.add_argument("--max-attempts", type=int, default=8)
    prepare.add_argument("--output-dir", type=Path)
    prepare.set_defaults(handler=_prepare)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--plan-id", required=True)
    resume.add_argument("--allowed-root", type=Path, required=True)
    resume.add_argument("--store-root", type=Path, required=True)
    resume.add_argument("--run-at", required=True)
    resume.add_argument("--max-items", type=int, default=100)
    resume.add_argument("--output-dir", type=Path)
    resume.set_defaults(handler=_resume)

    status = subparsers.add_parser("status")
    status.add_argument("--plan-id", required=True)
    status.add_argument("--store-root", type=Path, required=True)
    status.set_defaults(handler=_status)

    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
