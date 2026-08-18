from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .m26_aq_semantic_contract import synthesize_and_verify
from .m26_multilingual_semantic_spine import CanonicalSemanticContext

VerifiedClaimSpineStatus = Literal[
    "verified_full",
    "verified_partial",
    "abstained",
    "failed",
]


@dataclass(frozen=True)
class CanonicalSupportEvidenceRef:
    citation_id: str
    evidence_id: str
    locator_id: str
    source_identity: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class CanonicalVerifiedClaim:
    claim_id: str
    surface_text: str
    claim_role: str
    claim_type: str
    facet_ids: tuple[str, ...]
    support_mode: str
    support_ref_count: int
    source_identities: tuple[str, ...]
    citation_ids: tuple[str, ...]
    citations: tuple[Mapping[str, Any], ...]
    support_evidence_refs: tuple[CanonicalSupportEvidenceRef, ...]
    publication_eligible: bool


@dataclass(frozen=True)
class CanonicalVerifiedClaimSpine:
    status: VerifiedClaimSpineStatus
    closure_question_en: str
    intent_class: str
    requested_answer_language: str
    semantic_contract_schema: str
    semantic_contract_fingerprint: str
    answer_source: str
    safe_abstention: bool
    reason_codes: tuple[str, ...]
    repair_attempted: bool
    unsupported_accepted_claims: int
    citation_locator_valid: bool
    material_claim_support_verified: bool
    canonical_claims: tuple[CanonicalVerifiedClaim, ...]
    citations: tuple[Mapping[str, Any], ...]
    semantic_review: Mapping[str, Any]
    closure: Mapping[str, Any]
    verification: Mapping[str, Any]
    publication_eligible_claim_count: int
    dropped_claim_ids: tuple[str, ...] = ()
    dropped_claim_count: int = 0
    telemetry: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalVerifiedClaimSpineResult:
    status: VerifiedClaimSpineStatus
    spine: CanonicalVerifiedClaimSpine | None = None
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"verified_full", "verified_partial", "abstained"}


ClosureRunner = Callable[..., tuple[Mapping[str, Any], Mapping[str, Any]]]


@dataclass(frozen=True)
class CanonicalClaimProjection:
    canonical_claims: tuple[CanonicalVerifiedClaim, ...]
    omitted_model_explanation_claim_ids: tuple[str, ...] = ()


def build_canonical_verified_claim_spine(
    *,
    context: CanonicalSemanticContext,
    selected_authorized_evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    endpoint_proof: Mapping[str, Any],
    trace_id: str,
    closure_runner: ClosureRunner = synthesize_and_verify,
) -> CanonicalVerifiedClaimSpineResult:
    try:
        verification, closure = closure_runner(
            question=context.closure_question_en,
            trace_id=trace_id,
            intent_class=context.intent_class,
            evidence=selected_authorized_evidence,
            provider_client=provider_client,
            requirements=context.semantic_requirements,
            endpoint_proof=endpoint_proof,
        )
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("CANONICAL_CLOSURE_AUTHORITY_FAILED", str(exc))
    return project_verified_claim_spine(
        context=context,
        verification=verification,
        closure=closure,
    )


