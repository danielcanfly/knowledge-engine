from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine import m26_aq_semantic_contract as contract
from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


def _evidence(evidence_id: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc-{evidence_id}",
        "passage_text": "A bounded runtime records durable state.",
        "source_identity": "source",
    }


def _envelope(*citation_ids: str) -> contract.FastAttemptEnvelope:
    return contract.FastAttemptEnvelope(
        publication={
            "answer_text": "The bounded runtime records durable state.",
            "citation_ids": list(citation_ids),
            "support_refs": [
                {"evidence_id": item, "locator_id": f"loc-{item}"}
                for item in citation_ids
            ],
        },
        rejection_reason_codes=("QUESTION_ALIGNMENT_FAILED",),
    )


def test_fast_seed_rejects_unknown_evidence_identity() -> None:
    seed = contract._fast_recovery_seed(
        envelope=_envelope("unknown"),
        question="What does the runtime record?",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence("ev-1")],
        requirements=[],
    )

    assert seed is None


def test_fast_seed_rejects_ambiguous_facet_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "_facet_support_classification",
        lambda **_kwargs: [
            {
                "facet_id": "facet-a",
                "support_state": "SUPPORTED",
                "supporting_evidence_ids": ["ev-1"],
            },
            {
                "facet_id": "facet-b",
                "support_state": "SUPPORTED",
                "supporting_evidence_ids": ["ev-1"],
            },
        ],
    )

    assert contract._fast_recovery_seed(
        envelope=_envelope("ev-1"),
        question="What does the runtime record?",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence("ev-1")],
        requirements=[],
    ) is None


def test_fast_seed_binds_one_runtime_supported_facet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime,
        "_facet_support_classification",
        lambda **_kwargs: [
            {
                "facet_id": "durable_state",
                "support_state": "SUPPORTED",
                "supporting_evidence_ids": ["ev-1"],
            }
        ],
    )

    seed = contract._fast_recovery_seed(
        envelope=_envelope("ev-1"),
        question="What does the runtime record?",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence("ev-1")],
        requirements=[],
    )

    assert seed is not None
    assert seed.facet_ids == ("durable_state",)
    assert seed.citation_ids == ("ev-1",)
