from __future__ import annotations

from knowledge_engine.m26_multilingual_equivalence import (
    RequestedLanguageEquivalenceReview,
    RequestedLanguageRealizationRequest,
    build_requested_language_equivalence_request,
    build_requested_language_realization_request,
    evaluate_marker_preservation,
    review_authorizes_claim,
)
from knowledge_engine.m26_multilingual_verified_claim_spine import (
    CanonicalSupportEvidenceRef,
    CanonicalVerifiedClaim,
)


def claim_a() -> CanonicalVerifiedClaim:
    citation = {
        "citation_id": "claim-a_ref_1",
        "claim_id": "claim-a",
        "claim_role": "direct",
        "evidence_id": "ev-a",
        "locator_id": "loc-a",
    }
    support_ref = CanonicalSupportEvidenceRef(
        citation_id="claim-a_ref_1",
        evidence_id="ev-a",
        locator_id="loc-a",
    )
    return CanonicalVerifiedClaim(
        claim_id="claim-a",
        surface_text="API-42 uses the LLM model.",
        claim_role="direct",
        claim_type="EVIDENCE_FACT",
        facet_ids=("direct_answer",),
        support_mode="exact_quote",
        support_ref_count=1,
        source_identities=("source-router#section-router",),
        citation_ids=("claim-a_ref_1",),
        citations=(citation,),
        support_evidence_refs=(support_ref,),
        publication_eligible=True,
    )


def test_realization_request_schema_preserves_id_and_canonical_text() -> None:
    request = build_requested_language_realization_request(
        requested_answer_language="zh-TW",
        canonical_claims=(claim_a(),),
    )

    assert isinstance(request, RequestedLanguageRealizationRequest)
    assert request.requested_answer_language == "zh-TW"
    assert request.claims[0].canonical_claim_id == "claim-a"
    assert request.claims[0].canonical_surface_text_en == "API-42 uses the LLM model."
    assert request.claims[0].preservation_markers == ("API-42", "LLM", "42")
    assert not hasattr(request.claims[0], "citations")


def test_equivalence_request_schema_preserves_canonical_and_realized_texts() -> None:
    request = build_requested_language_equivalence_request(
        requested_answer_language="zh-TW",
        canonical_claims=(claim_a(),),
        realized_text_by_claim_id={"claim-a": "請保留 API-42 與 LLM。"},
        marker_preservation_status_by_claim_id={"claim-a": "pass"},
    )

    assert request.claims[0].canonical_claim_id == "claim-a"
    assert request.claims[0].canonical_surface_text_en == "API-42 uses the LLM model."
    assert request.claims[0].requested_language_text_zh_tw == "請保留 API-42 與 LLM。"
    assert not hasattr(request.claims[0], "citation_ids")


def test_marker_preservation_pass_and_fail() -> None:
    verdict, missing = evaluate_marker_preservation(
        canonical_surface_text_en="API-42 uses the LLM model.",
        requested_language_text="請保留 API-42 與 LLM。",
    )
    assert verdict == "pass"
    assert missing == ()

    verdict, missing = evaluate_marker_preservation(
        canonical_surface_text_en="API-42 uses the LLM model.",
        requested_language_text="請保留模型。",
    )
    assert verdict == "fail"
    assert missing == ("API-42", "LLM", "42")


def test_marker_preservation_not_applicable_when_no_markers_exist() -> None:
    verdict, missing = evaluate_marker_preservation(
        canonical_surface_text_en="The claim is purely descriptive.",
        requested_language_text="這個說法仍然成立。",
    )

    assert verdict == "not_applicable"
    assert missing == ()


def test_review_authorizes_only_pass_without_factual_expansion_or_contradiction() -> None:
    passing = RequestedLanguageEquivalenceReview(
        claim_id="claim-a",
        equivalence="pass",
        no_material_factual_expansion=True,
        no_contradiction=True,
        negation_preserved="true",
        modality_preserved="not_applicable",
        comparison_direction_preserved="not_applicable",
        relationship_direction_preserved="not_applicable",
        numeric_identity_preserved="true",
        entity_identity_preserved="true",
    )
    failing = RequestedLanguageEquivalenceReview(
        claim_id="claim-a",
        equivalence="pass",
        no_material_factual_expansion=False,
        no_contradiction=True,
    )

    assert review_authorizes_claim(passing) is True
    assert review_authorizes_claim(failing) is False