def project_verified_claim_spine(
    *,
    context: CanonicalSemanticContext,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> CanonicalVerifiedClaimSpineResult:
    fingerprint_failure = _semantic_contract_fingerprint_failure(context, verification, closure)
    if fingerprint_failure is not None:
        return fingerprint_failure

    answer_source = str(verification.get("answer_source", "safe_abstention"))
    reason_codes = _string_tuple(verification.get("reason_codes", ()))
    safe_abstention = bool(verification.get("safe_abstention", False)) or (
        verification.get("status") == "owner_only_safe_abstention"
    )
    repair_attempted = bool(verification.get("repair_attempted", False))
    unsupported_accepted_claims = int(verification.get("unsupported_accepted_claims", 0))
    citation_locator_valid = bool(verification.get("citation_locator_valid", True))
    material_claim_support_verified = bool(
        verification.get("material_claim_support_verified", True)
    )
    semantic_review = _semantic_review(verification, closure)
    dropped_claim_ids, dropped_claim_count = _partial_drop_metadata(verification, closure)

    if safe_abstention:
        return _spine_result(
            status="abstained",
            context=context,
            verification=verification,
            closure=closure,
            answer_source=answer_source,
            safe_abstention=True,
            reason_codes=reason_codes,
            repair_attempted=repair_attempted,
            unsupported_accepted_claims=unsupported_accepted_claims,
            citation_locator_valid=citation_locator_valid,
            material_claim_support_verified=material_claim_support_verified,
            canonical_claims=(),
            citations=(),
            semantic_review=semantic_review,
            dropped_claim_ids=dropped_claim_ids,
            dropped_claim_count=dropped_claim_count,
        )

    integrity_failure = _integrity_failure(
        unsupported_accepted_claims=unsupported_accepted_claims,
        citation_locator_valid=citation_locator_valid,
        material_claim_support_verified=material_claim_support_verified,
    )
    if integrity_failure is not None:
        return integrity_failure

    try:
        citations = tuple(_mapping_items(verification.get("citations", ()), "citations"))
    except ValueError as exc:
        return _failure("VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID", str(exc))

    try:
        raw_claims = _mapping_items(verification.get("answer_claims", ()), "answer_claims")
    except ValueError as exc:
        return _failure("VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID", str(exc))
    claim_result = _canonical_claims(raw_claims, citations)
    if isinstance(claim_result, CanonicalVerifiedClaimSpineResult):
        return claim_result
    omitted_model_explanation_claim_ids = claim_result.omitted_model_explanation_claim_ids
    dropped_claim_ids, dropped_claim_count = _merged_dropped_metadata(
        dropped_claim_ids,
        dropped_claim_count,
        omitted_model_explanation_claim_ids,
    )
    if not claim_result.canonical_claims:
        if omitted_model_explanation_claim_ids:
            return _spine_result(
                status="abstained",
                context=context,
                verification=verification,
                closure=closure,
                answer_source=answer_source,
                safe_abstention=True,
                reason_codes=reason_codes,
                repair_attempted=repair_attempted,
                unsupported_accepted_claims=unsupported_accepted_claims,
                citation_locator_valid=citation_locator_valid,
                material_claim_support_verified=material_claim_support_verified,
                canonical_claims=(),
                citations=citations,
                semantic_review=semantic_review,
                dropped_claim_ids=dropped_claim_ids,
                dropped_claim_count=dropped_claim_count,
                omitted_model_explanation_claim_ids=omitted_model_explanation_claim_ids,
            )
        return _failure(
            "VERIFIED_CLAIM_SPINE_NO_VERIFIED_CLAIMS",
            "accepted non-abstention verification contained no verified claims",
        )
    status = (
        "verified_partial"
        if _is_partial_answer(verification, closure)
        or omitted_model_explanation_claim_ids
        else "verified_full"
    )
    return _spine_result(
        status=status,
        context=context,
        verification=verification,
        closure=closure,
        answer_source=answer_source,
        safe_abstention=False,
        reason_codes=reason_codes,
        repair_attempted=repair_attempted,
        unsupported_accepted_claims=unsupported_accepted_claims,
        citation_locator_valid=citation_locator_valid,
        material_claim_support_verified=material_claim_support_verified,
        canonical_claims=claim_result.canonical_claims,
        citations=citations,
        semantic_review=semantic_review,
        dropped_claim_ids=dropped_claim_ids,
        dropped_claim_count=dropped_claim_count,
        omitted_model_explanation_claim_ids=omitted_model_explanation_claim_ids,
    )


def _semantic_contract_fingerprint_failure(
    context: CanonicalSemanticContext,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> CanonicalVerifiedClaimSpineResult | None:
    observed = str(verification.get("semantic_contract_fingerprint", "")).strip()
    semantic_contract = closure.get("semantic_contract", {})
    if isinstance(semantic_contract, Mapping):
        observed = observed or str(semantic_contract.get("fingerprint", "")).strip()
    if not observed:
        return _failure(
            "SEMANTIC_CONTRACT_IDENTITY_MISSING",
            "closure semantic contract fingerprint was not reported",
        )
    if observed != context.semantic_contract_fingerprint:
        return _failure(
            "SEMANTIC_CONTRACT_IDENTITY_MISMATCH",
            "closure semantic contract fingerprint did not match context",
        )
    return None


def _integrity_failure(
    *,
    unsupported_accepted_claims: int,
    citation_locator_valid: bool,
    material_claim_support_verified: bool,
) -> CanonicalVerifiedClaimSpineResult | None:
    if unsupported_accepted_claims > 0:
        return _failure(
            "VERIFIED_CLAIM_SPINE_UNSUPPORTED_ACCEPTED_CLAIM",
            "accepted verification reported unsupported accepted claims",
        )
    if not citation_locator_valid:
        return _failure(
            "VERIFIED_CLAIM_SPINE_INVALID_CITATION_LOCATOR",
            "accepted verification reported invalid citation locator",
        )
    if not material_claim_support_verified:
        return _failure(
            "VERIFIED_CLAIM_SPINE_MATERIAL_SUPPORT_UNVERIFIED",
            "accepted verification did not verify material claim support",
        )
    return None


def _canonical_claims(
    raw_claims: Sequence[Mapping[str, Any]],
    citations: tuple[Mapping[str, Any], ...],
) -> CanonicalClaimProjection | CanonicalVerifiedClaimSpineResult:
    citation_index_result = _citation_index(citations)
    if isinstance(citation_index_result, CanonicalVerifiedClaimSpineResult):
        return citation_index_result
    citation_index = citation_index_result

    claims: list[CanonicalVerifiedClaim] = []
    omitted_model_explanation_claim_ids: list[str] = []
    for raw_claim in raw_claims:
        claim_id = str(raw_claim.get("claim_id", "")).strip()
        if not claim_id:
            return _failure(
                "VERIFIED_CLAIM_SPINE_CLAIM_ID_MISSING",
                "accepted verified claim omitted a stable claim_id",
            )
        citation_ids_result = _claim_citation_ids(raw_claim, claim_id)
        if isinstance(citation_ids_result, CanonicalVerifiedClaimSpineResult):
            return citation_ids_result
        citation_ids = citation_ids_result
        support_ref_count_result = _claim_support_ref_count(raw_claim, citation_ids)
        if isinstance(support_ref_count_result, CanonicalVerifiedClaimSpineResult):
            return support_ref_count_result
        support_ref_count = support_ref_count_result
        if _is_supported_model_explanation(raw_claim, citation_ids, support_ref_count):
            return _failure(
                "VERIFIED_CLAIM_SPINE_MODEL_EXPLANATION_SUPPORT_INVALID",
                "accepted MODEL_EXPLANATION carried corpus support",
            )
        if not citation_ids:
            if _is_citation_free_model_explanation(
                raw_claim,
                citation_ids,
                support_ref_count,
            ):
                omitted_model_explanation_claim_ids.append(claim_id)
                continue
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted material claim had no authoritative citation_ids",
            )
        if support_ref_count != len(citation_ids):
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted claim support_ref_count did not match unique citation_ids",
            )
        mapped_citations = tuple(citation_index.get(citation_id) for citation_id in citation_ids)
        if any(citation is None for citation in mapped_citations):
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted claim referenced an unknown citation_id",
            )
        citations_for_claim = tuple(
            citation for citation in mapped_citations if citation is not None
        )
        if any(
            str(citation.get("claim_id", "")).strip() != claim_id
            for citation in citations_for_claim
        ):
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted claim referenced a citation owned by another claim",
            )
        support_evidence_refs = tuple(
            CanonicalSupportEvidenceRef(
                citation_id=str(citation["citation_id"]),
                evidence_id=str(citation["evidence_id"]),
                locator_id=str(citation["locator_id"]),
                source_identity=str(citation.get("source_identity", "")),
                source_id=str(citation.get("source_id", "")),
            )
            for citation in citations_for_claim
        )
        claims.append(
            CanonicalVerifiedClaim(
                claim_id=claim_id,
                surface_text=str(raw_claim.get("surface_text", "")),
                claim_role=str(raw_claim.get("claim_role", "")),
                claim_type=str(raw_claim.get("claim_type", "")),
                facet_ids=_string_tuple(raw_claim.get("facet_ids", ())),
                support_mode=str(raw_claim.get("support_mode", "")),
                support_ref_count=support_ref_count,
                source_identities=_string_tuple(raw_claim.get("source_identities", ())),
                citation_ids=citation_ids,
                citations=citations_for_claim,
                support_evidence_refs=support_evidence_refs,
                publication_eligible=True,
            )
        )
    return CanonicalClaimProjection(
        canonical_claims=tuple(claims),
        omitted_model_explanation_claim_ids=tuple(omitted_model_explanation_claim_ids),
    )


