from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from knowledge_engine import api
from knowledge_engine.auth import Principal
from knowledge_engine.m14_feedback_contracts import (
    FEEDBACK_TYPES,
    PublicFeedbackReceipt,
    PublicFeedbackRequest,
)
from knowledge_engine.m14_security import (
    PUBLIC_API_PATHS,
    PUBLIC_PATHS,
    PUBLIC_POST_PATHS,
    PublicRequestIdentity,
)


def _principal(*audiences: str, authenticated: bool) -> Principal:
    return Principal(
        subject="feedback-user",
        audiences=frozenset(audiences),
        claims={},
        authenticated=authenticated,
    )


def _identity(*audiences: str, authenticated: bool) -> PublicRequestIdentity:
    return PublicRequestIdentity(
        principal=_principal(*audiences, authenticated=authenticated),
        client_key="a" * 64,
    )


def _request(**overrides) -> PublicFeedbackRequest:
    payload = {
        "feedback_type": "helpful",
        "request_id": "req_" + "1" * 32,
        "release_id": "release-a",
        "audience": "public",
        "locale": "en",
    }
    payload.update(overrides)
    return PublicFeedbackRequest(**payload)


def test_feedback_route_is_registered_with_all_public_edge_controls() -> None:
    assert "/v1/feedback" in PUBLIC_API_PATHS
    assert "/v1/feedback" in PUBLIC_POST_PATHS
    assert "/v1/feedback" in PUBLIC_PATHS


def test_anonymous_public_feedback_is_accepted_without_source_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubIntake:
        def submit(self, request, *, client_key: str, authenticated: bool):
            assert request.feedback_type == "helpful"
            assert client_key == "a" * 64
            assert authenticated is False
            return PublicFeedbackReceipt(
                feedback_id="fb_" + "2" * 32,
                status="accepted",
                feedback_type=request.feedback_type,
                request_id=request.request_id,
                release_id=request.release_id,
                audience=request.audience,
                received_at="2026-07-10T00:00:00Z",
                privacy_redactions_applied=False,
            )

    monkeypatch.setattr(api, "get_feedback_intake", lambda: StubIntake())
    receipt = api.feedback(
        _request(),
        _identity("public", authenticated=False),
    )
    assert receipt.status == "accepted"
    assert receipt.source_write_performed is False
    assert receipt.production_write_performed is False


def test_feedback_audience_escalation_is_rejected() -> None:
    with pytest.raises(HTTPException) as anonymous:
        api.feedback(
            _request(audience="internal"),
            _identity("public", authenticated=False),
        )
    assert anonymous.value.status_code == 403

    with pytest.raises(HTTPException) as missing_claim:
        api.feedback(
            _request(audience="internal"),
            _identity("public", authenticated=True),
        )
    assert missing_claim.value.status_code == 403


def test_authenticated_exact_audience_feedback_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = SimpleNamespace(request=None)

    class StubIntake:
        def submit(self, request, *, client_key: str, authenticated: bool):
            captured.request = request
            assert authenticated is True
            return PublicFeedbackReceipt(
                feedback_id="fb_" + "3" * 32,
                status="accepted",
                feedback_type=request.feedback_type,
                request_id=request.request_id,
                release_id=request.release_id,
                audience=request.audience,
                received_at="2026-07-10T00:00:00Z",
                privacy_redactions_applied=False,
            )

    monkeypatch.setattr(api, "get_feedback_intake", lambda: StubIntake())
    receipt = api.feedback(
        _request(audience="internal"),
        _identity("public", "internal", authenticated=True),
    )
    assert receipt.audience == "internal"
    assert captured.request.audience == "internal"


def test_feedback_service_errors_use_stable_public_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnsafeIntake:
        def submit(self, *args, **kwargs):
            raise ValueError("reference_uri is not a safe public HTTP(S) URI")

    monkeypatch.setattr(api, "get_feedback_intake", lambda: UnsafeIntake())
    with pytest.raises(HTTPException) as unsafe:
        api.feedback(_request(), _identity("public", authenticated=False))
    assert unsafe.value.status_code == 422
    assert unsafe.value.detail["code"] == "PUBLIC-FEEDBACK-422"

    class UnavailableIntake:
        def submit(self, *args, **kwargs):
            raise FileNotFoundError("store unavailable")

    monkeypatch.setattr(api, "get_feedback_intake", lambda: UnavailableIntake())
    with pytest.raises(HTTPException) as unavailable:
        api.feedback(_request(), _identity("public", authenticated=False))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == {
        "schema_version": "knowledge-engine-public-query/v1/error",
        "code": "PUBLIC-FEEDBACK-503",
        "message": "feedback intake is temporarily unavailable",
        "request_id": None,
    }


def test_capabilities_advertise_feedback_without_write_power(monkeypatch) -> None:
    settings = SimpleNamespace(
        public_anonymous_enabled=True,
        public_allowed_origins=(),
        public_rate_limit_requests=30,
        public_rate_limit_window_seconds=60,
        public_max_body_bytes=16384,
        public_request_timeout_seconds=15.0,
        public_max_concurrent_requests=8,
    )
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    capabilities = api.ask_capabilities_endpoint().model_dump()
    feedback = capabilities["feedback"]
    assert feedback["path"] == "/v1/feedback"
    assert feedback["feedback_types"] == list(FEEDBACK_TYPES)
    assert feedback["immutable_intake"] is True
    assert feedback["pending_review_queue"] is True
    assert feedback["direct_source_write"] is False
    assert feedback["direct_production_write"] is False
    assert feedback["contact_identity_collected"] is False
    assert feedback["raw_query_collected"] is False
    assert feedback["raw_answer_collected"] is False


def test_served_widget_has_feedback_controls_without_raw_answer_submission() -> None:
    script = api.ask_widget_script().body.decode("utf-8")
    assert 'feedbackEndpoint()' in script
    assert '"/v1/feedback"' in script
    assert 'this.copy.helpful' in script
    assert 'this.copy.unhelpful' in script
    assert 'this.copy.correction' in script
    assert 'feedback_type: type' in script
    assert 'request_id: state.meta.request_id' in script
    assert 'release_id: state.meta.release_id' in script
    assert 'citation_id' in script
    assert 'source_card_id' in script
    assert 'concept_id' in script
    assert 'section_id' in script
    assert 'body.query' not in script
    assert 'body.answer' not in script
    assert 'credentials: endpoint.origin === window.location.origin' in script
    assert '? "same-origin"' in script
    assert ': "omit"' in script
    for forbidden in (
        "inner" + "HTML",
        "local" + "Storage",
        "session" + "Storage",
        "document" + ".cookie",
    ):
        assert forbidden not in script
