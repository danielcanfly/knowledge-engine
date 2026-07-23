from __future__ import annotations

import argparse
from pathlib import Path

from .m26_retrieval_envelope import (
    load_json,
    run_benchmark,
    write_json,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="M26.2 synthetic retrieval envelope benchmark")
    value.add_argument("--policy", required=True, type=Path)
    value.add_argument("--corpus", required=True, type=Path)
    value.add_argument("--cases", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    report = run_benchmark(
        load_json(args.cases),
        corpus=load_json(args.corpus),
        policy=load_json(args.policy),
    )
    write_json(args.output, report)
    return 0 if report["status"] == "m26_2_retrieval_envelope_ready" else 30


if __name__ == "__main__":
    raise SystemExit(main())
