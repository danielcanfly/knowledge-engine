from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m14_feedback import (
    FeedbackIntake,
    feedback_object_keys,
    sanitize_feedback_text,
)
from knowledge_engine.m14_feedback_contracts import PublicFeedbackRequest
from knowledge_engine.storage import FileObjectStore


def _request(**overrides) -> PublicFeedbackRequest:
    value = {
        "feedback_type": "factual_correction",
        "request_id": "req_" + "1" * 32,
        "release_id": "20260710T000000Z-aaaaaaaaaaaa",
        "audience": "public",
        "message": "The operational rule should mention verification.",
        "citation_id": "cite_" + "2" * 32,
        "source_card_id": "card_" + "3" * 32,
        "concept_id": "concepts/compiler",
        "section_id": "concepts/compiler#operations",
        "reference_uri": "https://example.com/spec?b=2&a=1#fragment",
        "locale": "en",
    }
    value.update(overrides)
    return PublicFeedbackRequest(**value)


def test_feedback_contract_requires_explanation_and_target() -> None:
    with pytest.raises(ValidationError, match="message is required"):
        PublicFeedbackRequest(
            feedback_type="missing_coverage",
            request_id="req_" + "1" * 32,
            release_id="release-a",
        )
    with pytest.raises(ValidationError, match="citation_issue requires"):
        PublicFeedbackRequest(
            feedback_type="citation_issue",
            request_id="req_" + "1" * 32,
            release_id="release-a",
            message="The source does not support this claim.",
        )
    with pytest.raises(ValidationError, match="factual_correction requires"):
        PublicFeedbackRequest(
            feedback_type="factual_correction",
            request_id="req_" + "1" * 32,
            release_id="release-a",
            message="This statement is inaccurate.",
        )
    with pytest.raises(ValidationError, match="section_id must belong"):
        _request(section_id="concepts/other#overview")


