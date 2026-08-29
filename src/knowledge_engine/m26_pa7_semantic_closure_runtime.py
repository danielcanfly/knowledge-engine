from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from . import m26_pa7_arbitrary_query_runtime as legacy
from . import m26_sealed_kernel_trace as sealed_trace
from .m14_retrieval import retrieve_wiki_first
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_production_answer_bundle import (
    FULL_PRODUCTION_EDGE_COUNT,
    FULL_PRODUCTION_GRAPH_V2_SHA256,
    FULL_PRODUCTION_NODE_COUNT,
    FULL_PRODUCTION_RELEASE_ID,
    ProductionAnswerBundle,
    load_production_answer_bundle,
)
from .m26_verified_answer_citation_gate import canonical_sha256

DenseChannel = legacy.DenseChannel
ProviderClient = legacy.ProviderClient
LocalDenseProjectionChannel = legacy.LocalDenseProjectionChannel
RemoteQdrantDenseChannel = legacy.RemoteQdrantDenseChannel
RemoteDenseConfig = legacy.RemoteDenseConfig
PA7ArbitraryQueryError = legacy.PA7ArbitraryQueryError
MAX_QUERY_CHARS = legacy.MAX_QUERY_CHARS
RESPONSE_SCHEMA = legacy.RESPONSE_SCHEMA

MAX_PROVIDER_EVIDENCE = 10
MAX_PROVIDER_SNIPPET_CHARS = 420
MAX_PROVIDER_ANSWER_CHARS = 4096
MIN_PROVIDER_OUTPUT_TOKENS = 1024
MIN_PROVIDER_REPAIR_OUTPUT_TOKENS = 1536
MAX_PROVIDER_OUTPUT_TOKENS = 3072
MAX_VERIFICATION_SUPPORT_QUOTE_CHARS = 120
MAX_VERIFICATION_PROVIDER_TEXT_CHARS = 11_500
VERIFICATION_SUPPORT_QUOTE_LIMITS = (96, 72, 48, 32, 24, 16, 8, 4, 1)
RUNTIME_BOUND_SUPPORT_REF_LIMITS = (4, 3, 2, 1)
COMPACT_PROVIDER_TRUNCATED = "COMPACT_PROVIDER_TRUNCATED"
COMPACT_PROVIDER_PARSE_FAILED = "COMPACT_PROVIDER_PARSE_FAILED"
SEMANTIC_REVIEW_PARSE_FAILED = "SEMANTIC_REVIEW_PARSE_FAILED"
SEMANTIC_REVIEW_SCHEMA_VERSION = legacy.SEMANTIC_REVIEW_SCHEMA_VERSION
SEMANTIC_REVIEW_CALL_CLASS = "aq_claim_semantic_entailment"
COMPACT_CLOSURE_SCHEMA_VERSION = "m26-fas-synthesis/segments/v1"
SEMANTIC_SEGMENT_ROLES = {"material_claim", "model_explanation"}
PARTIAL_SEMANTIC_CLOSURE_SOURCE = (
    "provider_verified_runtime_bound_partial_semantic_closure"
)


@dataclass(frozen=True)
class SemanticRequirement:
    requirement_id: str
    instruction: str
    evidence_terms: tuple[str, ...]
    visible_patterns: tuple[str, ...]
    exact_phrase: str = ""


def run_owner_arbitrary_query(
    *,
    root: Path,
    gate: Mapping[str, Any],
    question: str,
    owner_subject_hash: str,
    public_request: bool = False,
    provider_client: ProviderClient | None = None,
    dense_channel: DenseChannel | None = None,
    require_remote_dense: bool = False,
    max_provider_calls: int = 4,
    max_cost: Decimal = Decimal("0.10"),
    answer_bundle: ProductionAnswerBundle | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    normalized_question = legacy._normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = legacy._intent_class(normalized_question)
    validated_gate = legacy._validate_gate(root, gate)
    identities = legacy._object(
        validated_gate.get("production_identities"), "gate.production_identities"
    )
    admission = legacy.evaluate_owner_admission(
        validated_gate,
        {
            "resolved_gate_self_sha256": validated_gate.get("self_sha256"),
            "owner_subject_hash": owner_subject_hash,
            "owner_only_route": identities.get("owner_only_route"),
            "public_request": public_request,
        },
    )
    trace_id = "m26pa7aq_" + canonical_sha256(
        {
            "gate": validated_gate.get("self_sha256"),
            "question_sha256": question_sha,
            "owner_subject_hash": owner_subject_hash,
        }
    )[:32]

    if not admission["admitted"]:
        return legacy._base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status="denied_non_owner_or_public_request",
            terminal_status="denied_before_retrieval",
            reason_codes=admission["reason_codes"],
        )

    if legacy._looks_like_prompt_injection(normalized_question):
        return legacy._base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status="owner_only_safe_abstention",
            terminal_status="safe_abstention",
            reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
        )
    if legacy._looks_like_underspecified_workflow_question(normalized_question):
        return legacy._base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status="owner_only_safe_abstention",
            terminal_status="safe_abstention",
            reason_codes=["QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED"],
        )

    provider = provider_client
    if provider is None:
        try:
            provider = MiniMaxClient(
                legacy.os.environ.get("MINIMAX_API_KEY", ""),
                max_calls=max_provider_calls,
                max_cost=max_cost,
            )
        except LiveGateError as exc:
            verification = legacy._verified_abstention(
                reason_codes=[type(exc).__name__, "PROVIDER_CONFIGURATION_MISSING"],
                calls=[],
                repair_attempted=False,
            )
            return _response_from_verification(
                gate=validated_gate,
                bundle=None,
                dense_result=None,
                lexical_result=None,
                evidence=[],
                verification=verification,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                intent_class=intent_class,
                semantic_closure={
                    "requirements": [],
                    "support_proof": [],
                    "failures": [],
                },
            )

    bundle = answer_bundle or load_production_answer_bundle()
    _assert_full_production_graph(bundle)

    dense = (
        dense_channel or legacy.dense_channel_from_env(require_remote=require_remote_dense)
    ).search(
        question=normalized_question,
        bundle=bundle,
        top_k=8,
    )
    lexical = retrieve_wiki_first(
        query=normalized_question,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=None,
        limit=8,
    )
    evidence = legacy._select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    requirements = _semantic_requirements(normalized_question, intent_class)
    evidence, endpoint_proof = _strengthen_evidence(
        bundle=bundle,
        evidence=evidence,
        lexical_result=lexical,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        requirements=requirements,
    )

    if not evidence or not legacy._has_meaningful_overlap(normalized_question, evidence):
        verification = legacy._verified_abstention(
            reason_codes=(
                ["NO_AUTHORIZED_PRODUCTION_EVIDENCE"]
                if not evidence
                else ["LOW_RETRIEVAL_SUPPORT"]
            ),
            calls=[],
            repair_attempted=False,
        )
        return _response_from_verification(
            gate=validated_gate,
            bundle=bundle,
            dense_result=dense,
            lexical_result=lexical,
            evidence=[],
            verification=verification,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            semantic_closure={
                "requirements": [_requirement_public(item) for item in requirements],
                "support_proof": [],
                "endpoint_proof": endpoint_proof,
                "failures": ["LOW_RETRIEVAL_SUPPORT"],
            },
        )

    verification, closure = _synthesize_and_verify(
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        requirements=requirements,
        endpoint_proof=endpoint_proof,
    )
    return _response_from_verification(
        gate=validated_gate,
        bundle=bundle,
        dense_result=dense,
        lexical_result=lexical,
        evidence=evidence,
        verification=verification,
        trace_id=trace_id,
        question_sha=question_sha,
        started=started,
        intent_class=intent_class,
        semantic_closure=closure,
    )


def _assert_full_production_graph(bundle: ProductionAnswerBundle) -> None:
    nodes = legacy._list(bundle.graph_v2.get("nodes"), "graph_v2 nodes")
    edges = legacy._list(bundle.graph_v2.get("edges"), "graph_v2 edges")
    if bundle.release_id != FULL_PRODUCTION_RELEASE_ID:
        raise PA7ArbitraryQueryError(
            "PA7_PRODUCTION_BUNDLE_RELEASE_MISMATCH",
            "answer runtime is not bound to the accepted full production release",
        )
    if bundle.artifact_sha256.get("graph_v2") != FULL_PRODUCTION_GRAPH_V2_SHA256:
        raise PA7ArbitraryQueryError(
            "PA7_PRODUCTION_GRAPH_DIGEST_MISMATCH",
            "answer runtime graph digest is not the accepted production graph",
        )
    if len(nodes) != FULL_PRODUCTION_NODE_COUNT or len(edges) != FULL_PRODUCTION_EDGE_COUNT:
        raise PA7ArbitraryQueryError(
            "PA7_PRODUCTION_GRAPH_POPULATION_MISMATCH",
            "answer runtime must use the 4,222-node / 8,525-edge production graph",
        )


def _response_from_verification(
    *,
    gate: Mapping[str, Any],
    bundle: ProductionAnswerBundle | None,
    dense_result: Mapping[str, Any] | None,
    lexical_result: Mapping[str, Any] | None,
    evidence: Sequence[Mapping[str, Any]],
    verification: Mapping[str, Any],
    trace_id: str,
    question_sha: str,
    started: float,
    intent_class: str,
    semantic_closure: Mapping[str, Any],
) -> dict[str, Any]:
    response = {
        **legacy._base_response(
            gate=gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status=str(verification["status"]),
            terminal_status=str(verification["terminal_status"]),
            answer_text=str(verification.get("answer_text", "")),
            safe_abstention=bool(verification.get("safe_abstention", True)),
            reason_codes=verification.get("reason_codes", []),
            provider_invoked=int(verification.get("provider_call_count", 0)) > 0,
            provider_call_count=int(verification.get("provider_call_count", 0)),
            payg_equivalent_cost_usd=str(
                verification.get("payg_equivalent_cost_usd", "0")
            ),
            material_claim_support_verified=bool(
                verification.get("material_claim_support_verified", True)
            ),
            citation_locator_valid=bool(
                verification.get("citation_locator_valid", True)
            ),
            unsupported_accepted_claims=int(
                verification.get("unsupported_accepted_claims", 0)
            ),
            repair_attempted=bool(verification.get("repair_attempted", False)),
        ),
        "citations": list(verification.get("citations", [])),
        "answer_claims": list(verification.get("answer_claims", [])),
        "answer_source": str(verification.get("answer_source", "safe_abstention")),
        "relationship_summary": dict(
            verification.get("relationship_summary", {})
        ),
        "multi_evidence_verification": dict(
            verification.get("multi_evidence_verification", {})
        ),
        "semantic_closure": dict(semantic_closure),
    }
    if bundle is not None and dense_result is not None and lexical_result is not None:
        response.update(
            legacy._retrieval_response_fields(
                gate=gate,
                bundle=bundle,
                lexical_result=lexical_result,
                dense_result=dense_result,
                selected_evidence=evidence,
                intent_class=intent_class,
            )
        )
        response["evidence_utilization_trace"] = legacy._evidence_utilization_trace(
            response
        )
    response["latency_ms"] = max(
        int(response.get("latency_ms", 0)),
        int((time.monotonic() - started) * 1000),
    )
    return response


