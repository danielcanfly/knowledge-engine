from __future__ import annotations

import argparse
import json
from pathlib import Path

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_candidate_release import (
    load_contract,
    write_candidate_release,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = write_candidate_release(args.output_dir)
    contract = load_contract(
        ROOT / "pilot/m23/m23-6-6-candidate-release-contract.json"
    )
    expected = contract["expected"]
    if report["candidate_release_id"] != expected["candidate_release_id"]:
        raise IntegrityError("candidate release ID drift")
    if (
        report["candidate_release_manifest_sha256"]
        != expected["candidate_release_manifest_sha256"]
    ):
        raise IntegrityError("candidate release manifest drift")
    if report["artifact_hashes"] != expected["artifact_hashes"]:
        raise IntegrityError("candidate release artifact hash drift")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
