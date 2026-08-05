from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from decimal import Decimal
from typing import Any

from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


EXPECTED_ENTRYPOINT = "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"


class _CompactAbstainingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        return {
            "text": json.dumps({"status": "abstain", "answer": "", "used": []}),
            "usage": {"input_tokens": 16, "output_tokens": 4},
            "cost_usd": "0.00001",
            "latency_ms": 1,
            "response_id": f"compact-abstain-{self.calls}",
            "call_class": call_class,
        }


def _passage(evidence_id: str, text: str, *, concept_id: str = "") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "concept_id": concept_id or f"concept-{evidence_id}",
        "section_id": f"section-{evidence_id}",
        "release_id": "release-test",
        "source_id": f"source-{evidence_id}",
        "source_identity": f"source-{evidence_id}",
        "channels": ["semantic_requirement_recovery"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode()),
        "provenance_record_sha256": "b" * 64,
        "retrieval_metadata": {
            "coverage_terms": [
                token.casefold()
                for token in text.replace(".", " ").replace(",", " ").split()
            ]
        },
    }


def _graph_edge(
    evidence_id: str,
    *,
    edge_id: str,
    source: str,
    target: str,
    text: str,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "graph_edge",
        "locator_id": f"loc-{evidence_id}",
        "artifact_key": "graph-test",
        "artifact_sha256": "c" * 64,
        "concept_id": source,
        "section_id": edge_id,
        "release_id": "release-test",
        "source_id": "relation-graph",
        "source_identity": "relation-graph",
        "channels": ["graph_edge"],
        "edge_id": edge_id,
        "edge_source": source,
        "edge_target": target,
        "relation_type": "precedes",
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode()),
        "provenance_record_sha256": "d" * 64,
        "retrieval_metadata": {"coverage_terms": ["precedes", "ordering", "sequence"]},
    }


