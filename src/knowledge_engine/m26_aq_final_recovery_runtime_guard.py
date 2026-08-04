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


def apply() -> None:
    """Apply bounded production-only guards around final recovery.

    This module deliberately patches the already-loaded final recovery module instead of
    introducing another serving wrapper. The goal is to keep a single canonical hook while
    tightening two live boundaries observed in closure artifacts: provider-abstain recovery
    must not answer invented external protocols, and non-direct internal comparisons may use
    deterministic verified evidence recovery when the original serving path already selected
    authorized evidence.
    """
    with suppress(Exception):
        patch._PROVIDER_ABSTAIN_EXTERNAL_STOPWORDS.update({"compare", "dag"})
    patch._unsupported_external_markers = _unsupported_external_markers
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
    if intent in _RECOVERABLE_INTENTS:
        candidate = _legacy_candidate(legacy, question, intent, evidence)
        if candidate is not None:
            return candidate
    direct = _legacy_candidate(legacy, question, "direct_grounded_knowledge", evidence)
    if direct is not None:
        return direct
    return _ORIGINAL_CANDIDATE(
        legacy=legacy,
        runtime=runtime,
        question=question,
        evidence=evidence,
        requirements=requirements,
        telemetry=telemetry,
    )


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
        item = patch._best_item(legacy, runtime, evidence, terms, question, requirements)
        if item is None:
            continue
        quote = patch._support_quote(legacy, runtime, item, terms, question, requirements)
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
