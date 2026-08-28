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
MAX_PROVIDER_ANSWER_CHARS = 1800
RUNTIME_OBSERVABILITY_SCHEMA = "m26-pa7-runtime-observability/v1"


@dataclass(frozen=True)
class SemanticRequirement:
    requirement_id: str
    instruction: str
    evidence_terms: tuple[str, ...]
    visible_patterns: tuple[str, ...]
    exact_phrase: str = ""


def _new_runtime_observability() -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_OBSERVABILITY_SCHEMA,
        "stage_timings": [],
        "provider_call_timings": [],
        "counts": {},
    }


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _safe_observability_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        return value[:120]
    return None


def _observe_count(observability: dict[str, Any] | None, **counts: Any) -> None:
    if observability is None:
        return
    target = observability.setdefault("counts", {})
    if not isinstance(target, dict):
        return
    for key, value in counts.items():
        safe = _safe_observability_value(value)
        if safe is not None:
            target[key] = safe


def _observe_stage(
    observability: dict[str, Any] | None,
    stage: str,
    started: float,
    **metadata: Any,
) -> None:
    if observability is None:
        return
    record: dict[str, Any] = {
        "stage": stage,
        "elapsed_ms": _elapsed_ms(started),
    }
    for key, value in metadata.items():
        safe = _safe_observability_value(value)
        if safe is not None:
            record[key] = safe
    stages = observability.setdefault("stage_timings", [])
    if isinstance(stages, list):
        stages.append(record)


def _payload_size_bytes(value: Any) -> int:
    try:
        return len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
    except (TypeError, ValueError):
        return 0


def _observe_provider_call(
    observability: dict[str, Any] | None,
    *,
    call_class: str,
    payload: Mapping[str, Any],
    started: float,
    result: Mapping[str, Any] | None = None,
    error_type: str = "",
) -> None:
    if observability is None:
        return
    target = observability.setdefault("provider_call_timings", [])
    if not isinstance(target, list):
        return
    usage = result.get("usage") if isinstance(result, Mapping) else {}
    usage = usage if isinstance(usage, Mapping) else {}
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
    record: dict[str, Any] = {
        "attempt": len(target) + 1,
        "call_class": str(call_class),
        "elapsed_ms": _elapsed_ms(started),
        "payload_bytes": _payload_size_bytes(payload),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens)),
    }
    if isinstance(result, Mapping):
        record["provider_latency_ms"] = int(result.get("latency_ms", 0))
        record["provider_text_char_count"] = len(
            str(result.get("text", result.get("provider_text", "")))
        )
        record["stop_reason"] = str(
            result.get("stop_reason") or result.get("finish_reason") or ""
        )
    if error_type:
        record["error_type"] = error_type
    target.append(record)


def _provider_call_timing_from_telemetry(
    call: Mapping[str, Any], *, attempt: int
) -> dict[str, Any]:
    usage = call.get("usage") if isinstance(call.get("usage"), Mapping) else {}
    parse = (
        call.get("parse_telemetry")
        if isinstance(call.get("parse_telemetry"), Mapping)
        else {}
    )
    return {
        "attempt": attempt,
        "call_class": str(call.get("call_class", "")),
        "latency_ms": int(call.get("latency_ms", 0)),
        "provider_text_char_count": int(call.get("provider_text_char_count", 0)),
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "total_tokens": int(usage.get("total_tokens", 0)),
        "parse_ok": bool(parse.get("parse_ok", False)),
        "parse_subtype": str(parse.get("parse_subtype", "")),
    }


def _add_provider_call_observability(
    observability: dict[str, Any] | None,
    verification: Mapping[str, Any],
) -> None:
    if observability is None:
        return
    mve = (
        verification.get("multi_evidence_verification")
        if isinstance(verification.get("multi_evidence_verification"), Mapping)
        else {}
    )
    calls = mve.get("provider_attempt_telemetry", []) if isinstance(mve, Mapping) else []
    if not isinstance(calls, list):
        return
    target = observability.setdefault("provider_call_timings", [])
    if not isinstance(target, list):
        return
    existing = len(target)
    for index, call in enumerate(calls, start=1):
        if isinstance(call, Mapping):
            timing = _provider_call_timing_from_telemetry(
                call, attempt=existing + index
            )
            target_index = index - 1
            if target_index < existing:
                parse_keys = ("parse_ok", "parse_subtype")
                target[target_index].update(
                    {key: timing[key] for key in parse_keys if key in timing}
                )
            else:
                target.append(timing)


