from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from knowledge_engine.m26_pa5_v8_live import (
    PACKAGE_SHA256,
    POPULATION_SHA256,
    formal_ids,
    run_population,
    write_receipt,
)
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

TRIGGER_PATH = Path("pilot/m26/m26-pa-5-attempt-9-live-trigger.json")
TRIGGER_MARKER = "[m26.pa5-controlled-internal-shadow-pilot-authorized-attempt-9]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the single formal M26.PA.5 attempt 9")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--trigger-file", type=Path, default=None)
    return parser.parse_args()


def _load_trigger(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("attempt-9 trigger must be an object")
    expected = value.get("self_sha256")
    candidate = dict(value)
    candidate["self_sha256"] = ""
    if not isinstance(expected, str) or canonical_sha256(candidate) != expected:
        raise ValueError("attempt-9 trigger self digest mismatch")
    if value.get("logical_attempt") != 9:
        raise ValueError("attempt-9 trigger logical attempt mismatch")
    if value.get("trigger_marker") != TRIGGER_MARKER:
        raise ValueError("attempt-9 trigger marker mismatch")
    if value.get("package_sha256") != PACKAGE_SHA256:
        raise ValueError("attempt-9 package identity mismatch")
    if value.get("population_sha256") != POPULATION_SHA256:
        raise ValueError("attempt-9 population identity mismatch")
    passes = value.get("calibration_passes")
    if not isinstance(passes, list) or len(passes) != 2:
        raise ValueError("attempt-9 requires two calibration passes")
    executable_heads = {item.get("executable_head_sha") for item in passes}
    sample_digests = {item.get("sample_sha256") for item in passes}
    receipt_digests = {item.get("receipt_self_sha256") for item in passes}
    if len(executable_heads) != 1 or executable_heads != {value.get("executable_head_sha")}:
        raise ValueError("calibration executable heads do not match trigger")
    if len(sample_digests) != 1 or sample_digests != {value.get("calibration_sample_sha256")}:
        raise ValueError("calibration sample digests do not match trigger")
    if len(receipt_digests) != 2 or not all(receipt_digests):
        raise ValueError("calibration receipt identities are incomplete or reused")
    runtime_head = os.environ.get("PA5_EXECUTABLE_HEAD_SHA", "")
    if runtime_head and runtime_head != value.get("executable_head_sha"):
        raise ValueError("workflow executable head does not match trigger")
    return value


def main() -> None:
    args = parse_args()
    trigger_path = args.trigger_file or Path(
        os.environ.get("PA5_ATTEMPT_9_TRIGGER_FILE", str(TRIGGER_PATH))
    )
    trigger = _load_trigger(trigger_path)
    receipt = run_population(
        root=Path("."),
        question_ids=formal_ids(Path(".")),
        max_calls=800,
        max_cost=Decimal("20.00"),
        thresholds={
            "count": 200,
            "safe_min": 0.90,
            "grounded_min": 0.85,
            "over_abstention_max": 0.15,
            "disagreement_max": 0.15,
        },
        mode="formal-attempt-9",
    )
    receipt["formal_authority"] = {
        "logical_attempt": 9,
        "trigger_marker": TRIGGER_MARKER,
        "trigger_self_sha256": trigger["self_sha256"],
        "executable_head_sha": trigger["executable_head_sha"],
        "calibration_sample_sha256": trigger["calibration_sample_sha256"],
        "calibration_receipt_self_sha256s": [
            item["receipt_self_sha256"] for item in trigger["calibration_passes"]
        ],
    }
    receipt["self_sha256"] = ""
    receipt["self_sha256"] = canonical_sha256(receipt)
    name = (
        "m26-pa-5-attempt-9-success-receipt.json"
        if receipt["status"] == "passed"
        else "m26-pa-5-attempt-9-failure-receipt.json"
    )
    write_receipt(args.evidence_dir, name, receipt)
    print(json.dumps({"status": receipt["status"], "self_sha256": receipt["self_sha256"]}))
    if receipt["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
