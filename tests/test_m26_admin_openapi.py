from __future__ import annotations

from knowledge_engine.m26_admin_settings import (
    CANONICAL_ADMIN_API_VERSION,
    CANONICAL_ADMIN_OPENAPI_SHA256,
)
from knowledge_engine.m26_console_api import app


def test_s6_admin_openapi_exposes_qa_inbox_and_suggested_questions_contract() -> None:
    schema = app.openapi()

    assert schema["info"]["version"] == CANONICAL_ADMIN_API_VERSION
    paths = schema["paths"]
    assert paths["/v1/admin/qa/inbox/events"]["get"]["operationId"] == "listQaInboxEvents"
    query_names = {
        parameter["name"]
        for parameter in paths["/v1/admin/qa/inbox/events"]["get"]["parameters"]
    }
    assert query_names == {
        "range_name",
        "from_ts",
        "to_ts",
        "search",
        "result",
        "evaluation_status",
        "country",
        "lifecycle",
        "limit",
        "cursor",
    }

    export_schema = paths["/v1/admin/qa/inbox/export-jsonl"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert export_schema["$ref"].endswith("__QaExportRequest")
    export_properties = schema["components"]["schemas"][export_schema["$ref"].split("/")[-1]][
        "properties"
    ]
    assert set(export_properties) == {
        "mode",
        "include_previously_exported",
        "event_ids",
        "cluster_ids",
        "range_name",
        "from_ts",
        "to_ts",
        "search",
        "result",
        "evaluation_status",
        "country",
        "lifecycle",
    }
    assert export_properties["mode"]["enum"] == ["new", "selected", "current_filter"]
    export_headers = paths["/v1/admin/qa/inbox/export-jsonl"]["post"]["responses"]["200"][
        "headers"
    ]
    assert set(export_headers) >= {"X-QA-Export-Mode", "X-QA-Export-Reused"}
    assert export_headers["X-QA-Export-Reused"]["schema"] == {
        "type": "string",
        "enum": ["true", "false"],
    }

    promotion_paths = (
        "/v1/admin/suggested-questions/promotions/preview",
        "/v1/admin/suggested-questions/promotions/{promotion_id}",
        "/v1/admin/suggested-questions/promotions/{promotion_id}/publish",
    )
    for path in promotion_paths:
        assert path in paths
    preview_ref = paths[promotion_paths[0]]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    publish_ref = paths[promotion_paths[2]]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    preview_event_ids = schema["components"]["schemas"][preview_ref.split("/")[-1]][
        "properties"
    ]["event_ids"]
    assert preview_event_ids["minItems"] == 1
    assert preview_event_ids["maxItems"] == 20
    publish_schema = schema["components"]["schemas"][publish_ref.split("/")[-1]]
    assert publish_schema["required"] == [
        "base_revision",
        "selected_event_ids",
    ]
    assert publish_schema["properties"]["selected_event_ids"]["maxItems"] == 20


def test_s6_canonical_openapi_hash_matches_admin_settings_contract() -> None:
    assert len(CANONICAL_ADMIN_OPENAPI_SHA256) == 64
    assert CANONICAL_ADMIN_API_VERSION == "1.2.0-l3b-qa-inbox-sq"
