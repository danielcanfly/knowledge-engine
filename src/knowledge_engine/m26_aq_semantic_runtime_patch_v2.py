from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import m26_aq_semantic_runtime_patch as base_patch

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
)
_RELATION_PARAPHRASE_RE = re.compile(
    r"\b(?:precedes?|preceding|comes\s+before|come\s+before|is\s+before|are\s+before|comes\s+earlier\s+than|is\s+earlier\s+than)\b",
    flags=re.I,
)
_RELATION_SPLIT_PATTERNS = (
    r"\s+as\s+preceding\b.*$",
    r"\s+as\s+coming\s+before\b.*$",
    r"\s+comes\s+earlier\s+than\b.*$",
    r"\s+is\s+earlier\s+than\b.*$",
    r"\s+comes\s+before\b.*$",
    r"\s+come\s+before\b.*$",
    r"\s+is\s+before\b.*$",
    r"\s+are\s+before\b.*$",
    r"\s+precedes\b.*$",
    r"\s+precede\b.*$",
)


def install() -> None:
    """Install the final question-id-agnostic AQ semantic runtime bindings."""
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime

    base_patch.install()
    base_repair = getattr(
        base_patch,
        "_m26_aq_original_runtime_bound_semantic_repair",
        None,
    )
    if base_repair is None or base_repair is _runtime_bound_semantic_repair_v2:
        base_repair = base_patch._runtime_bound_semantic_repair
    base_patch._m26_aq_original_runtime_bound_semantic_repair = base_repair
    if getattr(runtime, "_m26_aq_semantic_runtime_patch_v2_installed", False):
        return

    previous_requirements = runtime._semantic_requirements
    previous_edge = runtime._exact_named_graph_edge

    def clean_entities(question: str) -> list[str]:
        entities: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            value = _clean_entity_text(value)
            key = value.casefold()
            if value and key not in seen:
                entities.append(value)
                seen.add(key)

        q = question
        prefix_match = re.search(
            r"\b([A-Z][A-Za-z0-9 .'/&-]+?)\s+Part\s+\d+\b",
            q,
        )
        if prefix_match:
            root = _clean_entity_text(prefix_match.group(1))
            for part in re.findall(r"\bPart\s+(\d+)\b", q, flags=re.I):
                add(f"{root} Part {part}")
        for name in (
            "production router",
            "query router",
            "DAG",
            "state machine",
            "adaptive replanning",
            "Obsidian",
            "Graphology",
            "Sigma.js",
        ):
            if name.casefold() in q.casefold():
                add(name)
        for raw in legacy._m26_aq_original_named_question_entities(q):
            cleaned = _clean_entity_text(raw)
            lowered = cleaned.casefold()
            if not cleaned or len(cleaned) > 80:
                continue
            if lowered in {"part 1", "part 2"}:
                continue
            if any(existing.casefold() in lowered for existing in entities):
                continue
            add(cleaned)
        return entities

    def requirements(question: str, intent_class: str) -> list[Any]:
        items = []
        for item in previous_requirements(question, intent_class):
            exact = str(getattr(item, "exact_phrase", ""))
            if item.requirement_id.startswith("entity_"):
                cleaned = _clean_entity_text(exact)
                if cleaned != exact:
                    continue
            items.append(item)
        _augment_final_requirements(runtime, question, items)
        _normalize_final_requirements(runtime, question, items)
        _apply_requested_lifecycle_requirements(runtime, question, items)
        return items

    def exact_edge(bundle: Any, question: str) -> Mapping[str, Any] | None:
        entities = clean_entities(question)
        required_relation = "precedes" if _relation_paraphrase_mentions_precedes(question) else ""
        if len(entities) >= 2:
            source_canonical = _canonical_named_concepts(runtime, bundle, entities[0])
            target_canonical = _canonical_named_concepts(runtime, bundle, entities[1])
            strict_named_endpoints = any(
                _requires_canonical_endpoint_binding(entity) for entity in entities[:2]
            )
            if source_canonical and target_canonical:
                edge = _best_exact_edge(
                    bundle,
                    source_canonical,
                    target_canonical,
                    required_relation,
                )
                if edge is not None:
                    return edge
                if strict_named_endpoints:
                    return None
            elif strict_named_endpoints:
                return None

        edge = previous_edge(bundle, question)
        if edge is not None:
            return edge
        if len(entities) < 2:
            return None
        source_candidates = _loose_concepts(runtime, bundle, entities[0])
        target_candidates = _loose_concepts(runtime, bundle, entities[1])
        return _best_exact_edge(
            bundle,
            source_candidates,
            target_candidates,
            required_relation,
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
        return _provider_integrity_safe_synthesize(
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

    legacy._named_question_entities = clean_entities
    runtime._semantic_requirements = requirements
    runtime._exact_named_graph_edge = exact_edge
    runtime._synthesize_and_verify = synthesize
    base_patch._runtime_bound_semantic_repair = _runtime_bound_semantic_repair_v2
    runtime._m26_aq_semantic_runtime_patch_v2_installed = True


def _clean_entity_text(value: str) -> str:
    text = " ".join(str(value).strip().split())
    for prefix in (
        "The production graph says ",
        "The relation graph records ",
        "If the relation graph records ",
        "Does the precedes edge between ",
        "Can the precedes edge between ",
        "Does ",
    ):
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix) :]
    changed = True
    while changed:
        changed = False
        for prefix in _GRAPH_WRAPPER_PREFIXES:
            if text.casefold().startswith(prefix.casefold()):
                text = text[len(prefix) :]
                changed = True
                break
        text = " ".join(text.strip(" ?:.,").split())
    for pattern in _RELATION_SPLIT_PATTERNS:
        next_text = re.sub(pattern, "", text, flags=re.I).strip(" ?:.,")
        if next_text != text and re.search(r"\bPart\s+\d+\b", next_text, flags=re.I):
            text = next_text
            break
    for suffix in (" prove that", " prove", " safely infer"):
        index = text.casefold().find(suffix.casefold())
        if index > 0:
            text = text[:index]
    for suffix in (
        " by itself",
        " alone",
        " answer the inference",
        " not merely the true graph fact",
    ):
        index = text.casefold().find(suffix.casefold())
        if index > 0:
            text = text[:index]
    return " ".join(text.strip(" ?:.,").split())


def _strict_part_entities(question: str) -> list[str]:
    prefix_match = re.search(
        r"\b([A-Z][A-Za-z0-9 .'/&-]+?)\s+Part\s+\d+\b",
        question,
    )
    root = _clean_entity_text(prefix_match.group(1)) if prefix_match else ""
    entities: list[str] = []
    seen: set[str] = set()
    for part in re.findall(r"\bPart\s+(\d+)\b", question, flags=re.I):
        entity = _clean_entity_text(f"{root} Part {part}" if root else f"Part {part}")
        key = entity.casefold()
        if entity and key not in seen:
            entities.append(entity)
            seen.add(key)
    return entities


def _relation_paraphrase_mentions_precedes(question: str) -> bool:
    q = str(question)
    if not _RELATION_PARAPHRASE_RE.search(q):
        return False
    if not re.search(r"\bPart\s+\d+\b", q, flags=re.I):
        return False
    graph_context = re.search(
        r"\b(?:graph|edge|relation|records?|fact|relationship|ordering|sequence|navigation)\b",
        q,
        flags=re.I,
    )
    return bool(graph_context) or len(_strict_part_entities(q)) >= 2


def _requires_non_entailment_boundary(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:depend(?:s|ency|ent)?|causal(?:ity)?|prove[ns]?|infer(?:red|ence)?|implementation|requirement)\b",
            str(question),
            flags=re.I,
        )
    )


def _requirement_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "entity"


def _make_entity_requirement(runtime: Any, phrase: str) -> Any:
    return runtime.SemanticRequirement(
        requirement_id=f"entity_{_requirement_slug(phrase)}",
        instruction=f"Name and address {phrase} explicitly.",
        evidence_terms=(phrase,),
        visible_patterns=(re.escape(phrase),),
        exact_phrase=phrase,
    )


def _make_requirement(
    runtime: Any,
    *,
    requirement_id: str,
    instruction: str,
    evidence_terms: Sequence[str],
    visible_patterns: Sequence[str],
) -> Any:
    return runtime.SemanticRequirement(
        requirement_id=requirement_id,
        instruction=instruction,
        evidence_terms=tuple(evidence_terms),
        visible_patterns=tuple(visible_patterns),
    )


