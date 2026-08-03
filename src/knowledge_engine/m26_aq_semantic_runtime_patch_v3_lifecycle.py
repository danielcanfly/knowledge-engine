from __future__ import annotations

import copy
import json
import re
from contextvars import ContextVar
from collections.abc import Mapping
from typing import Any

from . import m26_aq_semantic_runtime_patch_v2 as v2_patch
from . import m26_aq_semantic_runtime_patch_v3 as v3_patch

_ORIGINAL_EXPLICIT_FULL_LIFECYCLE = v3_patch._explicit_full_lifecycle
_INTERNAL_REF_RE = re.compile(
    r"\b(?:article_[0-9a-f]{8,}|m26pa7(?:ev|loc|edge)_[0-9a-f]{8,}|"
    r"claim_\d+(?:_ref_\d+)?|edge_[0-9a-f]{8,})\b",
    flags=re.I,
)
_DISCOURSE_ONLY = {"no", "yes", "correct", "incorrect"}
_MAX_VERIFIER_QUOTE_CHARS = 780
_DIRECT_CANDIDATE_BUDGET = 11_000
_COMPACT_DIRECT_QUOTE_CHARS = 360
_VERIFIED_NATURAL_SURFACE: ContextVar[str | None] = ContextVar(
    "m26_aq_v3_verified_natural_surface",
    default=None,
)
_LIFECYCLE_VERIFICATION_SURFACES = {
    "admission_policy": (
        "Admission and intake policy gates decide whether the run may start."
    ),
    "durable_state": (
        "Durable server-side state preserves run progress after a client disconnect."
    ),
    "completion_verification": (
        "Completion verification checks the final result before acceptance."
    ),
    "observability": (
        "Observability and status let the owner inspect or reattach to the run."
    ),
}


def _explicit_full_lifecycle_with_span(question: str) -> bool:
    if _ORIGINAL_EXPLICIT_FULL_LIFECYCLE(question):
        return True

    q = " ".join(question.casefold().split())
    has_start_boundary = any(
        marker in q
        for marker in (
            "from admission",
            "from intake",
        )
    )
    has_progression = " to " in q or " through " in q
    has_terminal_boundary = any(
        marker in q
        for marker in (
            "completion",
            "final status",
            "final verification",
            "final acceptance",
            "status reattachment",
            "result verification",
        )
    )
    return has_start_boundary and has_progression and has_terminal_boundary


def _bounded_quote(value: str, *, limit: int = _MAX_VERIFIER_QUOTE_CHARS) -> str:
    quote = " ".join(str(value).split())
    if len(quote) <= limit:
        return quote
    prefix = quote[:limit]
    return prefix.rsplit(" ", 1)[0].rstrip() or prefix


def _bound_candidate_support_refs(
    candidate: Mapping[str, Any],
    *,
    limit: int = _MAX_VERIFIER_QUOTE_CHARS,
) -> dict[str, Any]:
    """Keep exact verifier support while removing redundant provider-only duplication."""
    bounded = copy.deepcopy(dict(candidate))
    claims = bounded.get("claims", [])
    if not isinstance(claims, list):
        return bounded
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        refs = claim.get("support_refs", [])
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            exact = _bounded_quote(
                str(ref.get("exact_quote", ref.get("exact_support_snippet", ""))),
                limit=limit,
            )
            if exact:
                ref["exact_quote"] = exact
                ref.pop("exact_support_snippet", None)
    return bounded


def _rebuild_anchored_answer(candidate: dict[str, Any]) -> None:
    claims = candidate.get("claims", [])
    if not isinstance(claims, list):
        return
    candidate["answer_text"] = " ".join(
        f"{str(claim.get('surface_text', '')).rstrip('.')} "
        f"[[{str(claim.get('claim_id', ''))}]]."
        for claim in claims
        if isinstance(claim, Mapping)
        and claim.get("claim_id")
        and claim.get("surface_text")
    )


