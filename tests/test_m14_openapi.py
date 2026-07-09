from __future__ import annotations

from knowledge_engine.api import app


def test_public_ask_openapi_uses_wrapped_error_wire_format() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/v1/ask"]["post"]
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    forbidden = operation["responses"]["403"]["content"]["application/json"]["schema"]
    unavailable = operation["responses"]["503"]["content"]["application/json"]["schema"]
    assert success["$ref"].endswith("/PublicAskResponse")
    assert forbidden["$ref"].endswith("/PublicErrorResponse")
    assert unavailable["$ref"].endswith("/PublicErrorResponse")
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
    assert capability_schema["$ref"].endswith("/PublicInterfaceCapabilities")

    stream = paths["/v1/ask/stream"]["post"]
    assert "text/event-stream" in stream["responses"]["200"]["content"]
    request_schema = stream["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/PublicAskRequest")
    assert stream["responses"]["403"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PublicErrorResponse")

    assert "/ask" not in paths
    assert "/embed/ask.js" not in paths
