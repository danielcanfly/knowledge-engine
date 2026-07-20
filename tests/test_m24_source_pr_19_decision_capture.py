from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

CAPTURE_PATH = Path("pilot/m24/m24-source-pr-19-decision-capture.json")


def _capture() -> dict:
    return json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))


def test_source_pr_19_decision_capture_is_digest_bound() -> None:
    capture = _capture()
    unsigned = dict(capture)
    digest = unsigned.pop("decision_capture_sha256")

    assert digest != "TO_BE_FILLED"
    assert canonical_sha256(unsigned) == digest


def test_source_pr_19_capture_keeps_review_pending_until_human_decisions() -> None:
    capture = _capture()

    assert capture["status"] == "decision_capture_ready"
    assert capture["source_pr"] == {
        "repository": "danielcanfly/knowledge-source",
        "number": 19,
        "url": "https://github.com/danielcanfly/knowledge-source/pull/19",
        "state": "open",
        "draft": True,
        "base_sha": "a6ba738d910d01d2ae99b1968f0831989934c549",
        "head_sha": "deb3ad1e631c2149183d10561fbceb0a1848a989",
        "decision_template_state": "all_pending",
        "human_approval_claimed": False,
        "merge_as_is_allowed": False,
    }
    assert len(capture["review_items"]) == 15
    assert {item["decision"] for item in capture["review_items"]} == {"pending"}
    assert all(item["human_actor"] is None for item in capture["review_items"])
    assert all(item["reviewed_at"] is None for item in capture["review_items"])


def test_source_pr_19_capture_lists_allowed_decisions_and_closure_requirements() -> None:
    capture = _capture()

    assert capture["allowed_decisions"] == [
        "approve_new",
        "map_existing",
        "edit",
        "reject",
        "defer",
    ]
    assert capture["closure_requirements"] == {
        "all_items_non_pending": True,
        "human_actor_required": True,
        "reviewed_at_required": True,
        "source_pr_comment_or_review_required": True,
        "source_pr_must_not_merge_as_is": True,
        "canonical_adoption_pr_required_later": True,
    }


def test_source_pr_19_capture_preserves_non_serving_authority_boundary() -> None:
    authority = _capture()["authority_boundary"]

    assert authority == {
        "production_retrieval": "lexical",
        "semantic_promotion_enabled": False,
        "semantic_answer_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
        "source_mutation_authorized": False,
        "pointer_mutation_authorized": False,
        "r2_mutation_authorized": False,
        "qdrant_mutation_authorized": False,
        "credential_rotation_authorized": False,
    }