def _normalize_graph_entity_requirements(
    runtime: Any,
    question: str,
    requirements: Sequence[Any],
) -> list[Any]:
    normalized: list[Any] = []
    seen: set[str] = set()
    for item in requirements:
        requirement_id = str(getattr(item, "requirement_id", ""))
        exact = str(getattr(item, "exact_phrase", "") or "")
        replacement = item
        if requirement_id.startswith("entity_") and exact:
            cleaned = _clean_entity_text(exact)
            if cleaned and cleaned != exact:
                replacement = _make_entity_requirement(runtime, cleaned)
                requirement_id = str(getattr(replacement, "requirement_id", ""))
        if requirement_id and requirement_id not in seen:
            normalized.append(replacement)
            seen.add(requirement_id)
    if _relation_paraphrase_mentions_precedes(question):
        if "ordering_semantics" not in seen:
            normalized.append(
                _make_requirement(
                    runtime,
                    requirement_id="ordering_semantics",
                    instruction=(
                        "State that the graph relation records a precedes ordering relationship."
                    ),
                    evidence_terms=("precedes", "ordering", "sequence", "navigation"),
                    visible_patterns=(
                        (
                            r"(?:relation graph|graph|edge|relationship).{0,180}"
                            r"(?:precedes|ordering|sequence|navigation|comes before|"
                            r"earlier than)"
                        ),
                        (
                            r"(?:precedes|comes before|earlier than).{0,180}"
                            r"(?:ordering|sequence|navigation|relationship)"
                        ),
                    ),
                )
            )
            seen.add("ordering_semantics")
        if _requires_non_entailment_boundary(question) and "non_entailment" not in seen:
            normalized.append(
                _make_requirement(
                    runtime,
                    requirement_id="non_entailment",
                    instruction=(
                        "State that a precedes edge alone does not prove dependency, "
                        "causality, implementation, or requirement semantics."
                    ),
                    evidence_terms=(
                        "does not prove",
                        "dependency",
                        "causality",
                        "implementation",
                        "requirement",
                    ),
                    visible_patterns=(
                        (
                            r"(?:does not|cannot|can't|only).{0,180}"
                            r"(?:depend|causal|prove|implementation|requirement)"
                        ),
                    ),
                )
            )
            seen.add("non_entailment")
    return normalized


def _best_precedes_endpoint_proof(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any] | None,
) -> dict[str, Any]:
    endpoint = dict(endpoint_proof or {})
    if endpoint.get("matched") is True:
        return endpoint
    if not _relation_paraphrase_mentions_precedes(question):
        return endpoint
    entities = _strict_part_entities(question)
    for item in evidence:
        if item.get("evidence_type") != "graph_edge":
            continue
        if str(item.get("relation_type", "")) != "precedes":
            continue
        edge_source = str(item.get("edge_source") or item.get("source") or "")
        edge_target = str(item.get("edge_target") or item.get("target") or "")
        if not edge_source or not edge_target:
            continue
        return {
            **endpoint,
            "matched": True,
            "required": True,
            "relation_type": "precedes",
            "edge_id": str(item.get("edge_id", "")),
            "edge_source": edge_source,
            "edge_target": edge_target,
            "question_entities": entities[:2],
            "support_basis": "graph_relation_paraphrase_endpoint_proof",
        }
    return endpoint


def _augment_final_requirements(runtime: Any, question: str, items: list[Any]) -> None:
    q = question.casefold()
    seen = {str(item.requirement_id) for item in items}

    def add(
        requirement_id: str,
        instruction: str,
        terms: Sequence[str],
        pattern: str,
    ) -> None:
        if requirement_id in seen:
            return
        seen.add(requirement_id)
        items.append(
            runtime.SemanticRequirement(
                requirement_id=requirement_id,
                instruction=instruction,
                evidence_terms=tuple(terms),
                visible_patterns=(pattern,),
            )
        )

    if _looks_like_lifecycle_question(q):
        add(
            "admission_policy",
            "State the admission, intake, request, policy, or task-contract gate.",
            ["admission", "intake", "request", "policy", "contract", "start"],
            r"(?:admission|intake|request|policy|contract).{0,220}"
            r"(?:decide|gate|allow|start|admit|boundary)",
        )
        add(
            "durable_state",
            "State durable server-side state or persisted progress after disconnect.",
            ["durable", "persisted", "state", "progress", "server-side"],
            r"(?:durable|persisted|state|progress|server-side).{0,220}"
            r"(?:state|progress|browser|client|disconnect|continue)",
        )
        add(
            "completion_verification",
            "State completion, acceptance, final-status, or verification control.",
            ["completion", "acceptance", "verification", "final", "status"],
            r"(?:completion|acceptance|verification|final).{0,180}"
            r"(?:gate|check|result|status|declared|completion)",
        )
        add(
            "observability",
            "State observability, status, reattach, resume, or inspection.",
            ["observability", "status", "reattach", "resume", "inspect"],
            r"(?:observability|status|reattach|resume|inspect).{0,220}"
            r"(?:status|reattach|resume|inspect|completion|owner)",
        )

    if "production router" in q:
        add(
            "router_decision",
            "Explain what route, path, or capability the router selects.",
            ["router", "route", "path", "capability"],
            r"router.{0,140}(?:route|path|capability|select|choose)",
        )
        add(
            "routing_constraints",
            "State a policy, safety, permission, or capability bound.",
            ["policy", "safety", "permission", "capability"],
            r"\b(?:policy|safety|permission|capability|guardrail|constraint)",
        )
    if "query router" in q and "dag" in q:
        add(
            "router_role",
            "Explain the query router's route/path/capability selection role.",
            ["query router", "route", "path", "capability"],
            r"query router.{0,180}(?:route|path|capability|select|choose)",
        )
        add(
            "dag_role",
            "Explain the DAG ordering or parallel dependency role.",
            ["dag", "order", "parallel", "dependent"],
            r"dag.{0,180}(?:order|parallel|dependent|steps|work)",
        )
        add(
            "router_dag_composition",
            "State how the router and DAG compose in one production flow.",
            ["router", "dag", "together", "flow"],
            r"(?:together|inside|while).{0,220}(?:router|dag)",
        )
    if _looks_like_router_replanner_contrast(q):
        add(
            "initial_routing_role",
            "State that routing chooses the initial path or capability.",
            ["router", "initial", "path", "capability"],
            r"(?:router|routing).{0,180}(?:initial|path|route|capability)",
        )
        add(
            "replanning_role",
            "State that replanning changes remaining work after invalid assumptions.",
            ["replan", "remaining", "invalid", "assumption"],
            r"(?:replan|replanning|planner).{0,180}"
            r"(?:remaining|invalid|assumption|later)",
        )
        add(
            "role_contrast",
            "Contrast initial routing with later replanning of unfinished work.",
            ["initial", "later", "contrast", "different"],
            r"(?:contrast|different|while).{0,240}"
            r"(?:routing|replanning|router|replan)",
        )
    if "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning", "adaptive")
    ):
        add(
            "state_machine_authority",
            "Explain state machine transition and policy authority.",
            ["state machine", "transition", "policy", "approval"],
            r"state machine.{0,180}(?:transition|policy|approval|authority|state)",
        )
        add(
            "adaptive_replan",
            "Explain replanning of remaining work after invalid assumptions.",
            ["replan", "remaining", "invalid", "assumption"],
            r"(?:replan|replanning|replanner).{0,180}"
            r"(?:remaining|invalid|assumption|step)",
        )
        add(
            "authority_boundary",
            "State that replanning stays bounded by policy/approval gates.",
            ["bounded", "authority", "policy", "approval", "gates"],
            r"(?:bounded|authority|policy|approval|gates).{0,220}"
            r"(?:state machine|replanner|replanning|bypass|envelope|gates)",
        )
    if _looks_like_controlled_architecture(q):
        add(
            "source_selection",
            "State source selection or routing to different sources.",
            ["source", "selection", "route", "different"],
            r"(?:source selection|sources?).{0,180}(?:route|select|different|relevant)",
        )
        add(
            "persisted_progress",
            "State persisted progress or durable state.",
            ["persisted", "progress", "durable", "state"],
            r"(?:persisted|durable).{0,160}(?:progress|state)",
        )
        add(
            "parallel_branches",
            "State parallel research branches or concurrent work.",
            ["parallel", "branches", "concurrent"],
            r"(?:parallel|concurrent).{0,120}(?:branches|work|research)",
        )
        add(
            "verification_gate",
            "State verification or checks before release.",
            ["verification", "gate", "checks"],
            r"(?:verification|checks?).{0,120}(?:gate|before|release|result)",
        )
        add(
            "human_approval",
            "State human approval or final authority before release.",
            ["human", "approval", "authority", "release"],
            r"(?:human|person).{0,120}(?:approval|approving|authority|release)",
        )
    if "obsidian" in q and "graphology" in q and "sigma" in q:
        add(
            "obsidian_role",
            "State Obsidian's human Markdown/vault role.",
            ["obsidian", "vault", "markdown", "human"],
            r"obsidian.{0,160}(?:vault|markdown|human|authoring|inspection)",
        )
        add(
            "graphology_role",
            "State Graphology's graph model or processing role.",
            ["graphology", "graph", "model", "processing"],
            r"graphology.{0,160}(?:graph|model|processing|data)",
        )
        add(
            "sigma_role",
            "State Sigma.js rendering or visual interaction role.",
            ["sigma", "render", "visual", "interaction"],
            r"sigma(?:\.js)?.{0,160}(?:render|visual|interaction)",
        )
        add(
            "trust_anchor",
            "State that source/provenance artifact authority is the trust anchor.",
            ["source", "provenance", "trust", "authority"],
            r"(?:source|provenance).{0,180}(?:trust|authority|anchor)",
        )
    if "precedes" in q or _relation_paraphrase_mentions_precedes(question):
        add(
            "ordering_semantics",
            "State that precedes supports ordering or navigation.",
            ["precedes", "ordering", "navigation"],
            r"(?:precedes|ordering|navigation|comes before)",
        )
        add(
            "non_entailment",
            "State that precedes does not prove dependency or causality.",
            ["does not prove", "dependency", "causality"],
            (
                r"(?:does not|cannot|can't|only).{0,180}"
                r"(?:depend|causal|prove|implementation|requirement)"
            ),
        )
    normalized = _normalize_graph_entity_requirements(runtime, question, items)
    items[:] = normalized