def _attach_runtime_observability(
    response: dict[str, Any],
    observability: dict[str, Any] | None,
) -> dict[str, Any]:
    if observability is None:
        return response
    stages = [
        dict(item)
        for item in observability.get("stage_timings", [])
        if isinstance(item, Mapping)
    ]
    provider_calls = [
        dict(item)
        for item in observability.get("provider_call_timings", [])
        if isinstance(item, Mapping)
    ]
    counts = (
        dict(observability.get("counts", {}))
        if isinstance(observability.get("counts"), Mapping)
        else {}
    )
    response["runtime_observability"] = {
        "schema_version": RUNTIME_OBSERVABILITY_SCHEMA,
        "stage_timings": stages,
        "provider_call_timings": provider_calls,
        "counts": {
            **counts,
            "stage_count": len(stages),
            "provider_call_count": len(provider_calls),
        },
        "totals": {
            "stage_elapsed_ms_sum": sum(int(item.get("elapsed_ms", 0)) for item in stages),
            "provider_latency_ms_sum": sum(
                int(item.get("provider_latency_ms", item.get("latency_ms", 0)))
                for item in provider_calls
            ),
            "provider_wall_elapsed_ms_sum": sum(
                int(item.get("elapsed_ms", 0)) for item in provider_calls
            ),
        },
    }
    return response


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
    max_provider_calls: int = 2,
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
    observability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response_stage_started = time.monotonic()
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
    _observe_stage(
        observability,
        "response_dto_build",
        response_stage_started,
        selected_evidence_count=len(evidence),
        has_retrieval_fields=bundle is not None
        and dense_result is not None
        and lexical_result is not None,
    )
    return _attach_runtime_observability(response, observability)


