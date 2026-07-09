from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m14_citation_runtime import enrich_runtime_citations
from knowledge_engine.runtime import Runtime


def _result(*, audience: str = "public") -> dict:
    return {
        "concept_id": "concepts/example",
        "section_id": "concepts/example#rule",
        "title": "Example",
        "section_title": "Rule",
        "description": "Example rule",
        "excerpt": "The rule is governed.",
        "audience": audience,
        "score": 10,
        "citations": [],
    }


def _record(*, source_audience: str | None = "public") -> dict:
    source = {
        "source_id": "source-1",
        "uri": "https://example.com/spec",
        "kind": "web",
        "title": "Example Specification",
        "publisher": "Example Foundation",
        "content_sha256": "a" * 64,
        "retrieved_at": "2026-07-10T00:00:00Z",
        "snapshot_key": "sources/source-1/raw.md",
    }
    if source_audience is not None:
        source["audience"] = source_audience
    return {
        "subject": {"concept_id": "concepts/example"},
        "sources": [source],
        "claims": [
            {
                "claim_id": "claim-rule",
                "selector": {"heading": "Rule"},
                "derivation_type": "synthesized",
                "confidence": 0.97,
                "review_status": "human_approved",
                "evidence": [
                    {
                        "source_ref": "source-1",
                        "support": "direct",
                        "locator": {"heading": "Specification", "page": 4},
                    }
                ],
            }
        ],
        "access": {
            "source_audiences": [source_audience or "public"],
            "effective_audience": "public",
            "declassified": False,
        },
    }


def test_runtime_maps_selected_section_to_claim_evidence(
    tmp_path: Path,
    built_store,
) -> None:
    store, _, _ = built_store
    runtime = Runtime(store, tmp_path / "cache", "staging")
    result = runtime.query("channel pointer integrity", {"internal"})
    citation = result["results"][0]["citations"][0]
    assert result["results"][0]["section_id"].endswith("#operational-rule")
    assert citation["citation_scope"] == "claim"
    assert citation["claim_id"] == "claim_compiler_release_rule"
    assert citation["support"] == "context"
    assert citation["locator"] == {"heading": "Specification"}
    assert citation["snapshot_available"] is True
    assert "snapshot_key" not in citation
    assert result["retrieval"]["claim_citation_candidate_count"] == 1
    assert result["retrieval"]["concept_citation_candidate_count"] == 0


def test_missing_matching_claim_uses_concept_level_compatibility() -> None:
    result = _result()
    record = _record()
    record["claims"] = []
    metrics = enrich_runtime_citations(
        results=[result],
        provenance={"records": [record]},
        allowed_audiences={"public"},
    )
    citation = result["citations"][0]
    assert citation["citation_scope"] == "concept"
    assert citation["claim_id"] is None
    assert citation["support"] == "context"
    assert citation["locator"] is None
    assert metrics["concept_citation_candidate_count"] == 1


def test_source_audience_is_rechecked_after_concept_authorization() -> None:
    result = _result(audience="public")
    metrics = enrich_runtime_citations(
        results=[result],
        provenance={"records": [_record(source_audience="internal")]},
        allowed_audiences={"public"},
    )
    assert result["citations"] == []
    assert metrics["citation_source_acl_filtered_count"] == 1
    assert metrics["citation_candidate_count"] == 0


def test_declassified_record_without_source_audience_fails_closed() -> None:
    result = _result(audience="public")
    record = _record(source_audience=None)
    record["access"] = {
        "source_audiences": [],
        "effective_audience": "public",
        "declassified": True,
    }
    metrics = enrich_runtime_citations(
        results=[result],
        provenance={"records": [record]},
        allowed_audiences={"public"},
    )
    assert result["citations"] == []
    assert metrics["citation_source_acl_filtered_count"] == 1


def test_claim_with_unknown_source_reference_fails_closed() -> None:
    result = _result()
    record = _record()
    record["claims"][0]["evidence"][0]["source_ref"] = "missing-source"
    with pytest.raises(IntegrityError, match="unknown source"):
        enrich_runtime_citations(
            results=[result],
            provenance={"records": [record]},
            allowed_audiences={"public"},
        )


def test_duplicate_provenance_records_fail_closed() -> None:
    result = _result()
    record = _record()
    with pytest.raises(IntegrityError, match="duplicate provenance concept_id"):
        enrich_runtime_citations(
            results=[result],
            provenance={"records": [record, record]},
            allowed_audiences={"public"},
        )
