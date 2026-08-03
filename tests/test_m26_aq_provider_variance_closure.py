from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_isolated(code: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_in_progress_text_does_not_create_persisted_progress_requirement() -> None:
    _run_isolated(
        """
        import knowledge_engine.m26_production_api as production

        production._production_question_contract = lambda **kwargs: {
            "required_facets": [
                {"facet_id": "persisted_progress"},
                {"facet_id": "replanning_role"},
            ]
        }
        contract = production._question_contract_without_progress_substring_false_positive(
            question=(
                "New evidence invalidates the remaining steps of an in-progress workflow; "
                "how should the plan change?"
            ),
            intent_class="direct_grounded_knowledge",
        )
        assert [item["facet_id"] for item in contract["required_facets"]] == [
            "replanning_role"
        ]

        persisted = production._question_contract_without_progress_substring_false_positive(
            question="How should persisted progress survive a client disconnect?",
            intent_class="direct_grounded_knowledge",
        )
        assert "persisted_progress" in {
            item["facet_id"] for item in persisted["required_facets"]
        }
        """
    )


def test_route_replan_paraphrase_gets_generalized_semantic_contract() -> None:
    _run_isolated(
        """
        import knowledge_engine.m26_production_api as production

        question = (
            "A request is assigned to an initial route, then new evidence arrives after "
            "execution and the unfinished plan must be revised. Explain the two roles."
        )
        requirements = production._production_variance_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        )
        ids = production._requirement_ids(requirements)
        assert {
            "initial_routing_role",
            "replanning_role",
            "role_contrast",
        }.issubset(ids)
        text = production._production_variance_semantic_answer_text(question, requirements)
        lowered = text.casefold()
        assert "initial route" in lowered
        assert "replanning" in lowered
        assert "remaining" in lowered
        """
    )


def test_graph_variance_repair_requires_exact_precedes_endpoint_proof() -> None:
    _run_isolated(
        """
        from typing import Any

        import knowledge_engine.m26_aq_semantic_runtime_patch_v2 as aq_v2_patch
        import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic_runtime
        import knowledge_engine.m26_production_api as production

        def requirement(
            requirement_id: str,
            *,
            terms: tuple[str, ...] = ("evidence",),
            pattern: str = r"evidence",
            exact_phrase: str = "",
        ) -> Any:
            return semantic_runtime.SemanticRequirement(
                requirement_id=requirement_id,
                instruction=f"Cover {requirement_id}.",
                evidence_terms=terms,
                visible_patterns=(pattern,),
                exact_phrase=exact_phrase,
            )

        def fake_synthesize(**kwargs: Any):
            del kwargs
            return (
                {
                    "terminal_status": "safe_abstention",
                    "multi_evidence_verification": {},
                },
                {"broad_deterministic_fallback_used": False},
            )

        repair_calls = []

        def fake_repair(**kwargs: Any):
            repair_calls.append(dict(kwargs))
            return (
                {
                    "terminal_status": "verified_answer_ready_candidate",
                    "multi_evidence_verification": {},
                },
                {
                    "support_proof": [{"supported": True}],
                    "broad_deterministic_fallback_used": False,
                },
            )

        production._production_semantic_synthesize = fake_synthesize
        aq_v2_patch._runtime_bound_semantic_repair_v2 = fake_repair
        requirements = [
            requirement(
                "entity_alpha_note",
                terms=("alpha",),
                pattern=r"Alpha Note",
                exact_phrase="Alpha Note",
            ),
            requirement(
                "entity_beta_note",
                terms=("beta",),
                pattern=r"Beta Note",
                exact_phrase="Beta Note",
            ),
            requirement(
                "ordering_semantics",
                terms=("precedes", "ordering"),
                pattern=r"(?:precedes|ordering|sequence)",
            ),
        ]
        endpoint = {
            "required": True,
            "matched": True,
            "relation_type": "precedes",
            "edge_source": "alpha_concept",
            "edge_target": "beta_concept",
            "question_entities": ["Alpha Note", "Beta Note"],
        }
        answer, closure = production._synthesize_with_bounded_provider_variance_repair(
            question="Alpha Note comes before Beta Note in the relation graph. What is recorded?",
            trace_id="trace_graph",
            intent_class="graph_relationship",
            evidence=[{"evidence_id": "edge", "relation_type": "precedes"}],
            provider_client=object(),
            requirements=requirements,
            endpoint_proof=endpoint,
        )
        assert answer["terminal_status"] == "verified_answer_ready_candidate"
        assert closure["provider_variance_repair_kind"] == "exact_precedes_endpoint"
        assert len(repair_calls) == 1

        for invalid in (
            {**endpoint, "matched": False},
            {**endpoint, "relation_type": "depends_on"},
            {**endpoint, "edge_target": ""},
        ):
            repair_calls.clear()
            answer, closure = production._synthesize_with_bounded_provider_variance_repair(
                question=(
                    "Alpha Note comes before Beta Note in the relation graph. "
                    "What is recorded?"
                ),
                trace_id="trace_graph_invalid",
                intent_class="graph_relationship",
                evidence=[{"evidence_id": "edge"}],
                provider_client=object(),
                requirements=requirements,
                endpoint_proof=invalid,
            )
            assert answer["terminal_status"] == "safe_abstention"
            assert "provider_variance_repair_kind" not in closure
            assert repair_calls == []
        """
    )


def test_route_replan_provider_abstention_uses_only_bounded_verified_repair() -> None:
    _run_isolated(
        """
        from typing import Any

        import knowledge_engine.m26_aq_semantic_runtime_patch_v2 as aq_v2_patch
        import knowledge_engine.m26_production_api as production

        def fake_synthesize(**kwargs: Any):
            del kwargs
            return (
                {
                    "terminal_status": "safe_abstention",
                    "multi_evidence_verification": {},
                },
                {"broad_deterministic_fallback_used": False},
            )

        repair_calls = []

        def fake_repair(**kwargs: Any):
            repair_calls.append(dict(kwargs))
            return (
                {
                    "terminal_status": "verified_answer_ready_candidate",
                    "multi_evidence_verification": {},
                },
                {
                    "support_proof": [{"supported": True}],
                    "broad_deterministic_fallback_used": False,
                    "runtime_bound_semantic_repair_used": True,
                },
            )

        production._production_semantic_synthesize = fake_synthesize
        aq_v2_patch._runtime_bound_semantic_repair_v2 = fake_repair
        question = (
            "An initial route has already been selected. Later evidence invalidates unfinished "
            "work, so the plan must be revised. How do those roles differ?"
        )
        requirements = production._production_variance_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        )
        answer, closure = production._synthesize_with_bounded_provider_variance_repair(
            question=question,
            trace_id="trace_route_replan",
            intent_class="direct_grounded_knowledge",
            evidence=[{"evidence_id": "route_source"}, {"evidence_id": "plan_source"}],
            provider_client=object(),
            requirements=requirements,
            endpoint_proof={},
        )
        assert answer["terminal_status"] == "verified_answer_ready_candidate"
        assert closure["provider_variance_repair_kind"] == "route_replan_contrast"
        assert closure["broad_deterministic_fallback_used"] is False
        assert closure["runtime_bound_semantic_repair_used"] is True
        assert len(repair_calls) == 1
        assert repair_calls[0]["evidence"][0]["evidence_id"] == "route_source"
        """
    )


def test_visual_source_authority_variance_has_narrow_repair_shape() -> None:
    _run_isolated(
        """
        import knowledge_engine.m26_production_api as production

        question = (
            "If a Sigma.js visualization conflicts with canonical source material, which layer "
            "is authoritative and what evidence should the answer cite?"
        )
        requirements = production._production_variance_semantic_requirements(
            question,
            "provenance_source_trace",
        )
        ids = production._requirement_ids(requirements)
        assert {"sigma_role", "trust_anchor"}.issubset(ids)
        text = production._production_variance_semantic_answer_text(question, requirements)
        lowered = text.casefold()
        assert "sigma.js" in lowered
        assert "source" in lowered
        assert "provenance" in lowered
        assert "authority" in lowered
        """
    )


def test_unrelated_abstention_stays_fail_closed_and_hard_verifier_is_preserved() -> None:
    _run_isolated(
        """
        from typing import Any

        import knowledge_engine.m26_aq_semantic_runtime_patch_v2 as aq_v2_patch
        import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic_runtime
        import knowledge_engine.m26_production_api as production

        def fake_synthesize(**kwargs: Any):
            del kwargs
            return (
                {"terminal_status": "safe_abstention"},
                {"broad_deterministic_fallback_used": False},
            )

        repair_calls = []

        def fake_repair(**kwargs: Any):
            repair_calls.append(dict(kwargs))
            raise AssertionError("unrelated questions must not enter repair")

        production._production_semantic_synthesize = fake_synthesize
        aq_v2_patch._runtime_bound_semantic_repair_v2 = fake_repair
        requirements = [
            semantic_runtime.SemanticRequirement(
                requirement_id="unrelated_fact",
                instruction="Cover unrelated fact.",
                evidence_terms=("unrelated",),
                visible_patterns=(r"unrelated",),
            )
        ]
        answer, closure = production._synthesize_with_bounded_provider_variance_repair(
            question="What unrelated fact is present?",
            trace_id="trace_unrelated",
            intent_class="direct_grounded_knowledge",
            evidence=[{"evidence_id": "unrelated"}],
            provider_client=object(),
            requirements=requirements,
            endpoint_proof={},
        )
        assert answer["terminal_status"] == "safe_abstention"
        assert closure["broad_deterministic_fallback_used"] is False
        assert repair_calls == []

        code = aq_v2_patch._runtime_bound_semantic_repair_v2.__code__
        assert "_verify_multi_evidence_provider_output" in code.co_names
        assert "_verified_multi_evidence_answer" in code.co_names
        assert "_verified_repair_support_items" in code.co_names

        guidance = production._production_variance_repair_guidance("M26-PA7-ME-036").casefold()
        assert "precedes" in guidance
        assert "ordering" in guidance
        assert "dependency" in guidance
        assert "causal" in guidance
        """
    )
