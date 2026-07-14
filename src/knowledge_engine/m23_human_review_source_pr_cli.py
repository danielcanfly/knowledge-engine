from __future__ import annotations

import argparse
import json
from pathlib import Path

from .m23_human_review_source_pr import build_human_review_package, load_json


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge-m23-review")
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--governed", type=Path, required=True)
    parser.add_argument("--source-index-input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = load_json(args.source_index_input)
    concepts = source.get("concepts")
    result = build_human_review_package(
        load_json(args.extraction),
        load_json(args.governed),
        concepts,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in result.items():
        filename = name.replace("_", "-") + ".json"
        (args.output_dir / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result["receipt"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
