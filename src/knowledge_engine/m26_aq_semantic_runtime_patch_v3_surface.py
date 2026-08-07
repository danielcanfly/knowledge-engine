from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from . import m26_aq_semantic_runtime_patch_v2 as v2_patch
from . import m26_aq_semantic_runtime_patch_v3 as v3_patch
from . import m26_aq_semantic_runtime_patch_v3_lifecycle as lifecycle_patch

_ORIGINAL_SOFTEN_UNSUPPORTED_MODALITY = lifecycle_patch._soften_unsupported_modality
_ORIGINAL_REPAIR_GUIDANCE = lifecycle_patch._repair_guidance
_ORIGINAL_VERIFICATION_CANDIDATE = lifecycle_patch._verification_candidate_bounded
_ORIGINAL_DIRECT_FACET_PARTITION = v2_patch._direct_facet_partition_candidate
_ORIGINAL_QUESTION_CONTRACT: Any | None = None
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MODALITY_REPLACEMENTS = {
    "always": "typically",
    "cannot": "may not",
    "guarantee": "support",
    "guarantees": "supports",
    "must": "should",
    "never": "not necessarily",
    "requires": "can involve",
}
_LEGACY_LIFECYCLE_FACETS = {
    "lifecycle_trust_envelope",
    "admission_policy",
    "durable_state_authority",
    "continued_execution",
    "verification_completion",
    "observability_reattachment",
    "persisted_progress",
    "verification_or_approval",
}
_NARROW_LIFECYCLE_SURFACES = {
    "admission_policy": "Admission policy decides whether the run may start.",
    "durable_state_authority": (
        "Persisted server-side state preserves durable run progress after a client disconnect."
    ),
    "continued_execution": (
        "Server-side execution can continue after a client disconnect while run state is preserved."
    ),
    "verification_completion": (
        "Completion verification checks the final result before it is accepted as complete."
    ),
    "observability_reattachment": (
        "Status and observability let the owner inspect or reattach to the continuing run."
    ),
}


def _normalize_text_unsupported_modality(
    text: str,
    *,
    allowed_terms: set[str],
    legacy: Any,
) -> str:
    """Monotonically weaken only hard-gate modality not licensed by question/support."""
    normalized = str(text)
    strengthening = set(
        getattr(
            legacy,
            "MODALITY_STRENGTHENING_TERMS",
            set(_MODALITY_REPLACEMENTS),
        )
    )
    remaining = legacy._meaningful_terms(normalized) & strengthening - allowed_terms
    for term in sorted(remaining, key=len, reverse=True):
        replacement = _MODALITY_REPLACEMENTS.get(term)
        if replacement is None:
            continue
        normalized = re.sub(
            rf"\b{re.escape(term)}\b",
            lambda match, value=replacement: lifecycle_patch._case_preserving_replacement(
                match,
                value,
            ),
            normalized,
            flags=re.I,
        )
    return " ".join(normalized.split())


def _soften_complete_unsupported_modality(
    answer: str,
    *,
    question: str,
    used_items: Any,
    legacy: Any,
) -> str:
    """Complete the existing monotonic modality softening for every hard-gate term."""
    softened = _ORIGINAL_SOFTEN_UNSUPPORTED_MODALITY(
        answer,
        question=question,
        used_items=used_items,
        legacy=legacy,
    )
    allowed = legacy._meaningful_terms(question) | legacy._meaningful_terms(
        lifecycle_patch._support_text(used_items)
    )
    return _normalize_text_unsupported_modality(
        softened,
        allowed_terms=allowed,
        legacy=legacy,
    )


def _surface_repair_guidance(code: str) -> str:
    value = str(code)
    if value == "M26-PA7-ME-033":
        return (
            "Do not introduce numeric values that are absent from the question and exact "
            "supporting evidence; remove the unsupported numeric detail instead."
        )
    if value == "M26-PA7-ME-034":
        return (
            "Do not strengthen modality beyond evidence. Avoid always, cannot, guarantee, "
            "guarantees, must, never, and requires unless the question or exact evidence "
            "explicitly supports that term."
        )
    return _ORIGINAL_REPAIR_GUIDANCE(value)


def _lifecycle_contract_facets(question: str) -> set[str] | None:
    """Return the narrow legacy facets actually requested, or None when not lifecycle."""
    if lifecycle_patch._explicit_full_lifecycle_with_span(question):
        return None
    q = " ".join(str(question).casefold().split())
    lifecycle_context = any(
        marker in q
        for marker in (
            "client disconnect",
            "disconnect",
            "persisted",
            "persist",
            "durable",
            "recover",
            "resume",
            "reattach",
            "long-running",
        )
    )
    if not lifecycle_context:
        return None

    requested: set[str] = set()
    if any(
        marker in q
        for marker in (
            "disconnect",
            "persisted",
            "persist",
            "durable",
            "recover",
            "resume",
        )
    ):
        requested.add("durable_state_authority")
    if any(
        marker in q
        for marker in (
            "verify",
            "verification",
            "verified",
            "completion",
            "complete",
            "correct",
            "success",
            "acceptance",
        )
    ):
        requested.add("verification_completion")
    if any(
        marker in q
        for marker in (
            "admission",
            "intake",
            "before execution",
            "request boundary",
        )
    ):
        requested.add("admission_policy")
    if any(
        marker in q
        for marker in (
            "observability",
            "reattach",
            "status",
            "headless",
            "inspect",
            "inspection",
        )
    ):
        requested.add("observability_reattachment")
    if any(
        marker in q
        for marker in (
            "keeps working",
            "keep working",
            "keeps running",
            "keep running",
            "continues running",
            "continue running",
            "continued execution",
        )
    ):
        requested.add("continued_execution")
    return requested


