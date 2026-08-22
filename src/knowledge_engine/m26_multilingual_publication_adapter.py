from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .m26_multilingual_equivalence import (
    EquivalenceVerdict,
    MarkerPreservationVerdict,
    RequestedLanguage,
    RequestedLanguageEquivalenceReview,
    RequestedLanguageEquivalenceReviewer,
    RequestedLanguageEquivalenceReviewRequest,
    RequestedLanguageRealizationRequest,
    RequestedLanguageRealizationResponse,
    RequestedLanguageRealizer,
    build_requested_language_equivalence_request,
    build_requested_language_realization_request,
    evaluate_marker_preservation,
    parse_requested_language_equivalence_review_item,
    review_authorizes_claim,
)
from .m26_multilingual_verified_claim_spine import (
    CanonicalSupportEvidenceRef,
    CanonicalVerifiedClaim,
    CanonicalVerifiedClaimSpine,
)

VerifiedRequestedLanguagePublicationStatus = Literal[
    "verified_full",
    "verified_partial",
    "abstained",
    "failed",
]


@dataclass(frozen=True)
class VerifiedRequestedLanguageClaim:
    canonical_claim_id: str
    requested_language: RequestedLanguage
    visible_text: str
    canonical_surface_text_en: str
    citation_ids: tuple[str, ...]
    citations: tuple[Mapping[str, Any], ...]
    support_evidence_refs: tuple[CanonicalSupportEvidenceRef, ...]
    equivalence_review_status: EquivalenceVerdict
    publication_eligible: bool
    marker_preservation_status: MarkerPreservationVerdict = "not_applicable"
    equivalence_review: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedRequestedLanguagePublication:
    status: VerifiedRequestedLanguagePublicationStatus
    requested_answer_language: RequestedLanguage
    visible_claims: tuple[VerifiedRequestedLanguageClaim, ...]
    visible_answer_text: str
    canonical_claim_count: int
    visible_claim_count: int
    language_dropped_claim_ids: tuple[str, ...]
    canonical_dropped_claim_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    repair_attempted_from_canonical_spine: bool
    unsupported_accepted_claims: int
    citation_locator_valid: bool
    material_claim_support_verified: bool
    semantic_contract_fingerprint: str
    telemetry: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedRequestedLanguagePublicationResult:
    status: VerifiedRequestedLanguagePublicationStatus
    publication: VerifiedRequestedLanguagePublication | None = None
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"verified_full", "verified_partial", "abstained"}


