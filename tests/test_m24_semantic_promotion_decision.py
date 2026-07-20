from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

DECISION_PATH = Path("pilot/m24/m24-semantic-promotion-decision.json")
SOURCE_REVIEW_PATH = Path("pilot/m24/m24-source-pr-19-pre-review.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_self_digest(value: dict, key: str) -> None:
    digest = value[key]
    unsigned = dict(value)
    unsigned.pop(key)
    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_semantic_promotion_decision_unblocks_implementation_only() -> None:
    decision = _load(DECISION_PATH)
    _assert_self_digest(decision, "decision_sha256")

    assert decision["issue"] == 965
    assert decision["status"] == "accepted_flagged_implementation_only"
    assert decision["decision"] == {
        "semantic_promotion_decision_complete": True,
        "production_semantic_hybrid_retrieval_may_start": True,
        "production_semantic_hybrid_retrieval_scope": (
            "flagged_implementation_without_serving"
        ),
        "production_retrieval_after_decision": "lexical",
        "semantic_promotion_enabled_after_decision": False,
        "semantic_answer_serving_enabled_after_decision": False,
        "hybrid_retrieval_enabled_after_decision": False,
        "activation_gate_required_after_implementation": True,
    }


def test_semantic_promotion_decision_preserves_production_boundaries() -> None:
    decision = _load(DECISION_PATH)

    assert decision["authority_boundary"] == {
        "decision_authorized": True,
        "issue_966_unblocked_for_flagged_implementation": True,
        "production_retrieval_change_authorized": False,
        "production_semantic_serving_authorized": False,
        "production_hybrid_serving_authorized": False,
        "semantic_answer_serving_authorized": False,
        "semantic_promotion_authorized": False,
        "qdrant_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "source_mutation_authorized": False,
        "pointer_mutation_authorized": False,
        "credential_rotation_authorized": False,
        "production_traffic_change_authorized": False,
    }
    assert decision["serving_contract"]["default_retrieval_mode"] == "lexical"
    assert decision["serving_contract"]["implementation_must_default_disabled"] is True
    assert decision["serving_contract"]["activation_requires_new_reconciliation"] is True
    assert decision["reconciliation"] == {
        "issue_965_may_close_after_merge": True,
        "issue_966_may_start_after_merge": True,
        "issue_966_must_not_enable_serving": True,
        "production_semantic_or_hybrid_serving_remains_blocked": True,
        "next_required_gate": "m24_semantic_activation_reconciliation",
    }


def test_source_pr_19_pre_review_records_pending_human_decisions() -> None:
    review = _load(SOURCE_REVIEW_PATH)
    _assert_self_digest(review, "review_sha256")

    assert review["issue"] == 974
    assert review["status"] == "technical_pre_review_complete_human_decisions_pending"
    assert review["source_pr"]["repo"] == "danielcanfly/knowledge-source"
    assert review["source_pr"]["number"] == 19
    assert review["source_pr"]["draft"] is True
    assert review["source_pr"]["state"] == "OPEN"
    assert review["source_pr"]["head_sha"] == (
        "deb3ad1e631c2149183d10561fbceb0a1848a989"
    )
    assert review["observed_counts"] == {
        "candidate_count": 38,
        "concept_endpoints": 15,
        "governed_tags": 34,
        "typed_relationships": 12,
        "decision_items": 15,
        "pending_decisions": 15,
        "provenance_records": 15,
        "review_manifest_items": 15,
    }
    assert review["review_findings"]["recommendation"] == (
        "defer_canonical_adoption_pending_human_distinctness_decisions"
    )


def test_source_pr_19_pre_review_does_not_authorize_source_or_serving() -> None:
    review = _load(SOURCE_REVIEW_PATH)

    assert review["authority_boundary"] == {
        "source_pr_merge_authorized": False,
        "source_mutation_authorized": False,
        "canonical_adoption_authorized": False,
        "production_mutation_authorized": False,
        "semantic_serving_authorized": False,
        "promotion_authorized": False,
    }
    assert review["reconciliation"] == {
        "issue_974_started": True,
        "issue_974_may_close_after_this_merge": False,
        "issue_967_may_use_this_pre_review": True,
        "source_pr_19_may_merge": False,
    }
