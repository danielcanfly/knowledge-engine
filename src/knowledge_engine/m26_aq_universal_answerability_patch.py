from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_ORIGINAL_HAS_MEANINGFUL_OVERLAP: Callable[[str, Sequence[Mapping[str, Any]]], bool] | None = None
_ORIGINAL_SYNTHESIZE_AND_VERIFY: Any | None = None


def install() -> None:
    """Install question-agnostic answerability repair hooks."""
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime

    if getattr(runtime, "_m26_aq_universal_answerability_patch_installed", False):
        return

    global _ORIGINAL_HAS_MEANINGFUL_OVERLAP, _ORIGINAL_SYNTHESIZE_AND_VERIFY
    _ORIGINAL_HAS_MEANINGFUL_OVERLAP = legacy._has_meaningful_overlap
    _ORIGINAL_SYNTHESIZE_AND_VERIFY = runtime._synthesize_and_verify

    def semantic_overlap(
        question: str,
        evidence: Sequence[Mapping[str, Any]],
    ) -> bool:
        assert _ORIGINAL_HAS_MEANINGFUL_OVERLAP is not None
        return _semantic_admission_overlap(
            legacy=legacy,
            question=question,
            evidence=evidence,
            original=_ORIGINAL_HAS_MEANINGFUL_OVERLAP,
        )

    def synthesize(
        *,
        question: str,
        trace_id: str,
        intent_class: str,
        evidence: Sequence[Mapping[str, Any]],
        provider_client: Any,
        requirements: Sequence[Any],
        endpoint_proof: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert _ORIGINAL_SYNTHESIZE_AND_VERIFY is not None
        return _synthesize_with_evidence_recovery(
            runtime=runtime,
            legacy=legacy,
            original=_ORIGINAL_SYNTHESIZE_AND_VERIFY,
            question=question,
            trace_id=trace_id,
            intent_class=intent_class,
            evidence=evidence,
            provider_client=provider_client,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
        )

    legacy._has_meaningful_overlap = semantic_overlap
    runtime._synthesize_and_verify = synthesize
    runtime._m26_aq_universal_answerability_patch_installed = True


def _semantic_admission_overlap(
    *,
    legacy: Any,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    original: Callable[[str, Sequence[Mapping[str, Any]]], bool],
) -> bool:
    """Let semantically strong selected evidence reach synthesis without lexical overlap."""
    try:
        if original(question, evidence):
            return True
    except Exception:
        return False

    query_terms = legacy._meaningful_terms(question)
    if not query_terms or legacy._requires_precise_overlap(query_terms):
        return False

    passages = [item for item in evidence if item.get("evidence_type", "passage") == "passage"]
    if len(passages) < 2 or not _has_semantic_signal(passages):
        return False
    if _distinct_sources(legacy, passages) < 2 and len(passages) < 3:
        return False

    quality = sum(
        legacy._passage_text_quality(str(item.get("passage_text", "")))
        for item in passages
    )
    return quality > 0


def _has_semantic_signal(evidence: Sequence[Mapping[str, Any]]) -> bool:
    semantic_channels = {
        "dense",
        "query_coverage",
        "required_facet_coverage",
        "release_distinct_source",
        "semantic_requirement_recovery",
    }
    metadata_keys = {
        "coverage_terms",
        "graph_relevance_scores",
        "query_overlap_score",
        "semantic_requirement_score",
    }
    for item in evidence:
        channels = {str(channel) for channel in item.get("channels", [])}
        if channels & semantic_channels:
            return True
        if any(channel.startswith("graph_") for channel in channels):
            return True
        metadata = item.get("retrieval_metadata", {})
        if isinstance(metadata, Mapping) and bool(metadata_keys & set(metadata)):
            return True
    return False


def _synthesize_with_evidence_recovery(
    *,
    runtime: Any,
    legacy: Any,
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
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    if not _should_attempt_evidence_recovery(verification, closure, evidence):
        return verification, closure

    candidate = _evidence_bound_recovery_candidate(
        runtime=runtime,
        legacy=legacy,
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
    )
    if candidate is None:
        return verification, closure

    try:
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            provider_text=json.dumps(candidate, ensure_ascii=False, separators=(",", ":")),
        )
        final_answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=evidence,
            calls=[],
            repair_attempted=True,
        )
    except Exception:
        return verification, closure

    if final_answer.get("status") != "owner_only_cited_answer":
        return verification, closure

    previous_checks = _verification_map(verification)
    previous_closure = dict(closure) if isinstance(closure, Mapping) else {}
    failures = sorted(set(str(item) for item in previous_closure.get("failures", [])))
    final_answer["provider_call_count"] = int(verification.get("provider_call_count", 0))
    final_answer["payg_equivalent_cost_usd"] = str(
        verification.get("payg_equivalent_cost_usd", "0")
    )
    final_answer["repair_attempted"] = True
    final_answer["answer_source"] = "deterministic_verified_evidence_recovery"
    final_answer["multi_evidence_verification"] = {
        **dict(final_answer.get("multi_evidence_verification", {})),
        "provider_attempt_telemetry": list(previous_checks.get("provider_attempt_telemetry", [])),
        "repair_result": "deterministic_verified_evidence_recovery",
        "repair_trigger": failures,
        "universal_answerability_recovery": True,
        "verification_failure_codes_by_attempt": failures,
    }
    return final_answer, {
        **previous_closure,
        "broad_deterministic_fallback_used": True,
        "failures": [],
        "pre_recovery_failures": failures,
        "universal_answerability_recovery": {
            "case_specific": False,
            "mechanism": "selected_evidence_exact_quote_reverification",
            "used": True,
        },
    }