def build_verified_requested_language_publication(
    *,
    canonical_spine: CanonicalVerifiedClaimSpine,
    realizer: RequestedLanguageRealizer | None = None,
    equivalence_reviewer: RequestedLanguageEquivalenceReviewer | None = None,
) -> VerifiedRequestedLanguagePublicationResult:
    if canonical_spine.status == "failed":
        return _failure(
            "REQUESTED_LANGUAGE_UPSTREAM_SPINE_FAILED",
            "canonical verified claim spine failed before publication",
        )
    if canonical_spine.unsupported_accepted_claims > 0:
        return _failure(
            "REQUESTED_LANGUAGE_UPSTREAM_UNSUPPORTED_ACCEPTED_CLAIMS",
            "canonical spine reported unsupported accepted claims",
        )
    if not canonical_spine.citation_locator_valid:
        return _failure(
            "REQUESTED_LANGUAGE_UPSTREAM_INVALID_CITATION_LOCATOR",
            "canonical spine reported invalid citation locator",
        )
    if not canonical_spine.material_claim_support_verified:
        return _failure(
            "REQUESTED_LANGUAGE_UPSTREAM_MATERIAL_SUPPORT_UNVERIFIED",
            "canonical spine reported unverified material claim support",
        )
    requested_language = _normalize_requested_language(
        canonical_spine.requested_answer_language
    )
    if requested_language is None:
        return _failure(
            "REQUESTED_LANGUAGE_INVALID",
            "requested answer language must be en or zh-TW",
        )
    publication_claims = _publication_claims(canonical_spine.canonical_claims)
    if canonical_spine.status == "abstained" or not publication_claims:
        return _abstained_result(
            canonical_spine=canonical_spine,
            requested_language=requested_language,
            visible_claims=(),
            language_dropped_claim_ids=(),
        )
    if requested_language == "en":
        visible_claims = tuple(
            _english_visible_claim(canonical_claim=claim, requested_language=requested_language)
            for claim in publication_claims
        )
        return _finalize_result(
            canonical_spine=canonical_spine,
            requested_language=requested_language,
            publication_claims=publication_claims,
            visible_claims=visible_claims,
            language_dropped_claim_ids=(),
        )
    if realizer is None:
        return _failure(
            "REQUESTED_LANGUAGE_REALIZER_REQUIRED",
            "zh-TW publication requires a requested-language realizer",
        )
    if equivalence_reviewer is None:
        return _failure(
            "REQUESTED_LANGUAGE_EQUIVALENCE_REVIEWER_REQUIRED",
            "zh-TW publication requires a language-equivalence reviewer",
        )

    realization_request = build_requested_language_realization_request(
        requested_answer_language=requested_language,
        canonical_claims=publication_claims,
    )
    try:
        realization_response = realizer(realization_request)
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("REQUESTED_LANGUAGE_REALIZER_FAILED", str(exc))
    realization_result = _validate_realization_response(
        request=realization_request,
        response=realization_response,
    )
    if isinstance(realization_result, VerifiedRequestedLanguagePublicationResult):
        return realization_result
    realized_text_by_claim_id, empty_or_missing_claim_ids = realization_result
    if not realized_text_by_claim_id:
        return _abstained_result(
            canonical_spine=canonical_spine,
            requested_language=requested_language,
            visible_claims=(),
            language_dropped_claim_ids=empty_or_missing_claim_ids,
        )

    marker_preservation_status_by_claim_id: dict[str, MarkerPreservationVerdict] = {}
    marker_drop_claim_ids: list[str] = []
    realized_claim_ids: list[str] = []
    for claim in publication_claims:
        claim_id = claim.claim_id
        realized_text = realized_text_by_claim_id.get(claim_id)
        if realized_text is None:
            marker_drop_claim_ids.append(claim_id)
            continue
        marker_status, _missing_markers = evaluate_marker_preservation(
            canonical_surface_text_en=claim.surface_text,
            requested_language_text=realized_text,
        )
        marker_preservation_status_by_claim_id[claim_id] = marker_status
        if marker_status == "fail":
            marker_drop_claim_ids.append(claim_id)
            continue
        if not realized_text.strip():
            marker_drop_claim_ids.append(claim_id)
            continue
        realized_claim_ids.append(claim_id)

    if not realized_claim_ids:
        return _abstained_result(
            canonical_spine=canonical_spine,
            requested_language=requested_language,
            visible_claims=(),
            language_dropped_claim_ids=tuple(
                _dedupe_ordered(
                    empty_or_missing_claim_ids + tuple(marker_drop_claim_ids)
                )
            ),
        )

    review_request = build_requested_language_equivalence_request(
        requested_answer_language=requested_language,
        canonical_claims=[
            claim for claim in publication_claims if claim.claim_id in set(realized_claim_ids)
        ],
        realized_text_by_claim_id=realized_text_by_claim_id,
        marker_preservation_status_by_claim_id=marker_preservation_status_by_claim_id,
    )
    try:
        review_response = equivalence_reviewer(review_request)
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("REQUESTED_LANGUAGE_EQUIVALENCE_REVIEWER_FAILED", str(exc))
    review_result = _validate_review_response(
        request=review_request,
        response=review_response,
    )
    if isinstance(review_result, VerifiedRequestedLanguagePublicationResult):
        return review_result
    review_by_claim_id = review_result

    visible_claims: list[VerifiedRequestedLanguageClaim] = []
    language_dropped_claim_ids = list(empty_or_missing_claim_ids)
    language_dropped_claim_ids.extend(marker_drop_claim_ids)
    realized_claim_id_set = set(realized_claim_ids)
    for claim in publication_claims:
        claim_id = claim.claim_id
        if claim_id not in realized_claim_id_set:
            if claim_id not in language_dropped_claim_ids:
                language_dropped_claim_ids.append(claim_id)
            continue
        review = review_by_claim_id.get(claim_id)
        if review is None:
            language_dropped_claim_ids.append(claim_id)
            continue
        if not review_authorizes_claim(review):
            language_dropped_claim_ids.append(claim_id)
            continue
        visible_claims.append(
            _visible_claim_from_canonical(
                canonical_claim=claim,
                requested_language=requested_language,
                visible_text=realized_text_by_claim_id[claim_id],
                review=review,
                marker_preservation_status=marker_preservation_status_by_claim_id[
                    claim_id
                ],
            )
        )

    return _finalize_result(
        canonical_spine=canonical_spine,
        requested_language=requested_language,
        publication_claims=publication_claims,
        visible_claims=tuple(visible_claims),
        language_dropped_claim_ids=_dedupe_ordered(tuple(language_dropped_claim_ids)),
    )


