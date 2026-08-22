from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_multilingual_equivalence import (
    RequestedLanguageEquivalenceReview,
    RequestedLanguageEquivalenceReviewResponse,
    RequestedLanguageRealizationResponse,
    RequestedLanguageRealizationResponseClaim,
)
from knowledge_engine.m26_multilingual_publication_adapter import (
    build_verified_requested_language_publication,
)
from knowledge_engine.m26_multilingual_verified_claim_spine import (
    CanonicalSupportEvidenceRef,
    CanonicalVerifiedClaim,
    CanonicalVerifiedClaimSpine,
)


@dataclass(frozen=True)
class ClaimFixture:
    claim_id: str
    surface_text: str
    citation_id: str
    evidence_id: str
    locator_id: str
    citation_ids: tuple[str, ...] | None = None
    publication_eligible: bool = True
    support_mode: str = "exact_quote"
    support_ref_count: int = 1
    claim_role: str = "direct"
    claim_type: str = "EVIDENCE_FACT"
    facet_ids: tuple[str, ...] = ("direct_answer",)
    source_identities: tuple[str, ...] = ("source-router#section-router",)

    def canonical(self) -> CanonicalVerifiedClaim:
        citation_ids = (
            (self.citation_id,) if self.citation_ids is None else self.citation_ids
        )
        citation = {
            "citation_id": self.citation_id,
            "claim_id": self.claim_id,
            "claim_role": self.claim_role,
            "evidence_id": self.evidence_id,
            "locator_id": self.locator_id,
            "source_id": "source-router",
            "source_identity": self.source_identities[0],
        }
        support_ref = CanonicalSupportEvidenceRef(
            citation_id=self.citation_id,
            evidence_id=self.evidence_id,
            locator_id=self.locator_id,
            source_identity=self.source_identities[0],
            source_id="source-router",
        )
        return CanonicalVerifiedClaim(
            claim_id=self.claim_id,
            surface_text=self.surface_text,
            claim_role=self.claim_role,
            claim_type=self.claim_type,
            facet_ids=self.facet_ids,
            support_mode=self.support_mode,
            support_ref_count=self.support_ref_count,
            source_identities=self.source_identities,
            citation_ids=citation_ids,
            citations=(citation,),
            support_evidence_refs=(support_ref,),
            publication_eligible=self.publication_eligible,
        )


@dataclass
class RecordingRealizer:
    response: RequestedLanguageRealizationResponse
    fail: bool = False
    calls: list[Any] = field(default_factory=list)

    def __call__(self, request: Any) -> RequestedLanguageRealizationResponse:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("realizer boom")
        return self.response


@dataclass
class RecordingReviewer:
    response: RequestedLanguageEquivalenceReviewResponse
    fail: bool = False
    calls: list[Any] = field(default_factory=list)

    def __call__(self, request: Any) -> RequestedLanguageEquivalenceReviewResponse:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("reviewer boom")
        return self.response


def claim_a(*, publication_eligible: bool = True) -> CanonicalVerifiedClaim:
    return ClaimFixture(
        claim_id="claim-a",
        surface_text="API-42 uses the LLM model.",
        citation_id="claim-a_ref_1",
        evidence_id="ev-a",
        locator_id="loc-a",
        publication_eligible=publication_eligible,
    ).canonical()


def claim_b(*, publication_eligible: bool = True) -> CanonicalVerifiedClaim:
    return ClaimFixture(
        claim_id="claim-b",
        surface_text="Version 3 keeps 5 ms latency.",
        citation_id="claim-b_ref_1",
        evidence_id="ev-b",
        locator_id="loc-b",
        publication_eligible=publication_eligible,
        source_identities=("source-b#section-b",),
    ).canonical()


def claim_url(*, publication_eligible: bool = True) -> CanonicalVerifiedClaim:
    return ClaimFixture(
        claim_id="claim-url",
        surface_text="The docs live at https://example.com/docs.",
        citation_id="claim-url_ref_1",
        evidence_id="ev-url",
        locator_id="loc-url",
        publication_eligible=publication_eligible,
        source_identities=("source-url#section-url",),
    ).canonical()


