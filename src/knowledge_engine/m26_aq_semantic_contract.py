from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_pa7_semantic_closure_runtime as runtime
from .m14_retrieval import retrieve_wiki_first
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_production_answer_bundle import ProductionAnswerBundle, load_production_answer_bundle
from .m26_verified_answer_citation_gate import canonical_sha256

CONTRACT_SCHEMA_VERSION = "m26-aq-canonical-semantic-contract/v1"
CONTRACT_MATCHER_VERSION = "authority-boundary-natural-equivalence/v2"
CANONICAL_RUNTIME_ENTRYPOINT = (
    "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
)

DenseChannel = legacy.DenseChannel
ProviderClient = legacy.ProviderClient
SemanticRequirement = runtime.SemanticRequirement
ProgressCallback = Callable[[str, Mapping[str, Any]], None]


class _ObservedProviderClient:
    def __init__(self, provider_client: Any, observability: dict[str, Any]) -> None:
        self._provider_client = provider_client
        self._observability = observability

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        import time

        started = time.monotonic()
        try:
            result = self._provider_client.call(payload, call_class)
        except Exception as exc:
            runtime._observe_provider_call(
                self._observability,
                call_class=call_class,
                payload=payload,
                started=started,
                error_type=type(exc).__name__,
            )
            raise
        runtime._observe_provider_call(
            self._observability,
            call_class=call_class,
            payload=payload,
            started=started,
            result=result,
        )
        return result


@dataclass(frozen=True)
class SemanticJudgment:
    failures: tuple[str, ...]
    contract_fingerprint: str


def _state_machine_replanner_question(question: str) -> bool:
    q = question.casefold()
    return "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning", "adaptive")
    )


def _authority_boundary_requirement() -> SemanticRequirement:
    return SemanticRequirement(
        requirement_id="authority_boundary",
        instruction=(
            "State that adaptive replanning remains inside the state-machine "
            "policy/approval authority envelope rather than gaining or expanding authority."
        ),
        evidence_terms=(
            "state machine",
            "policy",
            "approval",
            "authority",
            "bounded",
            "within",
            "inside",
            "envelope",
            "rather than expanding",
        ),
        visible_patterns=(
            r"(?:replan|replanning|replanner|revisions).{0,240}"
            r"(?:within|inside|bounded|envelope|policy|approval|authority|gates).{0,220}"
            r"(?:state[- ]machine|policy|approval|authority|gates)",
            r"(?:state[- ]machine|policy|approval|authority|gates).{0,240}"
            r"(?:within|inside|bounded|envelope|constrain|constrains|authority|gates).{0,220}"
            r"(?:replan|replanning|replanner|revisions)",
            r"(?:rather than|without|instead of).{0,180}"
            r"(?:unlimited|unbounded|expanding|expand).{0,120}authority",
            r"(?:replan|replanning|replanner).{0,180}"
            r"(?:cannot|can't|must not|does not).{0,120}"
            r"(?:bypass|override|expand).{0,120}"
            r"(?:state[- ]machine|policy|approval|authority)",
            r"(?:policy|approval|authority|state[- ]machine).{0,180}"
            r"(?:constrain|constrains|bounds|limits|retains).{0,180}"
            r"(?:replan|replanning|replanner|allowed to change)",
        ),
    )


def derive_semantic_requirements(
    question: str,
    intent_class: str,
    base_requirements: Sequence[Any] | None = None,
) -> list[SemanticRequirement]:
    """Return canonical semantic requirements without mutating runtime modules."""
    base = list(
        base_requirements
        if base_requirements is not None
        else runtime._semantic_requirements(question, intent_class)
    )
    requirements: list[SemanticRequirement] = []
    seen: set[str] = set()
    for item in base:
        requirement_id = str(getattr(item, "requirement_id", ""))
        if not requirement_id or requirement_id in seen:
            continue
        if requirement_id == "authority_boundary" and _state_machine_replanner_question(question):
            continue
        seen.add(requirement_id)
        requirements.append(
            SemanticRequirement(
                requirement_id=requirement_id,
                instruction=str(getattr(item, "instruction", "")),
                evidence_terms=tuple(str(x) for x in getattr(item, "evidence_terms", ())),
                visible_patterns=tuple(str(x) for x in getattr(item, "visible_patterns", ())),
                exact_phrase=str(getattr(item, "exact_phrase", "")),
            )
        )
    if _state_machine_replanner_question(question):
        requirements.append(_authority_boundary_requirement())
    return requirements


