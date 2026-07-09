from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from knowledge_engine import api
from knowledge_engine.auth import Principal
from knowledge_engine.m14_interfaces import (
    PUBLIC_INTERFACE_SCHEMA,
    PUBLIC_STREAM_SCHEMA,
    normalize_interface_locale,
    public_ask_widget_javascript,
    public_interface_capabilities,
    public_interface_sse_events,
    standalone_ask_html,
)
from knowledge_engine.m14_public_contracts import PublicAskRequest, PublicAskResponse


def _principal(*audiences: str) -> Principal:
    return Principal(
        subject="interface-user",
        audiences=frozenset(audiences),
        claims={},
    )


def _response(*, status: str = "answered") -> PublicAskResponse:
    answered = status != "not_found"
    cited = status == "answered"
    citation_id = "cite_" + "1" * 32
    card_id = "card_" + "2" * 32
    return PublicAskResponse(
        answer=(
            "Knowledge Compiler: Reviewed knowledge. [1]\n\n"
            "Operational rule: Verify before changing the pointer. [1]"
            if answered
            else None
        ),
        status=status,
        citations=(
            [
                {
                    "citation_id": citation_id,
                    "ordinal": 1,
                    "source_card_id": card_id,
                    "source_id": "source-1",
                    "source_kind": "web",
                    "uri": "https://example.com/spec",
                    "retrieved_at": "2026-07-10T00:00:00Z",
                    "concept_id": "concepts/compiler",
                    "section_id": "concepts/compiler#operations",
                    "citation_scope": "claim",
                    "claim_ids": ["claim-1"],
                    "support": "direct",
                    "locator": {"heading": "Specification"},
                    "claim_confidence": 0.97,
                    "review_status": "human_approved",
                    "derivation_type": "synthesized",
                }
            ]
            if cited
            else []
        ),
        source_cards=(
            [
                {
                    "source_card_id": card_id,
                    "ordinal": 1,
                    "source_id": "source-1",
                    "title": "Compiler Specification",
                    "publisher": "Example Foundation",
                    "display_host": "example.com",
                    "source_kind": "web",
                    "uri": "https://example.com/spec",
                    "retrieved_at": "2026-07-10T00:00:00Z",
                    "published_at": None,
                    "snapshot_available": True,
                    "integrity_sha256": "a" * 64,
                    "citation_ids": [citation_id],
                    "concept_ids": ["concepts/compiler"],
                    "section_ids": ["concepts/compiler#operations"],
                    "claim_ids": ["claim-1"],
                }
            ]
            if cited
            else []
        ),
        concept_ids=["concepts/compiler"] if answered else [],
        release_id="release-a",
        request_id="req_" + "3" * 32,
        audience="public",
        confidence=0.82 if cited else (0.42 if answered else 0.0),
        not_found_reason="no_match" if status == "not_found" else None,
    )


def _events(response: PublicAskResponse) -> list[tuple[str, dict]]:
    output = []
    for block in public_interface_sse_events(response):
        lines = block.strip().splitlines()
        event = next(
            line.split(":", 1)[1].strip()
            for line in lines
            if line.startswith("event:")
        )
        data = next(
            line.split(":", 1)[1].strip()
            for line in lines
            if line.startswith("data:")
        )
        output.append((event, json.loads(data)))
    return output


async def _stream_text(stream) -> str:
    chunks = []
    async for chunk in stream.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_interface_capabilities_are_stable_and_stateless() -> None:
    capabilities = public_interface_capabilities().model_dump()
    assert capabilities["schema_version"] == PUBLIC_INTERFACE_SCHEMA
    assert capabilities["surfaces"] == ["api", "standalone_chat", "blog_widget"]
    assert capabilities["transports"] == ["json", "sse"]
    assert capabilities["session_mode"] == "stateless"
    assert capabilities["default_audience"] == "public"
    assert capabilities["same_origin_default"] is True
    assert capabilities["ask_path"] == "/v1/ask"
    assert capabilities["stream_path"] == "/v1/ask/stream"
    assert capabilities["standalone_path"] == "/ask"
    assert capabilities["widget_script_path"] == "/embed/ask.js"
    assert capabilities["supported_locales"] == ["en", "zh-TW"]
    assert capabilities["max_query_characters"] == 8000
    assert capabilities["max_results"] == 20
    assert capabilities["stream_event_order"] == [
        "meta",
        "answer",
        "citations",
        "source_cards",
        "done",
    ]


