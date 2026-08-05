from __future__ import annotations

from dataclasses import dataclass

from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    instruction: str
    evidence_terms: tuple[str, ...] = ()
    visible_patterns: tuple[str, ...] = ()
    exact_phrase: str = ""


class Runtime:
    SemanticRequirement = Requirement


def _entity_req(text: str) -> Requirement:
    slug = text.casefold().replace(" ", "_")
    return Requirement(
        requirement_id=f"entity_{slug}",
        instruction=f"Name {text}",
        exact_phrase=text,
    )


def test_graph_fact_wrapper_is_not_entity_identity() -> None:
    requirements = [
        _entity_req("A true graph fact says Harness Theory Part 1"),
        _entity_req("A true graph fact says Harness Theory Part 2"),
    ]
    normalized = patch._normalize_graph_entity_requirements(
        Runtime,
        "A true graph fact says Harness Theory Part 1 precedes Part 2. Does that fact by itself prove that Part 1 depends on Part 2?",
        requirements,
    )
    exacts = [item.exact_phrase for item in normalized if item.requirement_id.startswith("entity_")]
    assert "A true graph fact says Harness Theory Part 1" not in exacts
    assert "A true graph fact says Harness Theory Part 2" not in exacts
    assert "Harness Theory Part 1" in exacts
    assert "Harness Theory Part 2" in exacts
    ids = {item.requirement_id for item in normalized}
    assert "ordering_semantics" in ids
    assert "non_entailment" in ids


def test_relation_paraphrases_map_to_precedes_semantics() -> None:
    for phrase in ("comes before", "is before", "as preceding"):
        question = f"Harness Theory Part 1 {phrase} Part 2 in the relation graph."
        normalized = patch._normalize_graph_entity_requirements(
            Runtime,
            question,
            [_entity_req("Harness Theory Part 1"), _entity_req("Harness Theory Part 2")],
        )
        ids = {item.requirement_id for item in normalized}
        assert "ordering_semantics" in ids
        answer = patch._semantic_answer_text_v2(question, normalized)
        assert "Harness Theory Part 1" in answer
        assert "Harness Theory Part 2" in answer
        assert "precedes" in answer


def test_part_token_boundaries_stay_strict() -> None:
    assert patch._strict_part_entities(
        "The graph fact says Harness Theory Part 1 precedes Part 10."
    ) == ["Harness Theory Part 1", "Harness Theory Part 10"]
    assert patch._strict_part_entities(
        "If a true graph fact records Harness Theory Part 99 as preceding Part 2, answer safely."
    ) == ["Harness Theory Part 99", "Harness Theory Part 2"]


def test_non_graph_direct_before_question_is_not_forced_to_relation() -> None:
    assert not patch._relation_paraphrase_mentions_precedes(
        "Before starting, explain how the production router chooses a path."
    )
