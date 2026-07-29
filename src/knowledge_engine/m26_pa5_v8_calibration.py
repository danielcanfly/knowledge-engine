from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

from knowledge_engine.m26_pa5_v8_live import (
    PACKAGE_SHA256,
    POPULATION_SHA256,
    calibration_ids,
    run_population,
    write_receipt,
)
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run governed M26.PA.5 v8 calibration")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(".")
    question_ids, sample_sha256 = calibration_ids(root)
    receipt = run_population(
        root=root,
        question_ids=question_ids,
        max_calls=160,
        max_cost=Decimal("5.00"),
        thresholds={
            "count": 35,
            "safe_min": 0.90,
            "grounded_min": 0.90,
            "over_abstention_max": 0.10,
            "disagreement_max": 0.10,
        },
        mode="calibration",
    )
    receipt["calibration"] = {
        "sequence": int(os.environ.get("PA5_CALIBRATION_SEQUENCE", "0")),
        "sample_count": 35,
        "sample_sha256": sample_sha256,
        "question_ids_sha256": canonical_sha256(question_ids),
        "package_sha256": PACKAGE_SHA256,
        "population_sha256": POPULATION_SHA256,
    }
    receipt["self_sha256"] = ""
    receipt["self_sha256"] = canonical_sha256(receipt)
    write_receipt(args.evidence_dir, "m26-pa-5-v8-calibration-receipt.json", receipt)
    (args.evidence_dir / "calibration-sample-manifest.json").write_text(
        json.dumps(
            {
                "count": 35,
                "question_ids": question_ids,
                "sample_sha256": sample_sha256,
                "population_sha256": POPULATION_SHA256,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}))
    if receipt["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