def _synthesize_and_verify(
    *,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: ProviderClient,
    requirements: Sequence[SemanticRequirement],
    endpoint_proof: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
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
        try:
            raw = provider_client.call(
                compact_payload,
                (
                    "aq_semantic_closure_repair"
                    if attempt == 2
                    else "aq_semantic_closure"
                ),
            )
            try:
                parsed = _parse_compact_provider_result(
                    str(raw.get("text", raw.get("provider_text", "")))
                )
            except ValueError:
                calls.append(_compact_call_telemetry(raw, parse_ok=False))
                raise
            calls.append(_compact_call_telemetry(raw, parse_ok=True))
            if parsed["status"] == "abstain":
                failures.append("PROVIDER_ABSTAINED_WITH_AVAILABLE_EVIDENCE")
                if attempt == 1:
                    repair_attempted = True
                    continue
                break

            answer = str(parsed["answer"]).strip()
            visible_failures = _visible_semantic_failures(
                answer, requirements, question
            )
            used_items = _resolve_used_items(parsed["used"], label_map)
            if not used_items:
                used_items = _infer_used_items(answer, evidence, limit=6)
            used_items = _force_required_support_items(
                question=question,
                intent_class=intent_class,
                evidence=evidence,
                used_items=used_items,
                requirements=requirements,
            )
            support_failures, support_proof = _requirement_support_failures(
                requirements=requirements,
                evidence=used_items,
            )
            final_support_proof = support_proof
            semantic_failures = sorted(
                set([*visible_failures, *support_failures])
            )
            if semantic_failures:
                failures.extend(semantic_failures)
                if attempt == 1:
                    repair_attempted = True
                    continue
                break

            candidate = _runtime_bound_candidate(
                answer=answer,
                question=question,
                intent_class=intent_class,
                used_items=used_items,
                snippet_map=snippet_map,
            )
            verified = legacy._verify_multi_evidence_provider_output(
                trace_id=trace_id,
                question=question,
                intent_class=intent_class,
                evidence=evidence,
                provider_text=json.dumps(
                    candidate,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            final_answer = legacy._verified_multi_evidence_answer(
                intent_class=intent_class,
                verified=verified,
                evidence=evidence,
                calls=calls,
                repair_attempted=repair_attempted,
            )
            post_failures = _visible_semantic_failures(
                str(final_answer.get("answer_text", "")),
                requirements,
                question,
            )
            if post_failures:
                failures.extend(post_failures)
                if attempt == 1:
                    repair_attempted = True
                    continue
                break

            final_answer["answer_source"] = (
                "provider_verified_runtime_bound_semantic_closure"
            )
            final_answer["multi_evidence_verification"] = {
                **dict(final_answer.get("multi_evidence_verification", {})),
                "verification_failure_codes_by_attempt": list(failures),
                "repair_trigger": sorted(set(failures)) if repair_attempted else [],
                "repair_result": "verified" if repair_attempted else "not_needed",
                "deterministic_evidence_synthesis_used": False,
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
            }
            closure = {
                "schema_version": "m26-aq-semantic-closure/v1",
                "requirements": [_requirement_public(item) for item in requirements],
                "support_proof": final_support_proof,
                "endpoint_proof": dict(endpoint_proof),
                "failures": [],
                "provider_contract": "compact_runtime_bound_semantic_closure/v1",
                "broad_deterministic_fallback_used": False,
            }
            return final_answer, closure
        except (legacy.VerifiedAnswerGateError, ValueError, KeyError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            failures.append(str(code))
            if attempt == 1:
                repair_attempted = True
                continue
        except (LiveGateError, httpx.HTTPError) as exc:
            failures.append(type(exc).__name__)
            break

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
        return deterministic, closure

    abstention = legacy._verified_abstention(
        reason_codes=[*failures, "SEMANTIC_CLOSURE_FAILED"],
        calls=calls,
        repair_attempted=repair_attempted,
    )
    abstention["answer_source"] = "safe_abstention"
    closure = {
        "schema_version": "m26-aq-semantic-closure/v1",
        "requirements": [_requirement_public(item) for item in requirements],
        "support_proof": final_support_proof,
        "endpoint_proof": dict(endpoint_proof),
        "failures": sorted(set(failures)),
        "provider_contract": "compact_runtime_bound_semantic_closure/v1",
        "broad_deterministic_fallback_used": False,
    }
    return abstention, closure


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
            "status": "answer|abstain",
            "answer": "",
            "used": ["e1"],
        },
    }
    system = (
        "Answer only from supplied evidence. Return exactly one compact JSON object with "
        "keys status, answer, used. status is answer or abstain. For answer, write 2-4 "
        "concise natural sentences and list the evidence labels actually used. Address "
        "every must_state item explicitly. Do not paste code or headings. Do not invent "
        "facts. A precedes edge means ordering/navigation only, never dependency, "
        "causality or implementation unless passage text separately proves that stronger "
        "relation. If support is insufficient, abstain."
    )
    return (
        {
            "model": "MiniMax-M3",
            "max_tokens": 512,
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


def _parse_compact_provider_result(text: str) -> dict[str, Any]:
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
    if set(value) - {"status", "answer", "used"}:
        raise ValueError("compact provider JSON has unknown keys")
    status = str(value.get("status", ""))
    if status not in {"answer", "abstain"}:
        raise ValueError("compact provider status invalid")
    answer = str(value.get("answer", ""))
    if status == "answer" and (
        not answer.strip() or len(answer) > MAX_PROVIDER_ANSWER_CHARS
    ):
        raise ValueError("compact provider answer invalid")
    raw_used = value.get("used", [])
    if not isinstance(raw_used, list):
        raise ValueError("compact provider used must be list")
    return {
        "status": status,
        "answer": answer,
        "used": [str(item) for item in raw_used],
    }


def _compact_call_telemetry(
    result: Mapping[str, Any], *, parse_ok: bool
) -> dict[str, Any]:
    usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
    return {
        "provider_text": "",
        "provider_text_char_count": len(
            str(result.get("text", result.get("provider_text", "")))
        ),
        "call_class": str(result.get("call_class", "")),
        "stop_reason": str(
            result.get("stop_reason") or result.get("finish_reason") or ""
        ),
        "content_block_types": [
            str(item) for item in result.get("content_block_types", [])
        ],
        "parse_telemetry": {
            "parse_ok": parse_ok,
            "parse_subtype": (
                "compact_semantic_closure_json" if parse_ok else "invalid"
            ),
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


def _runtime_bound_candidate(
    *,
    answer: str,
    question: str,
    intent_class: str,
    used_items: Sequence[Mapping[str, Any]],
    snippet_map: Mapping[str, str],
) -> dict[str, Any]:
    refs = []
    for item in used_items[:8]:
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
    if not refs:
        raise ValueError("runtime could not bind provider prose to evidence")
    role = "direct"
    relation: str | None = None
    if intent_class == "cross_document_comparison":
        role = "comparison"
        relation = "contrasts_with"
    elif intent_class == "complementary_synthesis":
        role = "relationship"
        relation = "complements"
    elif intent_class == "graph_relationship":
        role = "relationship"
        edge = next(
            (
                item
                for item in used_items
                if item.get("evidence_type") == "graph_edge"
            ),
            None,
        )
        relation = str(edge.get("relation_type", "")) if edge is not None else None
    elif intent_class == "provenance_source_trace":
        role = "provenance"
    elif intent_class == "temporal_conflict":
        role = "temporal"
        relation = "precedes"
    anchored = _anchor_material_sentences(answer)
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": [
            str(item.get("evidence_id", "")) for item in used_items
        ],
        "answer_text": anchored,
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": role,
                "surface_text": answer,
                "facet_ids": legacy._required_facet_ids(
                    question=question,
                    intent_class=intent_class,
                ),
                "support_mode": "runtime_bound_exact_multi_evidence",
                "support_refs": refs,
            }
        ],
        "missing_facets": [],
        "abstention_reason": None,
    }


def _anchor_material_sentences(answer: str) -> str:
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", str(answer).strip())
        if item.strip()
    ]
    if not sentences:
        return ""
    return " ".join(
        item if legacy.CLAIM_ANCHOR_RE.search(item) else f"{item} [[claim_1]]"
        for item in sentences
    )


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

    return requirements


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
        key=lambda item: (
            -max(
                [
                    _requirement_evidence_score(req, item)
                    for req in requirements
                ]
                or [0.0]
            ),
            -legacy._text_term_overlap_score(
                qterms,
                str(item.get("passage_text", "")),
            ),
            0 if item.get("evidence_type") == "graph_edge" else 1,
            legacy._is_article_root_evidence(item),
            str(item.get("evidence_id", "")),
        ),
    )


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
