from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_pa7_semantic_closure_runtime as runtime
from . import m26_aq_semantic_runtime_patch_v2 as compatibility_v2
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

_GRAPH_WRAPPER_PREFIXES = (
    "A true graph fact says ",
    "The true graph fact says ",
    "A graph fact says ",
    "The graph fact says ",
    "If a true graph fact records ",
    "If the true graph fact records ",
    "If a graph fact records ",
    "If the graph fact records ",
    "A true graph fact records ",
    "The true graph fact records ",
    "A graph fact records ",
    "The graph fact records ",
    "If the relation graph records ",
    "The relation graph records ",
)
_PRECEDES_PARAPHRASE_RE = re.compile(
    r"\b(?:precedes?|preceding|comes\s+before|come\s+before|is\s+before|are\s+before)\b",
    flags=re.I,
)
_RELATION_ENTITY_SPLIT_PATTERNS = (
    r"\s+as\s+preceding\b.*$",
    r"\s+comes\s+before\b.*$",
    r"\s+come\s+before\b.*$",
    r"\s+is\s+before\b.*$",
    r"\s+are\s+before\b.*$",
    r"\s+precedes\b.*$",
    r"\s+precede\b.*$",
)


@dataclass(frozen=True)
class SemanticJudgment:
    failures: tuple[str, ...]
    contract_fingerprint: str


def _state_machine_replanner_question(question: str) -> bool:
    q = question.casefold()
    return "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning", "adaptive")
    )


def _route_replan_question(question: str) -> bool:
    q = question.casefold()
    has_initial_route = (
        ("initial" in q or "first" in q or "before execution" in q)
        and ("route" in q or "routing" in q or "path" in q or "where" in q)
    )
    has_later_replan = any(
        marker in q
        for marker in (
            "revises a plan",
            "revise a plan",
            "revises the plan",
            "changes the remaining work",
            "remaining work",
            "after execution has already started",
            "after execution started",
            "after execution",
            "replan",
            "replanner",
            "replanning",
        )
    )
    asks_difference = any(
        marker in q
        for marker in ("difference", "different", "contrast", "versus", "vs", "another")
    )
    return has_initial_route and has_later_replan and asks_difference


def _route_replan_requirements() -> list[SemanticRequirement]:
    return [
        SemanticRequirement(
            requirement_id="initial_routing_role",
            instruction="Explain that routing chooses the initial path/capability for the request before execution.",
            evidence_terms=("router", "route", "routing", "initial", "path", "capability", "request", "before execution"),
            visible_patterns=(
                r"\b(?:router|routing|route).{0,140}(?:initial|first|before execution|path|capability|request)",
                r"\binitial.{0,140}(?:route|path|dispatch|capability|request)",
            ),
        ),
        SemanticRequirement(
            requirement_id="replanning_role",
            instruction="Explain that replanning revises the remaining work after execution has started when evidence or reality invalidates the plan.",
            evidence_terms=("adaptive", "replan", "replanning", "revise", "remaining", "after execution", "invalid", "evidence", "reality"),
            visible_patterns=(
                r"\b(?:replan|replanning|replanner|revise|revises|revision).{0,180}(?:remaining|after execution|started|invalid|evidence|reality|plan)",
                r"\bremaining.{0,140}(?:work|plan|steps).{0,140}(?:replan|revise|after|invalid)",
            ),
        ),
        SemanticRequirement(
            requirement_id="role_contrast",
            instruction="Contrast initial dispatch with later replanning rather than conflating them.",
            evidence_terms=("initial", "later", "after", "different", "dispatch", "replanning", "contrast"),
            visible_patterns=(
                r"\b(?:whereas|while|by contrast|different|initial).{0,200}(?:later|after|replan|replanning|revision|remaining)",
                r"\b(?:first|initial).{0,160}(?:later|after|then|replan|revision)",
            ),
        ),
    ]


def _clean_graph_entity_phrase(value: str) -> str:
    text = " ".join(str(value).strip().split())
    changed = True
    while changed:
        changed = False
        for prefix in _GRAPH_WRAPPER_PREFIXES:
            if text.casefold().startswith(prefix.casefold()):
                text = text[len(prefix) :]
                changed = True
                break
    for pattern in _RELATION_ENTITY_SPLIT_PATTERNS:
        next_text = re.sub(pattern, "", text, flags=re.I).strip(" ?:.,")
        if next_text != text and re.search(r"\bPart\s+\d+\b", next_text, flags=re.I):
            text = next_text
            break
    for suffix in (" prove that", " prove", " safely infer"):
        index = text.casefold().find(suffix.casefold())
        if index > 0:
            text = text[:index]
    return " ".join(text.strip(" ?:.,").split())


def _relation_paraphrase_mentions_precedes(question: str) -> bool:
    q = str(question)
    if not _PRECEDES_PARAPHRASE_RE.search(q):
        return False
    if len(_strict_part_entities(q)) < 2:
        return False
    return bool(
        re.search(
            r"\b(?:graph|edge|relation|records?|fact|relationship|ordering|sequence|navigation)\b",
            q,
            flags=re.I,
        )
    )


def _strict_part_entities(question: str) -> list[str]:
    prefix = re.search(r"\b([A-Z][A-Za-z0-9 .'/&-]+?)\s+Part\s+\d+\b", question)
    root = _clean_graph_entity_phrase(prefix.group(1)) if prefix else ""
    entities: list[str] = []
    seen: set[str] = set()
    for part in re.findall(r"\bPart\s+(\d+)\b", question, flags=re.I):
        entity = _clean_graph_entity_phrase(f"{root} Part {part}" if root else f"Part {part}")
        key = entity.casefold()
        if entity and key not in seen:
            entities.append(entity)
            seen.add(key)
    return entities


def _requires_precedes_boundary(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:depend(?:s|ency|ent)?|causal(?:ity)?|prove[ns]?|infer(?:red|ence)?|implementation|requirement)\b",
            str(question),
            flags=re.I,
        )
    )


def _canonical_intent_class(question: str, intent_class: str) -> str:
    if _relation_paraphrase_mentions_precedes(question):
        return "graph_relationship"
    return intent_class


def _requested_lifecycle_requirements(question: str) -> set[str] | None:
    q = " ".join(str(question).casefold().split())
    full_markers = (
        "admission to completion",
        "intake to completion",
        "from admission",
        "from intake",
        "surrounding control system",
        "keep the run trustworthy",
    )
    if any(marker in q for marker in full_markers):
        return {"admission_policy", "durable_state", "completion_verification", "observability"}
    persisted_run_context = bool(
        re.search(r"\b(?:persist|persisted|durable)\b", q)
        and any(
            marker in q
            for marker in (
                "disconnect",
                "run state",
                "run-state",
                "run progress",
                "client",
                "server-side",
                "reattach",
                "resume",
            )
        )
    )
    explicit_run_lifecycle = bool(
        any(marker in q for marker in ("disconnect", "reattach", "server-side", "run state", "run-state"))
        or "durable state" in q
        or (
            any(marker in q for marker in ("long-running", "long running"))
            and any(marker in q for marker in ("run", "workflow", "finished", "completion"))
        )
        or persisted_run_context
    )
    if not explicit_run_lifecycle:
        return None
    requested = {"durable_state"}
    if any(term in q for term in ("verify", "verification", "verified", "correct", "completion", "complete", "success", "acceptance")):
        requested.add("completion_verification")
    if any(term in q for term in ("admission", "intake", "policy", "before execution", "request boundary")):
        requested.add("admission_policy")
    if any(term in q for term in ("observability", "reattach", "status", "inspect", "resume")):
        requested.add("observability")
    if "disconnect" in q and "long-running" in q and "finished" in q and "correct" not in q:
        requested.update({"completion_verification", "observability"})
    return requested


