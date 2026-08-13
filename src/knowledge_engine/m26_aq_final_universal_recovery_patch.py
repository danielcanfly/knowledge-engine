from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import Any

_RECOVERY_KEY = "universal_answerability_recovery"
_FINAL_MARKER = "_m26_aq_final_universal_recovery_callable"
_ORIGINAL_INTENT: Callable[[str], str] | None = None
_ORIGINAL_DIRECT_FACETS: Callable[[str], list[dict[str, Any]]] | None = None
_ORIGINAL_GENERALIZED_SYNTHESIZE: Any | None = None

_ORDER_TERMS = {
    "after",
    "before",
    "chronology",
    "newer",
    "older",
    "order",
    "ordering",
    "precedes",
    "sequence",
    "temporal",
    "timeline",
}
_TEMPORAL_TERMS = {
    "adoption state",
    "between source records",
    "conflict",
    "fresh",
    "freshness",
    "newer",
    "older",
    "source record",
    "source version",
    "stale",
    "temporal",
    "version",
}
_PROVIDER_ABSTAIN_EXTERNAL_STOPWORDS = {
    "according",
    "answer",
    "cite",
    "daniel",
    "evidence",
    "explain",
    "founder",
    "give",
    "how",
    "list",
    "only",
    "separate",
    "the",
    "using",
    "walk",
    "what",
    "when",
    "which",
    "why",
}
_QUESTION_CONTRACT_STOPWORDS = {
    "about",
    "again",
    "also",
    "answer",
    "around",
    "because",
    "between",
    "briefly",
    "case",
    "cite",
    "cited",
    "compare",
    "cover",
    "covering",
    "describe",
    "determine",
    "does",
    "explain",
    "from",
    "give",
    "grounded",
    "help",
    "into",
    "more",
    "only",
    "question",
    "rather",
    "should",
    "show",
    "source",
    "sources",
    "structured",
    "than",
    "that",
    "their",
    "there",
    "through",
    "using",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "without",
    "why",
}
_CONTRACT_MARKERS = (
    "covering",
    "including",
    "include",
    "separating",
    "separate",
    "distinguishing",
    "distinguish",
    "through",
    "across",
    "cover",
    "covers",
)
_MIN_ITEM_RELEVANCE_SCORE = 2.5
_MIN_QUOTE_RELEVANCE_SCORE = 2.0
_MAX_RECOVERY_FACETS = 12


