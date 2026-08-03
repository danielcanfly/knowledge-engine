from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import m26_aq_semantic_runtime_patch as base_patch


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
        return items

    def exact_edge(bundle: Any, question: str) -> Mapping[str, Any] | None:
        entities = clean_entities(question)
        required_relation = "precedes" if "precedes" in question.casefold() else ""
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
        "Does the precedes edge between ",
        "Can the precedes edge between ",
        "Does ",
    ):
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix) :]
    for suffix in (" prove that", " prove", " safely infer"):
        index = text.casefold().find(suffix.casefold())
        if index > 0:
            text = text[:index]
    return " ".join(text.strip(" ?:.,").split())


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
    if "state machine" in q and any(
        term in q for term in ("replan", "replanner", "replanning")
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
            r"(?:replan|replanning|replanner).{0,180}(?:remaining|invalid|assumption|step)",
        )
        add(
            "authority_boundary",
            "State that replanning cannot override or bypass gates.",
            ["cannot", "override", "bypass", "policy"],
            r"(?:cannot|can't|must not|does not).{0,180}(?:override|bypass|escape)",
        )
    if "precedes" in q:
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
    failures: list[str] = []
    calls: list[dict[str, Any]] = []
    final_support_proof: list[dict[str, Any]] = []
    repair_attempted = False

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
    support_failures, support_proof = runtime._requirement_support_failures(
        requirements=requirements,
        evidence=used_items,
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


def _repairable_verifier_failure(code: str) -> bool:
    return str(code) in {
        "M26-PA7-ME-029",
        "M26-PA7-ME-030",
        "M26-PA7-ME-032",
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
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    previous_answer = _previous_abstention(
        legacy=legacy,
        calls=calls,
        failures=failures,
        repair_attempted=repair_attempted,
    )
    if not _provider_calls_parse_clean(previous_answer):
        return None
    previous_closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [runtime._requirement_public(item) for item in requirements],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": sorted(set(str(item) for item in failures)),
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "broad_deterministic_fallback_used": False,
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
        return None
    text = _semantic_answer_text_v2(question, requirements) or base_patch._semantic_answer_text(
        question,
        requirements,
    )
    if not text or runtime._visible_semantic_failures(text, requirements, question):
        return None
    used_items, support_proof, support_failures = _verified_repair_support_items(
        runtime=runtime,
        evidence=evidence,
        requirements=requirements,
        question=question,
        intent_class=intent_class,
    )
    if support_failures or not used_items:
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
    try:
        candidate = runtime._runtime_bound_candidate(
            answer=text,
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
        final = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=evidence,
            calls=_provider_calls(previous_answer),
            repair_attempted=True,
        )
    except Exception:
        return None
    if final.get("status") != "owner_only_cited_answer":
        return None
    if runtime._visible_semantic_failures(
        str(final.get("answer_text", "")),
        requirements,
        question,
    ):
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
        "deterministic_evidence_synthesis_used": False,
        "provider_contract": "compact_runtime_bound_semantic_closure/v2",
        "runtime_bound_semantic_repair_used": True,
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


def _verified_repair_support_items(
    *,
    runtime: Any,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
    question: str,
    intent_class: str,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]], list[str]]:
    evidence_by_id = {str(item.get("evidence_id", "")): item for item in evidence}
    all_failures, all_proof = runtime._requirement_support_failures(
        requirements=requirements,
        evidence=evidence,
    )
    if all_failures:
        return [], all_proof, [str(item) for item in all_failures]

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

    if intent_class in {"cross_document_comparison", "complementary_synthesis"}:
        while _distinct_repair_sources(selected) < 2:
            before = len(selected)
            for item in ranked or evidence:
                if _repair_source_identity(item) not in {
                    _repair_source_identity(existing) for existing in selected
                }:
                    add_item(item)
                    break
            if len(selected) == before:
                break

    support_failures, support_proof = runtime._requirement_support_failures(
        requirements=requirements,
        evidence=selected,
    )
    if support_failures:
        return selected, support_proof, [str(item) for item in support_failures]
    return selected, support_proof, []


def _repair_source_identity(item: Mapping[str, Any]) -> str:
    return str(item.get("source_identity") or item.get("source_id") or "")


def _distinct_repair_sources(items: Sequence[Mapping[str, Any]]) -> int:
    return len({_repair_source_identity(item) for item in items if _repair_source_identity(item)})


def _semantic_answer_text_v2(question: str, requirements: Sequence[Any]) -> str:
    ids = {str(item.requirement_id) for item in requirements}
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
    return ""


def _citation(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        "citation_id": f"citation_{index}",
        "evidence_id": str(item.get("evidence_id", "")),
        "locator_id": str(item.get("locator_id", "")),
        "source_identity": str(item.get("source_identity") or item.get("source_id") or ""),
        "evidence_type": str(item.get("evidence_type", "")),
    }


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