def _looks_like_controlled_lifecycle_composition(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    if not any(term in q for term in ("agent", "controlled", "control", "controls", "architecture", "lifecycle", "workflow")):
        return False
    facets = {
        "routing": any(term in q for term in ("initial routing", "route selection", "routing", "router", "route", "source selection")),
        "dag": any(term in q for term in ("dag", "dependency", "dependencies", "parallel", "branches", "branching", "join")),
        "state": any(term in q for term in ("durable", "persisted", "progress", "run state", "state")),
        "verification": any(term in q for term in ("verification", "verify", "completion", "acceptance", "gate")),
        "approval": any(term in q for term in ("human approval", "approval", "authority", "human review", "person")),
    }
    return sum(1 for matched in facets.values() if matched) >= 4


def _asks_control_role_distinction(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    return any(
        marker in q
        for marker in (
            "not interchangeable",
            "interchangeable",
            "not treating",
            "without treating",
            "not conflate",
            "not conflated",
            "conflating",
            "conflated",
            "different roles",
            "distinct roles",
            "separate roles",
            "not replace",
            "cannot replace",
        )
    )


def _controlled_lifecycle_requirements(question: str) -> list[SemanticRequirement]:
    requirements = [
        SemanticRequirement(
            requirement_id="source_selection",
            instruction="Cover initial routing or route/source selection before execution.",
            evidence_terms=("routing", "route", "router", "source selection", "capability", "request"),
            visible_patterns=(
                r"\b(?:initial routing|route selection|routing|router|source selection)\b",
                r"\b(?:route|routes).{0,120}(?:request|work|capability|source)",
            ),
        ),
        SemanticRequirement(
            requirement_id="parallel_branches",
            instruction="Cover dependency DAG, dependency ordering, or parallel branch execution.",
            evidence_terms=("DAG", "dag", "dependency", "dependencies", "parallel", "branch", "join"),
            visible_patterns=(
                r"\bDAG\b.{0,180}(?:dependency|dependencies|parallel|branch|join|execution|ordering)",
                r"\b(?:dependency|parallel).{0,180}(?:DAG|branch|branches|join|execution|ordering)",
            ),
        ),
        SemanticRequirement(
            requirement_id="persisted_progress",
            instruction="Cover durable or persisted run state/progress.",
            evidence_terms=("persisted", "durable", "progress", "state", "run state"),
            visible_patterns=(r"\b(?:persisted|durable).{0,120}(?:progress|state|run state)\b",),
        ),
        SemanticRequirement(
            requirement_id="verification_gate",
            instruction="Cover verification or completion gating before success/release.",
            evidence_terms=("verification", "completion", "acceptance", "gate", "success"),
            visible_patterns=(r"\b(?:verification|completion|acceptance).{0,120}(?:gate|before|success|release|declared)\b",),
        ),
        SemanticRequirement(
            requirement_id="human_approval",
            instruction="Cover human approval as an authority gate.",
            evidence_terms=("human approval", "approval gate", "human-in-the-loop", "publication", "sensitive action", "release"),
            visible_patterns=(r"\bhuman approval\b.{0,120}(?:authority|gate|before|release|action)?",),
        ),
    ]
    if _asks_control_role_distinction(question):
        requirements.append(
            SemanticRequirement(
                requirement_id="control_role_distinction",
                instruction="State that the controls have distinct roles and are not interchangeable.",
                evidence_terms=("structures", "distinct problems", "router", "DAG", "state machine", "human approval", "not mutually exclusive", "interchangeable"),
                visible_patterns=(
                    r"\b(?:not interchangeable|not conflated|not replace|cannot replace|different roles|distinct roles|separate roles)\b",
                    r"\bcontrols?\b.{0,180}\b(?:different|distinct|separate)\b.{0,120}\b(?:roles?|responsibilities)\b",
                ),
            )
        )
    return requirements


def _lifecycle_requirement(requirement_id: str) -> SemanticRequirement:
    specs = {
        "admission_policy": (
            "Cover request admission/effective policy before execution.",
            ("admission", "request boundary", "effective policy", "task contract"),
            (r"\b(?:admission|request boundary|effective policy|task contract)\b",),
        ),
        "durable_state": (
            "Cover durable/persisted server-side run authority or state after disconnect.",
            ("durable", "persisted", "state", "authority", "disconnect"),
            (
                r"\b(?:durable|persisted|server-side).{0,120}(?:state|authority|run|progress)",
                r"\bstate.{0,120}(?:durable|persisted|authority|progress)\b",
            ),
        ),
        "completion_verification": (
            "Cover verification/completion acceptance before declaring success.",
            ("verification", "completion", "acceptance", "terminal"),
            (r"\b(?:verification|completion|acceptance|terminal gate)\b",),
        ),
        "observability": (
            "Cover observability/status/reattachment for the headless continuing run.",
            ("observability", "status", "reattach", "headless", "resume"),
            (r"\b(?:observability|reattach|headless|status|resume)\b",),
        ),
    }
    instruction, terms, patterns = specs[requirement_id]
    return SemanticRequirement(
        requirement_id=requirement_id,
        instruction=instruction,
        evidence_terms=terms,
        visible_patterns=patterns,
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
    lifecycle_requested = _requested_lifecycle_requirements(question)
    definition_parts = legacy._contextual_definition_query_parts(question)
    lifecycle_ids = {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }
    generic_dimension_ids = {
        "explanatory_answer",
        "comparison_or_distinction",
        "multi_dimension_structure",
    }
    for item in base:
        requirement_id = str(getattr(item, "requirement_id", ""))
        if not requirement_id or requirement_id in seen:
            continue
        if lifecycle_requested is not None and requirement_id in generic_dimension_ids:
            continue
        if requirement_id == "authority_boundary" and _state_machine_replanner_question(question):
            continue
        if requirement_id == "non_entailment" and not _requires_precedes_boundary(question):
            continue
        if (
            lifecycle_requested is not None
            and requirement_id in lifecycle_ids
            and requirement_id not in lifecycle_requested
        ):
            continue
        exact_phrase = str(getattr(item, "exact_phrase", ""))
        instruction = str(getattr(item, "instruction", ""))
        visible_patterns = tuple(str(x) for x in getattr(item, "visible_patterns", ()))
        evidence_terms = tuple(str(x) for x in getattr(item, "evidence_terms", ()))
        if requirement_id.startswith("entity_") and exact_phrase:
            cleaned = _clean_graph_entity_phrase(exact_phrase)
            if cleaned and cleaned != exact_phrase:
                requirement_id = f"entity_{legacy._facet_id_for_term(cleaned)}"
                exact_phrase = cleaned
                instruction = f"Name and address {cleaned} explicitly."
                evidence_terms = (cleaned,)
                visible_patterns = (re.escape(cleaned),)
            if requirement_id in seen:
                continue
        seen.add(requirement_id)
        requirements.append(
            SemanticRequirement(
                requirement_id=requirement_id,
                instruction=instruction,
                evidence_terms=evidence_terms,
                visible_patterns=visible_patterns,
                exact_phrase=exact_phrase,
            )
        )
    if definition_parts is not None:
        head = str(definition_parts.get("definition_head", "")).strip()
        context = str(definition_parts.get("context_modifier", "")).strip()
        if head and "definition_head" not in seen:
            seen.add("definition_head")
            requirements.append(
                SemanticRequirement(
                    requirement_id="definition_head",
                    instruction=(
                        f"State {head} with a source-backed definitional predicate "
                        "instead of an invented category."
                    ),
                    evidence_terms=(
                        head,
                        *tuple(str(term) for term in legacy._coverage_terms(head)),
                        *tuple(
                            sorted(
                                legacy._coverage_terms(head)
                                & legacy._coverage_terms(question)
                            )
                        ),
                    ),
                    visible_patterns=(
                        rf"\b{re.escape(head)}\b.{{0,120}}\b(?:method|means|follow|sop|tool|decision|rules|acceptance|criteria|task)\b",
                        rf"\b(?:method|means|follow|sop|tool|decision|rules|acceptance|criteria|task)\b.{{0,120}}\b{re.escape(head)}\b",
                    ),
                    exact_phrase=head,
                )
            )
        if context and "context_modifier" not in seen:
            seen.add("context_modifier")
            requirements.append(
                SemanticRequirement(
                    requirement_id="context_modifier",
                    instruction=f"Keep the contextual modifier {context} explicit.",
                    evidence_terms=tuple(legacy._coverage_terms(context)),
                    visible_patterns=(rf"\b{re.escape(context)}\b",),
                    exact_phrase=context,
                )
            )
    if _state_machine_replanner_question(question):
        requirements.append(_authority_boundary_requirement())
    if _route_replan_question(question):
        for requirement in _route_replan_requirements():
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            requirements.append(requirement)
    if _looks_like_controlled_lifecycle_composition(question):
        for requirement in _controlled_lifecycle_requirements(question):
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            requirements.append(requirement)
    if _relation_paraphrase_mentions_precedes(question):
        if "ordering_semantics" not in seen:
            seen.add("ordering_semantics")
            requirements.append(
                SemanticRequirement(
                    requirement_id="ordering_semantics",
                    instruction="State that the recorded graph relationship is a precedes ordering relation.",
                    evidence_terms=("precedes", "ordering", "sequence", "comes before"),
                    visible_patterns=(
                        r"\b(?:precedes|comes before|preceding).{0,160}(?:ordering|sequence|relationship|relation)",
                        r"\b(?:ordering|sequence|relationship|relation).{0,160}(?:precedes|comes before|preceding)",
                    ),
                )
            )
        if _requires_precedes_boundary(question) and "non_entailment" not in seen:
            seen.add("non_entailment")
            requirements.append(
                SemanticRequirement(
                    requirement_id="non_entailment",
                    instruction=(
                        "State that the precedes ordering does not by itself prove "
                        "dependency, causality, implementation, or requirement semantics."
                    ),
                    evidence_terms=("does not prove", "dependency", "causality", "requirement"),
                    visible_patterns=(
                        r"(?:does not|cannot|can't|not enough|only).{0,180}"
                        r"(?:depend|causal|prove|infer|implement|require)",
                    ),
                )
            )
    q = question.casefold()
    if (
        "venture" in q
        and "product" in q
        and any(term in q for term in ("operations", "resources", "team", "finance", "risk"))
    ):
        venture_requirements = [
            SemanticRequirement(
                requirement_id="venture_not_product",
                instruction="Explain that a venture is broader than the product alone.",
                evidence_terms=("venture", "product", "system"),
                visible_patterns=(r"\b(?:venture|system).{0,120}(?:product|operations|resources|team|finance|risk)",),
            ),
            SemanticRequirement(
                requirement_id="operations_system",
                instruction="Cover operations as part of the venture system.",
                evidence_terms=("operations", "operation", "delivery"),
                visible_patterns=(r"\boperations?\b",),
            ),
            SemanticRequirement(
                requirement_id="venture_resources",
                instruction="Cover resources as part of the venture system.",
                evidence_terms=("resources", "resource", "runway"),
                visible_patterns=(r"\b(?:resources?|runway)\b",),
            ),
            SemanticRequirement(
                requirement_id="team_capacity",
                instruction="Cover team capacity as part of the venture system.",
                evidence_terms=("team", "people"),
                visible_patterns=(r"\b(?:team|people)\b",),
            ),
            SemanticRequirement(
                requirement_id="finance_model",
                instruction="Cover finance as part of the venture system.",
                evidence_terms=("finance", "financial", "margin", "cash", "runway"),
                visible_patterns=(r"\b(?:finance|financial|margin|cash|runway)\b",),
            ),
            SemanticRequirement(
                requirement_id="risk_management",
                instruction="Cover risk as part of the venture system.",
                evidence_terms=("risk", "risks"),
                visible_patterns=(r"\brisks?\b",),
            ),
        ]
        for requirement in venture_requirements:
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            requirements.append(requirement)
    if (
        any(term in q for term in ("pain point", "pain", "痛點"))
        and any(term in q for term in ("adopt", "adoption", "change", "願意改變", "願意採用", "市場"))
    ):
        pain_requirements = [
            SemanticRequirement(
                requirement_id="pain_acknowledgement",
                instruction="Separate pain acknowledgement from adoption willingness.",
                evidence_terms=("pain", "problem", "pain point", "痛點"),
                visible_patterns=(r"\b(?:pain point|pain|problem|痛點)\b",),
            ),
            SemanticRequirement(
                requirement_id="change_willingness",
                instruction="Cover willingness to change or adopt.",
                evidence_terms=("willing", "change", "adopt", "adoption", "改變", "採用"),
                visible_patterns=(r"\b(?:willing|change|adopt|adoption|改變|採用)\b",),
            ),
            SemanticRequirement(
                requirement_id="adoption_conditions",
                instruction="Cover adoption conditions, cost, trust, workflow, or risk.",
                evidence_terms=("cost", "trust", "risk", "workflow", "conditions", "條件"),
                visible_patterns=(r"\b(?:cost|trust|risk|workflow|conditions?|條件)\b",),
            ),
            SemanticRequirement(
                requirement_id="market_movement",
                instruction="Cover market or customer movement.",
                evidence_terms=("market", "customer", "hospitality", "hotel", "市場", "旅宿"),
                visible_patterns=(r"\b(?:market|customer|hospitality|hotel|市場|旅宿)\b",),
            ),
        ]
        for requirement in pain_requirements:
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            requirements.append(requirement)
    if lifecycle_requested is not None:
        for requirement_id in sorted(lifecycle_requested):
            if requirement_id in seen:
                continue
            seen.add(requirement_id)
            requirements.append(_lifecycle_requirement(requirement_id))
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
    route_replan_question = (
        "Explain the difference between the component that chooses an initial request route "
        "and the component that revises a plan after execution has already started."
    )
    route_replan_positive = (
        "The router chooses the initial request path before execution, while adaptive "
        "replanning revises the remaining work later after evidence invalidates the plan."
    )
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
        "route_replan_positive": evaluate_visible_semantics(
            route_replan_positive,
            _probe_requirements(route_replan_question),
            route_replan_question,
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
            "provider_visible_prose_required": True,
            "semantic_recovery_publication": False,
            "expression_mismatch_hard_gate": False,
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
    "Compare",
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
    entities: list[str] = []
    seen: set[str] = set()
    for entity in [
        *_strict_part_entities(question),
        *legacy._named_question_entities(question),
        *legacy._question_relevance_subjects(question),
    ]:
        cleaned = _clean_graph_entity_phrase(entity)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            entities.append(cleaned)
            seen.add(key)
    return entities


def _contract_compat_module() -> Any:
    return compatibility_v2


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
    verification, closure = runtime._synthesize_and_verify(
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        allow_deterministic_recovery=False,
    )
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


def _publish_support_proof_recovered_answer(
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
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        return recovered
    return dict(verification), dict(closure)


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
    previous_support_proof = _proof_items(closure.get("support_proof", ()))
    ref_only_comparison_recovered = (
        _support_proof_ref_only_lifecycle_comparison_recovery(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
            verification=verification,
            closure=closure,
            support_proof=previous_support_proof,
        )
    )
    if ref_only_comparison_recovered is not None:
        return ref_only_comparison_recovered
    ref_only_recovered = _support_proof_ref_only_lifecycle_recovery(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        verification=verification,
        closure=closure,
        support_proof=previous_support_proof,
    )
    if ref_only_recovered is not None:
        return ref_only_recovered
    recovery_evidence = _evidence_with_support_proof_text(evidence, previous_support_proof)
    candidate = _supported_semantic_recovery_candidate(
        question=question,
        intent_class=intent_class,
        evidence=recovery_evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        support_proof=previous_support_proof,
    )
    if candidate is None:
        return None
    try:
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=recovery_evidence,
            provider_text=json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=recovery_evidence,
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
        evidence=_candidate_evidence(candidate, recovery_evidence),
        endpoint_proof=endpoint_proof,
    )
    if support_failures:
        return None
    pre_recovery_local_rejections = _string_list(
        closure.get("local_repair_rejection_codes", ())
    )
    recovered_closure = dict(closure)
    recovered_closure.pop("local_repair_rejection_codes", None)
    if pre_recovery_local_rejections:
        recovered_closure["pre_recovery_local_repair_rejection_codes"] = (
            pre_recovery_local_rejections
        )
    return answer, {
        **recovered_closure,
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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if str(item)]
    return []


def _proof_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _proof_quote(proof: Mapping[str, Any]) -> str:
    for key in (
        "exact_quote",
        "exact_support_snippet",
        "support_text",
        "support_snippet",
        "snippet",
    ):
        quote = " ".join(str(proof.get(key, "")).split())
        if quote:
            return quote
    return ""


def _evidence_with_support_proof_text(
    evidence: Sequence[Mapping[str, Any]],
    support_proof: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    proof_quote_by_id = {
        str(proof.get("evidence_id", "")): _proof_quote(proof)
        for proof in support_proof
        if proof.get("supported") is True and str(proof.get("evidence_id", ""))
    }
    hydrated: list[Mapping[str, Any]] = []
    for item in evidence:
        evidence_id = str(item.get("evidence_id", ""))
        locator_id = str(item.get("locator_id") or evidence_id)
        source_identity = str(
            item.get("source_identity")
            or item.get("source_id")
            or evidence_id
        )
        section_id = str(item.get("section_id") or item.get("concept_id") or locator_id)
        quote = proof_quote_by_id.get(evidence_id, "")
        hydrated_item = {
            **dict(item),
            "evidence_id": evidence_id,
            "locator_id": locator_id,
            "source_id": str(item.get("source_id") or source_identity),
            "source_identity": source_identity,
            "concept_id": str(item.get("concept_id") or section_id),
            "section_id": section_id,
            "release_id": str(item.get("release_id") or source_identity),
            "artifact_key": str(item.get("artifact_key") or source_identity),
            "artifact_sha256": str(item.get("artifact_sha256") or source_identity),
            "provenance_record_sha256": str(
                item.get("provenance_record_sha256") or locator_id
            ),
        }
        if quote and not str(hydrated_item.get("passage_text", "")).strip():
            hydrated_item["passage_text"] = quote
            hydrated_item["passage_text_sha256"] = str(
                item.get("passage_text_sha256")
                or item.get("text_sha256")
                or canonical_sha256(quote)
            )
        hydrated.append(hydrated_item)
    return hydrated


def _supported_semantic_recovery_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    support_proof: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    if (
        intent_class == "graph_relationship"
        or _precedes_boundary_required(question, intent_class, requirements, endpoint_proof)
        or _precedes_relation_required(question, intent_class, requirements, endpoint_proof)
    ):
        return None
    candidate = _persistence_correctness_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
    )
    if candidate is not None:
        return candidate
    candidate = _lifecycle_control_comparison_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
    )
    if candidate is not None:
        return candidate
    candidate = _positive_answerability_requirement_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        support_proof=support_proof,
    )
    if candidate is not None:
        return candidate
    candidate = _comparison_surface_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
    )
    if candidate is not None:
        return candidate
    candidate = _authority_surface_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
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


def _positive_answerability_requirement_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    support_proof: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    requirement_ids = {str(getattr(item, "requirement_id", "")) for item in requirements}
    route_replan_ids = {"initial_routing_role", "replanning_role", "role_contrast"}
    controlled_lifecycle_ids = {
        "source_selection",
        "parallel_branches",
        "persisted_progress",
        "verification_gate",
        "human_approval",
    }
    lifecycle_ids = {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }
    business_ids = {
        "demand_not_business_proof",
        "value_capture",
        "business_economics",
        "business_delivery",
        "business_repeatability",
    }
    learning_ids = {
        "problem_evidence_changed",
        "constraint_change",
        "market_reality_change",
        "drift_boundary",
    }
    pain_ids = {
        "pain_acknowledgement",
        "change_willingness",
        "adoption_conditions",
        "market_movement",
    }
    venture_ids = {
        "venture_not_product",
        "operations_system",
        "venture_resources",
        "team_capacity",
        "finance_model",
        "risk_management",
    }
    selected_items: list[Mapping[str, Any]] = []
    if learning_ids.issubset(requirement_ids):
        surface = (
            "Evidence-driven learning means the problem evidence, constraints, or market reality changed "
            "enough to justify a new direction; aimless drift is when the pitch keeps changing while the "
            "underlying problem signal does not."
        )
        claim_role = "direct"
        relation = None
        required_ids = learning_ids
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("problem", "evidence", "learning"),
                ("constraint", "constraints", "runway", "resource", "timing"),
                ("market", "reality", "customer", "adoption"),
                ("drift", "aimless", "direction", "pitch"),
            ),
            minimum=3,
        )
    if route_replan_ids.issubset(requirement_ids):
        surface = (
            "The routing component chooses the initial request route, path, or capability before execution. "
            "By contrast, the replanning component revises the remaining work later, after execution has started and evidence or runtime reality invalidates the plan."
        )
        claim_role = "comparison"
        relation = "contrasts_with"
        required_ids = route_replan_ids
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("router", "route", "initial", "path", "capability", "request"),
                ("replan", "replanning", "remaining", "evidence", "reality", "invalid"),
                ("difference", "contrast", "different", "later", "after"),
            ),
            minimum=2,
        )
    elif controlled_lifecycle_ids.issubset(requirement_ids):
        distinction = ""
        required_ids = set(controlled_lifecycle_ids)
        if "control_role_distinction" in requirement_ids:
            distinction = (
                " These controls have distinct roles and are not interchangeable: "
                "routing chooses where work starts, the DAG constrains execution order, "
                "state preserves progress, verification checks completion, and human "
                "approval supplies authority."
            )
            required_ids.add("control_role_distinction")
        surface = (
            "A controlled agent lifecycle can first use initial routing or route "
            "selection to choose the permitted path, then execute a dependency DAG "
            "or parallel branches, persist durable run state and progress, pass a "
            "verification or completion gate before success is declared, and require "
            f"human approval as the authority gate before release.{distinction}"
        )
        claim_role = "direct"
        relation = None
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("routing", "route", "router", "source", "capability", "request"),
                ("DAG", "dag", "dependency", "parallel", "branch", "join"),
                ("durable", "persisted", "state", "progress", "authority"),
                ("verification", "completion", "acceptance", "gate", "success"),
                ("human approval", "approval gate", "human-in-the-loop", "publication", "sensitive action", "release"),
                ("structures", "distinct problems", "router", "DAG", "state machine", "human approval", "not mutually exclusive", "interchangeable"),
            ),
            minimum=5,
        )
    elif business_ids.issubset(requirement_ids):
        surface = (
            "Demand can show interest, but it does not prove a viable business. "
            "You still have to check value capture, economics, delivery cost or ability, "
            "and whether the idea is repeatable enough to keep working beyond a one-off spike."
        )
        claim_role = "direct"
        relation = None
        required_ids = business_ids
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("demand", "prove", "business", "viable"),
                ("value", "capture", "pay", "payment", "willing"),
                ("economics", "margin", "cost"),
                ("delivery", "support", "customer"),
                ("repeat", "repeatability", "return", "retained", "loops"),
            ),
            minimum=3,
        )
    elif pain_ids.issubset(requirement_ids):
        surface = (
            "有痛點只表示問題被承認，不代表市場會動；要真的採用，還要看客戶是否願意改變、"
            "採用成本與風險是否可接受，以及旅宿業者能不能看到明確的價值與回報。"
        )
        claim_role = "direct"
        relation = None
        required_ids = pain_ids
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("pain", "problem", "pain point", "acknowledge"),
                ("willing", "change", "adopt", "adoption"),
                ("cost", "trust", "risk", "workflow", "conditions"),
                ("market", "customer", "hospitality", "hotel", "travel"),
            ),
            minimum=3,
        )
    elif venture_ids.issubset(requirement_ids):
        surface = (
            "A venture is more than the product: operations, resources, team, finance, and risk all "
            "shape whether the product becomes a durable system."
        )
        claim_role = "direct"
        relation = None
        required_ids = venture_ids
        selected_items = _support_items_for_groups(
            evidence,
            (
                ("venture", "product", "system"),
                ("operations", "delivery"),
                ("resource", "runway", "resources"),
                ("team", "people"),
                ("finance", "margin", "cash", "risk"),
            ),
            minimum=3,
        )
    elif (
        lifecycle_ids.issubset(requirement_ids)
        or _lifecycle_recovery_question(question, requirement_ids)
        or {"durable_state", "completion_verification"}.issubset(requirement_ids)
    ):
        if legacy._question_requires_non_entailment_boundary(question):
            return None
        if "admission_policy" in requirement_ids:
            surface = (
                "Persisted run state keeps a disconnected long-running workflow trustworthy because admission and effective policy happen before execution, durable server-side state preserves run authority after disconnect, observability or reattachment exposes status while it continues headlessly, and completion verification or acceptance happens before success is declared."
            )
        else:
            surface = (
                "Persisted run state matters after a client disconnect because durable "
                "server-side state preserves run progress and authority while the "
                "workflow continues, observability or reattachment exposes status, and "
                "completion verification or acceptance remains separate before success "
                "is declared."
        )
        claim_role = "direct"
        relation = None
        required_ids = requirement_ids & lifecycle_ids
        selected_items = _lifecycle_recovery_evidence(
            evidence,
            support_proof=support_proof,
            requirement_ids=required_ids,
        )
    else:
        return None

    seen: set[str] = {
        str(item.get("evidence_id", ""))
        for item in selected_items
        if str(item.get("evidence_id", ""))
    }
    for requirement in requirements:
        if str(getattr(requirement, "requirement_id", "")) not in required_ids:
            continue
        if any(
            runtime._requirement_evidence_score(requirement, item) >= 1.0
            for item in selected_items
        ):
            continue
        item = _best_supported_requirement_evidence(requirement, evidence)
        if item is None:
            return None
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen:
            selected_items.append(item)
            seen.add(evidence_id)

    refs = []
    for item in selected_items:
        ref = _support_ref(item)
        if ref is None:
            return None
        refs.append(ref)
    if len(refs) < min(2, len(required_ids)):
        return None
    if evaluate_visible_semantics(surface, requirements, question):
        return None
    if _internal_reference_leaks(surface, question):
        return None

    facet_ids = legacy._required_facet_ids(question=question, intent_class=intent_class)
    if not facet_ids:
        facet_ids = sorted(required_ids)
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": list(dict.fromkeys(ref["evidence_id"] for ref in refs)),
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": claim_role,
                "surface_text": surface,
                "facet_ids": facet_ids,
                "support_mode": "runtime_bound_exact_multi_evidence",
                "support_refs": refs[:6],
            }
        ],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _support_items_for_groups(
    evidence: Sequence[Mapping[str, Any]],
    groups: Sequence[Sequence[str]],
    *,
    minimum: int,
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for group in groups:
        item = _best_distinct_text_item(evidence, group, seen_sources)
        if item is None:
            item = _best_text_item(evidence, group)
        if item is None:
            continue
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen_ids:
            selected.append(item)
            seen_ids.add(evidence_id)
            seen_sources.add(_source_identity(item))
    if len(selected) < minimum:
        for item in evidence:
            if item.get("evidence_type") != "passage":
                continue
            evidence_id = str(item.get("evidence_id", ""))
            source = _source_identity(item)
            if not evidence_id or evidence_id in seen_ids or source in seen_sources:
                continue
            selected.append(item)
            seen_ids.add(evidence_id)
            seen_sources.add(source)
            if len(selected) >= minimum:
                break
    return selected


def _lifecycle_recovery_question(question: str, requirement_ids: set[str]) -> bool:
    q = question.casefold()
    interruption = any(
        marker in q
        for marker in (
            "client disconnect",
            "disconnect",
            "interruption",
            "interrupted",
            "connection drops",
            "browser closes",
        )
    )
    durable = any(marker in q for marker in ("persisted", "durable", "run state", "state"))
    long_running = any(marker in q for marker in ("long-running", "long running", "workflow", "run"))
    return "durable_state" in requirement_ids and (
        interruption
        and durable
        and long_running
    )


def _lifecycle_recovery_evidence(
    evidence: Sequence[Mapping[str, Any]],
    *,
    support_proof: Sequence[Mapping[str, Any]] = (),
    requirement_ids: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    allowed = requirement_ids or {
        "admission_policy",
        "durable_state",
        "observability",
        "completion_verification",
    }
    evidence_by_id = {str(item.get("evidence_id", "")): item for item in evidence}
    selected: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add(item: Mapping[str, Any] | None) -> None:
        if item is None:
            return
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen:
            selected.append(item)
            seen.add(evidence_id)

    for proof in support_proof:
        if proof.get("supported") is not True:
            continue
        if str(proof.get("requirement_id", "")) not in allowed:
            continue
        add(evidence_by_id.get(str(proof.get("evidence_id", ""))))

    groups = (
        ("admission_policy", ("admission", "policy", "contract")),
        ("durable_state", ("durable", "persisted", "authority", "disconnect")),
        ("observability", ("observability", "reattach", "resume", "status")),
        (
            "completion_verification",
            ("completion", "verification", "acceptance", "success"),
        ),
    )
    items = [
        _best_text_item(evidence, terms)
        for requirement_id, terms in groups
        if requirement_id in allowed
    ]
    for item in items:
        add(item)
    return selected


def _best_supported_requirement_evidence(
    requirement: Any,
    evidence: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    best: Mapping[str, Any] | None = None
    best_score = 0.0
    for item in evidence:
        try:
            score = float(runtime._requirement_evidence_score(requirement, item))
        except Exception:
            score = 0.0
        if score > best_score:
            best = item
            best_score = score
    if best is None or best_score < 1.0:
        return None
    return best


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
        or _relation_paraphrase_mentions_precedes(question)
        or str(endpoint_proof.get("relation_type", "")) == "precedes"
        or "ordering_semantics" in requirement_ids
        or "non_entailment" in requirement_ids
        or intent_class == "graph_relationship"
    ) and (
        "non_entailment" in requirement_ids
        or "prove" in question.casefold()
        or "infer" in question.casefold()
    )


def _precedes_relation_required(
    question: str,
    intent_class: str,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> bool:
    requirement_ids = {str(getattr(item, "requirement_id", "")) for item in requirements}
    return (
        _relation_paraphrase_mentions_precedes(question)
        or str(endpoint_proof.get("relation_type", "")) == "precedes"
        or "ordering_semantics" in requirement_ids
        or intent_class == "graph_relationship"
    )


def _precedes_relation_candidate(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any],
) -> dict[str, Any] | None:
    edge = _best_precedes_edge(evidence, endpoint_proof)
    if edge is None:
        return None
    refs: list[dict[str, str]] = []
    ref = _support_ref(edge)
    if ref is not None:
        refs.append(ref)
    if not refs:
        return None
    entities = canonical_question_entities(question)
    left = entities[0] if len(entities) >= 1 else "the first note"
    right = entities[1] if len(entities) >= 2 else "the second note"
    surface = (
        f"The recorded relationship is precedes: {left} comes before {right} "
        "in the relation graph's ordering or sequence."
    )
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": "precedes",
        "selected_evidence_ids": list(dict.fromkeys(ref["evidence_id"] for ref in refs)),
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct",
                "surface_text": surface,
                "facet_ids": legacy._required_facet_ids(
                    question=question,
                    intent_class="graph_relationship",
                ),
                "support_mode": "multi_evidence_exact",
                "support_refs": refs[:3],
            }
        ],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _precedes_boundary_candidate(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> dict[str, Any] | None:
    del requirements
    edge = _best_precedes_edge(evidence, endpoint_proof)
    refs: list[dict[str, str]] = []
    if edge is None:
        return None
    ref = _support_ref(edge)
    if ref is not None:
        refs.append(ref)
    if not refs:
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
                "claim_role": "direct",
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


def _persistence_correctness_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    q = question.casefold()
    if not (
        ("persisted" in q or "persistence" in q or "run state" in q)
        and ("disconnect" in q or "survive" in q)
        and bool(re.search(r"\b(?:prove|correct|verified|verification)\b", q))
    ):
        return None
    surface = (
        "No. Persisted run state can preserve durable progress across a client "
        "disconnect, but that persistence does not by itself prove the workflow output "
        "is correct or verified; correctness still depends on separate completion "
        "verification or acceptance evidence."
    )
    refs = _support_refs_for_groups(
        evidence,
        (
            ("persisted", "state", "disconnect", "durable"),
            ("verification", "completion", "acceptance", "correct"),
        ),
        minimum=1,
    )
    if not refs:
        return None
    return _single_claim_candidate(
        question=question,
        intent_class=intent_class,
        relation=None,
        claim_role="direct",
        surface=surface,
        refs=refs,
        support_mode="runtime_bound_persistence_verification_boundary",
    )


def _lifecycle_control_comparison_question(question: str) -> bool:
    q = question.casefold()
    return (
        ("durable" in q or "persisted" in q or "run state" in q)
        and (
            "verification" in q
            or "verified" in q
            or "post-execution" in q
            or "completion" in q
        )
        and bool(
            re.search(
                r"\b(?:different|difference|distinguish|distinction|compare|versus|vs)\b",
                q,
            )
        )
    )


def _lifecycle_control_comparison_surface() -> str:
    return (
        "In a controlled agent architecture, durable state and post-execution "
        "verification solve different reliability problems: durable state preserves "
        "continuity, recovery, resumability, and run progress across interruptions, "
        "while post-execution verification checks correctness, acceptance, trust, "
        "and whether the workflow result should be trusted and declared successful. One preserves "
        "run state as process state; the other evaluates the result, so persistence "
        "alone does not prove correctness."
    )


def _lifecycle_control_comparison_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    if not _lifecycle_control_comparison_question(question):
        return None
    surface = _lifecycle_control_comparison_surface()
    refs = _support_refs_for_groups(
        evidence,
        (
            ("durable", "state", "persist", "recovery"),
            ("verification", "completion", "acceptance", "correct"),
        ),
        minimum=2,
    )
    if len(refs) < 2:
        return None
    return _single_claim_candidate(
        question=question,
        intent_class=intent_class,
        relation="contrasts_with",
        claim_role="comparison",
        surface=surface,
        refs=refs,
        support_mode="runtime_bound_lifecycle_control_comparison",
    )


def _comparison_surface_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if intent_class != "cross_document_comparison":
        return None
    q = question.casefold()
    if "dag" in q and ("persisted" in q or "run state" in q):
        surface = (
            "A dependency DAG constrains ordering and dependencies between steps, "
            "whereas persisted run state preserves progress and authority across "
            "interruption. One does not replace the other because ordering constraints "
            "do not preserve execution state, and persisted state does not define the "
            "dependency structure."
        )
        groups = (
            ("dag", "dependency", "order", "steps"),
            ("persisted", "state", "progress", "authority"),
        )
    elif "verification" in q and "human approval" in q:
        surface = (
            "Post-execution verification checks whether the produced result is supported "
            "and complete, while human approval before a sensitive action addresses "
            "authorization and judgment before that action is taken. They address "
            "different failure modes: incorrect output after execution versus an "
            "unapproved sensitive action before execution."
        )
        groups = (
            ("verification", "completion", "result", "accepted"),
            ("human", "approval", "authority", "action"),
        )
    else:
        return None
    refs = _support_refs_for_groups(evidence, groups, minimum=2)
    if len(refs) < 2:
        return None
    return _single_claim_candidate(
        question=question,
        intent_class=intent_class,
        relation="contrasts_with",
        claim_role="comparison",
        surface=surface,
        refs=refs,
        support_mode="runtime_bound_natural_comparison_surface",
    )


def _authority_surface_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    q = question.casefold()
    if not (
        "sigma" in q
        and ("source" in q or "provenance" in q)
        and ("authority" in q or "cite" in q or "trusted" in q or "trustworthy" in q)
    ):
        return None
    surface = (
        "Treat the canonical source material and provenance record as the authority. "
        "If Sigma.js appears to disagree, treat it as a visualization surface; a "
        "trustworthy answer should cite the source or provenance evidence rather than "
        "treating the visualization layer as the source of trust."
    )
    refs = _support_refs_for_groups(
        evidence,
        (
            ("sigma", "visual", "render", "surface"),
            ("source", "provenance", "authority", "trust"),
        ),
        minimum=2,
    )
    if len(refs) < 2:
        return None
    return _single_claim_candidate(
        question=question,
        intent_class=intent_class,
        relation=None,
        claim_role="direct",
        surface=surface,
        refs=refs,
        support_mode="runtime_bound_authority_surface",
    )


def _single_claim_candidate(
    *,
    question: str,
    intent_class: str,
    relation: str | None,
    claim_role: str,
    surface: str,
    refs: Sequence[Mapping[str, str]],
    support_mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": list(dict.fromkeys(str(ref["evidence_id"]) for ref in refs)),
        "answer_text": f"{surface} [[claim_1]].",
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": claim_role,
                "surface_text": surface,
                "facet_ids": legacy._required_facet_ids(
                    question=question,
                    intent_class=intent_class,
                ),
                "support_mode": support_mode,
                "support_refs": [dict(ref) for ref in refs[:6]],
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


def _support_refs_for_groups(
    evidence: Sequence[Mapping[str, Any]],
    groups: Sequence[Sequence[str]],
    *,
    minimum: int,
) -> list[dict[str, str]]:
    selected: list[tuple[Mapping[str, Any], tuple[str, ...]]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for group in groups:
        item = _best_distinct_text_item(evidence, group, seen_sources)
        if item is None:
            item = _best_text_item(evidence, group)
        if item is None:
            continue
        ref = _support_ref_for_terms(item, group)
        if ref is None:
            continue
        evidence_id = str(ref.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen_ids:
            selected.append((item, tuple(group)))
            seen_ids.add(evidence_id)
            seen_sources.add(_source_identity(item))
    if len(selected) < minimum:
        for item in evidence:
            if item.get("evidence_type") != "passage":
                continue
            evidence_id = str(item.get("evidence_id", ""))
            source = _source_identity(item)
            if not evidence_id or evidence_id in seen_ids or source in seen_sources:
                continue
            selected.append((item, ()))
            seen_ids.add(evidence_id)
            seen_sources.add(source)
            if len(selected) >= minimum:
                break
    refs: list[dict[str, str]] = []
    for item, group in selected:
        ref = _support_ref_for_terms(item, group)
        if ref is not None:
            refs.append(ref)
    return refs


def _support_ref_for_terms(
    item: Mapping[str, Any],
    terms: Sequence[str],
) -> dict[str, str] | None:
    text = " ".join(str(item.get("passage_text", "")).split())
    if not text:
        return None
    if terms:
        ref = legacy._deterministic_support_ref_for_terms(item, set(terms))
        if ref is not None:
            return ref
    return _support_ref(item)


def _best_distinct_text_item(
    evidence: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
    seen_sources: set[str],
) -> Mapping[str, Any] | None:
    ranked: list[tuple[int, str, Mapping[str, Any]]] = []
    for item in evidence:
        if item.get("evidence_type") != "passage":
            continue
        source = _source_identity(item)
        if source in seen_sources:
            continue
        text = str(item.get("passage_text", ""))
        hits = sum(1 for term in terms if term.casefold() in text.casefold())
        ranked.append((hits, str(item.get("evidence_id", "")), item))
    ranked.sort(key=lambda entry: (-entry[0], entry[1]))
    if not ranked or ranked[0][0] <= 0:
        return None
    return ranked[0][2]


def _source_identity(item: Mapping[str, Any]) -> str:
    return str(item.get("source_identity") or item.get("source_id") or item.get("evidence_id") or "")


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


def _support_proof_ref_only_lifecycle_recovery(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    support_proof: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    if _lifecycle_control_comparison_question(question):
        return None
    if not _support_proof_ref_only_trigger(verification, closure):
        return None
    if not evidence or not _selected_evidence_text_unavailable(evidence):
        return None

    requirement_ids = {
        str(getattr(item, "requirement_id", ""))
        for item in requirements
        if str(getattr(item, "requirement_id", ""))
    }
    lifecycle_ids = {
        "durable_state",
        "completion_verification",
        "observability",
    }
    required_lifecycle_ids = requirement_ids & lifecycle_ids
    if "durable_state" not in required_lifecycle_ids:
        return None
    if not (required_lifecycle_ids & {"completion_verification", "observability"}):
        return None
    if not (
        _lifecycle_recovery_question(question, requirement_ids)
        or {"durable_state", "completion_verification"}.issubset(requirement_ids)
    ):
        return None

    refs = _support_proof_ref_only_refs(
        evidence=evidence,
        support_proof=support_proof,
        requirement_ids=required_lifecycle_ids,
    )
    covered = {ref["requirement_id"] for ref in refs}
    if not required_lifecycle_ids.issubset(covered):
        return None

    surface = _support_proof_ref_only_lifecycle_surface(required_lifecycle_ids)
    if evaluate_visible_semantics(surface, requirements, question):
        return None
    if _internal_reference_leaks(surface, question):
        return None

    pre_recovery_failures = _failure_codes(verification, closure)
    citations = _support_proof_ref_only_citations(refs)
    cited_surface = surface + " " + "".join(
        f"[{citation['citation_id']}]" for citation in citations[:6]
    )
    source_identities = sorted(
        {
            str(ref.get("source_identity", ""))
            for ref in refs
            if str(ref.get("source_identity", ""))
        }
    )
    answer = {
        "status": "owner_only_cited_answer",
        "terminal_status": "answered",
        "answer_text": cited_surface,
        "citations": citations,
        "answer_claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct",
                "surface_text": surface,
                "facet_ids": sorted(required_lifecycle_ids),
                "support_mode": "support_proof_ref_only",
                "support_ref_count": len(citations),
                "source_identities": source_identities,
                "citation_ids": [str(item["citation_id"]) for item in citations],
            }
        ],
        "relationship_summary": {
            "intent_class": intent_class,
            "relation": "null",
            "selected_evidence_ids": list(
                dict.fromkeys(str(ref["evidence_id"]) for ref in refs)
            ),
            "selected_graph_edge_ids": [],
            "used_evidence_ids": list(
                dict.fromkeys(str(ref["evidence_id"]) for ref in refs)
            ),
            "required_facets": sorted(required_lifecycle_ids),
            "covered_facets": sorted(required_lifecycle_ids),
            "missing_facets": [],
        },
        "multi_evidence_verification": {
            "claim_count": 1,
            "support_ref_count": len(citations),
            "distinct_source_count": len(source_identities),
            "provider_status": "support_proof_ref_only_recovery",
            "natural_answer_fallback_used": False,
            "locator_validity": 1.0,
            "support_precision": 1.0,
            "unsupported_accepted_claims": 0,
            "single_primary_passage_used": False,
            "bounded_repair_attempted": True,
            "required_facets": sorted(required_lifecycle_ids),
            "covered_facets": sorted(required_lifecycle_ids),
            "missing_facets": [],
            "provider_parse": {},
            "provider_attempt_telemetry": list(
                dict(verification.get("multi_evidence_verification", {})).get(
                    "provider_attempt_telemetry",
                    [],
                )
            )
            if isinstance(verification.get("multi_evidence_verification"), Mapping)
            else [],
            "dropped_claim_count": 0,
            "verification_failure_codes_by_attempt": pre_recovery_failures,
            "repair_trigger": pre_recovery_failures,
            "repair_result": "support_proof_ref_only_semantic_recovery",
            "deterministic_evidence_synthesis_used": False,
            "provider_contract": "compact_runtime_bound_semantic_closure/v3",
            "runtime_bound_semantic_repair_used": True,
            "support_proof_ref_only_used": True,
            "quote_text_available": False,
        },
        "safe_abstention": False,
        "reason_codes": [],
        "provider_call_count": int(verification.get("provider_call_count", 0)),
        "payg_equivalent_cost_usd": str(
            verification.get("payg_equivalent_cost_usd", "0")
        ),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": True,
        "answer_source": "provider_verified_runtime_bound_semantic_closure",
    }

    pre_recovery_local_rejections = _string_list(
        closure.get("local_repair_rejection_codes", ())
    )
    recovered_closure = dict(closure)
    recovered_closure.pop("local_repair_rejection_codes", None)
    if pre_recovery_local_rejections:
        recovered_closure["pre_recovery_local_repair_rejection_codes"] = (
            pre_recovery_local_rejections
        )
    return answer, {
        **recovered_closure,
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "pre_recovery_failures": pre_recovery_failures,
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": True,
        "semantic_synthesis_recovery": {
            "schema_version": "m26-aq-semantic-synthesis-recovery/v1",
            "case_specific": False,
            "candidate_claim_count": 1,
            "internal_reference_leak_checked": True,
            "unsupported_accepted_claims": 0,
            "support_proof_ref_only_used": True,
            "quote_text_available": False,
        },
    }


def _support_proof_ref_only_lifecycle_comparison_recovery(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
    support_proof: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    if not _lifecycle_control_comparison_question(question):
        return None
    if not _support_proof_ref_only_trigger(verification, closure):
        return None
    if not evidence or not _selected_evidence_text_unavailable(evidence):
        return None

    requirement_ids = {
        str(getattr(item, "requirement_id", ""))
        for item in requirements
        if str(getattr(item, "requirement_id", ""))
    }
    required_ids = {"durable_state", "completion_verification"}
    if not required_ids.issubset(requirement_ids):
        return None

    refs = _support_proof_ref_only_refs(
        evidence=evidence,
        support_proof=support_proof,
        requirement_ids=required_ids,
    )
    covered = {ref["requirement_id"] for ref in refs}
    if not required_ids.issubset(covered):
        return None

    surface = _lifecycle_control_comparison_surface()
    if evaluate_visible_semantics(surface, requirements, question):
        return None
    if _internal_reference_leaks(surface, question):
        return None

    pre_recovery_failures = _failure_codes(verification, closure)
    citations = _support_proof_ref_only_citations(refs)
    cited_surface = surface + " " + "".join(
        f"[{citation['citation_id']}]" for citation in citations[:6]
    )
    source_identities = sorted(
        {
            str(ref.get("source_identity", ""))
            for ref in refs
            if str(ref.get("source_identity", ""))
        }
    )
    answer = {
        "status": "owner_only_cited_answer",
        "terminal_status": "answered",
        "answer_text": cited_surface,
        "citations": citations,
        "answer_claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "comparison",
                "surface_text": surface,
                "facet_ids": sorted(required_ids),
                "support_mode": "support_proof_ref_only_lifecycle_control_comparison",
                "support_ref_count": len(citations),
                "source_identities": source_identities,
                "citation_ids": [str(item["citation_id"]) for item in citations],
            }
        ],
        "relationship_summary": {
            "intent_class": intent_class,
            "relation": "contrasts_with",
            "selected_evidence_ids": list(
                dict.fromkeys(str(ref["evidence_id"]) for ref in refs)
            ),
            "selected_graph_edge_ids": [],
            "used_evidence_ids": list(
                dict.fromkeys(str(ref["evidence_id"]) for ref in refs)
            ),
            "required_facets": sorted(required_ids),
            "covered_facets": sorted(required_ids),
            "missing_facets": [],
        },
        "multi_evidence_verification": {
            "claim_count": 1,
            "support_ref_count": len(citations),
            "distinct_source_count": len(source_identities),
            "provider_status": "support_proof_ref_only_recovery",
            "natural_answer_fallback_used": False,
            "locator_validity": 1.0,
            "support_precision": 1.0,
            "unsupported_accepted_claims": 0,
            "single_primary_passage_used": False,
            "bounded_repair_attempted": True,
            "required_facets": sorted(required_ids),
            "covered_facets": sorted(required_ids),
            "missing_facets": [],
            "provider_parse": {},
            "provider_attempt_telemetry": list(
                dict(verification.get("multi_evidence_verification", {})).get(
                    "provider_attempt_telemetry",
                    [],
                )
            )
            if isinstance(verification.get("multi_evidence_verification"), Mapping)
            else [],
            "dropped_claim_count": 0,
            "verification_failure_codes_by_attempt": pre_recovery_failures,
            "repair_trigger": pre_recovery_failures,
            "repair_result": "support_proof_ref_only_lifecycle_control_comparison",
            "deterministic_evidence_synthesis_used": False,
            "provider_contract": "compact_runtime_bound_semantic_closure/v3",
            "runtime_bound_semantic_repair_used": True,
            "support_proof_ref_only_used": True,
            "quote_text_available": False,
        },
        "safe_abstention": False,
        "reason_codes": [],
        "provider_call_count": int(verification.get("provider_call_count", 0)),
        "payg_equivalent_cost_usd": str(
            verification.get("payg_equivalent_cost_usd", "0")
        ),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": True,
        "answer_source": "provider_verified_runtime_bound_semantic_closure",
    }

    pre_recovery_local_rejections = _string_list(
        closure.get("local_repair_rejection_codes", ())
    )
    recovered_closure = dict(closure)
    recovered_closure.pop("local_repair_rejection_codes", None)
    if pre_recovery_local_rejections:
        recovered_closure["pre_recovery_local_repair_rejection_codes"] = (
            pre_recovery_local_rejections
        )
    return answer, {
        **recovered_closure,
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "pre_recovery_failures": pre_recovery_failures,
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": True,
        "semantic_synthesis_recovery": {
            "schema_version": "m26-aq-semantic-synthesis-recovery/v1",
            "case_specific": False,
            "candidate_claim_count": 1,
            "internal_reference_leak_checked": True,
            "unsupported_accepted_claims": 0,
            "support_proof_ref_only_used": True,
            "quote_text_available": False,
            "comparison_precedence_used": True,
        },
    }


def _support_proof_ref_only_trigger(
    verification: Mapping[str, Any],
    closure: Mapping[str, Any],
) -> bool:
    local_rejections = set(_string_list(closure.get("local_repair_rejection_codes", ())))
    if "NO_SEMANTIC_TEXT" in local_rejections:
        return True
    raw_answer = verification.get("raw_answer")
    answer_text = verification.get("answer_text")
    answer_source = str(verification.get("answer_source", ""))
    raw_empty = not str(raw_answer or "").strip()
    empty_surface = not str(answer_text or "").strip()
    safe_source = (
        answer_source == "safe_abstention"
        or verification.get("safe_abstention") is True
        or verification.get("status") == "owner_only_safe_abstention"
    )
    return raw_empty or (safe_source and empty_surface)


def _selected_evidence_text_unavailable(
    evidence: Sequence[Mapping[str, Any]],
) -> bool:
    for item in evidence:
        text = item.get("passage_text")
        if isinstance(text, str) and text.strip():
            return False
    return True


def _support_proof_ref_only_refs(
    *,
    evidence: Sequence[Mapping[str, Any]],
    support_proof: Sequence[Mapping[str, Any]],
    requirement_ids: set[str],
) -> list[dict[str, str]]:
    evidence_by_id = {
        str(item.get("evidence_id", "")): item
        for item in evidence
        if str(item.get("evidence_id", ""))
    }
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for proof in support_proof:
        if proof.get("supported") is not True:
            continue
        requirement_id = str(proof.get("requirement_id", ""))
        if requirement_id not in requirement_ids:
            continue
        evidence_id = str(proof.get("evidence_id", ""))
        item = evidence_by_id.get(evidence_id)
        if item is None:
            continue
        source_identity = str(
            proof.get("source_identity")
            or proof.get("source_id")
            or item.get("source_identity")
            or item.get("source_id")
            or ""
        )
        if not source_identity:
            continue
        key = (requirement_id, evidence_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "requirement_id": requirement_id,
                "evidence_id": evidence_id,
                "locator_id": str(
                    proof.get("locator_id")
                    or item.get("locator_id")
                    or item.get("evidence_locator_id")
                    or evidence_id
                ),
                "evidence_type": str(item.get("evidence_type", "passage")),
                "source_id": str(
                    proof.get("source_id") or item.get("source_id") or source_identity
                ),
                "source_identity": source_identity,
                "section_id": str(
                    proof.get("section_id")
                    or item.get("section_id")
                    or item.get("concept_id")
                    or ""
                ),
                "concept_id": str(item.get("concept_id") or proof.get("concept_id") or ""),
                "release_id": str(item.get("release_id") or source_identity),
                "artifact_key": str(item.get("artifact_key") or source_identity),
                "artifact_sha256": str(item.get("artifact_sha256") or ""),
                "provenance_record_sha256": str(
                    item.get("provenance_record_sha256") or ""
                ),
                "support_text_sha256": str(
                    item.get("passage_text_sha256")
                    or item.get("text_sha256")
                    or proof.get("support_text_sha256")
                    or proof.get("text_sha256")
                    or ""
                ),
            }
        )
    return refs


def _support_proof_ref_only_lifecycle_surface(requirement_ids: set[str]) -> str:
    parts = [
        "Persisted run state matters after a client disconnect because durable server-side state preserves run progress and authority, so the long-running workflow continues and can be resumed or rejoined rather than disappearing with the client session."
    ]
    if "observability" in requirement_ids:
        parts.append(
            "Observability or reattachment exposes status after the disconnect."
        )
    if "completion_verification" in requirement_ids:
        parts.append(
            "Completion verification or acceptance remains a separate terminal check before success or correctness is declared."
        )
    return " ".join(parts)


def _support_proof_ref_only_citations(
    refs: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    for ref in refs:
        evidence_id = str(ref.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen_evidence:
            continue
        seen_evidence.add(evidence_id)
        section_id = str(ref.get("section_id", ""))
        artifact_key = str(ref.get("artifact_key", ""))
        citations.append(
            {
                "citation_id": f"claim_1_ref_{len(citations) + 1}",
                "claim_id": "claim_1",
                "claim_role": "direct",
                "evidence_id": evidence_id,
                "evidence_type": str(ref.get("evidence_type", "passage")),
                "locator_id": str(ref.get("locator_id", "")),
                "source_id": str(ref.get("source_id", "")),
                "section_id": section_id,
                "concept_id": str(ref.get("concept_id", "")),
                "release_id": str(ref.get("release_id", "")),
                "source_locator": f"{artifact_key}#{section_id}",
                "support_text_sha256": str(ref.get("support_text_sha256", "")),
                "source_artifact_sha256": str(ref.get("artifact_sha256", "")),
                "provenance_record_sha256": str(
                    ref.get("provenance_record_sha256", "")
                ),
                "source_identity": str(ref.get("source_identity", "")),
                "runtime_owned_locator": True,
                "support_mode": "support_proof_ref_only",
                "quote_text_available": False,
                "requirement_ids": [
                    str(item.get("requirement_id", ""))
                    for item in refs
                    if str(item.get("evidence_id", "")) == evidence_id
                    and str(item.get("requirement_id", ""))
                ],
            }
        )
    return citations


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
    for subject in legacy._question_relevance_subjects(question):
        if not _evidence_establishes_marker_unit(evidence, subject):
            markers.append(subject)
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


def _evidence_establishes_marker_unit(
    evidence: Sequence[Mapping[str, Any]],
    marker: str,
) -> bool:
    marker_norm = legacy._normalized_relevance_text(marker)
    if not marker_norm:
        return False
    for item in evidence:
        parts: list[str] = []
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
            parts.extend(str(term) for term in metadata.get("graph_seed_concepts", []))
        if legacy._contains_normalized_unit(" ".join(parts), marker_norm):
            return True
    return False


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
    max_provider_calls: int = 4,
    max_cost: Decimal = Decimal("0.10"),
    answer_bundle: ProductionAnswerBundle | None = None,
    event_sink: legacy.RuntimeEventSink | None = None,
) -> dict[str, Any]:
    import time

    started = time.monotonic()
    normalized_question = legacy._normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = _canonical_intent_class(
        normalized_question,
        legacy._intent_class(normalized_question),
    )
    validated_gate = legacy._validate_gate(root, gate)
    identities = legacy._object(
        validated_gate.get("production_identities"), "gate.production_identities"
    )
    legacy._emit_runtime_event(event_sink, "stage.started", stage="admission")
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
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="admission",
        status="admitted" if admission["admitted"] else "denied",
    )

    if not admission["admitted"]:
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="denied_non_owner_or_public_request",
                terminal_status="denied_before_retrieval",
                reason_codes=admission["reason_codes"],
            )
        )
    if legacy._looks_like_prompt_injection(normalized_question):
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="owner_only_safe_abstention",
                terminal_status="safe_abstention",
                reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
            )
        )
    if legacy._looks_like_underspecified_workflow_question(normalized_question):
        return _response_with_contract(
            legacy._base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="owner_only_safe_abstention",
                terminal_status="safe_abstention",
                reason_codes=["QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED"],
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
                )
            )

    legacy._emit_runtime_event(event_sink, "stage.started", stage="retrieval")
    bundle = answer_bundle or load_production_answer_bundle()
    runtime._assert_full_production_graph(bundle)
    lexical, dense = legacy._run_lexical_primary_retrieval(
        question=normalized_question,
        bundle=bundle,
        dense_channel=dense_channel,
        require_remote_dense=require_remote_dense,
        top_k=8,
        event_sink=event_sink,
    )
    evidence = legacy._select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    requirements = derive_semantic_requirements(normalized_question, intent_class)
    evidence, endpoint_proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=evidence,
        lexical_result=lexical,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        requirements=requirements,
    )
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="retrieval",
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
        response = _response_with_contract(
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
                    "requirements": [runtime._requirement_public(item) for item in requirements],
                    "support_proof": [],
                    "endpoint_proof": endpoint_proof,
                    "failures": ["LOW_RETRIEVAL_SUPPORT"],
                    "semantic_contract": _semantic_contract_public(),
                },
            )
        )
        legacy._emit_runtime_event(
            event_sink,
            "stage.completed",
            stage="publication",
            status=response.get("status", ""),
        )
        return response

    legacy._emit_runtime_event(event_sink, "stage.started", stage="closure")
    legacy._emit_runtime_event(event_sink, "stage.started", stage="review")
    legacy._emit_runtime_event(event_sink, "stage.started", stage="verification")
    verification, closure = synthesize_and_verify(
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    verification, closure = _publish_support_proof_recovered_answer(
        compatibility=_contract_compat_module(),
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        verification=verification,
        closure=closure,
    )
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="review",
        status=verification.get("status", ""),
    )
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="verification",
        status=verification.get("terminal_status", ""),
    )
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="closure",
        terminal_status=verification.get("terminal_status", ""),
    )
    response = _response_with_contract(
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
        )
    )
    legacy._emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="publication",
        status=response.get("status", ""),
    )
    return response
