from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m20_embedding_contract import (
    benchmark_result,
    lexical_rankings,
    load_json,
    validate_benchmark_suite,
    validate_provider_contract,
)


def _rankings(path: Path) -> dict[str, list[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, list) for key, value in raw.items()
    ):
        raise SystemExit("rankings must be a JSON object of query ID to section ID array")
    return {key: [str(item) for item in value] for key, value in raw.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and score the M20.1 bilingual benchmark")
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path("benchmarks/m20/bilingual-blog-benchmark-v1.json"),
    )
    parser.add_argument("--provider-contract", type=Path)
    parser.add_argument("--rankings", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    suite: dict[str, Any] = validate_benchmark_suite(load_json(args.suite))
    provider = None
    if args.provider_contract is not None:
        provider = validate_provider_contract(load_json(args.provider_contract))
    rankings = (
        _rankings(args.rankings)
        if args.rankings is not None
        else lexical_rankings(suite, limit=max(args.k, 10))
    )
    result = benchmark_result(
        suite,
        rankings,
        method="candidate-rankings" if args.rankings is not None else "deterministic-lexical-baseline",
        k=args.k,
        provider_contract=provider,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
