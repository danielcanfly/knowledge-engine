from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from knowledge_engine import api
from knowledge_engine.auth import Principal
from knowledge_engine.m14_public_contracts import (
    PUBLIC_QUERY_SCHEMA,
    PublicAskRequest,
    PublicSearchRequest,
    public_request_id,
    public_response_from_runtime,
    public_search_response_from_runtime,
)


def _runtime_result(*, answered: bool = True) -> dict:
    results = []
    if answered:
        results = [
            {
                "concept_id": "concepts/compiler",
                "section_id": "concepts/compiler#operations",
                "title": "Knowledge Compiler",
                "section_title": "Operations",
                "excerpt": "The compiler validates reviewed knowledge.",
                "score": 12,
                "citations": [
                    {
                        "source_id": "source-1",
                        "source_kind": "web",
                        "source_title": "Compiler Specification",
                        "publisher": "Example Foundation",
                        "uri": "https://example.com/compiler",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                        "published_at": "2026-06-01T00:00:00Z",
                        "content_sha256": "b" * 64,
                        "snapshot_available": True,
                        "concept_id": "concepts/compiler",
                        "section_id": "concepts/compiler#operations",
                        "citation_scope": "claim",
                        "claim_id": "claim-1",
                        "support": "direct",
                        "locator": {"heading": "Operations"},
                        "claim_confidence": 0.98,
                        "review_status": "human_approved",
                        "derivation_type": "synthesized",
                    }
                ],
            }
        ]
    return {
        "status": "answered" if answered else "not_found",
        "release": {
            "release_id": "20260710T000000Z-aaaaaaaaaaaa",
            "manifest_sha256": "a" * 64,
        },
        "results": results,
        "not_found_reason": None if answered else "no_match",
    }


def _search_runtime_result() -> dict:
    result = _runtime_result()
    first = result["results"][0]
    result["results"] = [
        {
            **first,
            "concept_id": "concepts/zeta",
            "section_id": "concepts/zeta#overview",
            "title": "Zeta Concept",
            "section_title": "Overview",
            "score": 15,
        },
        {
            **first,
            "concept_id": "concepts/alpha",
            "section_id": "concepts/alpha#overview",
            "title": "Alpha Concept",
            "section_title": "Overview",
            "score": 9,
            "citations": [
                {
                    **first["citations"][0],
                    "source_id": "source-2",
                    "source_kind": "paper",
                    "source_title": "Alpha Paper",
                    "uri": "https://example.com/alpha",
                    "concept_id": "concepts/alpha",
                    "section_id": "concepts/alpha#overview",
                }
            ],
        },
    ]
    return result


def _principal(*audiences: str) -> Principal:
    return Principal(
        subject="public-user",
        audiences=frozenset(audiences),
        claims={},
    )


def test_public_request_id_is_canonical_and_release_bound() -> None:
    first = public_request_id(
        query=" knowledge   compiler ",
        max_results=5,
        audience="public",
        release_id="release-a",
        manifest_sha256="a" * 64,
    )
    replay = public_request_id(
        query="knowledge compiler",
        max_results=5,
        audience="public",
        release_id="release-a",
        manifest_sha256="a" * 64,
    )
    changed = public_request_id(
        query="knowledge compiler",
        max_results=5,
        audience="public",
        release_id="release-b",
        manifest_sha256="b" * 64,
    )
    assert first == replay
    assert first.startswith("req_")
    assert changed != first


def test_public_response_has_only_stable_contract_fields() -> None:
    response = public_response_from_runtime(
        _runtime_result(),
        query="knowledge compiler",
        max_results=5,
        audience="public",
    )
    payload = response.model_dump()
    assert set(payload) == {
        "schema_version",
        "answer",
        "status",
        "citations",
        "source_cards",
        "concept_ids",
        "release_id",
        "request_id",
        "audience",
        "confidence",
        "not_found_reason",
    }
    assert payload["schema_version"] == PUBLIC_QUERY_SCHEMA
    assert payload["status"] == "answered"
    assert payload["answer"].endswith("[1]")
    assert payload["concept_ids"] == ["concepts/compiler"]
    citation = payload["citations"][0]
    assert citation["citation_id"].startswith("cite_")
    assert citation["source_card_id"].startswith("card_")
    assert citation["section_id"].endswith("#operations")
    assert citation["claim_ids"] == ["claim-1"]
    assert citation["locator"] == {
        "heading": "Operations",
        "page": None,
        "paragraph": None,
        "start_line": None,
        "end_line": None,
        "timecode": None,
        "anchor": None,
    }
    card = payload["source_cards"][0]
    assert card["source_card_id"] == citation["source_card_id"]
    assert card["title"] == "Compiler Specification"
    assert card["publisher"] == "Example Foundation"
    assert card["snapshot_available"] is True
    assert card["integrity_sha256"] == "b" * 64
    assert card["citation_ids"] == [citation["citation_id"]]
    assert "evaluation" not in payload
    assert "retrieval" not in payload
    assert 0 < payload["confidence"] <= 1


