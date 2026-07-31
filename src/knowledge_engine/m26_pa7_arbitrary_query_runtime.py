from __future__ import annotations

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
    build_provider_payload,
    canonical_sha256,
    sha256_bytes,
    verify_provider_output,
)

RESPONSE_SCHEMA = "knowledge-engine-m26-pa7-arbitrary-owner-query-response/v1"
MAX_QUERY_CHARS = 2_000
MAX_EVIDENCE_ITEMS = 3
MAX_PARENT_SECTIONS_PER_EVIDENCE = 3
LOCAL_DENSE_DIMENSION = 64
PA4_POLICY_PATH = Path("pilot/m26/m26-pa-4-verified-answer-policy.json")
PA7_OWNER_DECISION_PATH = Path("pilot/m26/m26-pa-7-owner-final-decision.json")
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\bdeveloper\s+message\b", re.I),
    re.compile(r"\bhidden\s+(?:instruction|prompt|policy)\b", re.I),
    re.compile(r"\b(?:api[_ -]?key|secret|password|token|credential)\b", re.I),
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
                evidence=evidence,
                provider_client=provider,
            )
    else:
        verification = _synthesize_and_verify(
            root=root,
            question=normalized_question,
            trace_id=trace_id,
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
        ),
        "citations": verification["citations"],
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
) -> dict[str, Any]:
    dense_candidates = _list(dense_result.get("candidates"), "dense candidates")
    lexical_results = _list(lexical_result.get("results"), "lexical results")
    parent_expansion = _parent_expansion_summary(bundle, selected_evidence)
    graph_edges = _graph_edges(
        lexical_results,
        selected_evidence_ids={str(e["section_id"]) for e in selected_evidence},
    )
    identities = _object(gate.get("production_identities"), "gate.production_identities")
    backend_identity = _object(dense_result.get("backend_identity"), "dense backend identity")
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
            "reranking": "bounded_channel_score_then_release_identity",
        },
        "candidate_count_by_channel": {
            "lexical": len(lexical_results),
            "dense": len(dense_candidates),
            "combined_unique": len(
                {str(item.get("section_id", "")) for item in lexical_results}
                | {str(item.get("section_id", "")) for item in dense_candidates}
            ),
        },
        "graph_hops_used": len(graph_edges),
        "graph_trace": graph_edges[:4],
        "parent_expansion": parent_expansion,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in selected_evidence],
        "selected_locator_ids": [str(item["locator_id"]) for item in selected_evidence],
    }


def _synthesize_and_verify(
    *,
    root: Path,
    question: str,
    trace_id: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: ProviderClient,
) -> dict[str, Any]:
    policy = load_pa7_json(root / PA4_POLICY_PATH)
    primary = evidence[0]
    passage_text = str(primary["passage_text"])
    case = _pa4_case(question=question, trace_id=trace_id, evidence=primary)
    calls: list[dict[str, Any]] = []
    failures: list[str] = []
    repair_attempted = False
    for attempt in (1, 2):
        payload = build_provider_payload(
            policy=policy,
            case=case,
            passage_text=passage_text,
            repair=attempt == 2,
            previous_reason_codes=failures,
        )
        try:
            result = provider_client.call(
                payload,
                "pa7_arbitrary_query_repair" if attempt == 2 else "pa7_arbitrary_query",
            )
            normalized = _normalize_provider_result(result)
            calls.append(normalized)
            verified = verify_provider_output(
                case=case,
                passage_text=passage_text,
                provider_text=normalized["provider_text"],
                policy=policy,
            )
            if verified["terminal_status"] == "abstention_required":
                return _verified_abstention(
                    reason_codes=verified["abstention"]["reason_codes"],
                    calls=calls,
                    repair_attempted=repair_attempted,
                )
            return _verified_answer(primary, verified, passage_text, calls, repair_attempted)
        except VerifiedAnswerGateError as exc:
            failures.append(exc.code)
            if attempt == 1:
                repair_attempted = True
                continue
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


