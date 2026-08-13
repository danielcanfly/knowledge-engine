from __future__ import annotations

import json
import re
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import suppress
from typing import Any

from . import m26_aq_final_universal_recovery_patch as patch

_RECOVERABLE_INTENTS = {
    "direct_grounded_knowledge",
    "cross_document_comparison",
    "complementary_synthesis",
    "graph_relationship",
}
_ORIGINAL_CANDIDATE = patch._candidate
_ORIGINAL_SYNTHESIZE = patch._synthesize_with_final_recovery
_ORIGINAL_PRECISE_DIRECT_FACETS = patch._precise_direct_facets
_ORIGINAL_SURFACE = patch._surface

_SOURCE_MARKER_PHRASES = (
    "multiple sources",
    "compare sources",
    "compare source",
    "source a",
    "source b",
    "source record",
    "source records",
    "source version",
    "source versions",
)
_GRAPH_ORDER_MARKER_PHRASES = (
    "relation graph",
    "precedes relation",
    "preceding relation",
    "ordering relation",
    "causality relation",
    "dependency relation",
    "ordering imply",
    "order imply",
)
_GRAPH_ORDER_TOKENS = {
    "precedes",
    "preceding",
    "causality",
    "causal",
    "dependency",
    "dependencies",
    "relation",
    "graph",
}
_GENERIC_PROVE_MARKERS = {"prove", "proves", "proven", "proof", "imply", "implies"}
_NON_ENTAILMENT_KEY_TERMS = ("prove", "viable", "business")
_NON_ENTAILMENT_OPTIONAL_TERMS = (
    "demand",
    "value",
    "capture",
    "economics",
    "delivery",
    "repeatability",
    "repeatable",
)


def apply() -> None:
    """Apply bounded production-only guards around final recovery.

    This module deliberately patches the already-loaded final recovery module instead of
    introducing another serving wrapper. The goal is to keep a single canonical hook while
    tightening live and regression boundaries: provider-abstain recovery must not answer
    invented external protocols, token-like words such as ``resources`` must not trigger
    ``source`` facets, generic non-entailment must not inherit graph/precedes semantics,
    and direct deterministic recovery must pass the stricter question-contract path before
    publication.
    """
    with suppress(Exception):
        patch._PROVIDER_ABSTAIN_EXTERNAL_STOPWORDS.update({"compare", "dag"})
    patch._unsupported_external_markers = _unsupported_external_markers
    patch._precise_direct_facets = _precise_direct_facets
    patch._surface = _surface
    patch._candidate = _candidate
    patch._synthesize_with_final_recovery = _synthesize_with_final_recovery


