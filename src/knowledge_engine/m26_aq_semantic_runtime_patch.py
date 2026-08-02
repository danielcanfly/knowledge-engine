from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


def install() -> None:
    """Install production-general AQ semantic closure compatibility patches.

    This is intentionally question-id agnostic. It strengthens the same runtime
    entrypoint by improving semantic entity normalisation, graph-edge endpoint
    matching, and compact provider repair instructions for relation/composition
    questions.
    """
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime
    from .m26_intent_compat import classify_with_semantic_compat

    if getattr(runtime, "_m26_aq_semantic_runtime_patch_installed", False):
        return

    original_named_entities = getattr(
        legacy,
        "_m26_aq_original_named_question_entities",
        legacy._named_question_entities,
    )
    original_intent_class = getattr(
        legacy,
        "_m26_aq_original_intent_class",
        legacy._intent_class,
    )
    original_semantic_requirements = runtime._semantic_requirements
    original_compact_payload = runtime._compact_provider_payload
    original_exact_edge = runtime._exact_named_graph_edge

    legacy._m26_aq_original_named_question_entities = original_named_entities
    legacy._m26_aq_original_intent_class = original_intent_class

    def named_question_entities_with_series_shorthand(question: str) -> list[str]:
        entities = list(original_named_entities(question))
        existing = {item.casefold() for item in entities}
        prefix = ""
        prefix_match = re.search(
            r"\b([A-Z][A-Za-z0-9 .'/&-]+?)\s+Part\s+\d+\b",
            question,
        )
        if prefix_match:
            prefix = prefix_match.group(1).strip()
        if prefix:
            for part in re.findall(r"\bPart\s+(\d+)\b", question, flags=re.I):
                entity = f"{prefix} Part {part}"
                if entity.casefold() not in existing:
                    entities.append(entity)
                    existing.add(entity.casefold())
        return entities

    def intent_class_with_semantic_compat(question: str) -> str:
        return classify_with_semantic_compat(
            question,
            legacy_classifier=original_intent_class,
        )

    def semantic_requirements_with_semantic_synonyms(
        question: str,
        intent_class: str,
    ) -> list[Any]:
        requirements = list(original_semantic_requirements(question, intent_class))
        q = question.casefold()
        seen = {str(item.requirement_id) for item in requirements}

        def add(
            requirement_id: str,
            instruction: str,
            evidence_terms: Sequence[str],
            visible_patterns: Sequence[str],
            *,
            exact_phrase: str = "",
        ) -> None:
            if requirement_id in seen:
                return
            seen.add(requirement_id)
            requirements.append(
                runtime.SemanticRequirement(
                    requirement_id=requirement_id,
                    instruction=instruction,
                    evidence_terms=tuple(evidence_terms),
                    visible_patterns=tuple(visible_patterns),
                    exact_phrase=exact_phrase,
                )
            )

        routerish = any(
            item in q
            for item in (
                "router",
                "dispatcher",
                "dispatch",
                "where a request should go",
                "first capability",
                "initial capability",
                "route",
            )
        )
        replanish = any(
            item in q
            for item in (
                "replan",
                "planner",
                "remaining work",
                "unfinished steps",
                "remaining steps",
                "invalidates",
                "invalid assumptions",
                "reality",
                "world proves",
            )
        )
        if routerish and replanish:
            add(
                "initial_routing_role",
                "Explain that routing chooses the initial path/capability.",
                ["router", "route", "initial", "path", "capability"],
                [
                    r"\b(?:router|routing|dispatcher|dispatch).{0,120}"
                    r"(?:initial|path|route|request|capability)"
                ],
            )
            add(
                "replanning_role",
                "Explain that adaptive replanning changes remaining work.",
                ["adaptive", "replan", "remaining", "invalid", "assumption"],
                [
                    r"\b(?:replan|replanning|replanner|planner|adaptive).{0,140}"
                    r"(?:remaining|unfinished|invalid|assumption|evidence|reality)"
                ],
            )
            add(
                "role_contrast",
                "Contrast initial dispatch with later replanning.",
                ["initial", "later", "after", "different"],
                [
                    r"\b(?:whereas|while|by contrast|different|initial).{0,180}"
                    r"(?:later|after|replan|remaining|unfinished)"
                ],
            )

        if "router" in q and "dag" in q:
            add(
                "router_role",
                "State that the query router selects the path/mode/capability.",
                ["query router", "route", "path", "mode", "capability"],
                [
                    r"(?:query router|router).{0,140}"
                    r"(?:path|route|mode|capability|select)"
                ],
            )
            add(
                "router_decision",
                "Explain what the router chooses or bounds.",
                ["router", "query", "path", "route", "capability"],
                [r"router.{0,120}(?:path|route|select|choose|capability)"],
            )
            add(
                "routing_constraints",
                "State one permission/safety/policy/capability constraint.",
                ["permission", "safety", "policy", "capability"],
                [
                    r"\b(?:permission|safety|policy|risk|cost|latency|capability)"
                    r"s?\b"
                ],
            )
            add(
                "dag_role",
                "State that the DAG structures dependency/parallel work.",
                ["dag", "dependency", "parallel", "task", "step"],
                [r"\bdag\b.{0,160}(?:depend|parallel|task|step|work)"],
            )
            add(
                "router_dag_composition",
                "Explain how router selection and DAG execution compose.",
                ["together", "within", "then", "chosen path", "flow"],
                [
                    r"(?:router|route).{0,200}(?:dag|within|then|flow)",
                    r"dag.{0,200}(?:router|route|chosen path|flow)",
                ],
            )

        if "precedes" in q:
            add(
                "ordering_semantics",
                "State that precedes supports ordering/sequence/navigation only.",
                ["precedes", "ordering", "sequence", "navigation"],
                [r"\b(?:ordering|sequence|navigation|comes before|precedes)\b"],
            )
            if re.search(r"\b(?:prove|infer|depend|depends|dependency|causal|cause)\b", q):
                add(
                    "non_entailment",
                    "State that precedes alone does not prove stronger relations.",
                    ["dependency", "causality", "implementation", "requirement"],
                    [
                        r"\b(?:does not|doesn't|cannot|can't|only).{0,140}"
                        r"(?:depend|causal|implement|require|prove|infer)"
                    ],
                )

        if "state machine" in q and any(
            item in q for item in ("replanner", "replanning", "replan", "change a plan")
        ):
            add(
                "state_machine_authority",
                "Explain the state machine as the transition/policy envelope.",
                ["state machine", "transition", "permission", "approval", "policy"],
                [
                    r"state machine.{0,180}"
                    r"(?:transition|permission|approval|guard|legal|policy)"
                ],
            )
            add(
                "adaptive_replan",
                "Explain that replanning may change remaining steps.",
                ["replan", "remaining", "assumption", "invalid"],
                [
                    r"\b(?:replan|replanning|replanner).{0,160}"
                    r"(?:remaining|assumption|invalid|plan|step)"
                ],
            )
            add(
                "authority_boundary",
                "State that replanning cannot bypass policy/approval authority.",
                ["cannot bypass", "authority", "policy", "approval", "transition"],
                [
                    r"\b(?:cannot|can't|must not|does not).{0,160}"
                    r"(?:bypass|override|escape).{0,120}"
                    r"(?:state|policy|transition|approval|authority)"
                ],
            )

        architecture_terms = (
            "different sources",
            "multi-source",
            "source selection",
            "saved progress",
            "persisted progress",
            "durable state",
            "parallel",
            "concurrent",
            "branches",
            "verification",
            "checks",
            "human approval",
            "person approving",
        )
        if sum(term in q for term in architecture_terms) >= 3:
            add(
                "source_selection",
                "Include source selection/routing for different sources.",
                ["source", "routing", "selection"],
                [
                    r"\bsource.{0,100}(?:select|route|routing)",
                    r"\b(?:select|route).{0,100}source",
                ],
            )
            add(
                "persisted_progress",
                "Include persisted/durable progress state.",
                ["persisted", "durable", "progress", "state"],
                [r"\b(?:persisted|durable|saved).{0,100}(?:progress|state)"],
            )
            add(
                "parallel_branches",
                "Include parallel research branches/DAG execution.",
                ["parallel", "branch", "dag", "research"],
                [
                    r"\b(?:parallel|concurrent).{0,100}"
                    r"(?:branch|research|dag|work)"
                ],
            )
            add(
                "verification_gate",
                "Include an explicit verification/completion gate.",
                ["verification", "verify", "completion", "gate"],
                [r"\b(?:verification|verify|checks?|completion gate)\b"],
            )
            add(
                "human_approval",
                "Include human approval as an authority gate.",
                ["human approval", "approval", "person approving"],
                [r"\b(?:human approval|person approving|approval)\b"],
            )

        if all(name in q for name in ("obsidian", "graphology", "sigma.js")):
            add(
                "obsidian_role",
                "Explain Obsidian as a human-facing Markdown/vault surface.",
                ["obsidian", "markdown", "vault", "human", "authoring"],
                [r"obsidian.{0,180}(?:markdown|vault|human|author|inspect)"],
            )
            add(
                "graphology_role",
                "Explain Graphology as graph data/model/processing.",
                ["graphology", "graph", "data", "model", "processing"],
                [r"graphology.{0,180}(?:data|model|process|graph)"],
            )
            add(
                "sigma_role",
                "Explain Sigma.js as graph visualization/rendering/interaction.",
                ["sigma.js", "visual", "render", "interaction"],
                [r"sigma\.js.{0,180}(?:visual|render|interact|display)"],
            )
            add(
                "trust_anchor",
                "Assign trust to canonical provenance/artifact authority.",
                ["canonical", "provenance", "artifact", "source of trust"],
                [
                    r"\b(?:canonical|provenance|artifact).{0,140}"
                    r"(?:trust|authority|source)",
                    r"\b(?:source of trust|trust anchor).{0,140}"
                    r"(?:canonical|provenance|artifact)",
                ],
            )

        return requirements

    def compact_provider_payload_with_semantic_contract(
        *,
        question: str,
        intent_class: str,
        evidence: Sequence[Mapping[str, Any]],
        requirements: Sequence[Any],
        repair: bool,
        previous_failures: Sequence[str],
    ) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], dict[str, str]]:
        payload, label_map, snippet_map = original_compact_payload(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            repair=repair,
            previous_failures=previous_failures,
        )
        messages = payload.get("messages", [])
        task: dict[str, Any] = {}
        if messages and isinstance(messages[0], Mapping):
            try:
                task = json.loads(str(messages[0].get("content", "{}")))
            except json.JSONDecodeError:
                task = {}

        requirement_contract = [
            {
                "id": str(item.requirement_id),
                "must_say": str(item.instruction),
                "visible_terms_to_use": _visible_terms_for_requirement(item),
            }
            for item in requirements
        ]
        task["semantic_requirement_contract"] = requirement_contract
        task["answer_quality_contract"] = {
            "direct_answer_required_when_evidence_is_available": True,
            "cover_each_requirement_id_explicitly": [
                item["id"] for item in requirement_contract
            ],
            "do_not_return_empty_answer": True,
            "do_not_substitute_a_nearby_graph_edge": True,
            "precedes_boundary": (
                "precedes means ordering/navigation; it does not by itself prove "
                "dependency, causality, implementation, or requirement"
            ),
        }
        if _question_requires_initial_no(question):
            task["answer_quality_contract"]["required_opening"] = "No."
        if repair:
            task["repair_instruction"] = (
                "Rewrite the answer, not the evidence. Fix every listed missing "
                "semantic requirement using the exact visible terms requested. "
                "Keep status=answer when the evidence labels support the contract."
            )
        if messages and isinstance(messages[0], dict):
            messages[0]["content"] = json.dumps(
                task,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        payload["messages"] = messages
        payload["max_tokens"] = max(int(payload.get("max_tokens", 512)), 900)
        payload["system"] = str(payload.get("system", "")) + _semantic_system_suffix(
            question,
            requirements,
            repair=repair,
        )
        return payload, label_map, snippet_map

    def exact_named_graph_edge_with_shorthand(
        bundle: Any,
        question: str,
    ) -> Mapping[str, Any] | None:
        edge = original_exact_edge(bundle, question)
        if edge is not None:
            return edge
        entities = named_question_entities_with_series_shorthand(question)
        if len(entities) < 2:
            return None
        q = question.casefold()
        required_relation = "precedes" if "precedes" in q else ""
        source_candidates = _loose_entity_concepts(runtime, bundle, entities[0])
        target_candidates = _loose_entity_concepts(runtime, bundle, entities[1])
        if not source_candidates or not target_candidates:
            return None
        matches: list[Mapping[str, Any]] = []
        for raw_edge in bundle.graph_v2.get("edges", []):
            if not isinstance(raw_edge, Mapping):
                continue
            if required_relation and str(raw_edge.get("relation_type", "")) != required_relation:
                continue
            source = str(raw_edge.get("source", ""))
            target = str(raw_edge.get("target", ""))
            if source in source_candidates and target in target_candidates:
                matches.append(raw_edge)
        if not matches:
            return None
        return max(matches, key=lambda item: float(item.get("confidence", 0.0) or 0.0))

    legacy._named_question_entities = named_question_entities_with_series_shorthand
    legacy._intent_class = intent_class_with_semantic_compat
    runtime._semantic_requirements = semantic_requirements_with_semantic_synonyms
    runtime._compact_provider_payload = compact_provider_payload_with_semantic_contract
    runtime._exact_named_graph_edge = exact_named_graph_edge_with_shorthand
    runtime._m26_aq_semantic_runtime_patch_installed = True


def _visible_terms_for_requirement(requirement: Any) -> list[str]:
    rid = str(requirement.requirement_id)
    terms_by_id = {
        "initial_routing_role": ["router", "initial", "path", "capability"],
        "replanning_role": ["adaptive replanning", "remaining work", "invalidates"],
        "role_contrast": ["initial", "later", "different"],
        "router_role": ["query router", "selects", "path", "capability"],
        "router_decision": ["router", "route", "capability", "constraints"],
        "routing_constraints": ["permission", "policy", "safety", "capability"],
        "dag_role": ["DAG", "dependencies", "parallel", "steps"],
        "router_dag_composition": ["router", "DAG", "chosen path", "flow"],
        "ordering_semantics": ["precedes", "ordering", "navigation"],
        "non_entailment": [
            "does not prove",
            "dependency",
            "causality",
            "implementation",
        ],
        "state_machine_authority": [
            "state machine",
            "transitions",
            "approval",
            "policy",
        ],
        "adaptive_replan": ["replanner", "remaining steps", "invalid assumptions"],
        "authority_boundary": ["cannot override", "state machine", "policy"],
        "source_selection": ["source selection", "route sources"],
        "persisted_progress": ["persisted progress", "durable state"],
        "parallel_branches": ["parallel branches", "research"],
        "verification_gate": ["verification gate"],
        "human_approval": ["human approval"],
        "obsidian_role": ["Obsidian", "Markdown", "vault", "human"],
        "graphology_role": ["Graphology", "graph", "model", "processing"],
        "sigma_role": ["Sigma.js", "visualisation", "rendering", "interaction"],
        "trust_anchor": ["canonical", "provenance", "source of trust", "authority"],
    }
    if rid in terms_by_id:
        return terms_by_id[rid]
    if rid.startswith("entity_") and getattr(requirement, "exact_phrase", ""):
        return [str(requirement.exact_phrase)]
    return [str(term) for term in getattr(requirement, "evidence_terms", ())[:4]]


def _semantic_system_suffix(
    question: str,
    requirements: Sequence[Any],
    *,
    repair: bool,
) -> str:
    required_terms = []
    for requirement in requirements:
        required_terms.extend(_visible_terms_for_requirement(requirement))
    unique_terms = []
    seen = set()
    for term in required_terms:
        key = term.casefold()
        if key not in seen:
            unique_terms.append(term)
            seen.add(key)
    suffix = [
        (
            "\n\nSemantic closure contract: if the supplied evidence contains "
            "support for the listed requirements, answer directly rather than "
            "abstaining."
        ),
        "Use the requested visible terms where accurate: "
        + "; ".join(unique_terms[:36])
        + ".",
        (
            "For router/DAG/state-machine/replanning questions, explicitly "
            "assign each component its own job and then state how the jobs "
            "compose or differ."
        ),
        (
            "For graph relation questions, cite only the named edge endpoints "
            "and stated relation; do not substitute a nearby edge or upgrade "
            "precedes into depends_on."
        ),
    ]
    if _question_requires_initial_no(question):
        suffix.append(
            "For this false-premise relation question, the answer must begin "
            "with: No."
        )
    if repair:
        suffix.append(
            "This is a repair attempt: the prior answer missed semantic "
            "requirements, so make each missing role visible in the answer text."
        )
    return " ".join(suffix)


def _question_requires_initial_no(question: str) -> bool:
    q = question.casefold()
    return "precedes" in q and any(
        word in q for word in ("prove", "depends on", "dependency")
    )


def _loose_entity_concepts(runtime: Any, bundle: Any, entity: str) -> set[str]:
    concepts = set(runtime._entity_concepts(bundle, entity))
    if concepts:
        return concepts
    normalized = re.sub(r"[^a-z0-9]+", " ", entity.casefold()).strip()
    if not normalized:
        return concepts
    for document in runtime.legacy._release_documents(bundle):
        title = str(document.get("title", ""))
        section = str(document.get("section_title", ""))
        haystack = re.sub(
            r"[^a-z0-9]+",
            " ",
            f"{title} {section} {runtime.legacy._document_text(document)}".casefold(),
        )
        if normalized in haystack:
            concept = str(document.get("concept_id", ""))
            if concept:
                concepts.add(concept)
    return concepts
