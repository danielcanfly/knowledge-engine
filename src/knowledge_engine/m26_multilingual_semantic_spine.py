from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from . import m26_pa7_arbitrary_query_runtime as legacy
from .m26_aq_semantic_contract import (
    CONTRACT_SCHEMA_VERSION,
    derive_semantic_requirements,
    semantic_contract_fingerprint,
)
from .m26_multilingual_language_envelope import LanguageEnvelope

SemanticQuestionSource = Literal["original", "canonical_en"]
SpineStatus = Literal["ok", "failed"]


@dataclass(frozen=True)
class SemanticRequirementSummary:
    requirement_id: str
    exact_phrase: str = ""


@dataclass(frozen=True)
class CanonicalSemanticContext:
    original_question: str
    semantic_question_en: str
    closure_question_en: str
    requested_answer_language: str
    detected_input_language: str
    semantic_question_source: SemanticQuestionSource
    intent_class: str
    semantic_requirements: tuple[Any, ...]
    semantic_requirement_summaries: tuple[SemanticRequirementSummary, ...]
    semantic_requirement_ids: tuple[str, ...]
    question_contract: Mapping[str, Any]
    question_contract_facet_ids: tuple[str, ...]
    semantic_contract_schema: str
    semantic_contract_fingerprint: str
    canonicalization_status_reference: str
    telemetry: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalSemanticSpineResult:
    status: SpineStatus
    context: CanonicalSemanticContext | None = None
    failure_code: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.context is not None


@dataclass(frozen=True)
class SemanticAuthorityDependencies:
    intent_classifier: Callable[[str], str] | None = legacy._intent_class
    question_contract_builder: Callable[..., Mapping[str, Any]] | None = (
        legacy._question_contract
    )
    requirement_deriver: Callable[[str, str], Sequence[Any]] | None = (
        derive_semantic_requirements
    )
    contract_fingerprint_provider: Callable[[], str] | None = (
        semantic_contract_fingerprint
    )
    contract_schema_version: str = CONTRACT_SCHEMA_VERSION


DEFAULT_SEMANTIC_AUTHORITIES = SemanticAuthorityDependencies()


def build_canonical_semantic_context(
    envelope: LanguageEnvelope,
    *,
    authorities: SemanticAuthorityDependencies = DEFAULT_SEMANTIC_AUTHORITIES,
) -> CanonicalSemanticSpineResult:
    question_result = _semantic_question(envelope)
    if isinstance(question_result, CanonicalSemanticSpineResult):
        return question_result
    semantic_question, source = question_result

    dependency_failure = _validate_authorities(authorities)
    if dependency_failure is not None:
        return dependency_failure

    try:
        intent_class = authorities.intent_classifier(semantic_question)  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("SEMANTIC_AUTHORITY_EXCEPTION", str(exc))
    if not isinstance(intent_class, str) or not intent_class.strip():
        return _failure(
            "SEMANTIC_INTENT_INVALID",
            "semantic intent authority returned an invalid intent class",
        )
    intent_class = intent_class.strip()

    try:
        requirements = authorities.requirement_deriver(  # type: ignore[union-attr]
            semantic_question,
            intent_class,
        )
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("SEMANTIC_AUTHORITY_EXCEPTION", str(exc))
    requirement_result = _preserve_and_summarize_requirements(requirements)
    if isinstance(requirement_result, CanonicalSemanticSpineResult):
        return requirement_result
    authoritative_requirements, requirement_summaries = requirement_result

    try:
        question_contract = authorities.question_contract_builder(  # type: ignore[union-attr]
            question=semantic_question,
            intent_class=intent_class,
        )
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("SEMANTIC_AUTHORITY_EXCEPTION", str(exc))
    contract_result = _validate_question_contract(question_contract)
    if isinstance(contract_result, CanonicalSemanticSpineResult):
        return contract_result
    facet_ids = contract_result

    try:
        contract_fingerprint = authorities.contract_fingerprint_provider()  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover - exact exception type belongs to authority
        return _failure("SEMANTIC_AUTHORITY_EXCEPTION", str(exc))
    if not isinstance(contract_fingerprint, str) or not contract_fingerprint.strip():
        return _failure(
            "SEMANTIC_CONTRACT_FINGERPRINT_INVALID",
            "semantic contract fingerprint provider returned an invalid fingerprint",
        )

    requirement_ids = tuple(item.requirement_id for item in requirement_summaries)
    context = CanonicalSemanticContext(
        original_question=envelope.original_question,
        semantic_question_en=semantic_question,
        closure_question_en=semantic_question,
        requested_answer_language=envelope.requested_answer_language,
        detected_input_language=envelope.detected_input_language,
        semantic_question_source=source,
        intent_class=intent_class,
        semantic_requirements=authoritative_requirements,
        semantic_requirement_summaries=requirement_summaries,
        semantic_requirement_ids=requirement_ids,
        question_contract=question_contract,
        question_contract_facet_ids=facet_ids,
        semantic_contract_schema=authorities.contract_schema_version,
        semantic_contract_fingerprint=contract_fingerprint,
        canonicalization_status_reference=envelope.canonicalization_status,
        telemetry={
            "semantic_question_source": source,
            "intent_class": intent_class,
            "semantic_requirement_ids": requirement_ids,
            "semantic_contract_schema": authorities.contract_schema_version,
            "semantic_contract_fingerprint": contract_fingerprint,
            "canonical_question_used": source == "canonical_en",
            "original_question_retained": True,
        },
    )
    return CanonicalSemanticSpineResult(status="ok", context=context)


