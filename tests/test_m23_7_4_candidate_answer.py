from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_4_candidate_answer import (
    build_candidate_answer_report,
    canonical_candidate_answer_payload,
    evaluate_candidate_answers,
)


def evidence():
    return canonical_candidate_answer_payload()


def test_canonical_candidate_answers_pass_and_are_deterministic():
    first = build_candidate_answer_report(evidence())
    second = build_candidate_answer_report(evidence())
    assert first == second
    assert first["status"] == "pass"
    assert first["metrics"]["case_count"] == 64
    assert first["metrics"]["answer_count"] == 16
    assert first["metrics"]["abstain_count"] == 48
    assert first["metrics"]["positive_answer_rate"] == 1.0
    assert first["metrics"]["negative_abstention_rate"] == 1.0
    assert first["metrics"]["citation_coverage"] == 1.0
    assert first["production_response_authority"] is False
    assert first["candidate_answers_served"] is False
    assert first["candidate_answers_discarded"] is True


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item["entry"].__setitem__("shadow_replay_sha256", "0" * 64),
            "entry identity drifted",
        ),
        (
            lambda item: item["composer_identity"].__setitem__("model_revision", "drift"),
            "composer identity drifted",
        ),
        (
            lambda item: item["privacy"].__setitem__("raw_candidate_answer_persisted", True),
            "privacy boundary drifted",
        ),
        (
            lambda item: item["output_authority"].__setitem__(
                "candidate_answer_response_authoritative", True
            ),
            "output authority drifted",
        ),
        (
            lambda item: item["cases"].pop(),
            "exactly 64 composition cases",
        ),
        (
            lambda item: item["cases"][0].__setitem__("candidate_answer_served", True),
            "candidate answer served",
        ),
        (
            lambda item: item["cases"][0].__setitem__(
                "candidate_answer_influenced_output", True
            ),
            "candidate answer influenced output",
        ),
        (
            lambda item: item["cases"][0]["evidence"][0].__setitem__("authorised", False),
            "unauthorised evidence",
        ),
        (
            lambda item: item["cases"][0]["evidence"][0].__setitem__("fresh", False),
            "stale evidence",
        ),
        (
            lambda item: item["cases"][0]["evidence"][0].__setitem__(
                "prompt_injection_isolated", False
            ),
            "prompt injection was not isolated",
        ),
        (
            lambda item: item["cases"][0]["ephemeral_candidate_response"]["claims"][0].__setitem__(
                "text", "Unsupported claim"
            ),
            "unsupported claim",
        ),
        (
            lambda item: item["cases"][0]["ephemeral_candidate_response"][
                "citations"
            ][0].__setitem__("section_id", "pilot/wrong#section"),
            "citation provenance mismatch",
        ),
        (
            lambda item: item["cases"][0]["ephemeral_candidate_response"][
                "provider_trace"
            ].__setitem__("attempts", 3),
            "retry ceiling exceeded",
        ),
        (
            lambda item: item["cases"][0]["ephemeral_candidate_response"].__setitem__(
                "prompt_injection_followed", True
            ),
            "prompt injection succeeded",
        ),
        (
            lambda item: item["cases"][8].__setitem__("provider_invoked", True),
            "provider invoked for negative case",
        ),
        (
            lambda item: item["protected_mutations"].__setitem__(
                "production_response_authority", True
            ),
            "protected mutations dispatched",
        ),
    ],
)
def test_candidate_composition_fails_closed(mutator, match):
    item = copy.deepcopy(evidence())
    mutator(item)
    with pytest.raises(IntegrityError, match=match):
        evaluate_candidate_answers(item)


def test_all_positive_claims_have_exact_readable_citations_and_provenance():
    payload = evidence()
    positives = [case for case in payload["cases"] if case["expects_answer"]]
    assert len(positives) == 16
    for case in positives:
        response = case["ephemeral_candidate_response"]
        citation = response["citations"][0]
        evidence_item = case["evidence"][0]
        assert citation["readable_marker"] in response["answer_text"]
        assert citation["section_id"] == evidence_item["section_id"]
        assert citation["parent_id"] == evidence_item["parent_id"]
        assert citation["evidence_sha256"] == evidence_item["evidence_sha256"]
        assert citation["byte_start"] == evidence_item["byte_start"]
        assert citation["byte_end"] == evidence_item["byte_end"]


def test_all_negative_classes_abstain_without_provider_invocation():
    payload = evidence()
    negatives = [case for case in payload["cases"] if not case["expects_answer"]]
    assert len(negatives) == 48
    assert all(case["composition_status"] == "abstain" for case in negatives)
    assert all(case["provider_invoked"] is False for case in negatives)
    assert all(case["ephemeral_candidate_response"] is None for case in negatives)


def test_durable_report_contains_digests_not_raw_candidate_answers():
    report = build_candidate_answer_report(evidence())
    encoded = repr(report)
    assert "answer_text" not in encoded
    assert len(report["answer_digests"]) == 16
    assert report["raw_candidate_answers_persisted"] is False
