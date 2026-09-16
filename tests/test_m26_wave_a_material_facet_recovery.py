from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


def _evidence(evidence_id: str, text: str, *, concept_id: str = "concept-a") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": f"loc-{evidence_id}",
        "release_id": "release-a",
        "artifact_key": "artifact-a",
        "artifact_sha256": "a" * 64,
        "provenance_record_sha256": "b" * 64,
        "concept_id": concept_id,
        "section_id": f"section-{evidence_id}",
        "source_id": "source-a",
        "source_identity": "source-a",
        "title": "Alpha guide",
        "section_title": "Selected section",
        "channels": ["r1_selected"],
        "passage_text": text,
        "passage_text_sha256": "c" * 64,
    }


def test_structural_cue_without_topic_is_not_supported() -> None:
    requirement = runtime.SemanticRequirement(
        "explanatory_answer", "Explain Alpha.", ("alpha", "because"), (r"\bbecause\b",)
    )
    hostile = {
        **_evidence("hostile", "Unrelated policy because it was approved yesterday."),
        "title": "Unrelated policy",
        "section_title": "Approval record",
        "source_id": "source-unrelated",
        "source_identity": "source-unrelated",
    }
    relevant = _evidence("relevant", "Alpha is selected because it preserves the boundary.")
    assert runtime._facet_support_classification(
        requirements=[requirement], evidence=[hostile]
    )[0]["support_state"] == "UNSUPPORTED"
    assert runtime._facet_support_classification(
        requirements=[requirement], evidence=[relevant]
    )[0]["support_state"] == "SUPPORTED"


def test_missing_material_facet_recovers_source_local_child(monkeypatch: Any) -> None:
    parent = {
        "section_id": "parent",
        "concept_id": "concept-a",
        "source_id": "source-a",
        "title": "Alpha guide",
        "section_title": "Overview",
        "body": "Alpha is introduced here.",
    }
    child = {
        "section_id": "child",
        "concept_id": "concept-a",
        "source_id": "source-a",
        "title": "Alpha guide",
        "section_title": "Boundary details",
        "body": "Alpha preserves the boundary through verification.",
    }
    bundle = SimpleNamespace(lexical_index={"documents": [parent, child]})
    monkeypatch.setattr(runtime.legacy, "_release_documents", lambda _bundle: [parent, child])
    monkeypatch.setattr(
        runtime.legacy,
        "_evidence_item",
        lambda **kwargs: _evidence(
            f"recovered-{kwargs['document']['section_id']}",
            kwargs["document"]["body"],
            concept_id=kwargs["document"]["concept_id"],
        ),
    )
    requirement = runtime.SemanticRequirement(
        "boundary", "State Alpha's boundary.", ("alpha", "boundary", "verification"), ()
    )
    strengthened, proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=[_evidence("parent", "Alpha is introduced here.")],
        lexical_result={"results": []},
        trace_id="trace-a",
        question="What boundary does Alpha preserve?",
        intent_class="direct_grounded_knowledge",
        requirements=[requirement],
    )
    assert {item["section_id"] for item in strengthened} == {
        "section-parent",
        "section-recovered-child",
    }
    assert proof["recovered_facets"] == ["boundary"]
    assert proof["recovery_actions"][0]["scope"] == "source_local"


def test_empty_material_requirements_cannot_reach_provider() -> None:
    class NoCallProvider:
        def __init__(self) -> None:
            self.calls = 0

        def call(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            raise AssertionError("provider must not be called")

    provider = NoCallProvider()
    requirements = runtime._material_requirements_for_query(
        "Explain Alpha's boundary.", "direct_grounded_knowledge", []
    )
    response, trace = runtime._synthesize_and_verify(
        question="Explain Alpha's boundary.",
        trace_id="trace-empty",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence("e1", "Alpha is discussed here.")],
        provider_client=provider,
        requirements=requirements,
        endpoint_proof={},
    )
    assert provider.calls == 0
    assert response["answer_source"] == "safe_abstention"
    assert "NO_SUPPORTED_REQUIRED_FACETS" in trace["failures"]