def _semantic_question(
    envelope: LanguageEnvelope,
) -> tuple[str, SemanticQuestionSource] | CanonicalSemanticSpineResult:
    if envelope.detected_input_language == "en":
        if not envelope.ok:
            return _failure(
                "LANGUAGE_ENVELOPE_INVALID",
                "English semantic spine requires a successful language envelope",
            )
        return envelope.original_question, "original"
    if not envelope.canonical_question_en:
        return _failure(
            "CANONICAL_ENGLISH_SEMANTIC_QUESTION_REQUIRED",
            "non-English semantic spine requires canonical English",
        )
    if not envelope.ok:
        return _failure(
            "LANGUAGE_ENVELOPE_INVALID",
            "non-English semantic spine requires a successful language envelope",
        )
    return envelope.canonical_question_en, "canonical_en"


def _validate_authorities(
    authorities: SemanticAuthorityDependencies,
) -> CanonicalSemanticSpineResult | None:
    missing = []
    if not callable(authorities.intent_classifier):
        missing.append("intent_classifier")
    if not callable(authorities.question_contract_builder):
        missing.append("question_contract_builder")
    if not callable(authorities.requirement_deriver):
        missing.append("requirement_deriver")
    if not callable(authorities.contract_fingerprint_provider):
        missing.append("contract_fingerprint_provider")
    if missing:
        return _failure(
            "SEMANTIC_AUTHORITY_UNAVAILABLE",
            "semantic authority dependency unavailable: " + ",".join(missing),
        )
    if not authorities.contract_schema_version:
        return _failure(
            "SEMANTIC_CONTRACT_SCHEMA_INVALID",
            "semantic contract schema version is empty",
        )
    return None


def _preserve_and_summarize_requirements(
    requirements: Sequence[Any],
) -> (
    tuple[tuple[Any, ...], tuple[SemanticRequirementSummary, ...]]
    | CanonicalSemanticSpineResult
):
    if isinstance(requirements, (str, bytes)) or not isinstance(requirements, Sequence):
        return _failure(
            "SEMANTIC_REQUIREMENTS_INVALID",
            "semantic requirement authority returned malformed requirements",
        )
    authoritative_requirements = tuple(requirements)
    summaries: list[SemanticRequirementSummary] = []
    for requirement in authoritative_requirements:
        requirement_id = getattr(requirement, "requirement_id", None)
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            return _failure(
                "SEMANTIC_REQUIREMENTS_INVALID",
                "semantic requirement omitted a non-empty requirement_id",
            )
        summaries.append(
            SemanticRequirementSummary(
                requirement_id=requirement_id.strip(),
                exact_phrase=str(getattr(requirement, "exact_phrase", "")),
            )
        )
    return authoritative_requirements, tuple(summaries)


def _validate_question_contract(
    question_contract: Mapping[str, Any],
) -> tuple[str, ...] | CanonicalSemanticSpineResult:
    if not isinstance(question_contract, Mapping):
        return _failure(
            "SEMANTIC_QUESTION_CONTRACT_INVALID",
            "question contract authority returned malformed contract",
        )
    facets = question_contract.get("required_facets")
    if isinstance(facets, (str, bytes)) or not isinstance(facets, Sequence):
        return _failure(
            "SEMANTIC_QUESTION_CONTRACT_INVALID",
            "question contract omitted required_facets sequence",
        )
    facet_ids: list[str] = []
    for facet in facets:
        if not isinstance(facet, Mapping):
            return _failure(
                "SEMANTIC_QUESTION_CONTRACT_INVALID",
                "question contract facet is malformed",
            )
        facet_id = facet.get("facet_id")
        if not isinstance(facet_id, str) or not facet_id.strip():
            return _failure(
                "SEMANTIC_QUESTION_CONTRACT_INVALID",
                "question contract facet omitted a non-empty facet_id",
            )
        facet_ids.append(facet_id.strip())
    return tuple(facet_ids)


def _failure(code: str, detail: str) -> CanonicalSemanticSpineResult:
    return CanonicalSemanticSpineResult(
        status="failed",
        failure_code=code,
        failure_detail=detail,
    )
