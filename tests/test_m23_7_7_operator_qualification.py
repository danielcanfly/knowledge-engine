from __future__ import annotations

import copy
import json

import pytest
from knowledge_engine.errors import IntegrityError

from knowledge_engine import m23_7_7_operator_qualification as qualification


def _resign(payload: dict) -> dict:
    payload = copy.deepcopy(payload)
    payload.pop("operator_qualification_sha256", None)
    payload["operator_qualification_sha256"] = qualification._sha(payload)
    return payload


def test_canonical_operator_submission_passes() -> None:
    submission = qualification.canonical_operator_submission()
    normalized = qualification.validate_operator_submission(submission)
    report = qualification.build_operator_qualification_report(normalized)

    assert report["status"] == "qualified_with_blockers"
    assert report["operator_qualified"] is True
    assert report["score_percent"] == 100
    assert report["task_count"] == report["tasks_passed"] == 10
    assert report["promotion_eligibility_granted"] is False
    assert report["production_retrieval"] == "lexical"
    assert report["graph_explorer_exposure"] == "internal-only"
    assert report["carry_forward_blockers"] == [
        "blocked_pending_latency",
        "blocked_pending_retrieval_quality",
    ]


def test_operator_output_is_byte_deterministic() -> None:
    first = qualification.canonical_bytes(
        qualification.canonical_operator_submission()
    )
    second = qualification.canonical_bytes(
        qualification.canonical_operator_submission()
    )
    assert first == second


def test_challenge_discloses_no_hidden_answer_fields() -> None:
    challenge = qualification.load_operator_challenge()
    assert challenge["rules"]["expected_answers_in_challenge_allowed"] is False
    assert [task["task_id"] for task in challenge["tasks"]] == list(
        qualification.TASK_IDS
    )
    for task in challenge["tasks"]:
        assert set(task) == {
            "task_id",
            "procedure",
            "evidence_paths",
            "required_output_fields",
        }


def test_challenge_rejects_hidden_answer_key(tmp_path, monkeypatch) -> None:
    challenge = qualification.load_operator_challenge()
    challenge["tasks"][0]["answer_key"] = {"release": "hidden"}
    challenge.pop("challenge_sha256")
    challenge["challenge_sha256"] = qualification._sha(challenge)
    path = tmp_path / "challenge.json"
    path.write_text(json.dumps(challenge), encoding="utf-8")
    monkeypatch.setattr(qualification, "CHALLENGE_PATH", path)
    with pytest.raises(IntegrityError):
        qualification.load_operator_challenge()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["task_results"]["verify-identities"][
            "identity_chain"
        ].__setitem__("candidate_release_id", "m23cand-drifted"),
        lambda value: value["task_results"]["verify-production-pointer"][
            "production_snapshot"
        ].__setitem__("pointer_sha256", "0" * 64),
        lambda value: value["task_results"].pop("run-shadow-replay"),
        lambda value: value["execution"].__setitem__(
            "prior_chat_context_used", True
        ),
        lambda value: value["carry_forward_blockers"].pop(),
        lambda value: value["task_results"][
            "inspect-graph-explorer-boundary"
        ]["graph_explorer"].__setitem__("public_route_allowed", True),
        lambda value: value["authority"].__setitem__(
            "promotion_eligibility_granted", True
        ),
        lambda value: value["protected_mutations"].__setitem__(
            "production_pointer_mutation", True
        ),
        lambda value: value["task_results"]["verify-identities"][
            "source_pr_19"
        ].__setitem__("merged", True),
        lambda value: value["execution"].__setitem__("qdrant_read_used", True),
    ],
)
def test_operator_submission_fails_closed_on_drift(mutate) -> None:
    submission = qualification.canonical_operator_submission()
    mutate(submission)
    with pytest.raises(IntegrityError):
        qualification.validate_operator_submission(_resign(submission))