def _question_has_ordering_semantics(question: str) -> bool:
    q = str(question).casefold()
    return any(
        marker in q
        for marker in (
            "precedes",
            "precede",
            "ordering",
            "sequence",
            "comes before",
            "comes after",
        )
    )


def _product_question_contract(*, question: str, intent_class: str) -> dict[str, Any]:
    """Align only narrow lifecycle questions with the product-first verifier contract."""
    if _ORIGINAL_QUESTION_CONTRACT is None:
        raise RuntimeError("AQ product question contract installed without original contract")
    contract = copy.deepcopy(
        _ORIGINAL_QUESTION_CONTRACT(
            question=question,
            intent_class=intent_class,
        )
    )
    if intent_class != "direct_grounded_knowledge":
        return contract

    requested_lifecycle = _lifecycle_contract_facets(question)
    if requested_lifecycle is None:
        return contract

    facets = contract.get("required_facets", [])
    if not isinstance(facets, list):
        return contract

    facets = [
        facet
        for facet in facets
        if not isinstance(facet, Mapping)
        or str(facet.get("facet_id", "")) not in _LEGACY_LIFECYCLE_FACETS
        or str(facet.get("facet_id", "")) in requested_lifecycle
    ]
    if not _question_has_ordering_semantics(question):
        facets = [
            facet
            for facet in facets
            if not isinstance(facet, Mapping)
            or str(facet.get("facet_id", "")) != "ordering_boundary"
        ]
    contract["required_facets"] = facets
    return contract


def _direct_facet_partition_candidate_any(
    *,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Any,
    requirements: Any,
) -> dict[str, Any] | None:
    """Extend 1-3 facet partition only for narrow lifecycle questions."""
    candidate = _ORIGINAL_DIRECT_FACET_PARTITION(
        legacy=legacy,
        answer=answer,
        question=question,
        intent_class=intent_class,
        used_items=used_items,
        requirements=requirements,
    )
    if candidate is not None:
        return candidate
    if intent_class != "direct_grounded_knowledge" or not used_items:
        return None
    if _lifecycle_contract_facets(question) is None:
        return None

    required_facets = legacy._question_contract(
        question=question,
        intent_class=intent_class,
    ).get("required_facets", [])
    if not isinstance(required_facets, list) or not 1 <= len(required_facets) <= 3:
        return None

    claims: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for index, facet in enumerate(required_facets, start=1):
        if not isinstance(facet, Mapping):
            return None
        facet_id = str(facet.get("facet_id", ""))
        if not facet_id:
            return None
        terms = v2_patch._facet_terms_from_contract(facet)
        item = v2_patch._best_repair_item_for_terms(legacy, used_items, terms)
        if item is None:
            return None
        ref = v2_patch._support_ref_for_terms(legacy, item, terms)
        if ref is None:
            return None
        selected_ids.append(str(item.get("evidence_id", "")))
        surface = _NARROW_LIFECYCLE_SURFACES.get(facet_id)
        if surface is None:
            surface = v2_patch._direct_facet_surface_text(
                facet_id=facet_id,
                answer=answer,
                requirements=requirements,
            )
        claims.append(
            {
                "claim_id": f"claim_{index}",
                "claim_role": "direct",
                "surface_text": surface,
                "facet_ids": [facet_id],
                "support_mode": "runtime_bound_exact_facet_partition",
                "support_refs": [ref],
            }
        )
    if not claims:
        return None
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": None,
        "selected_evidence_ids": list(dict.fromkeys(selected_ids)),
        "answer_text": v2_patch._anchored_partition_answer(answer, claims),
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _claim_support_text(claim: Mapping[str, Any]) -> str:
    refs = claim.get("support_refs", [])
    if not isinstance(refs, list):
        return ""
    return " ".join(
        str(ref.get("exact_quote", ref.get("exact_support_snippet", "")))
        for ref in refs
        if isinstance(ref, Mapping)
    )


def _candidate_support_text(candidate: Mapping[str, Any]) -> str:
    claims = candidate.get("claims", [])
    if not isinstance(claims, list):
        return ""
    return " ".join(
        _claim_support_text(claim)
        for claim in claims
        if isinstance(claim, Mapping)
    )


