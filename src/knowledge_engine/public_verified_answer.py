from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from .m14_retrieval import retrieve_wiki_first
from .m26_ask_api import _mapping, _object_list, _source_cards, _string_list, _web_citations
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_pa7_semantic_closure_runtime import (
    DenseChannel,
    PA7ArbitraryQueryError,
    ProductionAnswerBundle,
    ProviderClient,
    _assert_full_production_graph,
    _response_from_verification,
    _semantic_requirements,
    _strengthen_evidence,
    _synthesize_and_verify,
    legacy,
    load_production_answer_bundle,
)
from .m26_production_promotion_closure import load_json
from .m26_verified_answer_citation_gate import canonical_sha256

PUBLIC_VERIFIED_ANSWER_RESPONSE_SCHEMA = "knowledge-engine-api-v1-ask-response/v1"
PUBLIC_VERIFIED_ANSWER_RUNTIME_ENTRYPOINT = (
    "knowledge_engine.public_verified_answer.run_public_verified_answer"
)
DEFAULT_GATE_PATH = Path("pilot/m26/m26-pa-7-resolved-production-gate.json")
DEFAULT_PUBLIC_MAX_PROVIDER_CALLS = 1
DEFAULT_PUBLIC_MAX_COST_USD = Decimal("0.02")
PUBLIC_AUDIENCE = "public"


class PublicVerifiedAnswerError(PA7ArbitraryQueryError):
    """Fail-closed public verified answer adapter error."""


def run_public_verified_answer(
    *,
    question: str,
    root: Path | None = None,
    gate: Mapping[str, Any] | None = None,
    gate_path: Path = DEFAULT_GATE_PATH,
    provider_client: ProviderClient | None = None,
    dense_channel: DenseChannel | None = None,
    require_remote_dense: bool = False,
    max_provider_calls: int = DEFAULT_PUBLIC_MAX_PROVIDER_CALLS,
    max_cost: Decimal = DEFAULT_PUBLIC_MAX_COST_USD,
    answer_bundle: ProductionAnswerBundle | None = None,
    requested_max_results: int | None = None,
) -> dict[str, Any]:
    runtime_response = _run_public_verified_answer_runtime(
        question=question,
        root=root,
        gate=gate,
        gate_path=gate_path,
        provider_client=provider_client,
        dense_channel=dense_channel,
        require_remote_dense=require_remote_dense,
        max_provider_calls=max_provider_calls,
        max_cost=max_cost,
        answer_bundle=answer_bundle,
    )
    return public_response_from_verified_runtime(
        runtime_response,
        requested_max_results=requested_max_results,
        max_provider_calls=max_provider_calls,
    )