def full_spine(
    *,
    requested_answer_language: str = "zh-TW",
    status: str = "verified_full",
    canonical_claims: tuple[CanonicalVerifiedClaim, ...] | None = None,
    dropped_claim_ids: tuple[str, ...] = (),
    dropped_claim_count: int = 0,
    safe_abstention: bool = False,
    reason_codes: tuple[str, ...] = (),
    unsupported_accepted_claims: int = 0,
    citation_locator_valid: bool = True,
    material_claim_support_verified: bool = True,
) -> CanonicalVerifiedClaimSpine:
    claims = canonical_claims if canonical_claims is not None else (claim_a(), claim_b())
    return CanonicalVerifiedClaimSpine(
        status=status,  # type: ignore[arg-type]
        closure_question_en="How does API-42 preserve the model?",
        intent_class="direct_grounded_knowledge",
        requested_answer_language=requested_answer_language,
        semantic_contract_schema="schema/v1",
        semantic_contract_fingerprint="fingerprint/v1",
        answer_source=(
            "safe_abstention"
            if safe_abstention
            else "provider_verified_runtime_bound_semantic_closure"
        ),
        safe_abstention=safe_abstention,
        reason_codes=reason_codes,
        repair_attempted=False,
        unsupported_accepted_claims=unsupported_accepted_claims,
        citation_locator_valid=citation_locator_valid,
        material_claim_support_verified=material_claim_support_verified,
        canonical_claims=claims,
        citations=tuple(citation for claim in claims for citation in claim.citations),
        semantic_review={"claim_judgments": []},
        closure={"partial_answer": status == "verified_partial"},
        verification={"answer_source": "provider_verified_runtime_bound_semantic_closure"},
        publication_eligible_claim_count=sum(
            1 for claim in claims if claim.publication_eligible
        ),
        dropped_claim_ids=dropped_claim_ids,
        dropped_claim_count=dropped_claim_count,
    )


def realized_response(*items: tuple[str, str]) -> RequestedLanguageRealizationResponse:
    return RequestedLanguageRealizationResponse(
        claims=tuple(
            RequestedLanguageRealizationResponseClaim(
                claim_id=claim_id,
                requested_language_text=text,
            )
            for claim_id, text in items
        )
    )


def review_response(
    *items: tuple[str, RequestedLanguageEquivalenceReview],
) -> RequestedLanguageEquivalenceReviewResponse:
    return RequestedLanguageEquivalenceReviewResponse(
        reviews=tuple(review for _, review in items)
    )


def review_for(
    claim_id: str,
    *,
    equivalence: str = "pass",
    no_material_factual_expansion: bool = True,
    no_contradiction: bool = True,
    negation_preserved: str = "not_applicable",
    modality_preserved: str = "not_applicable",
    comparison_direction_preserved: str = "not_applicable",
    relationship_direction_preserved: str = "not_applicable",
    numeric_identity_preserved: str = "not_applicable",
    entity_identity_preserved: str = "not_applicable",
) -> RequestedLanguageEquivalenceReview:
    return RequestedLanguageEquivalenceReview(
        claim_id=claim_id,
        equivalence=equivalence,  # type: ignore[arg-type]
        no_material_factual_expansion=no_material_factual_expansion,
        no_contradiction=no_contradiction,
        negation_preserved=negation_preserved,  # type: ignore[arg-type]
        modality_preserved=modality_preserved,  # type: ignore[arg-type]
        comparison_direction_preserved=comparison_direction_preserved,  # type: ignore[arg-type]
        relationship_direction_preserved=relationship_direction_preserved,  # type: ignore[arg-type]
        numeric_identity_preserved=numeric_identity_preserved,  # type: ignore[arg-type]
        entity_identity_preserved=entity_identity_preserved,  # type: ignore[arg-type]
    )