def _verification_map(verification: Mapping[str, Any]) -> Mapping[str, Any]:
    value = verification.get("multi_evidence_verification", {})
    return value if isinstance(value, Mapping) else {}


def _should_attempt_evidence_recovery(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> bool:
    if verification.get("status") != "owner_only_safe_abstention" or not evidence:
        return False
    combined = {str(item) for item in verification.get("reason_codes", [])}
    combined |= {str(item) for item in closure.get("failures", [])}
    hard_stop = {
        "LOW_RETRIEVAL_SUPPORT",
        "NO_AUTHORIZED_PRODUCTION_EVIDENCE",
        "PROMPT_INJECTION_OR_PRIVACY_RISK",
        "PROVIDER_ABSTAINED",
        "QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED",
    }
    if combined & hard_stop:
        return False
    recoverable = any(
        item == "SEMANTIC_CLOSURE_FAILED"
        or item in {"M26-PA7-ME-029", "M26-PA7-ME-032"}
        or item.startswith("USER_VISIBLE_INTERNAL_REFERENCE_LEAK:")
        for item in combined
    )
    if not recoverable:
        return False
    if int(verification.get("unsupported_accepted_claims", 0)) != 0:
        return False
    return bool(verification.get("citation_locator_valid", True))


def _evidence_bound_recovery_candidate(
    *,
    runtime: Any,
    legacy: Any,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any] | None:
    used_items = _recovery_items(
        runtime=runtime,
        legacy=legacy,
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
    )
    if not used_items:
        return None

    role, relation = _claim_role_and_relation(intent_class, used_items)
    required_facets = legacy._required_facet_ids(question=question, intent_class=intent_class)
    claims: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for index, item in enumerate(used_items[:4], start=1):
        quote = _exact_recovery_quote(runtime, legacy, item, question, requirements)
        if not quote:
            continue
        evidence_id = str(item.get("evidence_id", ""))
        selected_ids.append(evidence_id)
        claims.append(
            {
                "claim_id": f"claim_{index}",
                "claim_role": role,
                "facet_ids": required_facets if index == 1 else ["direct_answer"],
                "surface_text": quote,
                "support_mode": "selected_evidence_exact_quote_recovery",
                "support_refs": [
                    {
                        "evidence_id": evidence_id,
                        "exact_quote": quote,
                        "locator_id": str(item.get("locator_id", "")),
                        "uncertainty": "low",
                    }
                ],
            }
        )
    if not claims:
        return None

    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": list(dict.fromkeys(selected_ids)),
        "answer_text": " ".join(
            f"{claim['surface_text']} [[{claim['claim_id']}]]." for claim in claims
        ),
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _claim_role_and_relation(
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    if intent_class == "cross_document_comparison":
        return "comparison", "contrasts_with"
    if intent_class == "complementary_synthesis":
        return "relationship", "complements"
    if intent_class == "graph_relationship":
        edge = next((item for item in used_items if item.get("evidence_type") == "graph_edge"), None)
        relation = str(edge.get("relation_type", "")) if edge is not None else None
        return "relationship", relation
    if intent_class == "provenance_source_trace":
        return "provenance", None
    if intent_class == "temporal_conflict":
        return "temporal", "precedes"
    return "direct", None


def _recovery_items(
    *,
    runtime: Any,
    legacy: Any,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> list[Mapping[str, Any]]:
    passages = [item for item in evidence if item.get("evidence_type", "passage") == "passage"]
    if intent_class == "graph_relationship":
        graph_items = [item for item in evidence if item.get("evidence_type") == "graph_edge"]
        passages = [*graph_items, *passages]
    if not passages:
        return []

    query_terms = legacy._meaningful_terms(question)
    ranked = sorted(
        passages,
        key=lambda item: (
            -_requirement_score(runtime, item, requirements),
            -legacy._text_term_overlap_score(query_terms, str(item.get("passage_text", ""))),
            -_channel_strength(item),
            legacy._is_article_root_evidence(item),
            -legacy._passage_text_quality(str(item.get("passage_text", ""))),
            str(item.get("evidence_id", "")),
        ),
    )

    selected: list[Mapping[str, Any]] = []
    seen_sources: set[str] = set()
    for item in ranked:
        if legacy._passage_text_quality(str(item.get("passage_text", ""))) <= 0:
            continue
        source = legacy._source_identity(item)
        if source in seen_sources and len(selected) >= 2:
            continue
        selected.append(item)
        seen_sources.add(source)
        if len(selected) >= 3:
            break
    return selected


def _exact_recovery_quote(
    runtime: Any,
    legacy: Any,
    item: Mapping[str, Any],
    question: str,
    requirements: Sequence[Any],
) -> str:
    text = str(item.get("passage_text", ""))
    if not text:
        return ""
    quote = runtime._provider_snippet(item, question, requirements)
    if quote and quote in text and len(quote) <= 800:
        return quote
    fallback = legacy._first_exact_evidence_quote(text, max_chars=360)
    if fallback and fallback in text and len(fallback) <= 800:
        return fallback
    return ""


def _requirement_score(
    runtime: Any,
    item: Mapping[str, Any],
    requirements: Sequence[Any],
) -> float:
    scores = [
        runtime._requirement_evidence_score(requirement, item)
        for requirement in requirements
    ]
    return max(scores or [0.0])


def _channel_strength(item: Mapping[str, Any]) -> float:
    channels = {str(channel) for channel in item.get("channels", [])}
    score = 0.0
    if "semantic_requirement_recovery" in channels:
        score += 3.0
    if "required_facet_coverage" in channels:
        score += 2.5
    if "query_coverage" in channels:
        score += 2.0
    if "dense" in channels:
        score += 1.5
    if "lexical" in channels:
        score += 1.0
    if any(channel.startswith("graph_") for channel in channels):
        score += 0.75
    return score


def _distinct_sources(legacy: Any, evidence: Sequence[Mapping[str, Any]]) -> int:
    return len({legacy._source_identity(item) for item in evidence})