def _normalize_candidate_unsupported_modality(
    candidate: Mapping[str, Any],
    *,
    question: str,
    natural_answer: str,
) -> tuple[dict[str, Any], str]:
    """Normalize claim surfaces at the final boundary immediately before hard verification."""
    from . import m26_pa7_arbitrary_query_runtime as legacy

    normalized = copy.deepcopy(dict(candidate))
    question_terms = legacy._meaningful_terms(question)
    claims = normalized.get("claims", [])
    changed = False
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            allowed = question_terms | legacy._meaningful_terms(_claim_support_text(claim))
            surface = str(claim.get("surface_text", ""))
            cleaned = _normalize_text_unsupported_modality(
                surface,
                allowed_terms=allowed,
                legacy=legacy,
            )
            if cleaned != surface:
                claim["surface_text"] = cleaned
                changed = True
    if changed:
        lifecycle_patch._rebuild_anchored_answer(normalized)

    natural_allowed = question_terms | legacy._meaningful_terms(
        _candidate_support_text(normalized)
    )
    cleaned_natural = _normalize_text_unsupported_modality(
        natural_answer,
        allowed_terms=natural_allowed,
        legacy=legacy,
    )
    return normalized, cleaned_natural


def _candidate_allowed_numbers(
    candidate: Mapping[str, Any],
    *,
    question: str,
) -> set[str]:
    allowed = set(_NUMBER_RE.findall(str(question)))
    claims = candidate.get("claims", [])
    if not isinstance(claims, list):
        return allowed
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        refs = claim.get("support_refs", [])
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, Mapping):
                continue
            allowed.update(
                _NUMBER_RE.findall(
                    str(ref.get("exact_quote", ref.get("exact_support_snippet", "")))
                )
            )
    return allowed


def _drop_unsupported_number_sentences(text: str, *, allowed_numbers: set[str]) -> str:
    """Remove only whole sentences carrying an unsupported numeric assertion."""
    value = " ".join(str(text).split())
    if not value:
        return value
    sentences = [item.strip() for item in _SENTENCE_SPLIT_RE.split(value) if item.strip()]
    if not sentences:
        return value
    kept = [
        sentence
        for sentence in sentences
        if set(_NUMBER_RE.findall(sentence)).issubset(allowed_numbers)
    ]
    if not kept:
        return value
    return " ".join(kept)


def _normalize_candidate_unsupported_numbers(
    candidate: Mapping[str, Any],
    *,
    question: str,
    natural_answer: str,
) -> tuple[dict[str, Any], str]:
    """Monotonically drop unsupported-number sentences while preserving licensed numbers."""
    normalized = copy.deepcopy(dict(candidate))
    allowed = _candidate_allowed_numbers(normalized, question=question)
    claims = normalized.get("claims", [])
    changed = False
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            surface = str(claim.get("surface_text", ""))
            cleaned = _drop_unsupported_number_sentences(
                surface,
                allowed_numbers=allowed,
            )
            if cleaned != surface:
                claim["surface_text"] = cleaned
                changed = True
    if changed:
        lifecycle_patch._rebuild_anchored_answer(normalized)
    cleaned_natural = _drop_unsupported_number_sentences(
        natural_answer,
        allowed_numbers=allowed,
    )
    return normalized, cleaned_natural


def _verification_candidate_with_surface_guard(**kwargs: Any) -> dict[str, Any]:
    candidate = _ORIGINAL_VERIFICATION_CANDIDATE(**kwargs)
    natural_answer = lifecycle_patch._VERIFIED_NATURAL_SURFACE.get() or str(
        kwargs.get("answer", "")
    )
    candidate, natural_answer = _normalize_candidate_unsupported_modality(
        candidate,
        question=str(kwargs.get("question", "")),
        natural_answer=natural_answer,
    )
    candidate, natural_answer = _normalize_candidate_unsupported_numbers(
        candidate,
        question=str(kwargs.get("question", "")),
        natural_answer=natural_answer,
    )
    lifecycle_patch._VERIFIED_NATURAL_SURFACE.set(natural_answer)
    return candidate


def install() -> None:
    """Install bounded product contract alignment without weakening hard verifier gates."""
    global _ORIGINAL_QUESTION_CONTRACT

    from . import m26_pa7_arbitrary_query_runtime as legacy

    lifecycle_patch._soften_unsupported_modality = _soften_complete_unsupported_modality
    lifecycle_patch._repair_guidance = _surface_repair_guidance
    lifecycle_patch._verification_candidate_bounded = _verification_candidate_with_surface_guard
    v3_patch._verification_candidate = _verification_candidate_with_surface_guard

    if not hasattr(legacy, "_m26_aq_product_original_question_contract"):
        legacy._m26_aq_product_original_question_contract = legacy._question_contract
    _ORIGINAL_QUESTION_CONTRACT = legacy._m26_aq_product_original_question_contract
    legacy._question_contract = _product_question_contract

    if not hasattr(v2_patch, "_m26_aq_product_original_direct_facet_partition"):
        v2_patch._m26_aq_product_original_direct_facet_partition = (
            _ORIGINAL_DIRECT_FACET_PARTITION
        )
    v2_patch._direct_facet_partition_candidate = _direct_facet_partition_candidate_any
