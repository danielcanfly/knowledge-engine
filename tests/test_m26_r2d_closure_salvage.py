from __future__ import annotations

import json
from typing import Any

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime
from knowledge_engine.m26_verified_answer_citation_gate import sha256_bytes


def _rich_passage(evidence_id: str, text: str) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator_id": f"loc_{evidence_id}",
        "evidence_type": "passage",
        "source_id": f"source_{evidence_id}",
        "source_identity": f"source_{evidence_id}",
        "concept_id": f"concept_{evidence_id}",
        "title": f"source {evidence_id}",
        "section_title": f"section {evidence_id}",
        "passage_text": text,
        "release_id": "release-test",
        "artifact_key": "artifact-test",
        "artifact_sha256": "a" * 64,
        "section_id": f"section_{evidence_id}",
        "channels": ["dense"],
        "passage_text_sha256": sha256_bytes(text.encode("utf-8")),
        "provenance_record_sha256": "b" * 64,
        "retrieved_at": "",
        "retrieval_metadata": {"query_overlap_score": 1.0},
    }


def _body(segments: list[dict[str, Any]], *, schema_version: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": schema_version or runtime.COMPACT_CLOSURE_SCHEMA_VERSION,
        "status": "answer",
        "segments": segments,
        "unanswered_dimensions": [],
        "abstention_reason": None,
    }


def _material_segment(
    segment_id: str,
    text: str,
    labels: list[str],
    *,
    claim_id: str | None = None,
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "semantic_role": "material_claim",
        "claim_id": claim_id or f"claim_{segment_id}",
        "claim_type": "EVIDENCE_FACT",
        "text": text,
        "evidence_labels": labels,
        "covers": [],
    }


class _Provider:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.review_claim_cases: list[list[dict[str, Any]]] = []

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls.append((payload, call_class))
        if call_class == runtime.SEMANTIC_REVIEW_CALL_CLASS:
            task = json.loads(payload["messages"][0]["content"])
            claim_cases = task["claim_cases"]
            self.review_claim_cases.append(claim_cases)
            return {
                "text": json.dumps(
                    {
                        "schema_version": runtime.SEMANTIC_REVIEW_SCHEMA_VERSION,
                        "claim_judgments": [
                            {
                                "claim_id": str(case["claim_id"]),
                                "verdict": "ENTAILED",
                                "evidence_ids": [
                                    str(item["evidence_id"]) for item in case["evidence"]
                                ],
                            }
                            for case in claim_cases
                        ],
                        "visible_coverage": {
                            "verdict": "COVERED",
                            "uncovered_assertions": [],
                        },
                    }
                ),
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "cost_usd": "0.001",
                "call_class": call_class,
            }
        return {
            "text": json.dumps(self.body),
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "cost_usd": "0.001",
            "call_class": call_class,
        }


def test_prunes_unsupported_surplus_segments_before_repair_and_runs_review() -> None:
    evidence = [
        _rich_passage(
            "router",
            "The router stores graph snapshots for controlled execution.",
        ),
        _rich_passage(
            "monitor",
            "The router records runtime events for operator review.",
        ),
    ]
    provider = _Provider(
        _body(
            [
                _material_segment(
                    "s1",
                    "The router stores graph snapshots for controlled execution.",
                    ["e2"],
                ),
                _material_segment(
                    "s2",
                    "The router records runtime events for operator review.",
                    ["e1"],
                ),
                _material_segment(
                    "s3",
                    "Unsupported surplus closure text should be pruned.",
                    [],
                ),
                _material_segment(
                    "s4",
                    "Another unsupported closure claim should disappear.",
                    [],
                ),
            ]
        )
    )

    answer, _closure = runtime._synthesize_and_verify(
        question="Explain router graph snapshots and runtime event review.",
        trace_id="trace-r2d-salvage",
        intent_class="direct_grounded_knowledge",
        evidence=evidence,
        provider_client=provider,
        requirements=[],
        endpoint_proof={"schema_version": "test"},
    )

    assert [call_class for _, call_class in provider.calls] == [
        "aq_semantic_closure",
        runtime.SEMANTIC_REVIEW_CALL_CLASS,
    ]
    assert len(provider.review_claim_cases) == 1
    assert len(provider.review_claim_cases[0]) == 2
    assert answer["answer_source"] == "provider_verified_runtime_bound_semantic_closure"
    assert "Unsupported surplus closure text" not in answer["answer_text"]
    parse = answer["multi_evidence_verification"]["provider_attempt_telemetry"][0][
        "parse_telemetry"
    ]
    assert parse["deterministic_surplus_pruning_used"] is True
    assert parse["dropped_segment_ids"] == ["s3", "s4"]
    assert parse["retained_segment_count"] == 2


def test_salvage_fail_closed_matrix() -> None:
    label_map = {"e1": {"evidence_id": "ev1"}}
    valid_labeled = _material_segment("s1", "The router stores graph snapshots.", ["e1"])
    surplus = _material_segment("s2", "Unsupported surplus text.", [])

    cases = [
        _body([_material_segment("s1", "Unknown labels are not salvaged.", ["e404"]), surplus]),
        _body([{"segment_id": "s1"}, surplus]),
        _body([valid_labeled, surplus], schema_version="unknown-schema"),
        _body([_material_segment("s1", "All unsupported text.", [])]),
    ]

    for body in cases:
        assert (
            runtime._salvage_compact_provider_surplus_segments(
                json.dumps(body),
                label_map=label_map,
            )
            is None
        )
