from __future__ import annotations

import knowledge_engine.m26_aq_semantic_runtime_patch_v3_surface as surface_patch


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