def strict_review_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "claim_id": "claim-a",
        "equivalence": "pass",
        "no_material_factual_expansion": True,
        "no_contradiction": True,
        "negation_preserved": "not_applicable",
        "modality_preserved": "not_applicable",
        "comparison_direction_preserved": "not_applicable",
        "relationship_direction_preserved": "not_applicable",
        "numeric_identity_preserved": "true",
        "entity_identity_preserved": "true",
    }
    payload.update(overrides)
    return payload


def test_realizer_request_contains_only_public_claim_identity_and_canonical_text() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
            ("claim-b", "版本 3 會保持 5 ms 延遲。"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"), review_for("claim-b"))
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    request = realizer.calls[0]
    assert request.requested_answer_language == "zh-TW"
    assert [claim.canonical_claim_id for claim in request.claims] == ["claim-a", "claim-b"]
    assert [claim.canonical_surface_text_en for claim in request.claims] == [
        "API-42 uses the LLM model.",
        "Version 3 keeps 5 ms latency.",
    ]
    assert request.claims[0].preservation_markers == ("API-42", "LLM", "42")
    assert not hasattr(request.claims[0], "citations")
    assert not hasattr(request.claims[0], "support_evidence_refs")


def test_realizer_uses_publication_eligible_claims_only() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            canonical_claims=(claim_a(), claim_b(publication_eligible=False))
        ),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert [claim.canonical_claim_id for claim in realizer.calls[0].claims] == ["claim-a"]


def test_realizer_response_unknown_claim_id_fails_closed() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("unknown", "請保留 API-42。"))
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REALIZATION_UNKNOWN_CLAIM"
    assert reviewer.calls == []


def test_realizer_response_duplicate_claim_id_fails_closed() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42。"),
            ("claim-a", "請保留 API-42 與 LLM。"),
        )
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REALIZATION_DUPLICATE_CLAIM"
    assert reviewer.calls == []


def test_realizer_response_malformed_item_fails_closed() -> None:
    realizer = RecordingRealizer(response={"claims": ["not-a-claim"]})
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REALIZATION_SCHEMA_INVALID"


def test_realizer_response_requires_string_fields() -> None:
    realizer = RecordingRealizer(
        response={
            "claims": [
                {
                    "claim_id": 1,
                    "requested_language_text": 2,
                }
            ]
        }
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REALIZATION_SCHEMA_INVALID"


def test_empty_realized_text_drops_claim() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", ""),
            ("claim-b", "版本 3 會保持 5 ms 延遲。"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-b"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert [claim.canonical_claim_id for claim in result.publication.visible_claims] == [
        "claim-b"
    ]
    assert "claim-a" in result.publication.language_dropped_claim_ids


def test_missing_realized_claim_drops_claim() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert [claim.canonical_claim_id for claim in result.publication.visible_claims] == [
        "claim-a"
    ]
    assert "claim-b" in result.publication.language_dropped_claim_ids


def test_no_new_claim_can_appear() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
            ("claim-b", "版本 3 會保持 5 ms 延遲。"),
            ("claim-new", "新增內容"),
        )
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REALIZATION_UNKNOWN_CLAIM"