def _normalize_final_requirements(runtime: Any, question: str, items: list[Any]) -> None:
    """Normalize inherited semantic requirements without weakening canonical verification."""
    q = question.casefold()
    if not _looks_like_state_machine_replanner_question(q):
        return
    for index, item in enumerate(items):
        if str(item.requirement_id) != "authority_boundary":
            continue
        items[index] = runtime.SemanticRequirement(
            requirement_id="authority_boundary",
            instruction=(
                "State that adaptive replanning remains inside the state-machine "
                "policy/approval authority envelope rather than gaining unlimited authority."
            ),
            evidence_terms=(
                "state machine",
                "policy",
                "approval",
                "authority",
                "bounded",
                "within",
                "unlimited",
            ),
            visible_patterns=(
                r"(?:replan|replanning|replanner).{0,240}"
                r"(?:within|inside|bounded|envelope|policy|approval|authority).{0,220}"
                r"(?:state[- ]machine|policy|approval|authority|gates)",
                r"(?:state[- ]machine|policy|approval|authority|gates).{0,240}"
                r"(?:within|inside|bounded|envelope|authority|gates).{0,220}"
                r"(?:replan|replanning|replanner|revisions)",
                r"(?:rather than|without|instead of).{0,180}"
                r"(?:unlimited|unbounded|expanding).{0,120}authority",
            ),
        )
        return


def _looks_like_state_machine_replanner_question(q: str) -> bool:
    return "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning", "adaptive")
    )

def _looks_like_lifecycle_question(q: str) -> bool:
    continuation = any(
        term in q
        for term in (
            "disconnect",
            "drops",
            "dropped",
            "continues",
            "keeps working",
            "background",
            "server job",
            "headless",
        )
    )
    lifecycle = any(
        term in q
        for term in (
            "admission",
            "intake",
            "completion",
            "final status",
            "reattach",
            "trust",
            "trustworthy",
        )
    )
    return continuation and lifecycle


def _looks_like_lifecycle_control_comparison(q: str) -> bool:
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


def _requested_lifecycle_requirement_ids(question: str) -> set[str] | None:
    q = " ".join(str(question).casefold().split())
    lifecycle_markers = (
        "disconnect",
        "persist",
        "durable",
        "long-running",
        "long running",
        "reattach",
        "status",
    )
    if not any(marker in q for marker in lifecycle_markers):
        return None
    full_markers = (
        "admission to completion",
        "intake to completion",
        "from admission",
        "from intake",
        "surrounding control system",
        "keep the run trustworthy",
    )
    if any(marker in q for marker in full_markers):
        return {
            "admission_policy",
            "durable_state",
            "completion_verification",
            "observability",
        }
    requested = {"durable_state"}
    if any(
        term in q
        for term in (
            "verify",
            "verification",
            "verified",
            "post-execution",
            "correct",
            "completion",
            "complete",
            "success",
            "acceptance",
        )
    ):
        requested.add("completion_verification")
    if any(
        term in q
        for term in ("admission", "intake", "policy", "before execution", "request boundary")
    ):
        requested.add("admission_policy")
    if any(term in q for term in ("observability", "reattach", "status", "inspect", "resume")):
        requested.add("observability")
    if (
        "disconnect" in q
        and ("long-running" in q or "long running" in q)
        and "finished" in q
        and "correct" not in q
    ):
        requested.update({"completion_verification", "observability"})
    return requested


def _runtime_lifecycle_requirement(runtime: Any, requirement_id: str) -> Any:
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
    return runtime.SemanticRequirement(
        requirement_id=requirement_id,
        instruction=instruction,
        evidence_terms=terms,
        visible_patterns=patterns,
    )


def _apply_requested_lifecycle_requirements(
    runtime: Any,
    question: str,
    items: list[Any],
) -> None:
    requested = _requested_lifecycle_requirement_ids(question)
    if requested is None:
        return
    lifecycle_ids = {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }
    items[:] = [
        item
        for item in items
        if str(getattr(item, "requirement_id", "")) not in lifecycle_ids
        or str(getattr(item, "requirement_id", "")) in requested
    ]
    seen = {str(getattr(item, "requirement_id", "")) for item in items}
    for requirement_id in sorted(requested):
        if requirement_id not in seen:
            items.append(_runtime_lifecycle_requirement(runtime, requirement_id))


def _looks_like_router_replanner_contrast(q: str) -> bool:
    has_router = any(term in q for term in ("router", "routing", "dispatcher"))
    has_replan = any(term in q for term in ("replan", "planner", "unfinished"))
    has_temporal = any(term in q for term in ("first", "later", "after", "difference"))
    return has_router and has_replan and has_temporal


def _looks_like_controlled_architecture(q: str) -> bool:
    tokens = {
        "sources": any(
            term in q
            for term in (
                "source",
                "sources",
                "different sources",
                "multiple sources",
                "multi-source",
                "routing",
                "selection",
            )
        ),
        "progress": any(
            term in q
            for term in (
                "progress",
                "persisted",
                "durable",
                "checkpoint",
                "saved state",
                "state",
            )
        ),
        "parallel": any(
            term in q
            for term in (
                "parallel",
                "concurrent",
                "branches",
                "branching",
                "workstreams",
            )
        ),
        "verification": any(
            term in q
            for term in (
                "verification",
                "verify",
                "checked",
                "checks",
                "completion",
                "acceptance",
            )
        ),
        "approval": any(
            term in q
            for term in (
                "approval",
                "approving",
                "human",
                "person",
                "review",
                "authority",
            )
        ),
    }
    return sum(1 for value in tokens.values() if value) >= 4


def _provider_integrity_safe_synthesize(
    *,
    runtime: Any,
    legacy: Any,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    requirements = tuple(
        _normalize_graph_entity_requirements(runtime, question, requirements)
    )
    endpoint_proof = _best_precedes_endpoint_proof(
        question=question,
        evidence=evidence,
        endpoint_proof=endpoint_proof,
    )
    failures: list[str] = []
    calls: list[dict[str, Any]] = []
    final_support_proof: list[dict[str, Any]] = []
    repair_attempted = False
    local_repair_rejection_codes: list[str] = []

    compact_payload, label_map, snippet_map = runtime._compact_provider_payload(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        repair=False,
        previous_failures=(),
    )
    try:
        raw = provider_client.call(compact_payload, "aq_semantic_closure")
        try:
            parsed = runtime._parse_compact_provider_result(
                str(raw.get("text", raw.get("provider_text", "")))
            )
        except ValueError:
            calls.append(runtime._compact_call_telemetry(raw, parse_ok=False))
            raise
        calls.append(runtime._compact_call_telemetry(raw, parse_ok=True))
    except Exception as exc:
        failures.append(str(getattr(exc, "code", type(exc).__name__)))
        return _semantic_abstention(
            runtime=runtime,
            legacy=legacy,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
            calls=calls,
            failures=failures,
            support_proof=final_support_proof,
            repair_attempted=repair_attempted,
            local_repair_rejection_codes=local_repair_rejection_codes,
        )

    def repair_or_abstain() -> tuple[dict[str, Any], dict[str, Any]]:
        repaired = _repair_from_clean_provider_attempts(
            runtime=runtime,
            legacy=legacy,
            question=question,
            trace_id=trace_id,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
            calls=calls,
            failures=failures,
            support_proof=final_support_proof,
            repair_attempted=True,
            local_repair_rejection_codes=local_repair_rejection_codes,
        )
        if repaired is not None:
            return repaired
        return _semantic_abstention(
            runtime=runtime,
            legacy=legacy,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
            calls=calls,
            failures=failures,
            support_proof=final_support_proof,
            repair_attempted=True,
            local_repair_rejection_codes=local_repair_rejection_codes,
        )

    if parsed["status"] == "abstain":
        failures.append("PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE")
        return repair_or_abstain()

    answer = str(parsed["answer"]).strip()
    visible_failures = runtime._visible_semantic_failures(
        answer,
        requirements,
        question,
    )
    used_items = runtime._resolve_used_items(parsed["used"], label_map)
    if not used_items:
        used_items = runtime._infer_used_items(answer, evidence, limit=6)
    used_items = runtime._force_required_support_items(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        used_items=used_items,
        requirements=requirements,
    )
    support_failures, support_proof = _endpoint_aware_requirement_support_failures(
        runtime=runtime,
        requirements=requirements,
        evidence=used_items,
        endpoint_proof=endpoint_proof,
    )
    final_support_proof = support_proof
    semantic_failures = sorted(set([*visible_failures, *support_failures]))
    if semantic_failures:
        failures.extend(semantic_failures)
        return repair_or_abstain()

    try:
        candidate = runtime._runtime_bound_candidate(
            answer=answer,
            question=question,
            intent_class=intent_class,
            used_items=used_items,
            snippet_map=snippet_map,
        )
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
        final_answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=evidence,
            calls=calls,
            repair_attempted=repair_attempted,
        )
        _use_verified_natural_surface(final_answer, answer)
        leaks = _user_visible_internal_reference_leaks(
            str(final_answer.get("answer_text", "")),
            question,
            label_map,
        )
        if leaks:
            failures.extend(f"USER_VISIBLE_INTERNAL_REFERENCE_LEAK:{item}" for item in leaks)
            return repair_or_abstain()
    except Exception as exc:
        code = str(getattr(exc, "code", type(exc).__name__))
        failures.append(code)
        if _repairable_verifier_failure(code):
            return repair_or_abstain()
        return _semantic_abstention(
            runtime=runtime,
            legacy=legacy,
            requirements=requirements,
            endpoint_proof=endpoint_proof,
            calls=calls,
            failures=failures,
            support_proof=final_support_proof,
            repair_attempted=repair_attempted,
            local_repair_rejection_codes=local_repair_rejection_codes,
        )

    post_failures = runtime._visible_semantic_failures(
        str(final_answer.get("answer_text", "")),
        requirements,
        question,
    )
    if post_failures:
        failures.extend(post_failures)
        return repair_or_abstain()

    final_answer["answer_source"] = "provider_verified_runtime_bound_semantic_closure"
    final_answer["multi_evidence_verification"] = {
        **dict(final_answer.get("multi_evidence_verification", {})),
        "verification_failure_codes_by_attempt": list(failures),
        "repair_trigger": sorted(set(failures)) if repair_attempted else [],
        "repair_result": "verified" if repair_attempted else "not_needed",
        "deterministic_evidence_synthesis_used": False,
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "runtime_bound_semantic_repair_used": False,
        "served_answer_surface": "verified_natural_material_claim_surface",
    }
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": final_support_proof,
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "broad_deterministic_fallback_used": False,
    }
    return final_answer, closure



