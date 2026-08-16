from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .m26_multilingual_canonicalization import (
    contains_any_marker,
    extract_preservation_markers,
)

RequestedLanguage = Literal["zh-TW", "en"]
EquivalenceVerdict = Literal["pass", "fail"]
SemanticVerdict = Literal["true", "false", "not_applicable"]
MarkerPreservationVerdict = Literal["pass", "fail", "not_applicable"]


@dataclass(frozen=True)
class RequestedLanguageRealizationClaim:
    canonical_claim_id: str
    canonical_surface_text_en: str
    requested_answer_language: RequestedLanguage
    preservation_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequestedLanguageRealizationRequest:
    requested_answer_language: RequestedLanguage
    claims: tuple[RequestedLanguageRealizationClaim, ...]


@dataclass(frozen=True)
class RequestedLanguageRealizationResponseClaim:
    claim_id: str
    requested_language_text: str


@dataclass(frozen=True)
class RequestedLanguageRealizationResponse:
    claims: tuple[RequestedLanguageRealizationResponseClaim, ...] = ()


@dataclass(frozen=True)
class RequestedLanguageEquivalenceReviewClaim:
    canonical_claim_id: str
    canonical_surface_text_en: str
    requested_language_text_zh_tw: str
    requested_answer_language: RequestedLanguage
    preservation_markers: tuple[str, ...] = ()
    marker_preservation_status: MarkerPreservationVerdict = "not_applicable"


@dataclass(frozen=True)
class RequestedLanguageEquivalenceReviewRequest:
    requested_answer_language: RequestedLanguage
    claims: tuple[RequestedLanguageEquivalenceReviewClaim, ...]


@dataclass(frozen=True)
class RequestedLanguageEquivalenceReview:
    claim_id: str
    equivalence: EquivalenceVerdict
    no_material_factual_expansion: bool
    no_contradiction: bool
    negation_preserved: SemanticVerdict = "not_applicable"
    modality_preserved: SemanticVerdict = "not_applicable"
    comparison_direction_preserved: SemanticVerdict = "not_applicable"
    relationship_direction_preserved: SemanticVerdict = "not_applicable"
    numeric_identity_preserved: SemanticVerdict = "not_applicable"
    entity_identity_preserved: SemanticVerdict = "not_applicable"
    failure_code: str = ""
    failure_detail: str = ""


@dataclass(frozen=True)
class RequestedLanguageEquivalenceReviewResponse:
    reviews: tuple[RequestedLanguageEquivalenceReview, ...] = ()


class RequestedLanguageRealizer(Protocol):
    def __call__(
        self, request: RequestedLanguageRealizationRequest
    ) -> RequestedLanguageRealizationResponse: ...


class RequestedLanguageEquivalenceReviewer(Protocol):
    def __call__(
        self, request: RequestedLanguageEquivalenceReviewRequest
    ) -> RequestedLanguageEquivalenceReviewResponse: ...


def build_requested_language_realization_claim(
    *,
    canonical_claim_id: str,
    canonical_surface_text_en: str,
    requested_answer_language: RequestedLanguage,
) -> RequestedLanguageRealizationClaim:
    return RequestedLanguageRealizationClaim(
        canonical_claim_id=canonical_claim_id,
        canonical_surface_text_en=canonical_surface_text_en,
        requested_answer_language=requested_answer_language,
        preservation_markers=tuple(
            extract_preservation_markers(canonical_surface_text_en)
        ),
    )


def build_requested_language_realization_request(
    *,
    requested_answer_language: RequestedLanguage,
    canonical_claims: Sequence[Any],
) -> RequestedLanguageRealizationRequest:
    return RequestedLanguageRealizationRequest(
        requested_answer_language=requested_answer_language,
        claims=tuple(
            RequestedLanguageRealizationClaim(
                canonical_claim_id=_claim_field(claim, "claim_id"),
                canonical_surface_text_en=_claim_field(claim, "surface_text"),
                requested_answer_language=requested_answer_language,
                preservation_markers=tuple(
                    extract_preservation_markers(_claim_field(claim, "surface_text"))
                ),
            )
            for claim in canonical_claims
        ),
    )


def build_requested_language_equivalence_request(
    *,
    requested_answer_language: RequestedLanguage,
    canonical_claims: Sequence[Any],
    realized_text_by_claim_id: Mapping[str, str],
    marker_preservation_status_by_claim_id: Mapping[str, MarkerPreservationVerdict],
) -> RequestedLanguageEquivalenceReviewRequest:
    claims = []
    for claim in canonical_claims:
        claim_id = _claim_field(claim, "claim_id")
        claims.append(
            RequestedLanguageEquivalenceReviewClaim(
                canonical_claim_id=claim_id,
                canonical_surface_text_en=_claim_field(claim, "surface_text"),
                requested_language_text_zh_tw=realized_text_by_claim_id[claim_id],
                requested_answer_language=requested_answer_language,
                preservation_markers=tuple(
                    extract_preservation_markers(_claim_field(claim, "surface_text"))
                ),
                marker_preservation_status=marker_preservation_status_by_claim_id[
                    claim_id
                ],
            )
        )
    return RequestedLanguageEquivalenceReviewRequest(
        requested_answer_language=requested_answer_language,
        claims=tuple(claims),
    )


def evaluate_marker_preservation(
    *,
    canonical_surface_text_en: str,
    requested_language_text: str,
) -> tuple[MarkerPreservationVerdict, tuple[str, ...]]:
    markers = tuple(extract_preservation_markers(canonical_surface_text_en))
    if not markers:
        return "not_applicable", ()
    missing = tuple(
        marker
        for marker in markers
        if marker.casefold() not in requested_language_text.casefold()
    )
    if missing:
        return "fail", missing
    return "pass", ()


def review_authorizes_claim(review: RequestedLanguageEquivalenceReview) -> bool:
    if review.equivalence != "pass":
        return False
    if not review.no_material_factual_expansion:
        return False
    if not review.no_contradiction:
        return False
    for field_value in (
        review.negation_preserved,
        review.modality_preserved,
        review.comparison_direction_preserved,
        review.relationship_direction_preserved,
        review.numeric_identity_preserved,
        review.entity_identity_preserved,
    ):
        if field_value == "false":
            return False
    return True


def has_visible_markers(text: str, markers: Sequence[str]) -> bool:
    return contains_any_marker(text, markers)


def _claim_field(claim: Any, field_name: str) -> str:
    if isinstance(claim, Mapping):
        return str(claim[field_name])
    return str(getattr(claim, field_name))
