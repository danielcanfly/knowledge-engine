from __future__ import annotations

import knowledge_engine.m26_aq_semantic_runtime_patch_v3_surface as surface_patch
import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy

surface_patch.install()


def _candidate(*, surface: str, support: str) -> dict[str, object]:
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct",
                "surface_text": surface,
                "facet_ids": ["direct_answer"],
                "support_mode": "exact_quote",
                "support_refs": [
                    {
                        "evidence_id": "evidence_1",
                        "locator_id": "locator_1",
                        "exact_quote": support,
                    }
                ],
            }
        ],
    }


def _contract_ids(question: str) -> set[str]:
    contract = legacy._question_contract(
        question=question,
        intent_class="direct_grounded_knowledge",
    )
    return {
        str(item.get("facet_id", ""))
        for item in contract["required_facets"]
        if item.get("facet_id")
    }


def test_final_candidate_boundary_weakens_unsupported_modality() -> None:
    surface = "Adaptive planning requires global replanning and must always continue."
    support = (
        "Adaptive planning can replan globally when local repair no longer resolves "
        "the broader execution problem."
    )
    normalized, natural = surface_patch._normalize_candidate_unsupported_modality(
        _candidate(surface=surface, support=support),
        question="When should adaptive planning replan globally?",
        natural_answer=surface,
    )

    claim_surface = str(normalized["claims"][0]["surface_text"]).casefold()
    natural_surface = natural.casefold()
    for forbidden in ("requires", "must", "always"):
        assert forbidden not in claim_surface
        assert forbidden not in natural_surface
    assert "can involve" in claim_surface
    assert "should" in claim_surface
    assert "typically" in claim_surface


def test_final_candidate_boundary_preserves_evidence_licensed_modality() -> None:
    surface = "The policy must reject the request."
    normalized, natural = surface_patch._normalize_candidate_unsupported_modality(
        _candidate(surface=surface, support=surface),
        question="What does the policy do?",
        natural_answer=surface,
    )

    assert normalized["claims"][0]["surface_text"] == surface
    assert natural == surface


def test_narrow_disconnect_contract_requires_only_durable_state() -> None:
    ids = _contract_ids(
        "Why is persisted run state important when a client disconnects before a "
        "long-running workflow has finished?"
    )
    assert ids == {"durable_state_authority"}


def test_recovery_contract_keeps_durable_state_and_completion_verification() -> None:
    ids = _contract_ids(
        "How should a long-running controlled agent recover after a client disconnect "
        "without replaying completed work or skipping the verification that still has "
        "to happen later?"
    )
    assert ids == {"durable_state_authority", "verification_completion"}


def test_persistence_false_premise_does_not_invent_ordering_requirement() -> None:
    ids = _contract_ids(
        "Persisted run state can survive a client disconnect. Does that persistence by "
        "itself prove that the workflow output is correct and verified?"
    )
    assert ids == {
        "durable_state_authority",
        "verification_completion",
        "non_entailment_boundary",
    }
    assert "ordering_boundary" not in ids


def test_explicit_full_lifecycle_preserves_legacy_full_control_contract() -> None:
    ids = _contract_ids(
        "If an agent keeps working after the client disconnects, what parts of the "
        "surrounding control system keep the run trustworthy from admission to completion?"
    )
    assert {
        "lifecycle_trust_envelope",
        "admission_policy",
        "durable_state_authority",
        "continued_execution",
        "verification_completion",
        "observability_reattachment",
    }.issubset(ids)


def test_one_facet_direct_contract_uses_exact_evidence_partition() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before a "
        "long-running workflow has finished?"
    )
    candidate = surface_patch._direct_facet_partition_candidate_any(
        legacy=legacy,
        answer=(
            "Persisted server-side state preserves run progress after a client disconnect."
        ),
        question=question,
        intent_class="direct_grounded_knowledge",
        used_items=[
            {
                "evidence_id": "evidence_1",
                "locator_id": "locator_1",
                "source_identity": "source_1",
                "passage_text": (
                    "Persisted server-side state is durable and preserves run progress "
                    "after a client disconnect."
                ),
            }
        ],
        requirements=[],
    )
    assert candidate is not None
    assert len(candidate["claims"]) == 1
    assert candidate["claims"][0]["facet_ids"] == ["durable_state_authority"]
    assert candidate["claims"][0]["support_refs"]
