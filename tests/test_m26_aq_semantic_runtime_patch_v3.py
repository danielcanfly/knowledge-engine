from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import knowledge_engine.m26_aq_semantic_runtime_patch as base_patch
import knowledge_engine.m26_aq_semantic_runtime_patch_v3 as patch_v3
import knowledge_engine.m26_aq_semantic_runtime_patch_v3_lifecycle as boundary_patch
import knowledge_engine.m26_aq_semantic_runtime_patch_v3_surface as surface_patch
import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy
import knowledge_engine.m26_pa7_semantic_closure_runtime as runtime

patch_v3.install()
boundary_patch.install()
surface_patch.install()


def _run_isolated(code: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


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


def test_v2_relation_graph_prefixes_do_not_become_entity_names() -> None:
    _run_isolated(
        """
        from knowledge_engine import m26_aq_semantic_runtime_patch_v2 as patch_v2
        from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy

        patch_v2.install()
        entities = legacy._named_question_entities(
            "If the relation graph records Widget Harness Part 1 precedes Widget Harness Part 2, "
            "what can we infer and what can we not infer from that edge?"
        )
        assert entities == ["Widget Harness Part 1", "Widget Harness Part 2"], entities
        """
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
    assert all("exact_support_snippet" not in ref for ref in refs)
    assert len(json.dumps(bounded, separators=(",", ":"))) < 12_000


def test_oversized_direct_candidate_uses_exact_support_verification_surfaces() -> None:
    long_answer = "Natural provider explanation about the surrounding controls. " * 35
    quote = "Admission durable state verification observability remain evidence bound. " * 20
    candidate = {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "answer_text": long_answer,
        "claims": [
            {
                "claim_id": f"claim_{index}",
                "claim_role": "direct",
                "surface_text": long_answer,
                "facet_ids": [f"facet_{index}"],
                "support_mode": "exact_quote",
                "support_refs": [
                    {
                        "evidence_id": f"evidence_{index}",
                        "locator_id": f"locator_{index}",
                        "exact_quote": quote,
                        "exact_support_snippet": quote,
                    }
                ],
            }
            for index in range(1, 9)
        ],
    }
    compact = boundary_patch._fit_direct_candidate_budget(
        candidate,
        intent_class="direct_grounded_knowledge",
    )
    serialized = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) < 11_000
    for claim in compact["claims"]:
        ref = claim["support_refs"][0]
        assert len(ref["exact_quote"]) <= 360
        assert claim["surface_text"] == ref["exact_quote"]
        assert "exact_support_snippet" not in ref


def test_lifecycle_verification_surfaces_do_not_repeat_long_natural_answer() -> None:
    long_answer = "Natural provider lifecycle explanation " * 100
    facet_ids = [
        "admission_policy",
        "durable_state",
        "completion_verification",
        "observability",
    ]
    candidate = {
        "answer_text": long_answer,
        "claims": [
            {
                "claim_id": f"claim_{index}",
                "surface_text": long_answer,
                "facet_ids": [facet_id],
                "support_refs": [],
            }
            for index, facet_id in enumerate(facet_ids, start=1)
        ],
    }
    compact = boundary_patch._compact_lifecycle_facet_surfaces(candidate)
    surfaces = [claim["surface_text"] for claim in compact["claims"]]
    assert all(long_answer not in surface for surface in surfaces)
    assert "Admission" in surfaces[0]
    assert "Durable" in surfaces[1]
    assert "Completion" in surfaces[2]
    assert "Observability" in surfaces[3]
    assert len(json.dumps(compact, separators=(",", ":"))) < 4_000


def test_false_premise_claims_merge_for_answer_level_non_entailment() -> None:
    candidate = {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": "precedes",
        "selected_evidence_ids": ["evidence_graph", "evidence_boundary"],
        "answer_text": "old",
        "claims": [
            {
                "claim_id": "claim_1",
                "surface_text": "The edge records ordering.",
                "facet_ids": ["ordering_semantics"],
                "support_refs": [
                    {
                        "evidence_id": "evidence_graph",
                        "locator_id": "locator_graph",
                        "exact_quote": "Part 1 precedes Part 2.",
                    }
                ],
            },
            {
                "claim_id": "claim_2",
                "surface_text": "It does not prove dependency.",
                "facet_ids": ["non_entailment"],
                "support_refs": [
                    {
                        "evidence_id": "evidence_boundary",
                        "locator_id": "locator_boundary",
                        "exact_quote": "Ordering alone does not establish dependency.",
                    }
                ],
            },
        ],
    }
    merged = boundary_patch._merge_false_premise_claims(
        candidate,
        answer="The edge records ordering. It does not prove dependency.",
    )
    assert len(merged["claims"]) == 1
    claim = merged["claims"][0]
    assert "ordering" in claim["surface_text"].casefold()
    assert "does not prove dependency" in claim["surface_text"].casefold()
    assert claim["facet_ids"] == ["ordering_semantics", "non_entailment"]
    assert len(claim["support_refs"]) == 2
    assert "[[claim_1]]" in merged["answer_text"]


def test_unsupported_modality_is_softened_before_hard_verification() -> None:
    answer = (
        "Adaptive planning must always replan globally, and that guarantee cannot fail."
    )
    softened = boundary_patch._soften_unsupported_modality(
        answer,
        question="When should adaptive planning replan globally?",
        used_items=[
            {
                "passage_text": (
                    "Adaptive planning can replan when local repair no longer resolves "
                    "the broader execution problem."
                )
            }
        ],
        legacy=legacy,
    )
    lowered = softened.casefold()
    assert "must" not in lowered
    assert "always" not in lowered
    assert "guarantee" not in lowered
    assert "cannot" not in lowered
    assert "should" in lowered
    assert "typically" in lowered
    assert "support" in lowered
    assert "may not" in lowered


def test_never_and_requires_are_softened_when_unsupported() -> None:
    answer = "Adaptive planning never repairs locally and requires global replanning."
    softened = boundary_patch._soften_unsupported_modality(
        answer,
        question="When should adaptive planning replan globally?",
        used_items=[
            {
                "passage_text": (
                    "Adaptive planning can replan globally when local repair no longer "
                    "resolves the broader execution problem."
                )
            }
        ],
        legacy=legacy,
    )
    lowered = softened.casefold()
    assert "never" not in lowered
    assert "requires" not in lowered
    assert "not necessarily" in lowered
    assert "can involve" in lowered


def test_supported_strong_modality_is_not_weakened() -> None:
    answer = "The policy must reject the request."
    softened = boundary_patch._soften_unsupported_modality(
        answer,
        question="What does the policy do?",
        used_items=[{"passage_text": "The policy must reject the request."}],
        legacy=legacy,
    )
    assert softened == answer


def test_unsupported_numeric_sentence_is_dropped_but_question_numbers_remain() -> None:
    candidate = {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "answer_text": "old",
        "claims": [
            {
                "claim_id": "claim_1",
                "surface_text": (
                    "Harness Theory Part 1 precedes Part 2. "
                    "That edge creates 3 independent guarantees."
                ),
                "facet_ids": ["ordering_semantics"],
                "support_refs": [
                    {
                        "evidence_id": "evidence_graph",
                        "locator_id": "locator_graph",
                        "exact_quote": "Harness Theory Part 1 precedes Part 2.",
                    }
                ],
            }
        ],
    }
    normalized, natural = surface_patch._normalize_candidate_unsupported_numbers(
        candidate,
        question="Does Harness Theory Part 1 precede Part 2?",
        natural_answer=(
            "Harness Theory Part 1 precedes Part 2. "
            "That edge creates 3 independent guarantees."
        ),
    )
    assert "Part 1" in normalized["claims"][0]["surface_text"]
    assert "Part 2" in normalized["claims"][0]["surface_text"]
    assert "3" not in normalized["claims"][0]["surface_text"]
    assert "Part 1" in natural and "Part 2" in natural
    assert "3" not in natural


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
            "M26-PA7-ME-033",
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
    assert any("Do not introduce numeric values" in item for item in safe["repair"])
    assert any("Do not strengthen modality beyond evidence" in item for item in safe["repair"])
