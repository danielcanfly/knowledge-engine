from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .errors import IntegrityError
from .m14_retrieval import retrieve_wiki_first
from .m23_cloudflare_qdrant import (
    CLOUDFLARE_MODEL,
    QDRANT_VECTOR_NAME,
    CloudflareConfig,
    SectionInput,
    embed_sections,
)
from .m24_product_surface_integration import CanonicalReleaseBundle, load_canonical_release
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_production_promotion_closure import (
    ProductionPromotionClosureError,
    evaluate_owner_admission,
    validate_resolved_gate,
    verify_self_digest,
)
from .m26_production_promotion_closure import (
    load_json as load_pa7_json,
)
from .m26_retrieval_envelope import normalize_question, sha256_value
from .m26_verified_answer_citation_gate import (
    VerifiedAnswerGateError,
    canonical_sha256,
    sha256_bytes,
)

RESPONSE_SCHEMA = "knowledge-engine-m26-pa7-arbitrary-owner-query-response/v1"
MAX_QUERY_CHARS = 2_000
MAX_EVIDENCE_ITEMS = 3
MAX_BUNDLE_EVIDENCE_ITEMS = 5
MAX_CANDIDATE_POOL_ITEMS = 40
MAX_DYNAMIC_EVIDENCE_ITEMS = 16
MAX_PARENT_SECTIONS_PER_EVIDENCE = 3
LOCAL_DENSE_DIMENSION = 64
PA4_POLICY_PATH = Path("pilot/m26/m26-pa-4-verified-answer-policy.json")
PA7_OWNER_DECISION_PATH = Path("pilot/m26/m26-pa-7-owner-final-decision.json")
RELATIONAL_INTENTS = {
    "cross_document_comparison",
    "complementary_synthesis",
    "graph_relationship",
    "temporal_conflict",
}
MULTI_SOURCE_INTENTS = RELATIONAL_INTENTS | {"provenance_source_trace"}
PROVIDER_STATUS_VALUES = {"answer_candidate", "abstain"}
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\bdeveloper\s+message\b", re.I),
    re.compile(r"\bhidden\s+(?:instruction|prompt|policy)\b", re.I),
    re.compile(r"\b(?:api[_ -]?key|secret|password|token|credential)\b", re.I),
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")
STOP_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
}

INTENT_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "temporal_conflict",
        (
            re.compile(r"\b(?:temporal|fresh|freshness|newer|older|changed|version)\b", re.I),
            re.compile(r"\b(?:conflict|contradict|stale|between source records)\b", re.I),
            re.compile(r"\b(?:edited|adoption state)\b", re.I),
        ),
    ),
    (
        "provenance_source_trace",
        (
            re.compile(
                r"\b(?:provenance|source trace|source record|which source|supports)\b",
                re.I,
            ),
        ),
    ),
    (
        "graph_relationship",
        (
            re.compile(
                r"\b(?:graph|relationship|edge|connects?|depends|requires|dag)\b",
                re.I,
            ),
            re.compile(r"\bdirected acyclic graph\b", re.I),
            re.compile(r"\b(?:implemented_by|part_of|has_part)\b", re.I),
        ),
    ),
    (
        "cross_document_comparison",
        (
            re.compile(
                r"\b(?:compare|contrast|difference|different|distinction|versus|vs)\b",
                re.I,
            ),
            re.compile(r"\bwhile\b", re.I),
        ),
    ),
    (
        "complementary_synthesis",
        (
            re.compile(r"\b(?:complement|synthesis|synthesize|combine|together)\b", re.I),
        ),
    ),
)