def _publication_claims(
    canonical_claims: Sequence[CanonicalVerifiedClaim],
) -> tuple[CanonicalVerifiedClaim, ...]:
    return tuple(claim for claim in canonical_claims if claim.publication_eligible)


def _normalize_requested_language(value: str) -> RequestedLanguage | None:
    if value in {"en", "zh-TW"}:
        return value
    return None


def _english_visible_claim(
    *,
    canonical_claim: CanonicalVerifiedClaim,
    requested_language: RequestedLanguage,
) -> VerifiedRequestedLanguageClaim:
    return VerifiedRequestedLanguageClaim(
        canonical_claim_id=canonical_claim.claim_id,
        requested_language=requested_language,
        visible_text=canonical_claim.surface_text,
        canonical_surface_text_en=canonical_claim.surface_text,
        citation_ids=canonical_claim.citation_ids,
        citations=canonical_claim.citations,
        support_evidence_refs=canonical_claim.support_evidence_refs,
        equivalence_review_status="pass",
        publication_eligible=canonical_claim.publication_eligible,
        marker_preservation_status="pass",
        equivalence_review={
            "claim_id": canonical_claim.claim_id,
            "equivalence": "pass",
            "no_material_factual_expansion": True,
            "no_contradiction": True,
            "review_mode": "english_bypass",
        },
    )


def _visible_claim_from_canonical(
    *,
    canonical_claim: CanonicalVerifiedClaim,
    requested_language: RequestedLanguage,
    visible_text: str,
    review: RequestedLanguageEquivalenceReview,
    marker_preservation_status: MarkerPreservationVerdict,
) -> VerifiedRequestedLanguageClaim:
    return VerifiedRequestedLanguageClaim(
        canonical_claim_id=canonical_claim.claim_id,
        requested_language=requested_language,
        visible_text=visible_text,
        canonical_surface_text_en=canonical_claim.surface_text,
        citation_ids=canonical_claim.citation_ids,
        citations=canonical_claim.citations,
        support_evidence_refs=canonical_claim.support_evidence_refs,
        equivalence_review_status=review.equivalence,
        publication_eligible=canonical_claim.publication_eligible,
        marker_preservation_status=marker_preservation_status,
        equivalence_review=asdict(review),
    )


def _validate_realization_response(
    *,
    request: RequestedLanguageRealizationRequest,
    response: RequestedLanguageRealizationResponse | Mapping[str, Any] | Any,
) -> (
    tuple[dict[str, str], tuple[str, ...]]
    | VerifiedRequestedLanguagePublicationResult
):
    try:
        items = _response_items(response, "claims", "realization response")
    except ValueError as exc:
        return _failure("REQUESTED_LANGUAGE_REALIZATION_SCHEMA_INVALID", str(exc))
    requested_ids = [claim.canonical_claim_id for claim in request.claims]
    requested_id_set = set(requested_ids)
    seen: set[str] = set()
    realized_text_by_claim_id: dict[str, str] = {}
    missing_or_empty: list[str] = []
    for item in items:
        claim_id = _response_field(item, "claim_id", allow_aliases=("canonical_claim_id",))
        if not claim_id:
            return _failure(
                "REQUESTED_LANGUAGE_REALIZATION_SCHEMA_INVALID",
                "realization response claim omitted claim_id",
            )
        if claim_id not in requested_id_set:
            return _failure(
                "REQUESTED_LANGUAGE_REALIZATION_UNKNOWN_CLAIM",
                "realization response referenced an unknown claim_id",
            )
        if claim_id in seen:
            return _failure(
                "REQUESTED_LANGUAGE_REALIZATION_DUPLICATE_CLAIM",
                "realization response repeated a claim_id",
            )
        seen.add(claim_id)
        realized_text = _response_field(
            item,
            "requested_language_text",
            allow_aliases=("visible_text", "requested_language_text_zh_tw"),
        )
        if realized_text is None:
            return _failure(
                "REQUESTED_LANGUAGE_REALIZATION_SCHEMA_INVALID",
                "realization response omitted requested_language_text",
            )
        if not realized_text.strip():
            missing_or_empty.append(claim_id)
            continue
        realized_text_by_claim_id[claim_id] = realized_text
    for claim_id in requested_ids:
        if claim_id not in realized_text_by_claim_id:
            missing_or_empty.append(claim_id)
    return realized_text_by_claim_id, tuple(_dedupe_ordered(tuple(missing_or_empty)))


