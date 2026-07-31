from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .m26_production_promotion_closure import (
    compile_owner_query_response,
    load_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="knowledge-m26-pa7-query")
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--owner-subject-hash",
        default=os.getenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", ""),
    )
    parser.add_argument("--public-request", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    response = compile_owner_query_response(
        load_json(args.gate),
        question=args.question,
        owner_subject_hash=args.owner_subject_hash,
        public_request=args.public_request,
    )
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if response["status"].startswith("owner_only") else 13


if __name__ == "__main__":
    raise SystemExit(main())
