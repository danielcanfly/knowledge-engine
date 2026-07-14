from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .m23_cloudflare_qdrant import (
    CloudflareConfig,
    QdrantConfig,
    build_execution_plan,
    build_qdrant_points,
    build_receipt,
    embed_sections,
    upsert_qdrant_points,
    validate_sections,
)


def _load_sections(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("sections")
    if not isinstance(value, list):
        raise SystemExit("input must be a JSON array or an object containing sections")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or execute the bounded M23.5 Cloudflare Workers AI + Qdrant lane."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-qdrant-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sections = validate_sections(_load_sections(args.input))
    plan = build_execution_plan(sections, collection_name=args.collection)
    _write_json(args.output / "execution-plan.json", plan)

    vectors = None
    points = None
    qdrant_response = None
    if args.execute:
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        cloudflare_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        if not account_id or not cloudflare_token:
            raise SystemExit(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required with --execute"
            )
        vectors = embed_sections(
            sections,
            CloudflareConfig(account_id=account_id, api_token=cloudflare_token),
        )
        points = build_qdrant_points(sections, vectors)
        _write_json(args.output / "qdrant-points.json", {"points": points})

    if args.allow_qdrant_write:
        if not args.execute or points is None:
            raise SystemExit("--allow-qdrant-write also requires --execute")
        qdrant_url = os.environ.get("QDRANT_URL")
        qdrant_api_key = os.environ.get("QDRANT_API_KEY")
        if not qdrant_url or not qdrant_api_key:
            raise SystemExit(
                "QDRANT_URL and QDRANT_API_KEY are required with --allow-qdrant-write"
            )
        qdrant_response = upsert_qdrant_points(
            points,
            QdrantConfig(
                base_url=qdrant_url,
                api_key=qdrant_api_key,
                collection_name=args.collection,
            ),
            allow_write=True,
        )
        _write_json(args.output / "qdrant-response.json", qdrant_response)

    receipt = build_receipt(
        plan=plan,
        vectors=vectors,
        qdrant_response=qdrant_response,
        executed=args.execute,
        qdrant_write=args.allow_qdrant_write,
    )
    _write_json(args.output / "execution-receipt.json", receipt)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