def _validate_review_response(
    *,
    request: RequestedLanguageEquivalenceReviewRequest,
    response: Mapping[str, Any] | Any,
) -> dict[str, RequestedLanguageEquivalenceReview] | VerifiedRequestedLanguagePublicationResult:
    try:
        items = _response_items(response, "reviews", "equivalence review response")
    except ValueError as exc:
        return _failure("REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID", str(exc))
    requested_ids = [claim.canonical_claim_id for claim in request.claims]
    requested_id_set = set(requested_ids)
    seen: set[str] = set()
    review_by_claim_id: dict[str, RequestedLanguageEquivalenceReview] = {}
    for item in items:
        claim_id = _response_field(item, "claim_id", allow_aliases=("canonical_claim_id",))
        if not claim_id:
            return _failure(
                "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID",
                "equivalence review response claim omitted claim_id",
            )
        if claim_id not in requested_id_set:
            return _failure(
                "REQUESTED_LANGUAGE_REVIEW_UNKNOWN_CLAIM",
                "equivalence review response referenced an unknown claim_id",
            )
        if claim_id in seen:
            return _failure(
                "REQUESTED_LANGUAGE_REVIEW_DUPLICATE_CLAIM",
                "equivalence review response repeated a claim_id",
            )
        seen.add(claim_id)
        review = _coerce_review(item)
        if review is None:
            return _failure(
                "REQUESTED_LANGUAGE_REVIEW_SCHEMA_INVALID",
                "equivalence review response omitted required verdict fields",
            )
        review_by_claim_id[claim_id] = review
    return review_by_claim_id


def _coerce_review(item: Any) -> RequestedLanguageEquivalenceReview | None:
    return parse_requested_language_equivalence_review_item(item)


def _response_items(response: Any, field_name: str, label: str) -> tuple[Any, ...]:
    if isinstance(response, Mapping):
        items = response.get(field_name)
    else:
        items = getattr(response, field_name, None)
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise ValueError(f"{label} must include a sequence of items")
    return tuple(items)


def _response_field(
    item: Any,
    field_name: str,
    *,
    allow_aliases: Sequence[str] = (),
) -> str | None:
    value: Any = None
    if isinstance(item, Mapping):
        if field_name in item:
            value = item[field_name]
        else:
            for alias in allow_aliases:
                if alias in item:
                    value = item[alias]
                    break
    else:
        if hasattr(item, field_name):
            value = getattr(item, field_name)
        else:
            for alias in allow_aliases:
                if hasattr(item, alias):
                    value = getattr(item, alias)
                    break
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    if field_name == "claim_id" and not value.strip():
        return None
    return value