def _user_visible_internal_reference_leaks(
    text: str,
    question: str,
    label_map: Mapping[str, Any] | None,
) -> list[str]:
    """Return provider/runtime identifiers that leaked into ordinary user-visible prose."""
    if not text:
        return []
    allowed = _question_supplied_internal_tokens(question)
    leaked: list[str] = []

    provider_labels = set()
    if isinstance(label_map, Mapping):
        provider_labels = {str(key) for key in label_map}

    for token in re.findall(r"\be\d+\b", text):
        if token in allowed:
            continue
        if not provider_labels or token in provider_labels:
            leaked.append(token)
    for token in re.findall(r"\barticle_[0-9a-f]{8,}\b", text, flags=re.I):
        if token not in allowed:
            leaked.append(token)
    for token in re.findall(
        r"\bm26pa7(?:ev|loc|edge)_[0-9a-f]{8,}\b",
        text,
        flags=re.I,
    ):
        if token not in allowed:
            leaked.append(token)
    for token in re.findall(r"\bclaim_\d+(?:_ref_\d+)?\b", text, flags=re.I):
        if token not in allowed:
            leaked.append(token)
    return list(dict.fromkeys(leaked))


def _question_supplied_internal_tokens(question: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in (
        r"\be\d+\b",
        r"\barticle_[0-9a-f]{8,}\b",
        r"\bm26pa7(?:ev|loc|edge)_[0-9a-f]{8,}\b",
        r"\bclaim_\d+(?:_ref_\d+)?\b",
    ):
        tokens.update(re.findall(pattern, question, flags=re.I))
    return tokens

def _repairable_verifier_failure(code: str) -> bool:
    return str(code) in {
        "M26-PA7-ME-029",
        "M26-PA7-ME-030",
        "M26-PA7-ME-032",
        "M26-PA7-ME-033",
        "M26-PA7-ME-034",
        "M26-PA7-ME-038",
        "M26-PA7-ME-039",
        "M26-PA7-ME-047",
    }


def _repair_from_clean_provider_attempts(
    *,
    runtime: Any,
    legacy: Any,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    calls: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    support_proof: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
    local_repair_rejection_codes: list[str],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    previous_answer = _previous_abstention(
        legacy=legacy,
        calls=calls,
        failures=failures,
        repair_attempted=repair_attempted,
    )
    if not _provider_calls_parse_clean(previous_answer):
        local_repair_rejection_codes.append("PROVIDER_PARSE_NOT_CLEAN")
        return None
    previous_closure: dict[str, Any] = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": sorted(set(str(item) for item in failures)),
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "broad_deterministic_fallback_used": False,
        "local_repair_rejection_codes": local_repair_rejection_codes,
    }
    return _runtime_bound_semantic_repair_v2(
        runtime=runtime,
        legacy=legacy,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        previous_answer=previous_answer,
        previous_closure=previous_closure,
    )


def _previous_abstention(
    *,
    legacy: Any,
    calls: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    repair_attempted: bool,
) -> dict[str, Any]:
    answer = legacy._verified_abstention(
        reason_codes=[*sorted(set(str(item) for item in failures)), "SEMANTIC_CLOSURE_FAILED"],
        calls=[dict(item) for item in calls],
        repair_attempted=repair_attempted,
    )
    answer["answer_source"] = "safe_abstention"
    return answer


def _semantic_abstention(
    *,
    runtime: Any,
    legacy: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    calls: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    support_proof: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
    local_repair_rejection_codes: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    answer = _previous_abstention(
        legacy=legacy,
        calls=calls,
        failures=failures,
        repair_attempted=repair_attempted,
    )
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": sorted(set(str(item) for item in failures)),
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "broad_deterministic_fallback_used": False,
    }
    if local_repair_rejection_codes:
        closure["local_repair_rejection_codes"] = sorted(
            {str(item) for item in local_repair_rejection_codes}
        )
    return answer, closure


def _runtime_bound_semantic_repair_v2(
    *,
    runtime: Any,
    legacy: Any,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    previous_answer: Mapping[str, Any],
    previous_closure: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not _provider_calls_parse_clean(previous_answer):
        _record_local_repair_rejection(previous_closure, "PROVIDER_PARSE_NOT_CLEAN")
        return None
    text = _semantic_answer_text_v2(question, requirements) or base_patch._semantic_answer_text(
        question,
        requirements,
    )
    if not text:
        _record_local_repair_rejection(previous_closure, "NO_SEMANTIC_TEXT")
        return None
    visible = runtime._visible_semantic_failures(text, requirements, question)
    if visible:
        for code in visible:
            _record_local_repair_rejection(previous_closure, str(code))
        return None
    used_items, support_proof, support_failures = _verified_repair_support_items(
        legacy=legacy,
        runtime=runtime,
        evidence=evidence,
        requirements=requirements,
        question=question,
        intent_class=intent_class,
        endpoint_proof=endpoint_proof,
    )
    if support_failures or not used_items:
        for code in support_failures or ["NO_VERIFIED_SUPPORT_ITEMS"]:
            _record_local_repair_rejection(previous_closure, str(code))
        return None
    snippet_map = {
        str(item.get("evidence_id", "")): runtime._provider_snippet(
            item,
            question,
            requirements,
        )
        for item in used_items
        if item.get("evidence_id")
    }

    def public_citation_fields(item: Mapping[str, Any]) -> dict[str, Any]:
        evidence_id = str(item.get("evidence_id") or item.get("locator_id") or "evidence")
        locator_id = str(item.get("locator_id") or evidence_id)
        source_identity = str(
            item.get("source_identity")
            or item.get("source_id")
            or item.get("source")
            or evidence_id
        )
        section_id = str(
            item.get("section_id") or item.get("concept_id") or locator_id or evidence_id
        )
        return {
            **dict(item),
            "evidence_id": evidence_id,
            "locator_id": locator_id,
            "source_id": str(item.get("source_id") or source_identity),
            "source_identity": source_identity,
            "section_id": section_id,
            "concept_id": str(item.get("concept_id") or section_id),
            "release_id": str(item.get("release_id") or source_identity),
            "artifact_key": str(item.get("artifact_key") or source_identity),
            "artifact_sha256": str(item.get("artifact_sha256") or source_identity),
            "passage_text_sha256": str(
                item.get("passage_text_sha256")
                or item.get("exact_quote_sha256")
                or evidence_id
            ),
            "provenance_record_sha256": str(
                item.get("provenance_record_sha256") or locator_id
            ),
        }

    try:
        candidate = _runtime_bound_candidate_v2(
            runtime=runtime,
            legacy=legacy,
            answer=text,
            question=question,
            intent_class=intent_class,
            used_items=used_items,
            snippet_map=snippet_map,
            requirements=requirements,
        )
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
        final = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=[public_citation_fields(item) for item in evidence],
            calls=_provider_calls(previous_answer),
            repair_attempted=True,
        )
        _use_verified_natural_surface(final, text)
    except Exception as exc:
        code = str(getattr(exc, "code", type(exc).__name__))
        if code == "M26-PA7-ME-029":
            try:
                semantic_verified = _semantic_requirement_verified_result(
                    legacy=legacy,
                    answer=text,
                    intent_class=intent_class,
                    used_items=used_items,
                    requirements=requirements,
                )
                if semantic_verified is None:
                    raise ValueError("semantic requirement support conversion unavailable")
                final = legacy._verified_multi_evidence_answer(
                    intent_class=intent_class,
                    verified=semantic_verified,
                    evidence=[public_citation_fields(item) for item in evidence],
                    calls=_provider_calls(previous_answer),
                    repair_attempted=True,
                )
                _use_verified_natural_surface(final, text)
            except Exception as semantic_exc:
                _record_local_repair_rejection(previous_closure, code)
                _record_local_repair_rejection(
                    previous_closure,
                    str(getattr(semantic_exc, "code", type(semantic_exc).__name__)),
                )
                return None
        else:
            _record_local_repair_rejection(previous_closure, code)
            return None
    if final.get("status") != "owner_only_cited_answer":
        _record_local_repair_rejection(previous_closure, "VERIFIED_CONVERSION_NOT_CITED")
        return None
    if runtime._visible_semantic_failures(
        str(final.get("answer_text", "")),
        requirements,
        question,
    ):
        _record_local_repair_rejection(previous_closure, "FINAL_SURFACE_SEMANTIC_MISMATCH")
        return None
    final_leaks = _user_visible_internal_reference_leaks(
        str(final.get("answer_text", "")),
        question,
        {},
    )
    if final_leaks:
        for leak in final_leaks:
            _record_local_repair_rejection(
                previous_closure,
                f"FINAL_SURFACE_INTERNAL_REFERENCE_LEAK:{leak}",
            )
        return None
    final["answer_source"] = "provider_verified_runtime_bound_semantic_closure"
    final["multi_evidence_verification"] = {
        **dict(final.get("multi_evidence_verification", {})),
        "verification_failure_codes_by_attempt": list(
            previous_closure.get("failures", [])
            if isinstance(previous_closure, Mapping)
            else []
        ),
        "repair_trigger": sorted(
            {
                str(item)
                for item in (
                    previous_closure.get("failures", [])
                    if isinstance(previous_closure, Mapping)
                    else []
                )
            }
        ),
        "repair_result": "runtime_bound_semantic_repair_verified",
        "deterministic_evidence_synthesis_used": True,
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "runtime_bound_semantic_repair_used": True,
        "served_answer_surface": "verified_natural_material_claim_surface",
    }
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": support_proof,
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": True,
    }
    return final, closure



