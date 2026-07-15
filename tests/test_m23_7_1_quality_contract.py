from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_quality_contract import (
    build_acceptance_report,
    canonical_contract,
    validate_contract,
)


def test_contract_passes_and_report_replays():
    contract = canonical_contract()
    assert validate_contract(contract) == contract
    assert build_acceptance_report(contract) == build_acceptance_report(contract)
    assert build_acceptance_report(contract)["case_count"] == 24


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda item: item.__setitem__("contract_sha256", "0" * 64), "digest"),
        (lambda item: item["entry"].__setitem__("qdrant_points", 106), "entry identity"),
        (lambda item: item["suite"]["cases"].pop(), "digest|24 cases"),
        (lambda item: item["suite"].__setitem__("network_calls_allowed", True), "digest|external"),
        (lambda item: item["authority"].__setitem__("production_retrieval_mode", "semantic"), "digest|authority"),
        (lambda item: item["protected_state"].__setitem__("r2_write", True), "digest|protected"),
    ],
)
def test_contract_fails_closed(mutator, match):
    item = copy.deepcopy(canonical_contract())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        validate_contract(item)


def test_suite_is_balanced():
    cases = canonical_contract()["suite"]["cases"]
    counts = {}
    for case in cases:
        counts[case["query_class"]] = counts.get(case["query_class"], 0) + 1
    assert set(counts.values()) == {4}
