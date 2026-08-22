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
    negation_preserved: SemanticVerdict
    modality_preserved: SemanticVerdict
    comparison_direction_preserved: SemanticVerdict
    relationship_direction_preserved: SemanticVerdict
    numeric_identity_preserved: SemanticVerdict
    entity_identity_preserved: SemanticVerdict
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
    requested_answer_language = _strict_requested_language(requested_answer_language)
    if requested_answer_language is None:
        raise ValueError("requested_answer_language must be en or zh-TW")
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
    requested_answer_language = _strict_requested_language(requested_answer_language)
    if requested_answer_language is None:
        raise ValueError("requested_answer_language must be en or zh-TW")
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
    requested_answer_language = _strict_requested_language(requested_answer_language)
    if requested_answer_language is None:
        raise ValueError("requested_answer_language must be en or zh-TW")
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
    parsed = parse_requested_language_equivalence_review_item(review)
    if parsed is None:
        return False
    if parsed.equivalence != "pass":
        return False
    if parsed.no_material_factual_expansion is not True:
        return False
    if parsed.no_contradiction is not True:
        return False
    for field_value in (
        parsed.negation_preserved,
        parsed.modality_preserved,
        parsed.comparison_direction_preserved,
        parsed.relationship_direction_preserved,
        parsed.numeric_identity_preserved,
        parsed.entity_identity_preserved,
    ):
        if field_value == "false":
            return False
    return True


def parse_requested_language_equivalence_review_item(
    item: Any,
) -> RequestedLanguageEquivalenceReview | None:
    if isinstance(item, RequestedLanguageEquivalenceReview):
        return (
            item
            if _validate_requested_language_equivalence_review_fields(item) is not None
            else None
        )
    if not isinstance(item, Mapping):
        return None
    claim_id = _strict_str(item, "claim_id")
    equivalence = _strict_enum(item, "equivalence", {"pass", "fail"})
    no_material_factual_expansion = _strict_bool(
        item, "no_material_factual_expansion"
    )
    no_contradiction = _strict_bool(item, "no_contradiction")
    negation_preserved = _strict_semantic_verdict(item, "negation_preserved")
    modality_preserved = _strict_semantic_verdict(item, "modality_preserved")
    comparison_direction_preserved = _strict_semantic_verdict(
        item, "comparison_direction_preserved"
    )
    relationship_direction_preserved = _strict_semantic_verdict(
        item, "relationship_direction_preserved"
    )
    numeric_identity_preserved = _strict_semantic_verdict(
        item, "numeric_identity_preserved"
    )
    entity_identity_preserved = _strict_semantic_verdict(
        item, "entity_identity_preserved"
    )
    if None in {
        claim_id,
        equivalence,
        no_material_factual_expansion,
        no_contradiction,
        negation_preserved,
        modality_preserved,
        comparison_direction_preserved,
        relationship_direction_preserved,
        numeric_identity_preserved,
        entity_identity_preserved,
    }:
        return None
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
        failure_code=_optional_str(item, "failure_code"),
        failure_detail=_optional_str(item, "failure_detail"),
    )


def has_visible_markers(text: str, markers: Sequence[str]) -> bool:
    return contains_any_marker(text, markers)


def _claim_field(claim: Any, field_name: str) -> str:
    if isinstance(claim, Mapping):
        return str(claim[field_name])
    return str(getattr(claim, field_name))


def _strict_requested_language(value: Any) -> RequestedLanguage | None:
    if value in {"en", "zh-TW"}:
        return value
    return None


def _validate_requested_language_equivalence_review_fields(
    review: RequestedLanguageEquivalenceReview,
) -> RequestedLanguageEquivalenceReview | None:
    claim_id = _strict_str(review, "claim_id")
    equivalence = _strict_enum(review, "equivalence", {"pass", "fail"})
    no_material_factual_expansion = _strict_bool(
        review, "no_material_factual_expansion"
    )
    no_contradiction = _strict_bool(review, "no_contradiction")
    negation_preserved = _strict_semantic_verdict(review, "negation_preserved")
    modality_preserved = _strict_semantic_verdict(review, "modality_preserved")
    comparison_direction_preserved = _strict_semantic_verdict(
        review, "comparison_direction_preserved"
    )
    relationship_direction_preserved = _strict_semantic_verdict(
        review, "relationship_direction_preserved"
    )
    numeric_identity_preserved = _strict_semantic_verdict(review, "numeric_identity_preserved")
    entity_identity_preserved = _strict_semantic_verdict(review, "entity_identity_preserved")
    if None in {
        claim_id,
        equivalence,
        no_material_factual_expansion,
        no_contradiction,
        negation_preserved,
        modality_preserved,
        comparison_direction_preserved,
        relationship_direction_preserved,
        numeric_identity_preserved,
        entity_identity_preserved,
    }:
        return None
    return review


def _strict_str(item: Any, field_name: str) -> str | None:
    value = _field_value(item, field_name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_str(item: Any, field_name: str) -> str:
    value = _field_value(item, field_name)
    if value is None:
        return ""
    return str(value)


def _strict_bool(item: Any, field_name: str) -> bool | None:
    value = _field_value(item, field_name)
    if isinstance(value, bool):
        return value
    return None


def _strict_enum(item: Any, field_name: str, allowed: set[str]) -> str | None:
    value = _field_value(item, field_name)
    if not isinstance(value, str) or value not in allowed:
        return None
    return value


def _strict_semantic_verdict(item: Any, field_name: str) -> SemanticVerdict | None:
    value = _field_value(item, field_name)
    if not isinstance(value, str) or value not in {"true", "false", "not_applicable"}:
        return None
    return value  # type: ignore[return-value]


def _field_value(item: Any, field_name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field_name, _MISSING)
    if hasattr(item, field_name):
        return getattr(item, field_name)
    return _MISSING


_MISSING = object()
