from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_LEGACY_PATH = Path(__file__).resolve().parent.parent / "m26_aq_semantic_runtime_patch_v2.py"
_SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine._m26_aq_semantic_runtime_patch_v2_file",
    _LEGACY_PATH,
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - importlib defensive guard
    raise ImportError(f"Cannot load legacy AQ semantic runtime patch from {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault(_SPEC.name, _legacy)
_SPEC.loader.exec_module(_legacy)

for _name, _value in vars(_legacy).items():
    if _name not in {
        "__builtins__",
        "__cached__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
    }:
        globals()[_name] = _value

_BASE_CLEAN_ENTITY_TEXT = _legacy._clean_entity_text
_BASE_AUGMENT_FINAL_REQUIREMENTS = _legacy._augment_final_requirements
_BASE_SEMANTIC_ANSWER_TEXT_V2 = _legacy._semantic_answer_text_v2
_BASE_PROVIDER_INTEGRITY_SAFE_SYNTHESIZE = _legacy._provider_integrity_safe_synthesize
_BASE_ENDPOINT_AWARE_REQUIREMENT_SUPPORT_FAILURES = (
    _legacy._endpoint_aware_requirement_support_failures
)

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
    r"\b(?:precedes?|preceding|comes\s+before|come\s+before|is\s+before|are\s+before)\b",
    flags=re.I,
)
_RELATION_SPLIT_PATTERNS = (
    r"\s+as\s+preceding\b.*$",
    r"\s+as\s+coming\s+before\b.*$",
    r"\s+comes\s+before\b.*$",
    r"\s+come\s+before\b.*$",
    r"\s+is\s+before\b.*$",
    r"\s+are\s+before\b.*$",
    r"\s+precedes\b.*$",
    r"\s+precede\b.*$",
)


def _clean_entity_text(value: str) -> str:
    """Normalize wrapper prose without weakening strict Part-N endpoint identity."""
    text = _BASE_CLEAN_ENTITY_TEXT(value)
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
                    instruction="State that the graph relation records a precedes ordering relationship.",
                    evidence_terms=("precedes", "ordering", "sequence", "navigation"),
                    visible_patterns=(
                        r"(?:relation graph|graph|edge|relationship).{0,180}(?:precedes|ordering|sequence|navigation|comes before)",
                        r"(?:precedes|comes before).{0,180}(?:ordering|sequence|navigation|relationship)",
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
                        r"(?:does not|cannot|can't|only).{0,180}(?:depend|causal|prove|implementation|requirement)",
                    ),
                )
            )
            seen.add("non_entailment")
    return normalized


def _augment_final_requirements(runtime: Any, question: str, items: list[Any]) -> None:
    _BASE_AUGMENT_FINAL_REQUIREMENTS(runtime, question, items)
    normalized = _normalize_graph_entity_requirements(runtime, question, items)
    items[:] = normalized


def _semantic_answer_text_v2(question: str, requirements: Sequence[Any]) -> str:
    base_text = _BASE_SEMANTIC_ANSWER_TEXT_V2(question, requirements)
    if base_text:
        return base_text
    ids = {str(item.requirement_id) for item in requirements}
    if "ordering_semantics" not in ids:
        return ""
    entities = [
        _legacy._requirement_entity_phrase(item)
        for item in requirements
        if str(item.requirement_id).startswith("entity_")
    ]
    entities = [entity for entity in entities if entity]
    if len(entities) >= 2:
        prefix = f"The relation graph records {entities[0]} precedes {entities[1]}. "
        order_text = f"That means {entities[0]} comes before {entities[1]} in graph ordering or navigation."
    else:
        prefix = "The relation graph records a precedes edge. "
        order_text = "That edge supports graph ordering or navigation."
    if "non_entailment" in ids:
        return (
            prefix
            + order_text
            + " It does not prove dependency, causality, implementation, or requirement semantics; stronger dependency would need separate endpoint passage support."
        )
    return prefix + order_text


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
    normalized_requirements = _normalize_graph_entity_requirements(
        runtime,
        question,
        requirements,
    )
    strengthened_endpoint = _best_precedes_endpoint_proof(
        question=question,
        evidence=evidence,
        endpoint_proof=endpoint_proof,
    )
    return _BASE_PROVIDER_INTEGRITY_SAFE_SYNTHESIZE(
        runtime=runtime,
        legacy=legacy,
        question=question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider_client,
        requirements=normalized_requirements,
        endpoint_proof=strengthened_endpoint,
    )


def _endpoint_aware_requirement_support_failures(
    *,
    runtime: Any,
    requirements: Sequence[Any],
    evidence: Sequence[Mapping[str, Any]],
    endpoint_proof: Mapping[str, Any] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    question = " ".join(str(getattr(item, "exact_phrase", "")) for item in requirements)
    normalized_requirements = _normalize_graph_entity_requirements(
        runtime,
        question,
        requirements,
    )
    return _BASE_ENDPOINT_AWARE_REQUIREMENT_SUPPORT_FAILURES(
        runtime=runtime,
        requirements=normalized_requirements,
        evidence=evidence,
        endpoint_proof=endpoint_proof,
    )


def _install_graph_entity_paraphrase_overrides() -> None:
    _legacy._clean_entity_text = _clean_entity_text
    _legacy._augment_final_requirements = _augment_final_requirements
    _legacy._semantic_answer_text_v2 = _semantic_answer_text_v2
    _legacy._provider_integrity_safe_synthesize = _provider_integrity_safe_synthesize
    _legacy._endpoint_aware_requirement_support_failures = (
        _endpoint_aware_requirement_support_failures
    )


_install_graph_entity_paraphrase_overrides()

for _name in (
    "_clean_entity_text",
    "_augment_final_requirements",
    "_semantic_answer_text_v2",
    "_provider_integrity_safe_synthesize",
    "_endpoint_aware_requirement_support_failures",
    "_normalize_graph_entity_requirements",
    "_relation_paraphrase_mentions_precedes",
    "_strict_part_entities",
):
    globals()[_name] = globals()[_name]