def _run_public_verified_answer_runtime(
    *,
    question: str,
    root: Path | None,
    gate: Mapping[str, Any] | None,
    gate_path: Path,
    provider_client: ProviderClient | None,
    dense_channel: DenseChannel | None,
    require_remote_dense: bool,
    max_provider_calls: int,
    max_cost: Decimal,
    answer_bundle: ProductionAnswerBundle | None,
) -> dict[str, Any]:
    started = time.monotonic()
    resolved_root = root or Path(".")
    resolved_gate = dict(gate or load_json(resolved_root / gate_path))
    validated_gate = legacy._validate_gate(resolved_root, resolved_gate)
    normalized_question = legacy._normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = legacy._intent_class(normalized_question)
    trace_id = "keapi1ask_" + canonical_sha256(
        {
            "audience": PUBLIC_AUDIENCE,
            "gate": validated_gate.get("self_sha256"),
            "question_sha256": question_sha,
            "route": "/api/v1/ask",
        }
    )[:32]

    if legacy._looks_like_prompt_injection(normalized_question):
        return _runtime_abstention_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
        )
    if legacy._looks_like_underspecified_workflow_question(normalized_question):
        return _runtime_abstention_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            reason_codes=["QUESTION_UNDERSPECIFIED_CLARIFICATION_REQUIRED"],
        )

    provider = provider_client
    if provider is None:
        try:
            provider = MiniMaxClient(
                os.environ.get("MINIMAX_API_KEY", ""),
                max_calls=max_provider_calls,
                max_cost=max_cost,
            )
        except LiveGateError as exc:
            return _runtime_abstention_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                intent_class=intent_class,
                reason_codes=[type(exc).__name__, "PROVIDER_CONFIGURATION_MISSING"],
            )

    full_bundle = answer_bundle or load_production_answer_bundle()
    _assert_full_production_graph(full_bundle)
    public_bundle = _public_projection_bundle(full_bundle)
    public_sections = _public_section_ids(public_bundle)

    if not public_sections:
        return _runtime_abstention_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            bundle=public_bundle,
            reason_codes=["NO_AUTHORIZED_PUBLIC_PRODUCTION_EVIDENCE"],
        )

    dense = (
        dense_channel or legacy.dense_channel_from_env(require_remote=require_remote_dense)
    ).search(
        question=normalized_question,
        bundle=public_bundle,
        top_k=8,
    )
    lexical = retrieve_wiki_first(
        query=normalized_question,
        allowed_audiences={PUBLIC_AUDIENCE},
        lexical_index=public_bundle.lexical_index,
        graph=public_bundle.graph,
        relation_graph=public_bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=public_bundle.provenance,
        semantic_index=None,
        limit=8,
    )
    evidence = legacy._select_evidence(
        bundle=public_bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    evidence = _public_only_evidence(evidence, public_bundle=public_bundle)
    requirements = _semantic_requirements(normalized_question, intent_class)
    evidence, endpoint_proof = _strengthen_evidence(
        bundle=public_bundle,
        evidence=evidence,
        lexical_result=lexical,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
        requirements=requirements,
    )
    evidence = _public_only_evidence(evidence, public_bundle=public_bundle)

    if not evidence or not legacy._has_meaningful_overlap(normalized_question, evidence):
        verification = legacy._verified_abstention(
            reason_codes=(
                ["NO_AUTHORIZED_PUBLIC_PRODUCTION_EVIDENCE"]
                if not evidence
                else ["LOW_PUBLIC_RETRIEVAL_SUPPORT"]
            ),
            calls=[],
            repair_attempted=False,
        )
        return _response_from_verification(
            gate=validated_gate,
            bundle=public_bundle,
            dense_result=dense,
            lexical_result=lexical,
            evidence=[],
            verification=verification,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            intent_class=intent_class,
            semantic_closure={
                "requirements": [],
                "support_proof": [],
                "endpoint_proof": endpoint_proof,
                "failures": ["LOW_PUBLIC_RETRIEVAL_SUPPORT"],
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
        bundle=public_bundle,
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


def public_response_from_verified_runtime(
    runtime_response: Mapping[str, Any],
    *,
    requested_max_results: int | None,
    max_provider_calls: int,
) -> dict[str, Any]:
    citations = _web_citations(runtime_response)
    status = _public_status(runtime_response)
    provider_call_count = int(runtime_response.get("provider_call_count", 0))
    return {
        "schema_version": PUBLIC_VERIFIED_ANSWER_RESPONSE_SCHEMA,
        "route": "/api/v1/ask",
        "audience": PUBLIC_AUDIENCE,
        "canonical_runtime": {
            "schema_version": runtime_response.get("schema_version"),
            "entrypoint": PUBLIC_VERIFIED_ANSWER_RUNTIME_ENTRYPOINT,
            "build_sha": os.environ.get("M26_QUERY_BUILD_SHA", "local_unset"),
            "runtime_response_sha256": canonical_sha256(dict(runtime_response)),
        },
        "status": status,
        "terminal_status": str(runtime_response.get("terminal_status", "")),
        "trace_id": str(runtime_response.get("trace_id", "")),
        "question_sha256": str(runtime_response.get("question_sha256", "")),
        "answer_text": str(runtime_response.get("answer_text", "")),
        "safe_abstention": bool(runtime_response.get("safe_abstention", True)),
        "reason_codes": _string_list(runtime_response.get("reason_codes")),
        "citations": citations,
        "sources": _source_cards(citations),
        "answer_claims": _object_list(runtime_response.get("answer_claims")),
        "relationship_summary": dict(_mapping(runtime_response.get("relationship_summary"))),
        "multi_evidence_verification": _public_verification_summary(runtime_response),
        "semantic_closure": _public_semantic_closure(runtime_response),
        "identities": {
            "production_release_id": runtime_response.get("production_release_id"),
            "production_manifest_sha256": runtime_response.get("production_manifest_sha256"),
            "production_pointer_digest": runtime_response.get("production_pointer_digest"),
            "resolved_gate_self_sha256": runtime_response.get("resolved_gate_self_sha256"),
        },
        "retrieval": {
            "mode_summary": dict(_mapping(runtime_response.get("retrieval_mode_summary"))),
            "candidate_count_by_channel": dict(
                _mapping(runtime_response.get("candidate_count_by_channel"))
            ),
            "selected_evidence_count": int(runtime_response.get("selected_evidence_count", 0)),
            "distinct_source_count": int(runtime_response.get("distinct_source_count", 0)),
            "distinct_source_identities": _string_list(
                runtime_response.get("distinct_source_identities")
            ),
            "public_audience_only": True,
            "selected_evidence_returned": False,
            "requested_max_results": requested_max_results,
        },
        "accounting": {
            "provider_invoked": bool(runtime_response.get("provider_invoked", False)),
            "provider_call_count": provider_call_count,
            "max_provider_calls": max_provider_calls,
            "provider_call_bound_respected": provider_call_count <= max_provider_calls,
            "payg_equivalent_cost_usd": str(
                runtime_response.get("payg_equivalent_cost_usd", "0")
            ),
            "latency_ms": int(runtime_response.get("latency_ms", 0)),
        },
        "privacy": {
            **_public_privacy_counters(runtime_response),
            "owner_token_exposed": False,
            "owner_hash_exposed": False,
            "provider_secret_exposed": False,
            "raw_provider_response_exposed": False,
            "selected_evidence_text_exposed": False,
            "confidential_or_restricted_evidence_exposed": False,
        },
        "mutations": _public_mutation_counters(runtime_response),
    }


def _runtime_abstention_response(
    *,
    gate: Mapping[str, Any],
    trace_id: str,
    question_sha: str,
    started: float,
    intent_class: str,
    reason_codes: Sequence[str],
    bundle: ProductionAnswerBundle | None = None,
) -> dict[str, Any]:
    verification = legacy._verified_abstention(
        reason_codes=reason_codes,
        calls=[],
        repair_attempted=False,
    )
    return _response_from_verification(
        gate=gate,
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
            "endpoint_proof": {
                "public_audience_only": True,
                "production_release_id": bundle.release_id if bundle is not None else None,
            },
            "failures": list(reason_codes),
        },
    )


def _public_projection_bundle(bundle: ProductionAnswerBundle) -> ProductionAnswerBundle:
    public_concepts = {
        str(document.get("concept_id", ""))
        for document in _documents(bundle)
        if str(document.get("audience", "")) == PUBLIC_AUDIENCE
    }
    public_documents = [
        dict(document)
        for document in _documents(bundle)
        if str(document.get("concept_id", "")) in public_concepts
        and str(document.get("audience", "")) == PUBLIC_AUDIENCE
    ]
    graph_nodes = [
        dict(node)
        for node in _object_list(bundle.graph.get("nodes"))
        if str(node.get("concept_id", "")) in public_concepts
        and str(node.get("audience", "")) == PUBLIC_AUDIENCE
    ]
    graph_v2_nodes = [
        dict(node)
        for node in _object_list(bundle.graph_v2.get("nodes"))
        if str(node.get("concept_id", "")) in public_concepts
        and str(node.get("audience", "")) == PUBLIC_AUDIENCE
    ]
    graph_edges = _public_edges(bundle.graph.get("edges"), public_concepts)
    graph_v2_edges = _public_edges(bundle.graph_v2.get("edges"), public_concepts)
    public_sources = {str(document.get("source_id", "")) for document in public_documents}
    return ProductionAnswerBundle(
        manifest=dict(bundle.manifest),
        graph={**dict(bundle.graph), "nodes": graph_nodes, "edges": graph_edges},
        graph_v2={**dict(bundle.graph_v2), "nodes": graph_v2_nodes, "edges": graph_v2_edges},
        lexical_index={**dict(bundle.lexical_index), "documents": public_documents},
        provenance={
            **dict(bundle.provenance),
            "records": [
                dict(record)
                for record in _object_list(bundle.provenance.get("records"))
                if str(
                    _mapping(record.get("subject")).get("concept_id", "")
                )
                in public_concepts
            ],
        },
        manifest_sha256=bundle.manifest_sha256,
        artifact_sha256=dict(bundle.artifact_sha256),
        artifact_keys=dict(bundle.artifact_keys),
        loaded_at=bundle.loaded_at,
        production_pointer=(
            dict(bundle.production_pointer)
            if isinstance(bundle.production_pointer, Mapping)
            else None
        ),
        production_pointer_sha256=bundle.production_pointer_sha256,
        production_manifest=(
            dict(bundle.production_manifest)
            if isinstance(bundle.production_manifest, Mapping)
            else None
        ),
        production_manifest_sha256=bundle.production_manifest_sha256,
        source_documents=_filtered_source_documents(bundle.source_documents, public_sources),
        document_source_index=_filtered_document_source_index(
            bundle.document_source_index, public_sources
        ),
        semantic_inputs=_filtered_semantic_inputs(bundle.semantic_inputs, public_documents),
    )


def _documents(bundle: ProductionAnswerBundle) -> list[dict[str, Any]]:
    return _object_list(bundle.lexical_index.get("documents"))


def _public_edges(value: Any, public_concepts: set[str]) -> list[dict[str, Any]]:
    edges = []
    for edge in _object_list(value):
        source = str(edge.get("from_concept_id") or edge.get("source", ""))
        target = str(edge.get("to_concept_id") or edge.get("target", ""))
        if (
            source in public_concepts
            and target in public_concepts
            and str(edge.get("audience", "")) == PUBLIC_AUDIENCE
        ):
            edges.append(dict(edge))
    return edges


def _public_section_ids(bundle: ProductionAnswerBundle) -> set[str]:
    return {str(document.get("section_id", "")) for document in _documents(bundle)}


def _public_only_evidence(
    evidence: Sequence[Mapping[str, Any]],
    *,
    public_bundle: ProductionAnswerBundle,
) -> list[dict[str, Any]]:
    public_sections = _public_section_ids(public_bundle)
    public_concepts = {
        str(document.get("concept_id", ""))
        for document in _documents(public_bundle)
    }
    public_edge_ids = {
        str(edge.get("edge_id", ""))
        for edge in _object_list(public_bundle.graph_v2.get("edges"))
    }
    filtered = []
    for item in evidence:
        if str(item.get("evidence_type", "passage")) == "graph_edge":
            if (
                str(item.get("edge_id", "")) in public_edge_ids
                and str(item.get("edge_source", "")) in public_concepts
                and str(item.get("edge_target", "")) in public_concepts
            ):
                filtered.append(dict(item))
            continue
        if (
            str(item.get("section_id", "")) in public_sections
            and str(item.get("concept_id", "")) in public_concepts
        ):
            filtered.append(dict(item))
    return filtered


def _filtered_source_documents(
    value: Mapping[str, Any] | None,
    public_sources: set[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        **dict(value),
        "documents": [
            dict(document)
            for document in _object_list(value.get("documents"))
            if str(document.get("source_id", "")) in public_sources
        ],
    }


def _filtered_document_source_index(
    value: Mapping[str, Any] | None,
    public_sources: set[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        **dict(value),
        "sources": [
            dict(source)
            for source in _object_list(value.get("sources"))
            if str(source.get("source_id", "")) in public_sources
        ],
    }


def _filtered_semantic_inputs(
    value: Mapping[str, Any] | None,
    public_documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    public_sections = {str(document.get("section_id", "")) for document in public_documents}
    return {
        **dict(value),
        "documents": [
            dict(document)
            for document in _object_list(value.get("documents"))
            if str(document.get("section_id", "")) in public_sections
        ],
    }


def _public_status(runtime_response: Mapping[str, Any]) -> str:
    if bool(runtime_response.get("safe_abstention", True)):
        return "public_safe_abstention"
    if (
        bool(runtime_response.get("material_claim_support_verified", False))
        and bool(runtime_response.get("citation_locator_valid", False))
        and int(runtime_response.get("unsupported_accepted_claims", 0)) == 0
    ):
        return "public_cited_answer"
    return "public_safe_abstention"


def _public_verification_summary(runtime_response: Mapping[str, Any]) -> dict[str, Any]:
    verification = dict(_mapping(runtime_response.get("multi_evidence_verification")))
    return {
        "material_claim_support_verified": bool(
            runtime_response.get("material_claim_support_verified", False)
        ),
        "citation_locator_valid": bool(runtime_response.get("citation_locator_valid", False)),
        "unsupported_accepted_claims": int(
            runtime_response.get("unsupported_accepted_claims", 0)
        ),
        "repair_attempted": bool(runtime_response.get("repair_attempted", False)),
        "answer_source": str(runtime_response.get("answer_source", "")),
        "provider_contract": verification.get("provider_contract"),
        "provider_attempt_telemetry": _object_list(
            verification.get("provider_attempt_telemetry")
        ),
        "verification_failure_codes_by_attempt": _string_list(
            verification.get("verification_failure_codes_by_attempt")
        ),
        "raw_provider_text_returned": False,
    }


def _public_semantic_closure(runtime_response: Mapping[str, Any]) -> dict[str, Any]:
    closure = dict(_mapping(runtime_response.get("semantic_closure")))
    return {
        "schema_version": closure.get("schema_version"),
        "requirements": _object_list(closure.get("requirements")),
        "support_proof": _object_list(closure.get("support_proof")),
        "endpoint_proof": dict(_mapping(closure.get("endpoint_proof"))),
        "failures": _string_list(closure.get("failures")),
        "provider_contract": closure.get("provider_contract"),
    }


def _public_privacy_counters(runtime_response: Mapping[str, Any]) -> dict[str, Any]:
    privacy = dict(_mapping(runtime_response.get("privacy")))
    return {
        key: value
        for key, value in privacy.items()
        if key not in {"owner_token_exposed", "owner_hash_exposed"}
    }


def _public_mutation_counters(runtime_response: Mapping[str, Any]) -> dict[str, Any]:
    mutations = dict(_mapping(runtime_response.get("mutations")))
    return {
        **mutations,
        "writes_performed": 0,
        "feedback_records_written": 0,
        "corpus_mutations": 0,
    }