def test_standalone_page_is_self_contained_and_locale_bounded() -> None:
    html = standalone_ask_html("zh-TW")
    assert normalize_interface_locale("zh-TW") == "zh-TW"
    assert normalize_interface_locale("unsupported") == "en"
    assert '<html lang="zh-TW">' in html
    assert "<knowledge-ask" in html
    assert 'data-endpoint="/v1/ask/stream"' in html
    assert 'src="/embed/ask.js"' in html
    assert "https://" not in html
    assert "http://" not in html

    response = api.ask_page("zh-TW")
    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert response.headers["cache-control"] == "no-store"
    policy = response.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy
    assert response.headers["referrer-policy"] == "no-referrer"


def test_widget_uses_safe_dom_and_ephemeral_client_state() -> None:
    script = public_ask_widget_javascript()
    assert 'customElements.define("knowledge-ask"' in script
    assert 'attachShadow({ mode: "open" })' in script
    assert "textContent" in script
    assert 'rel = "noopener noreferrer"' in script
    assert 'credentials: "same-origin"' in script
    assert '"Accept": "text/event-stream"' in script
    assert "cross-origin endpoint is disabled" in script
    forbidden = (
        "inner" + "HTML",
        "outer" + "HTML",
        "local" + "Storage",
        "session" + "Storage",
        "document" + ".cookie",
        "insertAdjacent" + "HTML",
    )
    for value in forbidden:
        assert value not in script

    response = api.ask_widget_script()
    assert response.media_type == "application/javascript"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_sse_event_order_and_payload_are_deterministic() -> None:
    response = _response()
    first = list(public_interface_sse_events(response))
    replay = list(public_interface_sse_events(response))
    assert first == replay

    events = _events(response)
    assert [name for name, _ in events] == [
        "meta",
        "answer",
        "answer",
        "citations",
        "source_cards",
        "done",
    ]
    assert events[0][1]["schema_version"] == PUBLIC_STREAM_SCHEMA
    assert events[0][1]["session_mode"] == "stateless"
    assert events[1][1]["index"] == 0
    assert events[2][1]["index"] == 1
    assert events[3][1]["items"][0]["citation_id"].startswith("cite_")
    assert events[4][1]["items"][0]["source_card_id"].startswith("card_")
    assert events[5][1] == {
        "event_count": 6,
        "request_id": response.request_id,
        "status": "answered",
    }


def test_not_found_and_degraded_streams_are_explicit() -> None:
    not_found = _events(_response(status="not_found"))
    assert [name for name, _ in not_found] == [
        "meta",
        "citations",
        "source_cards",
        "done",
    ]
    assert not_found[0][1]["status"] == "not_found"
    assert not_found[0][1]["not_found_reason"] == "no_match"
    assert not_found[1][1]["items"] == []
    assert not_found[2][1]["items"] == []

    degraded = _events(_response(status="degraded"))
    assert degraded[0][1]["status"] == "degraded"
    assert [name for name, _ in degraded].count("answer") == 2
    assert degraded[-2][1]["items"] == []


def test_json_and_stream_surfaces_share_exact_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_result = {
        "status": "answered",
        "release": {
            "release_id": "release-shared",
            "manifest_sha256": "a" * 64,
        },
        "results": [
            {
                "concept_id": "concepts/compiler",
                "section_id": "concepts/compiler#overview",
                "title": "Compiler",
                "section_title": "Overview",
                "excerpt": "A governed compiler.",
                "score": 10,
                "citations": [],
            }
        ],
        "not_found_reason": None,
    }

    class StubRuntime:
        def query(self, query: str, audiences: set[str], *, limit: int) -> dict:
            assert query == "compiler"
            assert audiences == {"public"}
            assert limit == 4
            return runtime_result

    monkeypatch.setattr(api, "get_runtime", lambda: StubRuntime())
    request = PublicAskRequest(query="compiler", max_results=4, audience="public")
    principal = _principal("public")
    json_response = api.ask(request, principal)
    stream_response = api.ask_stream(request, principal)
    stream_text = asyncio.run(_stream_text(stream_response))

    assert json_response.status == "degraded"
    assert json_response.request_id in stream_text
    assert json_response.release_id in stream_text
    assert "event: meta" in stream_text
    assert "event: done" in stream_text
    assert stream_response.headers["cache-control"] == "no-store"
    assert stream_response.headers["x-accel-buffering"] == "no"


def test_stream_rejects_audience_escalation() -> None:
    with pytest.raises(HTTPException) as exc:
        api.ask_stream(
            PublicAskRequest(query="restricted topic", audience="internal"),
            _principal("public"),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "PUBLIC-QUERY-403"


def test_capabilities_endpoint_requires_no_runtime() -> None:
    response = api.ask_capabilities()
    assert response.session_mode == "stateless"
    assert response.stream_path == "/v1/ask/stream"
    assert response.widget_script_path == "/embed/ask.js"