@pytest.mark.parametrize(
    "field_name,bad_value",
    [
        ("no_material_factual_expansion", "false"),
        ("no_material_factual_expansion", "true"),
        ("no_material_factual_expansion", 1),
        ("no_material_factual_expansion", 0),
        ("no_material_factual_expansion", None),
        ("no_contradiction", "false"),
        ("no_contradiction", "true"),
        ("no_contradiction", 1),
        ("no_contradiction", 0),
        ("no_contradiction", None),
    ],
)
def test_raw_review_boolean_fields_require_actual_booleans(
    field_name: str,
    bad_value: Any,
) -> None:
    reviewer = RecordingReviewer(
        response={"reviews": [strict_review_payload(**{field_name: bad_value})]}
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=RecordingRealizer(
            response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
        ),
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID"


def test_raw_review_equivalence_must_be_exact() -> None:
    malformed_reviews = [
        strict_review_payload(),
        strict_review_payload(equivalence="PASS"),
        strict_review_payload(equivalence=True),
        strict_review_payload(equivalence="unknown"),
    ]
    malformed_reviews[0].pop("equivalence")

    for payload in malformed_reviews:
        reviewer = RecordingReviewer(response={"reviews": [payload]})
        result = build_verified_requested_language_publication(
            canonical_spine=full_spine(canonical_claims=(claim_a(),)),
            realizer=RecordingRealizer(
                response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
            ),
            equivalence_reviewer=reviewer,
        )
        assert result.status == "failed"
        assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "field_name,bad_value",
    [
        ("negation_preserved", "unknown"),
        ("negation_preserved", True),
        ("negation_preserved", None),
        ("modality_preserved", "unknown"),
        ("modality_preserved", True),
        ("modality_preserved", None),
        ("comparison_direction_preserved", "unknown"),
        ("comparison_direction_preserved", True),
        ("comparison_direction_preserved", None),
        ("relationship_direction_preserved", "unknown"),
        ("relationship_direction_preserved", True),
        ("relationship_direction_preserved", None),
        ("numeric_identity_preserved", "unknown"),
        ("numeric_identity_preserved", True),
        ("numeric_identity_preserved", None),
        ("entity_identity_preserved", "unknown"),
        ("entity_identity_preserved", True),
        ("entity_identity_preserved", None),
    ],
)
def test_raw_review_semantic_dimensions_require_explicit_valid_values(
    field_name: str,
    bad_value: Any,
) -> None:
    payload = strict_review_payload(**{field_name: bad_value})
    if bad_value is None:
        payload.pop(field_name)
    reviewer = RecordingReviewer(response={"reviews": [payload]})

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=RecordingRealizer(
            response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
        ),
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID"


def test_valid_negative_review_drops_claim() -> None:
    reviewer = RecordingReviewer(
        response={"reviews": [strict_review_payload(equivalence="fail")]}
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=RecordingRealizer(
            response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
        ),
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "abstained"
    assert result.publication.visible_claims == ()


def test_typed_malformed_review_object_fails_closed() -> None:
    malformed_review = RequestedLanguageEquivalenceReview(
        claim_id="claim-a",
        equivalence="pass",
        no_material_factual_expansion="false",  # type: ignore[arg-type]
        no_contradiction=True,
        negation_preserved="true",
        modality_preserved="not_applicable",
        comparison_direction_preserved="not_applicable",
        relationship_direction_preserved="not_applicable",
        numeric_identity_preserved="true",
        entity_identity_preserved="true",
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=RecordingRealizer(
            response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
        ),
        equivalence_reviewer=RecordingReviewer(
            response=RequestedLanguageEquivalenceReviewResponse(
                reviews=(malformed_review,)
            )
        ),
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID"


def test_invalid_requested_language_fails_closed() -> None:
    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(requested_answer_language="fr"),
        realizer=None,
        equivalence_reviewer=None,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_INVALID"


@pytest.mark.parametrize(
    "surface_text, realized_text",
    [
        ("API-42 uses the router.", "請保留 API-42。"),
            ("The LLM model is stable.", "請保留 The LLM。"),
            ("ModelX-7 preserves state.", "請保留 ModelX-7。"),
            ("Version 3 is stable.", "版本 3 穩定。"),
            ("Keep 5 ms latency.", "保持 5 ms 延遲。"),
        ("Read https://example.com/docs.", "請保留 https://example.com/docs。"),
        ("Use `retry_once` now.", "請保留 `retry_once`。"),
    ],
)
def test_deterministic_preservation_keeps_required_markers(
    surface_text: str,
    realized_text: str,
) -> None:
    claim = ClaimFixture(
        claim_id="claim-a",
        surface_text=surface_text,
        citation_id="claim-a_ref_1",
        evidence_id="ev-a",
        locator_id="loc-a",
    ).canonical()
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", realized_text))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim,)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_claims[0].visible_text == realized_text


def test_lost_required_marker_drops_claim() -> None:
    claim = claim_a()
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留中文說明，但不保留 marker。"))
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim,)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_claim_count == 0
    assert result.publication.status == "abstained"


def test_marker_guard_does_not_act_as_multilingual_intent_classifier() -> None:
    claim = claim_a()
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim,)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_claims[0].visible_text == "請保留 API-42 與 LLM。"