def _citation_index(
    citations: tuple[Mapping[str, Any], ...],
) -> dict[str, Mapping[str, Any]] | CanonicalVerifiedClaimSpineResult:
    index: dict[str, Mapping[str, Any]] = {}
    for citation in citations:
        citation_id = str(citation.get("citation_id", "")).strip()
        claim_id = str(citation.get("claim_id", "")).strip()
        evidence_id = str(citation.get("evidence_id", "")).strip()
        locator_id = str(citation.get("locator_id", "")).strip()
        if not citation_id or not claim_id or not evidence_id or not locator_id:
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted citation omitted citation_id, claim_id, evidence_id, or locator_id",
            )
        if citation_id in index:
            return _failure(
                "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
                "accepted verification contained duplicate citation_id entries",
            )
        index[citation_id] = citation
    return index


def _claim_citation_ids(
    raw_claim: Mapping[str, Any],
    claim_id: str,
) -> tuple[str, ...] | CanonicalVerifiedClaimSpineResult:
    raw_citation_ids = raw_claim.get("citation_ids")
    if isinstance(raw_citation_ids, (str, bytes)) or not isinstance(raw_citation_ids, Sequence):
        return _failure(
            "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
            f"accepted claim {claim_id} omitted public citation_ids",
        )
    if any(not isinstance(citation_id, str) for citation_id in raw_citation_ids):
        return _failure(
            "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
            f"accepted claim {claim_id} contained malformed citation_ids",
        )
    citation_ids = tuple(citation_id.strip() for citation_id in raw_citation_ids)
    if any(not citation_id for citation_id in citation_ids):
        return _failure(
            "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
            f"accepted claim {claim_id} contained an empty citation_id",
        )
    if len(set(citation_ids)) != len(citation_ids):
        return _failure(
            "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
            f"accepted claim {claim_id} contained duplicate citation_ids",
        )
    return citation_ids


