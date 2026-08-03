from __future__ import annotations

import json

import knowledge_engine.m26_aq_semantic_runtime_patch as base_patch
import knowledge_engine.m26_aq_semantic_runtime_patch_v3 as patch_v3
import knowledge_engine.m26_aq_semantic_runtime_patch_v3_lifecycle as boundary_patch
import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy
import knowledge_engine.m26_pa7_semantic_closure_runtime as runtime

patch_v3.install()
boundary_patch.install()


def _requirement_ids(question: str) -> set[str]:
    return {
        str(item.requirement_id)
        for item in runtime._semantic_requirements(
            question,
            legacy._intent_class(question),
        )
    }


def test_false_premise_prompt_does_not_require_prescribed_opening() -> None:
    question = (
        "A true graph fact says Harness Theory Part 1 precedes Harness Theory Part 2. "
        "Does that fact by itself prove dependency?"
    )
    assert base_patch._needs_initial_no(question) is False


def test_natural_graph_prefixes_do_not_become_entity_names() -> None:
    assert (
        patch_v3._clean_entity_text_v3("A true graph fact says Harness Theory Part 1")
        == "Harness Theory Part 1"
    )
    assert (
        patch_v3._clean_entity_text_v3(
            "If the relation graph records Harness Theory Part 1 as preceding"
        )
        == "Harness Theory Part 1"
    )


def test_disconnect_question_only_requires_lifecycle_facets_it_asks_for() -> None:
    question = (
        "Why is persisted run state important when a client disconnects before a "
        "long-running workflow has finished?"
    )
    ids = _requirement_ids(question)
    assert "durable_state" in ids
    assert "admission_policy" not in ids
    assert "completion_verification" not in ids
    assert "observability" not in ids


def test_disconnect_correctness_question_keeps_state_and_verification_only() -> None:
    question = (
        "Persisted run state can survive a client disconnect. Does that persistence "
        "by itself prove that the workflow output is correct and verified?"
    )
    ids = _requirement_ids(question)
    assert "durable_state" in ids
    assert "completion_verification" in ids
    assert "admission_policy" not in ids
    assert "observability" not in ids


def test_explicit_end_to_end_lifecycle_still_requires_full_control_chain() -> None:
    question = (
        "If an agent keeps working after the client disconnects, what parts of the "
        "surrounding control system keep the run trustworthy from admission to completion?"
    )
    ids = _requirement_ids(question)
    assert {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(ids)


def test_end_to_end_lifecycle_paraphrase_keeps_full_control_chain() -> None:
    question = (
        "When a browser drops while a server job continues, which controls preserve "
        "trust from intake through final status reattachment?"
    )
    ids = _requirement_ids(question)
    assert {
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    }.issubset(ids)


def test_comes_before_graph_question_is_classified_as_graph_relationship() -> None:
    question = (
        "Harness Theory Part 1 comes before Part 2 in the relation graph. "
        "What relationship is actually recorded between those two notes?"
    )
    assert legacy._intent_class(question) == "graph_relationship"


def test_long_natural_surface_is_partitioned_before_claim_verification() -> None:
    long_clause = "persisted state supports durable workflow continuity " * 28
    answer = (
        f"{long_clause.strip()}. "
        "Verification separately checks whether the completed result is supported."
    )
    sentences = patch_v3._material_sentences(answer)
    assert len(sentences) >= 2
    assert all(len(sentence) <= 900 for sentence in sentences)


def test_standalone_yes_no_is_not_promoted_to_material_claim() -> None:
    sentences = patch_v3._material_sentences(
        "No. The precedes edge does not prove dependency or causality."
    )
    assert sentences == [
        "The precedes edge does not prove dependency or causality"
    ]


def test_direct_facet_candidate_support_is_bounded_for_hard_parser_limit() -> None:
    quote = "durable state verification observability admission " * 80
    candidate = {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "answer_text": "A concise natural answer.",
        "claims": [
            {
                "claim_id": f"claim_{index}",
                "surface_text": "A bounded claim.",
                "support_refs": [
                    {
                        "evidence_id": f"evidence_{index}",
                        "locator_id": f"locator_{index}",
                        "exact_quote": quote,
                        "exact_support_snippet": quote,
                    }
                ],
            }
            for index in range(1, 5)
        ],
    }
    bounded = boundary_patch._bound_candidate_support_refs(candidate)
    refs = [claim["support_refs"][0] for claim in bounded["claims"]]
    assert all(len(ref["exact_quote"]) <= 780 for ref in refs)
    assert all(ref["exact_support_snippet"] == ref["exact_quote"] for ref in refs)
    assert len(json.dumps(bounded, separators=(",", ":"))) < 12_000


def test_provider_task_hides_runtime_ids_and_explains_repair_semantics() -> None:
    task = {
        "question": "What does the graph edge mean?",
        "evidence": [
            {
                "id": "e1",
                "type": "graph_edge",
                "source": "graph_v2:edge_3f15206278e63ccf8981",
                "concept": "article_f8573ff5ee10182a3f6c",
                "from": "article_f8573ff5ee10182a3f6c",
                "to": "article_71b9d92dad73c6d1fa18",
                "text": "Harness Theory Part 1 precedes Harness Theory Part 2.",
            }
        ],
        "repair": [
            "USER_VISIBLE_INTERNAL_REFERENCE_LEAK:article_f8573ff5ee10182a3f6c",
            "M26-PA7-ME-034",
        ],
    }
    safe = boundary_patch._sanitize_provider_task(task)
    serialized = json.dumps(safe, ensure_ascii=False)
    assert "article_f8573ff5ee10182a3f6c" not in serialized
    assert "article_71b9d92dad73c6d1fa18" not in serialized
    assert safe["evidence"][0]["source"] == "relation graph"
    assert safe["evidence"][0]["id"] == "e1"
    assert any("Do not expose internal runtime identifiers" in item for item in safe["repair"])
    assert any("Do not strengthen modality beyond evidence" in item for item in safe["repair"])