def test_reviewer_receives_exact_canonical_and_realized_texts() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    review_request = reviewer.calls[0]
    assert review_request.requested_answer_language == "zh-TW"
    assert review_request.claims[0].canonical_claim_id == "claim-a"
    assert review_request.claims[0].canonical_surface_text_en == "API-42 uses the LLM model."
    assert review_request.claims[0].requested_language_text_zh_tw == "請保留 API-42 與 LLM。"
    assert not hasattr(review_request.claims[0], "citation_ids")


def test_reviewer_response_unknown_claim_id_fails_closed() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("unknown"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_UNKNOWN_CLAIM"


def test_reviewer_response_duplicate_claim_id_fails_closed() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"), review_for("claim-a"))
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_DUPLICATE_CLAIM"


def test_reviewer_response_malformed_verdict_fails_closed() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(response={"reviews": [{"claim_id": "claim-a"}]})

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert result.failure_code == "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID"


@pytest.mark.parametrize(
    "field_name",
    [
        "equivalence",
        "no_material_factual_expansion",
        "no_contradiction",
        "negation_preserved",
        "modality_preserved",
        "comparison_direction_preserved",
        "relationship_direction_preserved",
        "numeric_identity_preserved",
        "entity_identity_preserved",
    ],
)
def test_reviewer_dimension_false_drops_claim(field_name: str) -> None:
    review_kwargs = {
        "equivalence": "pass",
        "no_material_factual_expansion": True,
        "no_contradiction": True,
    }
    if field_name == "equivalence":
        review_kwargs[field_name] = "fail"
    elif field_name in {"no_material_factual_expansion", "no_contradiction"}:
        review_kwargs[field_name] = False
    else:
        review_kwargs[field_name] = "false"

    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a", **review_kwargs),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_claim_count == 0
    assert result.publication.status == "abstained"


def test_missing_review_drops_claim() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_claim_count == 0
    assert result.publication.status == "abstained"


def test_partial_upstream_all_retained_pass_verified_partial() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            status="verified_partial",
            canonical_claims=(claim_a(),),
            dropped_claim_ids=("claim-b",),
            dropped_claim_count=1,
        ),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "verified_partial"
    assert result.publication.canonical_dropped_claim_ids == ("claim-b",)


def test_conservative_omission_partial_spine_sends_only_retained_claim_ids() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            status="verified_partial",
            canonical_claims=(claim_a(),),
            dropped_claim_ids=("claim-generic",),
            dropped_claim_count=1,
        ),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "verified_partial"
    assert [claim.canonical_claim_id for claim in realizer.calls[0].claims] == ["claim-a"]
    assert [claim.canonical_claim_id for claim in reviewer.calls[0].claims] == ["claim-a"]
    assert "claim-generic" not in result.publication.visible_answer_text
    assert result.publication.canonical_dropped_claim_ids == ("claim-generic",)


def test_full_upstream_one_chinese_claim_fails_verified_partial() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
            ("claim-b", "遺失標記"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "verified_partial"
    assert result.publication.visible_claim_count == 1


def test_all_chinese_claims_fail_abstained() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "遺失標記"),
            ("claim-b", "也是遺失標記"),
        )
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "abstained"
    assert result.publication.visible_claim_count == 0


def test_upstream_abstained_skips_realizer_and_reviewer() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            status="abstained",
            canonical_claims=(),
            safe_abstention=True,
            reason_codes=("M26-PA7-ME-065",),
        ),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "abstained"
    assert realizer.calls == []
    assert reviewer.calls == []
    assert result.publication.visible_claims == ()


def test_conservative_omission_zero_retained_material_skips_publication_providers() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            status="abstained",
            canonical_claims=(),
            safe_abstention=True,
            reason_codes=("TRACK2_CITATION_FREE_MODEL_EXPLANATION_OMITTED",),
        ),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "abstained"
    assert result.publication.visible_claims == ()
    assert result.publication.visible_claim_count == 0
    assert realizer.calls == []
    assert reviewer.calls == []


