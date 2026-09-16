from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine.m26_aq_semantic_contract import derive_semantic_requirements


def _requirements(question: str):
    return derive_semantic_requirements(question, legacy._intent_class(question))


def _ids(question: str) -> set[str]:
    return {item.requirement_id for item in _requirements(question)}


def test_comparison_list_does_not_invent_router_mechanics_or_duplicate_plural_entities():
    question = (
        "How do direct requests, pipelines, routers, state machines, and DAGs "
        "differ as execution paths?"
    )

    requirements = _requirements(question)
    ids = {item.requirement_id for item in requirements}
    exact_entities = [
        item.exact_phrase.casefold()
        for item in requirements
        if item.requirement_id.startswith("entity_")
    ]

    assert "router_decision" not in ids
    assert "routing_constraints" not in ids
    assert "entity_state_machine" in ids
    assert "entity_dag" in ids
    assert "state machines" not in exact_entities
    assert "dags" not in exact_entities
    assert "comparison_or_distinction" in ids


def test_shared_actor_predicate_is_not_misparsed_as_first_coordinated_entity():
    question = "How should a runtime handle context, state, memory, and retrieval?"

    requirements = _requirements(question)
    exact_entities = {
        item.exact_phrase.casefold()
        for item in requirements
        if item.requirement_id.startswith("entity_")
    }
    ids = {item.requirement_id for item in requirements}

    assert exact_entities == {"context", "state", "memory", "retrieval"}
    assert "process_sequence" not in ids
    assert "decision_criteria" not in ids
    assert "explanatory_answer" in ids


def test_explicit_router_mechanics_still_require_router_decision_and_constraints():
    question = "How does a router choose a downstream path for a request?"

    ids = _ids(question)

    assert "router_decision" in ids
    assert "routing_constraints" in ids


def test_explicit_decision_language_still_requires_decision_criteria():
    question = "Which criteria should a team evaluate when choosing a deployment mode?"

    assert "decision_criteria" in _ids(question)


def test_help_decide_question_keeps_semantic_decision_requirement_without_retrieval_override():
    question = "What does retry_count help an operator decide?"

    assert "decision_criteria" in _ids(question)

def test_action_enumeration_and_comparison_questions_are_not_misclassified_as_definitions():
    action_question = "What were the adapter variants actually measuring in the experiments?"
    enumeration_question = "What are the five parts of the runtime mental model?"
    comparison_question = "What is the practical difference between a handoff and a fork?"

    action_ids = _ids(action_question)
    enumeration_ids = _ids(enumeration_question)
    comparison_ids = _ids(comparison_question)

    assert "definition_head" not in action_ids
    assert "definition_head" not in enumeration_ids
    assert "multi_dimension_structure" in enumeration_ids
    assert "definition_head" not in comparison_ids
    assert "comparison_or_distinction" in comparison_ids
