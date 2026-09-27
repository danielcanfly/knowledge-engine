from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine import m26_aq_semantic_contract as contract


class _SequenceProvider:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.calls = 0
        self.payloads: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], _call_class: str) -> dict[str, Any]:
        self.payloads.append(dict(payload))
        status = self.statuses[self.calls]
        self.calls += 1
        return {
            "status": status,
            "answer_text": "The runtime keeps durable state.",
            "citation_ids": ["ev-1"],
        }


def _patch_fast_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        contract.legacy,
        "_fast_synthesis_payload",
        lambda **_kwargs: {"kind": "fast"},
    )
    monkeypatch.setattr(
        contract.legacy,
        "_normalize_fast_provider_result",
        lambda raw: raw,
    )
    monkeypatch.setattr(
        contract.legacy,
        "_fast_public_abstention_publication",
        lambda normalized: {} if normalized["status"] == "abstain" else None,
    )
    monkeypatch.setattr(
        contract.legacy,
        "_validate_fast_provider_candidate",
        lambda **kwargs: (
            {
                "answer_text": kwargs["provider_output"]["answer_text"],
                "citation_ids": list(kwargs["provider_output"]["citation_ids"]),
                "support_refs": [
                    {
                        "evidence_id": "ev-1",
                        "locator_id": "loc-1",
                        "exact_quote": "The runtime keeps durable state.",
                    }
                ],
            }
            if kwargs["provider_output"]["status"] == "answer"
            else None
        ),
    )
    monkeypatch.setattr(
        contract,
        "_fast_required_facet_citation_failures",
        lambda **_kwargs: [],
    )


def _run(provider: _SequenceProvider) -> contract._FastAttemptOutcome:
    return contract._try_fast_supported_answer(
        question="Why does the runtime keep durable state?",
        trace_id="trace",
        intent_class="direct_grounded_knowledge",
        gate={},
        bundle=None,
        lexical_result={},
        dense_result={},
        evidence=[
            {
                "evidence_id": "ev-1",
                "locator_id": "loc-1",
                "passage_text": "The runtime keeps durable state.",
            }
        ],
        requirements=[],
        provider=provider,
        question_sha="question-sha",
        started=0.0,
    )


def test_semantically_rejected_valid_candidate_routes_to_closure_without_fast_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(monkeypatch)
    monkeypatch.setattr(
        contract,
        "_question_answer_alignment_failures",
        lambda **_kwargs: ["QUESTION_ANSWER_ALIGNMENT_FAILED"],
    )
    provider = _SequenceProvider(["answer", "answer"])

    outcome = _run(provider)

    assert provider.calls == 1
    assert outcome.response is None
    assert outcome.envelope is not None
    assert outcome.envelope.rejection_reason_codes == (
        "QUESTION_ANSWER_ALIGNMENT_FAILED",
    )


def test_low_information_fast_abstention_keeps_one_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(monkeypatch)
    monkeypatch.setattr(
        contract,
        "_question_answer_alignment_failures",
        lambda **_kwargs: [],
    )
    provider = _SequenceProvider(["abstain", "abstain"])

    outcome = _run(provider)

    assert provider.calls == 2
    assert outcome.response is None
    assert outcome.envelope is None
    assert "bounded_repair_attempt" not in provider.payloads[0]
    assert provider.payloads[1]["bounded_repair_attempt"]["schema_version"] == (
        "m26-aq-fast-synthesis-bounded-repair/v1"
    )
