from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.m23_7_r3_2_semantic_payload_repair import canonical_repair_contract


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit the M23.7-R3.2 repair contract")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = canonical_repair_contract()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        "M23.7_R3.2_REPAIR "
        f"status=implementation_ready contract_sha256={payload['contract_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
