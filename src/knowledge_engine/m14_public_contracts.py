from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

PUBLIC_QUERY_SCHEMA = "knowledge-engine-public-query/v1"
AskStatus = Literal["answered", "not_found", "degraded"]
Audience = Literal["public", "internal", "confidential", "restricted"]
NotFoundReason = Literal["no_match", "no_authorized_match", "release_unavailable"]


class PublicAskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    max_results: int = Field(default=5, ge=1, le=20)
    audience: Audience = "public"


class PublicCitation(BaseModel):
    source_id: str
    uri: str
    retrieved_at: str
    concept_id: str
    section_id: str


class PublicAskResponse(BaseModel):
    schema_version: str = PUBLIC_QUERY_SCHEMA
    answer: str | None
    status: AskStatus
    citations: list[PublicCitation]
    concept_ids: list[str]
    release_id: str
    request_id: str
    audience: Audience
    confidence: float = Field(ge=0.0, le=1.0)
    not_found_reason: NotFoundReason | None


class PublicErrorDetail(BaseModel):
    schema_version: str = f"{PUBLIC_QUERY_SCHEMA}/error"
    code: str
    message: str
    request_id: str | None = None


class PublicErrorResponse(BaseModel):
    detail: PublicErrorDetail


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def public_request_id(
    *,
    query: str,
    max_results: int,
    audience: str,
    release_id: str,
    manifest_sha256: str,
) -> str:
    identity = {
        "schema_version": f"{PUBLIC_QUERY_SCHEMA}/request-identity",
        "query": " ".join(query.split()),
        "max_results": max_results,
        "audience": audience,
        "release_id": release_id,
        "manifest_sha256": manifest_sha256,
    }
    digest = hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:32]
    return f"req_{digest}"


def _dedupe_citations(results: list[dict[str, Any]]) -> list[PublicCitation]:
    citations: list[PublicCitation] = []
    seen: set[tuple[str, str, str, str]] = set()
    for result in results:
        for citation in result.get("citations", []):
            identity = (
                str(citation["source_id"]),
                str(citation["uri"]),
                str(citation["concept_id"]),
                str(citation["section_id"]),
            )
            if identity in seen:
                continue
            seen.add(identity)
            citations.append(
                PublicCitation(
                    source_id=identity[0],
                    uri=identity[1],
                    retrieved_at=str(citation["retrieved_at"]),
                    concept_id=identity[2],
                    section_id=identity[3],
                )
            )
    return citations


def _compose_answer(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results[:3]:
        title = str(result.get("title") or result["concept_id"])
        section_title = str(result.get("section_title") or title)
        excerpt = " ".join(str(result.get("excerpt") or "").split())
        heading = title if section_title == title else f"{title} · {section_title}"
        parts.append(f"{heading}: {excerpt}" if excerpt else heading)
    return "\n\n".join(parts)


def _confidence(results: list[dict[str, Any]], citation_count: int) -> float:
    if not results:
        return 0.0
    top_score = max(float(result.get("score", 0)) for result in results)
    score_component = min(top_score / 20.0, 0.55)
    coverage_component = min(len(results) / 5.0, 1.0) * 0.20
    citation_component = 0.25 if citation_count else 0.0
    return round(min(1.0, score_component + coverage_component + citation_component), 4)


def public_response_from_runtime(
    runtime_result: dict[str, Any],
    *,
    query: str,
    max_results: int,
    audience: Audience,
) -> PublicAskResponse:
    release = runtime_result.get("release")
    if not isinstance(release, dict):
        raise ValueError("runtime result is missing release identity")
    release_id = release.get("release_id")
    manifest_sha256 = release.get("manifest_sha256")
    if not isinstance(release_id, str) or not isinstance(manifest_sha256, str):
        raise ValueError("runtime release identity is invalid")
    results = runtime_result.get("results")
    if not isinstance(results, list):
        raise ValueError("runtime results must be a list")
    citations = _dedupe_citations(results)
    status_value = runtime_result.get("status")
    not_found_reason = runtime_result.get("not_found_reason")
    if status_value == "not_found":
        status: AskStatus = "not_found"
        answer = None
        confidence = 0.0
    else:
        answer = _compose_answer(results)
        status = "answered" if citations else "degraded"
        confidence = _confidence(results, len(citations))
        not_found_reason = None
    concept_ids = sorted(
        {
            str(result["concept_id"])
            for result in results
            if isinstance(result, dict) and isinstance(result.get("concept_id"), str)
        }
    )
    request_id = public_request_id(
        query=query,
        max_results=max_results,
        audience=audience,
        release_id=release_id,
        manifest_sha256=manifest_sha256,
    )
    return PublicAskResponse(
        answer=answer,
        status=status,
        citations=citations,
        concept_ids=concept_ids,
        release_id=release_id,
        request_id=request_id,
        audience=audience,
        confidence=confidence,
        not_found_reason=not_found_reason,
    )
