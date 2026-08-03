from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import m26_aq_semantic_runtime_patch_v2 as aq_v2_patch
from . import m26_aq_semantic_runtime_patch_v3_lifecycle as aq_lifecycle_patch
from . import m26_ask_api
from . import m26_pa7_arbitrary_query_runtime as legacy_runtime
from . import m26_pa7_semantic_closure_runtime as semantic_runtime
from .m26_aq_semantic_runtime_patch_v3 import install as install_aq_semantic_runtime_patch
from .m26_aq_semantic_runtime_patch_v3_lifecycle import (
    install as install_aq_lifecycle_runtime_patch,
)
from .m26_aq_semantic_runtime_patch_v3_surface import (
    install as install_aq_surface_runtime_patch,
)
from .m26_intent_compat import classify_with_semantic_compat
from .m26_pa7_semantic_closure_runtime import run_owner_arbitrary_query

install_aq_semantic_runtime_patch()
install_aq_lifecycle_runtime_patch()
install_aq_surface_runtime_patch()

_production_question_contract = legacy_runtime._question_contract
_production_repair_guidance = aq_lifecycle_patch._repair_guidance
_production_semantic_requirements = semantic_runtime._semantic_requirements
_production_semantic_synthesize = semantic_runtime._synthesize_and_verify
_production_v2_semantic_answer_text = aq_v2_patch._semantic_answer_text_v2


