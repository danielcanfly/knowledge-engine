from __future__ import annotations

import inspect
import time
from typing import Any

import pytest

from knowledge_engine import m26_aq_semantic_contract as contract


class _Provider:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0
        self.payloads: list[dict[str, Any]] = []

    def call(self, payload: dict[str, Any], _call_class: str) -> dict[str, Any]:
        self.payloads.append(dict(payload))
        status = self.statuses[self.calls]
        self.calls += 1
        return {
            "status": status,
            "answer_text": "The evidence supports a narrow answer.",
            "citation_ids": ["ev-1"],
        }


def _evidence(count: int = 8, sources: int = 4) -> list[dict[str, str]]:
    return [
        {
            "evidence_id": f"ev-{index + 1}",
            "locator_id": f"loc-{index + 1}",
            "source_identity": f"source-{index % sources}",
            "passage_text": "The evidence supports a narrow answer.",
        }
        for index in range(count)
    ]


def _patch_fast_contract(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failures: list[str],
    facet_failures: list[str] | None = None,
) -> None:
    monkeypatch.setattr(contract.legacy, "_fast_synthesis_payload", lambda **_kwargs: {})
    monkeypatch.setattr(contract.legacy, "_normalize_fast_provider_result", lambda raw: raw)
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
                "citation_ids": ["ev-1"],
                "support_refs": [
                    {
                        "evidence_id": "ev-1",
                        "locator_id": "loc-1",
                        "exact_quote": "The evidence supports a narrow answer.",
                    }
                ],
            }
            if kwargs["provider_output"]["status"] == "answer"
            else None
        ),
    )
    monkeypatch.setattr(
        contract,
        "_question_answer_alignment_failures",
        lambda **_kwargs: list(failures),
    )
    monkeypatch.setattr(
        contract,
        "_fast_required_facet_citation_failures",
        lambda **_kwargs: list(facet_failures or []),
    )


def _run(provider: _Provider, *, started: float = 0.0) -> contract._FastAttemptOutcome:
    return contract._try_fast_supported_answer(
        question="Why is the narrow answer supported?",
        trace_id="trace",
        intent_class="direct_grounded_knowledge",
        gate={},
        bundle=None,
        lexical_result={},
        dense_result={},
        evidence=_evidence(),
        requirements=[],
        provider=provider,
        question_sha="question-sha",
        started=started,
    )


def test_low_information_failure_keeps_one_affordable_fast_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(monkeypatch, failures=[])
    provider = _Provider(["abstain", "abstain"])

    outcome = _run(provider)

    assert provider.calls == 2
    assert outcome.response is None
    assert provider.payloads[1]["bounded_repair_attempt"]["semantic_route"] == (
        contract.FAST_RETRY_ONCE
    )


def test_valid_off_topic_candidate_routes_to_fast_retry_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(
        monkeypatch,
        failures=["QUESTION_ANSWER_ALIGNMENT_MISSING_FOCUS"],
    )
    provider = _Provider(["answer", "answer"])

    outcome = _run(provider)

    assert provider.calls == 2
    assert outcome.envelope is not None
    assert outcome.envelope.routing_decision == contract.FAST_RETRY_ONCE
    assert provider.payloads[1]["bounded_repair_attempt"]["semantic_route"] == (
        contract.FAST_RETRY_ONCE
    )


def test_required_facet_mismatch_routes_to_evidence_slot_realignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(
        monkeypatch,
        failures=[],
        facet_failures=["FAST_CITATION_REQUIRED_FACET_MISSING:direct_answer"],
    )
    provider = _Provider(["answer"])

    outcome = _run(provider)

    assert provider.calls == 1
    assert outcome.envelope is not None
    assert outcome.envelope.routing_decision == contract.EVIDENCE_SLOT_REALIGNMENT


def test_overstrong_valid_candidate_routes_to_claim_weakening() -> None:
    publication = {
        "answer_text": "This always proves the entire claim.",
        "citation_ids": ["ev-1"],
    }
    provider = _Provider([])

    decision = contract._fast_failure_route(
        publication=publication,
        failure_codes=["QUESTION_ANSWER_ALIGNMENT_UNSUPPORTED_SURFACE"],
        evidence=_evidence(),
        started=0.0,
        provider=provider,
    )

    assert decision.route == contract.CLAIM_WEAKENING


def test_contradiction_is_not_routed_as_insufficient() -> None:
    provider = _Provider([])

    decision = contract._semantic_failure_route(
        failures=["SEMANTIC_REVIEW_BLOCKED:slot_1_claim:CONTRADICTED"],
        evidence=_evidence(),
        started=0.0,
        provider=provider,
    )

    assert decision.route == contract.CONTRADICTION_TRIAGE


def test_deadline_budget_prevents_runaway_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fast_contract(monkeypatch, failures=[])
    provider = _Provider(["abstain", "abstain"])

    outcome = _run(provider, started=time.monotonic() - 13.0)

    assert provider.calls == 1
    assert outcome.response is None


def test_fast_retry_reserves_time_for_semantic_closure() -> None:
    provider = _Provider([])

    decision = contract._low_information_retry_decision(
        started=time.monotonic() - 8.0,
        provider=provider,
        reason="fast_provider_abstained",
    )

    assert decision.route == contract.SAFE_ABSTENTION
    assert decision.minimum_budget_ms == (
        contract.FAST_RETRY_MIN_BUDGET_MS
        + contract.SEMANTIC_CLOSURE_MIN_BUDGET_MS
        + contract.FINAL_VALIDATION_MIN_BUDGET_MS
    )


def test_routing_has_no_case_id_or_question_text_input() -> None:
    fast_parameters = inspect.signature(contract._fast_failure_route).parameters
    semantic_parameters = inspect.signature(contract._semantic_failure_route).parameters
    source = inspect.getsource(contract._fast_failure_route) + inspect.getsource(
        contract._semantic_failure_route
    )

    assert "case_id" not in fast_parameters
    assert "case_id" not in semantic_parameters
    assert "case_id" not in source
    assert "F102" not in source
    assert "F181" not in source


def test_alignment_trace_distinguishes_bound_from_unbound_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = contract.SemanticRequirement(
        requirement_id="direct_answer",
        instruction="Answer the question.",
        evidence_terms=("narrow", "answer"),
        visible_patterns=(),
    )
    monkeypatch.setattr(
        contract.runtime,
        "_facet_support_classification",
        lambda **_kwargs: [
            {
                "facet_id": "direct_answer",
                "support_state": "SUPPORTED",
                "selected_evidence_ids_considered": ["ev-1", "ev-2"],
                "supporting_evidence_ids": ["ev-1"],
                "best_support_score": 2.5,
            }
        ],
    )

    trace = contract._evidence_slot_alignment_trace(
        question="Why is the narrow answer supported?",
        intent_class="direct_grounded_knowledge",
        evidence=_evidence(),
        requirements=[requirement],
        claim_text="A narrow answer.",
    )

    assert trace[0]["selected_support_evidence_ids"] == ["ev-1"]
    assert trace[0]["support_relation"] == "runtime_semantic_or_paraphrase_candidate"
    assert trace[0]["decision"] == "accepted_for_slot_local_synthesis"
