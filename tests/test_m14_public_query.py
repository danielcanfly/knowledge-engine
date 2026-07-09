from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from knowledge_engine import api
from knowledge_engine.auth import Principal
from knowledge_engine.m14_public_contracts import (
    PUBLIC_QUERY_SCHEMA,
    PublicAskRequest,
    public_request_id,
    public_response_from_runtime,
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
                        "uri": "https://example.com/compiler",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                        "concept_id": "concepts/compiler",
                        "section_id": "concepts/compiler#operations",
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
        "concept_ids",
        "release_id",
        "request_id",
        "audience",
        "confidence",
        "not_found_reason",
    }
    assert payload["schema_version"] == PUBLIC_QUERY_SCHEMA
    assert payload["status"] == "answered"
    assert payload["concept_ids"] == ["concepts/compiler"]
    assert payload["citations"][0]["section_id"].endswith("#operations")
    assert "evaluation" not in payload
    assert "retrieval" not in payload
    assert 0 < payload["confidence"] <= 1


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