def _verified_answer(
    evidence: Mapping[str, Any],
    verified: Mapping[str, Any],
    passage_text: str,
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
) -> dict[str, Any]:
    claim_texts = []
    for claim in verified["material_claims"]:
        span = _object(claim.get("passage_span"), "claim passage_span")
        claim_texts.append(passage_text[int(span["start_char"]) : int(span["end_char"])])
    answer_text = " ".join(claim_texts).strip()
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
        "citations": [_public_citation(evidence, claim) for claim in verified["material_claims"]],
        "safe_abstention": False,
        "reason_codes": [],
        "provider_call_count": len(calls),
        "payg_equivalent_cost_usd": _calls_cost(calls),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": repair_attempted,
    }


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
) -> list[dict[str, Any]]:
    documents = {str(item["section_id"]): item for item in _release_documents(bundle)}
    candidates: dict[str, dict[str, Any]] = {}
    lexical_results = _list(lexical_result.get("results"), "lexical results")
    for rank, item in enumerate(lexical_results, start=1):
        section_id = str(item.get("section_id", ""))
        if section_id not in documents:
            continue
        candidates[section_id] = {
            "section_id": section_id,
            "lexical": dict(item),
            "channels": {"lexical"},
            "score": float(item.get("score", 0)) + 1.0 / rank,
        }
    for rank, item in enumerate(_list(dense_result.get("candidates"), "dense candidates"), start=1):
        section_id = str(item.get("section_id", ""))
        if section_id not in documents:
            continue
        candidate = candidates.setdefault(
            section_id,
            {
                "section_id": section_id,
                "lexical": {},
                "channels": set(),
                "score": 0.0,
            },
        )
        candidate["channels"].add("dense")
        candidate["score"] += float(item.get("score", 0.0)) + 0.5 / rank
        candidate["dense"] = dict(item)
    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            -len(item["channels"]),
            -float(item["score"]),
            item["section_id"],
        ),
    )
    evidence = []
    for index, candidate in enumerate(ordered[:MAX_EVIDENCE_ITEMS], start=1):
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
            )
        )
    return evidence


def _evidence_item(
    *,
    bundle: CanonicalReleaseBundle,
    document: Mapping[str, Any],
    lexical_result: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
    channels: Sequence[str],
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
    return {
        "evidence_id": evidence_id,
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": "pilot/m24/canonical-release/artifacts/lexical-index.json",
        "artifact_sha256": bundle.artifact_sha256["lexical_index"],
        "concept_id": str(document["concept_id"]),
        "section_id": section_id,
        "source_id": citation["source_id"],
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
    }


def _public_citation(evidence: Mapping[str, Any], claim: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "citation_id": str(claim.get("claim_id", "claim_1")),
        "locator_id": evidence["locator_id"],
        "source_id": evidence["source_id"],
        "section_id": evidence["section_id"],
        "concept_id": evidence["concept_id"],
        "release_id": evidence["release_id"],
        "source_locator": f"{evidence['artifact_key']}#{evidence['section_id']}",
        "support_text_sha256": evidence["passage_text_sha256"],
        "source_artifact_sha256": evidence["artifact_sha256"],
        "provenance_record_sha256": evidence["provenance_record_sha256"],
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


def _parent_expansion_summary(
    bundle: CanonicalReleaseBundle,
    selected_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_concept: dict[str, list[str]] = {}
    for document in _release_documents(bundle):
        by_concept.setdefault(str(document["concept_id"]), []).append(str(document["section_id"]))
    expanded: list[dict[str, Any]] = []
    for evidence in selected_evidence:
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


def _looks_like_prompt_injection(question: str) -> bool:
    return any(pattern.search(question) for pattern in PROMPT_INJECTION_PATTERNS)


def _has_meaningful_overlap(question: str, evidence: Sequence[Mapping[str, Any]]) -> bool:
    query_terms = {
        term.casefold()
        for term in TOKEN_RE.findall(question)
        if term.casefold() not in STOP_TERMS and len(term) > 2
    }
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