def test_empty_derivation_is_one_core_facet_not_fake_elaboration() -> None:
    requirements = runtime._material_requirements_for_query(
        "What is Alpha?", "direct_grounded_knowledge", []
    )
    assert [item.requirement_id for item in requirements] == ["core_answer"]


def test_structural_cues_require_topic_for_first_then_and_criteria() -> None:
    fixtures = [
        ("multi_dimension_structure", ("alpha", "first"), r"\bfirst\b"),
        ("process_sequence", ("alpha", "then"), r"\bthen\b"),
        ("decision_criteria", ("alpha", "criteria"), r"\bcriteria\b"),
    ]
    for requirement_id, terms, pattern in fixtures:
        requirement = runtime.SemanticRequirement(requirement_id, "", terms, (pattern,))
        evidence = _evidence("cue", "An unrelated record first/then lists criteria.")
        evidence["title"] = "Unrelated record"
        evidence["section_title"] = "Other topic"
        assert runtime._facet_support_classification(
            requirements=[requirement], evidence=[evidence]
        )[0]["support_state"] == "UNSUPPORTED"


def test_topic_words_without_requested_relation_remain_unsupported() -> None:
    requirement = runtime.SemanticRequirement(
        "comparison_or_distinction", "Compare Alpha and Beta.",
        ("alpha", "beta", "different"), (r"\b(?:different|whereas)\b",)
    )
    evidence = _evidence("topic", "Alpha and Beta are documented in the same guide.")
    assert runtime._facet_support_classification(
        requirements=[requirement], evidence=[evidence]
    )[0]["support_state"] == "UNSUPPORTED"


def test_recovery_stays_within_explicit_budget(monkeypatch: Any) -> None:
    docs = [
        {
            "section_id": f"s-{i}",
            "concept_id": "c",
            "source_id": "s",
            "title": "Alpha",
            "section_title": str(i),
            "body": f"Alpha facet {i} because verified.",
        }
        for i in range(5)
    ]
    bundle = SimpleNamespace(lexical_index={"documents": docs})
    monkeypatch.setattr(runtime.legacy, "_release_documents", lambda _bundle: docs)
    monkeypatch.setattr(runtime.legacy, "_dynamic_evidence_budget", lambda **_kwargs: 2)
    monkeypatch.setattr(
        runtime.legacy,
        "_evidence_item",
        lambda **kwargs: _evidence(
            kwargs["document"]["section_id"],
            kwargs["document"]["body"],
            concept_id="c",
        ),
    )
    requirements = [
        runtime.SemanticRequirement(f"facet-{i}", "", ("alpha", "facet", str(i)), ())
        for i in range(4)
    ]
    strengthened, proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=[_evidence("seed", "Seed evidence.", concept_id="c")],
        lexical_result={"results": []},
        trace_id="trace-budget",
        question="Explain Alpha facets.",
        intent_class="direct_grounded_knowledge",
        requirements=requirements,
    )
    assert len(strengthened) <= 2
    assert len(proof["recovery_actions"]) <= 1


def test_recovery_does_not_use_model_explanation_as_evidence(monkeypatch: Any) -> None:
    model_only = {
        "section_id": "model", "concept_id": "c", "source_id": "s",
        "title": "MODEL_EXPLANATION", "section_title": "model_explanation",
        "body": "Alpha because the model explanation says so.",
    }
    bundle = SimpleNamespace(lexical_index={"documents": [model_only]})
    monkeypatch.setattr(runtime.legacy, "_release_documents", lambda _bundle: [model_only])
    monkeypatch.setattr(
        runtime.legacy,
        "_evidence_item",
        lambda **kwargs: _evidence("model", kwargs["document"]["body"], concept_id="c"),
    )
    requirement = runtime.SemanticRequirement("alpha_fact", "", ("alpha", "fact"), ())
    strengthened, _proof = runtime._strengthen_evidence(
        bundle=bundle,
        evidence=[],
        lexical_result={"results": []},
        trace_id="trace-model",
        question="What is Alpha?",
        intent_class="direct_grounded_knowledge",
        requirements=[requirement],
    )
    assert strengthened == []
