from __future__ import annotations

from knowledge_engine.api import app


def test_public_ask_openapi_uses_wrapped_error_wire_format() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/v1/ask"]["post"]
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success["$ref"].endswith("/PublicAskResponse")
    for status_code in ("401", "403", "413", "429", "503", "504"):
        error = operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert error["$ref"].endswith("/PublicErrorResponse")
    error_schema = schema["components"]["schemas"]["PublicErrorResponse"]
    assert set(error_schema["properties"]) == {"detail"}
    assert error_schema["properties"]["detail"]["$ref"].endswith(
        "/PublicErrorDetail"
    )


def test_public_ask_openapi_exposes_citation_and_source_card_contracts() -> None:
    schema = app.openapi()
    response_schema = schema["components"]["schemas"]["PublicAskResponse"]
    citation_items = response_schema["properties"]["citations"]["items"]
    source_card_items = response_schema["properties"]["source_cards"]["items"]
    assert citation_items["$ref"].endswith("/PublicCitation")
    assert source_card_items["$ref"].endswith("/PublicSourceCard")

    citation_schema = schema["components"]["schemas"]["PublicCitation"]
    assert {
        "citation_id",
        "ordinal",
        "source_card_id",
        "source_id",
        "uri",
        "concept_id",
        "section_id",
        "citation_scope",
        "claim_ids",
        "support",
        "locator",
    } <= set(citation_schema["properties"])

    card_schema = schema["components"]["schemas"]["PublicSourceCard"]
    assert {
        "source_card_id",
        "title",
        "publisher",
        "display_host",
        "uri",
        "snapshot_available",
        "integrity_sha256",
        "citation_ids",
        "concept_ids",
        "section_ids",
        "claim_ids",
    } <= set(card_schema["properties"])


def test_public_interface_capabilities_and_stream_are_documented() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    capabilities = paths["/v1/ask/capabilities"]["get"]
    capability_schema = capabilities["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert capability_schema["$ref"].endswith("/PublicProductCapabilities")

    posture = schema["components"]["schemas"]["PublicSecurityPosture"]
    assert {
        "anonymous_public_access",
        "elevated_audience_requires_authentication",
        "cors_mode",
        "allowed_origin_count",
        "wildcard_origins_allowed",
        "cross_origin_credentials",
        "rate_limit_requests",
        "rate_limit_window_seconds",
        "max_body_bytes",
        "request_timeout_seconds",
        "max_concurrent_requests",
        "distributed_rate_limit",
        "server_conversation_state",
    } <= set(posture["properties"])

    feedback_capabilities = schema["components"]["schemas"][
        "PublicFeedbackCapabilities"
    ]
    assert {
        "enabled",
        "path",
        "feedback_types",
        "immutable_intake",
        "pending_review_queue",
        "direct_source_write",
        "direct_production_write",
        "contact_identity_collected",
        "raw_query_collected",
        "raw_answer_collected",
        "attachments_supported",
    } <= set(feedback_capabilities["properties"])

    stream = paths["/v1/ask/stream"]["post"]
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    request_schema = stream["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/PublicAskRequest")
    for status_code in ("401", "403", "413", "429", "503", "504"):
        error = stream["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert error["$ref"].endswith("/PublicErrorResponse")

    assert "/ask" not in paths
    assert "/embed/ask.js" not in paths


def test_public_feedback_openapi_exposes_bounded_intake_contract() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/v1/feedback"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    accepted = operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ]
    assert request_schema["$ref"].endswith("/PublicFeedbackRequest")
    assert accepted["$ref"].endswith("/PublicFeedbackReceipt")
    for status_code in ("401", "403", "413", "422", "429", "503", "504"):
        error = operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert error["$ref"].endswith("/PublicErrorResponse")

    request = schema["components"]["schemas"]["PublicFeedbackRequest"]
    properties = set(request["properties"])
    assert properties == {
        "feedback_type",
        "request_id",
        "release_id",
        "audience",
        "message",
        "citation_id",
        "source_card_id",
        "concept_id",
        "section_id",
        "reference_uri",
        "locale",
    }
    for forbidden in ("query", "answer", "email", "name", "metadata"):
        assert forbidden not in properties

    receipt = schema["components"]["schemas"]["PublicFeedbackReceipt"]
    receipt_properties = set(receipt["properties"])
    assert "feedback_id" in receipt_properties
    assert "curation_status" in receipt_properties
    assert "source_write_performed" in receipt_properties
    assert "production_write_performed" in receipt_properties
    for forbidden in (
        "intake_key",
        "queue_key",
        "submitter_scope_sha256",
        "identity_sha256",
    ):
        assert forbidden not in receipt_properties
