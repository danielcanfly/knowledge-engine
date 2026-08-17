from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_pa7_semantic_closure_runtime as semantic_closure
from .m14_retrieval import retrieve_wiki_first
from .m26_aq_semantic_contract import (
    derive_semantic_requirements,
    synthesize_and_verify,
)
from .m26_cloudflare_provider_router import (
    MINIMAX_MODEL,
    MINIMAX_PROVIDER,
    build_provider_routing_client,
)
from .m26_multilingual_canonicalization import (
    CanonicalizationRequest,
    CanonicalizationResult,
    SemanticFidelityContract,
    explicit_failure,
)
from .m26_multilingual_equivalence import (
    RequestedLanguageEquivalenceReviewRequest,
    RequestedLanguageRealizationRequest,
    parse_requested_language_equivalence_review_item,
)
from .m26_multilingual_provider_adapter import (
    LanguageProviderTelemetry,
    ProviderPurpose,
)
from .m26_multilingual_retrieval_adapter import (
    CandidateContribution,
    CandidateUnionResult,
    FusedRetrievalCandidate,
    RetrievalChannelResult,
    RetrievalHit,
    RetrievalQuery,
)
from .m26_multilingual_runtime import MultilingualRuntimeDependencies
from .m26_multilingual_semantic_spine import DEFAULT_SEMANTIC_AUTHORITIES
from .m26_pa5_v8_live import ENDPOINT, LiveGateError, prepare_minimax_http_client
from .m26_production_answer_bundle import (
    FULL_PRODUCTION_QDRANT_COLLECTION,
    ProductionAnswerBundle,
    load_production_answer_bundle,
)
from .m26_verified_answer_citation_gate import canonical_sha256

DEFAULT_STAGING_ENV_FILE = Path("/Users/huaihsuanhuang/Desktop/.env")
LANGUAGE_MODEL_MAX_TOKENS = 900
LANGUAGE_PROVIDER_CALL_CLASSES = {
    "multilingual_canonicalization": "m26_track2_multilingual_canonicalization",
    "multilingual_requested_language_realization": (
        "m26_track2_requested_language_realization"
    ),
    "multilingual_equivalence_review": "m26_track2_multilingual_equivalence_review",
}


@dataclass
class Track2StagingTrace:
    dense_channel: legacy.DenseChannel
    bundle: ProductionAnswerBundle | None = None
    endpoint_proof: dict[str, Any] = field(default_factory=dict)
    dense_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    lexical_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    graph_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    selector_projection_summary: dict[str, Any] = field(default_factory=dict)
    selector_provenance_trace: list[dict[str, Any]] = field(default_factory=list)


