from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .config import Settings
from .m13_closeout import close_batch
from .m13_operator import (
    integrity_audit,
    ledger_summary,
    load_production_identity,
    operator_lookup,
    operator_status,
    stale_report,
)
from .storage import create_object_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m13")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status")
    status.add_argument("--observed-at", required=True)
    status.add_argument("--candidate-capacity", type=int, default=2)

    lookup = commands.add_parser("lookup")
    lookup.add_argument("--identity", required=True)

    audit = commands.add_parser("audit")
    audit.add_argument("--observed-at", required=True)
    audit.add_argument("--candidate-capacity", type=int, default=2)

    stale = commands.add_parser("stale-report")
    stale.add_argument("--observed-at", required=True)
    stale.add_argument("--candidate-capacity", type=int, default=2)

    ledger = commands.add_parser("ledger-summary")
    ledger.add_argument("--observed-at", required=True)

    closeout = commands.add_parser("closeout")
    closeout.add_argument("--batch-id", required=True)
    closeout.add_argument("--actor", required=True)
    closeout.add_argument("--closed-at", required=True)
    closeout.add_argument("--expected-registry-version", type=int, required=True)
    closeout.add_argument("--expected-batch-version", type=int, required=True)
    closeout.add_argument(
        "--ledger-reference",
        action="append",
        required=True,
        dest="ledger_references",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    store = create_object_store(settings)

    if args.command == "status":
        result = operator_status(
            store,
            observed_at=args.observed_at,
            candidate_capacity=args.candidate_capacity,
        )
    elif args.command == "lookup":
        result = operator_lookup(store, identity=args.identity)
    elif args.command == "audit":
        result = integrity_audit(
            store,
            observed_at=args.observed_at,
            candidate_capacity=args.candidate_capacity,
        )
    elif args.command == "stale-report":
        result = stale_report(
            store,
            observed_at=args.observed_at,
            candidate_capacity=args.candidate_capacity,
        )
    elif args.command == "ledger-summary":
        result = ledger_summary(store, observed_at=args.observed_at)
    else:
        production, _ = load_production_identity(store)
        result = close_batch(
            store,
            batch_id=args.batch_id,
            actor=args.actor,
            closed_at=args.closed_at,
            observed_production=production,
            ledger_references=tuple(args.ledger_references),
            expected_registry_version=args.expected_registry_version,
            expected_batch_version=args.expected_batch_version,
        ).to_dict()

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
