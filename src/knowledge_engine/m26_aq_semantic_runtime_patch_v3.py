from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import knowledge_engine.m26_aq_semantic_runtime_patch as base_patch
import knowledge_engine.m26_aq_semantic_runtime_patch_v2 as v2_patch

_LIFECYCLE_REQUIREMENTS = {
    "admission_policy",
    "durable_state",
    "completion_verification",
    "observability",
}


def _never_require_initial_no(question: str) -> bool:
    del question
    return False


def install() -> None:
    """Install product-first semantic closure without frozen-answer coupling."""
    from . import m26_pa7_arbitrary_query_runtime as legacy
    from . import m26_pa7_semantic_closure_runtime as runtime

    v2_patch.install()

    if not hasattr(runtime, "_m26_aq_v3_base_intent"):
        runtime._m26_aq_v3_base_intent = legacy._intent_class
    if not hasattr(runtime, "_m26_aq_v3_base_requirements"):
        runtime._m26_aq_v3_base_requirements = runtime._semantic_requirements
    if not hasattr(runtime, "_m26_aq_v3_base_edge"):
        runtime._m26_aq_v3_base_edge = runtime._exact_named_graph_edge

    base_intent = runtime._m26_aq_v3_base_intent
    base_requirements = runtime._m26_aq_v3_base_requirements
    base_edge = runtime._m26_aq_v3_base_edge

    def intent(question: str) -> str:
        q = question.casefold()
        if (
            "comes before" in q
            and "graph" in q
            and "part 1" in q
            and "part 2" in q
        ):
            return "graph_relationship"
        return base_intent(question)

    def requirements(question: str, intent_class: str) -> list[Any]:
        items = list(base_requirements(question, intent_class))
        items = _prune_lifecycle_overreach(question, items)
        if _explicit_full_lifecycle(question):
            _ensure_full_lifecycle(runtime, items)
        if "comes before" in question.casefold() and not any(
            str(item.requirement_id) == "ordering_semantics" for item in items
        ):
            items.append(
                runtime.SemanticRequirement(
                    requirement_id="ordering_semantics",
                    instruction="State the recorded ordering or sequence relation.",
                    evidence_terms=(
                        "precedes",
                        "ordering",
                        "sequence",
                        "comes before",
                    ),
                    visible_patterns=(
                        r"\b(?:precedes|ordering|sequence|comes before)\b",
                    ),
                )
            )
        return items

    def exact_edge(bundle: Any, question: str) -> Mapping[str, Any] | None:
        edge = base_edge(bundle, question)
        if edge is not None:
            return edge
        q = question.casefold()
        if "comes before" in q and "precedes" not in q:
            return base_edge(
                bundle,
                question + " The recorded relation is precedes.",
            )
        return None

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
        return _generalized_provider_synthesize(
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

    base_patch._needs_initial_no = _never_require_initial_no
    v2_patch._clean_entity_text = _clean_entity_text_v3
    legacy._intent_class = intent
    runtime._semantic_requirements = requirements
    runtime._exact_named_graph_edge = exact_edge
    runtime._synthesize_and_verify = synthesize
    runtime._m26_aq_semantic_runtime_patch_v3_installed = True


def _clean_entity_text_v3(value: str) -> str:
    text = " ".join(str(value).strip().split())
    prefixes = (
        "The production graph says ",
        "A true graph fact says ",
        "If the relation graph records ",
        "The relation graph records ",
        "Does the precedes edge between ",
        "Can the precedes edge between ",
        "Does ",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if text.casefold().startswith(prefix.casefold()):
                text = text[len(prefix) :]
                changed = True
                break
    for suffix in (
        " prove that",
        " prove",
        " safely infer",
        " as preceding",
        " precedes",
    ):
        index = text.casefold().find(suffix.casefold())
        if index > 0:
            text = text[:index]
    return " ".join(text.strip(" ?:.,").split())


def _explicit_full_lifecycle(question: str) -> bool:
    q = question.casefold()
    return any(
        phrase in q
        for phrase in (
            "from admission to completion",
            "from intake to completion",
            "surrounding control system",
            "keep the run trustworthy",
        )
    )


def _prune_lifecycle_overreach(question: str, items: Sequence[Any]) -> list[Any]:
    lifecycle_ids = {
        str(item.requirement_id)
        for item in items
        if str(item.requirement_id) in _LIFECYCLE_REQUIREMENTS
    }
    if not lifecycle_ids:
        return list(items)
    if _explicit_full_lifecycle(question):
        return list(items)

    q = question.casefold()
    requested: set[str] = set()
    if any(
        term in q
        for term in (
            "disconnect",
            "persist",
            "durable",
            "state",
            "recover",
            "resume",
        )
    ):
        requested.add("durable_state")
    if any(
        term in q
        for term in (
            "verify",
            "verification",
            "verified",
            "completion",
            "correct",
            "success",
            "acceptance",
        )
    ):
        requested.add("completion_verification")
    if any(
        term in q
        for term in (
            "admission",
            "intake",
            "before execution",
            "request boundary",
        )
    ):
        requested.add("admission_policy")
    if any(
        term in q
        for term in (
            "observability",
            "reattach",
            "status",
            "headless",
            "inspect",
            "inspection",
        )
    ):
        requested.add("observability")

    return [
        item
        for item in items
        if str(item.requirement_id) not in _LIFECYCLE_REQUIREMENTS
        or str(item.requirement_id) in requested
    ]


def _ensure_full_lifecycle(runtime: Any, items: list[Any]) -> None:
    seen = {str(item.requirement_id) for item in items}
    specs = (
        (
            "admission_policy",
            "Cover request admission or effective policy before execution.",
            ("admission", "request", "policy", "contract"),
            r"\b(?:admission|request|policy|contract)\b",
        ),
        (
            "durable_state",
            "Cover durable or persisted server-side run state after disconnect.",
            ("durable", "persisted", "state", "disconnect"),
            r"\b(?:durable|persisted|state|disconnect)\b",
        ),
        (
            "completion_verification",
            "Cover verification or acceptance before declaring completion.",
            ("verification", "completion", "acceptance", "final"),
            r"\b(?:verification|completion|acceptance|final)\b",
        ),
        (
            "observability",
            "Cover status, observability, reattachment, resume, or inspection.",
            ("observability", "status", "reattach", "resume", "inspect"),
            r"\b(?:observability|status|reattach|resume|inspect)\b",
        ),
    )
    for requirement_id, instruction, terms, pattern in specs:
        if requirement_id in seen:
            continue
        items.append(
            runtime.SemanticRequirement(
                requirement_id=requirement_id,
                instruction=instruction,
                evidence_terms=terms,
                visible_patterns=(pattern,),
            )
        )
        seen.add(requirement_id)


def _generalized_provider_synthesize(
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

    for attempt in (1, 2):
        payload, label_map, _snippet_map = runtime._compact_provider_payload(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            repair=attempt == 2,
            previous_failures=failures,
        )
        payload["system"] = (
            str(payload.get("system", ""))
            + " Evidence labels such as e1/e2 are internal selectors and must never "
            "appear in the answer. If evidence is irrelevant or insufficient for the "
            "requested fact, abstain rather than inventing support."
        )
        try:
            raw = provider_client.call(
                payload,
                (
                    "aq_semantic_closure_repair"
                    if attempt == 2
                    else "aq_semantic_closure"
                ),
            )
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
            if attempt == 1:
                continue
            break

        if parsed["status"] == "abstain":
            return _provider_abstention(
                runtime=runtime,
                legacy=legacy,
                requirements=requirements,
                endpoint_proof=endpoint_proof,
                calls=calls,
                failures=[*failures, "PROVIDER_ABSTAINED"],
                repair_attempted=attempt == 2,
            )

        answer = str(parsed["answer"]).strip()
        leaks = v2_patch._user_visible_internal_reference_leaks(
            answer,
            question,
            label_map,
        )
        if leaks:
            failures.extend(
                f"USER_VISIBLE_INTERNAL_REFERENCE_LEAK:{item}" for item in leaks
            )
            if attempt == 1:
                continue
            break

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
        support_failures, support_proof = (
            v2_patch._endpoint_aware_requirement_support_failures(
                runtime=runtime,
                requirements=requirements,
                evidence=used_items,
                endpoint_proof=endpoint_proof,
            )
        )
        final_support_proof = support_proof
        semantic_failures = sorted(set([*visible_failures, *support_failures]))
        if semantic_failures:
            failures.extend(semantic_failures)
            if attempt == 1:
                continue
            break

        try:
            candidate = _verification_candidate(
                legacy=legacy,
                answer=answer,
                question=question,
                intent_class=intent_class,
                used_items=used_items,
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
            final_answer = legacy._verified_multi_evidence_answer(
                intent_class=intent_class,
                verified=verified,
                evidence=evidence,
                calls=calls,
                repair_attempted=attempt == 2,
            )
            v2_patch._use_verified_natural_surface(final_answer, answer)
        except Exception as exc:
            failures.append(str(getattr(exc, "code", type(exc).__name__)))
            if attempt == 1:
                continue
            break

        post_failures = runtime._visible_semantic_failures(
            str(final_answer.get("answer_text", "")),
            requirements,
            question,
        )
        if post_failures:
            failures.extend(post_failures)
            if attempt == 1:
                continue
            break
        final_leaks = v2_patch._user_visible_internal_reference_leaks(
            str(final_answer.get("answer_text", "")),
            question,
            label_map,
        )
        if final_leaks:
            failures.extend(
                f"USER_VISIBLE_INTERNAL_REFERENCE_LEAK:{item}"
                for item in final_leaks
            )
            if attempt == 1:
                continue
            break

        final_answer["answer_source"] = (
            "provider_verified_runtime_bound_semantic_closure"
        )
        final_answer["multi_evidence_verification"] = {
            **dict(final_answer.get("multi_evidence_verification", {})),
            "verification_failure_codes_by_attempt": list(failures),
            "repair_trigger": sorted(set(failures)) if attempt == 2 else [],
            "repair_result": "verified" if attempt == 2 else "not_needed",
            "deterministic_evidence_synthesis_used": False,
            "provider_contract": "compact_runtime_bound_semantic_closure/v3",
            "runtime_bound_semantic_repair_used": False,
            "served_answer_surface": "verified_natural_material_claim_surface",
        }
        closure = {
            "schema_version": "m26-aq-semantic-closure/v1",
            "requirements": [
                runtime._requirement_public(item) for item in requirements
            ],
            "support_proof": final_support_proof,
            "endpoint_proof": dict(endpoint_proof),
            "failures": [],
            "provider_contract": "compact_runtime_bound_semantic_closure/v3",
            "broad_deterministic_fallback_used": False,
            "runtime_bound_semantic_repair_used": False,
        }
        return final_answer, closure

    return _provider_abstention(
        runtime=runtime,
        legacy=legacy,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
        calls=calls,
        failures=[*failures, "SEMANTIC_CLOSURE_FAILED"],
        repair_attempted=len(calls) > 1,
        support_proof=final_support_proof,
    )


def _provider_abstention(
    *,
    runtime: Any,
    legacy: Any,
    requirements: Sequence[Any],
    endpoint_proof: Mapping[str, Any],
    calls: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    repair_attempted: bool,
    support_proof: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    reason_codes = sorted({str(item) for item in failures if str(item)})
    answer = legacy._verified_abstention(
        reason_codes=reason_codes or ["PROVIDER_ABSTAINED"],
        calls=[dict(item) for item in calls],
        repair_attempted=repair_attempted,
    )
    answer["answer_source"] = "safe_abstention"
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [
            runtime._requirement_public(item) for item in requirements
        ],
        "support_proof": list(support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": reason_codes,
        "provider_contract": "compact_runtime_bound_semantic_closure/v3",
        "broad_deterministic_fallback_used": False,
        "runtime_bound_semantic_repair_used": False,
    }
    return answer, closure


def _verification_candidate(
    *,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    requirements: Sequence[Any],
) -> dict[str, Any]:
    if intent_class == "direct_grounded_knowledge":
        candidate = v2_patch._direct_facet_partition_candidate(
            legacy=legacy,
            answer=answer,
            question=question,
            intent_class=intent_class,
            used_items=used_items,
            requirements=requirements,
        )
        if candidate is not None:
            return candidate
    return _sentence_bound_candidate(
        legacy=legacy,
        answer=answer,
        question=question,
        intent_class=intent_class,
        used_items=used_items,
    )


def _sentence_bound_candidate(
    *,
    legacy: Any,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    sentences = _material_sentences(answer)
    if not sentences:
        raise ValueError("natural answer has no material sentence")

    required_facets = legacy._required_facet_ids(
        question=question,
        intent_class=intent_class,
    )
    claims: list[dict[str, Any]] = []
    selected_ids: list[str] = []

    for index, sentence in enumerate(sentences, start=1):
        terms = legacy._meaningful_terms(sentence)
        ranked = sorted(
            used_items,
            key=lambda item: _sentence_evidence_score(
                legacy,
                sentence,
                item,
            ),
            reverse=True,
        )
        refs: list[dict[str, str]] = []
        for item in ranked:
            ref = _support_ref(legacy, item, terms)
            if ref is None:
                continue
            refs.append(ref)
            selected_ids.append(str(item.get("evidence_id", "")))
            if len(refs) >= 3:
                break
        if not refs:
            raise ValueError("natural answer sentence has no exact evidence support")
        claims.append(
            {
                "claim_id": f"claim_{index}",
                "claim_role": _claim_role(intent_class, index),
                "surface_text": sentence,
                "facet_ids": list(required_facets),
                "support_mode": "runtime_bound_sentence_exact_evidence",
                "support_refs": refs,
            }
        )

    _ensure_intent_evidence(
        legacy=legacy,
        intent_class=intent_class,
        used_items=used_items,
        claims=claims,
        selected_ids=selected_ids,
    )
    anchored = " ".join(
        f"{sentence.rstrip('.')} [[claim_{index}]]."
        for index, sentence in enumerate(sentences, start=1)
    )
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": _relation_for_intent(intent_class, used_items),
        "selected_evidence_ids": list(dict.fromkeys(selected_ids)),
        "answer_text": anchored,
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _claim_role(intent_class: str, index: int) -> str:
    if index != 1:
        return "direct"
    if intent_class == "cross_document_comparison":
        return "comparison"
    if intent_class == "complementary_synthesis":
        return "relationship"
    return "direct"


def _relation_for_intent(
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
) -> str | None:
    if intent_class == "cross_document_comparison":
        return "contrasts_with"
    if intent_class == "complementary_synthesis":
        return "complements"
    if intent_class == "temporal_conflict":
        return "precedes"
    if intent_class == "graph_relationship":
        edge = next(
            (
                item
                for item in used_items
                if item.get("evidence_type") == "graph_edge"
            ),
            None,
        )
        if edge is not None:
            return str(edge.get("relation_type", "")) or None
    return None


def _material_sentences(answer: str) -> list[str]:
    text = " ".join(str(answer).strip().split())
    if not text:
        return []
    pieces = [
        item.strip().rstrip(".")
        for item in re.split(r"(?<=[.!?])\s+", text)
        if item.strip()
    ]
    bounded: list[str] = []
    for piece in pieces:
        if len(piece) <= 900:
            bounded.append(piece)
            continue
        clauses = [
            item.strip()
            for item in re.split(r";\s+", piece)
            if item.strip()
        ]
        if len(clauses) == 1:
            clauses = _word_bounded_chunks(piece, 850)
        bounded.extend(item for item in clauses if item)
    return bounded


def _word_bounded_chunks(text: str, maximum: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for word in words:
        added = len(word) + (1 if current else 0)
        if current and current_length + added > maximum:
            chunks.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length += added
    if current:
        chunks.append(" ".join(current))
    return chunks


def _sentence_evidence_score(
    legacy: Any,
    sentence: str,
    item: Mapping[str, Any],
) -> tuple[int, float, int, str]:
    sentence_terms = legacy._meaningful_terms(sentence)
    text = " ".join(
        str(item.get(key, ""))
        for key in (
            "passage_text",
            "title",
            "section_title",
            "source_identity",
            "relation_type",
            "edge_source",
            "edge_target",
        )
    )
    item_terms = legacy._meaningful_terms(text)
    overlap = len(sentence_terms & item_terms)
    graph_bonus = (
        2
        if item.get("evidence_type") == "graph_edge"
        and "precedes" in sentence.casefold()
        else 0
    )
    ratio = overlap / max(len(sentence_terms), 1)
    return (
        overlap + graph_bonus,
        ratio,
        -len(item_terms),
        str(item.get("evidence_id", "")),
    )


def _support_ref(
    legacy: Any,
    item: Mapping[str, Any],
    terms: set[str],
) -> dict[str, str] | None:
    ref = v2_patch._support_ref_for_terms(legacy, item, terms)
    if ref is None:
        ref = v2_patch._full_passage_support_ref(item)
    if ref is None:
        return None
    bounded = dict(ref)
    quote = str(bounded.get("exact_quote", ""))
    if len(quote) > 780:
        quote = quote[:780].rsplit(" ", 1)[0].rstrip() or quote[:780]
        bounded["exact_quote"] = quote
        bounded["exact_support_snippet"] = quote
    return bounded


def _ensure_intent_evidence(
    *,
    legacy: Any,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    claims: list[dict[str, Any]],
    selected_ids: list[str],
) -> None:
    if not claims:
        return

    def add_ref(item: Mapping[str, Any]) -> None:
        evidence_id = str(item.get("evidence_id", ""))
        if not evidence_id:
            return
        existing = {
            str(ref.get("evidence_id", ""))
            for ref in claims[0].get("support_refs", [])
        }
        if evidence_id in existing:
            return
        ref = _support_ref(legacy, item, set())
        if ref is not None:
            claims[0]["support_refs"].append(ref)
            selected_ids.append(evidence_id)

    if intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
    }:
        seen_sources = {
            _source_identity(item)
            for item in used_items
            if str(item.get("evidence_id", ""))
            in {
                str(ref.get("evidence_id", ""))
                for ref in claims[0].get("support_refs", [])
            }
        }
        for item in used_items:
            source = _source_identity(item)
            if source and source not in seen_sources:
                add_ref(item)
                seen_sources.add(source)
            if len(seen_sources) >= 2:
                break
    elif intent_class == "graph_relationship":
        edge = next(
            (
                item
                for item in used_items
                if item.get("evidence_type") == "graph_edge"
            ),
            None,
        )
        if edge is not None:
            add_ref(edge)
            for concept_id in {
                str(edge.get("edge_source", "")),
                str(edge.get("edge_target", "")),
            }:
                item = next(
                    (
                        candidate
                        for candidate in used_items
                        if candidate.get("evidence_type") == "passage"
                        and str(candidate.get("concept_id", "")) == concept_id
                    ),
                    None,
                )
                if item is not None:
                    add_ref(item)
    elif intent_class == "provenance_source_trace":
        for evidence_type in ("passage", "provenance"):
            item = next(
                (
                    candidate
                    for candidate in used_items
                    if candidate.get("evidence_type") == evidence_type
                ),
                None,
            )
            if item is not None:
                add_ref(item)
    elif intent_class == "temporal_conflict":
        temporal = next(
            (
                item
                for item in used_items
                if item.get("evidence_type") == "temporal_record"
            ),
            None,
        )
        if temporal is not None:
            add_ref(temporal)
        first_identity = _source_or_version_identity(temporal) if temporal else ""
        other = next(
            (
                item
                for item in used_items
                if _source_or_version_identity(item)
                and _source_or_version_identity(item) != first_identity
            ),
            None,
        )
        if other is not None:
            add_ref(other)


def _source_identity(item: Mapping[str, Any]) -> str:
    return str(
        item.get("source_identity")
        or item.get("source_id")
        or item.get("source")
        or ""
    )


def _source_or_version_identity(item: Mapping[str, Any] | None) -> str:
    if item is None:
        return ""
    return (
        f"{_source_identity(item)}@"
        f"{item.get('retrieved_at') or item.get('temporal_identity') or ''}"
    )
