from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .m26_multilingual_canonicalization import CanonicalizationProvider
from .m26_multilingual_language_envelope import (
    AnswerLanguage,
    LanguageEnvelope,
    build_language_envelope,
)
from .m26_multilingual_observability import build_retrieval_observability_snapshot
from .m26_multilingual_publication_adapter import (
    VerifiedRequestedLanguagePublicationResult,
    build_verified_requested_language_publication,
)
from .m26_multilingual_retrieval_adapter import (
    CandidateUnionResult,
    Retriever,
    build_candidate_union,
)
from .m26_multilingual_semantic_spine import (
    SemanticAuthorityDependencies,
    build_canonical_semantic_context,
)
from .m26_multilingual_verified_claim_spine import (
    CanonicalVerifiedClaimSpine,
    build_canonical_verified_claim_spine,
)

RuntimeStatus = Literal["completed", "partial", "abstained", "failed"]
EventSink = Callable[[Mapping[str, Any]], None]
EvidenceSelector = Callable[[CandidateUnionResult, LanguageEnvelope], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class MultilingualRuntimeResult:
    status: RuntimeStatus
    answer_text: str = ""
    requested_answer_language: str = ""
    detected_input_language: str = ""
    final_visible_language: str = ""
    safe_abstention: bool = False
    citations: tuple[Mapping[str, Any], ...] = ()
    answer_claims: tuple[Mapping[str, Any], ...] = ()
    canonical_claim_count: int = 0
    canonical_dropped_claim_count: int = 0
    visible_claim_count: int = 0
    language_dropped_claim_count: int = 0
    unsupported_accepted_claims: int = 0
    citation_locator_valid: bool = True
    material_claim_support_verified: bool = True
    reason_codes: tuple[str, ...] = ()
    failure_code: str = ""
    failure_detail: str = ""
    telemetry: Mapping[str, Any] = field(default_factory=dict)

    @property
    def terminal_event_type(self) -> str:
        if self.status == "completed":
            return "answer.completed"
        if self.status == "partial":
            return "answer.partial"
        if self.status == "abstained":
            return "answer.abstained"
        return "answer.failed"


@dataclass(frozen=True)
class MultilingualRuntimeDependencies:
    canonicalization_provider: CanonicalizationProvider | None = None
    dense_retriever: Retriever | None = None
    lexical_retriever: Retriever | None = None
    graph_retriever: Retriever | None = None
    identifier_retriever: Retriever | None = None
    evidence_selector: EvidenceSelector | None = None
    semantic_authorities: SemanticAuthorityDependencies = field(
        default_factory=SemanticAuthorityDependencies
    )
    closure_provider_client: Any = None
    closure_runner: Callable[..., tuple[Mapping[str, Any], Mapping[str, Any]]] | None = None
    endpoint_proof: Mapping[str, Any] = field(default_factory=dict)
    requested_language_realizer: Any = None
    equivalence_reviewer: Any = None


def run_track2_multilingual_request(
    *,
    question: str,
    answer_language: AnswerLanguage,
    dependencies: MultilingualRuntimeDependencies,
    event_sink: EventSink | None = None,
    trace_id: str | None = None,
) -> MultilingualRuntimeResult:
    try:
        envelope = build_language_envelope(
            question,
            answer_language=answer_language,
            canonicalization_provider=dependencies.canonicalization_provider,
        )
    except ValueError as exc:
        return _failed("INVALID_ANSWER_LANGUAGE", str(exc))
    _emit(
        event_sink,
        "stage.completed",
        stage="language_envelope",
        status=envelope.canonicalization_status,
        detected_input_language=envelope.detected_input_language,
        requested_answer_language=envelope.requested_answer_language,
    )
    if not envelope.ok:
        return _abstained_or_failed_from_code(
            failure_code=envelope.failure_code or "LANGUAGE_ENVELOPE_FAILED",
            failure_detail=envelope.failure_detail,
            envelope=envelope,
        )

    union = _candidate_union(envelope, dependencies)
    if union is None:
        return _failed(
            "MULTILINGUAL_RETRIEVAL_DEPENDENCY_MISSING",
            "Track 2 retrieval dependencies are unavailable",
            envelope=envelope,
        )
    _emit(
        event_sink,
        "stage.completed",
        stage="retrieval",
        status=union.status,
        candidate_union_count=len(union.candidates),
    )
    if not union.ok:
        return _failed(union.failure_code, union.failure_detail, envelope=envelope)

    selected = _select_evidence(union, envelope, dependencies)
    retrieval_observability = build_retrieval_observability_snapshot(
        union,
        selected_evidence_ids=tuple(str(item.get("evidence_id", "")) for item in selected),
    )
    _emit(
        event_sink,
        "stage.completed",
        stage="evidence_selection",
        status="ok" if selected else "abstained",
        selected_evidence_count=len(selected),
    )
    if not selected:
        return _abstained(
            "NO_SELECTED_AUTHORIZED_EVIDENCE",
            "no authorized evidence survived frozen selection boundary",
            envelope=envelope,
            telemetry={"retrieval": retrieval_observability.as_dict()},
        )

    context_result = build_canonical_semantic_context(
        envelope,
        authorities=dependencies.semantic_authorities,
    )
    _emit(
        event_sink,
        "stage.completed",
        stage="semantic_spine",
        status=context_result.status,
    )
    if not context_result.ok or context_result.context is None:
        return _failed(
            context_result.failure_code,
            context_result.failure_detail,
            envelope=envelope,
            telemetry={"retrieval": retrieval_observability.as_dict()},
        )

    if dependencies.closure_provider_client is None or dependencies.closure_runner is None:
        return _failed(
            "CANONICAL_CLOSURE_DEPENDENCY_MISSING",
            "Track 2 closure authority dependencies are unavailable",
            envelope=envelope,
            telemetry={"retrieval": retrieval_observability.as_dict()},
        )
    spine_result = build_canonical_verified_claim_spine(
        context=context_result.context,
        selected_authorized_evidence=selected,
        provider_client=dependencies.closure_provider_client,
        endpoint_proof=dependencies.endpoint_proof,
        trace_id=trace_id or f"track2-{uuid.uuid4().hex}",
        closure_runner=dependencies.closure_runner,
    )
    _emit(
        event_sink,
        "stage.completed",
        stage="canonical_verified_claim_spine",
        status=spine_result.status,
    )
    if not spine_result.ok or spine_result.spine is None:
        return _failed(
            spine_result.failure_code,
            spine_result.failure_detail,
            envelope=envelope,
            telemetry={"retrieval": retrieval_observability.as_dict()},
        )

    publication_result = build_verified_requested_language_publication(
        canonical_spine=spine_result.spine,
        realizer=dependencies.requested_language_realizer,
        equivalence_reviewer=dependencies.equivalence_reviewer,
    )
    _emit(
        event_sink,
        "stage.completed",
        stage="requested_language_publication",
        status=publication_result.status,
    )
    return _publication_to_runtime_result(
        envelope=envelope,
        spine=spine_result.spine,
        publication_result=publication_result,
        retrieval_observability=retrieval_observability.as_dict(),
    )


def _candidate_union(
    envelope: LanguageEnvelope,
    dependencies: MultilingualRuntimeDependencies,
) -> CandidateUnionResult | None:
    if (
        dependencies.dense_retriever is None
        or dependencies.lexical_retriever is None
        or dependencies.graph_retriever is None
    ):
        return None
    return build_candidate_union(
        envelope,
        dense_retriever=dependencies.dense_retriever,
        lexical_retriever=dependencies.lexical_retriever,
        graph_retriever=dependencies.graph_retriever,
        identifier_retriever=dependencies.identifier_retriever,
    )


def _select_evidence(
    union: CandidateUnionResult,
    envelope: LanguageEnvelope,
    dependencies: MultilingualRuntimeDependencies,
) -> tuple[Mapping[str, Any], ...]:
    if dependencies.evidence_selector is None:
        return ()
    selected = dependencies.evidence_selector(union, envelope)
    return tuple(dict(item) for item in selected if isinstance(item, Mapping))


def _publication_to_runtime_result(
    *,
    envelope: LanguageEnvelope,
    spine: CanonicalVerifiedClaimSpine,
    publication_result: VerifiedRequestedLanguagePublicationResult,
    retrieval_observability: Mapping[str, Any],
) -> MultilingualRuntimeResult:
    if publication_result.publication is None:
        return _failed(
            publication_result.failure_code,
            publication_result.failure_detail,
            envelope=envelope,
            spine=spine,
            telemetry={"retrieval": dict(retrieval_observability)},
        )
    publication = publication_result.publication
    status: RuntimeStatus
    if publication.status == "verified_full":
        status = "completed"
    elif publication.status == "verified_partial":
        status = "partial"
    elif publication.status == "abstained":
        status = "abstained"
    else:
        status = "failed"
    visible_claims = tuple(
        {
            "claim_id": claim.canonical_claim_id,
            "surface_text": claim.visible_text,
            "citation_ids": list(claim.citation_ids),
            "publication_eligible": claim.publication_eligible,
            "marker_preservation_status": claim.marker_preservation_status,
        }
        for claim in publication.visible_claims
    )
    visible_citations = tuple(
        citation for claim in publication.visible_claims for citation in claim.citations
    )
    return MultilingualRuntimeResult(
        status=status,
        answer_text=publication.visible_answer_text if status in {"completed", "partial"} else "",
        requested_answer_language=publication.requested_answer_language,
        detected_input_language=envelope.detected_input_language,
        final_visible_language=publication.requested_answer_language,
        safe_abstention=status == "abstained",
        citations=visible_citations,
        answer_claims=visible_claims,
        canonical_claim_count=publication.canonical_claim_count,
        canonical_dropped_claim_count=len(publication.canonical_dropped_claim_ids),
        visible_claim_count=publication.visible_claim_count,
        language_dropped_claim_count=len(publication.language_dropped_claim_ids),
        unsupported_accepted_claims=publication.unsupported_accepted_claims,
        citation_locator_valid=publication.citation_locator_valid,
        material_claim_support_verified=publication.material_claim_support_verified,
        reason_codes=tuple(publication.reason_codes),
        telemetry={
            "language_envelope": dict(envelope.telemetry),
            "semantic_question_source": spine.telemetry.get("semantic_question_source", ""),
            "intent_class": spine.intent_class,
            "canonical_claim_count": publication.canonical_claim_count,
            "canonical_dropped_claim_count": len(publication.canonical_dropped_claim_ids),
            "language_realized_claim_count": publication.visible_claim_count
            + len(publication.language_dropped_claim_ids),
            "language_equivalence_pass_count": publication.visible_claim_count,
            "language_dropped_claim_count": len(publication.language_dropped_claim_ids),
            "final_visible_language": publication.requested_answer_language,
            "retrieval": dict(retrieval_observability),
            "publication": dict(publication.telemetry),
        },
    )


def _failed(
    code: str,
    detail: str,
    *,
    envelope: LanguageEnvelope | None = None,
    spine: CanonicalVerifiedClaimSpine | None = None,
    telemetry: Mapping[str, Any] | None = None,
) -> MultilingualRuntimeResult:
    return MultilingualRuntimeResult(
        status="failed",
        requested_answer_language=(
            envelope.requested_answer_language if envelope is not None else ""
        ),
        detected_input_language=envelope.detected_input_language if envelope is not None else "",
        safe_abstention=True,
        canonical_claim_count=len(spine.canonical_claims) if spine is not None else 0,
        canonical_dropped_claim_count=spine.dropped_claim_count if spine is not None else 0,
        unsupported_accepted_claims=(
            spine.unsupported_accepted_claims if spine is not None else 0
        ),
        citation_locator_valid=spine.citation_locator_valid if spine is not None else True,
        material_claim_support_verified=(
            spine.material_claim_support_verified if spine is not None else True
        ),
        failure_code=code or "TRACK2_MULTILINGUAL_RUNTIME_FAILED",
        failure_detail=detail,
        telemetry=dict(telemetry or {}),
    )


def _abstained_or_failed_from_code(
    *,
    failure_code: str,
    failure_detail: str,
    envelope: LanguageEnvelope,
) -> MultilingualRuntimeResult:
    if failure_code == "CANONICALIZATION_PROVIDER_REQUIRED":
        return _failed(failure_code, failure_detail, envelope=envelope)
    return _abstained(failure_code, failure_detail, envelope=envelope)


def _abstained(
    code: str,
    detail: str,
    *,
    envelope: LanguageEnvelope,
    telemetry: Mapping[str, Any] | None = None,
) -> MultilingualRuntimeResult:
    return MultilingualRuntimeResult(
        status="abstained",
        requested_answer_language=envelope.requested_answer_language,
        detected_input_language=envelope.detected_input_language,
        final_visible_language=envelope.requested_answer_language,
        safe_abstention=True,
        reason_codes=(code,),
        failure_code=code,
        failure_detail=detail,
        telemetry=dict(telemetry or {}),
    )


def _emit(event_sink: EventSink | None, event_type: str, **fields: Any) -> None:
    if event_sink is None:
        return
    event_sink({"type": event_type, **fields})
