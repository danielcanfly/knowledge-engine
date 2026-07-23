from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m25"


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def load(name: str) -> dict:
    return json.loads((PILOT / name).read_text())


def verify_self_sha(document: dict) -> None:
    unsigned = dict(document)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()


def test_all_30_exact_items_are_terminal_no_write() -> None:
    batch = load("m25-6-review-batch.json")
    ledger = load("m25-7-benchmark-decision-ledger.json")
    verify_self_sha(ledger)
    assert batch["batch_sha256"] == ledger["batch_sha256"]
    assert batch["item_count"] == ledger["counts"]["items"] == 30
    expected = {
        item["item_id"]: item["review_state_sha256"]
        for item in batch["items"]
    }
    previous = None
    for n, record in enumerate(ledger["records"], 1):
        assert record["n"] == n
        assert record["state"] == expected[record["id"]]
        assert record["decision"] == "benchmark_only_reject"
        assert record["op"] == "no_write"
        assert record["prev"] == previous
        unsigned = dict(record)
        claimed = unsigned.pop("sha256")
        assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
        previous = claimed
    assert set(expected) == {
        record["id"] for record in ledger["records"]
    }
    assert ledger["final_sha256"] == previous
    assert ledger["counts"] == {
        "deferred": 0,
        "items": 30,
        "pending": 0,
        "retained_fixtures": 30,
        "source_operations": 0,
        "terminal": 30,
    }
    assert ledger["source_pr_created"] is False
    assert ledger["m25_8_authorized"] is False
    assert ledger["production_mutation_permitted"] is False


def test_closure_preserves_all_authority_boundaries() -> None:
    ledger = load("m25-7-benchmark-decision-ledger.json")
    closure = load("m25-7-benchmark-closure.json")
    verify_self_sha(closure)
    assert closure["status"] == "m25_7_benchmark_batch_closed_no_write"
    assert closure["ledger"]["self_sha256"] == ledger["self_sha256"]
    assert closure["daniel_authority"]["authority_comment_id"] == 5057486325
    assert closure["result"] == {
        "deferred": 0,
        "pending": 0,
        "retained_fixtures": 30,
        "source_files_changed": 0,
        "source_operations": 0,
        "source_pr_created": False,
        "terminal": 30,
    }
    assert all(value is False for value in closure["boundary"].values())
    assert all(
        value is True for value in closure["future_real_pilot"].values()
    )