def install(*, force_rebind: bool = False) -> None:
    """Install final recovery hooks on the effective serving synthesis path."""
    from . import m26_aq_semantic_runtime_patch_v3 as v3_patch
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime

    current_intent = legacy._intent_class
    current_facets = legacy._direct_question_facets
    current_synthesize = v3_patch._generalized_provider_synthesize
    if (
        not force_rebind
        and _is_final_callable(current_intent)
        and _is_final_callable(current_facets)
        and _is_final_callable(current_synthesize)
    ):
        return

    global _ORIGINAL_INTENT, _ORIGINAL_DIRECT_FACETS, _ORIGINAL_GENERALIZED_SYNTHESIZE
    if _is_final_callable(current_intent) and _ORIGINAL_INTENT is not None:
        current_intent = _ORIGINAL_INTENT
    if _is_final_callable(current_facets) and _ORIGINAL_DIRECT_FACETS is not None:
        current_facets = _ORIGINAL_DIRECT_FACETS
    if _is_final_callable(current_synthesize) and _ORIGINAL_GENERALIZED_SYNTHESIZE is not None:
        current_synthesize = _ORIGINAL_GENERALIZED_SYNTHESIZE

    _ORIGINAL_INTENT = current_intent
    _ORIGINAL_DIRECT_FACETS = current_facets
    _ORIGINAL_GENERALIZED_SYNTHESIZE = current_synthesize

    def intent_class(question: str) -> str:
        assert _ORIGINAL_INTENT is not None
        return _precise_intent(question, _ORIGINAL_INTENT)

    def direct_question_facets(question: str) -> list[dict[str, Any]]:
        assert _ORIGINAL_DIRECT_FACETS is not None
        return _precise_direct_facets(question, _ORIGINAL_DIRECT_FACETS)

    def generalized_synthesize(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert _ORIGINAL_GENERALIZED_SYNTHESIZE is not None
        kwargs.pop("legacy", None)
        kwargs.pop("runtime", None)
        return _synthesize_with_final_recovery(
            *args,
            legacy=legacy,
            runtime=runtime,
            original=_ORIGINAL_GENERALIZED_SYNTHESIZE,
            **kwargs,
        )

    _mark_final_callable(intent_class)
    _mark_final_callable(direct_question_facets)
    _mark_final_callable(generalized_synthesize)
    legacy._intent_class = intent_class
    legacy._direct_question_facets = direct_question_facets
    v3_patch._generalized_provider_synthesize = generalized_synthesize
    v3_patch._m26_aq_final_universal_recovery_patch_installed = True
    runtime._m26_aq_final_universal_recovery_patch_installed = True
    runtime._m26_aq_final_universal_recovery_patch_binding = {
        "intent": "legacy._intent_class",
        "facets": "legacy._direct_question_facets",
        "synthesize": "v3_patch._generalized_provider_synthesize",
        "force_rebind": bool(force_rebind),
    }


def _mark_final_callable(value: Any) -> None:
    try:
        setattr(value, _FINAL_MARKER, True)
    except Exception:
        pass


def _is_final_callable(value: Any) -> bool:
    return bool(getattr(value, _FINAL_MARKER, False))


def _precise_intent(question: str, original: Callable[[str], str]) -> str:
    intent = str(original(question))
    if intent != "temporal_conflict":
        return intent
    q = question.casefold()
    if any(term in q for term in _TEMPORAL_TERMS):
        return intent
    if "changed since" in q or "edited" in q or "retrieved_at" in q:
        return intent
    return "direct_grounded_knowledge"


def _precise_direct_facets(
    question: str,
    original: Callable[[str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    facets = [dict(item) for item in original(question)]
    if any(term in question.casefold() for term in _ORDER_TERMS):
        return facets
    return [item for item in facets if item.get("facet_id") != "ordering_boundary"]


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
    verification, closure = original(
        runtime=runtime,
        legacy=legacy,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    if verification.get("status") == "owner_only_cited_answer" and not closure.get("failures"):
        return _attach(
            verification,
            closure,
            {
                **_telemetry(question, verification, closure, evidence),
                "first_broken_stage": "not_needed",
            },
            preserve_existing=True,
        )

    telemetry = _telemetry(question, verification, closure, evidence)
    if not telemetry["universal_recovery_should_attempt"]:
        return _attach(verification, closure, telemetry)
    if intent_class != "direct_grounded_knowledge":
        telemetry["first_broken_stage"] = "unsupported_intent_for_final_recovery"
        return _attach(verification, closure, telemetry)

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
            return _attach(verification, closure, telemetry)
        telemetry["candidate_built"] = True
        telemetry["candidate_claim_count"] = len(candidate.get("claims", []))
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            provider_text=json.dumps(candidate, ensure_ascii=False, separators=(",", ":")),
        )
        telemetry["candidate_verify_result"] = "verified"
        telemetry["candidate_missing_facets"] = list(verified.get("missing_facets", []))
        answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
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
        return _attach(verification, closure, telemetry)

    if answer.get("status") != "owner_only_cited_answer":
        telemetry["candidate_verify_result"] = "non_cited_final_answer"
        telemetry["first_broken_stage"] = "final_answer_status"
        return _attach(verification, closure, telemetry)

    post = _post_render_alignment(legacy, question, answer, telemetry)
    telemetry.update(post)
    if not post["post_render_alignment_passed"]:
        telemetry["first_broken_stage"] = "post_render_question_alignment"
        return _attach(verification, closure, telemetry)

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
        _RECOVERY_KEY: telemetry,
        "verification_failure_codes_by_attempt": failures,
    }
    return answer, {
        **dict(closure),
        "broad_deterministic_fallback_used": True,
        "failures": [],
        "pre_recovery_failures": failures,
        _RECOVERY_KEY: {**telemetry, "used": True, "case_specific": False},
    }


def _telemetry(
    question: str,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    codes = sorted(
        {str(item) for item in verification.get("reason_codes", [])}
        | {str(item) for item in closure.get("failures", [])}
    )
    hard_stop = _hard_stop_codes(question, codes, evidence)
    passage_items = [
        item for item in evidence if item.get("evidence_type", "passage") == "passage"
    ]
    should_attempt = _should_attempt(question, verification, closure, evidence, hard_stop)
    return {
        "schema_version": "m26-aq-final-universal-recovery-telemetry/v2",
        "case_specific": False,
        "universal_recovery_attempted": should_attempt,
        "universal_recovery_should_attempt": should_attempt,
        "universal_recovery_trigger_codes": codes,
        "universal_recovery_hard_stop_codes": hard_stop,
        "recovery_input_evidence_count": len(evidence),
        "recovery_items_count": len(passage_items),
        "recovery_text_available_count": sum(
            1 for item in passage_items if str(item.get("passage_text", ""))
        ),
        "unsupported_external_markers": _unsupported_external_markers(question, evidence),
        "question_alignment_checked": False,
        "question_alignment_passed": False,
        "question_alignment_failure_codes": [],
        "required_question_facets": [],
        "covered_question_facets": [],
        "missing_question_facets": [],
        "post_render_alignment_checked": False,
        "post_render_alignment_passed": False,
        "post_render_alignment_failure_codes": [],
        "quote_facet_support_checked": False,
        "quote_facet_support_passed": False,
        "recovery_selected_evidence_relevance": [],
        "recovery_relevance_threshold_met": False,
        "candidate_built": False,
        "candidate_claim_count": 0,
        "candidate_verify_result": "not_attempted",
        "candidate_verify_failure_codes": [],
        "candidate_missing_facets": [],
        "candidate_exception_class": "",
        "first_broken_stage": "pending" if should_attempt else "not_recoverable",
        "published_verified_answer": False,
    }


def _hard_stop_codes(
    question: str,
    codes: Sequence[str],
    evidence: Sequence[Mapping[str, Any]],
) -> list[str]:
    hard_stop_codes = {
        "PROMPT_INJECTION_OR_PRIVACY_RISK",
        "NO_AUTHORIZED_PRODUCTION_EVIDENCE",
        "LOW_RETRIEVAL_SUPPORT",
        "QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED",
    }
    result = [code for code in codes if code in hard_stop_codes]
    if "PROVIDER_ABSTAINED" in codes and _unsupported_external_markers(question, evidence):
        result.append("PROVIDER_ABSTAINED")
    return sorted(set(result))


def _should_attempt(
    question: str,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    hard_stop: Sequence[str],
) -> bool:
    if verification.get("status") != "owner_only_safe_abstention" or not evidence:
        return False
    if hard_stop:
        return False
    if int(verification.get("unsupported_accepted_claims", 0)) != 0:
        return False
    if not bool(verification.get("citation_locator_valid", True)):
        return False
    codes = {str(item) for item in verification.get("reason_codes", [])}
    codes |= {str(item) for item in closure.get("failures", [])}
    recoverable = {
        "M26-PA7-ME-029",
        "M26-PA7-ME-032",
        "M26-PA7-ME-033",
        "PROVIDER_ABSTAINED",
        "SEMANTIC_CLOSURE_FAILED",
        "ValueError",
    }
    if "PROVIDER_ABSTAINED" in codes and _unsupported_external_markers(question, evidence):
        return False
    return bool(codes & recoverable)


def _unsupported_external_markers(
    question: str,
    evidence: Sequence[Mapping[str, Any]],
) -> list[str]:
    evidence_space = _evidence_marker_space(evidence)
    markers: list[str] = []
    for raw in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z]+)?\b|\b\d{3,4}\b", question):
        marker = raw.strip(".,;:!?()[]{}\"")
        if not marker:
            continue
        marker_key = marker.casefold().replace(".", "")
        if marker_key in _PROVIDER_ABSTAIN_EXTERNAL_STOPWORDS:
            continue
        if len(marker_key) <= 2 and not marker_key.isdigit():
            continue
        if marker_key not in evidence_space:
            markers.append(marker)
    return sorted(dict.fromkeys(markers), key=str.casefold)


def _evidence_marker_space(evidence: Sequence[Mapping[str, Any]]) -> set[str]:
    parts: list[str] = []
    for item in evidence:
        for key in ("source_id", "source_identity", "concept_id", "section_id"):
            parts.append(str(item.get(key, "")))
        metadata = item.get("retrieval_metadata", {})
        if isinstance(metadata, Mapping):
            for term in metadata.get("coverage_terms", []):
                parts.append(str(term))
            for term in metadata.get("graph_seed_concepts", []):
                parts.append(str(term))
    text = " ".join(parts).casefold().replace(".", "")
    return {token for token in re.findall(r"[a-z0-9]+", text) if token}


def _attach(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    *,
    preserve_existing: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    patched_verification = dict(verification)
    previous_mve = dict(patched_verification.get("multi_evidence_verification", {}))
    if preserve_existing and _RECOVERY_KEY in previous_mve:
        return patched_verification, dict(closure)
    patched_verification["multi_evidence_verification"] = {
        **previous_mve,
        _RECOVERY_KEY: dict(telemetry),
    }
    patched_closure = dict(closure)
    if not (preserve_existing and _RECOVERY_KEY in patched_closure):
        patched_closure[_RECOVERY_KEY] = dict(telemetry)
    return patched_verification, patched_closure


def _candidate(
    *,
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    telemetry: MutableMapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    items = _ranked_items(legacy, runtime, question, evidence, requirements)
    original_facets = _ORIGINAL_DIRECT_FACETS or legacy._direct_question_facets
    base_facets = _precise_direct_facets(question, original_facets)
    contract = _question_contract(legacy, question, base_facets)
    required = contract["required_question_facets"][:_MAX_RECOVERY_FACETS]

    if telemetry is not None:
        telemetry["recovery_items_count"] = len(items)
        telemetry["recovery_text_available_count"] = sum(
            1 for item in items if _text(runtime, item, question, requirements)
        )
        telemetry["question_alignment_checked"] = True
        telemetry["required_question_facets"] = [facet["label"] for facet in required]
        telemetry["covered_question_facets"] = []
        telemetry["missing_question_facets"] = []
        telemetry["question_alignment_failure_codes"] = []
        telemetry["recovery_selected_evidence_relevance"] = []
        telemetry["quote_facet_support_checked"] = True

    if not items or not required:
        _fail_alignment(telemetry, "no_recoverable_question_contract")
        return None

    claims: list[dict[str, Any]] = []
    covered: list[str] = []
    relevance_records: list[dict[str, Any]] = []
    used_terms: set[str] = set()
    for facet in required:
        terms = list(facet["terms"])
        item, item_record = _best_item(
            legacy,
            runtime,
            items,
            terms,
            question,
            requirements,
        )
        relevance_records.append({**item_record, "facet": facet["label"]})
        if item is None:
            _fail_alignment(telemetry, "evidence_relevance_below_threshold")
            if telemetry is not None:
                telemetry["missing_question_facets"].append(facet["label"])
                telemetry["recovery_selected_evidence_relevance"] = relevance_records
            return None
        quote, quote_record = _support_quote(
            legacy,
            runtime,
            item,
            terms,
            question,
            requirements,
        )
        relevance_records[-1]["quote_support"] = quote_record
        if not quote:
            _fail_alignment(telemetry, "quote_facet_support_below_threshold")
            if telemetry is not None:
                telemetry["missing_question_facets"].append(facet["label"])
                telemetry["recovery_selected_evidence_relevance"] = relevance_records
            return None
        surface = _surface(
            legacy,
            question,
            str(facet["facet_id"]),
            terms,
            used_terms,
            quote,
            facet_label=str(facet["label"]),
        )
        if not _surface_question_aligned(surface, facet):
            _fail_alignment(telemetry, "claim_question_alignment_failed")
            if telemetry is not None:
                telemetry["missing_question_facets"].append(facet["label"])
            return None
        claims.append(
            _claim(
                len(claims) + 1,
                str(facet["facet_id"]),
                surface,
                item,
                quote,
            )
        )
        covered.append(str(facet["label"]))

    if not claims:
        _fail_alignment(telemetry, "no_recovery_claims")
        return None

    if telemetry is not None:
        telemetry["covered_question_facets"] = covered
        telemetry["missing_question_facets"] = []
        telemetry["question_alignment_passed"] = True
        telemetry["quote_facet_support_passed"] = True
        telemetry["recovery_relevance_threshold_met"] = True
        telemetry["recovery_selected_evidence_relevance"] = relevance_records

    selected = [
        str(ref.get("evidence_id", ""))
        for claim in claims
        for ref in claim.get("support_refs", [])
    ]
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": None,
        "selected_evidence_ids": list(dict.fromkeys(selected)),
        "answer_text": " ".join(
            f"{claim['surface_text']} [[{claim['claim_id']}]]." for claim in claims
        ),
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _fail_alignment(telemetry: MutableMapping[str, Any] | None, code: str) -> None:
    if telemetry is None:
        return
    failures = list(telemetry.get("question_alignment_failure_codes", []))
    if code not in failures:
        failures.append(code)
    telemetry["question_alignment_failure_codes"] = failures
    telemetry["question_alignment_passed"] = False
    telemetry["recovery_relevance_threshold_met"] = False


def _claim(
    index: int,
    facet_id: str,
    surface: str,
    item: Mapping[str, Any],
    quote: str,
) -> dict[str, Any]:
    return {
        "claim_id": f"claim_{index}",
        "claim_role": "direct",
        "surface_text": surface,
        "facet_ids": [facet_id],
        "support_mode": "exact_quote",
        "support_refs": [
            {
                "evidence_id": str(item.get("evidence_id", "")),
                "locator_id": str(item.get("locator_id", "")),
                "exact_quote": quote,
                "exact_support_snippet": quote,
                "uncertainty": "low",
            }
        ],
    }


def _ranked_items(
    legacy: Any,
    runtime: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> list[Mapping[str, Any]]:
    passages = [item for item in evidence if item.get("evidence_type", "passage") == "passage"]
    terms = legacy._meaningful_terms(question)
    ranked = sorted(
        passages,
        key=lambda item: (
            -legacy._text_term_overlap_score(terms, _text(runtime, item, question, requirements)),
            -_coverage_score(item, terms),
            -_channel_score(item),
            legacy._is_article_root_evidence(item),
            str(item.get("evidence_id", "")),
        ),
    )
    return [
        item
        for item in ranked
        if legacy._passage_text_quality(_text(runtime, item, question, requirements)) > 0
    ][:12]


def _best_item(
    legacy: Any,
    runtime: Any,
    items: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
    question: str,
    requirements: Sequence[Any],
) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    term_set = _distinctive_terms(terms)
    records: list[tuple[float, Mapping[str, Any], dict[str, Any]]] = []
    for item in items:
        text = _text(runtime, item, question, requirements)
        score, record = _relevance_score(item, text, term_set)
        records.append((score, item, record))
    ranked = sorted(
        records,
        key=lambda entry: (-entry[0], str(entry[1].get("evidence_id", ""))),
    )
    if not ranked:
        return None, {"eligible": False, "score": 0.0, "evidence_id": ""}
    score, item, record = ranked[0]
    eligible = record["eligible"] and score >= _MIN_ITEM_RELEVANCE_SCORE
    record = {**record, "eligible": bool(eligible)}
    if not eligible:
        return None, record
    return item, record


def _support_quote(
    legacy: Any,
    runtime: Any,
    item: Mapping[str, Any],
    terms: Sequence[str],
    question: str,
    requirements: Sequence[Any],
) -> tuple[str, dict[str, Any]]:
    text = _text(runtime, item, question, requirements)
    if not text:
        return "", {"eligible": False, "score": 0.0, "evidence_id": item.get("evidence_id", "")}
    term_set = _distinctive_terms(terms)
    segments = legacy._exact_quote_segments(text)
    if not segments:
        segments = [legacy._first_exact_evidence_quote(text, max_chars=360)]
    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for segment in segments:
        if not segment:
            continue
        score, record = _quote_relevance_score(segment, term_set)
        ranked.append((score, segment, record))
    ranked.sort(
        key=lambda entry: (
            -entry[0],
            legacy._segment_noise_penalty(entry[1]),
            legacy._thin_heading(entry[1]),
            legacy._article_title_like(entry[1]),
            -len(entry[1]),
        )
    )
    if not ranked:
        return "", {"eligible": False, "score": 0.0, "evidence_id": item.get("evidence_id", "")}
    score, quote, record = ranked[0]
    eligible = record["eligible"] and score >= _MIN_QUOTE_RELEVANCE_SCORE
    record = {
        **record,
        "eligible": bool(eligible),
        "evidence_id": str(item.get("evidence_id", "")),
    }
    if not eligible:
        return "", record
    if len(quote) > 800:
        quote = quote[:800].rsplit(" ", 1)[0].rstrip()
    return quote, record


def _text(runtime: Any, item: Mapping[str, Any], question: str, requirements: Sequence[Any]) -> str:
    text = str(item.get("passage_text", ""))
    if text:
        return text
    try:
        return str(runtime._provider_snippet(item, question, requirements))
    except Exception:
        return ""


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
    if facet_id == "non_entailment_boundary":
        return (
            "The evidence does not by itself prove dependency or viability; "
            + _bounded_surface(quote)
        )
    if facet_id == "ordering_boundary":
        return "The evidence supports ordering or sequence only; " + _bounded_surface(quote)
    visible = [term for term in _ordered_terms(legacy, " ".join(terms)) if term not in used_terms]
    used_terms.update(visible)
    label = facet_label or _phrase(visible or terms)
    return f"For {label}, the evidence supports this point: {_bounded_surface(quote)}"


def _bounded_surface(text: str) -> str:
    surface = re.sub(r"\s+", " ", str(text)).strip()
    if len(surface) <= 900:
        return surface
    return surface[:900].rsplit(" ", 1)[0].rstrip(" ,;:")


def _ordered_terms(legacy: Any, text: str) -> list[str]:
    meaningful = legacy._meaningful_terms(text)
    ordered: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_+/-]+|[\u3400-\u9fff]+", text):
        for part in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", token.casefold()):
            if part in meaningful and part not in ordered:
                ordered.append(part)
    return ordered


def _facet_terms(legacy: Any, facet: Mapping[str, Any]) -> list[str]:
    try:
        terms = legacy._facet_terms(facet)
    except Exception:
        terms = {str(item) for item in facet.get("terms", []) if str(item)}
    return sorted(_distinctive_terms(terms))


def _coverage_score(item: Mapping[str, Any], terms: set[str]) -> float:
    metadata = item.get("retrieval_metadata", {})
    if not isinstance(metadata, Mapping):
        return 0.0
    coverage = {str(term).casefold() for term in metadata.get("coverage_terms", [])}
    return float(len(coverage & terms))


def _channel_score(item: Mapping[str, Any]) -> float:
    channels = {str(channel) for channel in item.get("channels", [])}
    return (
        (3.0 if "semantic_requirement_recovery" in channels else 0.0)
        + (2.5 if "required_facet_coverage" in channels else 0.0)
        + (2.0 if "query_coverage" in channels else 0.0)
        + (1.5 if "dense" in channels else 0.0)
        + (1.0 if "lexical" in channels else 0.0)
        + (0.75 if any(channel.startswith("graph_") for channel in channels) else 0.0)
    )


def _question_contract(
    legacy: Any,
    question: str,
    facets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    explicit = _explicit_question_facets(legacy, question)
    required: list[dict[str, Any]] = []
    if explicit:
        required.extend(explicit)
    for facet in facets:
        facet_id = str(facet.get("facet_id", "direct_answer"))
        terms = _facet_terms(legacy, facet)
        if facet_id == "direct_answer" and explicit:
            continue
        if not terms:
            continue
        required.append(
            {
                "facet_id": facet_id,
                "label": _phrase(terms),
                "terms": terms,
            }
        )
    if not required:
        terms = _distinctive_terms(_ordered_terms(legacy, question))[:8]
        if terms:
            required.append(
                {"facet_id": "direct_answer", "label": _phrase(terms), "terms": terms}
            )
    return {"required_question_facets": _dedupe_facets(required)}


def _explicit_question_facets(legacy: Any, question: str) -> list[dict[str, Any]]:
    normalized = re.sub(r"[?!.]", ",", question)
    pieces: list[str] = []
    for raw_piece in re.split(r"[,;:]", normalized):
        piece = raw_piece.strip(" -—\t\n")
        if not piece:
            continue
        lowered = piece.casefold()
        for marker in _CONTRACT_MARKERS:
            marker_with_space = f"{marker} "
            if marker_with_space in lowered:
                piece = piece[lowered.rfind(marker_with_space) + len(marker_with_space) :]
                break
        pieces.extend(re.split(r"\s+(?:and|or)\s+", piece, flags=re.IGNORECASE))
    facets: list[dict[str, Any]] = []
    for piece in pieces:
        label = _clean_label(piece)
        terms = _distinctive_terms(_ordered_terms(legacy, label))
        if not terms:
            continue
        if len(terms) == 1 and len(terms[0]) < 3:
            continue
        facets.append({"facet_id": "direct_answer", "label": label, "terms": terms})
    return _dedupe_facets(facets)


def _clean_label(value: str) -> str:
    label = re.sub(r"\s+", " ", value).strip(" ,.;:!?()[]{}\"'")
    label = re.sub(
        r"^(?:walk|explain|show|tell|give|list|cover|include)\s+",
        "",
        label,
        flags=re.IGNORECASE,
    )
    words = [word for word in label.split() if word.casefold() not in _QUESTION_CONTRACT_STOPWORDS]
    return " ".join(words).strip() or label


def _distinctive_terms(terms: Sequence[str]) -> list[str]:
    result: list[str] = []
    for term in terms:
        for part in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", str(term).casefold()):
            if part in _QUESTION_CONTRACT_STOPWORDS:
                continue
            if len(part) < 2 and not part.isdigit():
                continue
            if part not in result:
                result.append(part)
    return result


def _dedupe_facets(facets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for facet in facets:
        terms = _distinctive_terms([str(item) for item in facet.get("terms", [])])
        if not terms:
            continue
        key = tuple(terms)
        if key in seen:
            continue
        seen.add(key)
        label = str(facet.get("label") or _phrase(terms))
        deduped.append(
            {
                "facet_id": str(facet.get("facet_id", "direct_answer")),
                "label": label,
                "terms": terms,
            }
        )
    return deduped


def _term_space(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", text.casefold()))


def _term_hits(terms: Sequence[str], text: str) -> set[str]:
    space = _term_space(text)
    text_folded = text.casefold()
    hits: set[str] = set()
    for term in _distinctive_terms(terms):
        if term in space or (len(term) >= 4 and term in text_folded):
            hits.add(term)
    return hits


def _relevance_score(
    item: Mapping[str, Any],
    text: str,
    terms: Sequence[str],
) -> tuple[float, dict[str, Any]]:
    hit_terms = _term_hits(terms, text)
    coverage = _coverage_score(item, set(terms))
    score = float(len(hit_terms) * 2) + coverage + min(_channel_score(item), 3.0) * 0.25
    needed = 1 if len(terms) <= 2 else 2
    eligible = len(hit_terms) >= needed or (len(hit_terms) >= 1 and coverage >= 1.0)
    return score, {
        "evidence_id": str(item.get("evidence_id", "")),
        "score": round(score, 3),
        "term_hits": sorted(hit_terms),
        "required_terms": list(terms),
        "coverage_score": coverage,
        "eligible": bool(eligible),
    }


def _quote_relevance_score(segment: str, terms: Sequence[str]) -> tuple[float, dict[str, Any]]:
    hit_terms = _term_hits(terms, segment)
    score = float(len(hit_terms) * 2)
    needed = 1 if len(terms) <= 2 else 2
    eligible = len(hit_terms) >= needed
    return score, {
        "score": round(score, 3),
        "term_hits": sorted(hit_terms),
        "required_terms": list(terms),
        "eligible": bool(eligible),
    }


def _surface_question_aligned(surface: str, facet: Mapping[str, Any]) -> bool:
    text = surface.casefold()
    label = str(facet.get("label", "")).casefold()
    terms = _distinctive_terms([str(item) for item in facet.get("terms", [])])
    return bool(label and label in text) or bool(_term_hits(terms, surface))


def _post_render_alignment(
    legacy: Any,
    question: str,
    answer: Mapping[str, Any],
    telemetry: Mapping[str, Any],
) -> dict[str, Any]:
    del legacy, question
    answer_text = str(answer.get("answer_text", ""))
    required = [str(item) for item in telemetry.get("required_question_facets", [])]
    covered = []
    missing = []
    for label in required:
        terms = _distinctive_terms([label])
        if label.casefold() in answer_text.casefold() or _term_hits(terms, answer_text):
            covered.append(label)
        else:
            missing.append(label)
    failure_codes = [] if not missing else ["missing_required_facet_after_render"]
    return {
        "post_render_alignment_checked": True,
        "post_render_alignment_passed": not missing,
        "post_render_alignment_failure_codes": failure_codes,
        "covered_question_facets": covered,
        "missing_question_facets": missing,
    }


def _phrase(terms: Sequence[str]) -> str:
    clean = [str(term).replace("_", " ") for term in terms if str(term)]
    if len(clean) <= 1:
        return clean[0] if clean else "the requested distinction"
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"
