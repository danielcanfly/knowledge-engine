from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from . import m26_aq_semantic_runtime_patch_v3 as v3_patch
from . import m26_aq_semantic_runtime_patch_v3_lifecycle as lifecycle_patch

_ORIGINAL_SOFTEN_UNSUPPORTED_MODALITY = lifecycle_patch._soften_unsupported_modality
_ORIGINAL_REPAIR_GUIDANCE = lifecycle_patch._repair_guidance
_ORIGINAL_VERIFICATION_CANDIDATE = lifecycle_patch._verification_candidate_bounded
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


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
    meaningful_terms = legacy._meaningful_terms
    support_terms = meaningful_terms(lifecycle_patch._support_text(used_items))
    question_terms = meaningful_terms(question)
    allowed = support_terms | question_terms
    strengthening = set(
        getattr(
            legacy,
            "MODALITY_STRENGTHENING_TERMS",
            {"always", "cannot", "guarantee", "guarantees", "must", "never", "requires"},
        )
    )
    remaining = meaningful_terms(softened) & strengthening - allowed
    replacements = {
        "never": "not necessarily",
        "requires": "can involve",
    }
    for term in sorted(remaining, key=len, reverse=True):
        replacement = replacements.get(term)
        if replacement is None:
            continue
        softened = re.sub(
            rf"\b{re.escape(term)}\b",
            lambda match, value=replacement: lifecycle_patch._case_preserving_replacement(
                match,
                value,
            ),
            softened,
            flags=re.I,
        )
    return softened


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
    candidate, natural_answer = _normalize_candidate_unsupported_numbers(
        candidate,
        question=str(kwargs.get("question", "")),
        natural_answer=natural_answer,
    )
    lifecycle_patch._VERIFIED_NATURAL_SURFACE.set(natural_answer)
    return candidate


def install() -> None:
    """Install bounded surface normalization without weakening any hard verifier gate."""
    lifecycle_patch._soften_unsupported_modality = _soften_complete_unsupported_modality
    lifecycle_patch._repair_guidance = _surface_repair_guidance
    lifecycle_patch._verification_candidate_bounded = _verification_candidate_with_surface_guard
    v3_patch._verification_candidate = _verification_candidate_with_surface_guard