def _finalize_result(
    *,
    canonical_spine: CanonicalVerifiedClaimSpine,
    requested_language: RequestedLanguage,
    publication_claims: Sequence[CanonicalVerifiedClaim],
    visible_claims: tuple[VerifiedRequestedLanguageClaim, ...],
    language_dropped_claim_ids: tuple[str, ...],
) -> VerifiedRequestedLanguagePublicationResult:
    status = _publication_status(
        canonical_status=canonical_spine.status,
        publication_claim_count=len(publication_claims),
        visible_claim_count=len(visible_claims),
        language_dropped_claim_ids=language_dropped_claim_ids,
    )
    publication = VerifiedRequestedLanguagePublication(
        status=status,
        requested_answer_language=requested_language,
        visible_claims=visible_claims,
        visible_answer_text=_assemble_visible_answer_text(visible_claims),
        canonical_claim_count=len(publication_claims),
        visible_claim_count=len(visible_claims),
        language_dropped_claim_ids=language_dropped_claim_ids,
        canonical_dropped_claim_ids=canonical_spine.dropped_claim_ids,
        reason_codes=canonical_spine.reason_codes,
        repair_attempted_from_canonical_spine=canonical_spine.repair_attempted,
        unsupported_accepted_claims=canonical_spine.unsupported_accepted_claims,
        citation_locator_valid=canonical_spine.citation_locator_valid,
        material_claim_support_verified=canonical_spine.material_claim_support_verified,
        semantic_contract_fingerprint=canonical_spine.semantic_contract_fingerprint,
        telemetry={
            "canonical_claim_count": len(publication_claims),
            "visible_claim_count": len(visible_claims),
            "language_dropped_claim_count": len(language_dropped_claim_ids),
            "canonical_dropped_claim_count": canonical_spine.dropped_claim_count,
            "requested_answer_language": requested_language,
        },
    )
    return VerifiedRequestedLanguagePublicationResult(
        status=status,
        publication=publication,
    )


def _abstained_result(
    *,
    canonical_spine: CanonicalVerifiedClaimSpine,
    requested_language: RequestedLanguage,
    visible_claims: tuple[VerifiedRequestedLanguageClaim, ...],
    language_dropped_claim_ids: tuple[str, ...],
) -> VerifiedRequestedLanguagePublicationResult:
    publication = VerifiedRequestedLanguagePublication(
        status="abstained",
        requested_answer_language=requested_language,
        visible_claims=visible_claims,
        visible_answer_text="",
        canonical_claim_count=len(_publication_claims(canonical_spine.canonical_claims)),
        visible_claim_count=len(visible_claims),
        language_dropped_claim_ids=language_dropped_claim_ids,
        canonical_dropped_claim_ids=canonical_spine.dropped_claim_ids,
        reason_codes=canonical_spine.reason_codes,
        repair_attempted_from_canonical_spine=canonical_spine.repair_attempted,
        unsupported_accepted_claims=canonical_spine.unsupported_accepted_claims,
        citation_locator_valid=canonical_spine.citation_locator_valid,
        material_claim_support_verified=canonical_spine.material_claim_support_verified,
        semantic_contract_fingerprint=canonical_spine.semantic_contract_fingerprint,
        telemetry={
            "canonical_claim_count": len(_publication_claims(canonical_spine.canonical_claims)),
            "visible_claim_count": len(visible_claims),
            "language_dropped_claim_count": len(language_dropped_claim_ids),
            "canonical_dropped_claim_count": canonical_spine.dropped_claim_count,
            "requested_answer_language": requested_language,
        },
    )
    return VerifiedRequestedLanguagePublicationResult(
        status="abstained",
        publication=publication,
    )


def _publication_status(
    *,
    canonical_status: str,
    publication_claim_count: int,
    visible_claim_count: int,
    language_dropped_claim_ids: tuple[str, ...],
) -> VerifiedRequestedLanguagePublicationStatus:
    if canonical_status == "abstained" or publication_claim_count == 0:
        return "abstained"
    if visible_claim_count == 0:
        return "abstained"
    if (
        canonical_status == "verified_full"
        and not language_dropped_claim_ids
        and visible_claim_count == publication_claim_count
    ):
        return "verified_full"
    return "verified_partial"


def _assemble_visible_answer_text(
    visible_claims: Sequence[VerifiedRequestedLanguageClaim],
) -> str:
    return "\n\n".join(claim.visible_text for claim in visible_claims if claim.visible_text)


def _dedupe_ordered(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _failure(code: str, detail: str) -> VerifiedRequestedLanguagePublicationResult:
    return VerifiedRequestedLanguagePublicationResult(
        status="failed",
        failure_code=code,
        failure_detail=detail,
    )
