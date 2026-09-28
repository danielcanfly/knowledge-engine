from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from knowledge_engine import m26_pa7_semantic_closure_runtime as runtime


def _slots() -> list[dict[str, Any]]:
    return [
        {
            "slot_id": "slot_1",
            "facet_id": "facet_main",
            "co_facet_ids": [],
            "allowed_evidence_ids": ["ev_1", "ev_2"],
            "allowed_evidence_labels": ["e1", "e2"],
            "support_quote_by_evidence_id": {
                "ev_1": "Durable runtime retains audit records.",
                "ev_2": "The audit records are used for controlled review.",
            },
        }
    ]


def _label_map() -> dict[str, dict[str, Any]]:
    return {
        "e1": {
            "evidence_id": "ev_1",
            "locator_id": "loc_1",
            "evidence_type": "passage",
            "passage_text": "Durable runtime retains audit records.",
        },
        "e2": {
            "evidence_id": "ev_2",
            "locator_id": "loc_2",
            "evidence_type": "passage",
            "passage_text": "The audit records are used for controlled review.",
        },
    }


def _body(**claim_overrides: Any) -> dict[str, Any]:
    claim = {
        "slot_id": "slot_1",
        "claim_id": "claim_1",
        "claim_text": "Durable runtime retains audit records for controlled review.",
        "evidence_ids": ["ev_1"],
        "support_type": "direct",
        "claim_strength": "narrow",
        "answer_role": "core",
        "source_span_hint": "retains audit records",
        "dropped": False,
        "weakened": False,
        "why": "ev_1 directly states the retained audit records.",
    }
    claim.update(claim_overrides)
    return {
        "schema_version": runtime.CLAIM_EVIDENCE_SUBSET_SCHEMA_VERSION,
        "claims": [claim],
        "dropped_claims": [],
        "answer_plan": {
            "style": "concise",
            "can_answer": True,
            "limits": "Use only verified claims.",
        },
    }


def _parse(body: dict[str, Any]) -> dict[str, Any]:
    return runtime._parse_facet_local_provider_result(json.dumps(body), slots=_slots())


def _candidate(drafts: dict[str, Any]) -> dict[str, Any]:
    return runtime._runtime_bound_facet_local_candidate(
        drafts=drafts,
        slots=_slots(),
        label_map=_label_map(),
        snippet_map={
            "ev_1": "Durable runtime retains audit records.",
            "ev_2": "The audit records are used for controlled review.",
        },
        question="What does the runtime retain?",
        intent_class="direct_grounded_knowledge",
        unresolved_required_ids=[],
    )


def test_schema_validation_accepts_valid_subset_claims() -> None:
    drafts = _parse(_body())

    assert drafts["provider_selected_subset"] is True
    assert drafts["claims"][0]["evidence_ids"] == ["ev_1"]
    assert drafts["claims"][0]["support_type"] == "direct"
    telemetry = drafts["claim_evidence_subset_contract"]
    assert telemetry["attempted"] is True
    assert telemetry["parse_ok"] is True
    assert telemetry["validated_claim_count"] == 1
    assert telemetry["rejected_claim_count"] == 0


@pytest.mark.parametrize(
    "support_type",
    ["direct", "paraphrase", "synthesis", "contrast", "limitation"],
)
def test_schema_validation_accepts_allowed_support_types(support_type: str) -> None:
    drafts = _parse(_body(support_type=support_type))

    assert drafts["claims"][0]["support_type"] == support_type


def test_schema_validation_accepts_object_answer_plan() -> None:
    drafts = _parse(_body())

    assert drafts["answer_plan"] == {
        "style": "concise",
        "can_answer": True,
        "limits": "Use only verified claims.",
    }


def test_schema_validation_rejects_missing_evidence_ids() -> None:
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        _parse(_body(evidence_ids=[]))

    assert exc_info.value.code == runtime.FACET_LOCAL_SLOT_MISSING
    assert "missing_evidence_ids" in exc_info.value.telemetry["rejection_reasons"]


def test_schema_validation_rejects_unknown_evidence_ids() -> None:
    with pytest.raises(runtime.ClaimDraftContractError) as exc_info:
        _parse(_body(evidence_ids=["ev_999"]))

    assert exc_info.value.code == runtime.FACET_LOCAL_SLOT_MISSING
    assert "unknown_evidence_ids" in exc_info.value.telemetry["rejection_reasons"]


def test_runtime_candidate_binds_only_provider_selected_subset() -> None:
    drafts = _parse(_body(evidence_ids=["ev_2"], support_type="paraphrase"))
    candidate = _candidate(drafts)
    claim = candidate["claims"][0]

    assert candidate["selected_evidence_ids"] == ["ev_2"]
    assert claim["evidence_labels"] == ["e2"]
    assert [ref["evidence_id"] for ref in claim["support_refs"]] == ["ev_2"]
    assert claim["claim_type"] == "EVIDENCE_FACT"
    assert candidate["claim_evidence_subset_contract"]["validated_claim_count"] == 1