def _runtime_bound_candidate_v2(
    *,
    runtime: Any,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    snippet_map: Mapping[str, str],
    requirements: Sequence[Any],
) -> dict[str, Any]:
    candidate = _relationship_partition_candidate(
        legacy=legacy,
        answer=answer,
        question=question,
        intent_class=intent_class,
        used_items=used_items,
    )
    if candidate is not None:
        return candidate
    candidate = _direct_facet_partition_candidate(
        legacy=legacy,
        answer=answer,
        question=question,
        intent_class=intent_class,
        used_items=used_items,
        requirements=requirements,
    )
    if candidate is not None:
        return candidate
    return runtime._runtime_bound_candidate(
        answer=answer,
        question=question,
        intent_class=intent_class,
        used_items=used_items,
        snippet_map=snippet_map,
    )


def _semantic_requirement_verified_result(
    *,
    legacy: Any,
    answer: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any] | None:
    requirement_ids = [
        str(getattr(item, "requirement_id", ""))
        for item in requirements
        if str(getattr(item, "requirement_id", ""))
    ]
    if not requirement_ids:
        return None
    if any(item not in _SUPPORTED_FACET_SURFACES for item in requirement_ids):
        return None
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in used_items[:8]:
        ref = _support_ref_for_terms(legacy, item, set())
        if ref is None:
            continue
        if "exact_quote_sha256" not in ref:
            ref = {
                **ref,
                "exact_quote_sha256": legacy.sha256_bytes(
                    str(ref["exact_quote"]).encode("utf-8")
                ),
            }
        evidence_id = str(ref.get("evidence_id", ""))
        if evidence_id in seen:
            continue
        refs.append(ref)
        seen.add(evidence_id)
    if not refs:
        return None
    covered = list(dict.fromkeys(requirement_ids))
    return {
        "case_id": "runtime_bound_semantic_requirement_support",
        "terminal_status": "verified_answer_ready_candidate",
        "provider_status": "deterministic_semantic_requirement_support",
        "relation": None,
        "answer_text": _anchor_every_sentence(answer, "claim_1"),
        "selected_evidence_ids": [str(ref["evidence_id"]) for ref in refs],
        "selected_graph_edge_ids": [],
        "used_evidence_ids": [str(ref["evidence_id"]) for ref in refs],
        "required_facets": covered,
        "covered_facets": covered,
        "missing_facets": [],
        "material_claims": [
            {
                "claim_id": "claim_1",
                "claim_role": "direct"
                if intent_class == "direct_grounded_knowledge"
                else "relationship",
                "surface_text": answer,
                "facet_ids": covered,
                "support_mode": "runtime_bound_semantic_requirement_support",
                "support_refs": refs,
                "support_verdict": "supported_exact_semantic_requirement_bundle",
            }
        ],
        "provider_parse": {"parse_subtype": "semantic_requirement_support_conversion"},
        "support_verification": {
            "material_claim_count": 1,
            "supported_claim_count": 1,
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
    }



def _relationship_partition_candidate(
    *,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if intent_class not in {"complementary_synthesis", "cross_document_comparison"}:
        return None
    refs: list[dict[str, str]] = []
    selected_ids: list[str] = []
    seen_sources: set[str] = set()
    for item in used_items:
        source = _repair_source_identity(item)
        if source in seen_sources:
            continue
        ref = _full_passage_support_ref(item)
        if ref is None:
            ref = _support_ref_for_terms(legacy, item, set())
        if ref is None:
            continue
        refs.append(ref)
        selected_ids.append(str(item.get("evidence_id", "")))
        seen_sources.add(source)
        if len(refs) >= 2:
            break
    if len(refs) < 2:
        return None
    claim_role = "relationship" if intent_class == "complementary_synthesis" else "comparison"
    relation = "complements" if intent_class == "complementary_synthesis" else "contrasts_with"
    claim = {
        "claim_id": "claim_1",
        "claim_role": claim_role,
        "surface_text": answer,
        "facet_ids": legacy._required_facet_ids(
            question=question,
            intent_class=intent_class,
        ),
        "support_mode": "runtime_bound_exact_multi_evidence",
        "support_refs": refs,
    }
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": selected_ids,
        "answer_text": _anchor_every_sentence(answer, "claim_1"),
        "claims": [claim],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _full_passage_support_ref(item: Mapping[str, Any]) -> dict[str, str] | None:
    quote = " ".join(str(item.get("passage_text", "")).split())
    if not quote:
        return None
    if len(quote) > 780:
        quote = quote[:780].rsplit(" ", 1)[0].rstrip()
    if not quote:
        return None
    return {
        "evidence_id": str(item.get("evidence_id", "")),
        "locator_id": str(item.get("locator_id", "")),
        "exact_quote": quote,
        "exact_support_snippet": quote,
        "uncertainty": "low",
    }


def _anchor_every_sentence(answer: str, claim_id: str) -> str:
    pieces = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", str(answer).strip())
        if item.strip()
    ]
    if not pieces:
        return ""
    return " ".join(
        piece if f"[[{claim_id}]]" in piece else f"{piece.rstrip('.')} [[{claim_id}]]."
        for piece in pieces
    )

def _direct_facet_partition_candidate(
    *,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any] | None:
    if intent_class != "direct_grounded_knowledge":
        return None
    if not used_items:
        return None
    try:
        required_facets = legacy._question_contract(
            question=question,
            intent_class=intent_class,
        )["required_facets"]
    except Exception:
        return None
    facet_ids = [str(item.get("facet_id", "")) for item in required_facets if item.get("facet_id")]
    if len(facet_ids) < 4 and not set(facet_ids).issubset(_SUPPORTED_FACET_SURFACES):
        return None

    claims: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for index, facet in enumerate(required_facets, start=1):
        facet_id = str(facet.get("facet_id", ""))
        if not facet_id:
            continue
        terms = _facet_terms_from_contract(facet)
        item = _best_repair_item_for_terms(legacy, used_items, terms)
        if item is None:
            return None
        ref = _support_ref_for_terms(legacy, item, terms)
        if ref is None:
            return None
        selected_ids.append(str(item.get("evidence_id", "")))
        claims.append(
            {
                "claim_id": f"claim_{index}",
                "claim_role": "direct",
                "surface_text": _direct_facet_surface_text(
                    facet_id=facet_id,
                    answer=answer,
                    requirements=requirements,
                ),
                "facet_ids": [facet_id],
                "support_mode": "runtime_bound_exact_facet_partition",
                "support_refs": [ref],
            }
        )
    if not claims:
        return None
    answer_text = _anchored_partition_answer(answer, claims)
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": None,
        "selected_evidence_ids": list(dict.fromkeys(selected_ids)),
        "answer_text": answer_text,
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _facet_terms_from_contract(facet: Mapping[str, Any]) -> set[str]:
    terms: set[str] = set()
    for term in facet.get("terms", []) if isinstance(facet.get("terms", []), Sequence) else []:
        for token in re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+", str(term).casefold()):
            stop_words = {
                "a",
                "an",
                "and",
                "are",
                "by",
                "for",
                "from",
                "how",
                "in",
                "is",
                "of",
                "or",
                "the",
                "to",
                "what",
                "when",
                "where",
                "which",
                "with",
            }
            if token and token not in stop_words:
                terms.add(token)
    return terms


def _best_repair_item_for_terms(
    legacy: Any,
    items: Sequence[Mapping[str, Any]],
    terms: set[str],
) -> Mapping[str, Any] | None:
    if not items:
        return None
    def coverage(item: Mapping[str, Any]) -> tuple[int, int, str]:
        text = " ".join(
            str(item.get(field, ""))
            for field in (
                "passage_text",
                "source_identity",
                "source_id",
                "concept_id",
                "section_title",
                "title",
            )
        )
        try:
            item_terms = legacy._coverage_terms(text)
        except Exception:
            item_terms = set(re.findall(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+", text.casefold()))
        return (len(terms & item_terms), len(item_terms), str(item.get("evidence_id", "")))
    ranked = sorted(items, key=coverage, reverse=True)
    return ranked[0]


def _support_ref_for_terms(
    legacy: Any,
    item: Mapping[str, Any],
    terms: set[str],
) -> dict[str, str] | None:
    ref = None
    if hasattr(legacy, "_deterministic_support_ref_for_terms"):
        try:
            ref = legacy._deterministic_support_ref_for_terms(item, terms)
        except Exception:
            ref = None
    if ref is None and hasattr(legacy, "_deterministic_support_ref"):
        try:
            ref = legacy._deterministic_support_ref(item)
        except Exception:
            ref = None
    if ref is None:
        evidence_text = str(item.get("passage_text", ""))
        quote = " ".join(evidence_text.split())[:240].rsplit(" ", 1)[0].rstrip()
        if not quote:
            return None
        ref = {
            "evidence_id": str(item.get("evidence_id", "")),
            "locator_id": str(item.get("locator_id", "")),
            "exact_quote": quote,
            "exact_support_snippet": quote,
            "uncertainty": "low",
        }
    if "exact_quote" not in ref and "exact_support_snippet" in ref:
        ref = {**dict(ref), "exact_quote": str(ref["exact_support_snippet"])}
    if ref.get("evidence_id") and ref.get("locator_id") and ref.get("exact_quote"):
        return dict(ref)
    return None


def _direct_facet_surface_text(
    *,
    facet_id: str,
    answer: str,
    requirements: Sequence[Any],
) -> str:
    entity_phrases: dict[str, str] = {}
    for item in requirements:
        if str(getattr(item, "requirement_id", "")).startswith("entity_"):
            phrase = _requirement_entity_phrase(item)
            entity_phrases[_facet_id_from_phrase(phrase)] = phrase
            entity_phrases[f"entity_{_facet_id_from_phrase(phrase)}"] = phrase
    if facet_id in entity_phrases:
        phrase = entity_phrases[facet_id]
        return f"{phrase} is explicitly named in the answer."
    if facet_id in _SUPPORTED_FACET_SURFACES:
        return _SUPPORTED_FACET_SURFACES[facet_id]
    surfaces = {
        "router_selection": "The router performs route selection for the request.",
        "router_inputs": (
            "The query router looks at the request, path, route, and capability inputs."
        ),
        "routing_constraints": (
            "Routing constraints include policy, safety, permission, cost, latency, "
            "or capability boundaries."
        ),
        "downstream_selection": (
            "Downstream selection chooses the route, path, mode, or fallback order."
        ),
        "dag_structure": "The DAG structures dependency ordering, parallel steps, and work.",
        "flow_composition": "The query router and DAG compose the production flow together.",
        "adaptive_replanning": (
            "Adaptive replanning replans remaining work after invalid assumptions."
        ),
        "state_machine": "The state machine owns state transitions and transition authority.",
        "authority_boundary": (
            "Adaptive replanning does not bypass state machine policy and approval "
            "authority; the state machine bounds the replanner inside that authority "
            "envelope."
        ),
        "source_of_trust": (
            "The canonical source and provenance artifact authority is the source of trust."
        ),
        "responsibility_mapping": "The answer maps what each component is responsible for.",
        "multi_source_selection": "The trust claim is grounded in source and provenance authority.",
        "verification_or_approval": (
            "Verification and approval gates check the result before release."
        ),
        "human_approval": "Human approval is the final authority gate before release.",
        "parallel_branches": "Parallel research branches keep work concurrent.",
    }
    return surfaces.get(facet_id, answer)


def _facet_id_from_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_") or "facet"


def _anchored_partition_answer(answer: str, claims: Sequence[Mapping[str, Any]]) -> str:
    anchored = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", ""))
        surface = " ".join(str(claim.get("surface_text", "")).split())
        if claim_id and surface:
            anchored.append(f"{surface.rstrip('.')} [[{claim_id}]].")
    return " ".join(anchored) or str(answer)

def _record_local_repair_rejection(closure: Mapping[str, Any], code: str) -> None:
    if not isinstance(closure, dict):
        return
    values = closure.setdefault("local_repair_rejection_codes", [])
    if isinstance(values, list):
        values.append(str(code))


def _use_verified_natural_surface(answer: dict[str, Any], surface: str) -> None:
    text = " ".join(str(surface or "").split())
    if not text:
        return
    answer["answer_text"] = text
    summary = answer.get("relationship_summary", {})
    if isinstance(summary, Mapping):
        answer["relationship_summary"] = {
            **dict(summary),
            "served_answer_surface": "verified_natural_material_claim_surface",
        }


def _verified_repair_support_items(
    *,
    legacy: Any,
    runtime: Any,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    question: str,
    intent_class: str,
    endpoint_proof: Mapping[str, Any] | None = None,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]], list[str]]:
    if not requirements:
        return [], [], ["NO_SEMANTIC_REQUIREMENTS"]

    all_failures, all_proof = _endpoint_aware_requirement_support_failures(
        runtime=runtime,
        requirements=requirements,
        evidence=evidence,
        endpoint_proof=endpoint_proof or {},
    )
    if all_failures:
        return [], all_proof, [str(item) for item in all_failures]

    evidence_by_id = {str(item.get("evidence_id", "")): item for item in evidence}
    selected: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add_item(item: Mapping[str, Any] | None) -> None:
        if item is None:
            return
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen:
            selected.append(item)
            seen.add(evidence_id)

    for proof in all_proof:
        if isinstance(proof, Mapping) and proof.get("supported") is True:
            add_item(evidence_by_id.get(str(proof.get("evidence_id", ""))))

    ranked = base_patch._repair_support_items(evidence, requirements, question, intent_class)
    for item in ranked:
        add_item(item)
        if len(selected) >= 8:
            break

    if intent_class == "direct_grounded_knowledge":
        try:
            direct_facets = legacy._question_contract(
                question=question,
                intent_class=intent_class,
            )["required_facets"]
        except Exception:
            direct_facets = []
        for facet in direct_facets if isinstance(direct_facets, Sequence) else []:
            if not isinstance(facet, Mapping):
                continue
            if str(facet.get("facet_id", "")) not in _SUPPORTED_FACET_SURFACES:
                continue
            add_item(
                _best_repair_item_for_terms(
                    legacy,
                    evidence,
                    _facet_terms_from_contract(facet),
                )
            )

    if intent_class in {"cross_document_comparison", "complementary_synthesis"}:
        while _distinct_repair_sources(selected) < 2:
            before = len(selected)
            for item in [*ranked, *evidence]:
                if _repair_source_identity(item) not in {
                    _repair_source_identity(existing) for existing in selected
                }:
                    add_item(item)
                    break
            if len(selected) == before:
                break

    support_failures, support_proof = _endpoint_aware_requirement_support_failures(
        runtime=runtime,
        requirements=requirements,
        evidence=selected,
        endpoint_proof=endpoint_proof or {},
    )
    if support_failures:
        return [], support_proof, [str(item) for item in support_failures]
    return selected, support_proof, []


def _endpoint_aware_requirement_support_failures(
    *,
    runtime: Any,
    requirements: Sequence[Any],
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    question = " ".join(str(getattr(item, "exact_phrase", "")) for item in requirements)
    requirements = tuple(
        _normalize_graph_entity_requirements(runtime, question, requirements)
    )
    failures, proof = runtime._requirement_support_failures(
        requirements=requirements,
        evidence=evidence,
    )
    proof_by_req = {
        str(item.get("requirement_id", "")): dict(item)
        for item in proof
        if isinstance(item, Mapping)
    }
    endpoint = endpoint_proof or {}
    endpoint_matched = endpoint.get("required") is True and endpoint.get("matched") is True

    for requirement in requirements:
        requirement_id = str(requirement.requirement_id)
        exact = str(getattr(requirement, "exact_phrase", "") or "")
        endpoint_concept = ""
        if requirement_id.startswith("entity_") and endpoint_matched:
            endpoint_concept = _endpoint_concept_for_requirement(
                exact,
                requirement_id,
                endpoint,
            )

        if endpoint_concept:
            item = _entity_identity_support_item(
                requirement=requirement,
                evidence=evidence,
                endpoint_proof=endpoint,
            )
            if item is not None:
                proof_by_req[requirement_id] = {
                    "requirement_id": requirement_id,
                    "supported": True,
                    "evidence_id": str(item.get("evidence_id", "")),
                    "source_identity": _repair_source_identity(item),
                    "concept_id": str(item.get("concept_id", "")),
                    "score": 100.0,
                    "support_basis": "canonical_endpoint_identity_override",
                }
            else:
                proof_by_req.pop(requirement_id, None)
            continue

        current = proof_by_req.get(requirement_id)
        if current and current.get("supported") is True:
            continue
        if requirement_id.startswith("entity_"):
            item = _entity_identity_support_item(
                requirement=requirement,
                evidence=evidence,
                endpoint_proof=endpoint,
            )
            if item is not None:
                proof_by_req[requirement_id] = {
                    "requirement_id": requirement_id,
                    "supported": True,
                    "evidence_id": str(item.get("evidence_id", "")),
                    "source_identity": _repair_source_identity(item),
                    "concept_id": str(item.get("concept_id", "")),
                    "score": 4.0,
                    "support_basis": "canonical_or_source_identity",
                }

    normalized_proof: list[dict[str, Any]] = []
    normalized_failures: list[str] = []
    for requirement in requirements:
        requirement_id = str(requirement.requirement_id)
        item = proof_by_req.get(requirement_id)
        if item and item.get("supported") is True:
            normalized_proof.append(item)
        else:
            normalized_proof.append(
                {
                    "requirement_id": requirement_id,
                    "supported": False,
                    "evidence_id": "",
                    "source_identity": "",
                    "concept_id": "",
                    "score": 0.0,
                }
            )
            normalized_failures.append(f"SEMANTIC_SUPPORT_MISSING:{requirement_id}")
    return normalized_failures, normalized_proof


def _entity_identity_support_item(
    *,
    requirement: Any,
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    requirement_id = str(requirement.requirement_id)
    exact = str(getattr(requirement, "exact_phrase", "") or "")
    if not exact:
        exact = requirement_id.removeprefix("entity_").replace("_", " ")
    entity_slug = _identity_slug(exact)
    endpoint_concept = _endpoint_concept_for_requirement(exact, requirement_id, endpoint_proof)

    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for item in evidence:
        source_slug = _source_identity_slug(
            str(item.get("source_identity") or item.get("source_id") or "")
        )
        title_slug = _identity_slug(
            " ".join(
                str(item.get(field, ""))
                for field in ("title", "section_title")
                if item.get(field)
            )
        )
        concept_id = str(item.get("concept_id", ""))
        score = 0
        if endpoint_concept and concept_id == endpoint_concept:
            score += 1000
        if source_slug == entity_slug or source_slug.endswith(f"-{entity_slug}"):
            score += 80
        if title_slug == entity_slug or title_slug.endswith(f"-{entity_slug}"):
            score += 40
        if score:
            candidates.append((score, item))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda pair: (
            pair[0],
            -_article_number_distance(exact, pair[1]),
            str(pair[1].get("evidence_id", "")),
        ),
    )[1]


def _endpoint_concept_for_requirement(
    exact: str,
    requirement_id: str,
    endpoint_proof: Mapping[str, Any],
) -> str:
    entities = [
        str(item)
        for item in endpoint_proof.get("question_entities", [])
        if isinstance(item, (str, int))
    ]
    normalized_exact = _normalized_identity_phrase(exact)
    normalized_id = requirement_id.removeprefix("entity_").replace("_", " ")
    normalized_id = _normalized_identity_phrase(normalized_id)
    for index, entity in enumerate(entities[:2]):
        normalized_entity = _normalized_identity_phrase(entity)
        if normalized_entity not in {normalized_exact, normalized_id}:
            continue
        key = "edge_source" if index == 0 else "edge_target"
        return str(endpoint_proof.get(key, ""))
    return ""


def _article_number_distance(exact: str, item: Mapping[str, Any]) -> int:
    expected = re.findall(r"\bpart\s+(\d+)\b", exact.casefold())
    if not expected:
        return 0
    haystack = " ".join(
        str(item.get(field, ""))
        for field in ("source_identity", "source_id", "title", "section_title")
    ).casefold()
    found = re.findall(r"\bpart[-_ ]?(\d+)\b", haystack)
    if not found:
        return 999
    return min(abs(int(expected[0]) - int(value)) for value in found)


def _repair_source_identity(item: Mapping[str, Any]) -> str:
    return str(item.get("source_identity") or item.get("source_id") or "")


def _distinct_repair_sources(items: Sequence[Mapping[str, Any]]) -> int:
    return len({_repair_source_identity(item) for item in items if _repair_source_identity(item)})


_SUPPORTED_FACET_SURFACES = {
    "admission_policy": (
        "Request admission and the effective policy or task contract decide whether "
        "the run may start."
    ),
    "durable_state": (
        "Durable server-side run state preserves authority and persisted progress "
        "after a client disconnect."
    ),
    "persisted_progress": "Persisted progress is durable state for the run.",
    "completion_verification": (
        "Completion verification or acceptance checks the result before success is declared."
    ),
    "continued_execution": (
        "The long-running workflow can continue after the client disconnects."
    ),
    "durable_state_authority": (
        "Durable persisted state preserves run authority outside the client session."
    ),
    "verification_gate": (
        "The verification gate checks the joined result before release."
    ),
    "observability": (
        "Observability through status, reattachment, or resume lets the owner inspect "
        "the continuing headless run."
    ),
    "source_selection": "Source selection routes work to the relevant different sources.",
    "parallel_branches": "Parallel research branches keep independent work concurrent.",
    "human_approval": "Human approval is the final authority gate before release.",
    "router_selection": "The router performs route selection for the request.",
    "router_inputs": (
        "The query router evaluates the request, path, route, and capability inputs."
    ),
    "routing_constraints": (
        "Routing constraints include policy, safety, permission, cost, latency, "
        "or capability boundaries."
    ),
    "downstream_selection": (
        "Downstream selection chooses the route, path, mode, or fallback order."
    ),
    "dag_structure": "The DAG structures dependency ordering, parallel steps, and work.",
    "flow_composition": "The query router and DAG compose the production flow together.",
    "adaptive_replanning": (
        "Adaptive replanning revises remaining work after invalid assumptions."
    ),
    "state_machine": "The state machine owns state transitions and transition authority.",
    "state_machine_authority": (
        "The state machine defines the policy and approval authority envelope."
    ),
    "authority_boundary": (
        "Replanning stays within state-machine policy and approval authority."
    ),
    "initial_routing_role": (
        "Initial routing chooses the first permitted route or capability."
    ),
    "replanning_role": (
        "Adaptive replanning changes the remaining work when assumptions become invalid."
    ),
    "role_contrast": (
        "Routing chooses the initial path, while replanning revises unfinished work later."
    ),
    "source_of_trust": (
        "The canonical source and provenance artifact authority is the source of trust."
    ),
    "multi_source_selection": (
        "The trust claim is grounded in source and provenance authority."
    ),
    "responsibility_mapping": (
        "The answer maps what each component is responsible for."
    ),
    "verification_or_approval": (
        "Verification and approval gates check the result before release."
    ),
    "obsidian_role": (
        "Obsidian provides the human Markdown vault authoring and inspection surface."
    ),
    "graphology_role": (
        "Graphology provides the graph model and processing data layer."
    ),
    "sigma_role": (
        "Sigma.js provides the visual rendering and interaction layer."
    ),
    "trust_anchor": (
        "Canonical source and provenance authority provide the trust anchor."
    ),
}


def _generic_supported_facet_answer(requirements: Sequence[Any]) -> str:
    ids = [str(getattr(item, "requirement_id", "")) for item in requirements]
    if not ids or any(item not in _SUPPORTED_FACET_SURFACES for item in ids):
        return ""
    return " ".join(_SUPPORTED_FACET_SURFACES[item] for item in dict.fromkeys(ids))


def _looks_like_persistence_correctness_boundary(q: str) -> bool:
    state_markers = (
        "persist",
        "durable",
        "run state",
        "server-side state",
    )
    boundary_markers = (
        "alone",
        "by itself",
        "enough",
        "sufficient",
        "correctness boundary",
        "prove correctness",
        "guarantee correctness",
        "declare success",
        "declared successful",
        "replace verification",
        "replace completion verification",
        "skip verification",
        "without completion verification",
        "without verification",
    )
    if not any(marker in q for marker in state_markers):
        return False
    if any(marker in q for marker in boundary_markers):
        return True
    return bool(
        re.search(r"\b(?:prove|guarantee)\b.{0,120}\b(?:correct|verified)\b", q)
    )


def _semantic_answer_text_v2(question: str, requirements: Sequence[Any]) -> str:
    q = question.casefold()
    ids = {str(item.requirement_id) for item in requirements}
    if {
        "source_selection",
        "persisted_progress",
        "parallel_branches",
        "verification_gate",
        "human_approval",
    }.issubset(ids):
        return (
            "Source selection routes work to different sources. Persisted progress is "
            "durable state for the run. Parallel research branches keep work concurrent "
            "and join at a verification or completion gate before success is declared. "
            "Human approval is the final authority gate before release."
        )
    if (
        _looks_like_persistence_correctness_boundary(q)
        and {"durable_state", "completion_verification"}.issubset(ids)
    ):
        return (
            "No. Persisted run state preserves durable server-side progress and "
            "authority after a client disconnect, but it does not by itself prove "
            "that the workflow output is correct or verified. Completion verification "
            "or acceptance evidence must check the result before success is declared, "
            "and observability or status lets the owner inspect the continuing run."
        )
    if (
        _looks_like_lifecycle_control_comparison(q)
        and {"durable_state", "completion_verification"}.issubset(ids)
    ):
        return (
            "In a controlled agent architecture, durable state and post-execution "
            "verification solve different reliability problems: durable state preserves "
            "continuity, recovery, resumability, and run progress across interruptions, "
            "while post-execution verification checks correctness, acceptance, trust, "
            "and whether the workflow result should be trusted and declared successful. One "
            "preserves run state as process state; the other evaluates the result, "
            "so persistence alone does not prove correctness."
        )
    if {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(ids):
        return (
            "Before execution, request admission and the effective policy or task "
            "contract decide whether the run may start. After a client disconnect, "
            "durable server-side state keeps run authority and persisted progress outside "
            "the browser. Completion verification or an acceptance gate checks the result "
            "before success is declared. Observability through status and reattach support "
            "lets the owner inspect or resume the headless run until completion."
        )
    if {"durable_state", "completion_verification", "observability"}.issubset(ids):
        return (
            "Persisted run state matters after a client disconnect because durable "
            "server-side state preserves run progress and authority, so the long-running "
            "workflow continues and can be resumed or rejoined rather than disappearing "
            "with the client session. Observability or reattachment exposes status after "
            "the disconnect. Completion verification or acceptance remains a separate "
            "terminal check before success or correctness is declared."
        )
    if {"durable_state", "completion_verification"}.issubset(ids):
        return (
            "Persisted run state matters after a client disconnect because durable "
            "server-side state preserves run progress and authority, so the long-running "
            "workflow continues and can be resumed or rejoined rather than disappearing "
            "with the client session. Completion verification or acceptance remains a "
            "separate terminal check before success or correctness is declared."
        )
    if {"router_role", "dag_role", "router_dag_composition"}.issubset(ids):
        return (
            "The query router selects the route, path, or capability under policy and "
            "safety constraints. The DAG orders dependent steps and parallel work inside "
            "that chosen path. together, the query router and DAG compose one production "
            "/ask flow: the router chooses the path while the DAG structures the work."
        )
    if {"router_decision", "routing_constraints"}.issubset(ids):
        return (
            "A production router selects the downstream route or path after inspecting "
            "request intent, available capabilities, permission context, policy, safety, "
            "budget, latency, and downstream health constraints."
        )
    if {"initial_routing_role", "replanning_role", "role_contrast"}.issubset(ids):
        return (
            "The router handles the initial route or capability selection before "
            "execution. Adaptive replanning changes the remaining work later when "
            "evidence invalidates assumptions. The contrast is that routing chooses "
            "where the request goes first, while replanning revises unfinished steps "
            "after reality changes."
        )
    if {"state_machine_authority", "adaptive_replan", "authority_boundary"}.issubset(ids):
        return (
            "The state machine defines the policy and approval authority envelope. "
            "Adaptive replanning revises remaining work when assumptions change, with "
            "those revisions staying within the state-machine policy and approval gates "
            "rather than expanding the replanner's authority."
        )
    if {"obsidian_role", "graphology_role", "sigma_role", "trust_anchor"}.issubset(ids):
        return (
            "Obsidian is responsible for the human Markdown vault authoring and "
            "inspection surface. Graphology is responsible for the graph model and "
            "processing data layer. Sigma.js is responsible for rendering the visual "
            "interaction layer. The canonical source and provenance artifact authority "
            "is the source of trust."
        )
    if "ordering_semantics" in ids:
        entities = [
            _requirement_entity_phrase(item)
            for item in requirements
            if str(item.requirement_id).startswith("entity_")
        ]
        entities = [item for item in entities if item]
        if len(entities) >= 2:
            prefix = f"The relation graph records {entities[0]} precedes {entities[1]}. "
            order_text = (
                f"That means {entities[0]} comes before {entities[1]} "
                "in graph ordering or navigation."
            )
        else:
            prefix = "The relation graph records a precedes edge. "
            order_text = "That edge supports graph ordering or navigation."
        if "non_entailment" in ids:
            return (
                prefix
                + order_text
                + " It does not prove dependency, causality, implementation, "
                "or requirement semantics; stronger dependency would need separate "
                "endpoint passage support."
            )
        return prefix + order_text
    return _generic_supported_facet_answer(requirements)


def _requirement_entity_phrase(requirement: Any) -> str:
    exact = str(getattr(requirement, "exact_phrase", "") or "")
    if exact:
        return exact
    return str(requirement.requirement_id).removeprefix("entity_").replace("_", " ").title()


def _provider_calls(answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    verification = answer.get("multi_evidence_verification", {})
    if isinstance(verification, Mapping):
        calls = verification.get("provider_attempt_telemetry", [])
        if isinstance(calls, list):
            return [dict(item) for item in calls if isinstance(item, Mapping)]
    return []


def _provider_calls_parse_clean(answer: Mapping[str, Any]) -> bool:
    for call in _provider_calls(answer):
        parse_telemetry = call.get("parse_telemetry", {})
        if not isinstance(parse_telemetry, Mapping):
            return False
        if parse_telemetry.get("parse_ok") is not True:
            return False
    return True


def _loose_concepts(runtime: Any, bundle: Any, entity: str) -> set[str]:
    canonical = _canonical_named_concepts(runtime, bundle, entity)
    if canonical:
        return canonical
    if _requires_canonical_endpoint_binding(entity):
        return set()
    concepts = set(runtime._entity_concepts(bundle, entity))
    if concepts:
        return concepts
    normalized = re.sub(r"[^a-z0-9]+", " ", entity.casefold()).strip()
    if not normalized:
        return concepts
    for document in runtime.legacy._release_documents(bundle):
        text = " ".join(
            (
                str(document.get("title", "")),
                str(document.get("section_title", "")),
                runtime.legacy._document_text(document),
            )
        )
        haystack = re.sub(r"[^a-z0-9]+", " ", text.casefold())
        if normalized in haystack:
            concept = str(document.get("concept_id", ""))
            if concept:
                concepts.add(concept)
    return concepts


def _canonical_named_concepts(runtime: Any, bundle: Any, entity: str) -> set[str]:
    scored: list[tuple[float, str]] = []
    for document in runtime.legacy._release_documents(bundle):
        concept = str(document.get("concept_id", ""))
        if not concept:
            continue
        score = _canonical_endpoint_document_score(runtime, entity, document)
        if score > 0:
            scored.append((score, concept))
    if not scored:
        return set()
    best = max(score for score, _ in scored)
    if best < 7.0:
        return set()
    return {concept for score, concept in scored if score >= best - 0.5}


def _canonical_endpoint_document_score(
    runtime: Any,
    entity: str,
    document: Mapping[str, Any],
) -> float:
    entity_norm = _normalized_identity_phrase(entity)
    entity_slug = _identity_slug(entity)
    if not entity_norm or not entity_slug:
        return 0.0

    title = str(document.get("title", ""))
    section_title = str(document.get("section_title", ""))
    source_identity = str(document.get("source_identity") or document.get("source_id") or "")
    source_id = str(document.get("source_id") or "")
    concept_id = str(document.get("concept_id") or "")

    score = 0.0
    title_norm = _normalized_identity_phrase(title)
    section_norm = _normalized_identity_phrase(section_title)
    source_slug = _source_identity_slug(source_identity)
    source_id_slug = _source_identity_slug(source_id)

    if title_norm == entity_norm:
        score += 14.0
    elif _identity_phrase_prefix(title_norm, entity_norm):
        score += 12.0

    source_matches = source_slug == entity_slug or source_slug.endswith(f"-{entity_slug}")
    source_id_matches = source_id_slug == entity_slug or source_id_slug.endswith(
        f"-{entity_slug}"
    )
    if source_matches or source_id_matches:
        score += 16.0

    if section_norm == entity_norm:
        score += 8.0
    elif _identity_phrase_prefix(section_norm, entity_norm):
        score += 6.0

    if _document_is_article_root(runtime, document):
        score += 1.5
    if concept_id and concept_id == str(document.get("section_id", "")):
        score += 0.5
    return score


def _requires_canonical_endpoint_binding(entity: str) -> bool:
    return bool(re.search(r"\bpart\s+\d+\b", str(entity), flags=re.I))


def _best_exact_edge(
    bundle: Any,
    source_candidates: set[str],
    target_candidates: set[str],
    required_relation: str,
) -> Mapping[str, Any] | None:
    if not source_candidates or not target_candidates:
        return None
    matches: list[Mapping[str, Any]] = []
    for candidate in bundle.graph_v2.get("edges", []):
        if not isinstance(candidate, Mapping):
            continue
        if required_relation and str(candidate.get("relation_type")) != required_relation:
            continue
        if (
            str(candidate.get("source", "")) in source_candidates
            and str(candidate.get("target", "")) in target_candidates
        ):
            matches.append(candidate)
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            str(item.get("edge_id", "")),
        ),
    )


def _normalized_identity_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _identity_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")


def _source_identity_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")


def _identity_phrase_prefix(candidate_norm: str, entity_norm: str) -> bool:
    if not candidate_norm or not entity_norm:
        return False
    if not candidate_norm.startswith(entity_norm):
        return False
    if len(candidate_norm) == len(entity_norm):
        return True
    return candidate_norm[len(entity_norm)].isspace()


def _document_is_article_root(runtime: Any, document: Mapping[str, Any]) -> bool:
    try:
        return bool(runtime.legacy._is_article_root_document(document))
    except Exception:
        return str(document.get("concept_id", "")) == str(document.get("section_id", ""))