def _claim_support_ref_count(
    raw_claim: Mapping[str, Any],
    citation_ids: tuple[str, ...],
) -> int | CanonicalVerifiedClaimSpineResult:
    value = raw_claim.get("support_ref_count", len(citation_ids))
    if isinstance(value, bool):
        return _failure(
            "VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID",
            "accepted claim support_ref_count was malformed",
        )
    try:
        count = int(value)
    except (TypeError, ValueError):
        return _failure(
            "VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID",
            "accepted claim support_ref_count was malformed",
        )
    if count > 0 and not citation_ids:
        return _failure(
            "VERIFIED_CLAIM_SPINE_CITATION_MAPPING_MISSING",
            "accepted claim had support_ref_count without citation_ids",
        )
    return count


def _is_citation_free_model_explanation(
    raw_claim: Mapping[str, Any],
    citation_ids: tuple[str, ...],
    support_ref_count: int,
) -> bool:
    if str(raw_claim.get("claim_type", "")).strip() != "MODEL_EXPLANATION":
        return False
    if support_ref_count != 0 or citation_ids:
        return False
    source_identities = _string_tuple(raw_claim.get("source_identities", ()))
    return not source_identities


def _is_supported_model_explanation(
    raw_claim: Mapping[str, Any],
    citation_ids: tuple[str, ...],
    support_ref_count: int,
) -> bool:
    if str(raw_claim.get("claim_type", "")).strip() != "MODEL_EXPLANATION":
        return False
    return support_ref_count > 0 or bool(citation_ids) or bool(
        _string_tuple(raw_claim.get("source_identities", ()))
    )


