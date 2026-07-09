from __future__ import annotations

from typing import Any

from .errors import IntegrityError
from .m14_citation_evidence import AUDIENCE_RANK, citation_evidence_for_section


def enrich_runtime_citations(
    *,
    results: list[dict[str, Any]],
    provenance: dict[str, Any],
    allowed_audiences: set[str],
) -> dict[str, int]:
    allowed = {item for item in allowed_audiences if item in AUDIENCE_RANK}
    if not allowed:
        allowed = {"public"}
    maximum_rank = max(AUDIENCE_RANK[item] for item in allowed)
    records = provenance.get("records", [])
    if not isinstance(records, list):
        raise IntegrityError("provenance records must be a list")
    by_concept: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise IntegrityError("provenance record must be an object")
        subject = record.get("subject")
        if not isinstance(subject, dict):
            raise IntegrityError("provenance record subject must be an object")
        concept_id = subject.get("concept_id")
        if not isinstance(concept_id, str) or not concept_id:
            raise IntegrityError("provenance record is missing concept_id")
        if concept_id in by_concept:
            raise IntegrityError(f"duplicate provenance concept_id: {concept_id}")
        by_concept[concept_id] = record

    filtered_source_count = 0
    claim_citation_count = 0
    concept_citation_count = 0
    for result in results:
        concept_id = result.get("concept_id")
        if not isinstance(concept_id, str) or not concept_id:
            raise IntegrityError("runtime result is missing concept_id")
        record = by_concept.get(concept_id)
        if record is None:
            result["citations"] = []
            continue
        citations, filtered = citation_evidence_for_section(
            record=record,
            document=result,
            maximum_audience_rank=maximum_rank,
        )
        result["citations"] = citations
        filtered_source_count += filtered
        claim_citation_count += sum(
            citation.get("citation_scope") == "claim" for citation in citations
        )
        concept_citation_count += sum(
            citation.get("citation_scope") == "concept" for citation in citations
        )
    return {
        "citation_source_acl_filtered_count": filtered_source_count,
        "claim_citation_candidate_count": claim_citation_count,
        "concept_citation_candidate_count": concept_citation_count,
        "citation_candidate_count": claim_citation_count + concept_citation_count,
    }