class PA7ArbitraryQueryError(IntegrityError):
    """Fail-closed M26.PA.7 arbitrary query runtime error."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(f"{reason_code}: {message}")
        self.reason_code = reason_code


class DenseChannel(Protocol):
    def search(
        self,
        *,
        question: str,
        bundle: CanonicalReleaseBundle,
        top_k: int,
    ) -> dict[str, Any]: ...


class ProviderClient(Protocol):
    calls: int
    cost: Decimal

    def call(self, payload: Mapping[str, Any], call_class: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RemoteDenseConfig:
    cloudflare_account_id: str
    cloudflare_api_token: str
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    timeout_seconds: float = 30.0


class LocalDenseProjectionChannel:
    """Ephemeral dense projection over the accepted local production release."""

    def search(
        self,
        *,
        question: str,
        bundle: CanonicalReleaseBundle,
        top_k: int,
    ) -> dict[str, Any]:
        query_vector = _hashed_vector(question)
        candidates: list[dict[str, Any]] = []
        for document in _release_documents(bundle):
            text = " ".join(
                str(document.get(key, ""))
                for key in ("title", "section_title", "description", "body", "excerpt")
            )
            score = _cosine(query_vector, _hashed_vector(text))
            if score <= 0:
                continue
            section_id = str(document["section_id"])
            candidates.append(
                {
                    "channel": "dense",
                    "section_id": section_id,
                    "concept_id": str(document["concept_id"]),
                    "score": round(score, 6),
                    "point_id_sha256": canonical_sha256(
                        {
                            "backend": "local_release_dense_projection_v1",
                            "release_id": bundle.release_id,
                            "section_id": section_id,
                        }
                    ),
                }
            )
        candidates.sort(key=lambda item: (-float(item["score"]), item["section_id"]))
        return {
            "backend_identity": {
                "backend": "local_release_dense_projection_v1",
                "release_id": bundle.release_id,
                "manifest_sha256": bundle.manifest_sha256,
                "vector_dimension": LOCAL_DENSE_DIMENSION,
                "remote": False,
                "vectors_persisted": False,
            },
            "candidates": candidates[:top_k],
        }


class RemoteQdrantDenseChannel:
    """Read-only dense query channel for formal owner-only execution."""

    def __init__(self, config: RemoteDenseConfig) -> None:
        self.config = config

    def search(
        self,
        *,
        question: str,
        bundle: CanonicalReleaseBundle,
        top_k: int,
    ) -> dict[str, Any]:
        vector = embed_sections(
            [SectionInput(section_id="m26-pa7-owner-query", text=question, payload={})],
            CloudflareConfig(
                account_id=self.config.cloudflare_account_id,
                api_token=self.config.cloudflare_api_token,
                timeout_seconds=self.config.timeout_seconds,
            ),
        )[0]
        response = httpx.post(
            _qdrant_search_url(self.config.qdrant_url, self.config.qdrant_collection),
            headers={"api-key": self.config.qdrant_api_key, "Content-Type": "application/json"},
            json={
                "vector": {"name": QDRANT_VECTOR_NAME, "vector": vector},
                "limit": max(1, min(top_k, 20)),
                "with_payload": [
                    "section_id",
                    "source_id",
                    "release_id",
                    "source_commit_sha",
                    "admission_sha256",
                    "candidate_release_eligible",
                    "production_authority",
                    "text_sha256",
                ],
                "with_vector": False,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("result"), list):
            raise PA7ArbitraryQueryError("PA7_DENSE_BACKEND_INVALID", "Qdrant response shape")
        candidates = []
        for raw in payload["result"]:
            if not isinstance(raw, Mapping):
                continue
            point_payload = raw.get("payload")
            if not isinstance(point_payload, Mapping):
                continue
            section_id = str(point_payload.get("section_id", "")).strip()
            if not section_id:
                continue
            score = raw.get("score", 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            candidates.append(
                {
                    "channel": "dense",
                    "section_id": section_id,
                    "concept_id": str(point_payload.get("concept_id", "")),
                    "score": round(float(score), 6),
                    "point_id_sha256": canonical_sha256(str(raw.get("id", ""))),
                    "payload_identity_sha256": canonical_sha256(
                        {
                            key: point_payload.get(key)
                            for key in (
                                "section_id",
                                "source_id",
                                "release_id",
                                "source_commit_sha",
                                "admission_sha256",
                                "candidate_release_eligible",
                                "production_authority",
                                "text_sha256",
                            )
                            if key in point_payload
                        }
                    ),
                }
            )
        return {
            "backend_identity": {
                "backend": "qdrant_dense_read_only",
                "qdrant_collection": self.config.qdrant_collection,
                "qdrant_url_sha256": canonical_sha256(self.config.qdrant_url.rstrip("/")),
                "embedding_model": CLOUDFLARE_MODEL,
                "vector_name": QDRANT_VECTOR_NAME,
                "release_id": bundle.release_id,
                "manifest_sha256": bundle.manifest_sha256,
                "remote": True,
                "vectors_persisted": False,
            },
            "candidates": candidates[:top_k],
        }


def dense_channel_from_env(*, require_remote: bool = False) -> DenseChannel:
    api_key = (
        os.environ.get("QDRANT_API_KEY_READ")
        or os.environ.get("QDRANT_READ_ONLY_API_KEY")
        or os.environ.get("QDRANT_API_KEY")
        or ""
    )
    collection = (
        os.environ.get("M26_PA7_DENSE_COLLECTION")
        or os.environ.get("QDRANT_COLLECTION")
        or os.environ.get("QDRANT_COLLECTION_NAME")
        or ""
    )
    config_values = {
        "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "cloudflare_api_token": os.environ.get("CLOUDFLARE_AI_TOKEN")
        or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        "qdrant_url": os.environ.get("QDRANT_URL", ""),
        "qdrant_api_key": api_key,
        "qdrant_collection": collection,
    }
    if all(config_values.values()):
        return RemoteQdrantDenseChannel(RemoteDenseConfig(**config_values))
    if require_remote:
        missing = sorted(key for key, value in config_values.items() if not value)
        raise PA7ArbitraryQueryError(
            "PA7_REMOTE_DENSE_CONFIG_MISSING",
            "missing remote dense configuration: " + ",".join(missing),
        )
    return LocalDenseProjectionChannel()


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
) -> dict[str, Any]:
    started = time.monotonic()
    normalized_question = _normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = _intent_class(normalized_question)
    validated_gate = _validate_gate(root, gate)
    identities = _object(validated_gate.get("production_identities"), "gate.production_identities")
    admission = evaluate_owner_admission(
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
        return _base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status="denied_non_owner_or_public_request",
            terminal_status="denied_before_retrieval",
            reason_codes=admission["reason_codes"],
        )

    if _looks_like_prompt_injection(normalized_question):
        return _base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status="owner_only_safe_abstention",
            terminal_status="safe_abstention",
            reason_codes=["PROMPT_INJECTION_OR_PRIVACY_RISK"],
        )

    bundle = load_canonical_release()
    dense = (dense_channel or dense_channel_from_env(require_remote=require_remote_dense)).search(
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
    evidence = _select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=trace_id,
        question=normalized_question,
        intent_class=intent_class,
    )
    if not evidence or not _has_meaningful_overlap(normalized_question, evidence):
        return {
            **_base_response(
                gate=validated_gate,
                trace_id=trace_id,
                question_sha=question_sha,
                started=started,
                status="owner_only_safe_abstention",
                terminal_status="safe_abstention",
                reason_codes=["NO_AUTHORIZED_PRODUCTION_EVIDENCE"]
                if not evidence
                else ["LOW_RETRIEVAL_SUPPORT"],
            ),
            **_retrieval_response_fields(
                gate=validated_gate,
                bundle=bundle,
                lexical_result=lexical,
                dense_result=dense,
                selected_evidence=[],
                intent_class=intent_class,
            ),
        }

    provider = provider_client
    if provider is None:
        try:
            provider = MiniMaxClient(
                os.environ.get("MINIMAX_API_KEY", ""),
                max_calls=max_provider_calls,
                max_cost=max_cost,
            )
        except LiveGateError as exc:
            verification = _verified_abstention(
                reason_codes=[type(exc).__name__, "PROVIDER_CONFIGURATION_MISSING"],
                calls=[],
                repair_attempted=False,
            )
        else:
            verification = _synthesize_and_verify(
                root=root,
                question=normalized_question,
                trace_id=trace_id,
                intent_class=intent_class,
                evidence=evidence,
                provider_client=provider,
            )
    else:
        verification = _synthesize_and_verify(
            root=root,
            question=normalized_question,
            trace_id=trace_id,
            intent_class=intent_class,
            evidence=evidence,
            provider_client=provider,
        )
    response = {
        **_base_response(
            gate=validated_gate,
            trace_id=trace_id,
            question_sha=question_sha,
            started=started,
            status=verification["status"],
            terminal_status=verification["terminal_status"],
            answer_text=verification["answer_text"],
            safe_abstention=verification["safe_abstention"],
            reason_codes=verification["reason_codes"],
            provider_invoked=verification["provider_call_count"] > 0,
            provider_call_count=verification["provider_call_count"],
            payg_equivalent_cost_usd=verification["payg_equivalent_cost_usd"],
            material_claim_support_verified=verification["material_claim_support_verified"],
            citation_locator_valid=verification["citation_locator_valid"],
            unsupported_accepted_claims=verification["unsupported_accepted_claims"],
            repair_attempted=verification["repair_attempted"],
        ),
        **_retrieval_response_fields(
            gate=validated_gate,
            bundle=bundle,
            lexical_result=lexical,
            dense_result=dense,
            selected_evidence=evidence,
            intent_class=intent_class,
        ),
        "citations": verification["citations"],
        "answer_claims": verification.get("answer_claims", []),
        "relationship_summary": verification.get("relationship_summary", {}),
        "multi_evidence_verification": verification.get("multi_evidence_verification", {}),
    }
    response["latency_ms"] = max(
        int(response["latency_ms"]),
        int((time.monotonic() - started) * 1000),
    )
    return response


def _normalize_request_question(question: str) -> str:
    normalized = normalize_question(question)
    if len(normalized) > MAX_QUERY_CHARS:
        raise PA7ArbitraryQueryError("PA7_QUERY_TOO_LONG", "question exceeds PA7 bound")
    return normalized


def _validate_gate(root: Path, gate: Mapping[str, Any]) -> dict[str, Any]:
    verify_self_digest(gate, "PA7 resolved gate")
    decision_path = root / PA7_OWNER_DECISION_PATH
    if decision_path.exists():
        try:
            return validate_resolved_gate(gate, load_pa7_json(decision_path))
        except ProductionPromotionClosureError as exc:
            raise PA7ArbitraryQueryError(exc.reason_code, str(exc)) from exc
    identities = _object(gate.get("production_identities"), "gate.production_identities")
    if gate.get("schema_version") != "knowledge-engine-m26-pa-7-resolved-production-gate/v1":
        raise PA7ArbitraryQueryError("PA7_GATE_INVALID", "schema mismatch")
    if identities.get("public_traffic_percent") != 0:
        raise PA7ArbitraryQueryError("PA7_GATE_INVALID", "public traffic is not zero")
    if identities.get("automatic_expansion") is not False:
        raise PA7ArbitraryQueryError("PA7_GATE_INVALID", "automatic expansion is not false")
    return dict(gate)


def _base_response(
    *,
    gate: Mapping[str, Any],
    trace_id: str,
    question_sha: str,
    started: float,
    status: str,
    terminal_status: str,
    answer_text: str = "",
    citations: Sequence[Mapping[str, Any]] | None = None,
    safe_abstention: bool = True,
    reason_codes: Sequence[str] | None = None,
    provider_invoked: bool = False,
    provider_call_count: int = 0,
    payg_equivalent_cost_usd: str = "0",
    material_claim_support_verified: bool = True,
    citation_locator_valid: bool = True,
    unsupported_accepted_claims: int = 0,
    repair_attempted: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": RESPONSE_SCHEMA,
        "status": status,
        "terminal_status": terminal_status,
        "trace_id": trace_id,
        "question_sha256": question_sha,
        "resolved_gate_self_sha256": gate.get("self_sha256"),
        "answer_text": answer_text,
        "citations": [dict(item) for item in citations or []],
        "safe_abstention": safe_abstention,
        "reason_codes": sorted(set(str(item) for item in reason_codes or [])),
        "provider_invoked": provider_invoked,
        "provider_identity": "MiniMax",
        "model_identity": "MiniMax-M3",
        "provider_call_count": provider_call_count,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "payg_equivalent_cost_usd": payg_equivalent_cost_usd,
        "material_claim_support_verified": material_claim_support_verified,
        "citation_locator_valid": citation_locator_valid,
        "unsupported_accepted_claims": unsupported_accepted_claims,
        "repair_attempted": repair_attempted,
        "privacy": _privacy_counters(),
        "mutations": _mutation_counters(),
    }


def _retrieval_response_fields(
    *,
    gate: Mapping[str, Any],
    bundle: CanonicalReleaseBundle,
    lexical_result: Mapping[str, Any],
    dense_result: Mapping[str, Any],
    selected_evidence: Sequence[Mapping[str, Any]],
    intent_class: str,
) -> dict[str, Any]:
    dense_candidates = _list(dense_result.get("candidates"), "dense candidates")
    lexical_results = _list(lexical_result.get("results"), "lexical results")
    parent_expansion = _parent_expansion_summary(bundle, selected_evidence)
    graph_edges = _graph_edges(
        lexical_results,
        selected_evidence_ids={
            str(e["section_id"]) for e in selected_evidence if e.get("section_id")
        },
    )
    selected_graph_edges = [
        {
            "edge_id": str(item.get("edge_id", "")),
            "source": str(item.get("edge_source", "")),
            "target": str(item.get("edge_target", "")),
            "relation_type": str(item.get("relation_type", "")),
        }
        for item in selected_evidence
        if item.get("evidence_type") == "graph_edge"
    ]
    if selected_graph_edges:
        graph_edges = selected_graph_edges + [
            item for item in graph_edges if item.get("edge_id") not in {
                edge["edge_id"] for edge in selected_graph_edges
            }
        ]
    identities = _object(gate.get("production_identities"), "gate.production_identities")
    backend_identity = _object(dense_result.get("backend_identity"), "dense backend identity")
    source_identities = sorted(
        {
            _source_identity(item)
            for item in selected_evidence
            if item.get("evidence_type") != "graph_edge" or item.get("source_id")
        }
    )
    graph_derived_selected = [
        item
        for item in selected_evidence
        if item.get("evidence_type") == "graph_edge"
        or any(str(channel).startswith("graph_") for channel in item.get("channels", []))
    ]
    selected_relation_types = sorted(
        {
            str(relation)
            for item in selected_evidence
            for relation in _object(
                item.get("retrieval_metadata", {})
                if isinstance(item.get("retrieval_metadata"), Mapping)
                else {},
                "retrieval metadata",
            ).get("relation_types", [])
            if str(relation)
        }
        | {
            str(item.get("relation_type", ""))
            for item in selected_evidence
            if item.get("relation_type")
        }
    )
    selected_hops = [
        int(meta.get("graph_hop", 0))
        for item in selected_evidence
        for meta in [
            item.get("retrieval_metadata", {})
            if isinstance(item.get("retrieval_metadata"), Mapping)
            else {}
        ]
        if int(meta.get("graph_hop", 0)) > 0
    ]
    return {
        "production_release_id": bundle.release_id,
        "production_manifest_sha256": bundle.manifest_sha256,
        "production_pointer_digest": sha256_value(
            {
                "target": identities.get("final_production_pointer_target"),
                "release_id": bundle.release_id,
                "manifest_sha256": bundle.manifest_sha256,
            }
        ),
        "retrieval_backend_identity": {
            "lexical": {
                "artifact_sha256": bundle.artifact_sha256["lexical_index"],
                "release_id": bundle.release_id,
            },
            "dense": backend_identity,
            "graph_v2": {
                "artifact_sha256": bundle.artifact_sha256["graph_v2"],
                "release_id": bundle.release_id,
            },
            "provenance": {
                "artifact_sha256": bundle.artifact_sha256["provenance"],
                "release_id": bundle.release_id,
            },
        },
        "qdrant_collection": backend_identity.get("qdrant_collection"),
        "retrieval_mode_summary": {
            "actual_question_reaches_retrieval": True,
            "lexical": True,
            "dense": True,
            "graph": True,
            "provenance": True,
            "parent_expansion": parent_expansion["expanded_section_count"] > 0,
            "reranking": (
                "dynamic_candidate_pool_graph_distance_source_diversity_redundancy_penalty"
            ),
            "intent_class": intent_class,
            "multi_evidence_bundle": True,
            "dynamic_evidence_budget": True,
            "graph_expansion_default_for_ordinary_queries": True,
            "source_diversity": True,
            "redundancy_penalty": True,
        },
        "candidate_count_by_channel": {
            "lexical": len(lexical_results),
            "dense": len(dense_candidates),
            "seed": len(
                {str(item.get("section_id", "")) for item in lexical_results}
                | {str(item.get("section_id", "")) for item in dense_candidates}
            ),
            "combined_unique": len(
                {str(item.get("section_id", "")) for item in lexical_results}
                | {str(item.get("section_id", "")) for item in dense_candidates}
            ),
            "graph_expanded_selected": len(graph_derived_selected),
            "graph_edge_selected": len(
                [item for item in selected_evidence if item.get("evidence_type") == "graph_edge"]
            ),
        },
        "graph_hops_used": max(selected_hops or [len(graph_edges) if graph_edges else 0]),
        "graph_trace": graph_edges[:4],
        "graph_observability": {
            "selected_graph_derived_evidence_count": len(graph_derived_selected),
            "selected_graph_relation_types": selected_relation_types,
            "selected_graph_hop_counts": selected_hops,
        },
        "rerank_diversity_summary": {
            "selected_evidence_count": len(selected_evidence),
            "distinct_source_count": len(source_identities),
            "selected_source_redundancy": {
                source: count
                for source, count in Counter(
                    _source_identity(item) for item in selected_evidence
                ).items()
                if count > 1
            },
        },
        "parent_expansion": parent_expansion,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in selected_evidence],
        "selected_locator_ids": [str(item["locator_id"]) for item in selected_evidence],
        "selected_evidence": [_public_evidence_summary(item) for item in selected_evidence],
        "selected_evidence_count": len(selected_evidence),
        "distinct_source_count": len(source_identities),
        "distinct_source_identities": source_identities,
        "intent_class": intent_class,
    }


def _synthesize_and_verify(
    *,
    root: Path,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: ProviderClient,
) -> dict[str, Any]:
    policy = load_pa7_json(root / PA4_POLICY_PATH)
    calls: list[dict[str, Any]] = []
    failures: list[str] = []
    repair_attempted = False
    for attempt in (1, 2):
        payload = _build_multi_evidence_provider_payload(
            policy=policy,
            question=question,
            trace_id=trace_id,
            intent_class=intent_class,
            evidence=evidence,
            repair=attempt == 2,
            previous_reason_codes=failures,
        )
        try:
            result = provider_client.call(
                payload,
                "pa7_multi_evidence_query_repair" if attempt == 2 else "pa7_multi_evidence_query",
            )
            normalized = _normalize_provider_result(result)
            calls.append(normalized)
            verified = _verify_multi_evidence_provider_output(
                trace_id=trace_id,
                intent_class=intent_class,
                evidence=evidence,
                provider_text=normalized["provider_text"],
            )
            if verified["terminal_status"] == "safe_abstention":
                deterministic = _deterministic_evidence_synthesis(
                    trace_id=trace_id,
                    intent_class=intent_class,
                    evidence=evidence,
                    calls=calls,
                    repair_attempted=repair_attempted,
                    trigger_reason_codes=verified["reason_codes"],
                    allow_after_repair_failure=False,
                )
                if deterministic is not None:
                    return deterministic
                return _verified_abstention(
                    reason_codes=verified["reason_codes"],
                    calls=calls,
                    repair_attempted=repair_attempted,
                )
            return _verified_multi_evidence_answer(
                intent_class=intent_class,
                verified=verified,
                evidence=evidence,
                calls=calls,
                repair_attempted=repair_attempted,
            )
        except VerifiedAnswerGateError as exc:
            failures.append(exc.code)
            if attempt == 1:
                repair_attempted = True
                continue
            deterministic = _deterministic_evidence_synthesis(
                trace_id=trace_id,
                intent_class=intent_class,
                evidence=evidence,
                calls=calls,
                repair_attempted=True,
                trigger_reason_codes=[*failures, "BOUNDED_REPAIR_EXHAUSTED"],
                allow_after_repair_failure=True,
            )
            if deterministic is not None:
                return deterministic
            return _verified_abstention(
                reason_codes=[*failures, "BOUNDED_REPAIR_EXHAUSTED"],
                calls=calls,
                repair_attempted=True,
            )
        except (LiveGateError, httpx.HTTPError, KeyError, ValueError) as exc:
            return _verified_abstention(
                reason_codes=[type(exc).__name__, "PROVIDER_CALL_FAILED"],
                calls=calls,
                repair_attempted=repair_attempted,
            )
    return _verified_abstention(
        reason_codes=["BOUNDED_REPAIR_EXHAUSTED"],
        calls=calls,
        repair_attempted=True,
    )


def _deterministic_evidence_synthesis(
    *,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
    trigger_reason_codes: Sequence[str],
    allow_after_repair_failure: bool,
) -> dict[str, Any] | None:
    if allow_after_repair_failure and intent_class != "direct_grounded_knowledge":
        return None
    candidate = _deterministic_provider_candidate(intent_class=intent_class, evidence=evidence)
    if candidate is None:
        return None
    try:
        verified = _verify_multi_evidence_provider_output(
            trace_id=trace_id,
            intent_class=intent_class,
            evidence=evidence,
            provider_text=json.dumps(candidate, ensure_ascii=False, sort_keys=True),
        )
    except VerifiedAnswerGateError:
        return None
    answer = _verified_multi_evidence_answer(
        intent_class=intent_class,
        verified=verified,
        evidence=evidence,
        calls=calls,
        repair_attempted=repair_attempted,
    )
    if answer["status"] != "owner_only_cited_answer":
        return None
    answer["relationship_summary"] = {
        **dict(answer.get("relationship_summary", {})),
        "synthesis_source": "deterministic_verified_evidence_spans",
    }
    answer["multi_evidence_verification"] = {
        **dict(answer.get("multi_evidence_verification", {})),
        "deterministic_evidence_synthesis_used": True,
        "trigger_reason_codes": sorted({str(item) for item in trigger_reason_codes}),
    }
    return answer


def _deterministic_provider_candidate(
    *,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    passages = [item for item in evidence if item.get("evidence_type") == "passage"]
    relation = None
    role = "direct"
    selected: list[Mapping[str, Any]]
    if intent_class == "cross_document_comparison":
        selected = _first_distinct_source_items(passages, minimum=2)
        relation = "contrasts_with"
        role = "relationship"
    elif intent_class == "complementary_synthesis":
        selected = _first_distinct_source_items(passages, minimum=2)
        relation = "complements"
        role = "relationship"
    elif intent_class == "graph_relationship":
        selected = _deterministic_graph_items(evidence)
        graph_edge = next(
            (item for item in selected if item.get("evidence_type") == "graph_edge"),
            {},
        )
        relation = str(graph_edge.get("relation_type") or "depends_on")
        role = "relationship"
    elif intent_class == "provenance_source_trace":
        provenance = next(
            (item for item in evidence if item.get("evidence_type") == "provenance"),
            None,
        )
        if provenance is None or not passages:
            return None
        selected = [passages[0], provenance]
        role = "provenance"
    elif intent_class == "temporal_conflict":
        temporal = [
            item for item in evidence if item.get("evidence_type") == "temporal_record"
        ]
        selected = _first_distinct_source_items(temporal, minimum=2)
        relation = "precedes"
        role = "temporal"
    else:
        selected = _first_distinct_source_items(passages, minimum=1)
        if len(_first_distinct_source_items(passages, minimum=2)) >= 2:
            selected = _first_distinct_source_items(passages, minimum=2)
    if not selected:
        return None
    refs = [_deterministic_support_ref(item) for item in selected]
    if any(ref is None for ref in refs):
        return None
    return {
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in evidence],
        "claims": [
            {
                "claim_id": "claim_1",
                "claim_role": role,
                "support_refs": [ref for ref in refs if ref is not None],
            }
        ],
        "abstention_reason": None,
    }


def _first_distinct_source_items(
    items: Sequence[Mapping[str, Any]],
    *,
    minimum: int,
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        source = _source_identity(item)
        if source in seen:
            continue
        selected.append(item)
        seen.add(source)
        if len(selected) >= minimum:
            return selected
    if minimum <= 1 and items:
        return [items[0]]
    return []


def _deterministic_graph_items(
    evidence: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    graph_edge = next(
        (item for item in evidence if item.get("evidence_type") == "graph_edge"),
        None,
    )
    if graph_edge is None:
        return []
    endpoint_concepts = {
        str(graph_edge.get("edge_source", "")),
        str(graph_edge.get("edge_target", "")),
    }
    endpoints: list[Mapping[str, Any]] = []
    for item in evidence:
        if item.get("evidence_type") != "passage":
            continue
        if str(item.get("concept_id", "")) in endpoint_concepts:
            endpoints.append(item)
    if {str(item.get("concept_id", "")) for item in endpoints} != endpoint_concepts:
        return []
    return [graph_edge, *endpoints[:2]]


def _deterministic_support_ref(item: Mapping[str, Any]) -> dict[str, str] | None:
    quote = _first_exact_evidence_quote(str(item.get("passage_text", "")))
    if not quote:
        return None
    return {
        "evidence_id": str(item["evidence_id"]),
        "locator_id": str(item["locator_id"]),
        "exact_quote": quote,
    }


JSON_FENCE = re.compile(r"^```(?:json)?\s*\n(?P<body>.*?)\n```\s*$", re.DOTALL)


def _build_multi_evidence_provider_payload(
    *,
    policy: Mapping[str, Any],
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    repair: bool = False,
    previous_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    provider = _object(policy.get("provider"), "policy provider")
    budget = _object(policy.get("budget"), "policy budget")
    evidence_payload = [_provider_evidence_item(item) for item in evidence]
    task = {
        "stage_id": "M26.PA.7-FINAL-CORRECTIVE",
        "case_id": trace_id,
        "attempt_kind": "bounded_repair" if repair else "initial_multi_evidence_draft",
        "question": question,
        "intent_class": intent_class,
        "evidence_bundle": evidence_payload,
        "minimum_evidence_rule": _minimum_evidence_rule(intent_class),
        "previous_reason_codes": previous_reason_codes or [],
        "output_contract": {
            "status_values": sorted(PROVIDER_STATUS_VALUES),
            "relation_values": [
                "contrasts_with",
                "complements",
                "causes",
                "depends_on",
                "precedes",
                "supersedes",
                "same_as",
                "insufficient_basis",
                None,
            ],
            "required_json_keys": [
                "status",
                "relation",
                "selected_evidence_ids",
                "claims",
                "abstention_reason",
            ],
            "optional_json_keys": ["answer_text"],
            "claim_contract": (
                "For answer_candidate, each claim must contain claim_id, claim_role, and "
                "support_refs. Each support_ref must copy evidence_id, locator_id, and an "
                "exact_quote byte-for-byte from one supplied evidence text. You may also "
                "return answer_text as natural prose, but every material sentence must include "
                "one or more citation markers matching verified support refs such as "
                "[claim_1_ref_1]. Do not invent IDs, locators, graph edges, provenance fields, "
                "or quotations."
            ),
            "answer_candidate_json_example": {
                "status": "answer_candidate",
                "relation": "complements",
                "selected_evidence_ids": [item["evidence_id"] for item in evidence_payload[:2]],
                "answer_text": (
                    "The evidence indicates that the first component and second component "
                    "work together in the approved runtime path [claim_1_ref_1][claim_1_ref_2]."
                ),
                "claims": [
                    {
                        "claim_id": "claim_1",
                        "claim_role": "relationship",
                        "support_refs": [
                            {
                                "evidence_id": "COPY_SUPPLIED_EVIDENCE_ID",
                                "locator_id": "COPY_SUPPLIED_LOCATOR_ID",
                                "exact_quote": "COPY EXACT TEXT FROM THAT EVIDENCE",
                            }
                        ],
                    }
                ],
                "abstention_reason": None,
            },
            "abstain_json_example": {
                "status": "abstain",
                "relation": "insufficient_basis",
                "selected_evidence_ids": [],
                "claims": [],
                "abstention_reason": "INSUFFICIENT_SUPPORT",
            },
        },
        "forbidden": [
            "single-primary-passage shortcut for multi-evidence questions",
            "free-form citations",
            "unsupported material claims",
            "secret values",
            "public traffic",
            "production pointer mutation",
            "canonical writes",
        ],
    }
    return {
        "model": provider["model_id"],
        "max_tokens": budget["max_output_tokens_per_call"],
        "temperature": 0,
        "stream": False,
        "system": (
            "You are executing a bounded M26.PA.7 answer-quality task. Return one compact JSON "
            "object only. Write a natural, coherent answer_text when supported, then bind every "
            "material claim to supplied evidence IDs, locators, graph/provenance identities, and "
            "exact quotations. If the evidence bundle cannot satisfy the intent-specific rule, "
            "return status abstain."
        ),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(task, ensure_ascii=False, sort_keys=True),
                    }
                ],
            }
        ],
    }


def _provider_evidence_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": str(item["evidence_id"]),
        "evidence_type": str(item.get("evidence_type", "passage")),
        "locator_id": str(item["locator_id"]),
        "source_id": str(item.get("source_id", "")),
        "source_identity": _source_identity(item),
        "section_id": str(item.get("section_id", "")),
        "concept_id": str(item.get("concept_id", "")),
        "artifact_key": str(item.get("artifact_key", "")),
        "artifact_sha256": str(item.get("artifact_sha256", "")),
        "release_id": str(item.get("release_id", "")),
        "text_sha256": str(item.get("passage_text_sha256", "")),
        "text": str(item.get("passage_text", "")),
        "edge_id": str(item.get("edge_id", "")),
        "edge_source": str(item.get("edge_source", "")),
        "edge_target": str(item.get("edge_target", "")),
        "relation_type": str(item.get("relation_type", "")),
        "provenance_record_sha256": str(item.get("provenance_record_sha256", "")),
        "retrieved_at": str(item.get("retrieved_at", "")),
    }


def _minimum_evidence_rule(intent_class: str) -> dict[str, Any]:
    if intent_class == "cross_document_comparison":
        return {"minimum_evidence": 2, "minimum_distinct_source_identities": 2}
    if intent_class == "complementary_synthesis":
        return {"minimum_evidence": 2, "minimum_distinct_source_identities": 2}
    if intent_class == "graph_relationship":
        return {
            "minimum_evidence": 3,
            "requires_graph_edge": True,
            "requires_both_endpoint_evidence": True,
        }
    if intent_class == "provenance_source_trace":
        return {"minimum_evidence": 2, "requires_passage": True, "requires_provenance": True}
    if intent_class == "temporal_conflict":
        return {"minimum_evidence": 2, "minimum_distinct_source_or_version_identities": 2}
    return {"minimum_evidence": 1}


def _parse_multi_provider_json(text: str) -> dict[str, Any]:
    if len(text) > 12_000:
        raise _verification_failure("M26-PA7-ME-001", "provider output exceeded bounded length")
    stripped = text.strip()
    if not stripped:
        raise _verification_failure("M26-PA7-ME-002", "provider output is empty")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = JSON_FENCE.fullmatch(stripped)
        if match is None:
            raise _verification_failure(
                "M26-PA7-ME-003", "provider output is not one unambiguous JSON object"
            ) from None
        try:
            parsed = json.loads(match.group("body"))
        except json.JSONDecodeError as exc:
            raise _verification_failure("M26-PA7-ME-004", "provider JSON is malformed") from exc
    value = _object(parsed, "provider JSON")
    required = {"status", "relation", "selected_evidence_ids", "claims", "abstention_reason"}
    optional = {"answer_text"}
    if not required.issubset(value):
        raise _verification_failure("M26-PA7-ME-005", "provider JSON missing required fields")
    if set(value) - required - optional:
        raise _verification_failure("M26-PA7-ME-006", "provider JSON contains unknown fields")
    return dict(value)


def _verify_multi_evidence_provider_output(
    *,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_text: str,
) -> dict[str, Any]:
    if _secret_like(provider_text):
        raise _verification_failure("M26-PA7-ME-007", "provider output contains secret-like text")
    parsed = _parse_multi_provider_json(provider_text)
    status = parsed.get("status")
    if status not in PROVIDER_STATUS_VALUES:
        raise _verification_failure("M26-PA7-ME-008", "provider status is invalid")
    raw_selected = _list(parsed.get("selected_evidence_ids"), "selected_evidence_ids")
    selected_ids = [str(item) for item in raw_selected]
    evidence_by_id = {str(item["evidence_id"]): item for item in evidence}
    unknown_selected = sorted(set(selected_ids) - set(evidence_by_id))
    if unknown_selected:
        raise _verification_failure("M26-PA7-ME-009", "provider selected unknown evidence id")
    if status == "abstain":
        if parsed.get("claims") not in ([], None):
            raise _verification_failure("M26-PA7-ME-010", "abstention response contains claims")
        reason = str(parsed.get("abstention_reason") or "PROVIDER_ABSTAINED")
        return {
            "case_id": trace_id,
            "terminal_status": "safe_abstention",
            "reason_codes": sorted({reason}),
            "material_claims": [],
        }

    claims = _list(parsed.get("claims"), "provider claims")
    if not claims:
        raise _verification_failure("M26-PA7-ME-011", "answer candidate has no claims")
    claim_records: list[dict[str, Any]] = []
    used_evidence_ids: set[str] = set()
    used_graph_edges: set[str] = set()
    for index, raw_claim in enumerate(claims, start=1):
        claim = _object(raw_claim, "provider claim")
        required = {"claim_id", "claim_role", "support_refs"}
        if not required.issubset(claim):
            raise _verification_failure("M26-PA7-ME-012", "claim missing required fields")
        if set(claim) - required:
            raise _verification_failure("M26-PA7-ME-013", "claim contains unknown fields")
        claim_id = str(claim.get("claim_id") or f"claim_{index}")
        claim_role = str(claim.get("claim_role") or "direct")
        support_refs = _list(claim.get("support_refs"), "claim support refs")
        if not support_refs:
            raise _verification_failure("M26-PA7-ME-014", "claim has no support refs")
        ref_records: list[dict[str, Any]] = []
        for ref in support_refs:
            support = _object(ref, "claim support ref")
            ref_required = {"evidence_id", "locator_id", "exact_quote"}
            if not ref_required.issubset(support):
                raise _verification_failure("M26-PA7-ME-015", "support ref missing fields")
            if set(support) - ref_required:
                raise _verification_failure("M26-PA7-ME-016", "support ref contains unknown fields")
            evidence_id = str(support["evidence_id"])
            evidence_item = evidence_by_id.get(evidence_id)
            if evidence_item is None:
                raise _verification_failure("M26-PA7-ME-017", "support ref invented evidence id")
            if support["locator_id"] != evidence_item["locator_id"]:
                raise _verification_failure("M26-PA7-ME-018", "support ref locator mismatch")
            exact_quote = str(support["exact_quote"])
            if not exact_quote or len(exact_quote) > 800:
                raise _verification_failure("M26-PA7-ME-019", "support quote is invalid")
            evidence_text = str(evidence_item.get("passage_text", ""))
            start = evidence_text.find(exact_quote)
            if start < 0:
                raise _verification_failure(
                    "M26-PA7-ME-020",
                    "support quote is not exact evidence text",
                )
            used_evidence_ids.add(evidence_id)
            if evidence_item.get("evidence_type") == "graph_edge":
                used_graph_edges.add(str(evidence_item.get("edge_id", "")))
            ref_records.append(
                {
                    "evidence_id": evidence_id,
                    "locator_id": str(support["locator_id"]),
                    "exact_quote": exact_quote,
                    "exact_quote_sha256": sha256_bytes(exact_quote.encode("utf-8")),
                    "evidence_type": str(evidence_item.get("evidence_type", "passage")),
                    "source_identity": _source_identity(evidence_item),
                    "passage_span": {"start_char": start, "end_char": start + len(exact_quote)},
                }
            )
        if _claim_requires_multi_source(intent_class, claim_role) and _distinct_source_count(
            evidence_by_id[str(ref["evidence_id"])] for ref in ref_records
        ) < 2:
            raise _verification_failure("M26-PA7-ME-021", "relational claim lacks two sources")
        claim_records.append(
            {
                "claim_id": claim_id,
                "claim_role": claim_role,
                "material": True,
                "support_refs": ref_records,
                "support_verdict": "supported_exact_multi_evidence_bundle",
            }
        )
    _enforce_intent_minimums(
        intent_class=intent_class,
        evidence=[evidence_by_id[item] for item in used_evidence_ids],
    )
    selected_or_used = selected_ids or sorted(used_evidence_ids)
    if not set(used_evidence_ids).issubset(set(selected_or_used)):
        raise _verification_failure("M26-PA7-ME-022", "claim used evidence outside selection")
    return {
        "case_id": trace_id,
        "terminal_status": "verified_answer_ready_candidate",
        "relation": parsed.get("relation"),
        "answer_text": str(parsed.get("answer_text") or ""),
        "selected_evidence_ids": selected_or_used,
        "selected_graph_edge_ids": sorted(used_graph_edges),
        "material_claims": claim_records,
        "support_verification": {
            "material_claim_count": len(claim_records),
            "supported_claim_count": len(claim_records),
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
    }


def _enforce_intent_minimums(
    *,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> None:
    evidence_types = {str(item.get("evidence_type", "passage")) for item in evidence}
    if intent_class in {"cross_document_comparison", "complementary_synthesis"}:
        if len(evidence) < 2 or _distinct_source_count(evidence) < 2:
            raise _verification_failure("M26-PA7-ME-023", "multi-document intent used one source")
    elif intent_class == "graph_relationship":
        graph_edges = [item for item in evidence if item.get("evidence_type") == "graph_edge"]
        if not graph_edges:
            raise _verification_failure("M26-PA7-ME-024", "graph intent missing graph edge")
        endpoint_concepts = {
            str(item.get("concept_id", ""))
            for item in evidence
            if item.get("evidence_type") == "passage"
        }
        edge = graph_edges[0]
        if not {str(edge.get("edge_source")), str(edge.get("edge_target"))}.issubset(
            endpoint_concepts
        ):
            raise _verification_failure("M26-PA7-ME-025", "graph intent missing endpoint evidence")
    elif intent_class == "provenance_source_trace":
        if not {"passage", "provenance"}.issubset(evidence_types):
            raise _verification_failure(
                "M26-PA7-ME-026",
                "provenance intent missing passage/provenance",
            )
    elif intent_class == "temporal_conflict":
        source_or_version = {
            f"{_source_identity(item)}@{item.get('retrieved_at') or item.get('temporal_identity')}"
            for item in evidence
            if item.get("evidence_type") in {"passage", "temporal_record"}
        }
        if len(source_or_version) < 2:
            raise _verification_failure(
                "M26-PA7-ME-027",
                "temporal intent lacks two source/version identities",
            )


def _claim_requires_multi_source(intent_class: str, claim_role: str) -> bool:
    if claim_role in {"relationship", "temporal"}:
        return True
    return (
        intent_class in {"cross_document_comparison", "complementary_synthesis"}
        and claim_role in {"relationship", "comparison"}
    )


def _verification_failure(code: str, message: str) -> VerifiedAnswerGateError:
    return VerifiedAnswerGateError(code, message, category="integrity", retryable=True)


def _verified_multi_evidence_answer(
    *,
    intent_class: str,
    verified: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
) -> dict[str, Any]:
    evidence_by_id = {str(item["evidence_id"]): item for item in evidence}
    claim_texts: list[str] = []
    public_claims: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for claim in _list(verified.get("material_claims"), "verified material claims"):
        support_refs = _list(claim.get("support_refs"), "claim support refs")
        fragments = []
        for ref_index, ref in enumerate(support_refs, start=1):
            evidence_item = evidence_by_id[str(ref["evidence_id"])]
            exact_quote = str(ref["exact_quote"])
            fragments.append(exact_quote)
            citations.append(_public_citation(evidence_item, claim, ref, ref_index))
        claim_text = _render_claim_clause(claim, fragments)
        claim_texts.append(claim_text)
        public_claims.append(
            {
                "claim_id": str(claim["claim_id"]),
                "claim_role": str(claim["claim_role"]),
                "support_ref_count": len(support_refs),
                "source_identities": sorted(
                    {
                        _source_identity(evidence_by_id[str(ref["evidence_id"])])
                        for ref in support_refs
                    }
                ),
                "citation_ids": [
                    f"{claim['claim_id']}_ref_{index}" for index in range(1, len(support_refs) + 1)
                ],
            }
        )
    answer_text = _verified_natural_answer_text(
        verified.get("answer_text"),
        citations=citations,
        fallback=_render_answer(intent_class, str(verified.get("relation")), claim_texts),
    )
    if not answer_text:
        return _verified_abstention(
            reason_codes=["EMPTY_VERIFIED_CLAIM"],
            calls=calls,
            repair_attempted=repair_attempted,
        )
    return {
        "status": "owner_only_cited_answer",
        "terminal_status": str(verified["terminal_status"]),
        "answer_text": answer_text,
        "citations": citations,
        "answer_claims": public_claims,
        "relationship_summary": {
            "intent_class": intent_class,
            "relation": str(verified.get("relation") or "null"),
            "selected_evidence_ids": list(verified.get("selected_evidence_ids", [])),
            "selected_graph_edge_ids": list(verified.get("selected_graph_edge_ids", [])),
        },
        "multi_evidence_verification": {
            "claim_count": len(public_claims),
            "support_ref_count": sum(item["support_ref_count"] for item in public_claims),
            "distinct_source_count": len(
                {
                    source
                    for item in public_claims
                    for source in item["source_identities"]
                }
            ),
            "locator_validity": 1.0,
            "support_precision": 1.0,
            "unsupported_accepted_claims": 0,
            "single_primary_passage_used": False,
            "bounded_repair_attempted": repair_attempted,
        },
        "safe_abstention": False,
        "reason_codes": [],
        "provider_call_count": len(calls),
        "payg_equivalent_cost_usd": _calls_cost(calls),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": repair_attempted,
    }


def _verified_natural_answer_text(
    raw_answer: Any,
    *,
    citations: Sequence[Mapping[str, Any]],
    fallback: str,
) -> str:
    answer = str(raw_answer or "").strip()
    if not answer:
        return fallback
    if _secret_like(answer):
        return fallback
    citation_ids = {str(item.get("citation_id", "")) for item in citations}
    markers = set(re.findall(r"\[([A-Za-z0-9_]+_ref_\d+)\]", answer))
    if not markers or not markers.issubset(citation_ids):
        return fallback
    material_sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", answer)
        if item.strip() and not item.strip().startswith("Note:")
    ]
    if any(
        not re.search(r"\[[A-Za-z0-9_]+_ref_\d+\]", sentence)
        for sentence in material_sentences
    ):
        return fallback
    return answer


def _verified_abstention(
    *,
    reason_codes: Sequence[str],
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
) -> dict[str, Any]:
    return {
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "answer_text": "",
        "citations": [],
        "answer_claims": [],
        "relationship_summary": {},
        "multi_evidence_verification": {
            "claim_count": 0,
            "support_ref_count": 0,
            "distinct_source_count": 0,
            "locator_validity": 1.0,
            "support_precision": 1.0,
            "unsupported_accepted_claims": 0,
            "single_primary_passage_used": False,
            "bounded_repair_attempted": repair_attempted,
        },
        "safe_abstention": True,
        "reason_codes": sorted(set(str(item) for item in reason_codes)),
        "provider_call_count": len(calls),
        "payg_equivalent_cost_usd": _calls_cost(calls),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": repair_attempted,
    }


def _normalize_provider_result(result: Mapping[str, Any]) -> dict[str, Any]:
    provider_text = str(result.get("provider_text", result.get("text", "")))
    usage = result.get("usage", {})
    if not isinstance(usage, Mapping):
        usage = {}
    return {
        "provider_text": provider_text,
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(
                usage.get(
                    "total_tokens",
                    int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
                )
            ),
        },
        "cost_usd": str(result.get("cost_usd", "0")),
        "latency_ms": int(result.get("latency_ms", 0)),
        "response_id_sha256": canonical_sha256(str(result.get("response_id", ""))),
    }


def _pa4_case(
    *,
    question: str,
    trace_id: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "case_id": trace_id,
        "category": "pa7_arbitrary_owner_query",
        "material_claim_type": "runtime_selected_evidence_span",
        "question": {
            "raw_corpus_text_in_question": False,
            "template_id": "pa7_arbitrary_owner_query",
            "text": question,
            "text_sha256": sha256_bytes(question.encode("utf-8")),
        },
        "expected_terminal_policy": "answerable",
        "passage_locator": {
            "locator_id": evidence["locator_id"],
            "source_id": evidence["source_id"],
            "section_id": evidence["section_id"],
            "text_sha256": evidence["passage_text_sha256"],
            "artifact_key": evidence["artifact_key"],
            "release_id": evidence["release_id"],
            "artifact_sha256": evidence["artifact_sha256"],
        },
    }


def _select_evidence(
    *,
    bundle: CanonicalReleaseBundle,
    lexical_result: Mapping[str, Any],
    dense_result: Mapping[str, Any],
    trace_id: str,
    question: str,
    intent_class: str,
) -> list[dict[str, Any]]:
    documents = {str(item["section_id"]): item for item in _release_documents(bundle)}
    lexical_results = _list(lexical_result.get("results"), "lexical results")
    candidates = _build_candidate_pool(
        bundle=bundle,
        documents=documents,
        lexical_results=lexical_results,
        dense_candidates=_list(dense_result.get("candidates"), "dense candidates"),
        question=question,
        intent_class=intent_class,
    )
    budget = _dynamic_evidence_budget(question=question, intent_class=intent_class)
    ordered = _rerank_candidates(candidates, budget=budget)
    selected_candidates = _select_diverse_candidates(ordered, budget=budget)
    evidence = []
    for index, candidate in enumerate(selected_candidates, start=1):
        document = documents[candidate["section_id"]]
        lexical = candidate.get("lexical") if isinstance(candidate.get("lexical"), Mapping) else {}
        evidence.append(
            _evidence_item(
                bundle=bundle,
                document=document,
                lexical_result=lexical,
                trace_id=trace_id,
                ordinal=index,
                channels=sorted(candidate["channels"]),
                retrieval_metadata=_candidate_public_metadata(candidate),
            )
        )
    return _augment_evidence_for_intent(
        bundle=bundle,
        base_evidence=evidence,
        lexical_results=lexical_results,
        trace_id=trace_id,
        intent_class=intent_class,
        budget=budget,
    )


def _build_candidate_pool(
    *,
    bundle: CanonicalReleaseBundle,
    documents: Mapping[str, Mapping[str, Any]],
    lexical_results: Sequence[Any],
    dense_candidates: Sequence[Any],
    question: str,
    intent_class: str,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(lexical_results, start=1):
        section_id = str(item.get("section_id", ""))
        if section_id not in documents:
            continue
        candidate = candidates.setdefault(section_id, _empty_candidate(section_id))
        candidate["lexical"] = dict(item)
        candidate["channels"].add("lexical")
        candidate["score"] += float(item.get("score", 0)) + 1.0 / rank
        candidate["seed_rank"] = min(int(candidate.get("seed_rank", 999)), rank)
    for rank, item in enumerate(dense_candidates, start=1):
        section_id = str(item.get("section_id", ""))
        if section_id not in documents:
            continue
        candidate = candidates.setdefault(section_id, _empty_candidate(section_id))
        candidate["channels"].add("dense")
        candidate["score"] += float(item.get("score", 0.0)) + 0.5 / rank
        candidate["dense"] = dict(item)
        candidate["seed_rank"] = min(int(candidate.get("seed_rank", 999)), rank)
    _add_graph_expanded_candidates(
        bundle=bundle,
        documents=documents,
        candidates=candidates,
        question=question,
        intent_class=intent_class,
    )
    return sorted(
        candidates.values(),
        key=lambda item: (-float(item["score"]), item["section_id"]),
    )[:MAX_CANDIDATE_POOL_ITEMS]


def _empty_candidate(section_id: str) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "lexical": {},
        "channels": set(),
        "score": 0.0,
        "seed_rank": 999,
        "graph_hop": 0,
        "graph_edges": [],
        "relation_types": set(),
    }


def _add_graph_expanded_candidates(
    *,
    bundle: CanonicalReleaseBundle,
    documents: Mapping[str, Mapping[str, Any]],
    candidates: dict[str, dict[str, Any]],
    question: str,
    intent_class: str,
) -> None:
    by_concept: dict[str, list[Mapping[str, Any]]] = {}
    for document in documents.values():
        by_concept.setdefault(str(document.get("concept_id", "")), []).append(document)
    doc_by_concept = {concept: docs[0] for concept, docs in by_concept.items() if docs}
    concept_seed_scores: dict[str, float] = {}
    for candidate in candidates.values():
        document = documents.get(str(candidate.get("section_id", "")))
        if not document:
            continue
        concept_id = str(document.get("concept_id", ""))
        concept_seed_scores[concept_id] = max(
            concept_seed_scores.get(concept_id, 0.0),
            float(candidate.get("score", 0.0)),
        )
    if not concept_seed_scores:
        return
    query_terms = _meaningful_terms(question)
    relation_index: dict[str, list[Mapping[str, Any]]] = {}
    for edge in bundle.graph_v2.get("edges", []):
        if not isinstance(edge, Mapping) or not _edge_has_endpoint_documents(edge, bundle):
            continue
        relation_index.setdefault(str(edge.get("source", "")), []).append(edge)
        relation_index.setdefault(str(edge.get("target", "")), []).append(edge)
    frontier = sorted(concept_seed_scores.items(), key=lambda item: (-item[1], item[0]))[:10]
    _expand_graph_hop(
        documents=documents,
        doc_by_concept=doc_by_concept,
        candidates=candidates,
        relation_index=relation_index,
        frontier=frontier,
        query_terms=query_terms,
        hop=1,
    )
    if _allow_second_hop(question=question, intent_class=intent_class):
        second_frontier = [
            (
                str(edge.get("target" if str(edge.get("source")) == concept else "source", "")),
                score * 0.65,
            )
            for concept, score in frontier[:6]
            for edge in relation_index.get(concept, [])[:4]
        ][:16]
        _expand_graph_hop(
            documents=documents,
            doc_by_concept=doc_by_concept,
            candidates=candidates,
            relation_index=relation_index,
            frontier=second_frontier,
            query_terms=query_terms,
            hop=2,
        )


def _expand_graph_hop(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    doc_by_concept: Mapping[str, Mapping[str, Any]],
    candidates: dict[str, dict[str, Any]],
    relation_index: Mapping[str, Sequence[Mapping[str, Any]]],
    frontier: Sequence[tuple[str, float]],
    query_terms: set[str],
    hop: int,
) -> None:
    channel = f"graph_{hop}hop"
    for seed_concept, seed_score in frontier:
        for edge in relation_index.get(seed_concept, [])[:6]:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            neighbour = target if source == seed_concept else source
            document = doc_by_concept.get(neighbour)
            if not document:
                continue
            section_id = str(document.get("section_id", ""))
            relevance = _text_term_overlap_score(query_terms, _document_text(document))
            confidence = float(edge.get("confidence", 0.0) or 0.0)
            hop_weight = 0.55 if hop == 1 else 0.3
            graph_score = seed_score * hop_weight + confidence + relevance
            if hop == 2 and relevance <= 0 and confidence < 0.85:
                continue
            candidate = candidates.setdefault(section_id, _empty_candidate(section_id))
            candidate["channels"].add(channel)
            candidate["score"] += graph_score
            candidate["graph_hop"] = min(
                int(candidate.get("graph_hop") or hop),
                hop,
            )
            candidate["graph_edges"].append(dict(edge))
            candidate["relation_types"].add(str(edge.get("relation_type", "")))
            candidate.setdefault("graph_seed_concepts", set()).add(seed_concept)


def _dynamic_evidence_budget(*, question: str, intent_class: str) -> int:
    terms = _meaningful_terms(question)
    if intent_class in {
        "graph_relationship",
        "cross_document_comparison",
        "complementary_synthesis",
    }:
        base = 10
    elif (
        intent_class in {"temporal_conflict", "provenance_source_trace"}
        or len(terms) >= 8
        or any(term in terms for term in {"explain", "how", "why"})
    ):
        base = 8
    else:
        base = 5
    if len(terms) >= 12:
        base += 2
    return max(4, min(base, MAX_DYNAMIC_EVIDENCE_ITEMS))


def _rerank_candidates(
    candidates: Sequence[Mapping[str, Any]], *, budget: int
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        channel_count = len(item.get("channels", []))
        hop = int(item.get("graph_hop") or 0)
        graph_bonus = 0.35 if hop == 1 else 0.15 if hop == 2 else 0.0
        item["rerank_score"] = float(item.get("score", 0.0)) + channel_count * 0.35 + graph_bonus
        ordered.append(item)
    return sorted(
        ordered,
        key=lambda item: (
            -float(item["rerank_score"]),
            int(item.get("graph_hop") or 99),
            int(item.get("seed_rank", 999)),
            str(item["section_id"]),
        ),
    )[: max(MAX_CANDIDATE_POOL_ITEMS, budget)]


def _select_diverse_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    budget: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    concept_counts: Counter[str] = Counter()
    for candidate in candidates:
        section_id = str(candidate["section_id"])
        source_key = section_id.split("#", 1)[0]
        concept_key = source_key
        if source_counts[source_key] >= 2 or concept_counts[concept_key] >= 3:
            continue
        selected.append(dict(candidate))
        source_counts[source_key] += 1
        concept_counts[concept_key] += 1
        if len(selected) >= budget:
            break
    if len(selected) < min(budget, len(candidates)):
        seen = {str(item["section_id"]) for item in selected}
        for candidate in candidates:
            if str(candidate["section_id"]) in seen:
                continue
            selected.append(dict(candidate))
            if len(selected) >= budget:
                break
    return selected


def _candidate_public_metadata(candidate: Mapping[str, Any]) -> dict[str, Any]:
    graph_edges = [
        {
            "edge_id": str(edge.get("edge_id", "")),
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
            "relation_type": str(edge.get("relation_type", "")),
            "confidence": edge.get("confidence"),
        }
        for edge in candidate.get("graph_edges", [])
        if isinstance(edge, Mapping)
    ]
    return {
        "rerank_score": round(float(candidate.get("rerank_score", candidate.get("score", 0.0))), 6),
        "graph_hop": int(candidate.get("graph_hop") or 0),
        "graph_edges": graph_edges[:4],
        "relation_types": sorted(
            {str(item) for item in candidate.get("relation_types", set()) if item}
        ),
        "graph_seed_concepts": sorted(
            {str(item) for item in candidate.get("graph_seed_concepts", set()) if item}
        )[:6],
    }


def _augment_evidence_for_intent(
    *,
    bundle: CanonicalReleaseBundle,
    base_evidence: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Any],
    trace_id: str,
    intent_class: str,
    budget: int,
) -> list[dict[str, Any]]:
    evidence = [dict(item) for item in base_evidence]
    if intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
        "temporal_conflict",
    }:
        evidence = _ensure_distinct_passage_sources(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            minimum=2,
            limit=budget,
        )
    if intent_class == "graph_relationship":
        evidence = _graph_evidence_bundle(
            bundle=bundle,
            evidence=evidence,
            lexical_results=lexical_results,
            trace_id=trace_id,
            limit=budget,
        )
    elif intent_class == "provenance_source_trace":
        evidence = _provenance_evidence_bundle(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            limit=budget,
        )
    elif intent_class == "temporal_conflict":
        evidence = _temporal_evidence_bundle(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            limit=budget,
        )
    return _dedupe_evidence(evidence)[:budget]


def _evidence_item(
    *,
    bundle: CanonicalReleaseBundle,
    document: Mapping[str, Any],
    lexical_result: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
    channels: Sequence[str],
    retrieval_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    section_id = str(document["section_id"])
    passage = _bounded_text(str(document.get("body") or document.get("excerpt") or ""))
    passage_sha = sha256_bytes(passage.encode("utf-8"))
    locator_id = "m26pa7loc_" + canonical_sha256(
        {
            "trace_id": trace_id,
            "section_id": section_id,
            "passage_sha256": passage_sha,
        }
    )[:32]
    evidence_id = "m26pa7ev_" + canonical_sha256(
        {
            "trace_id": trace_id,
            "ordinal": ordinal,
            "locator_id": locator_id,
            "channels": list(channels),
        }
    )[:32]
    citation = _first_citation(lexical_result, document)
    record = _provenance_records_by_concept(bundle).get(str(document["concept_id"]), {})
    source_identity = _citation_source_identity(citation, section_id)
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": "pilot/m24/canonical-release/artifacts/lexical-index.json",
        "artifact_sha256": bundle.artifact_sha256["lexical_index"],
        "concept_id": str(document["concept_id"]),
        "section_id": section_id,
        "source_id": citation["source_id"],
        "source_identity": source_identity,
        "source_uri_sha256": canonical_sha256(citation.get("uri", "")),
        "retrieved_at": citation.get("retrieved_at", ""),
        "title": str(document.get("title", "")),
        "section_title": str(document.get("section_title", "")),
        "channels": list(channels),
        "passage_text": passage,
        "passage_text_sha256": passage_sha,
        "provenance_record_sha256": canonical_sha256(record) if record else "",
        "relation_expansions": list(lexical_result.get("relation_expansions", []))
        if isinstance(lexical_result, Mapping)
        else [],
        "retrieval_metadata": dict(retrieval_metadata or {}),
    }


def _ensure_distinct_passage_sources(
    *,
    bundle: CanonicalReleaseBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    minimum: int,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    selected_sections = {str(item.get("section_id", "")) for item in selected}
    source_identities = {_source_identity(item) for item in selected}
    if len(source_identities) >= minimum:
        return selected
    ordinal = len(selected) + 1
    for document in _release_documents(bundle):
        section_id = str(document.get("section_id", ""))
        if section_id in selected_sections:
            continue
        item = _evidence_item(
            bundle=bundle,
            document=document,
            lexical_result={},
            trace_id=trace_id,
            ordinal=ordinal,
            channels=["release_distinct_source"],
        )
        if _source_identity(item) in source_identities:
            continue
        selected.append(item)
        selected_sections.add(section_id)
        source_identities.add(_source_identity(item))
        ordinal += 1
        if len(source_identities) >= minimum or len(selected) >= limit:
            break
    return selected


def _graph_evidence_bundle(
    *,
    bundle: CanonicalReleaseBundle,
    evidence: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Any],
    trace_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    passages = [dict(item) for item in evidence if item.get("evidence_type") == "passage"]
    edge = _first_authoritative_edge(passages, lexical_results, bundle)
    if edge is None:
        return passages
    endpoint_passages = _endpoint_passages(
        bundle=bundle,
        existing=passages,
        edge=edge,
        trace_id=trace_id,
        start_ordinal=len(passages) + 1,
    )
    graph_item = _graph_edge_evidence_item(
        bundle=bundle,
        edge=edge,
        trace_id=trace_id,
        ordinal=len(endpoint_passages) + 1,
    )
    # Keep the edge visible, followed by both endpoints, while staying inside the dynamic bound.
    ordered = [graph_item, *endpoint_passages]
    for item in passages:
        if len(ordered) >= limit:
            break
        if str(item["evidence_id"]) not in {str(existing["evidence_id"]) for existing in ordered}:
            ordered.append(item)
    return ordered


def _first_authoritative_edge(
    passages: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Any],
    bundle: CanonicalReleaseBundle,
) -> Mapping[str, Any] | None:
    for item in passages:
        for edge in item.get("relation_expansions", []):
            if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
                return edge
    for result in lexical_results:
        if not isinstance(result, Mapping):
            continue
        for edge in result.get("relation_expansions", []):
            if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
                return edge
    for edge in bundle.graph_v2.get("edges", []):
        if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
            return edge
    return None


def _edge_has_endpoint_documents(edge: Mapping[str, Any], bundle: CanonicalReleaseBundle) -> bool:
    concepts = {str(document.get("concept_id", "")) for document in _release_documents(bundle)}
    return str(edge.get("source", "")) in concepts and str(edge.get("target", "")) in concepts


def _endpoint_passages(
    *,
    bundle: CanonicalReleaseBundle,
    existing: Sequence[Mapping[str, Any]],
    edge: Mapping[str, Any],
    trace_id: str,
    start_ordinal: int,
) -> list[dict[str, Any]]:
    by_concept: dict[str, list[Mapping[str, Any]]] = {}
    for document in _release_documents(bundle):
        by_concept.setdefault(str(document.get("concept_id", "")), []).append(document)
    existing_by_concept = {
        str(item.get("concept_id", "")): dict(item)
        for item in existing
        if item.get("evidence_type") == "passage"
    }
    endpoint_items: list[dict[str, Any]] = []
    ordinal = start_ordinal
    for concept_id in (str(edge.get("source", "")), str(edge.get("target", ""))):
        if concept_id in existing_by_concept:
            endpoint_items.append(existing_by_concept[concept_id])
            continue
        documents = by_concept.get(concept_id, [])
        if not documents:
            continue
        endpoint_items.append(
            _evidence_item(
                bundle=bundle,
                document=documents[0],
                lexical_result={},
                trace_id=trace_id,
                ordinal=ordinal,
                channels=["graph_endpoint"],
            )
        )
        ordinal += 1
    return endpoint_items


def _graph_edge_evidence_item(
    *,
    bundle: CanonicalReleaseBundle,
    edge: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id", ""))
    source = str(edge.get("source", ""))
    target = str(edge.get("target", ""))
    relation_type = str(edge.get("relation_type", "related_to"))
    statement = (
        f"Graph edge {edge_id} states {source} {relation_type} {target} "
        f"with confidence {edge.get('confidence')} and review "
        f"{edge.get('review_status', 'approved')}."
    )
    text_sha = sha256_bytes(statement.encode("utf-8"))
    locator_id = "m26pa7edge_" + canonical_sha256(
        {"trace_id": trace_id, "edge_id": edge_id, "statement_sha256": text_sha}
    )[:32]
    evidence_id = "m26pa7ev_" + canonical_sha256(
        {"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id}
    )[:32]
    return {
        "evidence_id": evidence_id,
        "evidence_type": "graph_edge",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": "pilot/m24/canonical-release/artifacts/graph-v2.json",
        "artifact_sha256": bundle.artifact_sha256["graph_v2"],
        "concept_id": source,
        "section_id": edge_id,
        "source_id": f"graph_v2:{edge_id}",
        "source_identity": f"graph_v2:{edge_id}",
        "title": "Graph relationship",
        "section_title": relation_type,
        "channels": ["graph"],
        "passage_text": statement,
        "passage_text_sha256": text_sha,
        "edge_id": edge_id,
        "edge_source": source,
        "edge_target": target,
        "relation_type": relation_type,
        "provenance_record_sha256": canonical_sha256(str(edge.get("provenance_ref", ""))),
        "retrieved_at": "",
    }


def _provenance_evidence_bundle(
    *,
    bundle: CanonicalReleaseBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    for passage in selected:
        if passage.get("evidence_type") != "passage":
            continue
        record = _provenance_records_by_concept(bundle).get(str(passage.get("concept_id", "")))
        if not record:
            continue
        provenance_item = _provenance_evidence_item(
            bundle=bundle,
            record=record,
            passage=passage,
            trace_id=trace_id,
            ordinal=len(selected) + 1,
        )
        if len(selected) >= limit:
            selected = selected[: max(limit - 1, 1)]
        selected.append(provenance_item)
        break
    return selected[:limit]


def _provenance_evidence_item(
    *,
    bundle: CanonicalReleaseBundle,
    record: Mapping[str, Any],
    passage: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
) -> dict[str, Any]:
    subject = record.get("subject") if isinstance(record.get("subject"), Mapping) else {}
    claims = record.get("claims") if isinstance(record.get("claims"), list) else []
    first_claim = claims[0] if claims and isinstance(claims[0], Mapping) else {}
    claim_id = str(first_claim.get("claim_id", "provenance_claim"))
    claim_text = str(first_claim.get("text", "Provenance record is present for this concept."))
    statement = (
        f"Provenance record for {subject.get('concept_id', passage.get('concept_id'))} "
        f"contains {claim_id}: {claim_text}"
    )
    text_sha = sha256_bytes(statement.encode("utf-8"))
    locator_id = "m26pa7prov_" + canonical_sha256(
        {"trace_id": trace_id, "passage": passage["evidence_id"], "statement_sha256": text_sha}
    )[:32]
    evidence_id = "m26pa7ev_" + canonical_sha256(
        {"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id}
    )[:32]
    return {
        "evidence_id": evidence_id,
        "evidence_type": "provenance",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": "pilot/m24/canonical-release/artifacts/provenance.json",
        "artifact_sha256": bundle.artifact_sha256["provenance"],
        "concept_id": str(subject.get("concept_id", passage.get("concept_id", ""))),
        "section_id": f"provenance#{claim_id}",
        "source_id": f"provenance:{claim_id}",
        "source_identity": f"provenance:{claim_id}",
        "title": "Provenance",
        "section_title": claim_id,
        "channels": ["provenance"],
        "passage_text": statement,
        "passage_text_sha256": text_sha,
        "provenance_record_sha256": canonical_sha256(record),
        "retrieved_at": "",
    }


def _temporal_evidence_bundle(
    *,
    bundle: CanonicalReleaseBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    passage_items = [item for item in selected if item.get("evidence_type") == "passage"][:2]
    if len(selected) + len(passage_items) > limit:
        selected = selected[: max(limit - len(passage_items), 1)]
    for item in passage_items:
        if item.get("evidence_type") != "passage":
            continue
        temporal_item = _temporal_record_evidence_item(
            bundle=bundle,
            passage=item,
            trace_id=trace_id,
            ordinal=len(selected) + 1,
        )
        selected.append(temporal_item)
        if len(selected) >= limit:
            break
    return selected


def _temporal_record_evidence_item(
    *,
    bundle: CanonicalReleaseBundle,
    passage: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
) -> dict[str, Any]:
    temporal_identity = str(passage.get("retrieved_at") or "unknown-retrieved-at")
    statement = (
        f"Temporal record for {passage.get('source_id')} section {passage.get('section_id')} "
        f"was retrieved at {temporal_identity} in release {bundle.release_id}."
    )
    text_sha = sha256_bytes(statement.encode("utf-8"))
    locator_id = "m26pa7time_" + canonical_sha256(
        {"trace_id": trace_id, "passage": passage["evidence_id"], "statement_sha256": text_sha}
    )[:32]
    evidence_id = "m26pa7ev_" + canonical_sha256(
        {"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id}
    )[:32]
    return {
        "evidence_id": evidence_id,
        "evidence_type": "temporal_record",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": "pilot/m24/canonical-release/artifacts/provenance.json",
        "artifact_sha256": bundle.artifact_sha256["provenance"],
        "concept_id": str(passage.get("concept_id", "")),
        "section_id": f"temporal#{passage.get('section_id', '')}",
        "source_id": f"temporal:{passage.get('source_id', '')}",
        "source_identity": f"{_source_identity(passage)}@{temporal_identity}",
        "title": "Temporal record",
        "section_title": temporal_identity,
        "channels": ["temporal"],
        "passage_text": statement,
        "passage_text_sha256": text_sha,
        "temporal_identity": temporal_identity,
        "provenance_record_sha256": str(passage.get("provenance_record_sha256", "")),
        "retrieved_at": temporal_identity,
    }


def _dedupe_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        evidence_id = str(item.get("evidence_id", ""))
        if not evidence_id or evidence_id in seen:
            continue
        deduped.append(dict(item))
        seen.add(evidence_id)
    return deduped


def _public_citation(
    evidence: Mapping[str, Any],
    claim: Mapping[str, Any],
    support_ref: Mapping[str, Any],
    ref_index: int,
) -> dict[str, Any]:
    return {
        "citation_id": f"{claim.get('claim_id', 'claim_1')}_ref_{ref_index}",
        "claim_id": str(claim.get("claim_id", "claim_1")),
        "claim_role": str(claim.get("claim_role", "direct")),
        "evidence_id": evidence["evidence_id"],
        "evidence_type": str(evidence.get("evidence_type", "passage")),
        "locator_id": evidence["locator_id"],
        "source_id": evidence["source_id"],
        "section_id": evidence["section_id"],
        "concept_id": evidence["concept_id"],
        "release_id": evidence["release_id"],
        "source_locator": f"{evidence['artifact_key']}#{evidence['section_id']}",
        "support_text_sha256": evidence["passage_text_sha256"],
        "exact_quote_sha256": support_ref["exact_quote_sha256"],
        "source_artifact_sha256": evidence["artifact_sha256"],
        "provenance_record_sha256": evidence["provenance_record_sha256"],
        "source_identity": _source_identity(evidence),
        "runtime_owned_locator": True,
    }


def _first_citation(
    lexical_result: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    citations = lexical_result.get("citations") if isinstance(lexical_result, Mapping) else None
    if isinstance(citations, list) and citations and isinstance(citations[0], Mapping):
        return dict(citations[0])
    return {
        "source_id": str(document.get("concept_id", "unknown")),
        "uri": str(document.get("section_id", "unknown")),
        "retrieved_at": "",
    }


def _citation_source_identity(citation: Mapping[str, Any], fallback: str) -> str:
    source_id = str(citation.get("source_id") or "").strip()
    uri = str(citation.get("uri") or "").strip()
    if source_id:
        return source_id
    if uri:
        return "uri:" + canonical_sha256(uri)[:16]
    return "section:" + fallback


def _source_identity(evidence: Mapping[str, Any]) -> str:
    explicit = str(evidence.get("source_identity") or "").strip()
    if explicit:
        return explicit
    source_id = str(evidence.get("source_id") or "").strip()
    if source_id:
        return source_id
    return f"{evidence.get('artifact_key', 'artifact')}#{evidence.get('section_id', '')}"


def _distinct_source_count(evidence: Sequence[Mapping[str, Any]]) -> int:
    return len({_source_identity(item) for item in evidence})


def _public_evidence_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "evidence_id": str(evidence["evidence_id"]),
        "evidence_type": str(evidence.get("evidence_type", "passage")),
        "locator_id": str(evidence["locator_id"]),
        "source_id": str(evidence.get("source_id", "")),
        "source_identity": _source_identity(evidence),
        "section_id": str(evidence.get("section_id", "")),
        "concept_id": str(evidence.get("concept_id", "")),
        "artifact_key": str(evidence.get("artifact_key", "")),
        "artifact_sha256": str(evidence.get("artifact_sha256", "")),
        "release_id": str(evidence.get("release_id", "")),
        "text_sha256": str(evidence.get("passage_text_sha256", "")),
        "channels": list(evidence.get("channels", [])),
    }
    if isinstance(evidence.get("retrieval_metadata"), Mapping):
        summary["retrieval_metadata"] = dict(evidence["retrieval_metadata"])
    if evidence.get("evidence_type") == "graph_edge":
        summary.update(
            {
                "edge_id": str(evidence.get("edge_id", "")),
                "edge_source": str(evidence.get("edge_source", "")),
                "edge_target": str(evidence.get("edge_target", "")),
                "relation_type": str(evidence.get("relation_type", "")),
            }
        )
    if evidence.get("evidence_type") == "temporal_record":
        summary["temporal_identity"] = str(evidence.get("temporal_identity", ""))
    return summary


def _parent_expansion_summary(
    bundle: CanonicalReleaseBundle,
    selected_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_concept: dict[str, list[str]] = {}
    for document in _release_documents(bundle):
        by_concept.setdefault(str(document["concept_id"]), []).append(str(document["section_id"]))
    expanded: list[dict[str, Any]] = []
    for evidence in selected_evidence:
        if evidence.get("evidence_type") != "passage":
            continue
        section_id = str(evidence["section_id"])
        siblings = [
            item
            for item in sorted(by_concept.get(str(evidence["concept_id"]), []))
            if item != section_id
        ][:MAX_PARENT_SECTIONS_PER_EVIDENCE]
        if siblings:
            expanded.append(
                {
                    "evidence_id": evidence["evidence_id"],
                    "parent_concept_id": evidence["concept_id"],
                    "sibling_section_ids": siblings,
                }
            )
    return {
        "enabled": True,
        "max_siblings_per_evidence": MAX_PARENT_SECTIONS_PER_EVIDENCE,
        "expanded_section_count": sum(len(item["sibling_section_ids"]) for item in expanded),
        "items": expanded,
    }


def _graph_edges(
    lexical_results: Sequence[Any],
    *,
    selected_evidence_ids: set[str],
) -> list[dict[str, Any]]:
    edges = []
    for result in lexical_results:
        if not isinstance(result, Mapping):
            continue
        section_id = str(result.get("section_id", ""))
        if selected_evidence_ids and section_id not in selected_evidence_ids:
            continue
        for edge in result.get("relation_expansions", []):
            if not isinstance(edge, Mapping):
                continue
            edges.append(
                {
                    "edge_id": str(edge.get("edge_id", "")),
                    "source": str(edge.get("source", "")),
                    "target": str(edge.get("target", "")),
                    "relation_type": str(edge.get("relation_type", "")),
                    "confidence": edge.get("confidence"),
                    "provenance_ref_sha256": canonical_sha256(str(edge.get("provenance_ref", ""))),
                }
            )
    return edges


def _provenance_records_by_concept(bundle: CanonicalReleaseBundle) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for record in bundle.provenance.get("records", []):
        if not isinstance(record, Mapping):
            continue
        subject = record.get("subject")
        if isinstance(subject, Mapping) and isinstance(subject.get("concept_id"), str):
            records[str(subject["concept_id"])] = record
    return records


def _release_documents(bundle: CanonicalReleaseBundle) -> list[dict[str, Any]]:
    documents = bundle.lexical_index.get("documents")
    if not isinstance(documents, list):
        raise PA7ArbitraryQueryError("PA7_LEXICAL_INDEX_INVALID", "documents missing")
    return [dict(document) for document in documents if isinstance(document, Mapping)]


def _hashed_vector(text: str) -> list[float]:
    values = [0.0] * LOCAL_DENSE_DIMENSION
    tokens = [item.casefold() for item in TOKEN_RE.findall(text)]
    counts = Counter(token for token in tokens if token not in STOP_TERMS)
    for token, count in counts.items():
        index = int(canonical_sha256(token)[:8], 16) % LOCAL_DENSE_DIMENSION
        values[index] += float(count)
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return values
    return [value / norm for value in values]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _bounded_text(text: str, *, max_bytes: int = 1800) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized.encode("utf-8")) <= max_bytes:
        return normalized
    result = ""
    for character in normalized:
        if len((result + character).encode("utf-8")) > max_bytes:
            break
        result += character
    return result.rstrip()


def _first_exact_evidence_quote(text: str, *, max_chars: int = 760) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    for delimiter in (". ", "\n"):
        index = normalized.find(delimiter)
        if index >= 0:
            end = index + (1 if delimiter == ". " else 0)
            quote = normalized[:end].strip()
            break
    else:
        quote = normalized
    if len(quote) <= max_chars:
        return quote
    return quote[:max_chars].rstrip()


def _looks_like_prompt_injection(question: str) -> bool:
    return any(pattern.search(question) for pattern in PROMPT_INJECTION_PATTERNS)


def _intent_class(question: str) -> str:
    for intent, patterns in INTENT_PATTERNS:
        if any(pattern.search(question) for pattern in patterns):
            return intent
    return "direct_grounded_knowledge"


def _secret_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_VALUE_PATTERNS)


def _render_claim_clause(claim: Mapping[str, Any], fragments: Sequence[str]) -> str:
    claim_id = str(claim.get("claim_id", "claim"))
    cited_fragments = [
        f"{fragment} [{claim_id}_ref_{index}]"
        for index, fragment in enumerate(fragments, start=1)
    ]
    if str(claim.get("claim_role")) in {"relationship", "temporal"}:
        return "; ".join(cited_fragments)
    return " ".join(cited_fragments)


def _render_answer(intent_class: str, relation: str, claim_texts: Sequence[str]) -> str:
    compact_claims = [item.strip() for item in claim_texts if item.strip()]
    if not compact_claims:
        return ""
    if intent_class == "cross_document_comparison":
        return (
            "The strongest grounded comparison is that the selected sources describe different "
            "parts of the same operating model: "
            + " In contrast, ".join(compact_claims)
        )
    if intent_class == "complementary_synthesis":
        return (
            "Taken together, the cited evidence supports a combined reading: "
            + " It also shows that ".join(compact_claims)
        )
    if intent_class == "graph_relationship":
        relation_label = relation if relation and relation != "None" else "relationship"
        return (
            f"The relevant graph relation is {relation_label}. The relationship is grounded by "
            + " ".join(compact_claims)
        )
    if intent_class == "provenance_source_trace":
        return (
            "The provenance trail ties the answer back to the selected source record: "
            + " ".join(compact_claims)
        )
    if intent_class == "temporal_conflict":
        return (
            "The temporal evidence should be read as a source/version comparison: "
            + " ".join(compact_claims)
        )
    return "The available evidence supports this answer: " + " ".join(compact_claims)


def _has_meaningful_overlap(question: str, evidence: Sequence[Mapping[str, Any]]) -> bool:
    query_terms = _meaningful_terms(question)
    if not query_terms:
        return False
    evidence_text = " ".join(
        " ".join(
            str(item.get(key, ""))
            for key in ("title", "section_title", "passage_text", "concept_id", "section_id")
        )
        for item in evidence
    )
    evidence_terms = {term.casefold() for term in TOKEN_RE.findall(evidence_text)}
    return bool(query_terms & evidence_terms)


def _meaningful_terms(text: str) -> set[str]:
    return {
        term.casefold()
        for term in TOKEN_RE.findall(text)
        if term.casefold() not in STOP_TERMS and len(term) > 2
    }


def _document_text(document: Mapping[str, Any]) -> str:
    return " ".join(
        str(document.get(key, ""))
        for key in ("title", "section_title", "description", "body", "excerpt", "concept_id")
    )


def _text_term_overlap_score(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    text_terms = _meaningful_terms(text)
    if not text_terms:
        return 0.0
    return len(query_terms & text_terms) / max(len(query_terms), 1)


def _allow_second_hop(*, question: str, intent_class: str) -> bool:
    if intent_class in RELATIONAL_INTENTS:
        return True
    terms = _meaningful_terms(question)
    return len(terms) >= 10 or any(term in terms for term in {"explain", "connect", "combine"})


def _calls_cost(calls: Sequence[Mapping[str, Any]]) -> str:
    total = sum((Decimal(str(call.get("cost_usd", "0"))) for call in calls), Decimal("0"))
    return format(total, "f")


def _qdrant_search_url(base_url: str, collection: str) -> str:
    return f"{base_url.rstrip('/')}/collections/{quote(collection, safe='')}/points/search"


def _privacy_counters() -> dict[str, bool]:
    return {
        "raw_query_persisted": False,
        "raw_evidence_persisted": False,
        "full_provider_response_persisted": False,
        "secret_values_persisted": False,
        "vectors_persisted": False,
    }


def _mutation_counters() -> dict[str, int]:
    return {
        "answer_to_canonical_writes": 0,
        "canonical_writes": 0,
        "corpus_index_content_mutations": 0,
        "production_pointer_mutations": 0,
        "qdrant_write_operations": 0,
    }


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PA7ArbitraryQueryError("PA7_OBJECT_INVALID", label)
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PA7ArbitraryQueryError("PA7_LIST_INVALID", label)
    return value