class SingleAttemptMiniMaxLanguageClient:
    def __init__(
        self,
        *,
        api_key: str,
        telemetry: LanguageProviderTelemetry | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise LiveGateError("MINIMAX_API_KEY missing")
        self.api_key = api_key
        self.telemetry = telemetry or LanguageProviderTelemetry()
        self.timeout = timeout
        self.max_network_attempts = 1

    def generate_json(
        self,
        *,
        purpose: ProviderPurpose,
        system: str,
        user: Mapping[str, Any],
        max_tokens: int = LANGUAGE_MODEL_MAX_TOKENS,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            body = self._post(system=system, user=user, max_tokens=max_tokens)
            text = _extract_text(body)
            parsed = _extract_json_object(text)
        except Exception as exc:
            self.telemetry.record(
                purpose=purpose,
                provider=MINIMAX_PROVIDER,
                model=MINIMAX_MODEL,
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                error_class=type(exc).__name__,
            )
            raise
        self.telemetry.record(
            purpose=purpose,
            provider=MINIMAX_PROVIDER,
            model=MINIMAX_MODEL,
            status="completed",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return parsed

    def _post(
        self,
        *,
        system: str,
        user: Mapping[str, Any],
        max_tokens: int,
    ) -> Mapping[str, Any]:
        response = prepare_minimax_http_client().post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MINIMAX_MODEL,
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": False,
                "system": system,
                "messages": [{"role": "user", "content": _canonical(user)}],
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise LiveGateError(f"provider HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LiveGateError("provider returned non-JSON") from exc
        if str(body.get("model", "")) != MINIMAX_MODEL:
            raise LiveGateError("provider model identity drift")
        return body


class LiveCanonicalizationProvider:
    def __init__(self, client: SingleAttemptMiniMaxLanguageClient) -> None:
        self.client = client

    def canonicalize(self, request: CanonicalizationRequest) -> CanonicalizationResult:
        try:
            payload = self.client.generate_json(
                purpose="multilingual_canonicalization",
                system=(
                    "Return only JSON. Canonicalize the user's non-English or mixed "
                    "question into English while preserving intent, identity terms, "
                    "technical identifiers, numbers, negation, modality, comparison "
                    "direction, relationship direction, and graph references. Do not "
                    "answer the question."
                ),
                user={
                    "schema_version": "m26-track2-canonicalization-request/v1",
                    "original_question": request.original_question,
                    "detected_input_language": request.detected_input_language,
                    "requested_answer_language": request.requested_answer_language,
                    "preservation_markers": list(request.preservation_markers),
                    "required_response": {
                        "canonical_question_en": "string",
                        "semantic_fidelity": {
                            field_name: "preserved|not_applicable|failed"
                            for field_name in _fidelity_fields()
                        },
                    },
                },
            )
        except Exception as exc:
            return explicit_failure(
                "CANONICALIZATION_PROVIDER_EXTERNAL_ERROR",
                _external_detail(exc),
            )
        canonical = _strict_nonempty_str(payload, "canonical_question_en")
        fidelity = _semantic_fidelity(payload.get("semantic_fidelity"))
        if canonical is None or fidelity is None:
            return explicit_failure(
                "CANONICALIZATION_PROVIDER_SCHEMA_INVALID",
                "canonicalization provider returned malformed structured JSON",
            )
        return CanonicalizationResult(
            canonical_question_en=canonical,
            status="ok",
            semantic_fidelity=fidelity,
            telemetry={
                "provider": MINIMAX_PROVIDER,
                "model": MINIMAX_MODEL,
                "call_class": LANGUAGE_PROVIDER_CALL_CLASSES[
                    "multilingual_canonicalization"
                ],
            },
        )


class LiveRequestedLanguageRealizer:
    def __init__(self, client: SingleAttemptMiniMaxLanguageClient) -> None:
        self.client = client

    def __call__(self, request: RequestedLanguageRealizationRequest) -> Mapping[str, Any]:
        payload = self.client.generate_json(
            purpose="multilingual_requested_language_realization",
            system=(
                "Return only JSON. Render each canonical English claim in the "
                "requested language. Preserve claim_id and technical markers. Do "
                "not add facts, citations, explanations, or new claims."
            ),
            user={
                "schema_version": "m26-track2-requested-language-realization/v1",
                "requested_answer_language": request.requested_answer_language,
                "claims": [
                    {
                        "claim_id": claim.canonical_claim_id,
                        "canonical_surface_text_en": claim.canonical_surface_text_en,
                        "preservation_markers": list(claim.preservation_markers),
                    }
                    for claim in request.claims
                ],
                "required_response": {
                    "claims": [
                        {
                            "claim_id": "same input claim_id",
                            "requested_language_text": "string",
                        }
                    ]
                },
            },
        )
        return {"claims": _strict_claim_items(payload, "requested_language_text")}


class LiveEquivalenceReviewer:
    def __init__(self, client: SingleAttemptMiniMaxLanguageClient) -> None:
        self.client = client

    def __call__(
        self,
        request: RequestedLanguageEquivalenceReviewRequest,
    ) -> Mapping[str, Any]:
        payload = self.client.generate_json(
            purpose="multilingual_equivalence_review",
            system=(
                "Return only JSON. Strictly review whether requested-language text "
                "is semantically equivalent to the canonical English claim. Use "
                "actual booleans for boolean fields. Do not coerce strings."
            ),
            user={
                "schema_version": "m26-track2-language-equivalence-review/v1",
                "requested_answer_language": request.requested_answer_language,
                "claims": [
                    {
                        "claim_id": claim.canonical_claim_id,
                        "canonical_surface_text_en": claim.canonical_surface_text_en,
                        "requested_language_text_zh_tw": (
                            claim.requested_language_text_zh_tw
                        ),
                        "marker_preservation_status": claim.marker_preservation_status,
                        "preservation_markers": list(claim.preservation_markers),
                    }
                    for claim in request.claims
                ],
                "required_response": {"reviews": [_review_schema()]},
            },
        )
        reviews = _strict_review_items(payload)
        return {"reviews": reviews}


class StagingDenseRetriever:
    def __init__(self, trace: Track2StagingTrace) -> None:
        self.trace = trace
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        try:
            result = self.trace.dense_channel.search(
                question=query.query_text,
                bundle=_trace_bundle(self.trace),
                top_k=8,
            )
        except Exception as exc:
            return RetrievalChannelResult(
                status="failed",
                failure_code="TRACK2_DENSE_EXTERNAL_ERROR",
                failure_detail=_external_detail(exc),
            )
        self.trace.dense_results[query.query_representation] = dict(result)
        return _hits_from_items(result.get("candidates"), score_field="score")


class StagingLexicalRetriever:
    def __init__(self, trace: Track2StagingTrace) -> None:
        self.trace = trace
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        result = _accepted_lexical(
            bundle=_trace_bundle(self.trace),
            query=query.query_text,
            limit=8,
        )
        self.trace.lexical_results[query.query_representation] = dict(result)
        return _hits_from_items(result.get("results"), score_field="score")


class StagingGraphRetriever:
    def __init__(self, trace: Track2StagingTrace) -> None:
        self.trace = trace
        self.calls: list[RetrievalQuery] = []

    def __call__(self, query: RetrievalQuery) -> RetrievalChannelResult:
        self.calls.append(query)
        self.trace.graph_results[query.query_representation] = {
            "status": "delegated_to_frozen_selector_graph_authority",
            "results": [],
        }
        return RetrievalChannelResult()


class FrozenEvidenceSelectorAdapter:
    def __init__(self, trace: Track2StagingTrace) -> None:
        self.trace = trace
        self.calls = 0
        self.frozen_symbol = "m26_pa7_arbitrary_query_runtime._select_evidence"

    def __call__(
        self,
        union: CandidateUnionResult,
        envelope: Any,
    ) -> tuple[Mapping[str, Any], ...]:
        self.calls += 1
        question = _semantic_question_from_envelope(envelope)
        intent_class = legacy._intent_class(question)
        trace_id = "m26t2sel_" + canonical_sha256(
            {
                "question": question,
                "mode": union.mode,
                "candidate_ids": [candidate.candidate_id for candidate in union.candidates],
            }
        )[:32]
        lexical_result = self.trace.lexical_results.get("canonical_en")
        if lexical_result is None:
            lexical_result = _accepted_lexical(
                bundle=_trace_bundle(self.trace),
                query=question,
                limit=8,
            )
            self.trace.lexical_results["canonical_en"] = lexical_result
        dense_result = _dense_result_from_union(
            union,
            dense_results=self.trace.dense_results,
        )
        self.trace.selector_projection_summary.clear()
        self.trace.selector_projection_summary.update(
            _selector_projection_summary(union=union, dense_result=dense_result)
        )
        evidence = legacy._select_evidence(
            bundle=_trace_bundle(self.trace),
            lexical_result=lexical_result,
            dense_result=dense_result,
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
        )
        requirements = derive_semantic_requirements(question, intent_class)
        strengthened, endpoint_proof = semantic_closure._strengthen_evidence(
            bundle=_trace_bundle(self.trace),
            evidence=evidence,
            lexical_result=lexical_result,
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            requirements=requirements,
        )
        self.trace.endpoint_proof.clear()
        self.trace.endpoint_proof.update(endpoint_proof)
        self.trace.selector_provenance_trace.clear()
        self.trace.selector_provenance_trace.extend(
            _selector_provenance_trace(
                selected_evidence=strengthened,
                union=union,
                dense_result=dense_result,
            )
        )
        return tuple(strengthened)


def build_track2_staging_runtime_dependencies(
    *,
    root: Path | None = None,
    gate_path: Path | None = None,
    env_file: Path | None = None,
) -> MultilingualRuntimeDependencies:
    del gate_path
    _load_env_file(env_file or _env_file_from_env())
    _normalize_r2_endpoint_for_staging()
    os.environ.setdefault("M26_PA7_DENSE_COLLECTION", FULL_PRODUCTION_QDRANT_COLLECTION)
    dense_channel = legacy.dense_channel_from_env(require_remote=True)
    trace = Track2StagingTrace(
        dense_channel=dense_channel,
        endpoint_proof={"required": False, "matched": False},
    )
    telemetry = LanguageProviderTelemetry()
    language_client = SingleAttemptMiniMaxLanguageClient(
        api_key=os.environ.get("MINIMAX_API_KEY", ""),
        telemetry=telemetry,
    )
    return MultilingualRuntimeDependencies(
        canonicalization_provider=LiveCanonicalizationProvider(language_client),
        dense_retriever=StagingDenseRetriever(trace),
        lexical_retriever=StagingLexicalRetriever(trace),
        graph_retriever=StagingGraphRetriever(trace),
        identifier_retriever=StagingLexicalRetriever(trace),
        evidence_selector=FrozenEvidenceSelectorAdapter(trace),
        semantic_authorities=DEFAULT_SEMANTIC_AUTHORITIES,
        closure_provider_client=build_provider_routing_client(
            max_provider_calls=4,
            max_cost=Decimal("0.10"),
        ),
        closure_runner=synthesize_and_verify,
        endpoint_proof=trace.endpoint_proof,
        requested_language_realizer=LiveRequestedLanguageRealizer(language_client),
        equivalence_reviewer=LiveEquivalenceReviewer(language_client),
    )


def track2_runtime_readiness(
    dependencies: MultilingualRuntimeDependencies,
) -> dict[str, Any]:
    readiness = {
        "canonicalization_ready": dependencies.canonicalization_provider is not None,
        "dense_ready": dependencies.dense_retriever is not None,
        "lexical_ready": dependencies.lexical_retriever is not None,
        "graph_ready": dependencies.graph_retriever is not None,
        "evidence_selector_ready": dependencies.evidence_selector is not None,
        "closure_ready": dependencies.closure_provider_client is not None
        and dependencies.closure_runner is not None
        and isinstance(dependencies.endpoint_proof, Mapping),
        "realizer_ready": dependencies.requested_language_realizer is not None,
        "equivalence_reviewer_ready": dependencies.equivalence_reviewer is not None,
        "semantic_authorities_ready": (
            callable(dependencies.semantic_authorities.intent_classifier)
            and callable(dependencies.semantic_authorities.question_contract_builder)
            and callable(dependencies.semantic_authorities.requirement_deriver)
            and callable(dependencies.semantic_authorities.contract_fingerprint_provider)
        ),
    }
    return {
        **readiness,
        "multilingual_runtime_ready": all(readiness.values()),
    }


def _env_file_from_env() -> Path:
    configured = os.environ.get("M26_TRACK2_STAGING_ENV_FILE", "").strip()
    return Path(configured) if configured else DEFAULT_STAGING_ENV_FILE


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        os.environ.setdefault(key, _unquote_env_value(value.strip()))


def _normalize_r2_endpoint_for_staging() -> None:
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if endpoint.endswith("r2.cloudflarestorage.com"):
        return
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if account_id:
        os.environ["R2_ENDPOINT_URL"] = (
            f"https://{account_id}.r2.cloudflarestorage.com"
        )


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _accepted_lexical(
    *,
    bundle: ProductionAnswerBundle,
    query: str,
    limit: int,
) -> dict[str, Any]:
    return retrieve_wiki_first(
        query=query,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=None,
        limit=limit,
    )


def _trace_bundle(trace: Track2StagingTrace) -> ProductionAnswerBundle:
    if trace.bundle is None:
        trace.bundle = load_production_answer_bundle()
    return trace.bundle


def _dense_result_from_union(
    union: CandidateUnionResult,
    *,
    dense_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fallback = _preferred_dense_result(dense_results)
    if not union.candidates:
        return dict(fallback or {"backend_identity": {}, "candidates": []})

    dense_identity_by_key = _dense_candidate_identity_by_key(dense_results)
    projected: list[dict[str, Any]] = []
    for candidate in union.candidates:
        dense_contributions = tuple(
            contribution
            for contribution in candidate.contributions
            if contribution.channel == "dense"
            and contribution.query_representation in {"original", "canonical_en"}
        )
        if not dense_contributions:
            continue
        item = {
            "channel": "dense",
            "section_id": candidate.candidate_id,
            "score": round(
                sum(contribution.rank_fusion_score for contribution in dense_contributions),
                6,
            ),
            "track2_dense_projection": {
                "projection_authority": "dense_contributions_only",
                "source_representations": sorted(
                    {
                        contribution.query_representation
                        for contribution in dense_contributions
                    }
                ),
                "dense_ranks": [
                    {
                        "query_representation": contribution.query_representation,
                        "rank": contribution.rank,
                        "raw_score_if_available": contribution.raw_score_if_available,
                        "rank_fusion_score": round(contribution.rank_fusion_score, 6),
                    }
                    for contribution in sorted(
                        dense_contributions,
                        key=lambda contribution: (
                            contribution.query_representation,
                            contribution.rank,
                        ),
                    )
                ],
                "phase2_fusion_score_observability_only": round(
                    float(candidate.fusion_score),
                    6,
                ),
            },
        }
        identity = _preferred_dense_candidate_identity(
            candidate=candidate,
            dense_contributions=dense_contributions,
            dense_identity_by_key=dense_identity_by_key,
        )
        item.update(identity)
        projected.append(item)
    projected.sort(key=lambda item: (-float(item["score"]), str(item["section_id"])))
    return {
        "backend_identity": dict(
            fallback.get("backend_identity", {}) if isinstance(fallback, Mapping) else {}
        ),
        "candidates": projected,
    }


def _preferred_dense_result(
    dense_results: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for representation in ("canonical_en", "original"):
        result = dense_results.get(representation)
        if isinstance(result, Mapping):
            return result
    return None


def _dense_candidate_identity_by_key(
    dense_results: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    identities: dict[tuple[str, str], dict[str, Any]] = {}
    for representation, result in dense_results.items():
        if representation not in {"original", "canonical_en"}:
            continue
        candidates = result.get("candidates") if isinstance(result, Mapping) else None
        if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
            continue
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            section_id = str(item.get("section_id", "")).strip()
            if not section_id:
                continue
            identities[(representation, section_id)] = {
                key: item[key]
                for key in (
                    "point_id_sha256",
                    "payload_identity_sha256",
                    "payload_release_id",
                    "payload_text_sha256",
                    "concept_id",
                )
                if key in item
            }
    return identities


def _preferred_dense_candidate_identity(
    *,
    candidate: FusedRetrievalCandidate,
    dense_contributions: Sequence[CandidateContribution],
    dense_identity_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    ranked = sorted(
        dense_contributions,
        key=lambda contribution: (
            contribution.rank,
            0
            if dense_identity_by_key.get(
                (contribution.query_representation, candidate.candidate_id)
            )
            else 1,
            contribution.query_representation,
        ),
    )
    for contribution in ranked:
        identity = dense_identity_by_key.get(
            (contribution.query_representation, candidate.candidate_id)
        )
        if identity:
            return dict(identity)
    return {}


def _selector_projection_summary(
    *,
    union: CandidateUnionResult,
    dense_result: Mapping[str, Any],
) -> dict[str, Any]:
    dense_candidates = _sequence(dense_result.get("candidates"))
    projected_ids = {
        str(item.get("section_id", ""))
        for item in dense_candidates
        if isinstance(item, Mapping)
    }
    dense_contribution_ids = {
        candidate.candidate_id
        for candidate in union.candidates
        if any(contribution.channel == "dense" for contribution in candidate.contributions)
    }
    return {
        "projection_authority": "option_a_dense_contributions_only",
        "fusion_score_is_not_dense_score": True,
        "false_dense_provenance": len(projected_ids - dense_contribution_ids),
        "lexical_double_count": 0,
        "graph_double_count": sum(
            1
            for candidate in union.candidates
            for contribution in candidate.contributions
            if contribution.channel == "graph"
        ),
        "frozen_selector_source_changed": False,
        "frozen_selector_input_semantics_preserved": True,
        "frozen_m26_quality_kernel_preserved": True,
        "phase2_fusion_score_usage": "provenance_observability_diagnostics_only",
        "projected_dense_candidate_count": len(projected_ids),
    }


def _selector_provenance_trace(
    *,
    selected_evidence: Sequence[Mapping[str, Any]],
    union: CandidateUnionResult,
    dense_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_candidate_id = {candidate.candidate_id: candidate for candidate in union.candidates}
    dense_ids = {
        str(item.get("section_id", ""))
        for item in _sequence(dense_result.get("candidates"))
        if isinstance(item, Mapping)
    }
    trace = []
    for item in selected_evidence:
        section_id = str(item.get("section_id", ""))
        candidate = by_candidate_id.get(section_id)
        trace.append(
            {
                "evidence_id": str(item.get("evidence_id", "")),
                "section_id": section_id,
                "selector_channels": [
                    str(channel) for channel in item.get("channels", [])
                ],
                "used_as_frozen_selector_dense_score": section_id in dense_ids,
                "phase2_fusion_score_observability_only": (
                    round(float(candidate.fusion_score), 6)
                    if candidate is not None
                    else None
                ),
                "real_channel_contributions": (
                    [
                        {
                            "channel": contribution.channel,
                            "query_representation": contribution.query_representation,
                            "rank": contribution.rank,
                            "raw_score_if_available": (
                                contribution.raw_score_if_available
                            ),
                            "rank_fusion_score": round(
                                contribution.rank_fusion_score,
                                6,
                            ),
                        }
                        for contribution in candidate.contributions
                    ]
                    if candidate is not None
                    else []
                ),
            }
        )
    return trace


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return value


def _hits_from_items(
    items: Any,
    *,
    score_field: str,
) -> RetrievalChannelResult:
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        return RetrievalChannelResult()
    hits = []
    for rank, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            continue
        section_id = str(item.get("section_id", "")).strip()
        if not section_id:
            continue
        hits.append(
            RetrievalHit(
                candidate_id=section_id,
                rank=rank,
                raw_score_if_available=float(_number(item.get(score_field))),
            )
        )
    return RetrievalChannelResult(hits=tuple(hits))


def _semantic_question_from_envelope(envelope: Any) -> str:
    detected = str(getattr(envelope, "detected_input_language", ""))
    if detected == "en":
        return str(getattr(envelope, "original_question", ""))
    return str(getattr(envelope, "canonical_question_en", ""))


def _fidelity_fields() -> tuple[str, ...]:
    return (
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


def _semantic_fidelity(value: Any) -> SemanticFidelityContract | None:
    if not isinstance(value, Mapping):
        return None
    states: dict[str, str] = {}
    for field_name in _fidelity_fields():
        state = value.get(field_name)
        if state not in {"preserved", "not_applicable", "failed"}:
            return None
        states[field_name] = state
    return SemanticFidelityContract(**states)  # type: ignore[arg-type]


def _strict_claim_items(
    payload: Mapping[str, Any],
    text_field: str,
) -> list[dict[str, str]]:
    items = payload.get("claims")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise LiveGateError("language provider claims sequence missing")
    claims = []
    for item in items:
        if not isinstance(item, Mapping):
            raise LiveGateError("language provider claim item malformed")
        claim_id = _strict_nonempty_str(item, "claim_id")
        text = _strict_nonempty_str(item, text_field)
        if claim_id is None or text is None:
            raise LiveGateError("language provider claim fields malformed")
        claims.append({"claim_id": claim_id, text_field: text})
    return claims


def _strict_review_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("reviews")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise LiveGateError("language provider reviews sequence missing")
    reviews = []
    for item in items:
        review = parse_requested_language_equivalence_review_item(item)
        if review is None:
            raise LiveGateError("language provider review item malformed")
        reviews.append(
            {
                "claim_id": review.claim_id,
                "equivalence": review.equivalence,
                "no_material_factual_expansion": review.no_material_factual_expansion,
                "no_contradiction": review.no_contradiction,
                "negation_preserved": review.negation_preserved,
                "modality_preserved": review.modality_preserved,
                "comparison_direction_preserved": (
                    review.comparison_direction_preserved
                ),
                "relationship_direction_preserved": (
                    review.relationship_direction_preserved
                ),
                "numeric_identity_preserved": review.numeric_identity_preserved,
                "entity_identity_preserved": review.entity_identity_preserved,
            }
        )
    return reviews


def _review_schema() -> dict[str, str]:
    return {
        "claim_id": "same input claim_id",
        "equivalence": "pass|fail",
        "no_material_factual_expansion": "boolean",
        "no_contradiction": "boolean",
        "negation_preserved": "true|false|not_applicable",
        "modality_preserved": "true|false|not_applicable",
        "comparison_direction_preserved": "true|false|not_applicable",
        "relationship_direction_preserved": "true|false|not_applicable",
        "numeric_identity_preserved": "true|false|not_applicable",
        "entity_identity_preserved": "true|false|not_applicable",
    }


def _extract_text(response: Mapping[str, Any]) -> str:
    content = response.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("text")
        )
    return str(response.get("text", ""))


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = stripped.find("{")
    if start < 0:
        raise LiveGateError("provider JSON object missing")
    try:
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    except json.JSONDecodeError as exc:
        raise LiveGateError("provider JSON parse failure") from exc
    if not isinstance(value, dict):
        raise LiveGateError("provider JSON must be object")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_nonempty_str(item: Mapping[str, Any], field_name: str) -> str | None:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.strip().split())


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _external_detail(exc: Exception) -> str:
    if isinstance(exc, (httpx.HTTPError, LiveGateError, legacy.PA7ArbitraryQueryError)):
        return type(exc).__name__ + ": " + str(exc)
    return type(exc).__name__
