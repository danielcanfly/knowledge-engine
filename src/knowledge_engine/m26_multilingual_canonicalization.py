from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

CANONICALIZATION_SCHEMA_VERSION = "m26-multilingual-canonicalization/v1"
FidelityState = Literal["preserved", "not_applicable", "failed"]
VALID_FIDELITY_STATES = frozenset({"preserved", "not_applicable", "failed"})
REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS = (
    "intent",
    "identity_terms",
    "technical_identifiers",
    "numbers_and_units",
    "comparison_direction",
    "relationship_direction",
    "negation",
    "modality_qualifiers",
    "multi_part_synthesis",
    "graph_entity_references",
)


class CanonicalizationProvider(Protocol):
    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult: ...


@dataclass(frozen=True)
class SemanticFidelityContract:
    intent: FidelityState
    identity_terms: FidelityState
    technical_identifiers: FidelityState
    numbers_and_units: FidelityState
    comparison_direction: FidelityState
    relationship_direction: FidelityState
    negation: FidelityState
    modality_qualifiers: FidelityState
    multi_part_synthesis: FidelityState
    graph_entity_references: FidelityState

    def as_mapping(self) -> dict[str, str]:
        return {
            "intent": self.intent,
            "identity_terms": self.identity_terms,
            "technical_identifiers": self.technical_identifiers,
            "numbers_and_units": self.numbers_and_units,
            "comparison_direction": self.comparison_direction,
            "relationship_direction": self.relationship_direction,
            "negation": self.negation,
            "modality_qualifiers": self.modality_qualifiers,
            "multi_part_synthesis": self.multi_part_synthesis,
            "graph_entity_references": self.graph_entity_references,
        }


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
    semantic_fidelity: SemanticFidelityContract | Mapping[str, object] | None = None
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
    fidelity_failure = validate_semantic_fidelity(result.semantic_fidelity)
    if fidelity_failure is not None:
        return fidelity_failure
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
        semantic_fidelity=result.semantic_fidelity,
        telemetry={
            **dict(result.telemetry),
            "schema_version": CANONICALIZATION_SCHEMA_VERSION,
            "status": "ok",
            "preservation_marker_count": len(request.preservation_markers),
        },
    )


def validate_semantic_fidelity(
    fidelity: SemanticFidelityContract | Mapping[str, object] | None,
) -> CanonicalizationResult | None:
    if fidelity is None:
        return explicit_failure(
            "CANONICALIZATION_FIDELITY_MISSING",
            "canonicalization result omitted semantic fidelity contract",
        )
    if isinstance(fidelity, SemanticFidelityContract):
        mapping = fidelity.as_mapping()
    elif isinstance(fidelity, Mapping):
        mapping = dict(fidelity)
    else:
        return explicit_failure(
            "CANONICALIZATION_FIDELITY_INVALID",
            "semantic fidelity contract must be a typed contract or mapping",
        )

    dimensions = set(REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS)
    missing = [
        dimension
        for dimension in REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS
        if dimension not in mapping
    ]
    if missing:
        return explicit_failure(
            "CANONICALIZATION_FIDELITY_MISSING",
            "semantic fidelity contract omitted required dimension",
        )
    unexpected = sorted(set(mapping) - dimensions)
    if unexpected:
        return explicit_failure(
            "CANONICALIZATION_FIDELITY_INVALID",
            "semantic fidelity contract included unknown dimension",
        )
    for dimension in REQUIRED_SEMANTIC_FIDELITY_DIMENSIONS:
        state = mapping[dimension]
        if state not in VALID_FIDELITY_STATES:
            return explicit_failure(
                "CANONICALIZATION_FIDELITY_INVALID",
                "semantic fidelity contract included malformed dimension state",
            )
        if state == "failed":
            return explicit_failure(
                "CANONICALIZATION_SEMANTIC_LOSS",
                f"semantic fidelity dimension failed: {dimension}",
            )
    return None


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
