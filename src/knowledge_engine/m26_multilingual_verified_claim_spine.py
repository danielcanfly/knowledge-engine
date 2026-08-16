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
class CanonicalVerifiedClaim:
    claim_id: str
    surface_text: str
    claim_role: str
    claim_type: str
    support_refs: tuple[Mapping[str, Any], ...]
    citations: tuple[Mapping[str, Any], ...]
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
    try:
        citations = tuple(_mapping_items(verification.get("citations", ()), "citations"))
    except ValueError as exc:
        return _failure("VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID", str(exc))
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
            citations=citations,
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
        raw_claims = _mapping_items(verification.get("answer_claims", ()), "answer_claims")
    except ValueError as exc:
        return _failure("VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID", str(exc))
    claim_result = _canonical_claims(raw_claims, citations)
    if isinstance(claim_result, CanonicalVerifiedClaimSpineResult):
        return claim_result
    if not claim_result:
        return _failure(
            "VERIFIED_CLAIM_SPINE_NO_VERIFIED_CLAIMS",
            "accepted non-abstention verification contained no verified claims",
        )
    status = "verified_partial" if _is_partial_answer(verification, closure) else "verified_full"
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
        canonical_claims=claim_result,
        citations=citations,
        semantic_review=semantic_review,
        dropped_claim_ids=dropped_claim_ids,
        dropped_claim_count=dropped_claim_count,
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
) -> tuple[CanonicalVerifiedClaim, ...] | CanonicalVerifiedClaimSpineResult:
    claims: list[CanonicalVerifiedClaim] = []
    for raw_claim in raw_claims:
        claim_id = str(raw_claim.get("claim_id", "")).strip()
        if not claim_id:
            return _failure(
                "VERIFIED_CLAIM_SPINE_CLAIM_ID_MISSING",
                "accepted verified claim omitted a stable claim_id",
            )
        try:
            support_refs = tuple(
                _mapping_items(raw_claim.get("support_refs", ()), "claim support_refs")
            )
        except ValueError as exc:
            return _failure("VERIFIED_CLAIM_SPINE_VERIFICATION_SCHEMA_INVALID", str(exc))
        if not support_refs:
            return _failure(
                "VERIFIED_CLAIM_SPINE_SUPPORT_MAPPING_MISSING",
                "accepted verified claim omitted authoritative support_refs",
            )
        mapped_citations = _citations_for_support_refs(support_refs, citations)
        if not mapped_citations:
            return _failure(
                "VERIFIED_CLAIM_SPINE_SUPPORT_MAPPING_MISSING",
                "accepted verified claim support_refs did not map to accepted citations",
            )
        claims.append(
            CanonicalVerifiedClaim(
                claim_id=claim_id,
                surface_text=str(raw_claim.get("surface_text", "")),
                claim_role=str(raw_claim.get("claim_role", "")),
                claim_type=str(raw_claim.get("claim_type", "")),
                support_refs=support_refs,
                citations=mapped_citations,
                publication_eligible=True,
            )
        )
    return tuple(claims)


def _citations_for_support_refs(
    support_refs: tuple[Mapping[str, Any], ...],
    citations: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    support_keys = {
        (str(ref.get("evidence_id", "")), str(ref.get("locator_id", "")))
        for ref in support_refs
    }
    matched = [
        citation
        for citation in citations
        if (
            str(citation.get("evidence_id", "")),
            str(citation.get("locator_id", "")),
        )
        in support_keys
    ]
    return tuple(matched)


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


def _failure(code: str, detail: str) -> CanonicalVerifiedClaimSpineResult:
    return CanonicalVerifiedClaimSpineResult(
        status="failed",
        failure_code=code,
        failure_detail=detail,
    )
