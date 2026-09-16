from __future__ import annotations

import json
from typing import Any

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_pa7_semantic_closure_runtime import SemanticRequirement
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


def _requirement() -> SemanticRequirement:
    return SemanticRequirement(
        requirement_id="supported_facet",
        instruction="State the supported material fact.",
        evidence_terms=("supported", "fact"),
        visible_patterns=(r"\bsupported\b",),
    )


def _evidence() -> dict[str, Any]:
    text = "The supplied source states the supported material fact."
    return {
        "evidence_id": "evidence_1",
        "locator_id": "locator_1",
        "evidence_type": "passage",
        "source_id": "source_1",
        "source_identity": "source_1",
        "concept_id": "concept_1",
        "title": "Evidence",
        "section_title": "Support",
        "section_id": "section_1",
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "provenance_record_sha256": "b" * 64,
        "channels": ["dense"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
    }


def _payload(*, repair: bool, failures: list[str]) -> dict[str, Any]:
    payload, _, _ = runtime._compact_provider_payload(
        question="What does the supplied source support?",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        requirements=[_requirement()],
        repair=repair,
        previous_failures=failures,
    )
    return payload


def test_base_contract_requires_empty_model_explanation_covers() -> None:
    payload = _payload(repair=False, failures=[])

    assert "evidence_labels [], and covers []" in payload["system"]
    assert "may never satisfy a required material facet" in payload["system"]


def test_ppve_011_gets_one_bounded_actionable_repair_directive() -> None:
    payload = _payload(
        repair=True,
        failures=[
            runtime.COMPACT_PROVIDER_PARSE_FAILED,
            "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET",
            "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET",
        ],
    )
    task = json.loads(payload["messages"][0]["content"])

    assert task["repair_directives"] == [
        runtime.REPAIR_DIRECTIVES_BY_FAILURE[
            "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET"
        ]
    ]
    directive = task["repair_directives"][0]
    assert "covers=[] for every MODEL_EXPLANATION" in directive
    assert "material_claim" in directive
    assert "supporting evidence labels" in directive


def test_repair_directive_is_finite_and_contains_no_request_content() -> None:
    marker = "private-request-marker"
    payload, _, _ = runtime._compact_provider_payload(
        question=marker,
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        requirements=[_requirement()],
        repair=True,
        previous_failures=[
            "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET",
            marker,
        ],
    )
    task = json.loads(payload["messages"][0]["content"])

    assert len(task["repair_directives"]) == 1
    assert marker not in task["repair_directives"][0]
    assert "evidence_1" not in task["repair_directives"][0]
    assert "locator_1" not in task["repair_directives"][0]


def test_model_explanation_empty_covers_is_valid_parser_shape() -> None:
    parsed = runtime._parse_compact_provider_result(
        json.dumps(
            {
                "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                "status": "answer",
                "segments": [
                    {
                        "segment_id": "s1",
                        "semantic_role": "model_explanation",
                        "claim_id": "claim_1",
                        "claim_type": "MODEL_EXPLANATION",
                        "text": "A generic connective sentence.",
                        "evidence_labels": [],
                        "covers": [],
                    }
                ],
                "unanswered_dimensions": [],
                "abstention_reason": None,
            }
        )
    )

    assert parsed["segments"][0]["covers"] == []


def test_model_explanation_nonempty_covers_remains_runtime_rejected() -> None:
    segment = {
        "segment_id": "s1",
        "semantic_role": "model_explanation",
        "claim_id": "claim_1",
        "claim_type": "MODEL_EXPLANATION",
        "text": "A generic connective sentence.",
        "evidence_labels": [],
        "covers": ["supported_facet"],
    }
    runtime._validate_provider_segments([segment])

    try:
        runtime._runtime_bound_candidate(
            answer=segment["text"],
            question="What is supported?",
            intent_class="direct_grounded_knowledge",
            used_items=(),
            claims=None,
            segments=[segment],
            label_map={"e1": _evidence()},
            snippet_map={"evidence_1": "The supplied source states the fact."},
            requirements=[_requirement()],
        )
    except ValueError as exc:
        assert runtime._post_parse_exception_leaf(
            exc, stage="candidate_binding"
        ) == "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET"
    else:
        raise AssertionError("non-empty model-explanation covers must fail closed")


def test_material_claim_covers_facet_only_with_evidence_binding() -> None:
    base_segment = {
        "segment_id": "s1",
        "semantic_role": "material_claim",
        "claim_id": "claim_1",
        "claim_type": "EVIDENCE_FACT",
        "text": "The supplied source states the supported material fact.",
        "covers": ["supported_facet"],
    }
    invalid = {**base_segment, "evidence_labels": []}
    try:
        runtime._validate_provider_segments([invalid])
    except ValueError:
        pass
    else:
        raise AssertionError("material claim without evidence labels must fail closed")

    valid = {**base_segment, "evidence_labels": ["e1"]}
    runtime._validate_provider_segments([valid])
    candidate = runtime._runtime_bound_candidate(
        answer=valid["text"],
        question="What is supported?",
        intent_class="direct_grounded_knowledge",
        used_items=(),
        claims=None,
        segments=[valid],
        label_map={"e1": _evidence()},
        snippet_map={"evidence_1": "The supplied source states the supported material fact."},
        requirements=[_requirement()],
    )

    assert candidate["claims"][0]["facet_ids"] == ["supported_facet"]
    assert candidate["claims"][0]["support_refs"]


def test_repair_attempt_cap_remains_two() -> None:
    class AlwaysInvalidProvider:
        def __init__(self) -> None:
            self.call_classes: list[str] = []

        def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
            self.call_classes.append(call_class)
            return {
                "text": json.dumps(
                    {
                        "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                        "status": "answer",
                        "segments": [
                            {
                                "segment_id": "s1",
                                "semantic_role": "model_explanation",
                                "claim_id": "claim_1",
                                "claim_type": "MODEL_EXPLANATION",
                                "text": "A generic connective sentence.",
                                "evidence_labels": [],
                                "covers": ["supported_facet"],
                            }
                        ],
                        "unanswered_dimensions": [],
                        "abstention_reason": None,
                    }
                ),
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "call_class": call_class,
            }

    provider = AlwaysInvalidProvider()
    answer, closure = runtime._synthesize_and_verify(
        question="What does the supplied source support?",
        trace_id="trace-model-explanation-contract",
        intent_class="direct_grounded_knowledge",
        evidence=[_evidence()],
        provider_client=provider,
        requirements=[_requirement()],
        endpoint_proof={"required": False, "matched": False},
        max_attempts=99,
    )

    assert provider.call_classes == [
        "aq_semantic_closure",
        "aq_semantic_closure_repair",
    ]
    assert answer["safe_abstention"] is True
    assert "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET" in closure["failures"]