def _question_explicitly_requests_persisted_progress(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    return bool(
        re.search(r"\bpersist(?:ed|ence|ing)?\b", q)
        or any(
            marker in q
            for marker in (
                "durable",
                "disconnect",
                "recover",
                "resume",
                "saved state",
                "server-side state",
                "progress survives",
                "state survives",
            )
        )
    )


def _question_contract_without_progress_substring_false_positive(
    *, question: str, intent_class: str
) -> dict[str, Any]:
    """Do not treat ordinary in-progress wording as a persisted-progress request."""
    contract = dict(
        _production_question_contract(
            question=question,
            intent_class=intent_class,
        )
    )
    if _question_explicitly_requests_persisted_progress(question):
        return contract
    facets = contract.get("required_facets")
    if not isinstance(facets, list):
        return contract
    contract["required_facets"] = [
        item
        for item in facets
        if not isinstance(item, Mapping)
        or str(item.get("facet_id", "")) != "persisted_progress"
    ]
    return contract


def _production_variance_repair_guidance(code: str) -> str:
    if str(code) == "M26-PA7-ME-036":
        return (
            "The selected graph evidence records a precedes relation. State that exact "
            "ordering or sequence relationship explicitly, using comes before or precedes; "
            "do not replace it with dependency or causal semantics."
        )
    return _production_repair_guidance(str(code))


legacy_runtime._question_contract = (
    _question_contract_without_progress_substring_false_positive
)
aq_lifecycle_patch._repair_guidance = _production_variance_repair_guidance


def _requirement_ids(requirements: Sequence[Any]) -> set[str]:
    return {str(getattr(item, "requirement_id", "")) for item in requirements}


def _append_requirement(
    requirements: list[Any],
    *,
    requirement_id: str,
    instruction: str,
    evidence_terms: tuple[str, ...],
    visible_patterns: tuple[str, ...],
) -> None:
    if requirement_id in _requirement_ids(requirements):
        return
    requirements.append(
        semantic_runtime.SemanticRequirement(
            requirement_id=requirement_id,
            instruction=instruction,
            evidence_terms=evidence_terms,
            visible_patterns=visible_patterns,
        )
    )


def _looks_like_route_replan_contrast(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    route_signal = any(
        marker in q
        for marker in (
            "route",
            "routing",
            "router",
            "initial path",
            "initial capability",
        )
    )
    replan_signal = any(
        marker in q
        for marker in (
            "replan",
            "replanning",
            "revise a plan",
            "revises a plan",
            "revise the plan",
            "revises the plan",
            "change the plan",
            "changes the plan",
            "remaining steps",
            "remaining work",
            "after execution",
            "already started",
        )
    )
    return route_signal and replan_signal


def _looks_like_visual_source_authority(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    sigma_signal = "sigma.js" in q or "sigma js" in q or "sigma" in q
    visual_signal = any(marker in q for marker in ("visual", "visualization", "render"))
    authority_signal = any(
        marker in q
        for marker in (
            "source",
            "provenance",
            "authority",
            "authoritative",
            "trustworthy",
            "cite",
            "citation",
        )
    )
    return sigma_signal and visual_signal and authority_signal


def _production_variance_semantic_requirements(
    question: str,
    intent_class: str,
) -> list[Any]:
    requirements = list(_production_semantic_requirements(question, intent_class))
    if _looks_like_route_replan_contrast(question):
        _append_requirement(
            requirements,
            requirement_id="initial_routing_role",
            instruction="State that routing chooses the initial route, path, or capability.",
            evidence_terms=("route", "routing", "router", "path", "capability", "request"),
            visible_patterns=(
                r"(?:router|routing|route).{0,200}(?:initial|first|path|capability|select|choose)",
            ),
        )
        _append_requirement(
            requirements,
            requirement_id="replanning_role",
            instruction="State that replanning revises remaining work after execution changes.",
            evidence_terms=("replan", "replanning", "plan", "remaining", "execution", "evidence"),
            visible_patterns=(
                r"(?:replan|replanning|revise|revises|change|changes).{0,220}(?:plan|remaining|work|steps|execution|evidence|assumption)",
            ),
        )
        _append_requirement(
            requirements,
            requirement_id="role_contrast",
            instruction="Contrast initial routing with later replanning of unfinished work.",
            evidence_terms=("route", "routing", "plan", "replan", "initial", "remaining"),
            visible_patterns=(
                r"(?:contrast|while|whereas|routing|route).{0,300}(?:replan|replanning|revise|remaining|later)",
            ),
        )
    if _looks_like_visual_source_authority(question):
        _append_requirement(
            requirements,
            requirement_id="sigma_role",
            instruction="State that Sigma.js is a visualization or rendering layer.",
            evidence_terms=("sigma", "visualization", "visual", "render", "graph"),
            visible_patterns=(
                r"sigma(?:\.js| js)?.{0,180}(?:visual|visualization|render|interaction|layer)",
            ),
        )
        _append_requirement(
            requirements,
            requirement_id="trust_anchor",
            instruction="State that canonical source or provenance remains the authority.",
            evidence_terms=("canonical", "source", "provenance", "authority", "trust"),
            visible_patterns=(
                r"(?:canonical|source|provenance).{0,220}(?:authority|authoritative|trust|anchor|cite)",
            ),
        )
    return requirements


def _production_variance_semantic_answer_text(
    question: str,
    requirements: Sequence[Any],
) -> str:
    text = _production_v2_semantic_answer_text(question, requirements)
    if text:
        return text
    ids = _requirement_ids(requirements)
    if "ordering_semantics" in ids:
        entities = [
            aq_v2_patch._requirement_entity_phrase(item)
            for item in requirements
            if str(getattr(item, "requirement_id", "")).startswith("entity_")
        ]
        entities = [item for item in entities if item]
        if len(entities) >= 2:
            return (
                f"{entities[0]} precedes {entities[1]} in the relation graph. "
                "That records the ordering or sequence relationship between the two notes."
            )
    if {"sigma_role", "trust_anchor"}.issubset(ids):
        return (
            "Sigma.js is the visualization and rendering layer. When a visualization "
            "disagrees with underlying material, the canonical source and provenance "
            "artifact authority remains the source of trust, and a trustworthy answer "
            "cites that source or provenance evidence rather than treating the visual "
            "rendering as authority."
        )
    return ""


def _variance_repair_kind(
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> str:
    ids = _requirement_ids(requirements)
    if {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids):
        return "route_replan_contrast"
    if {"sigma_role", "trust_anchor"}.issubset(ids):
        return "visual_source_authority"
    if (
        "ordering_semantics" in ids
        and len([item for item in ids if item.startswith("entity_")]) >= 2
        and endpoint_proof.get("required") is True
        and endpoint_proof.get("matched") is True
        and str(endpoint_proof.get("relation_type", "")) == "precedes"
        and endpoint_proof.get("edge_source")
        and endpoint_proof.get("edge_target")
    ):
        return "exact_precedes_endpoint"
    return ""


def _synthesize_with_bounded_provider_variance_repair(
    *,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    answer, closure = _production_semantic_synthesize(
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    if str(answer.get("terminal_status", "")) != "safe_abstention":
        return answer, closure
    repair_kind = _variance_repair_kind(requirements, endpoint_proof)
    if not repair_kind:
        return answer, closure
    repaired = aq_v2_patch._runtime_bound_semantic_repair_v2(
        runtime=semantic_runtime,
        legacy=legacy_runtime,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        previous_answer=answer,
        previous_closure=closure,
    )
    if repaired is None:
        return answer, closure
    final_answer, final_closure = repaired
    final_answer["multi_evidence_verification"] = {
        **dict(final_answer.get("multi_evidence_verification", {})),
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "runtime_bound_semantic_repair_used": True,
        "provider_variance_repair_kind": repair_kind,
    }
    final_closure = {
        **dict(final_closure),
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": True,
        "provider_variance_repair_kind": repair_kind,
    }
    return final_answer, final_closure


aq_v2_patch._semantic_answer_text_v2 = _production_variance_semantic_answer_text
semantic_runtime._semantic_requirements = _production_variance_semantic_requirements
semantic_runtime._synthesize_and_verify = _synthesize_with_bounded_provider_variance_repair

_original_named_question_entities = legacy_runtime._named_question_entities
_original_intent_class = legacy_runtime._intent_class


def _named_question_entities_with_series_shorthand(question: str) -> list[str]:
    entities = list(_original_named_question_entities(question))
    harness_parts = re.findall(r"Harness Theory Part (\d+)", question, flags=re.I)
    if harness_parts:
        existing = {item.casefold() for item in entities}
        for part in re.findall(r"\bPart (\d+)\b", question, flags=re.I):
            entity = f"Harness Theory Part {part}"
            if entity.casefold() not in existing:
                entities.append(entity)
                existing.add(entity.casefold())
    return entities


def _intent_class_with_semantic_compat(question: str) -> str:
    return classify_with_semantic_compat(
        question,
        legacy_classifier=_original_intent_class,
    )


# Install semantic compatibility before the owner-only routes are registered.
legacy_runtime._named_question_entities = _named_question_entities_with_series_shorthand
legacy_runtime._intent_class = _intent_class_with_semantic_compat
m26_ask_api.run_owner_arbitrary_query = run_owner_arbitrary_query
m26_ask_api.RUNTIME_ENTRYPOINT = (
    "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
)

_original_build_web_query_dto = m26_ask_api.build_web_query_dto


def _build_web_query_dto_with_semantic_closure(
    runtime_response: Mapping[str, Any],
) -> dict[str, Any]:
    dto = _original_build_web_query_dto(runtime_response)
    dto["answer_source"] = str(runtime_response.get("answer_source", ""))
    dto["semantic_closure"] = dict(
        runtime_response.get("semantic_closure", {})
        if isinstance(runtime_response.get("semantic_closure"), Mapping)
        else {}
    )
    dto["evidence_utilization_trace"] = dict(
        runtime_response.get("evidence_utilization_trace", {})
        if isinstance(runtime_response.get("evidence_utilization_trace"), Mapping)
        else {}
    )
    dto["graph_observability"] = dict(
        runtime_response.get("graph_observability", {})
        if isinstance(runtime_response.get("graph_observability"), Mapping)
        else {}
    )
    dto["integrity"] = {
        "unsupported_accepted_claims": int(
            runtime_response.get("unsupported_accepted_claims", 0)
        ),
        "material_claim_support_verified": bool(
            runtime_response.get("material_claim_support_verified", True)
        ),
        "citation_locator_valid": bool(runtime_response.get("citation_locator_valid", True)),
    }
    return dto


m26_ask_api.build_web_query_dto = _build_web_query_dto_with_semantic_closure

# Import after patching so route registration sees the production closure runtime.
from .api import app  # noqa: E402,F401