def _run(code: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def test_fresh_process_fingerprints_converge() -> None:
    code = """
    from knowledge_engine.m26_aq_semantic_contract import (
        CANONICAL_RUNTIME_ENTRYPOINT,
        semantic_contract_fingerprint,
    )
    import knowledge_engine.m26_ask_api as ask
    import scripts.m26_aq_final_closure as final
    import scripts.m26_aq_generalized_closure as generalized
    import scripts.m26_aq_targeted_answerability_closure as targeted

    fingerprint = semantic_contract_fingerprint()
    values = {
        "canonical": fingerprint,
        "ask": ask.semantic_contract_fingerprint(),
        "final": final.semantic_contract_fingerprint(),
        "generalized": generalized.semantic_contract_fingerprint(),
        "targeted": targeted.semantic_contract_fingerprint(),
    }
    assert len(set(values.values())) == 1, values
    assert ask.RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert final.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert generalized.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    assert targeted.CANONICAL_RUNTIME_ENTRYPOINT == CANONICAL_RUNTIME_ENTRYPOINT
    print(fingerprint)
    """
    assert _run(code)


def test_production_import_graph_has_no_aq_patch_modules() -> None:
    code = """
    import sys
    import knowledge_engine.m26_production_api  # noqa: F401
    loaded = [
        name for name in sys.modules
        if name.startswith("knowledge_engine.m26_aq_") and "patch" in name
    ]
    assert loaded == [], loaded
    """
    _run(code)


def test_entrypoint_single_source_and_no_stale_literal() -> None:
    paths = [
        "src/knowledge_engine/m26_ask_api.py",
        "src/knowledge_engine/m26_production_api.py",
        "scripts/m26_aq_remote_production_closure.sh",
        "scripts/m26_aq_final_closure.py",
        "scripts/m26_aq_generalized_closure.py",
        "scripts/m26_aq_targeted_answerability_closure.py",
    ]
    stale = "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
    for path in paths:
        text = open(path, encoding="utf-8").read()
        assert stale not in text, path
    canonical_source = open(
        "src/knowledge_engine/m26_aq_semantic_contract.py",
        encoding="utf-8",
    ).read()
    assert canonical_source.count(EXPECTED_ENTRYPOINT) == 1


def test_authority_boundary_positive_and_negative_controls() -> None:
    code = """
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        evaluate_visible_semantics,
    )
    question = "How should the state machine and adaptive replanner handle revisions?"
    requirements = derive_semantic_requirements(
        question,
        "direct_grounded_knowledge",
        base_requirements=[],
    )
    authority = [item for item in requirements if item.requirement_id == "authority_boundary"]
    assert requirements == authority
    assert len(authority) == 1
    positive = (
        "Revisions stay within the state-machine policy and approval gates rather "
        "than expanding the replanner's authority."
    )
    negative = "The state machine tracks workflow state and the replanner changes future steps."
    assert evaluate_visible_semantics(positive, authority, question) == []
    assert evaluate_visible_semantics(negative, authority, question) == [
        "SEMANTIC_VISIBLE_MISSING:authority_boundary"
    ]
    """
    _run(code)


def test_shared_part_entities_are_derived_without_case_specific_text() -> None:
    from knowledge_engine.m26_aq_semantic_contract import canonical_question_entities

    entities = canonical_question_entities(
        "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
        "what follows from that edge?"
    )

    assert "Widget Harness Part 1" in entities
    assert "Widget Harness Part 2" in entities


def test_provider_abstention_recovers_precedes_relation_without_internal_id_leak() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "If the relation graph records Widget Harness Part 1 as preceding Part 2, "
        "what can we infer and what can we not infer from that edge?"
    )
    source = "concept-widget-part-1"
    target = "concept-widget-part-2"
    evidence = [
        _graph_edge(
            "ev-edge",
            edge_id="edge-widget-precedes",
            source=source,
            target=target,
            text=(
                "Widget Harness Part 1 precedes Widget Harness Part 2 in the "
                "relation graph."
            ),
        ),
        _passage(
            "ev-source",
            "Widget Harness Part 1 is the first article in the Widget Harness series.",
            concept_id=source,
        ),
        _passage(
            "ev-target",
            "Widget Harness Part 2 is the second article in the Widget Harness series.",
            concept_id=target,
        ),
        _passage(
            "ev-boundary",
            (
                "A precedes edge supports ordering and sequence navigation only. "
                "It does not prove dependency, causality, implementation, or requirement."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-precedes-recovery",
        intent_class="graph_relationship",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(question, "graph_relationship"),
        endpoint_proof={
            "required": True,
            "matched": True,
            "question_entities": ["Widget Harness Part 1", "Widget Harness Part 2"],
            "edge_id": "edge-widget-precedes",
            "edge_source": source,
            "edge_target": target,
            "relation_type": "precedes",
        },
    )

    text = answer["answer_text"]
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert closure["failures"] == []
    assert closure["broad_deterministic_fallback_used"] is False
    assert "Widget Harness Part 1" in text
    assert "Widget Harness Part 2" in text
    assert "ordering" in text.casefold() or "sequence" in text.casefold()
    assert "does not" in text.casefold()
    assert "prove" in text.casefold()
    assert "dependency" in text.casefold()
    assert "article_" not in text
    assert "concept-widget" not in text
    assert "ev-" not in text


def test_provider_abstention_recovers_supported_adaptive_planning_answer() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = (
        "When should adaptive planning replan globally instead of repairing one step locally?"
    )
    evidence = [
        _passage(
            "ev-global",
            (
                "Adaptive planning should replan globally when a changed premise "
                "invalidates the remaining plan and local repair cannot preserve the "
                "later dependencies."
            ),
        ),
        _passage(
            "ev-local",
            (
                "Local repair is appropriate when one step implementation failed, the "
                "objective remains valid, and later dependencies remain unchanged."
            ),
        ),
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-adaptive-recovery",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    text = answer["answer_text"].casefold()
    assert answer["status"] == "owner_only_cited_answer"
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert closure["failures"] == []
    assert closure["broad_deterministic_fallback_used"] is False
    assert "adaptive planning" in text
    assert "replan globally" in text
    assert "local repair" in text
    assert answer["unsupported_accepted_claims"] == 0
    assert answer["citation_locator_valid"] is True


def test_provider_abstention_does_not_recover_unsupported_external_marker_question() -> None:
    from knowledge_engine.m26_aq_semantic_contract import (
        derive_semantic_requirements,
        synthesize_and_verify,
    )

    question = "Which exact database table stores Contoso 2025 audited quarterly revenue?"
    evidence = [
        _passage(
            "ev-incidental-year",
            "Production concept 2025 has a hydrated section, source, and provenance record.",
        )
    ]

    answer, closure = synthesize_and_verify(
        question=question,
        trace_id="trace-ood-hard-stop",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=_CompactAbstainingProvider(),
        requirements=derive_semantic_requirements(
            question,
            "direct_grounded_knowledge",
        ),
        endpoint_proof={"required": False, "matched": False},
    )

    assert answer["status"] == "owner_only_safe_abstention"
    assert answer["answer_source"] == "safe_abstention"
    assert answer["answer_text"] == ""
    assert closure["failures"]
    assert closure["broad_deterministic_fallback_used"] is False