def _synthesize_and_verify(
    *,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: ProviderClient,
    requirements: Sequence[SemanticRequirement],
    endpoint_proof: Mapping[str, Any],
    allow_deterministic_recovery: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sealed_trace.trace(
        "synthesize_entry",
        trace_id=trace_id,
        question_sha256=canonical_sha256(question),
        intent_class=intent_class,
        evidence=sealed_trace.evidence_summary(evidence),
        requirement_ids=[item.requirement_id for item in requirements],
    )
    failures: list[str] = []
    calls: list[dict[str, Any]] = []
    repair_attempted = False
    final_support_proof: list[dict[str, Any]] = []

    for attempt in (1, 2):
        compact_payload, label_map, snippet_map = _compact_provider_payload(
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            requirements=requirements,
            repair=attempt == 2,
            previous_failures=failures,
        )
        sealed_trace.trace(
            "compact_provider_payload_ready",
            attempt=attempt,
            purpose=(
                "aq_semantic_closure_repair"
                if attempt == 2
                else "aq_semantic_closure"
            ),
            payload=sealed_trace.payload_fingerprint(compact_payload),
            label_count=len(label_map),
            snippet_count=len(snippet_map),
        )
        try:
            sealed_trace.trace(
                "provider_call_before",
                attempt=attempt,
                purpose=(
                    "aq_semantic_closure_repair"
                    if attempt == 2
                    else "aq_semantic_closure"
                ),
                payload=sealed_trace.payload_fingerprint(compact_payload),
            )
            raw = provider_client.call(
                compact_payload,
                (
                    "aq_semantic_closure_repair"
                    if attempt == 2
                    else "aq_semantic_closure"
                ),
            )
            sealed_trace.trace(
                "provider_call_after",
                attempt=attempt,
                purpose=(
                    "aq_semantic_closure_repair"
                    if attempt == 2
                    else "aq_semantic_closure"
                ),
                response=sealed_trace.response_fingerprint(raw),
            )
            try:
                stop_reason = str(
                    raw.get("stop_reason") or raw.get("finish_reason") or ""
                )
                raw_text = str(raw.get("text", raw.get("provider_text", "")))
                parse_meta: dict[str, Any] = {}
                parsed = _parse_compact_provider_result(raw_text)
            except ValueError:
                salvaged = _salvage_compact_provider_surplus_segments(
                    raw_text,
                    label_map=label_map,
                )
                if salvaged is None:
                    sealed_trace.trace(
                        "provider_parse_failure",
                        attempt=attempt,
                        stop_reason=stop_reason,
                        response=sealed_trace.response_fingerprint(raw),
                    )
                    calls.append(_compact_call_telemetry(raw, parse_ok=False))
                    if stop_reason == "max_tokens":
                        failures.append(COMPACT_PROVIDER_TRUNCATED)
                    else:
                        failures.append(COMPACT_PROVIDER_PARSE_FAILED)
                    if attempt == 1:
                        repair_attempted = True
                        sealed_trace.trace(
                            "repair_transition",
                            attempt=attempt,
                            failures=list(failures),
                        )
                        continue
                    break
                parsed, parse_meta = salvaged
                sealed_trace.trace(
                    "provider_parse_salvage_success",
                    attempt=attempt,
                    dropped_segment_ids=parse_meta.get("dropped_segment_ids", []),
                    retained_segment_count=parse_meta.get("retained_segment_count", 0),
                )
            sealed_trace.trace(
                "provider_parse_success",
                attempt=attempt,
                parsed_status=str(parsed["status"]),
                segment_count=len(
                    parsed.get("segments", [])
                    if isinstance(parsed.get("segments"), list)
                    else []
                ),
            )
            calls.append(
                _compact_call_telemetry(raw, parse_ok=True, parse_meta=parse_meta)
            )
            if parsed["status"] == "abstain":
                failures.append("PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE")
                sealed_trace.trace(
                    "provider_abstain_observed",
                    attempt=attempt,
                    failures=list(failures),
                )
                if attempt == 1:
                    repair_attempted = True
                    sealed_trace.trace(
                        "repair_transition",
                        attempt=attempt,
                        failures=list(failures),
                    )
                    continue
                break

            provider_status = str(parsed["status"])
            segments = _parsed_provider_segments(parsed)
            answer = _visible_answer_from_segments(segments)
            unanswered_dimensions = _parsed_provider_unanswered_dimensions(
                parsed, segments
            )
            candidate = _runtime_bound_candidate(
                answer=answer,
                question=question,
                intent_class=intent_class,
                used_items=(),
                claims=None,
                segments=segments,
                label_map=label_map,
                snippet_map=snippet_map,
                provider_status=provider_status,
                requirements=requirements,
                unanswered_dimensions=unanswered_dimensions,
                semantic_failures=[],
            )
            candidate, bounded_support_ref_limit = _bounded_publication_candidate(
                candidate
            )
            sealed_trace.trace(
                "candidate_constructed",
                attempt=attempt,
                candidate=sealed_trace.candidate_summary(candidate),
                bounded_publication_support_ref_limit=bounded_support_ref_limit,
            )
            sealed_trace.trace(
                "material_requirement_coverage_decision",
                attempt=attempt,
                decision_result="deferred_to_semantic_review_visible_coverage",
                requirement_count=len(requirements),
                candidate=sealed_trace.candidate_summary(candidate),
            )
            sealed_trace.trace(
                "partial_material_gap_decision",
                attempt=attempt,
                parsed_status=provider_status,
                unanswered_dimension_count=len(unanswered_dimensions),
            )
            sealed_trace.trace(
                "semantic_review_before",
                attempt=attempt,
                purpose=SEMANTIC_REVIEW_CALL_CLASS,
                candidate=sealed_trace.candidate_summary(candidate),
            )
            review_started_ns = time.monotonic_ns()
            try:
                semantic_review, review_raw = _call_semantic_entailment_review(
                    provider_client=provider_client,
                    question=question,
                    intent_class=intent_class,
                    candidate=candidate,
                    evidence=evidence,
                )
            except (LiveGateError, httpx.HTTPError) as exc:
                sealed_trace.trace(
                    "semantic_review_failure_observed",
                    attempt=attempt,
                    purpose=SEMANTIC_REVIEW_CALL_CLASS,
                    **sealed_trace.exception_summary(exc, started_ns=review_started_ns),
                )
                raise
            sealed_trace.trace(
                "semantic_review_after",
                attempt=attempt,
                purpose=SEMANTIC_REVIEW_CALL_CLASS,
                response=sealed_trace.response_fingerprint(review_raw),
                review=sealed_trace.review_summary(semantic_review),
            )
            claim_by_id = _candidate_claim_by_id(candidate)
            semantic_review = _canonicalize_semantic_review_evidence_refs(
                semantic_review,
                claim_by_id,
            )
            calls.append(_compact_call_telemetry(review_raw, parse_ok=True))
            if _semantic_review_has_out_of_local_evidence(
                semantic_review,
                claim_by_id,
            ):
                sealed_trace.trace(
                    "out_of_local_evidence_decision",
                    attempt=attempt,
                    out_of_local_evidence=True,
                )
                failures.append("M26-PA7-ME-065")
                if attempt == 1:
                    repair_attempted = True
                    sealed_trace.trace(
                        "repair_transition",
                        attempt=attempt,
                        failures=list(failures),
                    )
                    continue
                break
            sealed_trace.trace(
                "out_of_local_evidence_decision",
                attempt=attempt,
                out_of_local_evidence=False,
            )
            review_failures = _semantic_review_blocking_failures(semantic_review)
            sealed_trace.trace(
                "semantic_review_blocking_failures",
                attempt=attempt,
                failures=list(review_failures),
            )
            if review_failures:
                failures.extend(review_failures)
                if attempt == 1:
                    repair_attempted = True
                    sealed_trace.trace(
                        "repair_transition",
                        attempt=attempt,
                        failures=list(failures),
                    )
                    continue
                partial = _verified_supported_review_partial(
                    trace_id=trace_id,
                    question=question,
                    intent_class=intent_class,
                    evidence=evidence,
                    candidate=candidate,
                    semantic_review=semantic_review,
                    calls=calls,
                    repair_attempted=repair_attempted,
                    failures=failures,
                    requirements=requirements,
                    endpoint_proof=endpoint_proof,
                    final_support_proof=final_support_proof,
                )
                if partial is not None:
                    sealed_trace.trace(
                        "synthesize_return",
                        attempt=attempt,
                        terminal_classification="verified_partial_after_review_block",
                        failures=list(failures),
                    )
                    return partial
                break
            try:
                verified = legacy._verify_multi_evidence_provider_output(
                    trace_id=trace_id,
                    question=question,
                    intent_class=intent_class,
                    evidence=evidence,
                    provider_text=json.dumps(
                        _verification_candidate(candidate),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    semantic_review=semantic_review,
                )
            except legacy.VerifiedAnswerGateError as exc:
                failures.append(exc.code)
                sealed_trace.trace(
                    "verified_answer_gate_error",
                    attempt=attempt,
                    code=str(exc.code),
                    failures=list(failures),
                )
                if attempt == 1:
                    repair_attempted = True
                    sealed_trace.trace(
                        "repair_transition",
                        attempt=attempt,
                        failures=list(failures),
                    )
                    continue
                partial = _verified_supported_review_partial(
                    trace_id=trace_id,
                    question=question,
                    intent_class=intent_class,
                    evidence=evidence,
                    candidate=candidate,
                    semantic_review=semantic_review,
                    calls=calls,
                    repair_attempted=repair_attempted,
                    failures=failures,
                    requirements=requirements,
                    endpoint_proof=endpoint_proof,
                    final_support_proof=final_support_proof,
                )
                if partial is not None:
                    sealed_trace.trace(
                        "synthesize_return",
                        attempt=attempt,
                        terminal_classification="verified_partial_after_gate_error",
                        failures=list(failures),
                    )
                    return partial
                sealed_trace.trace(
                    "synthesize_exception",
                    attempt=attempt,
                    terminal_classification="verified_answer_gate_error",
                    exception_code=str(exc.code),
                    failures=list(failures),
                )
                raise
            final_answer = legacy._verified_multi_evidence_answer(
                intent_class=intent_class,
                verified=verified,
                evidence=evidence,
                calls=calls,
                repair_attempted=repair_attempted,
            )
            partial_answer = provider_status in {"partial", "partial_candidate"}

            final_answer["answer_source"] = (
                PARTIAL_SEMANTIC_CLOSURE_SOURCE
                if partial_answer
                else "provider_verified_runtime_bound_semantic_closure"
            )
            final_answer["multi_evidence_verification"] = {
                **dict(final_answer.get("multi_evidence_verification", {})),
                "verification_failure_codes_by_attempt": list(failures),
                "repair_trigger": sorted(set(failures)) if repair_attempted else [],
                "repair_result": (
                    "verified_partial"
                    if partial_answer
                    else "verified"
                    if repair_attempted
                    else "not_needed"
                ),
                "deterministic_evidence_synthesis_used": False,
                "bounded_publication_support_ref_limit": bounded_support_ref_limit,
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
                "semantic_review": dict(verified.get("semantic_review", {})),
            }
            if partial_answer:
                final_answer["multi_evidence_verification"]["partial_answer"] = True
                final_answer["multi_evidence_verification"][
                    "unanswered_dimensions"
                ] = unanswered_dimensions
            closure = {
                "schema_version": "m26-aq-semantic-closure/v1",
                "requirements": [_requirement_public(item) for item in requirements],
                "support_proof": final_support_proof,
                "endpoint_proof": dict(endpoint_proof),
                "failures": [],
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
                "semantic_review": dict(verified.get("semantic_review", {})),
                "bounded_publication_support_ref_limit": bounded_support_ref_limit,
                "broad_deterministic_fallback_used": False,
            }
            if partial_answer:
                closure["pre_partial_failures"] = sorted(set(failures))
                closure["partial_answer"] = True
                closure["unanswered_dimensions"] = unanswered_dimensions
            sealed_trace.trace(
                "synthesize_return",
                attempt=attempt,
                terminal_classification=(
                    "verified_partial" if partial_answer else "verified"
                ),
                failures=list(failures),
            )
            return final_answer, closure
        except (legacy.VerifiedAnswerGateError, ValueError, KeyError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            failures.append(str(code))
            sealed_trace.trace(
                "synthesize_exception_observed",
                attempt=attempt,
                exception_class=type(exc).__name__,
                exception_code=str(code),
                failures=list(failures),
            )
            if attempt == 1:
                repair_attempted = True
                sealed_trace.trace(
                    "repair_transition",
                    attempt=attempt,
                    failures=list(failures),
                )
                continue
        except (LiveGateError, httpx.HTTPError) as exc:
            failures.append(type(exc).__name__)
            sealed_trace.trace(
                "synthesize_exception_observed",
                attempt=attempt,
                exception_class=type(exc).__name__,
                exception_code=type(exc).__name__,
                failures=list(failures),
            )
            break

    if allow_deterministic_recovery:
        deterministic = legacy._deterministic_evidence_synthesis(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            calls=calls,
            repair_attempted=True,
            trigger_reason_codes=[*failures, "SEMANTIC_CLOSURE_FAILED"],
            allow_after_repair_failure=True,
        )
        if deterministic is not None:
            deterministic["multi_evidence_verification"] = {
                **dict(deterministic.get("multi_evidence_verification", {})),
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
            }
            closure = {
                "schema_version": "m26-aq-semantic-closure/v1",
                "requirements": [_requirement_public(item) for item in requirements],
                "support_proof": final_support_proof,
                "endpoint_proof": dict(endpoint_proof),
                "failures": [],
                "pre_recovery_failures": sorted(set(failures)),
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
                "broad_deterministic_fallback_used": True,
            }
            sealed_trace.trace(
                "synthesize_return",
                terminal_classification="deterministic_recovery",
                failures=list(failures),
            )
            return deterministic, closure

    final_failures = sorted({*failures, "SEMANTIC_CLOSURE_FAILED"})
    abstention = legacy._verified_abstention(
        reason_codes=final_failures,
        calls=calls,
        repair_attempted=repair_attempted,
    )
    abstention["answer_source"] = "safe_abstention"
    abstention["multi_evidence_verification"] = {
        **dict(abstention.get("multi_evidence_verification", {})),
        "provider_contract": "compact_runtime_bound_semantic_closure/v1",
    }
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [_requirement_public(item) for item in requirements],
        "support_proof": final_support_proof,
        "endpoint_proof": dict(endpoint_proof),
        "failures": final_failures,
        "provider_contract": "compact_runtime_bound_semantic_closure/v1",
        "broad_deterministic_fallback_used": False,
    }
    sealed_trace.trace(
        "synthesize_return",
        terminal_classification="safe_abstention",
        failures=final_failures,
    )
    return abstention, closure


def _verified_supported_review_partial(
    *,
    trace_id: str,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    semantic_review: Mapping[str, Any],
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
    failures: Sequence[str],
    requirements: Sequence[SemanticRequirement],
    endpoint_proof: Mapping[str, Any],
    final_support_proof: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    partial_candidate, partial_review, dropped_claim_ids = (
        _supported_review_partial_candidate(candidate, semantic_review)
    )
    if partial_candidate is None:
        return None
    try:
        verified = legacy._verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            evidence=evidence,
            provider_text=json.dumps(
                _verification_candidate(partial_candidate),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            semantic_review=partial_review,
        )
        answer = legacy._verified_multi_evidence_answer(
            intent_class=intent_class,
            verified=verified,
            evidence=evidence,
            calls=calls,
            repair_attempted=repair_attempted,
        )
    except Exception:
        return None

    pre_partial_failures = sorted({str(item) for item in failures if str(item)})
    answer["answer_source"] = PARTIAL_SEMANTIC_CLOSURE_SOURCE
    answer["multi_evidence_verification"] = {
        **dict(answer.get("multi_evidence_verification", {})),
        "verification_failure_codes_by_attempt": pre_partial_failures,
        "repair_trigger": pre_partial_failures,
        "repair_result": "semantic_review_supported_partial",
        "deterministic_evidence_synthesis_used": False,
        "provider_contract": "compact_runtime_bound_semantic_closure/v1",
        "semantic_review": dict(verified.get("semantic_review", {})),
        "partial_answer": True,
        "dropped_claim_count": len(dropped_claim_ids),
        "dropped_claim_ids": dropped_claim_ids,
    }
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [_requirement_public(item) for item in requirements],
        "support_proof": list(final_support_proof),
        "endpoint_proof": dict(endpoint_proof),
        "failures": [],
        "pre_partial_failures": pre_partial_failures,
        "provider_contract": "compact_runtime_bound_semantic_closure/v1",
        "semantic_review": dict(verified.get("semantic_review", {})),
        "broad_deterministic_fallback_used": False,
        "partial_answer": True,
        "dropped_claim_count": len(dropped_claim_ids),
        "dropped_claim_ids": dropped_claim_ids,
    }
    return answer, closure


def _supported_review_partial_candidate(
    candidate: Mapping[str, Any],
    semantic_review: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    claims = [
        dict(item)
        for item in legacy._list(candidate.get("claims"), "partial candidate claims")
        if isinstance(item, Mapping)
    ]
    if not claims:
        return None, {}, []
    claim_by_id = {str(claim.get("claim_id", "")): claim for claim in claims}
    semantic_review = _canonicalize_semantic_review_evidence_refs(
        semantic_review,
        claim_by_id,
    )
    if _semantic_review_has_out_of_local_evidence(semantic_review, claim_by_id):
        return None, {}, []
    supported_ids: list[str] = []
    dropped_ids: list[str] = []
    filtered_judgments: list[dict[str, Any]] = []
    for raw in legacy._list(
        semantic_review.get("claim_judgments"),
        "partial semantic review judgments",
    ):
        judgment = legacy._object(raw, "partial semantic review judgment")
        claim_id = str(judgment.get("claim_id", ""))
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        verdict = str(judgment.get("verdict", ""))
        claim_type = str(claim.get("claim_type", ""))
        if verdict == legacy.SEMANTIC_REVIEW_ENTAILED or (
            verdict == legacy.SEMANTIC_REVIEW_GENERIC_EXPLANATION
            and claim_type == "MODEL_EXPLANATION"
        ):
            supported_ids.append(claim_id)
            filtered_judgments.append(
                {
                    "claim_id": claim_id,
                    "verdict": verdict,
                    "evidence_ids": [
                        str(item)
                        for item in legacy._list(
                            judgment.get("evidence_ids"),
                            "partial semantic evidence ids",
                        )
                    ],
                }
            )
        else:
            dropped_ids.append(claim_id)

    if not supported_ids:
        return None, {}, dropped_ids
    supported_claims = [claim_by_id[claim_id] for claim_id in supported_ids]
    if not any(claim.get("support_refs") for claim in supported_claims):
        return None, {}, dropped_ids

    compact_claims = [_compact_partial_claim(claim) for claim in supported_claims]
    answer_text = _partial_answer_text(compact_claims)
    partial_review = {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "claim_judgments": filtered_judgments,
        "visible_coverage": {
            "verdict": "COVERED",
            "uncovered_assertions": [],
        },
    }
    return (
        {
            "schema_version": str(candidate.get("schema_version", "aq3-provider-candidate/v3")),
            "status": "partial_candidate",
            "relation": candidate.get("relation"),
            "selected_evidence_ids": list(
                dict.fromkeys(
                    str(ref.get("evidence_id", ""))
                    for claim in compact_claims
                    for ref in legacy._list(
                        claim.get("support_refs"), "partial support refs"
                    )
                    if str(ref.get("evidence_id", ""))
                )
            ),
            "answer_text": answer_text,
            "claims": compact_claims,
            "missing_facets": [],
            "abstention_reason": None,
            "unanswered_dimensions": dropped_ids,
        },
        partial_review,
        dropped_ids,
    )


def _candidate_claim_by_id(candidate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(claim.get("claim_id", "")): claim
        for claim in legacy._list(candidate.get("claims"), "candidate claims")
        if isinstance(claim, Mapping) and str(claim.get("claim_id", ""))
    }


def _semantic_review_has_out_of_local_evidence(
    semantic_review: Mapping[str, Any],
    claim_by_id: Mapping[str, Mapping[str, Any]],
) -> bool:
    for raw in legacy._list(
        semantic_review.get("claim_judgments"),
        "semantic review judgments",
    ):
        judgment = legacy._object(raw, "semantic review judgment")
        claim_id = str(judgment.get("claim_id", ""))
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        allowed = set(_claim_local_evidence_ids(claim))
        evidence_ids = set(
            str(item)
            for item in legacy._list(
                judgment.get("evidence_ids"),
                "semantic review evidence ids",
            )
        )
        if not evidence_ids.issubset(allowed):
            return True
    return False


def _canonicalize_semantic_review_evidence_refs(
    semantic_review: Mapping[str, Any],
    claim_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    canonical = dict(semantic_review)
    canonical_judgments: list[dict[str, Any]] = []
    for raw in legacy._list(
        semantic_review.get("claim_judgments"),
        "semantic review judgments",
    ):
        judgment = legacy._object(raw, "semantic review judgment")
        claim_id = str(judgment.get("claim_id", ""))
        claim = claim_by_id.get(claim_id)
        allowed = set(_claim_local_evidence_ids(claim)) if claim else set()
        alias_by_label = _claim_local_evidence_aliases(claim) if claim else {}
        evidence_ids: list[str] = []
        for raw_evidence_id in legacy._list(
            judgment.get("evidence_ids"),
            "semantic review evidence ids",
        ):
            evidence_ref = str(raw_evidence_id)
            if evidence_ref in allowed:
                evidence_ids.append(evidence_ref)
            elif evidence_ref in alias_by_label:
                evidence_ids.append(alias_by_label[evidence_ref])
            else:
                evidence_ids.append(evidence_ref)
        canonical_judgments.append(
            {
                **dict(judgment),
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
            }
        )
    canonical["claim_judgments"] = canonical_judgments
    return canonical


def _claim_local_evidence_ids(claim: Mapping[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(ref.get("evidence_id", ""))
            for ref in legacy._list(claim.get("support_refs"), "claim local support refs")
            if isinstance(ref, Mapping) and str(ref.get("evidence_id", ""))
        )
    )


def _claim_local_evidence_aliases(claim: Mapping[str, Any]) -> dict[str, str]:
    return {
        f"local_{index}": evidence_id
        for index, evidence_id in enumerate(_claim_local_evidence_ids(claim), start=1)
    }


def _bounded_publication_candidate(
    candidate: Mapping[str, Any],
) -> tuple[dict[str, Any], int | None]:
    candidate_dict = dict(candidate)
    if _json_size(_verification_candidate(candidate_dict)) <= MAX_VERIFICATION_PROVIDER_TEXT_CHARS:
        return candidate_dict, None
    bounded: dict[str, Any] | None = None
    for support_ref_limit in RUNTIME_BOUND_SUPPORT_REF_LIMITS:
        bounded = _candidate_with_support_ref_limit(
            candidate_dict,
            support_ref_limit=support_ref_limit,
        )
        if _json_size(_verification_candidate(bounded)) <= MAX_VERIFICATION_PROVIDER_TEXT_CHARS:
            return bounded, support_ref_limit
    if bounded is None:
        return candidate_dict, None
    return bounded, RUNTIME_BOUND_SUPPORT_REF_LIMITS[-1]


def _candidate_with_support_ref_limit(
    candidate: Mapping[str, Any],
    *,
    support_ref_limit: int,
) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    selected_evidence_ids: list[str] = []
    for raw_claim in legacy._list(candidate.get("claims"), "bounded publication claims"):
        claim = dict(legacy._object(raw_claim, "bounded publication claim"))
        support_refs = [
            dict(legacy._object(ref, "bounded publication support ref"))
            for ref in legacy._list(
                claim.get("support_refs"),
                "bounded publication support refs",
            )
        ][:support_ref_limit]
        claim["support_refs"] = support_refs
        claims.append(claim)
        selected_evidence_ids.extend(
            str(ref.get("evidence_id", ""))
            for ref in support_refs
            if str(ref.get("evidence_id", ""))
        )
    return {
        **dict(candidate),
        "claims": claims,
        "selected_evidence_ids": list(dict.fromkeys(selected_evidence_ids)),
    }


def _verification_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw_claims = legacy._list(candidate.get("claims"), "verification claims")
    verification: dict[str, Any] | None = None
    for quote_limit in (MAX_VERIFICATION_SUPPORT_QUOTE_CHARS, *VERIFICATION_SUPPORT_QUOTE_LIMITS):
        compact_claims = [
            _compact_partial_claim(claim, quote_limit=quote_limit)
            for claim in raw_claims
        ]
        verification = _verification_candidate_from_compact_claims(
            candidate,
            compact_claims,
        )
        if _json_size(verification) <= MAX_VERIFICATION_PROVIDER_TEXT_CHARS:
            return verification
    if verification is None:
        verification = _verification_candidate_from_compact_claims(candidate, [])
    return verification


def _verification_candidate_from_compact_claims(
    candidate: Mapping[str, Any],
    compact_claims: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_evidence_ids = list(
        dict.fromkeys(
            str(ref.get("evidence_id", ""))
            for claim in compact_claims
            for ref in legacy._list(
                claim.get("support_refs"), "verification support refs"
            )
            if str(ref.get("evidence_id", ""))
        )
    )
    if not selected_evidence_ids:
        selected_evidence_ids = [
            str(item)
            for item in legacy._list(
                candidate.get("selected_evidence_ids"), "verification selected evidence"
            )
            if str(item)
        ]
    return {
        "schema_version": str(candidate.get("schema_version", "aq3-provider-candidate/v3")),
        "status": str(candidate.get("status", "answer_candidate")),
        "relation": candidate.get("relation"),
        "selected_evidence_ids": selected_evidence_ids,
        "answer_text": str(candidate.get("answer_text", "")),
        "claims": compact_claims,
        "missing_facets": [
            str(item)
            for item in legacy._list(candidate.get("missing_facets", []), "verification missing facets")
            if str(item)
        ],
        "abstention_reason": candidate.get("abstention_reason"),
        "unanswered_dimensions": [
            str(item)
            for item in legacy._list(
                candidate.get("unanswered_dimensions", []),
                "verification unanswered dimensions",
            )
            if str(item)
        ][:16],
    }


def _json_size(value: Mapping[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _compact_partial_claim(
    claim: Mapping[str, Any],
    *,
    quote_limit: int = MAX_VERIFICATION_SUPPORT_QUOTE_CHARS,
) -> dict[str, Any]:
    support_refs = [
        _compact_partial_ref(ref, quote_limit=quote_limit)
        for ref in legacy._list(claim.get("support_refs"), "partial support refs")
    ]
    compact = {
        "claim_id": str(claim.get("claim_id", "")),
        "claim_role": str(claim.get("claim_role", "direct")),
        "claim_type": str(claim.get("claim_type", "EVIDENCE_FACT")),
        "surface_text": str(claim.get("surface_text", "")),
        "facet_ids": [
            str(item)
            for item in legacy._list(claim.get("facet_ids", []), "partial facets")
            if str(item)
        ],
        "support_mode": str(claim.get("support_mode", "exact_quote")),
        "support_refs": support_refs,
    }
    unanswered = [
        str(item)
        for item in legacy._list(
            claim.get("unanswered_dimensions", []), "partial unanswered dimensions"
        )
        if str(item)
    ]
    if unanswered:
        compact["unanswered_dimensions"] = unanswered[:8]
    return compact


def _compact_partial_ref(
    ref: Mapping[str, Any],
    *,
    quote_limit: int = MAX_VERIFICATION_SUPPORT_QUOTE_CHARS,
) -> dict[str, Any]:
    exact_quote = str(ref.get("exact_quote", ""))
    compact_quote = legacy._first_exact_evidence_quote(
        exact_quote,
        max_chars=quote_limit,
    )
    return {
        "evidence_id": str(ref.get("evidence_id", "")),
        "locator_id": str(ref.get("locator_id", "")),
        "exact_quote": compact_quote or exact_quote,
        "uncertainty": str(ref.get("uncertainty", "low")),
    }


def _partial_answer_text(claims: Sequence[Mapping[str, Any]]) -> str:
    segments: list[str] = []
    for claim in claims:
        surface = re.sub(r"\s+", " ", str(claim.get("surface_text", ""))).strip()
        if not surface:
            continue
        segments.append(surface)
    return " ".join(segments)


def _compact_provider_payload(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[SemanticRequirement],
    repair: bool,
    previous_failures: Sequence[str],
) -> tuple[
    dict[str, Any],
    dict[str, Mapping[str, Any]],
    dict[str, str],
]:
    ranked = _provider_evidence_order(evidence, requirements, question)[
        :MAX_PROVIDER_EVIDENCE
    ]
    label_map: dict[str, Mapping[str, Any]] = {}
    snippet_map: dict[str, str] = {}
    packed = []
    for index, item in enumerate(ranked, start=1):
        label = f"e{index}"
        snippet = _provider_snippet(item, question, requirements)
        label_map[label] = item
        snippet_map[str(item.get("evidence_id", ""))] = snippet
        packed.append(
            {
                "id": label,
                "type": str(item.get("evidence_type", "passage")),
                "source": str(
                    item.get("source_identity") or item.get("source_id") or ""
                ),
                "title": str(item.get("title", ""))[:120],
                "section": str(item.get("section_title", ""))[:120],
                "concept": str(item.get("concept_id", ""))[:120],
                "relation": str(item.get("relation_type", "")),
                "from": str(item.get("edge_source", ""))[:120],
                "to": str(item.get("edge_target", ""))[:120],
                "relation_metadata": dict(item.get("relation_metadata", {}))
                if isinstance(item.get("relation_metadata"), Mapping)
                else {},
                "text": snippet,
            }
        )
    task = {
        "question": question,
        "intent": intent_class,
        "must_state": [item.instruction for item in requirements],
        "evidence": packed,
        "repair": list(previous_failures)[-8:] if repair else [],
        "output": {
            "schema_version": COMPACT_CLOSURE_SCHEMA_VERSION,
            "status": "answer|partial|abstain",
            "segments": [
                {
                    "segment_id": "s1",
                    "semantic_role": "material_claim",
                    "claim_id": "claim_1",
                    "claim_type": "EVIDENCE_FACT|EVIDENCE_SYNTHESIS",
                    "text": "Provider-authored visible prose.",
                    "evidence_labels": ["e1"],
                    "covers": [],
                }
            ],
            "unanswered_dimensions": [],
            "abstention_reason": None,
        },
    }
    system = (
        "Answer only from supplied evidence. Return exactly one compact JSON object with "
        "keys schema_version, status, segments, unanswered_dimensions, and "
        "abstention_reason. status is answer, partial, or abstain. Every visible prose "
        "unit must appear exactly once as a segment text; do not include answer_text, "
        "claims, surface_text, or inline [[claim_id]] anchors. Each segment must include "
        "segment_id, semantic_role, and text. semantic_role must be material_claim or "
        "model_explanation. Use model_explanation only for genuinely generic connective "
        "or explanatory prose whose truth does not depend on supplied KB evidence. A "
        "segment must be material_claim if it refers to corpus-specific entities, document "
        "titles, numbered or versioned entities, identifiers, graph nodes, supplied graph "
        "relations, what supplied evidence entails or does not entail, or a supported "
        "negation, limitation, boundary, comparison, or non-inference; material_claim also "
        "applies to any segment that would require KB evidence to verify. If uncertain "
        "between material_claim and model_explanation, choose material_claim and bind "
        "evidence. For material_claim segments include exactly one claim_id, a claim_type "
        "value EVIDENCE_FACT or EVIDENCE_SYNTHESIS, evidence_labels, and covers. For "
        "model_explanation segments include claim_id, claim_type MODEL_EXPLANATION, "
        "evidence_labels [], and covers. Evidence labels such as e1 or e2 belong only in "
        "evidence_labels and must not appear in visible text. Address every must_state item "
        "explicitly. If evidence directly supports only a bounded subset of a broad "
        "question, prefer status partial with only those supported parts and list the "
        "unsupported dimensions. Abstain when no responsive material claim can be "
        "grounded. Never invent missing categories."
    )
    max_tokens = _compact_provider_output_tokens(
        question=question,
        intent_class=intent_class,
        packed_evidence=packed,
        requirements=requirements,
        repair=repair,
        previous_failures=previous_failures,
    )
    return (
        {
            "model": "MiniMax-M3",
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "system": system,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        task,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
        },
        label_map,
        snippet_map,
    )


def _compact_provider_output_tokens(
    *,
    question: str,
    intent_class: str,
    packed_evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[SemanticRequirement],
    repair: bool,
    previous_failures: Sequence[str],
) -> int:
    evidence_chars = sum(len(str(item.get("text", ""))) for item in packed_evidence)
    requirement_count = len(requirements)
    question_chars = len(str(question))
    relational_bonus = 192 if intent_class in legacy.RELATIONAL_INTENTS else 0
    base = (
        MIN_PROVIDER_OUTPUT_TOKENS
        + min(640, evidence_chars // 8)
        + min(320, question_chars // 4)
        + min(384, requirement_count * 48)
        + relational_bonus
    )
    if repair:
        base = max(int(base * 1.35), MIN_PROVIDER_REPAIR_OUTPUT_TOKENS)
    if COMPACT_PROVIDER_TRUNCATED in set(str(item) for item in previous_failures):
        base += 384
    elif COMPACT_PROVIDER_PARSE_FAILED in set(str(item) for item in previous_failures):
        base += 192
    return max(
        MIN_PROVIDER_REPAIR_OUTPUT_TOKENS if repair else MIN_PROVIDER_OUTPUT_TOKENS,
        min(MAX_PROVIDER_OUTPUT_TOKENS, base),
    )


def _semantic_review_payload(
    *,
    question: str,
    intent_class: str,
    candidate: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    evidence_by_id = {str(item.get("evidence_id", "")): item for item in evidence}
    claim_cases: list[dict[str, Any]] = []
    for raw_claim in legacy._list(candidate.get("claims"), "semantic review claims"):
        claim = legacy._object(raw_claim, "semantic review claim")
        local_evidence: list[dict[str, Any]] = []
        for raw_ref in legacy._list(
            claim.get("support_refs"), "semantic review support refs"
        ):
            ref = legacy._object(raw_ref, "semantic review support ref")
            evidence_id = str(ref.get("evidence_id", ""))
            item = evidence_by_id.get(evidence_id, {})
            graph_fact = {}
            if item.get("evidence_type") == "graph_edge":
                graph_fact = {
                    "edge_id": str(item.get("edge_id", "")),
                    "edge_source": str(item.get("edge_source", "")),
                    "edge_target": str(item.get("edge_target", "")),
                    "edge_source_label": str(item.get("edge_source_label", "")),
                    "edge_target_label": str(item.get("edge_target_label", "")),
                    "relation_type": str(item.get("relation_type", "")),
                    "provenance": "graph_artifact_fact",
                    "relation_metadata": dict(item.get("relation_metadata", {}))
                    if isinstance(item.get("relation_metadata"), Mapping)
                    else legacy._graph_relation_metadata(
                        str(item.get("relation_type", ""))
                    ),
                }
            local_evidence.append(
                {
                    "evidence_label": f"local_{len(local_evidence) + 1}",
                    "evidence_id": evidence_id,
                    "locator_id": str(ref.get("locator_id", "")),
                    "evidence_type": str(item.get("evidence_type", "passage")),
                    "source_identity": str(
                        item.get("source_identity") or item.get("source_id") or ""
                    ),
                    "text": str(ref.get("exact_quote", "")),
                    "graph_fact": graph_fact,
                }
            )
        allowed_evidence_ids = [
            str(item.get("evidence_id", "")) for item in local_evidence
        ]
        allowed_evidence_labels = [
            str(item.get("evidence_label", "")) for item in local_evidence
        ]
        claim_cases.append(
            {
                "claim_id": str(claim.get("claim_id", "")),
                "claim_type": str(claim.get("claim_type", "")),
                "surface_text": str(claim.get("surface_text", "")),
                "allowed_evidence_ids": allowed_evidence_ids,
                "allowed_evidence_labels": allowed_evidence_labels,
                "evidence_id_by_label": dict(
                    zip(allowed_evidence_labels, allowed_evidence_ids, strict=False)
                ),
                "evidence": local_evidence,
            }
        )
    task = {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "question_context": question,
        "intent_class": intent_class,
        "answer_text": str(candidate.get("answer_text", "")),
        "claim_cases": claim_cases,
        "review_protocol": {
            "evidence_ids_rule": (
                "For an ENTAILED judgment, evidence_ids must contain only either "
                "exact evidence_id strings from that claim case's allowed_evidence_ids "
                "or exact claim-local labels from allowed_evidence_labels. Claim-local "
                "labels are aliases for that same case's evidence_id_by_label entries. "
                "Unknown or cross-claim IDs or labels are invalid."
            ),
            "model_explanation_rule": (
                "If claim_type is MODEL_EXPLANATION and the claim case has no local "
                "evidence, use verdict GENERIC_EXPLANATION with evidence_ids []. Do "
                "not use ENTAILED for a claim with no local evidence."
            ),
            "visible_coverage_rule": (
                "Visible coverage concerns material KB-dependent assertions in "
                "answer_text. Do not mark coverage UNCOVERED merely because a visible "
                "generic glue statement is represented by a MODEL_EXPLANATION claim."
            ),
        },
        "output": {
            "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
            "claim_judgments": [
                {
                    "claim_id": "claim_1",
                    "verdict": "ENTAILED|CONTRADICTED|INSUFFICIENT|GENERIC_EXPLANATION",
                    "evidence_ids": [],
                }
            ],
            "visible_coverage": {
                "verdict": "COVERED|UNCOVERED",
                "uncovered_assertions": [],
            },
        },
    }
    system = (
        "You are the bounded M26 claim semantic-entailment reviewer. Return exactly one "
        "JSON object. Judge each claim's meaning against only that claim case's local "
        "evidence array. The user question, other claim surfaces, and other claim cases "
        "are context only and are not evidence. Paraphrase, voice, and order changes may "
        "be entailed; contradiction, strengthening, identity, quantity, time, causality, "
        "polarity, graph direction, or endpoint mutation is not entailed. Also report "
        "whether every material KB-dependent assertion visible in answer_text is covered "
        "by a structured claim. For each ENTAILED judgment, evidence_ids must be an array "
        "of exact evidence_id strings from that claim case's allowed_evidence_ids, or exact "
        "claim-local labels from that claim case's allowed_evidence_labels. "
        "If claim_type is MODEL_EXPLANATION and the claim case has no local evidence, "
        "return verdict GENERIC_EXPLANATION with evidence_ids []. "
        "If no allowed local evidence entails the claim, use INSUFFICIENT or CONTRADICTED "
        "instead of ENTAILED. Do not invent claim IDs, evidence IDs, or evidence labels; "
        "never output example labels unless that exact string is present in the claim case. "
        "For visible_coverage, only list material KB-dependent assertions that are not "
        "represented by any structured claim; a listed MODEL_EXPLANATION glue claim is "
        "not by itself an uncovered assertion."
    )
    return {
        "model": "MiniMax-M3",
        "max_tokens": 2048,
        "temperature": 0,
        "stream": False,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(task, ensure_ascii=False, separators=(",", ":")),
            }
        ],
    }


def _parse_semantic_review_result(text: str) -> dict[str, Any]:
    stripped = str(text).strip()
    if not stripped:
        raise ValueError("semantic review output is empty")
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
    stripped = re.sub(r"\s*```$", "", stripped)
    value, end = json.JSONDecoder().raw_decode(stripped)
    if stripped[end:].strip():
        raise ValueError("semantic review output contains trailing text")
    if not isinstance(value, Mapping):
        raise ValueError("semantic review JSON must be an object")
    return dict(value)


def _semantic_review_blocking_failures(review: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for raw_judgment in legacy._list(
        review.get("claim_judgments"), "semantic review claim judgments"
    ):
        judgment = legacy._object(raw_judgment, "semantic review claim judgment")
        verdict = str(judgment.get("verdict", ""))
        if verdict in legacy.SEMANTIC_REVIEW_BLOCKING_VERDICTS:
            failures.append(
                "SEMANTIC_REVIEW_BLOCKED:"
                + str(judgment.get("claim_id", ""))
                + ":"
                + verdict
            )
    coverage = review.get("visible_coverage")
    if not isinstance(coverage, Mapping) or coverage.get("verdict") != "COVERED":
        failures.append("SEMANTIC_REVIEW_VISIBLE_COVERAGE_FAILED")
    return failures


def _call_semantic_entailment_review(
    *,
    provider_client: ProviderClient,
    question: str,
    intent_class: str,
    candidate: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = provider_client.call(
        _semantic_review_payload(
            question=question,
            intent_class=intent_class,
            candidate=candidate,
            evidence=evidence,
        ),
        SEMANTIC_REVIEW_CALL_CLASS,
    )
    review = _parse_semantic_review_result(
        str(raw.get("text", raw.get("provider_text", "")))
    )
    if review.get("schema_version") != SEMANTIC_REVIEW_SCHEMA_VERSION:
        raise ValueError(SEMANTIC_REVIEW_PARSE_FAILED)
    return review, {**dict(raw), "call_class": SEMANTIC_REVIEW_CALL_CLASS}


def _validate_provider_segments(raw_segments: Sequence[Any]) -> None:
    seen_segment_ids: set[str] = set()
    seen_claim_ids: set[str] = set()
    seen_texts: set[str] = set()
    for index, raw_segment in enumerate(raw_segments, start=1):
        if not isinstance(raw_segment, Mapping):
            raise ValueError("compact provider segment must be object")
        segment = dict(raw_segment)
        if "surface_text" in segment:
            raise ValueError("compact provider segment must not include surface_text")
        if "answer_text" in segment:
            raise ValueError("compact provider segment must not include answer_text")
        segment_id = str(segment.get("segment_id") or "").strip()
        if not segment_id:
            raise ValueError(f"provider segment {index} missing segment_id")
        if segment_id in seen_segment_ids:
            raise ValueError("provider segment_id duplicated")
        seen_segment_ids.add(segment_id)
        role = str(segment.get("semantic_role") or "").strip()
        if role not in SEMANTIC_SEGMENT_ROLES:
            raise ValueError(f"provider segment {segment_id} has invalid semantic_role")
        text = str(segment.get("text") or "").strip()
        if not text:
            raise ValueError(f"provider segment {segment_id} missing text")
        if legacy.CLAIM_ANCHOR_RE.search(text):
            raise ValueError("provider segment text contains inline claim anchor")
        if text in seen_texts:
            raise ValueError("provider segment text duplicated")
        seen_texts.add(text)
        claim_id = str(segment.get("claim_id") or "").strip()
        if not claim_id:
            raise ValueError(f"provider segment {segment_id} missing claim_id")
        if claim_id in seen_claim_ids:
            raise ValueError("provider claim_id duplicated")
        seen_claim_ids.add(claim_id)
        claim_type = str(segment.get("claim_type") or "").strip()
        if role == "material_claim":
            if claim_type not in {"EVIDENCE_FACT", "EVIDENCE_SYNTHESIS"}:
                raise ValueError(
                    f"provider segment {segment_id} has invalid claim_type"
                )
        else:
            if claim_type != "MODEL_EXPLANATION":
                raise ValueError(
                    f"provider segment {segment_id} has invalid model explanation type"
                )
        raw_evidence_labels = segment.get("evidence_labels", [])
        if raw_evidence_labels is None:
            raw_evidence_labels = []
        if not isinstance(raw_evidence_labels, list):
            raise ValueError(
                f"provider segment {segment_id} has invalid claim-local evidence labels"
            )
        evidence_labels = [
            str(label).strip() for label in raw_evidence_labels if str(label).strip()
        ]
        if role == "material_claim" and not evidence_labels:
            raise ValueError(
                f"provider segment {segment_id} missing claim-local evidence labels"
            )
        if role == "model_explanation" and evidence_labels:
            raise ValueError(
                f"provider segment {segment_id} model explanation has evidence labels"
            )
        raw_covers = segment.get("covers", [])
        if raw_covers is not None and not isinstance(raw_covers, list):
            raise ValueError(f"provider segment {segment_id} covers must be list")


def _decode_compact_provider_value(text: str) -> dict[str, Any]:
    stripped = str(text).strip()
    if not stripped:
        raise ValueError("compact provider output is empty")
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    if start < 0:
        raise ValueError("compact provider JSON missing")
    value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    if not isinstance(value, Mapping):
        raise ValueError("compact provider JSON must be an object")
    return dict(value)


def _parse_compact_provider_result(text: str) -> dict[str, Any]:
    value = _decode_compact_provider_value(text)
    allowed_keys = {
        "status",
        "schema_version",
        "segments",
        "unanswered_dimensions",
        "abstention_reason",
    }
    if set(value) - allowed_keys:
        raise ValueError("compact provider JSON has unknown keys")
    status = str(value.get("status", ""))
    if status not in {"answer", "partial", "abstain", "answer_candidate", "partial_candidate"}:
        raise ValueError("compact provider status invalid")
    if value.get("schema_version") != COMPACT_CLOSURE_SCHEMA_VERSION:
        raise ValueError("compact provider schema_version invalid")
    raw_segments = value.get("segments", [])
    if raw_segments is None:
        raw_segments = []
    if not isinstance(raw_segments, list):
        raise ValueError("compact provider segments must be list")
    if status != "abstain" and not raw_segments:
        raise ValueError("compact provider segments required")
    _validate_provider_segments(raw_segments)
    answer_text = _visible_answer_from_segments(
        [dict(item) for item in raw_segments if isinstance(item, Mapping)]
    )
    if status != "abstain" and (
        not answer_text.strip() or len(answer_text) > MAX_PROVIDER_ANSWER_CHARS
    ):
        raise ValueError("compact provider answer invalid")
    raw_unanswered = value.get("unanswered_dimensions")
    if raw_unanswered is not None and not isinstance(raw_unanswered, list):
        raise ValueError("compact provider unanswered_dimensions must be list")
    return dict(value)


def _salvage_compact_provider_surplus_segments(
    text: str,
    *,
    label_map: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        value = _decode_compact_provider_value(text)
    except ValueError:
        return None
    allowed_keys = {
        "status",
        "schema_version",
        "segments",
        "unanswered_dimensions",
        "abstention_reason",
    }
    if set(value) - allowed_keys:
        return None
    status = str(value.get("status", ""))
    if status not in {"answer", "partial", "answer_candidate", "partial_candidate"}:
        return None
    if value.get("schema_version") != COMPACT_CLOSURE_SCHEMA_VERSION:
        return None
    raw_segments = value.get("segments", [])
    if raw_segments is None or not isinstance(raw_segments, list) or not raw_segments:
        return None
    raw_unanswered = value.get("unanswered_dimensions")
    if raw_unanswered is not None and not isinstance(raw_unanswered, list):
        return None

    known_labels = {str(label) for label in label_map}
    retained_segments: list[dict[str, Any]] = []
    dropped_segments: list[dict[str, Any]] = []
    seen_segment_ids: set[str] = set()
    seen_claim_ids: set[str] = set()
    seen_texts: set[str] = set()
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            return None
        segment = dict(raw_segment)
        if "surface_text" in segment or "answer_text" in segment:
            return None
        segment_id = str(segment.get("segment_id") or "").strip()
        if not segment_id or segment_id in seen_segment_ids:
            return None
        seen_segment_ids.add(segment_id)
        role = str(segment.get("semantic_role") or "").strip()
        if role not in SEMANTIC_SEGMENT_ROLES:
            return None
        segment_text = str(segment.get("text") or "").strip()
        if not segment_text or segment_text in seen_texts:
            return None
        if legacy.CLAIM_ANCHOR_RE.search(segment_text):
            return None
        seen_texts.add(segment_text)
        claim_id = str(segment.get("claim_id") or "").strip()
        if not claim_id or claim_id in seen_claim_ids:
            return None
        seen_claim_ids.add(claim_id)
        claim_type = str(segment.get("claim_type") or "").strip()
        if role == "material_claim":
            if claim_type not in {"EVIDENCE_FACT", "EVIDENCE_SYNTHESIS"}:
                return None
        elif claim_type != "MODEL_EXPLANATION":
            return None
        raw_evidence_labels = segment.get("evidence_labels", [])
        if raw_evidence_labels is None:
            raw_evidence_labels = []
        if not isinstance(raw_evidence_labels, list):
            return None
        evidence_labels = [
            str(label).strip() for label in raw_evidence_labels if str(label).strip()
        ]
        if role == "model_explanation":
            if evidence_labels:
                return None
        elif not evidence_labels:
            dropped_segments.append(segment)
            continue
        elif any(label not in known_labels for label in evidence_labels):
            return None
        raw_covers = segment.get("covers", [])
        if raw_covers is not None and not isinstance(raw_covers, list):
            return None
        retained_segments.append(segment)

    if not dropped_segments:
        return None
    if not any(
        str(segment.get("semantic_role") or "").strip() == "material_claim"
        for segment in retained_segments
    ):
        return None
    try:
        _validate_provider_segments(retained_segments)
    except ValueError:
        return None
    answer_text = _visible_answer_from_segments(retained_segments)
    if not answer_text.strip() or len(answer_text) > MAX_PROVIDER_ANSWER_CHARS:
        return None
    return (
        {**dict(value), "segments": retained_segments},
        {
            "deterministic_surplus_pruning_used": True,
            "dropped_segment_count": len(dropped_segments),
            "dropped_segment_ids": [
                str(segment.get("segment_id", "")).strip()
                for segment in dropped_segments
            ],
            "retained_segment_count": len(retained_segments),
        },
    )


def _compact_call_telemetry(
    result: Mapping[str, Any],
    *,
    parse_ok: bool,
    parse_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
    stop_reason = str(result.get("stop_reason") or result.get("finish_reason") or "")
    return {
        "provider_text": "",
        "provider_text_char_count": len(
            str(result.get("text", result.get("provider_text", "")))
        ),
        "call_class": str(result.get("call_class", "")),
        "stop_reason": stop_reason,
        "truncation_detected": stop_reason == "max_tokens",
        "content_block_types": [
            str(item) for item in result.get("content_block_types", [])
        ],
        "parse_telemetry": {
            "parse_ok": parse_ok,
            "parse_subtype": (
                "compact_semantic_closure_json" if parse_ok else "invalid"
            ),
            **dict(parse_meta or {}),
        },
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(
                usage.get(
                    "total_tokens",
                    int(usage.get("input_tokens", 0))
                    + int(usage.get("output_tokens", 0)),
                )
            ),
        },
        "cost_usd": str(result.get("cost_usd", "0")),
        "latency_ms": int(result.get("latency_ms", 0)),
        "response_id_sha256": canonical_sha256(
            str(result.get("response_id", ""))
        ),
    }


def _claims_from_segments(
    segments: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    source_segments = list(segments or [])
    _validate_provider_segments(source_segments)
    claims: list[dict[str, Any]] = []
    for raw_segment in source_segments:
        segment = dict(raw_segment)
        role = str(segment.get("semantic_role", "")).strip()
        claim_type = str(segment.get("claim_type", "")).strip()
        claims.append(
            {
                "segment_id": str(segment.get("segment_id", "")).strip(),
                "semantic_role": role,
                "claim_id": str(segment.get("claim_id", "")).strip(),
                "claim_type": claim_type,
                "surface_text": str(segment.get("text", "")).strip(),
                "evidence_labels": [
                    str(label).strip()
                    for label in legacy._list(
                        segment.get("evidence_labels", []),
                        "segment evidence labels",
                    )
                    if str(label).strip()
                ],
                "covers": [
                    str(item)
                    for item in legacy._list(
                        segment.get("covers", []), "segment covers"
                    )
                    if str(item)
                ],
                "claim_role": (
                    "model_explanation"
                    if role == "model_explanation"
                    else str(segment.get("claim_role", "")).strip()
                ),
                "support_mode": (
                    "model_explanation"
                    if role == "model_explanation"
                    else str(segment.get("support_mode", "")).strip()
                ),
                "unanswered_dimensions": [
                    str(item)
                    for item in legacy._list(
                        segment.get("unanswered_dimensions", []),
                        "segment unanswered dimensions",
                    )
                    if str(item)
                ],
            }
        )
    return claims


def _runtime_bound_candidate(
    *,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]] | None,
    label_map: Mapping[str, Mapping[str, Any]],
    snippet_map: Mapping[str, str],
    segments: Sequence[Mapping[str, Any]] | None = None,
    provider_status: str = "answer",
    requirements: Sequence[SemanticRequirement] = (),
    unanswered_dimensions: Sequence[str] = (),
    semantic_failures: Sequence[str] = (),
) -> dict[str, Any]:
    del used_items
    relation: str | None = None
    source_claims = (
        _claims_from_segments(segments)
        if segments is not None
        else list(claims or [])
    )
    if not source_claims:
        raise ValueError("provider structured claims required for publication")
    selected_items: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()

    def remember_selected(item: Mapping[str, Any]) -> None:
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in selected_ids:
            selected_items.append(item)
            selected_ids.add(evidence_id)

    if intent_class == "cross_document_comparison":
        relation = "contrasts_with"
    elif intent_class == "complementary_synthesis":
        relation = "complements"
    elif intent_class == "temporal_conflict":
        relation = "precedes"
    claim_records: list[dict[str, Any]] = []
    for index, raw_claim in enumerate(source_claims, start=1):
        claim = dict(raw_claim)
        claim_id = str(claim.get("claim_id") or "").strip()
        if not claim_id:
            raise ValueError(f"provider claim {index} missing claim_id")
        surface_text = str(claim.get("surface_text") or "").strip()
        if not surface_text:
            raise ValueError(f"provider claim {claim_id} missing surface_text")
        claim_type = str(claim.get("claim_type") or "").strip()
        if claim_type not in {
            "EVIDENCE_FACT",
            "EVIDENCE_SYNTHESIS",
            "MODEL_EXPLANATION",
        }:
            raise ValueError(f"provider claim {claim_id} has invalid claim_type")
        raw_evidence_labels = claim.get("evidence_labels", [])
        if raw_evidence_labels is None:
            raw_evidence_labels = []
        if not isinstance(raw_evidence_labels, list):
            raise ValueError(
                f"provider claim {claim_id} has invalid claim-local evidence labels"
            )
        evidence_labels = [str(label) for label in raw_evidence_labels if str(label)]
        if claim_type == "MODEL_EXPLANATION":
            support_items = []
        else:
            if not evidence_labels:
                raise ValueError(
                    f"provider claim {claim_id} missing claim-local evidence labels"
                )
            unknown_labels = [
                label for label in evidence_labels if label not in label_map
            ]
            if unknown_labels:
                raise ValueError(
                    f"provider claim {claim_id} has unknown evidence labels"
                )
            support_items = [label_map[label] for label in evidence_labels]
            for item in support_items:
                remember_selected(item)
        refs: list[dict[str, Any]] = []
        for _ref_index, item in enumerate(support_items, start=1):
            evidence_id = str(item.get("evidence_id", ""))
            quote = snippet_map.get(evidence_id) or legacy._first_exact_evidence_quote(
                str(item.get("passage_text", "")), max_chars=360
            )
            if not quote:
                continue
            refs.append(
                {
                    "evidence_id": evidence_id,
                    "locator_id": str(item.get("locator_id", "")),
                    "exact_quote": quote,
                    "uncertainty": "low",
                }
            )
        if not refs and claim_type != "MODEL_EXPLANATION":
            raise ValueError("runtime could not bind provider prose to evidence")
        claim_role = str(
            claim.get("claim_role")
            or _infer_claim_role(intent_class=intent_class, claim_type=claim_type)
        )
        facet_ids = list(
            claim.get("covers")
            or claim.get("facet_ids")
            or legacy._required_facet_ids(
                question=question,
                intent_class=intent_class,
            )
        )
        required_facet_ids = legacy._required_facet_ids(
            question=question,
            intent_class=intent_class,
        )
        if claim_type == "MODEL_EXPLANATION" and not (set(facet_ids) & set(required_facet_ids)):
            facet_ids = required_facet_ids
        claim_records.append(
            {
                "claim_id": claim_id,
                "claim_type": claim_type,
                "claim_role": claim_role,
                "surface_text": surface_text,
                "facet_ids": facet_ids,
                "support_mode": str(
                    claim.get("support_mode")
                    or ("model_explanation" if claim_type == "MODEL_EXPLANATION" else "exact_quote")
                ),
                "evidence_labels": evidence_labels,
                "covers": list(claim.get("covers", [])),
                "unanswered_dimensions": list(claim.get("unanswered_dimensions", [])),
                "support_refs": refs,
            }
        )
    if intent_class == "graph_relationship":
        edge = next(
            (
                item
                for item in selected_items
                if item.get("evidence_type") == "graph_edge"
            ),
            None,
        )
        relation = str(edge.get("relation_type", "")) if edge is not None else None
    if provider_status in {"partial", "partial_candidate"}:
        missing = _partial_missing_dimension_labels(
            requirements=requirements,
            unanswered_dimensions=unanswered_dimensions,
            semantic_failures=semantic_failures,
        )
        if missing:
            unanswered_dimensions = list(
                dict.fromkeys([*unanswered_dimensions, *missing])
            )
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": (
            "partial_candidate"
            if provider_status in {"partial", "partial_candidate"}
            else "answer_candidate"
        ),
        "relation": relation,
        "selected_evidence_ids": [
            str(item.get("evidence_id", "")) for item in selected_items
        ],
        "answer_text": answer.strip(),
        "claims": claim_records,
        "missing_facets": [],
        "abstention_reason": None,
        "unanswered_dimensions": [
            str(item)
            for item in [
                *unanswered_dimensions,
                *[
                    claim_item
                    for claim in claim_records
                    for claim_item in legacy._list(
                        claim.get("unanswered_dimensions", []),
                        "unanswered dimensions",
                    )
                ],
            ]
            if str(item)
        ],
    }


def _parsed_provider_segments(parsed: Mapping[str, Any]) -> list[dict[str, Any]]:
    segments = parsed.get("segments", [])
    return [
        dict(item)
        for item in segments
        if isinstance(item, Mapping)
    ]


def _visible_answer_from_segments(segments: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if str(segment.get("text", "")).strip()
    ).strip()


def _parsed_provider_unanswered_dimensions(
    parsed: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
) -> list[str]:
    values: list[str] = []
    raw_unanswered = parsed.get("unanswered_dimensions", [])
    if isinstance(raw_unanswered, Sequence) and not isinstance(raw_unanswered, (str, bytes)):
        values.extend(str(item) for item in raw_unanswered if str(item))
    for segment in segments:
        raw_segment_unanswered = segment.get("unanswered_dimensions", [])
        if isinstance(raw_segment_unanswered, Sequence) and not isinstance(
            raw_segment_unanswered, (str, bytes)
        ):
            values.extend(str(item) for item in raw_segment_unanswered if str(item))
    return list(dict.fromkeys(values))


def _partial_answer_has_substantial_value(
    *,
    answer: str,
    requirements: Sequence[SemanticRequirement],
    visible_failures: Sequence[str],
    support_failures: Sequence[str],
    used_items: Sequence[Mapping[str, Any]],
) -> bool:
    if not answer.strip() or not used_items:
        return False
    if not requirements:
        return False
    missing_visible = _missing_requirement_ids(visible_failures)
    missing_support = _missing_requirement_ids(support_failures)
    failed = missing_visible | missing_support
    covered = {item.requirement_id for item in requirements} - failed
    return bool(covered)


def _missing_requirement_ids(failures: Sequence[str]) -> set[str]:
    ids = set()
    for failure in failures:
        if ":" not in str(failure):
            continue
        ids.add(str(failure).split(":", 1)[1])
    return ids


def _partial_missing_dimension_labels(
    *,
    requirements: Sequence[SemanticRequirement],
    unanswered_dimensions: Sequence[str],
    semantic_failures: Sequence[str],
) -> list[str]:
    by_id = {item.requirement_id: item for item in requirements}
    labels: list[str] = []
    for item in unanswered_dimensions:
        value = str(item).strip()
        if value:
            labels.append(value)
    for requirement_id in sorted(_missing_requirement_ids(semantic_failures)):
        requirement = by_id.get(requirement_id)
        labels.append(requirement.requirement_id if requirement else requirement_id)
    return list(dict.fromkeys(labels))


def _infer_claim_role(*, intent_class: str, claim_type: str) -> str:
    if claim_type == "MODEL_EXPLANATION":
        return "model_explanation"
    if intent_class == "cross_document_comparison":
        return "comparison"
    if intent_class == "complementary_synthesis":
        return "relationship"
    if intent_class == "graph_relationship":
        return "relationship"
    if intent_class == "temporal_conflict":
        return "temporal"
    return "direct"


def _infer_claim_type(intent_class: str, claim: Mapping[str, Any]) -> str:
    claim_type = str(claim.get("claim_type") or claim.get("material_claim_type") or "").strip()
    if claim_type:
        return claim_type
    claim_role = str(claim.get("claim_role") or "").strip()
    if claim_role in {"relationship", "comparison", "temporal"}:
        return "EVIDENCE_SYNTHESIS"
    if claim.get("support_mode") == "model_explanation":
        return "MODEL_EXPLANATION"
    if intent_class in {"cross_document_comparison", "complementary_synthesis", "graph_relationship", "temporal_conflict"}:
        return "EVIDENCE_SYNTHESIS"
    return "EVIDENCE_FACT"


def _semantic_requirements(
    question: str, intent_class: str
) -> list[SemanticRequirement]:
    q = question.casefold()
    requirements: list[SemanticRequirement] = []
    seen: set[str] = set()

    def add(
        requirement_id: str,
        instruction: str,
        evidence_terms: Sequence[str],
        visible_patterns: Sequence[str],
        *,
        exact_phrase: str = "",
    ) -> None:
        if requirement_id in seen:
            return
        seen.add(requirement_id)
        requirements.append(
            SemanticRequirement(
                requirement_id=requirement_id,
                instruction=instruction,
                evidence_terms=tuple(evidence_terms),
                visible_patterns=tuple(visible_patterns),
                exact_phrase=exact_phrase,
            )
        )

    for entity in legacy._named_question_entities(question):
        entity_id = legacy._facet_id_for_term(entity)
        add(
            f"entity_{entity_id}",
            f"Name and address {entity} explicitly.",
            [entity],
            [re.escape(entity)],
            exact_phrase=entity,
        )

    if "production router" in q or (
        "router" in q
        and any(word in q for word in ("path", "downstream", "route"))
    ):
        add(
            "router_decision",
            "Explain what the router inspects and how that selects a downstream route/path.",
            ["router", "query", "path", "route", "capability"],
            [
                r"router.{0,100}(?:path|route|select|choose)",
                r"(?:path|route).{0,100}router",
            ],
        )
        add(
            "routing_constraints",
            (
                "State at least one permission/safety/policy/cost/latency/capability "
                "constraint on routing."
            ),
            [
                "permission",
                "safety",
                "policy",
                "risk",
                "cost",
                "latency",
                "capability",
                "guardrail",
            ],
            [
                r"\b(?:permission|safety|policy|risk|cost|latency|capability|guardrail)s?\b"
            ],
        )

    if "client disconnect" in q or "admission to completion" in q:
        add(
            "admission_policy",
            "Cover request admission/effective policy before execution.",
            ["admission", "request boundary", "effective policy", "task contract"],
            [r"\b(?:admission|request boundary|effective policy|task contract)\b"],
        )
        add(
            "durable_state",
            (
                "Cover durable/persisted server-side run authority or state after "
                "disconnect."
            ),
            ["durable", "persisted", "state", "authority", "disconnect"],
            [
                r"\b(?:durable|persisted|server-side).{0,80}(?:state|authority|run)",
                r"\bstate.{0,80}(?:durable|persisted|authority)\b",
            ],
        )
        add(
            "completion_verification",
            "Cover verification/completion acceptance before declaring success.",
            ["verification", "completion", "acceptance", "terminal"],
            [r"\b(?:verification|completion|acceptance|terminal gate)\b"],
        )
        add(
            "observability",
            (
            "Cover observability/status/reattachment for the headless continuing "
            "run."
        ),
            ["observability", "status", "reattach", "headless", "resume"],
            [r"\b(?:observability|reattach|headless|status|resume)\b"],
        )
    elif (
        ("durable" in q or "persisted" in q or "run state" in q)
        and (
            "verification" in q
            or "verified" in q
            or "post-execution" in q
            or "completion" in q
        )
    ):
        add(
            "durable_state",
            (
                "Cover durable/persisted server-side run authority or state after "
                "interruption."
            ),
            ["durable", "persisted", "state", "authority", "disconnect", "interruption"],
            [
                r"\b(?:durable|persisted|server-side).{0,80}(?:state|authority|run)",
                r"\bstate.{0,80}(?:durable|persisted|authority)\b",
            ],
        )
        add(
            "completion_verification",
            "Cover verification/completion acceptance before declaring success.",
            ["verification", "completion", "acceptance", "terminal", "correctness"],
            [r"\b(?:verification|completion|acceptance|terminal gate|correctness)\b"],
        )
    if (
        "venture" in q
        and "product" in q
        and any(term in q for term in ("operations", "resources", "team", "finance", "risk"))
    ):
        add(
            "venture_not_product",
            "Explain that a venture is broader than the product alone.",
            ["venture", "product", "system"],
            [r"\b(?:venture|system).{0,120}(?:product|operations|resources|team|finance|risk)"],
        )
        add(
            "operations_system",
            "Cover operations as part of the venture system.",
            ["operations", "operation", "delivery"],
            [r"\boperations?\b"],
        )
        add(
            "venture_resources",
            "Cover resources as part of the venture system.",
            ["resources", "resource", "runway"],
            [r"\b(?:resources?|runway)\b"],
        )
        add(
            "team_capacity",
            "Cover team capacity as part of the venture system.",
            ["team", "people"],
            [r"\b(?:team|people)\b"],
        )
        add(
            "finance_model",
            "Cover finance as part of the venture system.",
            ["finance", "financial", "margin", "cash", "runway"],
            [r"\b(?:finance|financial|margin|cash|runway)\b"],
        )
        add(
            "risk_management",
            "Cover risk as part of the venture system.",
            ["risk", "risks"],
            [r"\brisks?\b"],
        )
    if (
        any(term in q for term in ("pain point", "pain", "痛點"))
        and any(term in q for term in ("adopt", "adoption", "change", "願意改變", "願意採用", "市場"))
    ):
        add(
            "pain_acknowledgement",
            "Separate pain acknowledgement from adoption willingness.",
            ["pain", "problem", "pain point", "痛點"],
            [r"\b(?:pain point|pain|problem|痛點)\b"],
        )
        add(
            "change_willingness",
            "Cover willingness to change or adopt.",
            ["willing", "change", "adopt", "adoption", "改變", "採用"],
            [r"\b(?:willing|change|adopt|adoption|改變|採用)\b"],
        )
        add(
            "adoption_conditions",
            "Cover adoption conditions, cost, trust, workflow, or risk.",
            ["cost", "trust", "risk", "workflow", "conditions", "條件"],
            [r"\b(?:cost|trust|risk|workflow|conditions?|條件)\b"],
        )
        add(
            "market_movement",
            "Cover market or customer movement.",
            ["market", "customer", "hospitality", "hotel", "市場", "旅宿"],
            [r"\b(?:market|customer|hospitality|hotel|市場|旅宿)\b"],
        )
    if (
        any(term in q for term in ("changes direction", "changed in the problem", "founder drift", "aimless"))
        and any(term in q for term in ("problem", "constraint", "market reality"))
    ):
        add(
            "problem_evidence_changed",
            "Focus on how the problem evidence changed rather than the pitch deck.",
            ["problem", "evidence", "learning"],
            [r"\b(?:problem|evidence|learning|pitch deck)\b"],
        )
        add(
            "constraint_change",
            "Cover changed constraints such as runway, timing, or resources.",
            ["constraint", "constraints", "runway", "resource", "timing"],
            [r"\b(?:constraint|constraints|runway|resource|timing)\b"],
        )
        add(
            "market_reality_change",
            "Cover changes in market reality or customer adoption.",
            ["market", "reality", "customer", "adoption"],
            [r"\b(?:market|reality|customer|adoption)\b"],
        )
        add(
            "drift_boundary",
            "Separate evidence-driven learning from aimless founder drift.",
            ["drift", "aimless", "direction", "change"],
            [r"\b(?:drift|aimless|direction|change)\b"],
        )

    if (
        "where a request should go" in q and "remaining work" in q
    ) or (
        intent_class == "cross_document_comparison"
        and "adaptive" in q
        and "router" in q
    ):
        add(
            "initial_routing_role",
            "Explain that routing chooses the initial path/capability for the request.",
            ["router", "route", "initial", "path", "request"],
            [r"\b(?:router|routing).{0,100}(?:initial|path|route|request|capability)"],
        )
        add(
            "replanning_role",
            (
                "Explain that adaptive replanning changes remaining work after evidence "
                "invalidates the plan."
            ),
            ["adaptive", "replan", "remaining", "invalid", "assumption", "evidence"],
            [
                r"\b(?:replan|replanning|adaptive).{0,120}(?:remaining|invalid|assumption|evidence|reality)"
            ],
        )
        add(
            "role_contrast",
            "Contrast initial dispatch with later replanning rather than conflating them.",
            ["initial", "later", "after", "different"],
            [
                r"\b(?:whereas|while|by contrast|different|initial).{0,160}(?:later|after|replan|remaining)"
            ],
        )

    if "query router" in q and "dag" in q:
        add(
            "router_role",
            "State that the query router selects the path/mode/capability.",
            ["query router", "route", "path", "mode", "capability"],
            [r"query router.{0,120}(?:path|route|mode|capability|select)"],
        )
        add(
            "dag_role",
            (
                "State that the DAG structures dependency/parallel multi-step work "
                "inside the chosen path."
            ),
            ["dag", "dependency", "parallel", "task", "step"],
            [r"\bdag\b.{0,140}(?:depend|parallel|task|step|work)"],
        )
        add(
            "router_dag_composition",
            "Explain how router selection and DAG execution compose in the same flow.",
            ["together", "within", "then", "chosen path", "flow"],
            [
                r"(?:router|route).{0,180}(?:dag|within|then|flow)",
                r"dag.{0,180}(?:router|route|chosen path|flow)",
            ],
        )

    if "precedes" in q:
        add(
            "ordering_semantics",
            "State that precedes supports ordering/sequence/navigation only.",
            ["precedes", "ordering", "sequence", "navigation"],
            [r"\b(?:ordering|sequence|navigation|comes before|precedes)\b"],
        )
        if re.search(
            r"\b(?:prove|infer|depend|dependency|require|causal|cause)\b", q
        ):
            add(
                "non_entailment",
                (
                    "Explicitly state that precedes alone does not prove dependency, "
                    "causality, implementation, or requirement."
                ),
                ["dependency", "causality", "implementation", "requirement"],
                [
                    r"\b(?:does not|doesn't|cannot|can't|not enough|only).{0,120}(?:depend|causal|implement|require|prove|infer)",
                    r"\b(?:depend|causal|implement|require).{0,100}(?:not|does not|cannot|isn't)\b",
                ],
            )

    if "state machine" in q and (
        "adaptive replanning" in q or "replanner" in q or "replan" in q
    ):
        add(
            "state_machine_authority",
            (
                "Explain the state machine as the legal transition/permission/approval "
                "envelope."
            ),
            ["state machine", "legal transition", "permission", "approval", "guard"],
            [r"state machine.{0,160}(?:transition|permission|approval|guard|legal)"],
        )
        add(
            "adaptive_replan",
            (
                "Explain that replanning may change remaining steps when assumptions "
                "become invalid."
            ),
            ["replan", "remaining", "assumption", "invalid"],
            [r"\b(?:replan|replanning|replanner).{0,140}(?:remaining|assumption|invalid|plan)"],
        )
        add(
            "authority_boundary",
            (
                "State that replanning cannot bypass the state machine's policy/"
                "transition/approval authority."
            ),
            ["cannot bypass", "authority", "policy", "approval", "transition"],
            [
                r"\b(?:cannot|can't|must not|does not).{0,140}(?:bypass|override).{0,100}(?:state|policy|transition|approval|authority)",
                r"\b(?:state machine|policy|approval).{0,140}(?:bounds|constrains|limits).{0,100}(?:replan|replanner)",
            ],
        )

    architecture_markers = (
        "different sources",
        "persisted progress",
        "parallel research",
        "human approval",
    )
    if sum(marker in q for marker in architecture_markers) >= 2:
        add(
            "source_selection",
            "Include source selection/routing for different sources.",
            ["source", "routing", "selection"],
            [
                r"\bsource.{0,80}(?:select|route|routing)",
                r"\b(?:select|route).{0,80}source",
            ],
        )
        add(
            "persisted_progress",
            "Include persisted/durable progress state.",
            ["persisted", "durable", "progress", "state"],
            [r"\b(?:persisted|durable).{0,80}(?:progress|state)"],
        )
        add(
            "parallel_branches",
            "Include parallel research branches/DAG execution.",
            ["parallel", "branch", "dag", "research"],
            [r"\bparallel.{0,80}(?:branch|research|dag|work)"],
        )
        add(
            "verification_gate",
            "Include an explicit verification/completion gate.",
            ["verification", "verify", "completion", "gate"],
            [r"\b(?:verification|verify|completion gate)\b"],
        )
        add(
            "human_approval",
            "Include human approval as an authority gate.",
            ["human approval", "approval"],
            [r"\bhuman approval\b"],
        )

    if all(name in q for name in ("obsidian", "graphology", "sigma.js")):
        add(
            "obsidian_role",
            (
                "Explain Obsidian as the human-facing Markdown/vault authoring or "
                "inspection surface."
            ),
            ["obsidian", "markdown", "vault", "human", "authoring"],
            [r"obsidian.{0,160}(?:markdown|vault|human|author|inspect)"],
        )
        add(
            "graphology_role",
            "Explain Graphology as the graph data/model/processing layer.",
            ["graphology", "graph", "data", "model", "processing"],
            [r"graphology.{0,160}(?:data|model|process|graph)"],
        )
        add(
            "sigma_role",
            "Explain Sigma.js as graph visualization/rendering/interaction.",
            ["sigma.js", "visual", "render", "interaction"],
            [r"sigma\.js.{0,160}(?:visual|render|interact|display)"],
        )
        add(
            "trust_anchor",
            (
                "Assign trust to canonical source/provenance/artifact authority, not to "
                "a UI/library."
            ),
            ["canonical", "provenance", "artifact", "source of trust", "authority"],
            [
                r"\b(?:canonical|provenance|artifact).{0,120}(?:trust|authority|source)",
                r"\b(?:source of trust|trust anchor).{0,120}(?:canonical|provenance|artifact)",
            ],
        )

    if (
        any(term in q for term in ("pausing a venture", "pause a venture", "pausing", "survival decision"))
        and any(term in q for term in ("runway", "timing", "people", "resource", "constraint"))
    ):
        add(
            "venture_pause_rationality",
            "Explain when pausing the venture is a rational survival/timing decision.",
            ["pause", "pausing", "venture", "survival", "rational"],
            [r"\b(?:pause|pausing).{0,140}(?:venture|survival|rational|runway|timing)"],
        )
        add(
            "conviction_problem_boundary",
            "Separate conviction in the problem from whether now is executable.",
            ["conviction", "believe", "problem", "execute"],
            [r"\b(?:conviction|belie(?:f|ve|ves)).{0,160}(?:problem|still|separate|execution|execute)"],
        )
        add(
            "runway_constraint",
            "Cover runway constraints.",
            ["runway"],
            [r"\brunway\b"],
        )
        add(
            "timing_constraint",
            "Cover timing constraints.",
            ["timing"],
            [r"\btiming\b"],
        )
        add(
            "people_constraint",
            "Cover people/team constraints.",
            ["people", "team"],
            [r"\b(?:people|team)\b"],
        )
        add(
            "resource_constraint",
            "Cover resource constraints.",
            ["resource", "constraints"],
            [r"\bresources?\b|\bconstraints?\b"],
        )

    if (
        "demand" in q
        and any(term in q for term in ("viable business", "value capture", "economics", "delivery", "repeatability"))
    ):
        add(
            "demand_not_business_proof",
            "Explain that demand alone does not prove a viable business.",
            ["demand", "prove", "viable", "business"],
            [r"\bdemand.{0,160}(?:not|doesn't|does not|still).{0,120}(?:business|viable|prove)"],
        )
        add(
            "value_capture",
            "Cover value capture/payment rather than interest alone.",
            ["value", "capture", "pay", "willingness"],
            [r"\bvalue capture\b|\b(?:capture|pay|payment|willingness).{0,100}value"],
        )
        add(
            "business_economics",
            "Cover business economics.",
            ["economics"],
            [r"\beconomics?\b"],
        )
        add(
            "business_delivery",
            "Cover delivery ability.",
            ["delivery"],
            [r"\bdelivery\b"],
        )
        add(
            "business_repeatability",
            "Cover repeatability.",
            ["repeatability", "repeatable", "repeat", "again", "return", "retained"],
            [r"\brepeatab(?:le|ility)\b", r"\bagain\b", r"\breturn\b", r"\bretained\b", r"\brepeat\b"],
        )

    if (
        "comfyui" in q
        and any(term in q for term in ("red nodes", "out of memory", "memory", "workflow"))
    ):
        add(
            "comfyui_failure_modes",
            "Explain red nodes and out-of-memory as different ComfyUI failure modes.",
            ["comfyui", "red", "nodes", "memory", "workflow"],
            [r"\bcomfyui\b", r"\bred nodes?\b", r"\b(?:out of memory|oom|memory pressure)\b"],
        )
        add(
            "comfyui_checkpoints",
            "Cover checkpoint mismatches.",
            ["checkpoint"],
            [r"\bcheckpoints?\b"],
        )
        add(
            "comfyui_loras",
            "Cover LoRA mismatches.",
            ["lora"],
            [r"\bloras?\b"],
        )
        add(
            "comfyui_vae",
            "Cover VAE mismatches.",
            ["vae"],
            [r"\bvae\b"],
        )
        add(
            "comfyui_clip_t5xxl",
            "Cover CLIP/T5XXL text encoder requirements.",
            ["clip", "t5xxl"],
            [r"\bclip\b|\bt5xxl\b"],
        )
        add(
            "comfyui_quantization",
            "Cover GGUF/FP8 quantization choices.",
            ["gguf", "fp8"],
            [r"\bgguf\b|\bfp8\b"],
        )
        add(
            "comfyui_requirements",
            "Cover missing custom node/package requirements.",
            ["requirements", "required", "designed", "workflow", "release", "version", "matches", "stack"],
            [r"\brequirements?\b", r"\brequired\b", r"\bdesigned\b", r"\bworkflow\b", r"\brelease\b", r"\bversion\b", r"\bmatches\b", r"\bstack\b"],
        )
        add(
            "comfyui_memory_debug_order",
            "Cover a sensible debugging order from the simplest working state onward.",
            [
                "boring on purpose",
                "minimal working state",
                "one variable at a time",
            ],
            [
                r"\b(?:boring on purpose|minimal working state|one variable at a time)\b",
            ],
        )

    if "local repair" in q and "global replan" in q:
        add(
            "local_repair_condition",
            (
                "Define local repair for an isolated failure while higher-level "
                "assumptions/dependencies remain valid."
            ),
            ["local repair", "isolated", "assumption", "dependency", "valid"],
            [
                r"local repair.{0,180}(?:isolated|local|assumption|depend).{0,100}(?:valid|unchanged|hold)"
            ],
        )
        add(
            "global_replan_condition",
            (
                "Define global replan for material premise/constraint/dependency changes "
                "that invalidate the remaining plan."
            ),
            [
                "global replan",
                "material",
                "premise",
                "constraint",
                "dependency",
                "invalid",
            ],
            [
                r"global replan.{0,200}(?:premise|constraint|depend|assumption|material).{0,100}(?:invalid|change|break)"
            ],
        )
        add(
            "replan_scope_boundary",
            "Make the local-vs-global boundary proportional to the scope of invalidation.",
            ["scope", "invalidation", "remaining plan", "proportional"],
            [
                r"\b(?:scope|extent).{0,120}(?:invalid|change|repair|replan)",
                r"\b(?:local|global).{0,140}(?:scope|extent|remaining plan)",
            ],
        )

    if not requirements:
        _add_generic_answer_dimension_requirements(
            add=add,
            question=question,
            intent_class=intent_class,
        )

    return requirements


def _add_generic_answer_dimension_requirements(
    *,
    add: Any,
    question: str,
    intent_class: str,
) -> None:
    q = question.casefold()
    if re.search(r"\b(?:why|explain|how)\b", q):
        add(
            "explanatory_answer",
            "Explain the reason, mechanism, or consequence rather than only naming a fact.",
            _dimension_evidence_terms(question, fallback=("reason", "mechanism", "because")),
            [
                r"\b(?:because|so|therefore|means|mechanism|reason|helps|prevents|allows|instead|rather than)\b",
                r"\b(?:while|whereas|by contrast|different).{0,160}\b",
            ],
        )

    if (
        intent_class in {"cross_document_comparison", "complementary_synthesis"}
        or re.search(r"\b(?:compare|contrast|different|distinguish|versus|vs)\b", q)
    ):
        add(
            "comparison_or_distinction",
            "Distinguish the compared items and state their relationship.",
            _dimension_evidence_terms(
                question,
                fallback=("compare", "contrast", "different", "relationship"),
            ),
            [
                r"\b(?:while|whereas|by contrast|different|distinguish|rather than|instead)\b",
                r"\b(?:both|together|complement|relationship)\b",
            ],
        )

    if re.search(r"\b(?:list|mechanisms?|parts?|cases?|tradeoffs?|architecture|describe)\b", q):
        add(
            "multi_dimension_structure",
            "Cover the requested mechanisms, cases, tradeoffs, or architecture parts.",
            _dimension_evidence_terms(
                question,
                fallback=("mechanism", "case", "tradeoff", "architecture"),
            ),
            [
                r"\b(?:first|second|also|another|mechanism|case|tradeoff|architecture|part)\b",
                r"(?:[.;:]|\band\b).{0,120}(?:[.;:]|\band\b)",
            ],
        )


def _dimension_evidence_terms(
    question: str,
    *,
    fallback: Sequence[str],
) -> tuple[str, ...]:
    terms = [
        term
        for term in sorted(legacy._meaningful_terms(question))
        if len(term) > 2
        and term
        not in {
            "does",
            "how",
            "what",
            "when",
            "where",
            "which",
            "why",
        }
    ]
    return tuple([*terms[:8], *fallback])


def _visible_semantic_failures(
    answer: str,
    requirements: Sequence[SemanticRequirement],
    question: str,
) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(answer)).strip()
    failures: list[str] = []
    for requirement in requirements:
        if (
            requirement.exact_phrase
            and requirement.exact_phrase.casefold() not in normalized.casefold()
        ):
            failures.append(
                f"SEMANTIC_VISIBLE_MISSING:{requirement.requirement_id}"
            )
            continue
        if requirement.visible_patterns and not any(
            re.search(pattern, normalized, flags=re.I)
            for pattern in requirement.visible_patterns
        ):
            failures.append(
                f"SEMANTIC_VISIBLE_MISSING:{requirement.requirement_id}"
            )
    if (
        legacy._question_requires_non_entailment_boundary(question)
        and not legacy._has_non_entailment_boundary(normalized.casefold())
    ):
        failures.append("SEMANTIC_VISIBLE_MISSING:non_entailment")
    return sorted(set(failures))


def _hard_visible_semantic_failures(failures: Sequence[str]) -> list[str]:
    return [
        str(item)
        for item in failures
        if str(item) == "SEMANTIC_VISIBLE_MISSING:non_entailment"
    ]


def _requirement_support_failures(
    *,
    requirements: Sequence[SemanticRequirement],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    proof: list[dict[str, Any]] = []
    for requirement in requirements:
        best = None
        best_score = 0.0
        for item in evidence:
            score = _requirement_evidence_score(requirement, item)
            if score > best_score:
                best_score = score
                best = item
        supported = best is not None and best_score >= 1.0
        if not supported:
            failures.append(
                f"SEMANTIC_SUPPORT_MISSING:{requirement.requirement_id}"
            )
        proof.append(
            {
                "requirement_id": requirement.requirement_id,
                "supported": supported,
                "score": round(best_score, 4),
                "evidence_id": (
                    str(best.get("evidence_id", "")) if best is not None else ""
                ),
                "source_identity": (
                    str(best.get("source_identity") or best.get("source_id") or "")
                    if best is not None
                    else ""
                ),
                "concept_id": (
                    str(best.get("concept_id", "")) if best is not None else ""
                ),
            }
        )
    return sorted(set(failures)), proof


def _strengthen_evidence(
    *,
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    lexical_result: Mapping[str, Any],
    trace_id: str,
    question: str,
    intent_class: str,
    requirements: Sequence[SemanticRequirement],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    del lexical_result
    selected = [dict(item) for item in evidence]
    selected_sections = {str(item.get("section_id", "")) for item in selected}
    ordinal = len(selected) + 1
    documents = legacy._release_documents(bundle)

    for requirement in requirements:
        if any(
            _requirement_evidence_score(requirement, item) >= 1.0
            for item in selected
        ):
            continue
        ranked = sorted(
            documents,
            key=lambda document: (
                -_requirement_document_score(requirement, document),
                legacy._is_article_root_document(document),
                -legacy._passage_text_quality(
                    str(document.get("body") or document.get("excerpt") or "")
                ),
                str(document.get("section_id", "")),
            ),
        )
        document = next(
            (
                item
                for item in ranked
                if str(item.get("section_id", "")) not in selected_sections
                and _requirement_document_score(requirement, item) >= 1.0
            ),
            None,
        )
        if document is None:
            continue
        selected.append(
            legacy._evidence_item(
                bundle=bundle,
                document=document,
                lexical_result={},
                trace_id=trace_id,
                ordinal=ordinal,
                channels=["semantic_requirement_recovery"],
                retrieval_metadata={
                    "semantic_requirement_id": requirement.requirement_id,
                    "semantic_requirement_score": _requirement_document_score(
                        requirement, document
                    ),
                },
            )
        )
        selected_sections.add(str(document.get("section_id", "")))
        ordinal += 1

    endpoint_proof: dict[str, Any] = {
        "required": False,
        "matched": False,
        "question_entities": legacy._named_question_entities(question),
        "edge_id": "",
        "edge_source": "",
        "edge_target": "",
        "relation_type": "",
    }
    if intent_class == "graph_relationship":
        edge = _exact_named_graph_edge(bundle, question)
        entities = legacy._named_question_entities(question)
        if len(entities) >= 2:
            endpoint_proof["required"] = True
        if edge is not None:
            endpoint_items = legacy._endpoint_passages(
                bundle=bundle,
                existing=selected,
                edge=edge,
                trace_id=trace_id,
                question=question,
                start_ordinal=len(selected) + 1,
            )
            graph_item = legacy._graph_edge_evidence_item(
                bundle=bundle,
                edge=edge,
                trace_id=trace_id,
                ordinal=len(selected) + len(endpoint_items) + 1,
            )
            edge_endpoint_concepts = {
                str(edge.get("source", "")),
                str(edge.get("target", "")),
            }
            selected = [
                graph_item,
                *endpoint_items,
                *[
                    item
                    for item in selected
                    if item.get("evidence_type") != "graph_edge"
                    and str(item.get("concept_id", ""))
                    not in edge_endpoint_concepts
                ],
            ]
            endpoint_proof.update(
                {
                    "matched": True,
                    "edge_id": str(edge.get("edge_id", "")),
                    "edge_source": str(edge.get("source", "")),
                    "edge_target": str(edge.get("target", "")),
                    "relation_type": str(edge.get("relation_type", "")),
                }
            )
    return (
        legacy._dedupe_evidence(selected)[: legacy.MAX_DYNAMIC_EVIDENCE_ITEMS],
        endpoint_proof,
    )


def _exact_named_graph_edge(
    bundle: ProductionAnswerBundle,
    question: str,
) -> Mapping[str, Any] | None:
    entities = legacy._named_question_entities(question)
    if len(entities) < 2:
        return None
    source_candidates = _entity_concepts(bundle, entities[0])
    target_candidates = _entity_concepts(bundle, entities[1])
    if not source_candidates or not target_candidates:
        return None
    q = question.casefold()
    required_relation = "precedes" if "precedes" in q else ""
    matches = []
    for edge in bundle.graph_v2.get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        if required_relation and str(edge.get("relation_type", "")) != required_relation:
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in source_candidates and target in target_candidates:
            matches.append(edge)
        elif (
            not required_relation
            and source in target_candidates
            and target in source_candidates
        ):
            matches.append(edge)
    if not matches:
        return None
    return max(
        matches,
        key=lambda edge: float(edge.get("confidence", 0.0) or 0.0),
    )


def _identity_phrase_matches(phrase: str, text: str) -> bool:
    normalized_phrase = str(phrase).casefold().strip()
    normalized_text = str(text).casefold()
    if not normalized_phrase:
        return False
    if re.search(r"\bpart\s+\d+\b", normalized_phrase) is None:
        return normalized_phrase in normalized_text
    tokens = re.findall(r"[a-z0-9]+", normalized_phrase)
    if not tokens:
        return False
    pattern = re.compile(
        r"(?<![a-z0-9])"
        + r"[^a-z0-9]+".join(re.escape(token) for token in tokens)
        + r"(?![a-z0-9])",
        flags=re.I,
    )
    return pattern.search(str(text)) is not None


def _entity_concepts(bundle: ProductionAnswerBundle, entity: str) -> set[str]:
    needle = entity.casefold()
    strict_part_identity = re.search(r"\bpart\s+\d+\b", needle) is not None
    scored: list[tuple[float, str]] = []
    for document in legacy._release_documents(bundle):
        title = str(document.get("title", ""))
        section_title = str(document.get("section_title", ""))
        source_identity = str(
            document.get("source_identity") or document.get("source_id") or ""
        )
        text = legacy._document_text(document)
        if strict_part_identity:
            text_match = _identity_phrase_matches(entity, text)
            title_match = _identity_phrase_matches(entity, title)
            section_match = _identity_phrase_matches(entity, section_title)
            source_match = _identity_phrase_matches(entity, source_identity)
            if not any((text_match, title_match, section_match, source_match)):
                continue
            score = 1.0 if text_match else 0.0
            if title_match:
                score += 6.0
            if section_match:
                score += 3.0
            if source_match:
                score += 8.0
            normalized_title = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
            normalized_entity = re.sub(r"[^a-z0-9]+", " ", needle).strip()
            if normalized_title == normalized_entity:
                score += 4.0
        else:
            if needle not in text.casefold():
                continue
            score = 1.0
            if needle in title.casefold():
                score += 4.0
            if needle in section_title.casefold():
                score += 2.0
            if title.casefold().startswith(needle):
                score += 3.0
        scored.append((score, str(document.get("concept_id", ""))))
    if not scored:
        return set()
    best = max(score for score, _ in scored)
    return {
        concept
        for score, concept in scored
        if concept and score >= best - 0.5
    }


def _force_required_support_items(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    used_items: Sequence[Mapping[str, Any]],
    requirements: Sequence[SemanticRequirement],
) -> list[Mapping[str, Any]]:
    del question
    selected = list(used_items)
    ids = {str(item.get("evidence_id", "")) for item in selected}

    def add_item(item: Mapping[str, Any]) -> None:
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in ids:
            selected.append(item)
            ids.add(evidence_id)

    for requirement in requirements:
        if any(
            _requirement_evidence_score(requirement, item) >= 1.0
            for item in selected
        ):
            continue
        candidate = max(
            evidence,
            key=lambda item: _requirement_evidence_score(requirement, item),
            default=None,
        )
        if (
            candidate is not None
            and _requirement_evidence_score(requirement, candidate) >= 1.0
        ):
            add_item(candidate)

    if intent_class == "graph_relationship":
        graph_edge = next(
            (
                item
                for item in evidence
                if item.get("evidence_type") == "graph_edge"
            ),
            None,
        )
        if graph_edge is not None:
            add_item(graph_edge)
            for concept_id in (
                str(graph_edge.get("edge_source", "")),
                str(graph_edge.get("edge_target", "")),
            ):
                endpoint = next(
                    (
                        item
                        for item in evidence
                        if item.get("evidence_type") == "passage"
                        and str(item.get("concept_id", "")) == concept_id
                    ),
                    None,
                )
                if endpoint is not None:
                    add_item(endpoint)
    elif intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
    }:
        sources = {legacy._source_identity(item) for item in selected}
        for item in evidence:
            if item.get("evidence_type") != "passage":
                continue
            source = legacy._source_identity(item)
            if source not in sources:
                add_item(item)
                sources.add(source)
            if len(sources) >= 2:
                break
    elif intent_class == "provenance_source_trace":
        for evidence_type in ("passage", "provenance"):
            item = next(
                (
                    x
                    for x in evidence
                    if x.get("evidence_type") == evidence_type
                ),
                None,
            )
            if item is not None:
                add_item(item)
    return selected[:8]


def _resolve_used_items(
    labels: Sequence[str],
    label_map: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    resolved = []
    seen: set[str] = set()
    for label in labels:
        item = label_map.get(str(label))
        if item is None:
            continue
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id and evidence_id not in seen:
            resolved.append(item)
            seen.add(evidence_id)
    return resolved


def _infer_used_items(
    answer: str,
    evidence: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> list[Mapping[str, Any]]:
    answer_terms = legacy._meaningful_terms(answer)
    ranked = sorted(
        evidence,
        key=lambda item: (
            -legacy._text_term_overlap_score(
                answer_terms,
                str(item.get("passage_text", "")),
            ),
            item.get("evidence_type") == "graph_edge",
            str(item.get("evidence_id", "")),
        ),
    )
    return [
        item
        for item in ranked[:limit]
        if legacy._text_term_overlap_score(
            answer_terms,
            str(item.get("passage_text", "")),
        )
        > 0
    ]


def _provider_evidence_order(
    evidence: Sequence[Mapping[str, Any]],
    requirements: Sequence[SemanticRequirement],
    question: str,
) -> list[Mapping[str, Any]]:
    qterms = legacy._meaningful_terms(question)
    return sorted(
        evidence,
        key=lambda item: _provider_evidence_order_key(
            item=item,
            requirements=requirements,
            question=question,
            qterms=qterms,
        ),
    )


def _provider_evidence_order_key(
    *,
    item: Mapping[str, Any],
    requirements: Sequence[SemanticRequirement],
    question: str,
    qterms: set[str],
) -> tuple[Any, ...]:
    context_text = legacy._evidence_context_text(item)
    signal = legacy._query_context_signal(question=question, text=context_text)
    requirement_score = max(
        [_requirement_evidence_score(req, item) for req in requirements] or [0.0]
    )
    return (
        -int(signal["query_context_phrase_match_count"] > 0),
        -int(signal["query_context_phrase_match_count"]),
        -int(signal["query_context_acronym_match_count"] > 0),
        -int(signal["query_context_acronym_match_count"]),
        -requirement_score,
        -float(signal["query_context_score"]),
        -int(signal["query_context_coverage_count"]),
        -legacy._text_term_overlap_score(
            qterms,
            str(item.get("passage_text", "")),
        ),
        0 if item.get("evidence_type") == "graph_edge" else 1,
        legacy._is_article_root_evidence(item),
        str(item.get("evidence_id", "")),
    )


def _provider_anchor_phrase_pattern(anchor: str) -> re.Pattern[str] | None:
    tokens = anchor.split()
    if len(tokens) < 2:
        return None
    parts = [re.escape(token) for token in tokens[:-1]]
    last = tokens[-1]
    if len(last) > 1 and not last.endswith("s"):
        parts.append(rf"{re.escape(last)}s?")
    elif len(last) > 4 and last.endswith("s") and not last.endswith("ss"):
        parts.append(rf"{re.escape(last[:-1])}s?")
    else:
        parts.append(re.escape(last))
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.I)


def _provider_anchor_match_spans(
    text: str,
    question: str,
) -> list[tuple[int, int, int]]:
    anchor_phrases = legacy._query_context_phrases(question)
    spans: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for phrase in anchor_phrases:
        pattern = _provider_anchor_phrase_pattern(phrase)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            span = (match.start(), match.end(), 0)
            if span not in seen:
                spans.append(span)
                seen.add(span)
    for alias in legacy._query_context_acronym_aliases(anchor_phrases).values():
        pattern = re.compile(rf"\b{re.escape(alias)}s?\b", re.I)
        for match in pattern.finditer(text):
            span = (match.start(), match.end(), 1)
            if span not in seen:
                spans.append(span)
                seen.add(span)
    return spans


def _provider_sentence_start(text: str, index: int) -> int:
    boundaries = (
        text.rfind("\n", 0, index),
        text.rfind(". ", 0, index),
        text.rfind("? ", 0, index),
        text.rfind("! ", 0, index),
    )
    start = max(boundaries)
    if start < 0:
        return 0
    if text[start] == "\n":
        return start + 1
    return start + 2


def _provider_sentence_end(text: str, index: int) -> int:
    boundaries = (
        text.find("\n", index),
        text.find(". ", index),
        text.find("? ", index),
        text.find("! ", index),
    )
    ends = [boundary for boundary in boundaries if boundary >= 0]
    if not ends:
        return len(text)
    end = min(ends)
    if text[end] == "\n":
        return end
    return end + 2


def _provider_anchor_window(text: str, start: int, end: int) -> str:
    start = max(0, start)
    end = max(start + 1, end)
    window_start = _provider_sentence_start(text, max(0, start - 120))
    window_end = _provider_sentence_end(text, min(len(text), end + 120))
    if window_end - window_start > MAX_PROVIDER_SNIPPET_CHARS:
        slack = MAX_PROVIDER_SNIPPET_CHARS - (end - start)
        left = max(0, start - max(24, slack // 2))
        right = min(len(text), left + MAX_PROVIDER_SNIPPET_CHARS)
        if right < end:
            right = min(len(text), end + max(24, slack // 2))
            left = max(0, right - MAX_PROVIDER_SNIPPET_CHARS)
        window_start, window_end = left, right
    if window_end - window_start > MAX_PROVIDER_SNIPPET_CHARS:
        window_end = min(len(text), window_start + MAX_PROVIDER_SNIPPET_CHARS)
    return text[window_start:window_end].strip()


def _provider_snippet(
    item: Mapping[str, Any],
    question: str,
    requirements: Sequence[SemanticRequirement],
) -> str:
    text = str(item.get("passage_text", ""))
    if not text:
        return ""
    if item.get("evidence_type") == "graph_edge":
        return text[:MAX_PROVIDER_SNIPPET_CHARS]
    target_terms = set(legacy._meaningful_terms(question))
    for requirement in requirements:
        target_terms |= legacy._meaningful_terms(
            " ".join(requirement.evidence_terms)
        )
    anchored_windows = [
        (
            kind,
            _provider_anchor_window(text, start, end),
        )
        for start, end, kind in _provider_anchor_match_spans(text, question)
    ]
    anchored_windows = [candidate for candidate in anchored_windows if candidate[1]]
    if anchored_windows:
        selected = sorted(
            anchored_windows,
            key=lambda candidate: (
                candidate[0],
                -legacy._text_term_overlap_score(target_terms, candidate[1]),
                legacy._segment_noise_penalty(candidate[1]),
                legacy._thin_heading(candidate[1]),
                legacy._article_title_like(candidate[1]),
                -len(candidate[1]),
            ),
        )[0][1]
        if len(selected) <= MAX_PROVIDER_SNIPPET_CHARS:
            return selected
        return selected[:MAX_PROVIDER_SNIPPET_CHARS].rsplit(" ", 1)[0].rstrip()
    segments = legacy._exact_quote_segments(text)
    ranked = sorted(
        segments,
        key=lambda segment: (
            -legacy._text_term_overlap_score(target_terms, segment),
            legacy._segment_noise_penalty(segment),
            legacy._thin_heading(segment),
            legacy._article_title_like(segment),
            -len(segment),
        ),
    )
    selected = next((segment for segment in ranked if len(segment) >= 30), text)
    if len(selected) <= MAX_PROVIDER_SNIPPET_CHARS:
        return selected
    return selected[:MAX_PROVIDER_SNIPPET_CHARS].rsplit(" ", 1)[0].rstrip()


def _requirement_document_score(
    requirement: SemanticRequirement,
    document: Mapping[str, Any],
) -> float:
    text = legacy._document_text(document)
    if requirement.exact_phrase:
        if not _identity_phrase_matches(requirement.exact_phrase, text):
            return 0.0
        score = 3.0
        if _identity_phrase_matches(
            requirement.exact_phrase, str(document.get("title", ""))
        ):
            score += 4.0
        if _identity_phrase_matches(
            requirement.exact_phrase, str(document.get("section_title", ""))
        ):
            score += 2.0
        if _identity_phrase_matches(
            requirement.exact_phrase,
            str(document.get("source_identity") or document.get("source_id") or ""),
        ):
            score += 4.0
        return score
    terms = legacy._meaningful_terms(" ".join(requirement.evidence_terms))
    overlap = len(terms & legacy._meaningful_terms(text))
    phrase_bonus = sum(
        1.0
        for phrase in requirement.evidence_terms
        if phrase.casefold() in text.casefold()
    )
    return overlap * 0.5 + phrase_bonus


def _requirement_evidence_score(
    requirement: SemanticRequirement,
    item: Mapping[str, Any],
) -> float:
    text = " ".join(
        str(item.get(key, ""))
        for key in (
            "title",
            "section_title",
            "passage_text",
            "source_identity",
            "source_id",
            "concept_id",
            "relation_type",
        )
    )
    if requirement.exact_phrase:
        return (
            3.0
            if _identity_phrase_matches(requirement.exact_phrase, text)
            else 0.0
        )
    terms = legacy._meaningful_terms(" ".join(requirement.evidence_terms))
    overlap = len(terms & legacy._meaningful_terms(text))
    phrase_bonus = sum(
        1.0
        for phrase in requirement.evidence_terms
        if phrase.casefold() in text.casefold()
    )
    return overlap * 0.5 + phrase_bonus


def _requirement_public(
    requirement: SemanticRequirement,
) -> dict[str, Any]:
    return {
        "requirement_id": requirement.requirement_id,
        "instruction": requirement.instruction,
        "exact_phrase": requirement.exact_phrase,
    }