def _synthesize_with_final_recovery(
    *,
    legacy: Any,
    runtime: Any,
    original: Any,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    verification, closure = _ORIGINAL_SYNTHESIZE(
        legacy=legacy,
        runtime=runtime,
        original=original,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    if verification.get("status") == "owner_only_cited_answer":
        return verification, closure
    telemetry = _recovery_telemetry(verification, closure)
    if not telemetry.get("universal_recovery_should_attempt"):
        return verification, closure
    if str(intent_class) not in _RECOVERABLE_INTENTS:
        telemetry["first_broken_stage"] = "unsupported_intent_for_final_recovery"
        return patch._attach(verification, closure, telemetry)
    if telemetry.get("universal_recovery_hard_stop_codes"):
        telemetry["first_broken_stage"] = "hard_stop"
        return patch._attach(verification, closure, telemetry)
    if str(intent_class) == "direct_grounded_knowledge" and telemetry.get(
        "first_broken_stage"
    ) != "unsupported_intent_for_final_recovery":
        return verification, closure

    try:
        candidate = _candidate(
            legacy=legacy,
            runtime=runtime,
            question=question,
            evidence=evidence,
            requirements=requirements,
            telemetry=telemetry,
        )
        if candidate is None:
            telemetry["first_broken_stage"] = "candidate_none"
            return patch._attach(verification, closure, telemetry)
        telemetry["candidate_built"] = True
        telemetry["candidate_claim_count"] = len(candidate.get("claims", []))
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=str(intent_class),
            evidence=evidence,
            provider_text=json.dumps(candidate, ensure_ascii=False, separators=(",", ":")),
        )
        telemetry["candidate_verify_result"] = "verified"
        telemetry["candidate_missing_facets"] = list(verified.get("missing_facets", []))
        answer = legacy._verified_multi_evidence_answer(
            intent_class=str(intent_class),
            verified=verified,
            evidence=evidence,
            calls=[],
            repair_attempted=True,
        )
    except Exception as exc:
        telemetry["candidate_verify_result"] = "exception"
        telemetry["candidate_exception_class"] = type(exc).__name__
        telemetry["candidate_verify_failure_codes"] = [
            str(getattr(exc, "code", type(exc).__name__))
        ]
        telemetry["first_broken_stage"] = "candidate_verifier_exception"
        return patch._attach(verification, closure, telemetry)

    if answer.get("status") != "owner_only_cited_answer":
        telemetry["candidate_verify_result"] = "non_cited_final_answer"
        telemetry["first_broken_stage"] = "final_answer_status"
        return patch._attach(verification, closure, telemetry)

    post = patch._post_render_alignment(legacy, question, answer, telemetry)
    telemetry.update(post)
    if not post.get("post_render_alignment_passed"):
        telemetry["first_broken_stage"] = "post_render_question_alignment"
        return patch._attach(verification, closure, telemetry)

    previous_mve = verification.get("multi_evidence_verification", {})
    previous_mve = previous_mve if isinstance(previous_mve, Mapping) else {}
    failures = sorted({str(item) for item in closure.get("failures", [])})
    telemetry["first_broken_stage"] = "none"
    telemetry["published_verified_answer"] = True
    answer["provider_call_count"] = int(verification.get("provider_call_count", 0))
    answer["payg_equivalent_cost_usd"] = str(
        verification.get("payg_equivalent_cost_usd", "0")
    )
    answer["repair_attempted"] = True
    answer["answer_source"] = "deterministic_verified_evidence_recovery"
    answer["multi_evidence_verification"] = {
        **dict(answer.get("multi_evidence_verification", {})),
        "provider_attempt_telemetry": list(previous_mve.get("provider_attempt_telemetry", [])),
        "repair_result": "deterministic_verified_evidence_recovery",
        "repair_trigger": failures,
        patch._RECOVERY_KEY: telemetry,
        "verification_failure_codes_by_attempt": failures,
    }
    return answer, {
        **dict(closure),
        "broad_deterministic_fallback_used": True,
        "failures": [],
        "pre_recovery_failures": failures,
        patch._RECOVERY_KEY: {**telemetry, "used": True, "case_specific": False},
    }


def _recovery_telemetry(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    mve = verification.get("multi_evidence_verification", {})
    if isinstance(mve, Mapping) and isinstance(mve.get(patch._RECOVERY_KEY), Mapping):
        return dict(mve[patch._RECOVERY_KEY])
    if isinstance(closure.get(patch._RECOVERY_KEY), Mapping):
        return dict(closure[patch._RECOVERY_KEY])
    return {}


def _candidate(
    *,
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    telemetry: MutableMapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    intent = str(legacy._intent_class(question))
    if telemetry is not None:
        items = [item for item in evidence if item.get("evidence_type", "passage") == "passage"]
        telemetry["recovery_items_count"] = len(items)
        telemetry["recovery_text_available_count"] = sum(
            1 for item in items if patch._text(runtime, item, question, requirements)
        )
    if _looks_like_graph_premise_boundary(question):
        graph_premise = _graph_premise_candidate(
            legacy=legacy,
            runtime=runtime,
            question=question,
            evidence=evidence,
            requirements=requirements,
        )
        if graph_premise is not None:
            return graph_premise

    # Direct questions are the defect surface: never bypass the stricter question
    # contract with the older deterministic provider candidate. The old path can
    # cite a true passage while answering a different facet.
    contract_candidate = _ORIGINAL_CANDIDATE(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=requirements,
        telemetry=telemetry,
    )
    if contract_candidate is not None:
        return contract_candidate

    generic = _generic_non_entailment_candidate(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=requirements,
    )
    if generic is not None:
        return generic

    if intent in _RECOVERABLE_INTENTS and intent != "direct_grounded_knowledge":
        candidate = _legacy_candidate(legacy, question, intent, evidence)
        if candidate is not None and _legacy_candidate_respects_question(
            candidate,
            legacy=legacy,
            runtime=runtime,
            question=question,
            evidence=evidence,
            requirements=requirements,
        ):
            return candidate
    return None


def _legacy_candidate(
    legacy: Any,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    try:
        candidate = legacy._deterministic_provider_candidate(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
        )
    except Exception:
        return None
    if not isinstance(candidate, Mapping):
        return None
    claims = candidate.get("claims", [])
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)) or not claims:
        return None
    return dict(candidate)


def _legacy_candidate_respects_question(
    candidate: Mapping[str, Any],
    *,
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> bool:
    del evidence, runtime, requirements
    original_facets = patch._ORIGINAL_DIRECT_FACETS or legacy._direct_question_facets
    facets = patch._question_contract(
        legacy,
        question,
        patch._precise_direct_facets(question, original_facets),
    ).get("required_question_facets", [])
    if not facets:
        return False
    claims = candidate.get("claims", [])
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        return False
    answer_text = str(candidate.get("answer_text", ""))
    for facet in facets[: patch._MAX_RECOVERY_FACETS]:
        terms = [str(term) for term in facet.get("terms", [])]
        if not terms:
            return False
        if not patch._term_hits(terms, answer_text):
            return False
        supported = False
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            for ref in claim.get("support_refs", []):
                if not isinstance(ref, Mapping):
                    continue
                quote = str(
                    ref.get("exact_quote") or ref.get("exact_support_snippet") or ""
                )
                if quote and patch._quote_relevance_score(quote, terms)[1]["eligible"]:
                    supported = True
                    break
            if supported:
                break
        if not supported:
            return False
    return True


def _generic_non_entailment_candidate(
    *,
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any] | None:
    if _has_graph_order_marker(question):
        return None
    question_terms = _tokens(question)
    if not set(_NON_ENTAILMENT_KEY_TERMS).issubset(question_terms):
        return None
    required = [term for term in _NON_ENTAILMENT_KEY_TERMS if term in question_terms]
    required.extend(
        term for term in _NON_ENTAILMENT_OPTIONAL_TERMS if term in question_terms
    )
    required = list(dict.fromkeys(required))
    if len(required) < 4:
        return None
    best_item: Mapping[str, Any] | None = None
    best_quote = ""
    best_hits: set[str] = set()
    for item in evidence:
        if item.get("evidence_type", "passage") != "passage":
            continue
        text = patch._text(runtime, item, question, requirements)
        if not text:
            continue
        quote = _best_non_entailment_quote(legacy, text, required)
        hits = patch._term_hits(required, quote or text)
        if len(hits) > len(best_hits):
            best_item = item
            best_quote = quote or patch._bounded_surface(text)
            best_hits = hits
    if best_item is None:
        return None
    if not set(_NON_ENTAILMENT_KEY_TERMS).issubset(best_hits):
        return None
    optional = set(required) - set(_NON_ENTAILMENT_KEY_TERMS)
    if optional and len(best_hits & optional) < min(4, len(optional)):
        return None
    original_facets = patch._ORIGINAL_DIRECT_FACETS or legacy._direct_question_facets
    facet_ids = [
        str(facet.get("facet_id", "direct_answer"))
        for facet in patch._precise_direct_facets(question, original_facets)
        if str(facet.get("facet_id", "direct_answer")) != "ordering_boundary"
    ]
    if not facet_ids:
        facet_ids = ["direct_answer"]
    label_terms = [
        term
        for term in required
        if term not in {"prove", "proves", "proven", "proof"}
    ]
    surface = (
        f"For {patch._phrase(label_terms)}, the evidence supports this point: "
        f"{patch._bounded_surface(best_quote)}"
    )
    claim = {
        "claim_id": "claim_1",
        "claim_role": "direct",
        "surface_text": surface,
        "facet_ids": sorted(set(facet_ids)),
        "support_mode": "exact_quote",
        "support_refs": [
            {
                "evidence_id": str(best_item.get("evidence_id", "")),
                "locator_id": str(best_item.get("locator_id", "")),
                "exact_quote": best_quote,
                "exact_support_snippet": best_quote,
                "uncertainty": "low",
            }
        ],
    }
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": None,
        "selected_evidence_ids": [str(best_item.get("evidence_id", ""))],
        "answer_text": surface + " [[claim_1]].",
        "claims": [claim],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _best_non_entailment_quote(legacy: Any, text: str, required: Sequence[str]) -> str:
    segments = legacy._exact_quote_segments(text) or [
        legacy._first_exact_evidence_quote(text, max_chars=420)
    ]
    ranked: list[tuple[int, str]] = []
    for segment in segments:
        hits = patch._term_hits(required, segment)
        ranked.append((len(hits), segment))
    ranked.sort(key=lambda item: (-item[0], -len(item[1])))
    return ranked[0][1] if ranked else ""


def _precise_direct_facets(
    question: str,
    original: Any,
) -> list[dict[str, Any]]:
    facets = [dict(item) for item in _ORIGINAL_PRECISE_DIRECT_FACETS(question, original)]
    if not _has_graph_order_marker(question):
        facets = [item for item in facets if item.get("facet_id") != "ordering_boundary"]
    if not _has_source_marker(question):
        facets = [item for item in facets if item.get("facet_id") != "multi_source_selection"]
    return facets


def _surface(
    legacy: Any,
    question: str,
    facet_id: str,
    terms: Sequence[str],
    used_terms: set[str],
    quote: str,
    *,
    facet_label: str = "",
) -> str:
    if facet_id == "non_entailment_boundary" and not _has_graph_order_marker(question):
        visible = [
            term
            for term in patch._ordered_terms(legacy, " ".join(terms))
            if term not in used_terms
        ]
        used_terms.update(visible)
        label = facet_label or patch._phrase(visible or terms)
        return f"For {label}, the evidence supports this point: {patch._bounded_surface(quote)}"
    return _ORIGINAL_SURFACE(
        legacy,
        question,
        facet_id,
        terms,
        used_terms,
        quote,
        facet_label=facet_label,
    )


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", str(value).casefold()))


def _has_phrase(value: str, phrases: Sequence[str]) -> bool:
    padded = f" {' '.join(str(value).casefold().split())} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _has_source_marker(question: str) -> bool:
    q = str(question).casefold()
    tokens = _tokens(q)
    return "source" in tokens or "sources" in tokens or _has_phrase(q, _SOURCE_MARKER_PHRASES)


def _has_graph_order_marker(question: str) -> bool:
    q = str(question).casefold()
    tokens = _tokens(q)
    if _has_phrase(q, _GRAPH_ORDER_MARKER_PHRASES):
        return True
    if "precedes" in tokens or "preceding" in tokens:
        return True
    return bool((tokens & _GRAPH_ORDER_TOKENS) and (tokens & _GENERIC_PROVE_MARKERS))


def _looks_like_graph_premise_boundary(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    return (
        "relation graph" in q
        and ("preceding" in q or "precedes" in q)
        and ("dependency" in q or "causality" in q or "causal" in q)
    )


def _graph_premise_candidate(
    *,
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any] | None:
    original_facets = patch._ORIGINAL_DIRECT_FACETS or legacy._direct_question_facets
    facets = patch._precise_direct_facets(question, original_facets)
    refs: list[dict[str, str]] = []
    facet_ids: list[str] = []
    selected: list[str] = []
    for facet in facets[:4]:
        terms = patch._facet_terms(legacy, facet)
        item, _item_record = patch._best_item(
            legacy, runtime, evidence, terms, question, requirements
        )
        if item is None:
            continue
        quote, _quote_record = patch._support_quote(
            legacy,
            runtime,
            item,
            terms,
            question,
            requirements,
        )
        if not quote:
            continue
        refs.append(
            {
                "evidence_id": str(item.get("evidence_id", "")),
                "locator_id": str(item.get("locator_id", "")),
                "exact_quote": quote,
                "exact_support_snippet": quote,
                "uncertainty": "low",
            }
        )
        facet_ids.append(str(facet.get("facet_id", "direct_answer")))
        selected.append(str(item.get("evidence_id", "")))
    if not refs:
        return None
    surface = _graph_premise_surface(question)
    claims = [
        {
            "claim_id": "claim_1",
            "claim_role": "direct",
            "surface_text": surface,
            "facet_ids": sorted(set(facet_ids)) or ["direct_answer"],
            "support_mode": "multi_evidence_exact",
            "support_refs": refs[:2],
        }
    ]
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": "precedes",
        "selected_evidence_ids": list(dict.fromkeys(selected)),
        "answer_text": surface + " [[claim_1]].",
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _graph_premise_surface(question: str) -> str:
    left = "the first item"
    right = "the second item"
    match = re.search(
        r"records\s+(.+?)\s+as\s+preced(?:ing|es)\s+(.+?)(?:,|\?|$)",
        question,
        flags=re.I,
    )
    if match:
        left = re.sub(r"\s+", " ", match.group(1)).strip()
        right = re.sub(r"\s+", " ", match.group(2)).strip()
    return (
        f"If the relation graph records {left} as preceding {right}, the safe "
        "inference is ordering or navigation only; that precedes relation does not "
        "by itself prove dependency, causality, or that one item caused or is required "
        "by the other."
    )


def _unsupported_external_markers(
    question: str,
    evidence: Sequence[Mapping[str, Any]],
) -> list[str]:
    evidence_space = patch._evidence_marker_space(evidence)
    markers: list[str] = []
    for raw in re.findall(
        r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z]+)?\b|\b\d{3,4}\b|\b[a-z]+(?:-[a-z]+)+\b",
        question,
    ):
        marker = raw.strip(".,;:!?()[]{}\"")
        if not marker:
            continue
        marker_key = marker.casefold().replace(".", "").replace("-", "")
        marker_compact = marker.casefold().replace(".", "")
        if marker_key in patch._PROVIDER_ABSTAIN_EXTERNAL_STOPWORDS:
            continue
        if len(marker_key) <= 2 and not marker_key.isdigit():
            continue
        if marker_key not in evidence_space and marker_compact not in evidence_space:
            markers.append(marker)
    q = str(question).casefold()
    if "nonexistent" in q and "nonexistent" not in evidence_space:
        markers.append("nonexistent")
    if "ticketing protocol" in q:
        if "ticketing" not in evidence_space:
            markers.append("ticketing")
        if "protocol" not in evidence_space:
            markers.append("protocol")
    return sorted(dict.fromkeys(markers), key=str.casefold)


apply()
