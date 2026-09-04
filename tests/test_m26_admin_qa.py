from __future__ import annotations

import hashlib

from knowledge_engine.m26_admin_qa import (
    InMemoryQaEventSource,
    UnavailableQaEventSource,
    build_qa_markdown,
    redact_qa_text,
)


def _event(trace_id: str = "trace-1") -> dict:
    return {
        "trace_id": trace_id,
        "timestamp": "2026-09-04T00:00:00Z",
        "release_id": "release-1",
        "outcome": "retrieval_failure",
        "question": "Where is the evidence?",
        "answer": ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz\nNo citation returned."),
        "provider": "fixture-provider",
        "fallback": "none",
        "retrieval_status": "empty",
        "citation_count": 0,
        "latency_ms": 801,
        "reason_code": "NO_MATCH",
        "timeline": [{"stage": "retrieval", "status": "empty", "latency_ms": 88}],
        "provider_context": {"x-api-key": "never-export-me"},
    }


def test_unavailable_source_does_not_fabricate_empty_events() -> None:
    result = UnavailableQaEventSource().list_events(event_class=None, release_id=None)
    assert result.availability == "unavailable"
    assert result.data is None
    assert result.observed_at is None


def test_in_memory_source_filters_only_contract_backed_fields() -> None:
    source = InMemoryQaEventSource(
        [_event(), {**_event("trace-2"), "outcome": "refusal"}],
        observed_at="2026-09-04T00:00:00Z",
    )
    result = source.list_events(event_class="refusal", release_id="release-1")
    assert result.availability == "available"
    assert [row["trace_id"] for row in result.data["events"]] == ["trace-2"]


def test_export_is_deterministic_and_redacts_hostile_header_text() -> None:
    markdown_a = build_qa_markdown([_event()])
    markdown_b = build_qa_markdown([_event()])
    assert markdown_a == markdown_b
    assert (
        hashlib.sha256(markdown_a.encode()).hexdigest()
        == hashlib.sha256(markdown_b.encode()).hexdigest()
    )
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in markdown_a
    assert "never-export-me" not in markdown_a
    assert "Authorization: [REDACTED]" in markdown_a
    assert "[REDACTED]" in markdown_a


def test_redaction_catches_header_and_assignment_forms() -> None:
    hostile = "Cookie: session=topsecret\napi_key=abcdef123456\nhello"
    safe = redact_qa_text(hostile)
    assert "topsecret" not in safe
    assert "abcdef123456" not in safe
    assert "Cookie: [REDACTED]" in safe
    assert "api_key=[REDACTED]" in safe


def test_inline_metadata_cannot_inject_markdown_headings() -> None:
    event = {
        **_event("trace`\n# injected"),
        "release_id": "release\n## forged",
    }
    markdown = build_qa_markdown([event])
    assert "\n# injected" not in markdown
    assert "\n## forged" not in markdown
    assert "trace\\` # injected" in markdown
