from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_pa7_semantic_closure_runtime import SemanticRequirement
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


def _passage(text: str) -> dict[str, Any]:
    return {
        "evidence_id": "evidence_1",
        "locator_id": "locator_1",
        "evidence_type": "passage",
        "source_id": "source_1",
        "source_identity": "source_1",
        "concept_id": "concept_1",
        "title": "Evidence",
        "section_title": "Reason",
        "section_id": "section_1",
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "provenance_record_sha256": "b" * 64,
        "channels": ["dense"],
        "passage_text": text,
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
    }


class _Provider:
    def __init__(self, segment: dict[str, Any]) -> None:
        self.segment = segment
        self.call_classes: list[str] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.call_classes.append(call_class)
        assert call_class != runtime.SEMANTIC_REVIEW_CALL_CLASS
        return {
            "text": json.dumps(
                {
                    "schema_version": runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
                    "status": "answer",
                    "segments": [self.segment],
                    "unanswered_dimensions": [],
                    "abstention_reason": None,
                }
            ),
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "cost_usd": "0",
            "latency_ms": 1,
            "response_id": "privacy-safe-test",
            "call_class": call_class,
        }


def _segment(*, labels: list[str], covers: list[str], model: bool = False) -> dict[str, Any]:
    return {
        "segment_id": "s1",
        "semantic_role": "model_explanation" if model else "material_claim",
        "claim_id": "claim_1",
        "claim_type": "MODEL_EXPLANATION" if model else "EVIDENCE_FACT",
        "text": "Because the supplied evidence states the reason.",
        "evidence_labels": labels,
        "covers": covers,
    }


def _run(segment: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], _Provider]:
    provider = _Provider(segment)
    requirement = SemanticRequirement(
        requirement_id="explanatory_answer",
        instruction="Explain the supported reason.",
        evidence_terms=("reason",),
        visible_patterns=(r"\bbecause\b",),
    )
    answer, closure = runtime._synthesize_and_verify(
        question="Why is this the supported choice?",
        trace_id="trace-post-parse-observability",
        intent_class="direct_grounded_knowledge",
        evidence=[_passage("Because the supplied evidence states the reason.")],
        provider_client=provider,
        requirements=[requirement],
        endpoint_proof={"required": False, "matched": False},
        max_attempts=1,
    )
    return answer, closure, provider


@pytest.mark.parametrize(
    ("message", "leaf"),
    [
        (
            "provider claim c1 has unknown evidence labels",
            "M26_PPVE_007_UNKNOWN_EVIDENCE_LABEL",
        ),
        (
            "provider claim c1 covers unknown facet IDs",
            "M26_PPVE_010_UNKNOWN_FACET_ID",
        ),
        (
            "provider claim c1 model explanation cannot cover material facets",
            "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET",
        ),
    ],
)
def test_post_parse_contract_leaf_is_stable(message: str, leaf: str) -> None:
    assert (
        runtime._post_parse_exception_leaf(ValueError(message), stage="candidate_binding")
        == leaf
    )


def test_unclassified_value_error_is_bounded_by_stage() -> None:
    leaf = runtime._post_parse_exception_leaf(
        ValueError("arbitrary provider-derived detail must not be persisted"),
        stage="candidate_binding",
    )

    assert leaf == "M26_PPVE_099_UNCLASSIFIED_VALUE_ERROR_CANDIDATE_BINDING"
    assert "arbitrary" not in leaf


def test_key_error_does_not_persist_key_name() -> None:
    leaf = runtime._post_parse_exception_leaf(
        KeyError("sensitive-provider-derived-key"), stage="bounded_publication"
    )

    assert leaf == "M26_PPVE_024_UNEXPECTED_KEY_LOOKUP"
    assert "sensitive" not in leaf


def test_observability_integration_still_fails_closed_in_isolated_runtime() -> None:
    code = """
    import runpy

    namespace = runpy.run_path("tests/test_m26_post_parse_exception_observability.py")
    answer, closure, provider = namespace["_run"](
        namespace["_segment"](
            labels=[], covers=["explanatory_answer"], model=True
        )
    )
    assert answer["status"] == "owner_only_safe_abstention"
    assert "M26_PPVE_011_MODEL_EXPLANATION_COVERS_FACET" in closure["failures"]
    assert "ValueError" not in closure["failures"]
    assert provider.call_classes == ["aq_semantic_closure"]
    """
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