def test_feedback_contract_forbids_query_answer_contact_and_metadata_fields() -> None:
    for forbidden in ("query", "answer", "email", "name", "metadata"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PublicFeedbackRequest(
                feedback_type="helpful",
                request_id="req_" + "1" * 32,
                release_id="release-a",
                **{forbidden: "must not be collected"},
            )


def test_feedback_text_is_normalized_and_sensitive_values_are_redacted() -> None:
    text, redactions = sanitize_feedback_text(
        "  Contact ME@Example.COM\x00 Bearer abcdefghijklmnop "
        "api_key=super-secret  "
    )
    assert text == (
        "Contact [redacted-email] [redacted-token] [redacted-secret]"
    )
    assert redactions == [
        "bearer_token",
        "control_character",
        "email",
        "secret",
    ]


def test_feedback_submission_is_immutable_replayable_and_queue_bound(
    tmp_path: Path,
) -> None:
    store = FileObjectStore(tmp_path / "store")
    times = iter(("2026-07-10T00:00:00Z", "2026-07-10T01:00:00Z"))
    intake = FeedbackIntake(store, now=lambda: next(times))
    request = _request(
        message="Contact me@example.com. Bearer abcdefghijklmnop",
    )

    accepted = intake.submit(
        request,
        client_key="client-a",
        authenticated=False,
    )
    intake_key, queue_key = feedback_object_keys(accepted.feedback_id)
    intake_bytes = store.get(intake_key)
    queue_bytes = store.get(queue_key)
    record = json.loads(intake_bytes)
    queue = json.loads(queue_bytes)

    assert accepted.status == "accepted"
    assert accepted.privacy_redactions_applied is True
    assert accepted.source_write_performed is False
    assert accepted.production_write_performed is False
    assert record["message"] == "Contact [redacted-email]. [redacted-token]"
    assert record["reference_uri"] == "https://example.com/spec?a=1&b=2"
    assert record["submitter_class"] == "anonymous"
    assert len(record["submitter_scope_sha256"]) == 64
    assert record["governance"] == {
        "candidate_dispatch_allowed": False,
        "ledger_append_allowed": False,
        "production_write_allowed": False,
        "review_state": "pending_review",
        "source_write_allowed": False,
    }
    assert queue["feedback_id"] == accepted.feedback_id
    assert queue["state"] == "pending_review"
    assert queue["proposed_action"] == "review_feedback"
    assert queue["source_write_allowed"] is False
    assert queue["production_write_allowed"] is False

    duplicate = intake.submit(
        request,
        client_key="client-a",
        authenticated=False,
    )
    assert duplicate.status == "duplicate"
    assert duplicate.feedback_id == accepted.feedback_id
    assert duplicate.received_at == accepted.received_at
    assert store.get(intake_key) == intake_bytes
    assert store.get(queue_key) == queue_bytes

    payload = duplicate.model_dump()
    assert "intake_key" not in payload
    assert "queue_key" not in payload
    assert "submitter_scope_sha256" not in payload
    assert "identity_sha256" not in payload


def test_different_submitters_produce_distinct_feedback_identities(
    tmp_path: Path,
) -> None:
    store = FileObjectStore(tmp_path / "store")
    intake = FeedbackIntake(store, now=lambda: "2026-07-10T00:00:00Z")
    first = intake.submit(_request(), client_key="client-a", authenticated=False)
    second = intake.submit(_request(), client_key="client-b", authenticated=False)
    assert first.feedback_id != second.feedback_id


class _FailQueueOnceStore:
    def __init__(self, delegate: FileObjectStore) -> None:
        self.delegate = delegate
        self.failed = False

    def put(self, key, data, **kwargs):
        if "curation-queue" in key and not self.failed:
            self.failed = True
            raise RuntimeError("simulated queue outage")
        return self.delegate.put(key, data, **kwargs)

    def get(self, key):
        return self.delegate.get(key)

    def head(self, key):
        return self.delegate.head(key)

    def delete(self, key):
        return self.delegate.delete(key)


def test_replay_heals_interrupted_queue_publication(tmp_path: Path) -> None:
    delegate = FileObjectStore(tmp_path / "store")
    store = _FailQueueOnceStore(delegate)
    intake = FeedbackIntake(store, now=lambda: "2026-07-10T00:00:00Z")
    request = _request()

    with pytest.raises(RuntimeError, match="queue outage"):
        intake.submit(request, client_key="client-a", authenticated=False)

    expected = FeedbackIntake(
        delegate,
        now=lambda: "2026-07-10T01:00:00Z",
    ).submit(request, client_key="client-a", authenticated=False)
    intake_key, queue_key = feedback_object_keys(expected.feedback_id)
    assert expected.status == "duplicate"
    assert delegate.head(intake_key) is not None
    assert delegate.head(queue_key) is not None
    queue = json.loads(delegate.get(queue_key))
    assert queue["created_at"] == "2026-07-10T00:00:00Z"


def test_unsafe_reference_uri_is_rejected_without_fetch(tmp_path: Path) -> None:
    intake = FeedbackIntake(
        FileObjectStore(tmp_path / "store"),
        now=lambda: "2026-07-10T00:00:00Z",
    )
    for uri in (
        "file:///tmp/source.md",
        "http://127.0.0.1/private",
        "https://example.com/spec?token=secret",
    ):
        with pytest.raises(ValueError, match="safe public"):
            intake.submit(
                _request(reference_uri=uri),
                client_key="client-a",
                authenticated=False,
            )


def test_corrupt_existing_identity_fails_closed(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    intake = FeedbackIntake(store, now=lambda: "2026-07-10T00:00:00Z")
    receipt = intake.submit(_request(), client_key="client-a", authenticated=False)
    intake_key, _ = feedback_object_keys(receipt.feedback_id)
    record = json.loads(store.get(intake_key))
    record["identity_sha256"] = "f" * 64
    store.put(
        intake_key,
        (json.dumps(record, sort_keys=True) + "\n").encode(),
        content_type="application/json",
    )
    with pytest.raises(IntegrityError, match="identity collision"):
        intake.submit(_request(), client_key="client-a", authenticated=False)