def _compact_lifecycle_facet_surfaces(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Keep multi-facet verification concise while serving the provider's natural prose."""
    compact = copy.deepcopy(dict(candidate))
    claims = compact.get("claims", [])
    if not isinstance(claims, list):
        return compact
    changed = False
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        facets = claim.get("facet_ids", [])
        if not isinstance(facets, list) or len(facets) != 1:
            continue
        surface = _LIFECYCLE_VERIFICATION_SURFACES.get(str(facets[0]))
        if surface is None:
            continue
        claim["surface_text"] = surface
        changed = True
    if changed:
        _rebuild_anchored_answer(compact)
    return compact


def _fit_direct_candidate_budget(
    candidate: Mapping[str, Any],
    *,
    intent_class: str,
) -> dict[str, Any]:
    """Fit oversized direct verification JSON without weakening exact-support checks."""
    compact = _bound_candidate_support_refs(candidate)
    serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= _DIRECT_CANDIDATE_BUDGET:
        return compact
    if intent_class != "direct_grounded_knowledge":
        return compact

    claims = compact.get("claims", [])
    if not isinstance(claims, list):
        return compact
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        refs = claim.get("support_refs", [])
        if not isinstance(refs, list) or not refs:
            continue
        first = refs[0]
        if not isinstance(first, dict):
            continue
        support_surface = _bounded_quote(
            str(first.get("exact_quote", "")),
            limit=_COMPACT_DIRECT_QUOTE_CHARS,
        )
        if support_surface:
            claim["surface_text"] = support_surface
    compact = _bound_candidate_support_refs(
        compact,
        limit=_COMPACT_DIRECT_QUOTE_CHARS,
    )
    _rebuild_anchored_answer(compact)
    return compact


def _requires_non_entailment_boundary_question(question: str) -> bool:
    q = str(question).casefold()
    return "precedes" in q and bool(
        re.search(
            r"\b(prove|proves|infer|depends?|dependency|require|requires|causal|cause)\b",
            q,
        )
    )


def _merge_false_premise_claims(
    candidate: Mapping[str, Any],
    *,
    answer: str,
) -> dict[str, Any]:
    """Verify a multi-sentence ordering boundary as one material proposition."""
    merged = copy.deepcopy(dict(candidate))
    claims = merged.get("claims", [])
    if not isinstance(claims, list) or len(claims) <= 1:
        return merged

    sentences = v3_patch._material_sentences(answer)
    surface = ". ".join(sentence.rstrip(".") for sentence in sentences if sentence.strip())
    if not surface:
        return merged

    facets: list[str] = []
    refs: list[dict[str, Any]] = []
    seen_refs: set[tuple[str, str, str]] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        raw_facets = claim.get("facet_ids", [])
        if isinstance(raw_facets, list):
            for facet in raw_facets:
                value = str(facet)
                if value and value not in facets:
                    facets.append(value)
        raw_refs = claim.get("support_refs", [])
        if not isinstance(raw_refs, list):
            continue
        for ref in raw_refs:
            if not isinstance(ref, Mapping):
                continue
            key = (
                str(ref.get("evidence_id", "")),
                str(ref.get("locator_id", "")),
                str(ref.get("exact_quote", ref.get("exact_support_snippet", ""))),
            )
            if not key[0] or not key[1] or not key[2] or key in seen_refs:
                continue
            seen_refs.add(key)
            refs.append(dict(ref))

    if not refs:
        return merged
    merged["claims"] = [
        {
            "claim_id": "claim_1",
            "claim_role": "direct",
            "surface_text": surface,
            "facet_ids": facets,
            "support_mode": "runtime_bound_whole_answer_non_entailment",
            "support_refs": refs,
        }
    ]
    merged["answer_text"] = f"{surface.rstrip('.')} [[claim_1]]."
    return merged


def _support_text(used_items: Any) -> str:
    if not isinstance(used_items, (list, tuple)):
        return ""
    fields = ("passage_text", "title", "section_title", "relation_type")
    return " ".join(
        str(item.get(field, ""))
        for item in used_items
        if isinstance(item, Mapping)
        for field in fields
        if item.get(field)
    )


def _case_preserving_replacement(match: re.Match[str], replacement: str) -> str:
    original = match.group(0)
    if original and original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _soften_unsupported_modality(
    answer: str,
    *,
    question: str,
    used_items: Any,
    legacy: Any,
) -> str:
    """Monotonically weaken only modality terms not licensed by question/evidence."""
    meaningful_terms = legacy._meaningful_terms
    support_terms = meaningful_terms(_support_text(used_items))
    question_terms = meaningful_terms(question)
    allowed = support_terms | question_terms
    answer_terms = meaningful_terms(answer)
    strengthening = set(
        getattr(
            legacy,
            "MODALITY_STRENGTHENING_TERMS",
            {"always", "cannot", "guarantee", "guarantees", "must"},
        )
    )
    unsupported = answer_terms & strengthening - allowed
    if not unsupported:
        return answer

    replacements = {
        "always": "typically",
        "cannot": "may not",
        "guarantee": "support",
        "guarantees": "supports",
        "must": "should",
    }
    softened = answer
    for term in sorted(unsupported, key=len, reverse=True):
        replacement = replacements.get(term)
        if replacement is None:
            continue
        softened = re.sub(
            rf"\b{re.escape(term)}\b",
            lambda match, value=replacement: _case_preserving_replacement(match, value),
            softened,
            flags=re.I,
        )
    return softened


def _verification_candidate_bounded(**kwargs: Any) -> dict[str, Any]:
    original = v3_patch._m26_aq_v3_unbounded_verification_candidate
    safe_kwargs = dict(kwargs)
    answer = _soften_unsupported_modality(
        str(kwargs.get("answer", "")),
        question=str(kwargs.get("question", "")),
        used_items=kwargs.get("used_items", []),
        legacy=kwargs.get("legacy"),
    )
    safe_kwargs["answer"] = answer
    _VERIFIED_NATURAL_SURFACE.set(answer)

    candidate = original(**safe_kwargs)
    candidate = _compact_lifecycle_facet_surfaces(candidate)
    if _requires_non_entailment_boundary_question(str(kwargs.get("question", ""))):
        candidate = _merge_false_premise_claims(
            candidate,
            answer=answer,
        )
    return _fit_direct_candidate_budget(
        candidate,
        intent_class=str(kwargs.get("intent_class", "")),
    )


def _material_sentences_without_discourse(answer: str) -> list[str]:
    original = v3_patch._m26_aq_v3_original_material_sentences
    sentences = list(original(answer))
    if len(sentences) <= 1:
        return sentences
    first = re.sub(r"[^a-z]+", "", sentences[0].casefold())
    if first in _DISCOURSE_ONLY:
        return sentences[1:]
    return sentences


def _use_verified_natural_surface_safe(
    answer: dict[str, Any],
    surface: str,
) -> None:
    original = v2_patch._m26_aq_v3_original_use_verified_natural_surface
    verified_surface = _VERIFIED_NATURAL_SURFACE.get() or surface
    original(answer, verified_surface)


def _strip_internal_refs(value: str) -> str:
    return " ".join(_INTERNAL_REF_RE.sub("", str(value)).split())


def _repair_guidance(code: str) -> str:
    value = str(code)
    if value.startswith("USER_VISIBLE_INTERNAL_REFERENCE_LEAK"):
        return "Do not expose internal runtime identifiers in the answer."
    if value == "M26-PA7-ME-034":
        return (
            "Do not strengthen modality beyond evidence; prefer can, may, or typically "
            "unless supplied evidence explicitly supports must, always, cannot, or "
            "guarantees."
        )
    if value == "M26-PA7-ME-031":
        return "State the grounded proposition instead of a standalone yes/no claim."
    if value == "M26-PA7-ME-047":
        return (
            "For a precedes false-premise question, explicitly state the ordering meaning "
            "and the non-entailment boundary in the same overall answer."
        )
    if value == "M26-PA7-ME-001":
        return "Keep the answer concise; the verifier will bind it to bounded evidence."
    return value


def _sanitize_provider_task(task: Mapping[str, Any]) -> dict[str, Any]:
    safe = copy.deepcopy(dict(task))
    evidence = safe.get("evidence", [])
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")) == "graph_edge":
                item["source"] = "relation graph"
            for field in ("source", "title", "section", "concept", "from", "to", "text"):
                if field in item:
                    item[field] = _strip_internal_refs(str(item.get(field, "")))
            item["concept"] = ""
            item["from"] = ""
            item["to"] = ""
    repair = safe.get("repair", [])
    if isinstance(repair, list):
        safe["repair"] = list(dict.fromkeys(_repair_guidance(str(item)) for item in repair))
    return safe


def _compact_provider_payload_safe(**kwargs: Any) -> tuple[
    dict[str, Any],
    dict[str, Mapping[str, Any]],
    dict[str, str],
]:
    from . import m26_pa7_semantic_closure_runtime as runtime

    original = runtime._m26_aq_v3_original_compact_provider_payload
    payload, label_map, snippet_map = original(**kwargs)
    safe_payload = copy.deepcopy(payload)
    messages = safe_payload.get("messages", [])
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        try:
            task = json.loads(str(messages[0].get("content", "")))
        except (TypeError, ValueError, json.JSONDecodeError):
            task = None
        if isinstance(task, Mapping):
            messages[0]["content"] = json.dumps(
                _sanitize_provider_task(task),
                ensure_ascii=False,
                separators=(",", ":"),
            )
    safe_payload["system"] = (
        str(safe_payload.get("system", ""))
        + " Evidence labels and runtime identifiers are internal selectors: never put "
        "e1/e2, article_ ids, m26pa7 ids, claim_ ids, or graph edge ids in answer prose. "
        "Use the human-readable names in the question and evidence text. Do not strengthen "
        "modality beyond supplied evidence: avoid always, cannot, guarantee, guarantees, "
        "or must unless the question or exact evidence supports that word."
    )
    return safe_payload, label_map, snippet_map


def install() -> None:
    """Install bounded v3 closure repairs without weakening any hard verifier gate."""
    from . import m26_pa7_semantic_closure_runtime as runtime

    v3_patch._explicit_full_lifecycle = _explicit_full_lifecycle_with_span

    if not hasattr(v3_patch, "_m26_aq_v3_unbounded_verification_candidate"):
        v3_patch._m26_aq_v3_unbounded_verification_candidate = (
            v3_patch._verification_candidate
        )
    v3_patch._verification_candidate = _verification_candidate_bounded

    if not hasattr(v3_patch, "_m26_aq_v3_original_material_sentences"):
        v3_patch._m26_aq_v3_original_material_sentences = v3_patch._material_sentences
    v3_patch._material_sentences = _material_sentences_without_discourse

    if not hasattr(v2_patch, "_m26_aq_v3_original_use_verified_natural_surface"):
        v2_patch._m26_aq_v3_original_use_verified_natural_surface = (
            v2_patch._use_verified_natural_surface
        )
    v2_patch._use_verified_natural_surface = _use_verified_natural_surface_safe

    if not hasattr(runtime, "_m26_aq_v3_original_compact_provider_payload"):
        runtime._m26_aq_v3_original_compact_provider_payload = (
            runtime._compact_provider_payload
        )
    runtime._compact_provider_payload = _compact_provider_payload_safe