def _semantic_review(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> Mapping[str, Any]:
    closure_review = closure.get("semantic_review", {})
    if isinstance(closure_review, Mapping) and closure_review:
        return closure_review
    multi_evidence = verification.get("multi_evidence_verification", {})
    if isinstance(multi_evidence, Mapping):
        review = multi_evidence.get("semantic_review", {})
        if isinstance(review, Mapping):
            return review
    return {}


def _partial_drop_metadata(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> tuple[tuple[str, ...], int]:
    multi_evidence = verification.get("multi_evidence_verification", {})
    values: list[Mapping[str, Any]] = [closure]
    if isinstance(multi_evidence, Mapping):
        values.insert(0, multi_evidence)
    dropped_ids: tuple[str, ...] = ()
    dropped_count = 0
    for value in values:
        if "dropped_claim_ids" in value:
            dropped_ids = _string_tuple(value.get("dropped_claim_ids", ()))
        if "dropped_claim_count" in value:
            dropped_count = int(value.get("dropped_claim_count", 0))
    if dropped_ids and not dropped_count:
        dropped_count = len(dropped_ids)
    return dropped_ids, dropped_count


def _merged_dropped_metadata(
    dropped_claim_ids: tuple[str, ...],
    dropped_claim_count: int,
    omitted_model_explanation_claim_ids: tuple[str, ...],
) -> tuple[tuple[str, ...], int]:
    if not omitted_model_explanation_claim_ids:
        return dropped_claim_ids, dropped_claim_count
    merged_ids = _dedupe_ordered(
        (*dropped_claim_ids, *omitted_model_explanation_claim_ids)
    )
    if dropped_claim_ids:
        return merged_ids, len(merged_ids)
    return merged_ids, dropped_claim_count + len(omitted_model_explanation_claim_ids)


def _is_partial_answer(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> bool:
    multi_evidence = verification.get("multi_evidence_verification", {})
    partial_source = (
        str(verification.get("answer_source", ""))
        == "provider_verified_runtime_bound_partial_semantic_closure"
    )
    return (
        bool(closure.get("partial_answer", False))
        or (isinstance(multi_evidence, Mapping) and bool(multi_evidence.get("partial_answer")))
        or partial_source
    )


def _spine_result(
    *,
    status: VerifiedClaimSpineStatus,
    context: CanonicalSemanticContext,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    answer_source: str,
    safe_abstention: bool,
    reason_codes: tuple[str, ...],
    repair_attempted: bool,
    unsupported_accepted_claims: int,
    citation_locator_valid: bool,
    material_claim_support_verified: bool,
    canonical_claims: tuple[CanonicalVerifiedClaim, ...],
    citations: tuple[Mapping[str, Any], ...],
    semantic_review: Mapping[str, Any],
    dropped_claim_ids: tuple[str, ...],
    dropped_claim_count: int,
    omitted_model_explanation_claim_ids: tuple[str, ...] = (),
) -> CanonicalVerifiedClaimSpineResult:
    spine = CanonicalVerifiedClaimSpine(
        status=status,
        closure_question_en=context.closure_question_en,
        intent_class=context.intent_class,
        requested_answer_language=context.requested_answer_language,
        semantic_contract_schema=context.semantic_contract_schema,
        semantic_contract_fingerprint=context.semantic_contract_fingerprint,
        answer_source=answer_source,
        safe_abstention=safe_abstention,
        reason_codes=reason_codes,
        repair_attempted=repair_attempted,
        unsupported_accepted_claims=unsupported_accepted_claims,
        citation_locator_valid=citation_locator_valid,
        material_claim_support_verified=material_claim_support_verified,
        canonical_claims=canonical_claims,
        citations=citations,
        semantic_review=semantic_review,
        closure=closure,
        verification=verification,
        publication_eligible_claim_count=sum(
            1 for claim in canonical_claims if claim.publication_eligible
        ),
        dropped_claim_ids=dropped_claim_ids,
        dropped_claim_count=dropped_claim_count,
        telemetry={
            "closure_question_en": context.closure_question_en,
            "intent_class": context.intent_class,
            "semantic_contract_fingerprint": context.semantic_contract_fingerprint,
            "canonical_claim_count": len(canonical_claims),
            "publication_eligible_claim_count": sum(
                1 for claim in canonical_claims if claim.publication_eligible
            ),
            "track2_citation_free_model_explanation_omitted_count": len(
                omitted_model_explanation_claim_ids
            ),
            "track2_citation_free_model_explanation_omitted_claim_ids": (
                omitted_model_explanation_claim_ids
            ),
        },
    )
    return CanonicalVerifiedClaimSpineResult(status=status, spine=spine)


def _mapping_items(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence")
    items: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} item must be a mapping")
        items.append(item)
    return tuple(items)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        return (str(value),) if str(value) else ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if str(item))


def _dedupe_ordered(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _failure(code: str, detail: str) -> CanonicalVerifiedClaimSpineResult:
    return CanonicalVerifiedClaimSpineResult(
        status="failed",
        failure_code=code,
        failure_detail=detail,
    )
