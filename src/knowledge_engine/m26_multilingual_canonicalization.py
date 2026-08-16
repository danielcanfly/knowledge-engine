from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

CANONICALIZATION_SCHEMA_VERSION = "m26-multilingual-canonicalization/v1"


class CanonicalizationProvider(Protocol):
    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult: ...


@dataclass(frozen=True)
class CanonicalizationRequest:
    original_question: str
    detected_input_language: str
    requested_answer_language: str
    preservation_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalizationResult:
    canonical_question_en: str
    status: str
    telemetry: Mapping[str, object] = field(default_factory=dict)
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok" and bool(self.canonical_question_en.strip())


def explicit_failure(code: str, detail: str) -> CanonicalizationResult:
    return CanonicalizationResult(
        canonical_question_en="",
        status="failed",
        failure_code=code,
        failure_detail=detail,
        telemetry={
            "schema_version": CANONICALIZATION_SCHEMA_VERSION,
            "status": "failed",
            "failure_code": code,
        },
    )


def bounded_canonicalization_request(
    *,
    original_question: str,
    detected_input_language: str,
    requested_answer_language: str,
) -> CanonicalizationRequest:
    return CanonicalizationRequest(
        original_question=original_question,
        detected_input_language=detected_input_language,
        requested_answer_language=requested_answer_language,
        preservation_markers=tuple(extract_preservation_markers(original_question)),
    )


def validate_canonicalization_result(
    *,
    request: CanonicalizationRequest,
    result: CanonicalizationResult,
) -> CanonicalizationResult:
    if not result.ok:
        return result
    canonical = " ".join(result.canonical_question_en.strip().split())
    if not canonical:
        return explicit_failure("CANONICALIZATION_EMPTY", "canonical English question is empty")
    missing = [
        marker
        for marker in request.preservation_markers
        if marker and marker.casefold() not in canonical.casefold()
    ]
    if missing:
        return explicit_failure(
            "CANONICALIZATION_MARKER_LOSS",
            "canonical English question omitted preserved markers",
        )
    return CanonicalizationResult(
        canonical_question_en=canonical,
        status="ok",
        failure_code="",
        failure_detail="",
        telemetry={
            "schema_version": CANONICALIZATION_SCHEMA_VERSION,
            "status": "ok",
            "preservation_marker_count": len(request.preservation_markers),
            **dict(result.telemetry),
        },
    )


def extract_preservation_markers(question: str) -> list[str]:
    markers: list[str] = []

    def add(value: str, *, strip_outer_punctuation: bool = True) -> None:
        candidate = value.strip(" \t\r\n")
        if strip_outer_punctuation:
            candidate = candidate.strip(".,;:!?()[]{}\"'")
        if not candidate:
            return
        if candidate.casefold() not in {item.casefold() for item in markers}:
            markers.append(candidate)

    for match in re.finditer(r"https?://[^\s<>)\]]+", question):
        add(match.group(0))
    for match in re.finditer(r"`([^`]+)`", question):
        add(match.group(1), strip_outer_punctuation=False)
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)+\b", question):
        add(match.group(0))
    for match in re.finditer(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b", question):
        add(match.group(0))
    for match in re.finditer(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b", question):
        add(match.group(0))
    for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+)\b", question):
        add(match.group(0))
    for match in re.finditer(r"\b\d+(?:\.\d+)?(?:\s?(?:ms|s|sec|seconds|MB|GB|%|x))?\b", question):
        add(match.group(0))
    return markers


def canonicalization_telemetry(
    *,
    detected_input_language: str,
    requested_answer_language: str,
    applied: bool,
    status: str,
    provider_invoked: bool,
    result: CanonicalizationResult | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": CANONICALIZATION_SCHEMA_VERSION,
        "detected_input_language": detected_input_language,
        "requested_answer_language": requested_answer_language,
        "canonicalization_applied": applied,
        "canonicalization_status": status,
        "canonicalization_provider_invoked": provider_invoked,
    }
    if result is not None and result.failure_code:
        payload["failure_code"] = result.failure_code
    return payload


def contains_any_marker(text: str, markers: Sequence[str]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers if marker)