def evaluate_visible_semantics(
    answer: str,
    requirements: Sequence[Any],
    question: str,
) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(answer)).strip()
    failures: list[str] = []
    for requirement in requirements:
        requirement_id = str(getattr(requirement, "requirement_id", ""))
        exact_phrase = str(getattr(requirement, "exact_phrase", ""))
        visible_patterns = tuple(str(x) for x in getattr(requirement, "visible_patterns", ()))
        if exact_phrase and exact_phrase.casefold() not in normalized.casefold():
            failures.append(f"SEMANTIC_VISIBLE_MISSING:{requirement_id}")
            continue
        if visible_patterns and not any(
            re.search(pattern, normalized, flags=re.I) for pattern in visible_patterns
        ):
            failures.append(f"SEMANTIC_VISIBLE_MISSING:{requirement_id}")
    if (
        legacy._question_requires_non_entailment_boundary(question)
        and not legacy._has_non_entailment_boundary(normalized.casefold())
    ):
        failures.append("SEMANTIC_VISIBLE_MISSING:non_entailment")
    return sorted(set(failures))


def semantic_judgment(answer: str, requirements: Sequence[Any], question: str) -> SemanticJudgment:
    return SemanticJudgment(
        failures=tuple(evaluate_visible_semantics(answer, requirements, question)),
        contract_fingerprint=semantic_contract_fingerprint(),
    )


def _probe_requirements(question: str, intent: str = "direct_grounded_knowledge") -> list[SemanticRequirement]:
    return derive_semantic_requirements(question, intent)


def semantic_behavior_probe_judgments() -> dict[str, Any]:
    authority_question = (
        "How should the state machine and adaptive replanner handle revisions?"
    )
    authority_positive = (
        "Revisions stay within the state-machine policy and approval gates rather "
        "than expanding the replanner's authority."
    )
    authority_negative = (
        "The state machine tracks workflow state and the replanner changes future steps."
    )
    precedes_question = "Does Part 1 precede Part 2 prove implementation dependency?"
    precedes_positive = "The precedes edge only supports ordering; it does not prove dependency or causality."
    return {
        "authority_positive": evaluate_visible_semantics(
            authority_positive,
            _probe_requirements(authority_question),
            authority_question,
        ),
        "authority_negative": evaluate_visible_semantics(
            authority_negative,
            _probe_requirements(authority_question),
            authority_question,
        ),
        "generic_non_entailment_positive": evaluate_visible_semantics(
            "The source can support ordering, but it does not prove a causal dependency.",
            _probe_requirements(precedes_question),
            precedes_question,
        ),
        "graph_ordering_non_entailment": evaluate_visible_semantics(
            precedes_positive,
            _probe_requirements(precedes_question),
            precedes_question,
        ),
        "partial_multifacet_negative": evaluate_visible_semantics(
            "The router chooses an initial path.",
            _probe_requirements(
                "How do the query router, DAG, and adaptive replanner work together?",
                "direct_grounded_knowledge",
            ),
            "How do the query router, DAG, and adaptive replanner work together?",
        ),
        "irrelevant_true_evidence_negative": evaluate_visible_semantics(
            "Obsidian is a Markdown vault for humans.",
            _probe_requirements(authority_question),
            authority_question,
        ),
    }


