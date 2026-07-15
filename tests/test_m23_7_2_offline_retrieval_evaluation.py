from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_offline_retrieval_evaluation import (
    build_report,
    canonical_evidence,
    validate_evidence,
)


def test_offline_evaluation_passes_and_replays():
    evidence = canonical_evidence()
    assert validate_evidence(evidence) == evidence
    first = build_report(evidence)
    second = build_report(evidence)
    assert first == second
    assert first["status"] == "pass"
    assert first["candidate_metrics"]["recall_at_5"] == 1.0
    assert first["candidate_activation_authorized"] is False
    assert first["production_retrieval_mode"] == "lexical"


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda item: item.__setitem__("evidence_sha256", "0" * 64), "digest"),
        (lambda item: item["cases"].pop(), "digest|24 cases"),
        (
            lambda item: item["cases"][4]["candidate"].append(
                {
                    "section_id": "forbidden",
                    "rank": 1,
                    "score": 1.0,
                    "provenance_present": True,
                    "acl_allowed": True,
                }
            ),
            "digest|negative case",
        ),
        (
            lambda item: item.__setitem__("network_calls", 1),
            "digest|external call",
        ),
        (
            lambda item: item.__setitem__("production_authority", True),
            "digest|production authority",
        ),
    ],
)
def test_evidence_fails_closed(mutator, match):
    item = copy.deepcopy(canonical_evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        validate_evidence(item)


def test_acl_and_no_answer_cases_are_empty():
    for case in canonical_evidence()["cases"]:
        if case["no_answer_expected"] or not case["acl_allowed"]:
            assert case["lexical"] == []
            assert case["candidate"] == []