def test_public_search_response_shapes_lexical_results_for_scanning() -> None:
    response = public_search_response_from_runtime(
        _search_runtime_result(),
        query="agent",
        max_results=10,
        audience="public",
        sort_by="title",
        source_kind=None,
    )
    payload = response.model_dump()
    assert set(payload) == {
        "schema_version",
        "status",
        "results",
        "source_cards",
        "source_viewers",
        "concept_ids",
        "release_id",
        "request_id",
        "audience",
        "sort_by",
        "source_kind",
        "not_found_reason",
    }
    assert payload["schema_version"] == "knowledge-engine-public-search/v1"
    assert payload["status"] == "answered"
    assert [item["title"] for item in payload["results"]] == [
        "Alpha Concept",
        "Zeta Concept",
    ]
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][0]["source_kinds"] == ["paper"]
    assert payload["results"][0]["source_card_ids"]
    assert payload["source_cards"][0]["source_kind"] == "paper"
    viewer = payload["source_viewers"][0]
    assert viewer["source_card"]["source_card_id"] == payload["source_cards"][0][
        "source_card_id"
    ]
    assert viewer["citations"][0]["locator"]["heading"] == "Operations"
    assert viewer["summary"] == {
        "citation_count": 1,
        "concept_count": 1,
        "claim_count": 1,
        "has_snapshot": True,
        "integrity_available": True,
        "retrieval_authority": "lexical",
        "semantic_serving_enabled": False,
        "raw_evidence_exposed": False,
    }
    assert payload["request_id"].startswith("search_")
    assert "retrieval" not in payload
    assert "evaluation" not in payload
    assert "query_vector" not in response.model_dump_json()


def test_public_search_source_kind_filter_has_empty_state() -> None:
    response = public_search_response_from_runtime(
        _search_runtime_result(),
        query="agent",
        max_results=10,
        audience="public",
        source_kind="video",
    )

    assert response.status == "not_found"
    assert response.results == []
    assert response.source_cards == []
    assert response.source_viewers == []
    assert response.not_found_reason == "no_match"


def test_public_not_found_is_explicit() -> None:
    response = public_response_from_runtime(
        _runtime_result(answered=False),
        query="missing topic",
        max_results=5,
        audience="public",
    )
    assert response.status == "not_found"
    assert response.answer is None
    assert response.citations == []
    assert response.source_cards == []
    assert response.concept_ids == []
    assert response.confidence == 0
    assert response.not_found_reason == "no_match"


def test_ask_endpoint_uses_requested_audience_without_internal_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubRuntime:
        def query(self, query: str, audiences: set[str], *, limit: int) -> dict:
            assert query == "knowledge compiler"
            assert audiences == {"public"}
            assert limit == 3
            return _runtime_result()

    monkeypatch.setattr(api, "get_runtime", lambda: StubRuntime())
    response = api.ask(
        PublicAskRequest(
            query="knowledge compiler",
            max_results=3,
            audience="public",
        ),
        _principal("public", "internal"),
    )
    assert response.audience == "public"
    assert response.status == "answered"
    assert response.source_cards[0].display_host == "example.com"


def test_search_endpoint_uses_requested_audience_without_internal_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubRuntime:
        def query(self, query: str, audiences: set[str], *, limit: int) -> dict:
            assert query == "knowledge compiler"
            assert audiences == {"public"}
            assert limit == 2
            return _search_runtime_result()

    monkeypatch.setattr(api, "get_runtime", lambda: StubRuntime())
    response = api.search(
        PublicSearchRequest(
            query="knowledge compiler",
            max_results=2,
            audience="public",
            source_kind="paper",
        ),
        _principal("public", "internal"),
    )

    assert response.audience == "public"
    assert response.status == "answered"
    assert response.results[0].concept_id == "concepts/alpha"


def test_ask_endpoint_rejects_audience_escalation() -> None:
    with pytest.raises(HTTPException) as exc:
        api.ask(
            PublicAskRequest(query="secret", audience="internal"),
            _principal("public"),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["schema_version"].endswith("/error")
    assert exc.value.detail["code"] == "PUBLIC-QUERY-403"


def test_health_contract_remains_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        channel="production",
        ensure_loaded=lambda: SimpleNamespace(
            release_id="release-current",
            manifest_sha256="c" * 64,
        ),
    )
    monkeypatch.setattr(api, "get_runtime", lambda: runtime)
    assert api.health() == {
        "status": "healthy",
        "release_id": "release-current",
        "manifest_sha256": "c" * 64,
        "channel": "production",
    }
