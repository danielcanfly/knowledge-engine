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


def _direct_partition(
    *,
    question: str,
    answer: str,
    passage_text: str,
) -> dict[str, object] | None:
    return surface_patch._direct_facet_partition_candidate_any(
        legacy=legacy,
        answer=answer,
        question=question,
        intent_class="direct_grounded_knowledge",
        used_items=[
            {
                "evidence_id": "evidence_1",
                "locator_id": "locator_1",
                "source_identity": "source_1",
                "passage_text": passage_text,
            }
        ],
        requirements=[],
    )


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
    candidate = _direct_partition(
        question=question,
        answer=(
            "Persisted server-side state preserves run progress after a client disconnect."
        ),
        passage_text=(
            "Persisted server-side state is durable and preserves run progress after a "
            "client disconnect."
        ),
    )
    assert candidate is not None
    assert len(candidate["claims"]) == 1
    assert candidate["claims"][0]["facet_ids"] == ["durable_state_authority"]
    assert candidate["claims"][0]["support_refs"]


def test_recovery_two_facet_contract_uses_narrow_exact_evidence_partition() -> None:
    question = (
        "How should a long-running controlled agent recover after a client disconnect "
        "without replaying completed work or skipping the verification that still has "
        "to happen later?"
    )
    candidate = _direct_partition(
        question=question,
        answer=(
            "Persisted server-side state preserves completed progress after disconnect, "
            "and completion verification still checks the final result before acceptance."
        ),
        passage_text=(
            "Persisted durable state preserves completed progress after a client disconnect; "
            "completion verification checks the final result before acceptance."
        ),
    )
    assert candidate is not None
    assert {facet for claim in candidate["claims"] for facet in claim["facet_ids"]} == {
        "durable_state_authority",
        "verification_completion",
    }


def test_persistence_false_premise_uses_narrow_three_facet_partition() -> None:
    question = (
        "Persisted run state can survive a client disconnect. Does that persistence by "
        "itself prove that the workflow output is correct and verified?"
    )
    candidate = _direct_partition(
        question=question,
        answer=(
            "Persisted state can survive a disconnect, but persistence alone does not prove "
            "that the output is correct or verified; completion verification is separate."
        ),
        passage_text=(
            "Persisted durable state survives a client disconnect. Verification separately "
            "checks correctness and completion before acceptance."
        ),
    )
    assert candidate is not None
    assert {facet for claim in candidate["claims"] for facet in claim["facet_ids"]} == {
        "durable_state_authority",
        "verification_completion",
        "non_entailment_boundary",
    }


def test_non_lifecycle_adaptive_planning_preserves_known_good_fallthrough() -> None:
    question = "When should adaptive planning replan globally instead of repairing one step locally?"
    original_contract = surface_patch._ORIGINAL_QUESTION_CONTRACT(
        question=question,
        intent_class="direct_grounded_knowledge",
    )
    original_ids = {
        str(item.get("facet_id", ""))
        for item in original_contract["required_facets"]
        if item.get("facet_id")
    }
    assert _contract_ids(question) == original_ids
    assert surface_patch._lifecycle_contract_facets(question) is None

    candidate = _direct_partition(
        question=question,
        answer=(
            "Adaptive planning replans globally when a local repair can no longer recover "
            "from invalidated assumptions."
        ),
        passage_text=(
            "Adaptive planning can replan globally when local repair no longer resolves "
            "invalidated assumptions in the remaining plan."
        ),
    )
    assert candidate is None
