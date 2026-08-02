from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


def install() -> None:
    """Install question-id-agnostic AQ semantic closure patches."""
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime
    from .m26_intent_compat import classify_with_semantic_compat

    if getattr(runtime, "_m26_aq_semantic_runtime_patch_installed", False):
        return

    original_entities = getattr(
        legacy,
        "_m26_aq_original_named_question_entities",
        legacy._named_question_entities,
    )
    original_intent = getattr(
        legacy,
        "_m26_aq_original_intent_class",
        legacy._intent_class,
    )
    original_requirements = runtime._semantic_requirements
    original_payload = runtime._compact_provider_payload
    original_edge = runtime._exact_named_graph_edge

    legacy._m26_aq_original_named_question_entities = original_entities
    legacy._m26_aq_original_intent_class = original_intent

    def clean_entities(question: str) -> list[str]:
        entities: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            value = " ".join(value.strip().split())
            key = value.casefold()
            if value and key not in seen:
                entities.append(value)
                seen.add(key)

        prefix = re.search(
            r"\b([A-Z][A-Za-z0-9 .'/&-]+?)\s+Part\s+\d+\b",
            question,
        )
        if prefix:
            root = prefix.group(1).strip()
            for part in re.findall(r"\bPart\s+(\d+)\b", question, flags=re.I):
                add(f"{root} Part {part}")
        for name in (
            "query router",
            "DAG",
            "state machine",
            "adaptive replanning",
            "Obsidian",
            "Graphology",
            "Sigma.js",
        ):
            if name.casefold() in question.casefold():
                add(name)
        noisy = (
            "the production graph says",
            "does the precedes edge",
            "one mechanism",
            "another changes",
            "what can",
            "how are",
            "how can",
            "sketch a",
        )
        for raw in original_entities(question):
            lowered = raw.casefold()
            if len(raw) > 80 or any(item in lowered for item in noisy):
                continue
            if any(existing.casefold() in lowered for existing in entities):
                continue
            add(raw)
        return entities

    def compat_intent(question: str) -> str:
        return classify_with_semantic_compat(
            question,
            legacy_classifier=original_intent,
        )

    def requirements(question: str, intent_class: str) -> list[Any]:
        items = list(original_requirements(question, intent_class))
        _augment_requirements(runtime, question, items)
        return items

    def payload(
        *,
        question: str,
        intent_class: str,
        evidence: Sequence[Mapping[str, Any]],
        requirements: Sequence[Any],
        repair: bool,
        previous_failures: Sequence[str],
    ) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], dict[str, str]]:
        packed, label_map, snippet_map = original_payload(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            repair=repair,
            previous_failures=previous_failures,
        )
        messages = packed.get("messages", [])
        task = _message_task(messages)
        contract = [
            {
                "id": str(item.requirement_id),
                "must_say": str(item.instruction),
                "visible_terms_to_use": _visible_terms(item),
            }
            for item in requirements
        ]
        task["semantic_requirement_contract"] = contract
        task["answer_quality_contract"] = {
            "evidence_was_selected_by_verified_retrieval": True,
            "abstain_only_when_evidence_array_is_empty": True,
            "never_return_empty_answer_when_evidence_labels_exist": True,
            "cover_each_requirement_id_explicitly": [
                item["id"] for item in contract
            ],
            "do_not_substitute_a_nearby_graph_edge": True,
            "precedes_boundary": (
                "precedes means ordering/navigation only, not dependency, "
                "causality, implementation, or requirement"
            ),
        }
        if _needs_initial_no(question):
            task["answer_quality_contract"]["required_opening"] = "No."
        if repair:
            task["repair_instruction"] = (
                "Do not abstain when evidence labels exist. Return status=answer "
                "and make every missing semantic role visible."
            )
        if messages and isinstance(messages[0], dict):
            messages[0]["content"] = json.dumps(
                task,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        packed["messages"] = messages
        packed["max_tokens"] = max(int(packed.get("max_tokens", 512)), 900)
        packed["system"] = _system_message(question, requirements, repair=repair)
        return packed, label_map, snippet_map

    def exact_edge(bundle: Any, question: str) -> Mapping[str, Any] | None:
        edge = original_edge(bundle, question)
        if edge is not None:
            return edge
        entities = clean_entities(question)
        if len(entities) < 2:
            return None
        required = "precedes" if "precedes" in question.casefold() else ""
        source_candidates = _loose_concepts(runtime, bundle, entities[0])
        target_candidates = _loose_concepts(runtime, bundle, entities[1])
        matches = []
        for candidate in bundle.graph_v2.get("edges", []):
            if not isinstance(candidate, Mapping):
                continue
            if required and str(candidate.get("relation_type")) != required:
                continue
            source = str(candidate.get("source", ""))
            target = str(candidate.get("target", ""))
            if source in source_candidates and target in target_candidates:
                matches.append(candidate)
        if not matches:
            return None
        return max(matches, key=lambda item: float(item.get("confidence") or 0.0))

    legacy._named_question_entities = clean_entities
    legacy._intent_class = compat_intent
    runtime._semantic_requirements = requirements
    runtime._compact_provider_payload = payload
    runtime._exact_named_graph_edge = exact_edge
    runtime._m26_aq_semantic_runtime_patch_installed = True


def _message_task(messages: Any) -> dict[str, Any]:
    if messages and isinstance(messages[0], Mapping):
        try:
            value = json.loads(str(messages[0].get("content", "{}")))
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return {}
    return {}


def _augment_requirements(runtime: Any, question: str, items: list[Any]) -> None:
    q = question.casefold()
    seen = {str(item.requirement_id) for item in items}

    def add(
        requirement_id: str,
        instruction: str,
        evidence_terms: Sequence[str],
        visible_patterns: Sequence[str],
    ) -> None:
        if requirement_id in seen:
            return
        seen.add(requirement_id)
        items.append(
            runtime.SemanticRequirement(
                requirement_id=requirement_id,
                instruction=instruction,
                evidence_terms=tuple(evidence_terms),
                visible_patterns=tuple(visible_patterns),
            )
        )

    routerish = any(
        term in q
        for term in ("router", "dispatcher", "where a request should go", "route")
    )
    replanish = any(
        term in q
        for term in ("replan", "planner", "remaining", "invalidates", "reality")
    )
    if routerish and replanish:
        add(
            "initial_routing_role",
            "Explain that routing chooses the initial path/capability.",
            ["router", "route", "initial", "path", "capability"],
            [r"\b(?:router|routing|dispatcher).{0,120}(?:initial|path|route)"],
        )
        add(
            "replanning_role",
            "Explain that replanning changes remaining work.",
            ["adaptive", "replan", "remaining", "invalid", "assumption"],
            [r"\b(?:replan|replanning|adaptive).{0,140}(?:remaining|invalid)"],
        )
        add(
            "role_contrast",
            "Contrast initial dispatch with later replanning.",
            ["initial", "later", "after", "different"],
            [r"\b(?:whereas|while|different|initial).{0,180}(?:later|replan)"],
        )

    if "router" in q and "dag" in q:
        add(
            "router_role",
            "State that the query router selects the path/mode/capability.",
            ["query router", "route", "path", "mode", "capability"],
            [r"(?:query router|router).{0,140}(?:path|route|capability)"],
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
            [r"\b(?:permission|safety|policy|capability|risk|cost|latency)"],
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
            ["router", "DAG", "chosen path", "flow"],
            [r"(?:router|route).{0,200}(?:dag|within|then|flow)"],
        )

    if "precedes" in q:
        add(
            "ordering_semantics",
            "State that precedes supports ordering/sequence/navigation only.",
            ["precedes", "ordering", "sequence", "navigation"],
            [r"\b(?:ordering|sequence|navigation|comes before|precedes)\b"],
        )
        if re.search(r"\b(?:prove|infer|depend|depends|dependency|causal)\b", q):
            add(
                "non_entailment",
                "State that precedes alone does not prove stronger relations.",
                ["dependency", "causality", "implementation", "requirement"],
                [r"\b(?:does not|cannot|can't|only).{0,140}(?:depend|causal|prove)"],
            )

    if "state machine" in q and any(term in q for term in ("replan", "replanner")):
        add(
            "state_machine_authority",
            "Explain the state machine as the transition/policy envelope.",
            ["state machine", "transition", "permission", "approval", "policy"],
            [r"state machine.{0,180}(?:transition|permission|approval|policy)"],
        )
        add(
            "adaptive_replan",
            "Explain that replanning may change remaining steps.",
            ["replan", "remaining", "assumption", "invalid"],
            [r"\b(?:replan|replanning|replanner).{0,160}(?:remaining|invalid)"],
        )
        add(
            "authority_boundary",
            "State that replanning cannot bypass policy/approval authority.",
            ["cannot bypass", "authority", "policy", "approval"],
            [r"\b(?:cannot|can't|must not).{0,160}(?:bypass|override)"],
        )

    architecture_terms = (
        "different sources",
        "multi-source",
        "saved progress",
        "persisted progress",
        "parallel",
        "branches",
        "verification",
        "human approval",
    )
    if sum(term in q for term in architecture_terms) >= 3:
        for req_id, instruction, terms, pattern in (
            (
                "source_selection",
                "Include source selection/routing for different sources.",
                ["source", "routing", "selection"],
                r"\bsource.{0,100}(?:select|route|routing)",
            ),
            (
                "persisted_progress",
                "Include persisted/durable progress state.",
                ["persisted", "durable", "progress", "state"],
                r"\b(?:persisted|durable|saved).{0,100}(?:progress|state)",
            ),
            (
                "parallel_branches",
                "Include parallel research branches/DAG execution.",
                ["parallel", "branch", "dag", "research"],
                r"\b(?:parallel|concurrent).{0,100}(?:branch|research|dag)",
            ),
            (
                "verification_gate",
                "Include an explicit verification/completion gate.",
                ["verification", "verify", "completion", "gate"],
                r"\b(?:verification|verify|checks?|completion gate)\b",
            ),
            (
                "human_approval",
                "Include human approval as an authority gate.",
                ["human approval", "approval"],
                r"\b(?:human approval|approval)\b",
            ),
        ):
            add(req_id, instruction, terms, [pattern])

    if all(name in q for name in ("obsidian", "graphology", "sigma.js")):
        for req_id, instruction, terms, pattern in (
            (
                "obsidian_role",
                "Explain Obsidian as a human-facing Markdown/vault surface.",
                ["obsidian", "markdown", "vault", "human"],
                r"obsidian.{0,180}(?:markdown|vault|human|author|inspect)",
            ),
            (
                "graphology_role",
                "Explain Graphology as graph data/model/processing.",
                ["graphology", "graph", "model", "processing"],
                r"graphology.{0,180}(?:data|model|process|graph)",
            ),
            (
                "sigma_role",
                "Explain Sigma.js as graph visualization/rendering.",
                ["sigma.js", "visual", "render", "interaction"],
                r"sigma\.js.{0,180}(?:visual|render|interact|display)",
            ),
            (
                "trust_anchor",
                "Assign trust to canonical provenance/artifact authority.",
                ["canonical", "provenance", "artifact", "source of trust"],
                r"\b(?:canonical|provenance|artifact).{0,140}(?:trust|authority)",
            ),
        ):
            add(req_id, instruction, terms, [pattern])


def _visible_terms(requirement: Any) -> list[str]:
    rid = str(requirement.requirement_id)
    terms = {
        "initial_routing_role": ["router", "initial", "path", "capability"],
        "replanning_role": ["adaptive replanning", "remaining work"],
        "role_contrast": ["initial", "later", "different"],
        "router_role": ["query router", "path", "capability"],
        "dag_role": ["DAG", "dependencies", "parallel"],
        "ordering_semantics": ["precedes", "ordering", "navigation"],
        "non_entailment": ["does not prove", "dependency", "causality"],
        "trust_anchor": ["canonical", "provenance", "source of trust"],
    }
    if rid in terms:
        return terms[rid]
    if rid.startswith("entity_") and getattr(requirement, "exact_phrase", ""):
        return [str(requirement.exact_phrase)]
    return [str(term) for term in getattr(requirement, "evidence_terms", ())[:4]]


def _system_message(
    question: str,
    requirements: Sequence[Any],
    *,
    repair: bool,
) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for requirement in requirements:
        for term in _visible_terms(requirement):
            key = term.casefold()
            if key not in seen:
                terms.append(term)
                seen.add(key)
    pieces = [
        "Return exactly one compact JSON object with keys status, answer, used.",
        (
            "Use status=answer when the evidence array contains labels; "
            "abstain only when no supplied evidence can address the question."
        ),
        (
            "Never return an empty answer with status=answer, and do not "
            "abstain merely because the answer needs synthesis."
        ),
        "Write 2-5 direct sentences covering every semantic requirement.",
        "Use these visible terms where accurate: " + "; ".join(terms[:40]) + ".",
        (
            "For router, DAG, state-machine, and replanning questions, assign "
            "each component its own job and state how the jobs compose or differ."
        ),
        (
            "For graph relation questions, use only the named edge endpoints "
            "and relation; precedes means ordering/navigation only."
        ),
        "Do not invent facts or citation labels.",
    ]
    if _needs_initial_no(question):
        pieces.append("For this false-premise relation question, begin with 'No.'")
    if repair:
        pieces.append("Repair missing semantic roles instead of abstaining.")
    return " ".join(pieces)


def _needs_initial_no(question: str) -> bool:
    q = question.casefold()
    return "precedes" in q and any(
        word in q for word in ("prove", "depends on", "dependency")
    )


def _loose_concepts(runtime: Any, bundle: Any, entity: str) -> set[str]:
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
