from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .m26_pa7_arbitrary_query_runtime import run_owner_arbitrary_query
from .m26_production_promotion_closure import (
    compile_owner_query_response,
    load_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m26-pa7-query")
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--owner-subject-hash",
        default=os.getenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", ""),
    )
    parser.add_argument("--public-request", action="store_true")
    parser.add_argument(
        "--health-status",
        action="store_true",
        help="Run the legacy PA7 status responder instead of the product query runtime.",
    )
    parser.add_argument("--require-remote-dense", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gate = load_json(args.gate)
    if args.health_status:
        response = compile_owner_query_response(
            gate,
            question=args.question,
            owner_subject_hash=args.owner_subject_hash,
            public_request=args.public_request,
        )
    else:
        response = run_owner_arbitrary_query(
            root=args.root,
            gate=gate,
            question=args.question,
            owner_subject_hash=args.owner_subject_hash,
            public_request=args.public_request,
            require_remote_dense=args.require_remote_dense,
        )
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if response["status"].startswith("owner_only") else 13


if __name__ == "__main__":
    raise SystemExit(main())