def test_runtime_candidate_preserves_synthesis_subset_metadata() -> None:
    drafts = _parse(_body(evidence_ids=["ev_1", "ev_2"], support_type="synthesis", claim_strength="moderate", answer_role="qualifier"))
    candidate = _candidate(drafts)
    claim = candidate["claims"][0]

    assert claim["claim_type"] == "EVIDENCE_SYNTHESIS"
    assert claim["claim_strength"] == "moderate"
    assert claim["answer_role"] == "qualifier"
    assert [ref["evidence_id"] for ref in claim["support_refs"]] == ["ev_1", "ev_2"]


def test_subset_telemetry_records_semantic_review_status() -> None:
    drafts = _parse(_body())
    candidate = _candidate(drafts)
    review = {
        "claim_judgments": [
            {"claim_id": "claim_1", "verdict": runtime.legacy.SEMANTIC_REVIEW_ENTAILED, "evidence_ids": ["ev_1"]}
        ]
    }

    telemetry = runtime._claim_subset_telemetry_with_review(
        candidate,
        review,
        deadline_remaining_ms_before_subset_generation=12_000,
        deadline_remaining_ms_before_claim_verification=9_000,
    )

    assert telemetry["claim_count_verification_attempted"] == 1
    assert telemetry["verified_core_claim_count"] == 1
    assert telemetry["claim_traces"][0]["semantic_verifier_status"] == runtime.legacy.SEMANTIC_REVIEW_ENTAILED


def test_partial_answer_requires_verified_core_claim_for_subset_contract() -> None:
    drafts = _parse(_body(answer_role="qualifier"))
    candidate = _candidate(drafts)
    review = {
        "claim_judgments": [
            {"claim_id": "claim_1", "verdict": runtime.legacy.SEMANTIC_REVIEW_ENTAILED, "evidence_ids": ["ev_1"]}
        ]
    }

    partial, _proof, _dropped = runtime._supported_review_partial_candidate(candidate, review)

    assert partial is None


def test_partial_answer_preserves_verified_core_claim() -> None:
    drafts = _parse(_body())
    candidate = _candidate(drafts)
    review = {
        "claim_judgments": [
            {"claim_id": "claim_1", "verdict": runtime.legacy.SEMANTIC_REVIEW_ENTAILED, "evidence_ids": ["ev_1"]}
        ]
    }

    partial, _proof, dropped = runtime._supported_review_partial_candidate(candidate, review)

    assert partial is not None
    assert partial["claims"][0]["claim_id"] == "claim_1"
    assert dropped == []


def test_no_case_id_or_question_text_branching_in_subset_helpers() -> None:
    helpers = [
        runtime._validate_claim_evidence_subset_output,
        runtime._runtime_bound_facet_local_candidate,
        runtime._claim_subset_telemetry_with_review,
    ]
    source = "\n".join(inspect.getsource(helper) for helper in helpers)

    assert "case_id" not in source
    assert "F085" not in source
    assert "F106" not in source
    assert "F181" not in source


def test_diverse_selection_protects_rare_source_title_anchor() -> None:
    candidates = []
    for seed in range(1, 6):
        candidates.append(
            {
                "section_id": f"generic_{seed}",
                "source_id": f"generic_source_{seed}",
                "concept_id": f"generic_concept_{seed}",
                "channels": {"lexical"},
                "seed_rank": seed,
                "rerank_score": 100.0 - seed,
                "source_coverage": {
                    "title_overlap_terms": ["problem"],
                    "body_overlap_terms": ["problem", "stop"],
                    "coverage_score": 20.0,
                },
            }
        )
    # This candidate is outside the hard seed-1..5 preservation band but has a
    # rare domain/title anchor. It should not be erased by rank anchors like
    # 8/9/14/20/33 or by generic stop/problem overlap.
    candidates.append(
        {
            "section_id": "rare_anchor",
            "source_id": "rare_source",
            "concept_id": "rare_concept",
            "channels": {"lexical"},
            "seed_rank": 11,
            "rerank_score": 40.0,
            "source_coverage": {
                "title_overlap_terms": ["networking", "room"],
                "body_overlap_terms": ["networking", "room"],
                "coverage_score": 20.0,
            },
        }
    )
    for seed in (8, 9, 14, 20, 33):
        candidates.append(
            {
                "section_id": f"anchor_{seed}",
                "source_id": f"anchor_source_{seed}",
                "concept_id": f"anchor_concept_{seed}",
                "channels": {"lexical"},
                "seed_rank": seed,
                "rerank_score": 50.0 - seed,
                "source_coverage": {
                    "title_overlap_terms": ["problem"],
                    "body_overlap_terms": ["problem", "stop"],
                    "coverage_score": 18.0,
                },
            }
        )

    selected = runtime.legacy._select_diverse_candidates(candidates, budget=6)

    assert [item["section_id"] for item in selected][:1] == ["rare_anchor"]
    assert selected[0]["rare_source_title_anchor_terms"] == ["networking"]