def test_no_english_fallback_on_zh_tw_failure() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "遺失標記"))
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.status == "abstained"
    assert result.publication.visible_claims == ()


def test_dropped_claim_ids_retained() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
            ("claim-b", "遺失標記"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert "claim-b" in result.publication.language_dropped_claim_ids


def test_final_answer_contains_only_authorized_visible_claim_text() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-a", "請保留 API-42 與 LLM。"),
            ("claim-b", "遺失標記"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.visible_answer_text == "請保留 API-42 與 LLM。"
    assert "遺失標記" not in result.publication.visible_answer_text


def test_citations_are_attached_deterministically() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-a"),)
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    claim = result.publication.visible_claims[0]
    assert claim.citation_ids == ("claim-a_ref_1",)
    assert claim.citations == claim_a().citations
    assert claim.support_evidence_refs == claim_a().support_evidence_refs


def test_answer_order_is_deterministic_from_canonical_claim_order() -> None:
    realizer = RecordingRealizer(
        response=realized_response(
            ("claim-b", "版本 3 會保持 5 ms 延遲。"),
            ("claim-a", "請保留 API-42 與 LLM。"),
        )
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(
            reviews=(review_for("claim-b"), review_for("claim-a"))
        )
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.ok
    assert result.publication is not None
    assert [claim.canonical_claim_id for claim in result.publication.visible_claims] == [
        "claim-a",
        "claim-b",
    ]


def test_upstream_integrity_failures_are_rejected() -> None:
    bad_spines = [
        (full_spine(status="failed"), "failed"),
        (full_spine(unsupported_accepted_claims=1), "failed"),
        (full_spine(citation_locator_valid=False), "failed"),
        (full_spine(material_claim_support_verified=False), "failed"),
        (full_spine(canonical_claims=(claim_a(publication_eligible=False),)), "abstained"),
    ]
    for spine, expected_status in bad_spines:
        result = build_verified_requested_language_publication(canonical_spine=spine)
        assert result.status == expected_status


def test_realizer_exception_does_not_trigger_retry() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。")),
        fail=True,
    )
    reviewer = RecordingReviewer(response=RequestedLanguageEquivalenceReviewResponse())

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert len(realizer.calls) == 1
    assert reviewer.calls == []


def test_reviewer_exception_does_not_trigger_retry() -> None:
    realizer = RecordingRealizer(
        response=realized_response(("claim-a", "請保留 API-42 與 LLM。"))
    )
    reviewer = RecordingReviewer(
        response=RequestedLanguageEquivalenceReviewResponse(),
        fail=True,
    )

    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(canonical_claims=(claim_a(),)),
        realizer=realizer,
        equivalence_reviewer=reviewer,
    )

    assert result.status == "failed"
    assert len(realizer.calls) == 1
    assert len(reviewer.calls) == 1


def test_english_convenience_path_bypasses_realizer_and_reviewer() -> None:
    result = build_verified_requested_language_publication(
        canonical_spine=full_spine(
            requested_answer_language="en",
            canonical_claims=(claim_a(),),
        ),
        realizer=None,
        equivalence_reviewer=None,
    )

    assert result.ok
    assert result.publication is not None
    assert result.publication.requested_answer_language == "en"
    assert result.publication.visible_claims[0].visible_text == "API-42 uses the LLM model."


def test_publication_source_scan_has_no_provider_router_or_gaming_tokens() -> None:
    source = Path(__file__).resolve().parents[1].joinpath(
        "src/knowledge_engine/m26_multilingual_publication_adapter.py"
    )
    text = source.read_text(encoding="utf-8")

    for forbidden in (
        "m26_cloudflare_provider_router",
        "Q01",
        "Q03",
        "Q04",
        "Q06",
        "Q08",
        "差別",
        "benchmark",
        "R3",
        "derive_semantic_requirements",
        "_intent_class",
        "_synthesize_and_verify",
        "evaluate_visible_semantics",
    ):
        assert forbidden not in text
