from __future__ import annotations

from copy import deepcopy

import pytest

from knowledge_engine.m14_public_contracts import public_response_from_runtime
from knowledge_engine.m14_source_cards import (
    build_public_citation_payload,
    safe_public_uri,
)


def _candidate(**overrides) -> dict:
    value = {
        "source_id": "source-1",
        "source_kind": "web",
        "source_title": "Example Specification",
        "publisher": "Example Foundation",
        "uri": "https://www.example.com/spec?b=2&a=1#fragment",
        "retrieved_at": "2026-07-10T00:00:00Z",
        "published_at": "2026-06-01T00:00:00Z",
        "content_sha256": "a" * 64,
        "snapshot_available": True,
        "concept_id": "concepts/example",
        "section_id": "concepts/example#rule",
        "citation_scope": "claim",
        "claim_id": "claim-rule",
        "support": "direct",
        "locator": {
            "heading": "  Specification  ",
            "page": 4,
            "quote": "must not leak",
            "unknown": "must not leak",
        },
        "claim_confidence": 0.97,
        "review_status": "human_approved",
        "derivation_type": "synthesized",
    }
    value.update(overrides)
    return value


def _result(candidate: dict, *, section_id: str = "concepts/example#rule") -> dict:
    return {
        "concept_id": candidate.get("concept_id", "concepts/example"),
        "section_id": section_id,
        "title": "Example",
        "section_title": "Rule",
        "excerpt": "The rule is governed.",
        "score": 10,
        "citations": [candidate],
    }


@pytest.mark.parametrize(
    "uri",
    [
        "file:///tmp/source.md",
        "https://user:password@example.com/spec",
        "https://example.com/spec?token=secret",
        "https://example.com/spec?x-amz-signature=secret",
        "http://127.0.0.1/spec",
        "http://10.0.0.1/spec",
        "http://localhost/spec",
        "https://wiki.internal/spec",
    ],
)
def test_unsafe_source_uris_are_suppressed(uri: str) -> None:
    assert safe_public_uri(uri) is None


def test_safe_uri_is_canonicalized_without_fragment() -> None:
    assert safe_public_uri("HTTPS://www.example.com/spec?b=2&a=1#secret") == (
        "https://www.example.com/spec?a=1&b=2"
    )


def test_source_card_groups_multiple_citations_for_same_source() -> None:
    first = _candidate()
    second = _candidate(
        concept_id="concepts/second",
        section_id="concepts/second#overview",
        claim_id="claim-second",
        locator={"heading": "Second"},
    )
    citations, cards, ordinals = build_public_citation_payload(
        results=[
            _result(first),
            _result(second, section_id="concepts/second#overview"),
        ],
        release_id="release-a",
    )
    assert len(citations) == 2
    assert [item["ordinal"] for item in citations] == [1, 2]
    assert len(cards) == 1
    card = cards[0]
    assert card["display_host"] == "example.com"
    assert card["citation_ids"] == [
        citations[0]["citation_id"],
        citations[1]["citation_id"],
    ]
    assert card["concept_ids"] == ["concepts/example", "concepts/second"]
    assert card["claim_ids"] == ["claim-rule", "claim-second"]
    assert ordinals[("concepts/example", "concepts/example#rule")] == [1]
    assert ordinals[("concepts/second", "concepts/second#overview")] == [2]


def test_duplicate_evidence_combines_claim_ids_deterministically() -> None:
    first = _candidate(claim_id="claim-b")
    second = _candidate(claim_id="claim-a")
    citations, cards, _ = build_public_citation_payload(
        results=[
            {
                **_result(first),
                "citations": [first, second],
            }
        ],
        release_id="release-a",
    )
    assert len(citations) == 1
    assert citations[0]["claim_ids"] == ["claim-a", "claim-b"]
    assert cards[0]["claim_ids"] == ["claim-a", "claim-b"]


def test_citation_and_card_ids_are_replayable_and_release_bound() -> None:
    results = [_result(_candidate())]
    first = build_public_citation_payload(results=results, release_id="release-a")
    replay = build_public_citation_payload(
        results=deepcopy(results),
        release_id="release-a",
    )
    changed = build_public_citation_payload(
        results=deepcopy(results),
        release_id="release-b",
    )
    assert first == replay
    assert first[0][0]["citation_id"] != changed[0][0]["citation_id"]
    assert first[1][0]["source_card_id"] != changed[1][0]["source_card_id"]


def test_locator_is_bounded_and_source_internals_are_not_exposed() -> None:
    citations, cards, _ = build_public_citation_payload(
        results=[_result(_candidate())],
        release_id="release-a",
    )
    assert citations[0]["locator"] == {
        "heading": "Specification",
        "page": 4,
    }
    serialized = repr((citations, cards))
    assert "snapshot_key" not in serialized
    assert "must not leak" not in serialized
    assert "raw.md" not in serialized


def test_legacy_minimal_citation_remains_compatible() -> None:
    candidate = {
        "source_id": "legacy-source",
        "uri": "https://example.com/legacy",
        "retrieved_at": "2026-07-10T00:00:00Z",
        "concept_id": "concepts/example",
        "section_id": "concepts/example#overview",
    }
    citations, cards, _ = build_public_citation_payload(
        results=[_result(candidate, section_id="concepts/example#overview")],
        release_id="release-a",
    )
    assert citations[0]["citation_scope"] == "concept"
    assert citations[0]["support"] == "context"
    assert citations[0]["claim_ids"] == []
    assert cards[0]["title"] == "example.com"
    assert cards[0]["snapshot_available"] is False


def test_all_unsafe_citations_produce_degraded_answer_without_leak() -> None:
    runtime = {
        "status": "answered",
        "release": {
            "release_id": "release-a",
            "manifest_sha256": "a" * 64,
        },
        "results": [
            _result(
                _candidate(
                    uri="https://example.com/private?token=secret-value"
                )
            )
        ],
        "not_found_reason": None,
    }
    response = public_response_from_runtime(
        runtime,
        query="example",
        max_results=5,
        audience="public",
    )
    assert response.status == "degraded"
    assert response.answer == "Example · Rule: The rule is governed."
    assert response.citations == []
    assert response.source_cards == []
    assert "secret-value" not in response.model_dump_json()