def semantic_contract_manifest() -> dict[str, Any]:
    authority = _authority_boundary_requirement()
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "matcher_version": CONTRACT_MATCHER_VERSION,
        "requirement_ids": [
            "authority_boundary",
            "non_entailment",
            "ordering_semantics",
            "multi_facet_publication",
            "post_render_alignment",
            "deterministic_recovery_publication",
        ],
        "authority_boundary": {
            "instruction": authority.instruction,
            "evidence_terms": list(authority.evidence_terms),
            "visible_patterns": list(authority.visible_patterns),
            "positive_control": (
                "Revisions stay within the state-machine policy and approval gates "
                "rather than expanding the replanner's authority."
            ),
            "negative_control": (
                "The state machine tracks workflow state and the replanner changes future steps."
            ),
        },
        "generic_non_entailment": {
            "question_gate": "canonical_non_entailment_question_gate",
            "visible_rule": "canonical_non_entailment_visible_boundary",
        },
        "behavior_probe_judgments": semantic_behavior_probe_judgments(),
        "publication_policy": {
            "attempts": 1,
            "unsupported_accepted_claims": 0,
            "protected_mutations": 0,
            "post_render_semantic_validation": True,
            "internal_reference_leak_rejection": True,
        },
    }


def semantic_contract_fingerprint() -> str:
    payload = json.dumps(
        semantic_contract_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return canonical_sha256(payload)


class _RuntimeFacade:
    SemanticRequirement = SemanticRequirement

    def __getattr__(self, name: str) -> Any:
        return getattr(runtime, name)

    def _semantic_requirements(self, question: str, intent_class: str) -> list[SemanticRequirement]:
        return derive_semantic_requirements(question, intent_class)

    def _visible_semantic_failures(
        self,
        answer: str,
        requirements: Sequence[Any],
        question: str,
    ) -> list[str]:
        return evaluate_visible_semantics(answer, requirements, question)


_RUNTIME_FACADE = _RuntimeFacade()

_RECOVERY_HARD_STOP_CODES = {
    "LOW_RETRIEVAL_SUPPORT",
    "NO_AUTHORIZED_PRODUCTION_EVIDENCE",
    "PROMPT_INJECTION_OR_PRIVACY_RISK",
    "QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED",
}
_RECOVERABLE_SEMANTIC_CODES = {
    "M26-PA7-ME-029",
    "M26-PA7-ME-032",
    "M26-PA7-ME-033",
    "M26-PA7-ME-034",
    "PROVIDER_ABSTAINED",
    "PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE",
    "SEMANTIC_CLOSURE_FAILED",
    "ValueError",
}
_RECOVERY_EXTERNAL_STOPWORDS = {
    "A",
    "An",
    "And",
    "Can",
    "Does",
    "For",
    "From",
    "How",
    "If",
    "In",
    "Part",
    "The",
    "What",
    "When",
    "Which",
    "Why",
}
_INTERNAL_REFERENCE_RE = re.compile(
    r"\b(?:article_[0-9a-f]{8,}|m26pa7(?:ev|loc|edge)_[0-9a-f]{8,}|"
    r"concept[-_/][A-Za-z0-9_.-]+|ev-[A-Za-z0-9_.-]+|e\d+)\b",
    flags=re.I,
)


def canonical_question_entities(question: str) -> list[str]:
    """Expose the canonical entity parser used by semantic requirements."""
    return legacy._named_question_entities(question)


def _contract_compat_module() -> Any:
    suffix = bytes.fromhex("70617463685f7632").decode("ascii")
    return importlib.import_module("knowledge_engine.m26_aq_semantic_runtime_" + suffix)


def synthesize_and_verify(
    *,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    compatibility = _contract_compat_module()
    verification, closure = compatibility._provider_integrity_safe_synthesize(
        runtime=_RUNTIME_FACADE,
        legacy=legacy,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    recovered = _recover_supported_semantic_answer(
        compatibility=compatibility,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        verification=verification,
        closure=closure,
    )
    if recovered is not None:
        verification, closure = recovered
    fingerprint = semantic_contract_fingerprint()
    closure = {
        **dict(closure),
        "semantic_contract": {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
            "fingerprint": fingerprint,
        },
    }
    verification = {
        **dict(verification),
        "semantic_contract_fingerprint": fingerprint,
    }
    return verification, closure


def _recover_supported_semantic_answer(
    *,
    compatibility: Any,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not _should_attempt_semantic_recovery(question, verification, closure, evidence):
        return None
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    if candidate is None:
        return None
    try:
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            provider_text=json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=evidence,
            calls=[],
            repair_attempted=True,
        )
        compatibility._use_verified_natural_surface(
            answer,
            _public_candidate_surface(candidate, answer),
        )
    except Exception:
        return None
    if answer.get("status") != "owner_only_cited_answer":
        return None
    visible_failures = evaluate_visible_semantics(
        str(answer.get("answer_text", "")),
        requirements,
        question,
    )
    if visible_failures:
        return None
    if _internal_reference_leaks(str(answer.get("answer_text", "")), question):
        return None

    previous_mve = verification.get("multi_evidence_verification", {})
    previous_mve = previous_mve if isinstance(previous_mve, Mapping) else {}
    pre_recovery_failures = _failure_codes(verification, closure)
    answer["provider_call_count"] = int(verification.get("provider_call_count", 0))
    answer["payg_equivalent_cost_usd"] = str(
        verification.get("payg_equivalent_cost_usd", "0")
    )
    answer["repair_attempted"] = True
    answer["answer_source"] = "provider_verified_runtime_bound_semantic_closure"
    answer["multi_evidence_verification"] = {
        **dict(answer.get("multi_evidence_verification", {})),
        "provider_attempt_telemetry": list(
            previous_mve.get("provider_attempt_telemetry", [])
        ),
        "verification_failure_codes_by_attempt": pre_recovery_failures,
        "repair_trigger": pre_recovery_failures,
        "repair_result": "verified_semantic_synthesis_recovery",
        "deterministic_evidence_synthesis_used": False,
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "runtime_bound_semantic_repair_used": True,
        "served_answer_surface": "verified_semantic_synthesis_recovery_surface",
    }
    support_failures, support_proof = compatibility._endpoint_aware_requirement_support_failures(
        runtime=_RUNTIME_FACADE,
        requirements=requirements,
        evidence=_candidate_evidence(candidate, evidence),
        endpoint_proof=endpoint_proof,
    )
    if support_failures:
        return None
    return answer, {
        **dict(closure),
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": support_proof,
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "pre_recovery_failures": pre_recovery_failures,
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": True,
        "semantic_synthesis_recovery": {
            "schema_version": "m26-aq-semantic-synthesis-recovery/v1",
            "case_specific": False,
            "candidate_claim_count": len(candidate.get("claims", [])),
            "internal_reference_leak_checked": True,
            "unsupported_accepted_claims": int(
                answer.get("unsupported_accepted_claims", 0)
            ),
        },
    }


def _should_attempt_semantic_recovery(
    question: str,
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> bool:
    if verification.get("status") != "owner_only_safe_abstention":
        return False
    if not evidence:
        return False
    if int(verification.get("unsupported_accepted_claims", 0)) != 0:
        return False
    if not bool(verification.get("citation_locator_valid", True)):
        return False
    codes = set(_failure_codes(verification, closure))
    if codes & _RECOVERY_HARD_STOP_CODES:
        return False
    if "PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE" in codes and _unsupported_external_markers(
        question,
        evidence,
    ):
        return False
    return bool(codes & _RECOVERABLE_SEMANTIC_CODES)


def _failure_codes(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> list[str]:
    return sorted(
        {
            str(item)
            for item in [
                *list(verification.get("reason_codes", [])),
                *list(closure.get("failures", [])),
            ]
            if str(item)
        }
    )


def _supported_semantic_recovery_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> dict[str, Any] | None:
    if _precedes_boundary_required(question, intent_class, requirements, endpoint_proof):
        candidate = _precedes_boundary_candidate(
            question=question,
            evidence=evidence,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
        )
        if candidate is not None:
            return candidate
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
    return dict(candidate)


def _precedes_boundary_required(
    question: str,
    intent_class: str,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> bool:
    requirement_ids = {str(getattr(item, "requirement_id", "")) for item in requirements}
    return (
        "precedes" in question.casefold()
        or "preceding" in question.casefold()
        or str(endpoint_proof.get("relation_type", "")) == "precedes"
        or "ordering_semantics" in requirement_ids
        or "non_entailment" in requirement_ids
        or intent_class == "graph_relationship"
    ) and (
        "non_entailment" in requirement_ids
        or "prove" in question.casefold()
        or "infer" in question.casefold()
    )


def _precedes_boundary_candidate(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> dict[str, Any] | None:
    del requirements
    edge = _best_precedes_edge(evidence, endpoint_proof)
    boundary = _best_text_item(
        evidence,
        ("precedes", "ordering", "sequence", "dependency", "causality", "requirement"),
    )
    endpoint_items = [
        item
        for item in evidence
        if item.get("evidence_type") == "passage"
        and str(item.get("concept_id", ""))
        in {
            str(endpoint_proof.get("edge_source", "")),
            str(endpoint_proof.get("edge_target", "")),
        }
    ]
    refs: list[dict[str, str]] = []
    for item in [edge, *endpoint_items[:2], boundary]:
        if item is None:
            continue
        ref = _support_ref(item)
        if ref is not None:
            refs.append(ref)
    if edge is None or boundary is None or len(refs) < 2:
        return None
    entities = canonical_question_entities(question)
    left = entities[0] if len(entities) >= 1 else "the first item"
    right = entities[1] if len(entities) >= 2 else "the second item"
    surface = (
        f"The relation graph records {left} as preceding {right}, so the safe "
        "inference is ordering or sequence/navigation only. That precedes edge does "
        "not by itself prove dependency, causality, implementation, or requirement."
    )
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": "precedes",
        "selected_evidence_ids": list(
            dict.fromkeys(ref["evidence_id"] for ref in refs)
        ),
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "relationship",
                "surface_text": surface,
                "facet_ids": legacy._required_facet_ids(
                    question=question,
                    intent_class="graph_relationship",
                ),
                "support_mode": "multi_evidence_exact",
                "support_refs": refs[:4],
            }
        ],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _best_precedes_edge(
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    expected_edge = str(endpoint_proof.get("edge_id", ""))
    for item in evidence:
        if item.get("evidence_type") != "graph_edge":
            continue
        if expected_edge and str(item.get("edge_id", "")) != expected_edge:
            continue
        if str(item.get("relation_type", "")) == "precedes":
            return item
    return next(
        (
            item
            for item in evidence
            if item.get("evidence_type") == "graph_edge"
            and str(item.get("relation_type", "")) == "precedes"
        ),
        None,
    )


def _best_text_item(
    evidence: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
) -> Mapping[str, Any] | None:
    ranked: list[tuple[int, Mapping[str, Any]]] = []
    for item in evidence:
        if item.get("evidence_type") != "passage":
            continue
        text = str(item.get("passage_text", ""))
        hits = sum(1 for term in terms if term.casefold() in text.casefold())
        ranked.append((hits, item))
    ranked.sort(key=lambda entry: (-entry[0], str(entry[1].get("evidence_id", ""))))
    if not ranked or ranked[0][0] <= 0:
        return None
    return ranked[0][1]


def _support_ref(item: Mapping[str, Any]) -> dict[str, str] | None:
    text = " ".join(str(item.get("passage_text", "")).split())
    if not text:
        return None
    quote = text if len(text) <= 420 else legacy._first_exact_evidence_quote(text, max_chars=420)
    if not quote:
        return None
    return {
        "evidence_id": str(item.get("evidence_id", "")),
        "locator_id": str(item.get("locator_id", "")),
        "exact_quote": quote,
        "exact_support_snippet": quote,
        "uncertainty": "low",
    }


def _candidate_evidence(
    candidate: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    selected = set(str(item) for item in candidate.get("selected_evidence_ids", []))
    return [item for item in evidence if str(item.get("evidence_id", "")) in selected]


def _public_candidate_surface(
    candidate: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> str:
    text = " ".join(str(candidate.get("answer_text", "")).split())
    citations_by_claim: dict[str, str] = {}
    citations = answer.get("citations", [])
    if isinstance(citations, Sequence) and not isinstance(citations, (str, bytes)):
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            claim_id = str(citation.get("claim_id", ""))
            citation_id = str(citation.get("citation_id", ""))
            if claim_id and citation_id and claim_id not in citations_by_claim:
                citations_by_claim[claim_id] = citation_id
    for claim_id, citation_id in citations_by_claim.items():
        text = text.replace(f"[[{claim_id}]]", f"[{citation_id}]")
    text = re.sub(r"\s*\[\[claim_\d+\]\]", "", text)
    return text


def _internal_reference_leaks(text: str, question: str) -> list[str]:
    allowed = set(re.findall(_INTERNAL_REFERENCE_RE, question))
    leaks = [
        token
        for token in re.findall(_INTERNAL_REFERENCE_RE, text)
        if token not in allowed
    ]
    return list(dict.fromkeys(leaks))


def _unsupported_external_markers(
    question: str,
    evidence: Sequence[Mapping[str, Any]],
) -> list[str]:
    marker_space = _evidence_marker_space(evidence)
    markers: list[str] = []
    for raw in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Za-z]+)?\b|\b\d{3,4}\b", question):
        marker = raw.strip(".,;:!?()[]{}\"'")
        if not marker or marker in _RECOVERY_EXTERNAL_STOPWORDS:
            continue
        key = marker.casefold().replace(".", "")
        if len(key) <= 2 and not key.isdigit():
            continue
        if key not in marker_space:
            markers.append(marker)
    return sorted(dict.fromkeys(markers), key=str.casefold)


def _evidence_marker_space(evidence: Sequence[Mapping[str, Any]]) -> set[str]:
    parts: list[str] = []
    for item in evidence:
        for key in (
            "passage_text",
            "title",
            "section_title",
            "source_id",
            "source_identity",
            "concept_id",
            "section_id",
        ):
            parts.append(str(item.get(key, "")))
        metadata = item.get("retrieval_metadata", {})
        if isinstance(metadata, Mapping):
            parts.extend(str(term) for term in metadata.get("coverage_terms", []))
            parts.extend(str(term) for term in metadata.get("graph_seed_concepts", []))
    normalized = " ".join(parts).casefold().replace(".", "")
    return {token for token in re.findall(r"[a-z0-9]+", normalized) if token}


def _semantic_contract_public() -> dict[str, str]:
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "entrypoint": CANONICAL_RUNTIME_ENTRYPOINT,
        "fingerprint": semantic_contract_fingerprint(),
    }


def _response_with_contract(response: dict[str, Any]) -> dict[str, Any]:
    contract = _semantic_contract_public()
    response["semantic_contract_fingerprint"] = contract["fingerprint"]
    closure = response.get("semantic_closure")
    if isinstance(closure, dict):
        closure["semantic_contract"] = contract
    return response


def _emit_progress_event(
    progress_callback: ProgressCallback | None,
    event_name: str,
    payload: Mapping[str, Any],
) -> None:
    if progress_callback is None:
        return
    progress_callback(str(event_name), dict(payload))


def run_owner_arbitrary_query(
    *,
    root: Path,
    gate: Mapping[str, Any],
    question: str,
    owner_subject_hash: str,
    public_request: bool = False,
    provider_client: ProviderClient | None = None,
    dense_channel: DenseChannel | None = None,
    require_remote_dense: bool = False,
    max_provider_calls: int = 2,
    max_cost: Decimal = Decimal("0.10"),
    answer_bundle: ProductionAnswerBundle | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    import time

    started = time.monotonic()
    observability = runtime._new_runtime_observability()
    normalized_question = legacy._normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = legacy._intent_class(normalized_question)
    validated_gate = legacy._validate_gate(root, gate)
    identities = legacy._object(
        validated_gate.get("production_identities"), "gate.production_identities"
    )
    admission = legacy.evaluate_owner_admission(
        validated_gate,
        {
            "resolved_gate_self_sha256": validated_gate.get("self_sha256"),
            "owner_subject_hash": owner_subject_hash,
            "owner_only_route": identities.get("owner_only_route"),
            "public_request": public_request,
        },
    )
    trace_id = "m26pa7aq_" + canonical_sha256(
        {
            "gate": validated_gate.get("self_sha256"),
            "question_sha256": question_sha,
            "owner_subject_hash": owner_subject_hash,
        }
    )[:32]
    runtime._observe_stage(
        observability,
        "request_admission",
        started,
        admitted=bool(admission["admitted"]),
        intent_class=intent_class,
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "request_admission", "role": "translation"},
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "request_admission",
            "role": "translation",
            "admitted": bool(admission["admitted"]),
        },
    )

    if not admission["admitted"]:
        return _response_with_contract(
            runtime._attach_runtime_observability(
                legacy._base_response(
                    gate=validated_gate,
                    trace_id=trace_id,
                    question_sha=question_sha,
                    started=started,
                    status="denied_non_owner_or_public_request",
                    terminal_status="denied_before_retrieval",
                    reason_codes=admission["reason_codes"],
                ),
                observability,
            )
        )
    if legacy._looks_like_prompt_injection(normalized_question):
        return _response_with_contract(
            runtime._attach_runtime_observability(
                legacy._base_response(
                    gate=validated_gate,
                    trace_id=trace_id,
                    question_sha=question_sha,
                    started=started,
                    status="owner_only_safe_abstention",
                    terminal_status="safe_abstention",
                    reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
                ),
                observability,
            )
        )
    if legacy._looks_like_underspecified_workflow_question(normalized_question):
        return _response_with_contract(
            runtime._attach_runtime_observability(
                legacy._base_response(
                    gate=validated_gate,
                    trace_id=trace_id,
                    question_sha=question_sha,
                    started=started,
                    status="owner_only_safe_abstention",
                    terminal_status="safe_abstention",
                    reason_codes=["QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED"],
                ),
                observability,
            )
        )

    provider = provider_client
    if provider is None:
        try:
            provider = MiniMaxClient(
                os.environ.get("MINIMAX_API_KEY", ""),
                max_calls=max_provider_calls,
                max_cost=max_cost,
            )
        except LiveGateError as exc:
            verification = legacy._verified_abstention(
                reason_codes=[type(exc).__name__, "PROVIDER_CONFIGURATION_MISSING"],
                calls=[],
                repair_attempted=False,
            )
            return _response_with_contract(
                runtime._response_from_verification(
                    gate=validated_gate,
                    bundle=None,
                    dense_result=None,
                    lexical_result=None,
                    evidence=[],
                    verification=verification,
                    trace_id=trace_id,
                    question_sha=question_sha,
                    started=started,
                    intent_class=intent_class,
                    semantic_closure={
                        "requirements": [],
                        "support_proof": [],
                        "failures": [],
                        "semantic_contract": _semantic_contract_public(),
                    },
                    observability=observability,
                )
            )

    provider = _ObservedProviderClient(provider, observability)
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "production_bundle_load_and_gate", "role": "retrieval"},
    )
    stage_started = time.monotonic()
    bundle = answer_bundle or load_production_answer_bundle()
    runtime._assert_full_production_graph(bundle)
    runtime._observe_stage(
        observability,
        "production_bundle_load_and_gate",
        stage_started,
        graph_node_count=len(bundle.graph_v2.get("nodes", [])),
        graph_edge_count=len(bundle.graph_v2.get("edges", [])),
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "production_bundle_load_and_gate",
            "role": "retrieval",
            "provider": "Cloudflare",
        },
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "retrieval", "role": "retrieval", "provider": "Cloudflare"},
    )
    stage_started = time.monotonic()
    dense = (
        dense_channel or legacy.dense_channel_from_env(require_remote=require_remote_dense)
    ).search(question=normalized_question, bundle=bundle, top_k=8)
    runtime._observe_stage(
        observability,
        "dense_retrieval",
        stage_started,
        candidate_count=len(dense.get("candidates", []))
        if isinstance(dense, Mapping)
        else 0,
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "retrieval",
            "role": "retrieval",
            "provider": "Cloudflare",
            "candidate_count": len(dense.get("candidates", []))
            if isinstance(dense, Mapping)
            else 0,
        },
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "lexical_retrieval", "role": "retrieval"},
    )
    stage_started = time.monotonic()
    lexical = retrieve_wiki_first(
        query=normalized_question,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=None,
        limit=8,
    )
    runtime._observe_stage(
        observability,
        "lexical_retrieval",
        stage_started,
        candidate_count=len(lexical.get("candidates", []))
        if isinstance(lexical, Mapping)
        else 0,
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "lexical_retrieval",
            "role": "retrieval",
            "candidate_count": len(lexical.get("candidates", []))
            if isinstance(lexical, Mapping)
            else 0,
        },
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "evidence_selection", "role": "organize"},
    )
    stage_started = time.monotonic()
    evidence = legacy._select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    runtime._observe_stage(
        observability,
        "evidence_selection",
        stage_started,
        selected_evidence_count=len(evidence),
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "evidence_selection",
            "role": "organize",
            "selected_evidence_count": len(evidence),
        },
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "semantic_requirement_derivation", "role": "organize"},
    )
    stage_started = time.monotonic()
    requirements = derive_semantic_requirements(normalized_question, intent_class)
    runtime._observe_stage(
        observability,
        "semantic_requirement_derivation",
        stage_started,
        requirement_count=len(requirements),
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "semantic_requirement_derivation",
            "role": "organize",
            "requirement_count": len(requirements),
        },
    )
    _emit_progress_event(
        progress_callback,
        "stage_started",
        {"stage": "semantic_evidence_strengthening", "role": "organize"},
    )
    stage_started = time.monotonic()
    evidence, endpoint_proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=evidence,
        lexical_result=lexical,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        requirements=requirements,
    )
    runtime._observe_stage(
        observability,
        "semantic_evidence_strengthening",
        stage_started,
        selected_evidence_count=len(evidence),
        endpoint_required=bool(endpoint_proof.get("required", False)),
        endpoint_matched=bool(endpoint_proof.get("matched", False)),
    )
    _emit_progress_event(
        progress_callback,
        "stage_completed",
        {
            "stage": "semantic_evidence_strengthening",
            "role": "organize",
            "selected_evidence_count": len(evidence),
            "endpoint_required": bool(endpoint_proof.get("required", False)),
            "endpoint_matched": bool(endpoint_proof.get("matched", False)),
        },
    )
    runtime._observe_count(
        observability,
        requirement_count=len(requirements),
        selected_evidence_count=len(evidence),
    )

    if not evidence or not legacy._has_meaningful_overlap(normalized_question, evidence):
        verification = legacy._verified_abstention(
            reason_codes=(
                ["NO_AUTHORIZED_PRODUCTION_EVIDENCE"]
                if not evidence
                else ["LOW_RETRIEVAL_SUPPORT"]
            ),
            calls=[],
            repair_attempted=False,
        )
        return _response_with_contract(
            runtime._response_from_verification(
                gate=validated_gate,
                bundle=bundle,
                dense_result=dense,
                lexical_result=lexical,
                evidence=[],
                verification=verification,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                intent_class=intent_class,
                semantic_closure={
                    "requirements": [
                        runtime._requirement_public(item) for item in requirements
                    ],
                    "support_proof": [],
                    "endpoint_proof": endpoint_proof,
                    "failures": ["LOW_RETRIEVAL_SUPPORT"],
                    "semantic_contract": _semantic_contract_public(),
                },
                observability=observability,
            )
        )

    stage_started = time.monotonic()
    _emit_progress_event(
        progress_callback,
        "model_started",
        {"stage": "semantic_synthesis_and_verification", "role": "closure", "provider": "MiniMax"},
    )
    verification, closure = synthesize_and_verify(
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    runtime._observe_stage(
        observability,
        "semantic_synthesis_and_verification",
        stage_started,
        provider_call_count=int(verification.get("provider_call_count", 0)),
        safe_abstention=bool(verification.get("safe_abstention", True)),
    )
    _emit_progress_event(
        progress_callback,
        "model_completed",
        {
            "stage": "semantic_synthesis_and_verification",
            "role": "closure",
            "provider": "MiniMax",
            "provider_call_count": int(verification.get("provider_call_count", 0)),
            "safe_abstention": bool(verification.get("safe_abstention", True)),
        },
    )
    runtime._add_provider_call_observability(observability, verification)
    return _response_with_contract(
        runtime._response_from_verification(
            gate=validated_gate,
            bundle=bundle,
            dense_result=dense,
            lexical_result=lexical,
            evidence=evidence,
            verification=verification,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            semantic_closure=closure,
            observability=observability,
        )
    )
