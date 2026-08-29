from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
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
from .m26_pa5_v8_live import LiveGateError, MiniMaxClient
from .m26_production_answer_bundle import (
    FULL_PRODUCTION_ADMISSION_SHA256,
    FULL_PRODUCTION_QDRANT_COLLECTION,
    FULL_PRODUCTION_RELEASE_ID,
    FULL_PRODUCTION_SOURCE_SHA,
    ProductionAnswerBundle,
    load_production_answer_bundle,
)
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
PROVIDER_STATUS_VALUES = {
    "answer",
    "partial",
    "answer_candidate",
    "partial_candidate",
    "abstain",
}
QUESTION_EVIDENCE_RELEVANCE_CODE = "M26-PA7-ME-047"
QUESTION_EVIDENCE_RELEVANCE_HARD_STOP = "QUESTION_EVIDENCE_RELEVANCE_HARD_STOP"
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
_RELEASE_DOCUMENTS_CACHE: dict[int, list[dict[str, Any]]] = {}
_RELEASE_CONCEPTS_CACHE: dict[int, set[str]] = {}
STRUCTURAL_RELATION_TYPES = {"contains", "part_of", "precedes"}
ORDER_QUERY_TERMS = {
    "after",
    "before",
    "changed",
    "older",
    "newer",
    "order",
    "precede",
    "precedes",
    "sequence",
    "temporal",
    "version",
}
GENERIC_RELATIONAL_TERMS = {
    "compare",
    "comparison",
    "complement",
    "connect",
    "connects",
    "different",
    "execution",
    "explain",
    "first",
    "graph",
    "how",
    "permission",
    "relationship",
    "support",
    "supports",
}
QUERY_CONTEXT_UTILITY_TERMS = {
    "does",
    "should",
    "would",
    "could",
    "kind",
    "need",
    "needs",
    "learn",
    "conduct",
    "well",
    "help",
    "helps",
    "understand",
    "role",
}
CLAIM_ANCHOR_RE = re.compile(r"\[\[([A-Za-z0-9_:-]+)\]\]")
LEGACY_CITATION_RE = re.compile(r"\[([A-Za-z0-9_]+_ref_\d+)\]")
DEPENDENCY_TERMS = {
    "depend",
    "depends",
    "dependency",
    "require",
    "requires",
    "causal",
    "cause",
    "causes",
    "because",
    "must",
}
ORDER_SURFACE_TERMS = {
    "after",
    "before",
    "order",
    "ordering",
    "precede",
    "precedes",
    "precedence",
    "sequence",
    "series",
}

RuntimeEventSink = Callable[[Mapping[str, Any]], None]


def _emit_runtime_event(
    event_sink: RuntimeEventSink | None,
    event_type: str,
    **fields: Any,
) -> None:
    if event_sink is None:
        return
    try:
        event_sink({"type": event_type, **fields})
    except Exception:
        # Observability must never change the frozen runtime's behavior.
        return


def _graph_relation_metadata(relation_type: str) -> dict[str, Any]:
    relation = str(relation_type or "related_to")
    metadata: dict[str, Any] = {
        "schema_version": "m26-graph-relation-metadata/v1",
        "relation_type": relation,
        "provenance": "graph_artifact_fact",
        "directed": relation not in {"related_to", "contrasts_with", "complements"},
        "structural_relation": relation in STRUCTURAL_RELATION_TYPES,
    }
    if relation == "precedes":
        metadata.update(
            {
                "relation_family": "ordering",
                "retrieval_semantics": ["ordering", "sequence", "navigation"],
                "non_asserted_semantics": [
                    "dependency",
                    "causality",
                    "implementation",
                    "requirement",
                ],
            }
        )
    return metadata
DIRECT_FACET_EXACT_PHRASES = {
    "comfyui_memory_debug_order": (
        "boring on purpose",
        "minimal working state",
        "one variable at a time",
    )
}
DIRECT_FACET_REQUIRED_QUOTE_TERM_GROUPS = {
    "comfyui_checkpoints": (("checkpoint", "checkpoints"),),
    "comfyui_loras": (("lora", "loras"),),
    "comfyui_vae": (("vae",),),
    "comfyui_clip_t5xxl": (("clip",), ("t5xxl",)),
    "comfyui_quantization": (("gguf",), ("fp8",)),
    "resource_constraint": (
        ("resource", "resources", "runway"),
        ("runway", "timing", "people", "venture", "founder"),
    ),
}
DIRECT_FACET_DISPLAY_LABELS = {
    "comfyui_quantization": "comfyui GGUF/FP8 quantization",
}
MODALITY_STRENGTHENING_TERMS = {
    "always",
    "cannot",
    "certain",
    "certainly",
    "guarantee",
    "guarantees",
    "must",
    "never",
    "requires",
    "will",
}
CAUSALITY_UPGRADE_TERMS = {
    "cause",
    "caused",
    "causes",
    "causing",
    "determine",
    "determines",
    "determined",
}
CAUSALITY_SUPPORT_TERMS = CAUSALITY_UPGRADE_TERMS | {
    "because",
    "causal",
    "causality",
    "due",
    "leads",
    "lead",
    "results",
    "result",
}
PARTIAL_SCOPE_TERMS = {"some", "several"}
UNIVERSAL_SCOPE_TERMS = {"all", "each", "every"}
SYNTHESIS_CONTRADICTION_PHRASES = {
    "equivalent",
    "identical",
    "interchangeable",
    "no difference",
    "same thing",
}
MODEL_EXPLANATION_GENERIC_TERMS = {
    "available evidence",
    "because",
    "context",
    "does not establish",
    "explains",
    "explanation",
    "evidence",
    "framing",
    "generic",
    "generally",
    "in general",
    "instead",
    "may",
    "often",
    "rather",
    "typically",
    "unsupported",
    "usually",
}
MODEL_EXPLANATION_ATTRIBUTION_PATTERNS = (
    re.compile(r"\bsource says\b", re.I),
    re.compile(r"\bcorpus says\b", re.I),
    re.compile(r"\baccording to (?:the )?(?:source|corpus|evidence)\b", re.I),
)

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
                r"\b(?:graph\s+relationship|graph\s+edge|edge|connects?|depends|requires|precedes|part_of|has_part|implemented_by)\b",
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
                r"\b(?:compare|contrast|difference between|versus|vs)\b",
                re.I,
            ),
            re.compile(r"\bhow are .* different\b", re.I),
        ),
    ),
    (
        "complementary_synthesis",
        (re.compile(r"\b(?:complement|synthesis|synthesize|combine|together)\b", re.I),),
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
        bundle: ProductionAnswerBundle,
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
        bundle: ProductionAnswerBundle,
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
        bundle: ProductionAnswerBundle,
        top_k: int,
    ) -> dict[str, Any]:
        if bundle.release_id != FULL_PRODUCTION_RELEASE_ID:
            raise PA7ArbitraryQueryError(
                "PA7_PRODUCTION_BUNDLE_RELEASE_MISMATCH",
                "dense query bundle is not the accepted production release",
            )
        if self.config.qdrant_collection != FULL_PRODUCTION_QDRANT_COLLECTION:
            raise PA7ArbitraryQueryError(
                "PA7_QDRANT_COLLECTION_MISMATCH",
                "dense query collection is not the accepted production collection",
            )
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
                "filter": _production_qdrant_filter(),
                "with_payload": [
                    "concept_id",
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
            _validate_qdrant_payload_identity(point_payload)
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
                                "concept_id",
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
                    "payload_release_id": str(point_payload.get("release_id", "")),
                    "payload_text_sha256": str(point_payload.get("text_sha256", "")),
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
                "identity_filter": _production_qdrant_filter(),
                "identity_checked": True,
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
    answer_bundle: ProductionAnswerBundle | None = None,
    event_sink: RuntimeEventSink | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    normalized_question = _normalize_request_question(question)
    question_sha = canonical_sha256(normalized_question)
    intent_class = _intent_class(normalized_question)
    validated_gate = _validate_gate(root, gate)
    identities = _object(validated_gate.get("production_identities"), "gate.production_identities")
    _emit_runtime_event(event_sink, "stage.started", stage="admission")
    admission = evaluate_owner_admission(
        validated_gate,
        {
            "resolved_gate_self_sha256": validated_gate.get("self_sha256"),
            "owner_subject_hash": owner_subject_hash,
            "owner_only_route": identities.get("owner_only_route"),
            "public_request": public_request,
        },
    )
    trace_id = (
        "m26pa7aq_"
        + canonical_sha256(
            {
                "gate": validated_gate.get("self_sha256"),
                "question_sha256": question_sha,
                "owner_subject_hash": owner_subject_hash,
            }
        )[:32]
    )
    _emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="admission",
        status="admitted" if admission["admitted"] else "denied",
    )
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

    if _looks_like_underspecified_workflow_question(normalized_question):
        return _base_response(
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
                    provider_invoked=False,
                    provider_call_count=0,
                    payg_equivalent_cost_usd=verification["payg_equivalent_cost_usd"],
                    material_claim_support_verified=verification["material_claim_support_verified"],
                    citation_locator_valid=verification["citation_locator_valid"],
                    unsupported_accepted_claims=verification["unsupported_accepted_claims"],
                    repair_attempted=verification["repair_attempted"],
                ),
                "answer_claims": [],
                "relationship_summary": {},
                "multi_evidence_verification": verification["multi_evidence_verification"],
            }
            return response

    _emit_runtime_event(event_sink, "stage.started", stage="retrieval")
    bundle = answer_bundle or load_production_answer_bundle()
    if bundle.release_id != FULL_PRODUCTION_RELEASE_ID:
        raise PA7ArbitraryQueryError(
            "PA7_PRODUCTION_BUNDLE_RELEASE_MISMATCH",
            "answer runtime is not bound to the accepted full production release",
        )
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
    _emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="retrieval",
        selected_evidence_count=len(evidence),
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

    _emit_runtime_event(event_sink, "stage.started", stage="closure")
    verification = _synthesize_and_verify(
        root=root,
        question=normalized_question,
        trace_id=trace_id,
        intent_class=intent_class,
        evidence=evidence,
        provider_client=provider,
        event_sink=event_sink,
    )
    _emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="closure",
        terminal_status=verification.get("terminal_status", ""),
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
        "answer_source": verification.get("answer_source", "safe_abstention"),
        "relationship_summary": verification.get("relationship_summary", {}),
        "multi_evidence_verification": verification.get("multi_evidence_verification", {}),
    }
    response["evidence_utilization_trace"] = _evidence_utilization_trace(response)
    response["latency_ms"] = max(
        int(response["latency_ms"]),
        int((time.monotonic() - started) * 1000),
    )
    _emit_runtime_event(
        event_sink,
        "stage.completed",
        stage="publication",
        status=response.get("status", ""),
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
    bundle: ProductionAnswerBundle,
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
            item
            for item in graph_edges
            if item.get("edge_id") not in {edge["edge_id"] for edge in selected_graph_edges}
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
    selected_type_counts = Counter(
        str(item.get("evidence_type", "passage")) for item in selected_evidence
    )
    selected_channel_counts = Counter(
        str(channel) for item in selected_evidence for channel in item.get("channels", [])
    )
    selected_relation_counts = Counter(
        str(relation)
        for item in selected_evidence
        for relation in _selected_item_relation_types(item)
        if str(relation)
    )
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
                "node_count": len(_list(bundle.graph_v2.get("nodes"), "graph_v2 nodes")),
                "edge_count": len(_list(bundle.graph_v2.get("edges"), "graph_v2 edges")),
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
            "selected_graph_relation_type_counts": dict(sorted(selected_relation_counts.items())),
            "structural_relation_type_counts": {
                relation: count
                for relation, count in sorted(selected_relation_counts.items())
                if relation in STRUCTURAL_RELATION_TYPES
            },
        },
        "rerank_diversity_summary": {
            "selected_evidence_count": len(selected_evidence),
            "distinct_source_count": len(source_identities),
            "selected_evidence_type_counts": dict(sorted(selected_type_counts.items())),
            "selected_channel_counts": dict(sorted(selected_channel_counts.items())),
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


def _selected_item_relation_types(item: Mapping[str, Any]) -> list[str]:
    relation_types: list[str] = []
    if item.get("relation_type"):
        relation_types.append(str(item.get("relation_type")))
    metadata = item.get("retrieval_metadata")
    if isinstance(metadata, Mapping):
        for relation in metadata.get("relation_types", []):
            relation_types.append(str(relation))
        for edge in metadata.get("graph_edges", []):
            if isinstance(edge, Mapping) and edge.get("relation_type"):
                relation_types.append(str(edge.get("relation_type")))
    return relation_types


def _synthesize_and_verify(
    *,
    root: Path,
    question: str,
    trace_id: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_client: ProviderClient,
    event_sink: RuntimeEventSink | None = None,
) -> dict[str, Any]:
    policy = load_pa7_json(root / PA4_POLICY_PATH)
    calls: list[dict[str, Any]] = []
    failures: list[str] = []
    repair_attempted = False
    for attempt in (1, 2):
        if attempt == 2:
            _emit_runtime_event(
                event_sink,
                "repair.started",
                reason_codes=sorted(set(failures)),
            )
            _emit_runtime_event(event_sink, "stage.started", stage="repair")
        _emit_runtime_event(
            event_sink,
            "stage.started",
            stage="review",
            attempt=attempt,
        )
        model_role = (
            "semantic_reviewer"
            if "semantic" in str(
                "pa7_multi_evidence_query_repair" if attempt == 2 else "pa7_multi_evidence_query"
            )
            else "closure"
        )
        _emit_runtime_event(
            event_sink,
            "model.started",
            role=model_role,
            provider=_provider_identity(provider_client, role=model_role),
            model=_model_identity(provider_client, role=model_role),
            attempt=attempt,
        )
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
            _emit_runtime_event(
                event_sink,
                "stage.completed",
                stage="review",
                attempt=attempt,
                status="provider_response",
            )
            _emit_runtime_event(
                event_sink,
                "model.completed",
                role=model_role,
                provider=_provider_identity(provider_client, role=model_role),
                model=_model_identity(provider_client, role=model_role),
                attempt=attempt,
                status="ok",
                latency_ms=normalized.get("latency_ms"),
            )
            _emit_runtime_event(
                event_sink,
                "stage.started",
                stage="verification",
                attempt=attempt,
            )
            verified = _verify_multi_evidence_provider_output(
                trace_id=trace_id,
                question=question,
                intent_class=intent_class,
                evidence=evidence,
                provider_text=normalized["provider_text"],
            )
            _emit_runtime_event(
                event_sink,
                "stage.completed",
                stage="verification",
                attempt=attempt,
                status=verified.get("terminal_status", "verified"),
            )
            if verified["terminal_status"] == "safe_abstention":
                failures.extend(str(code) for code in verified["reason_codes"])
                deterministic = _deterministic_evidence_synthesis(
                    trace_id=trace_id,
                    question=question,
                    intent_class=intent_class,
                    evidence=evidence,
                    calls=calls,
                    repair_attempted=repair_attempted,
                    trigger_reason_codes=verified["reason_codes"],
                    allow_after_repair_failure=False,
                )
                if deterministic is not None:
                    if attempt == 2:
                        _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="verified")
                    return deterministic
                if attempt == 2:
                    _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="abstained")
                return _verified_abstention(
                    reason_codes=verified["reason_codes"],
                    calls=calls,
                    repair_attempted=repair_attempted,
                )
            answer = _verified_multi_evidence_answer(
                intent_class=intent_class,
                verified=verified,
                evidence=evidence,
                calls=calls,
                repair_attempted=repair_attempted,
            )
            answer["answer_source"] = "provider_verified_natural_or_rendered"
            answer["multi_evidence_verification"] = {
                **dict(answer.get("multi_evidence_verification", {})),
                "verification_failure_codes_by_attempt": list(failures),
                "repair_trigger": sorted(set(failures)) if repair_attempted else [],
                "repair_result": "verified" if repair_attempted else "not_needed",
                "deterministic_evidence_synthesis_used": False,
            }
            if attempt == 2:
                _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="verified")
            return answer
        except VerifiedAnswerGateError as exc:
            failures.append(exc.code)
            if _is_question_evidence_relevance_hard_stop(exc):
                if attempt == 2:
                    _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="abstained")
                return _verified_abstention(
                    reason_codes=[exc.code, QUESTION_EVIDENCE_RELEVANCE_HARD_STOP],
                    calls=calls,
                    repair_attempted=repair_attempted,
                )
            if attempt == 1:
                repair_attempted = True
                continue
            deterministic = _deterministic_evidence_synthesis(
                trace_id=trace_id,
                question=question,
                intent_class=intent_class,
                evidence=evidence,
                calls=calls,
                repair_attempted=True,
                trigger_reason_codes=[*failures, "BOUNDED_REPAIR_EXHAUSTED"],
                allow_after_repair_failure=True,
            )
            if deterministic is not None:
                _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="verified")
                return deterministic
            _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="abstained")
            return _verified_abstention(
                reason_codes=[*failures, "BOUNDED_REPAIR_EXHAUSTED"],
                calls=calls,
                repair_attempted=True,
            )
        except (LiveGateError, httpx.HTTPError, KeyError, ValueError) as exc:
            if attempt == 2:
                _emit_runtime_event(event_sink, "stage.completed", stage="repair", status="abstained")
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


def _provider_identity(provider_client: ProviderClient, *, role: str) -> str:
    if role == "semantic_reviewer":
        return "minimax-m3"
    telemetry = getattr(provider_client, "telemetry", None)
    if callable(telemetry):
        try:
            value = telemetry()
            if isinstance(value, Mapping):
                return str(value.get("closure_provider_final") or value.get("closure_provider_initial") or "unknown")
        except Exception:
            pass
    return "unknown"


def _model_identity(provider_client: ProviderClient, *, role: str) -> str:
    if role == "semantic_reviewer":
        return "MiniMax-M3"
    telemetry = getattr(provider_client, "telemetry", None)
    if callable(telemetry):
        try:
            value = telemetry()
            if isinstance(value, Mapping):
                attempts = value.get("provider_attempts")
                if isinstance(attempts, list) and attempts:
                    last = attempts[-1]
                    if isinstance(last, Mapping) and last.get("model"):
                        return str(last["model"])
        except Exception:
            pass
    return "unknown"


def _deterministic_evidence_synthesis(
    *,
    trace_id: str,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    repair_attempted: bool,
    trigger_reason_codes: Sequence[str],
    allow_after_repair_failure: bool,
) -> dict[str, Any] | None:
    eligible, eligibility_reasons = _deterministic_fallback_eligibility(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
        allow_after_repair_failure=allow_after_repair_failure,
        trigger_reason_codes=trigger_reason_codes,
    )
    if not eligible:
        return None
    candidate = _deterministic_provider_candidate(
        question=question,
        intent_class=intent_class,
        evidence=evidence,
    )
    if candidate is None:
        return None
    try:
        verified = _verify_multi_evidence_provider_output(
            trace_id=trace_id,
            question=question,
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
    answer["answer_source"] = "deterministic_verified_evidence_synthesis"
    answer["multi_evidence_verification"] = {
        **dict(answer.get("multi_evidence_verification", {})),
        "deterministic_evidence_synthesis_used": True,
        "trigger_reason_codes": sorted({str(item) for item in trigger_reason_codes}),
        "verification_failure_codes_by_attempt": [
            str(item) for item in trigger_reason_codes if str(item).startswith("M26-PA7-ME-")
        ],
        "repair_trigger": sorted({str(item) for item in trigger_reason_codes}),
        "repair_result": "deterministic_verified_evidence_synthesis",
        "fallback_eligibility": {
            "eligible": True,
            "reasons": eligibility_reasons,
            "allow_after_repair_failure": allow_after_repair_failure,
        },
    }
    return answer


def _deterministic_provider_candidate(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    passages = [item for item in evidence if item.get("evidence_type") == "passage"]
    relation = None
    role = "direct"
    selected: list[Mapping[str, Any]]
    claims: list[dict[str, Any]]
    if intent_class == "direct_grounded_knowledge":
        return _deterministic_direct_provider_candidate(question=question, evidence=evidence)
    if intent_class in {"cross_document_comparison", "complementary_synthesis"}:
        selected = _semantic_distinct_passages_for_query(question, passages, minimum=2)
        if len(selected) < 2:
            return None
        relation = "contrasts_with" if intent_class == "cross_document_comparison" else "complements"
        role = "comparison" if intent_class == "cross_document_comparison" else "relationship"
    elif intent_class == "graph_relationship":
        selected = _deterministic_graph_items(evidence)
        if not selected:
            return None
        graph_edge = next(
            (item for item in selected if item.get("evidence_type") == "graph_edge"),
            {},
        )
        relation = str(graph_edge.get("relation_type") or "precedes")
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
        temporal = [item for item in evidence if item.get("evidence_type") == "temporal_record"]
        selected = _first_distinct_source_items(temporal, minimum=2)
        if len(selected) < 2:
            return None
        relation = "precedes"
        role = "temporal"
    else:
        passage = _single_responsive_fallback_passage(question=question, evidence=passages)
        if passage is None:
            return None
        selected = [passage]
    if not selected:
        return None
    refs = [_deterministic_support_ref(item) for item in selected]
    if any(ref is None for ref in refs):
        return None
    surface_text = _deterministic_relation_surface_text(
        question=question,
        relation=relation,
        refs=[ref for ref in refs if ref is not None],
    )
    claims = [
        {
            "claim_id": "claim_1",
            "claim_role": role,
            "surface_text": surface_text,
            "facet_ids": _required_facet_ids(question=question, intent_class=intent_class),
            "support_mode": "multi_evidence_exact",
            "support_refs": [ref for ref in refs if ref is not None],
        }
    ]
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": [str(item["evidence_id"]) for item in selected],
        "answer_text": _deterministic_answer_text(claims),
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _deterministic_direct_provider_candidate(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    raw_claims: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    for index, facet in enumerate(
        _question_contract(
            question=question,
            intent_class="direct_grounded_knowledge",
        )["required_facets"],
        start=1,
    ):
        item = _best_evidence_for_direct_facet(question=question, facet=facet, evidence=evidence)
        if item is None:
            return None
        ref = _deterministic_support_ref_for_facet(item, facet)
        if ref is None:
            return None
        facet_id = str(facet.get("facet_id", f"facet_{index}"))
        surface_text = str(ref["exact_quote"])
        if facet_id == "non_entailment_boundary":
            surface_text = (
                "A precedes relationship does not by itself prove dependency; "
                + surface_text
            )
        raw_claims.append(
            {
                "claim_id": f"claim_{index}",
                "claim_role": "direct",
                "surface_text": surface_text,
                "facet_ids": [facet_id],
                "support_mode": "exact_quote",
                "support_refs": [ref],
            }
        )
        selected_ids.append(str(item["evidence_id"]))
    claims = _merge_deterministic_direct_claims(raw_claims)
    if not claims:
        return None
    return {
        "schema_version": "aq3-provider-candidate/v3",
        "status": "answer_candidate",
        "relation": None,
        "selected_evidence_ids": list(dict.fromkeys(selected_ids)),
        "answer_text": _deterministic_answer_text(claims),
        "claims": claims,
        "missing_facets": [],
        "abstention_reason": None,
    }


def _semantic_distinct_passages_for_query(
    question: str,
    passages: Sequence[Mapping[str, Any]],
    *,
    minimum: int,
) -> list[Mapping[str, Any]]:
    query_terms = _coverage_terms(question)
    selected: list[Mapping[str, Any]] = []
    selected_sources: set[str] = set()
    for component_terms in _question_component_term_sets(question)[:minimum]:
        candidate = _best_passage_for_terms(
            passages,
            component_terms,
            excluded_sources=selected_sources,
        )
        if candidate is None:
            continue
        selected.append(candidate)
        selected_sources.add(_source_identity(candidate))
    if len(selected) >= minimum:
        return selected
    ranked = sorted(
        passages,
        key=lambda item: (
            -_text_term_overlap_score(query_terms, str(item.get("passage_text", ""))),
            _is_article_root_evidence(item),
            _segment_noise_penalty(str(item.get("passage_text", ""))),
            str(item.get("section_id", "")),
        ),
    )
    for item in _first_distinct_source_items(ranked, minimum=minimum):
        if _source_identity(item) not in selected_sources:
            selected.append(item)
            selected_sources.add(_source_identity(item))
        if len(selected) >= minimum:
            break
    return selected


def _question_component_term_sets(question: str) -> list[set[str]]:
    components: list[set[str]] = []
    for entity in _named_question_entities(question):
        terms = _coverage_terms(entity)
        if entity.casefold() in {"dag"}:
            terms |= {"dag", "dependency", "dependencies", "task", "parallel"}
        if "router" in entity.casefold():
            terms |= {"query", "router", "route", "mode", "path"}
        if "state machine" in entity.casefold():
            terms |= {"state", "machine", "transition"}
        if "adaptive" in entity.casefold():
            terms |= {"adaptive", "replan", "replanning", "plan"}
        if terms:
            components.append(terms)
    return components


def _best_passage_for_terms(
    passages: Sequence[Mapping[str, Any]],
    terms: set[str],
    *,
    excluded_sources: set[str],
) -> Mapping[str, Any] | None:
    candidates = [
        item
        for item in passages
        if _source_identity(item) not in excluded_sources
        and terms & _coverage_terms(str(item.get("passage_text", "")))
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            len(terms & _coverage_terms(str(item.get("passage_text", "")))),
            _text_term_overlap_score(terms, str(item.get("passage_text", ""))),
            -int(_is_article_root_evidence(item)),
            -_segment_noise_penalty(str(item.get("passage_text", ""))),
        ),
    )


def _merge_deterministic_direct_claims(
    claims: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for claim in claims:
        support_refs = _list(claim.get("support_refs", []), "deterministic support refs")
        if not support_refs:
            continue
        first = support_refs[0]
        key = (str(first.get("evidence_id", "")), str(first.get("exact_quote", "")))
        if key not in merged:
            order.append(key)
            merged[key] = {
                **dict(claim),
                "facet_ids": [],
                "support_refs": [dict(first)],
            }
        merged[key]["facet_ids"] = sorted(
            {
                *[str(item) for item in merged[key].get("facet_ids", [])],
                *[str(item) for item in claim.get("facet_ids", [])],
            }
        )
    result = []
    for index, key in enumerate(order, start=1):
        claim = dict(merged[key])
        claim["claim_id"] = f"claim_{index}"
        result.append(claim)
    return result


def _best_evidence_for_direct_facet(
    *,
    question: str,
    facet: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    passages = [item for item in evidence if item.get("evidence_type") == "passage"]
    if not passages:
        return None
    facet_terms = _facet_terms(facet)
    if not facet_terms:
        return _single_responsive_fallback_passage(question=question, evidence=passages)
    if _direct_facet_required_quote_groups(str(facet.get("facet_id", ""))):
        passages = [
            item
            for item in passages
            if _direct_facet_text_matches(facet, str(item.get("passage_text", "")))
            and _deterministic_support_ref_for_facet(item, facet) is not None
        ]
        if not passages:
            return None
    ranked = sorted(
        passages,
        key=lambda item: (
            -_direct_facet_match_score(facet, str(item.get("passage_text", ""))),
            -_text_term_overlap_score(facet_terms, str(item.get("passage_text", ""))),
            _is_article_root_evidence(item),
            str(item.get("section_id", "")),
        ),
    )
    best = ranked[0]
    return (
        best
        if _direct_facet_match_score(facet, str(best.get("passage_text", ""))) >= 1
        else None
    )


def _deterministic_relation_surface_text(
    *,
    question: str,
    relation: str | None,
    refs: Sequence[Mapping[str, Any]],
) -> str:
    quotes = [str(ref.get("exact_quote", "")) for ref in refs if ref.get("exact_quote")]
    joined = " ".join(quotes)
    if relation == "precedes":
        entities = _named_question_entities(question)
        left = entities[0] if len(entities) >= 1 else "the first item"
        right = entities[1] if len(entities) >= 2 else "the second item"
        q = question.casefold()
        if any(
            marker in q
            for marker in (
                "source record",
                "source records",
                "temporal",
                "version",
                "changed between",
                "what changed",
                "retrieved",
            )
        ):
            return (
                "The first source/version record precedes the second source/version record, "
                "so this is a source/version comparison about what changed between records."
            )
        surface = f"{left} precedes {right} in ordering or sequence."
        if _question_requires_non_entailment_boundary(question):
            surface += (
                " That precedes edge supports ordering or sequence only and does not by itself "
                "prove dependency or causality."
            )
        return surface
    return joined


def _deterministic_answer_text(claims: Sequence[Mapping[str, Any]]) -> str:
    sentences = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", "claim_1"))
        support_refs = _list(claim.get("support_refs", []), "deterministic answer refs")
        surface_text = str(claim.get("surface_text", ""))
        if (
            len(support_refs) > 1
            and "does not by itself prove dependency" not in surface_text.casefold()
        ):
            clauses = [
                _bounded_sentence(str(ref.get("exact_quote", "")), max_chars=160)
                for ref in support_refs[:2]
            ]
            surface = "; ".join(clause for clause in clauses if clause)
        else:
            surface = _bounded_sentence(surface_text, max_chars=260)
        if surface:
            label = _deterministic_claim_label(claim.get("facet_ids", []))
            prefix = f"{label}: " if label else ""
            sentences.append(f"{prefix}{surface} [[{claim_id}]].")
    return " ".join(sentences)


def _deterministic_claim_label(facet_ids: Any) -> str:
    ids = [
        str(item)
        for item in (facet_ids if isinstance(facet_ids, Sequence) and not isinstance(facet_ids, (str, bytes)) else [])
        if str(item)
    ]
    labels = []
    for facet_id in ids[:3]:
        label = DIRECT_FACET_DISPLAY_LABELS.get(
            facet_id,
            facet_id.removeprefix("entity_").replace("_", " "),
        )
        labels.append(label)
    return " / ".join(labels)


def _deterministic_support_ref_for_terms(
    item: Mapping[str, Any],
    facet_terms: set[str],
) -> dict[str, str] | None:
    evidence_text = str(item.get("passage_text", ""))
    segments = _exact_quote_segments(evidence_text)
    if not segments:
        return _deterministic_support_ref(item)
    if facet_terms:
        ranked = sorted(
            segments,
            key=lambda segment: (
                -len(facet_terms & _coverage_terms(segment)),
                _thin_heading(segment),
                _article_title_like(segment),
                _segment_noise_penalty(segment),
                -len(_meaningful_terms(segment)),
            ),
        )
        quote = ranked[0]
        if not (facet_terms & _coverage_terms(quote)):
            return None
    else:
        quote = _first_exact_evidence_quote(evidence_text)
    if not quote:
        return None
    if len(quote) > 240:
        quote = _bounded_quote_around_terms(quote, facet_terms, max_chars=240)
    return {
        "evidence_id": str(item["evidence_id"]),
        "locator_id": str(item["locator_id"]),
        "exact_quote": quote,
        "exact_support_snippet": quote,
        "uncertainty": "low",
    }


def _deterministic_support_ref_for_facet(
    item: Mapping[str, Any],
    facet: Mapping[str, Any],
) -> dict[str, str] | None:
    facet_id = str(facet.get("facet_id", ""))
    quote_groups = _direct_facet_required_quote_groups(facet_id)
    if quote_groups and not _direct_facet_required_phrases(facet_id):
        evidence_text = str(item.get("passage_text", ""))
        segments = _exact_quote_segments(evidence_text)
        if not segments:
            return None
        grouped_terms = {term for group in quote_groups for term in group}
        ranked = sorted(
            segments,
            key=lambda segment: (
                -sum(
                    1
                    for group in quote_groups
                    if any(term in str(segment).casefold() for term in group)
                ),
                -_text_term_overlap_score(grouped_terms, segment),
                _thin_heading(segment),
                _article_title_like(segment),
                _segment_noise_penalty(segment),
                -len(_meaningful_terms(segment)),
            ),
        )
        quote = ranked[0]
        if not _direct_facet_text_matches(facet, quote):
            return None
        if len(quote) > 240:
            quote = _bounded_quote_around_terms(quote, grouped_terms, max_chars=240)
        return {
            "evidence_id": str(item["evidence_id"]),
            "locator_id": str(item["locator_id"]),
            "exact_quote": quote,
            "exact_support_snippet": quote,
            "uncertainty": "low",
        }
    if not _direct_facet_required_phrases(facet_id):
        return _deterministic_support_ref_for_terms(item, _facet_terms(facet))
    evidence_text = str(item.get("passage_text", ""))
    segments = _exact_quote_segments(evidence_text)
    if not segments:
        return None
    ranked = sorted(
        segments,
        key=lambda segment: (
            -_direct_facet_phrase_score(facet_id, segment),
            _thin_heading(segment),
            _article_title_like(segment),
            _segment_noise_penalty(segment),
            -len(_meaningful_terms(segment)),
        ),
    )
    quote = ranked[0]
    if _direct_facet_phrase_score(facet_id, quote) <= 0:
        return None
    if len(quote) > 240:
        quote = _bounded_quote_around_terms(
            quote,
            set(_direct_facet_required_phrases(facet_id)),
            max_chars=240,
        )
    return {
        "evidence_id": str(item["evidence_id"]),
        "locator_id": str(item["locator_id"]),
        "exact_quote": quote,
        "exact_support_snippet": quote,
        "uncertainty": "low",
    }


def _bounded_quote_around_terms(
    quote: str,
    terms: set[str],
    *,
    max_chars: int,
) -> str:
    text = re.sub(r"\s+", " ", str(quote)).strip()
    if len(text) <= max_chars:
        return text
    lowered = text.casefold()
    positions = [
        lowered.find(str(term).casefold())
        for term in sorted(terms, key=len, reverse=True)
        if str(term).strip() and lowered.find(str(term).casefold()) >= 0
    ]
    if not positions:
        return text[:max_chars].rsplit(" ", 1)[0].rstrip()
    anchor = min(positions)
    start = max(0, anchor - max_chars // 3)
    if start > 0:
        boundary = text.rfind(" ", 0, start)
        if boundary > 0:
            start = boundary + 1
    end = min(len(text), start + max_chars)
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        if boundary > start + max_chars // 2:
            end = boundary
    window = text[start:end].strip(" ,;:")
    return window or text[:max_chars].rsplit(" ", 1)[0].rstrip()


def _segment_noise_penalty(text: str) -> int:
    segment = str(text)
    penalty = 0
    if "```" in segment or re.search(r"\b(class|def|return|import)\b", segment):
        penalty += 3
    if "|" in segment:
        penalty += 2
    if segment.lstrip().startswith("#"):
        penalty += 1
    return penalty


def _bounded_sentence(text: str, *, max_chars: int) -> str:
    sentence = re.sub(r"\s+", " ", str(text)).strip()
    if not sentence:
        return ""
    sentence = sentence.split(". ", 1)[0].rstrip(".")
    if len(sentence) > max_chars:
        sentence = sentence[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return sentence


def _deterministic_fallback_eligibility(
    *,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    allow_after_repair_failure: bool,
    trigger_reason_codes: Sequence[str],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if intent_class not in {
        "direct_grounded_knowledge",
        "provenance_source_trace",
        "cross_document_comparison",
        "complementary_synthesis",
        "graph_relationship",
        "temporal_conflict",
    }:
        return False, ["intent_not_semantic_fallback_supported"]
    if "BOUNDED_REPAIR_EXHAUSTED" in {str(code) for code in trigger_reason_codes}:
        reasons.append("after_bounded_repair_failure")
    elif not allow_after_repair_failure:
        reasons.append("provider_abstention_narrow_eligibility_checked")
    if intent_class == "provenance_source_trace":
        has_provenance = any(item.get("evidence_type") == "provenance" for item in evidence)
        has_passage = any(item.get("evidence_type") == "passage" for item in evidence)
        if has_provenance and has_passage:
            return True, [*reasons, "simple_provenance_lookup"]
        return False, [*reasons, "provenance_or_passage_missing"]
    if not evidence:
        return False, [*reasons, "no_evidence_for_semantic_fallback"]
    return True, [*reasons, "semantic_facet_bound_candidate"]


def _looks_like_complex_fallback_denied_question(question: str) -> bool:
    q = question.casefold()
    denial_patterns = (
        r"\bhow\b",
        r"\bwhy\b",
        r"\bcompare\b|\bcontrast\b|\bdifferent\b|\bdifference\b|\bversus\b|\bvs\b",
        r"\barchitecture\b|\bsketch\b|\bparallel\b|\bhuman approval\b|\bpersisted\b",
        r"\bresponsible for\b|\bsource of trust\b|\bwhich one\b|\beach\b",
        r"\bprecedes\b|\bdepends?_on\b|\bdepend(?:s|ency)?\b|\bimply\b|\binfer\b",
        r"\bclient disconnect\b|\bkeeps? working\b|\badmission to completion\b",
        r"\bfit together\b|\bwork together\b|\bcomplement\b|\bsynthesis\b",
        r"\breplan\b|\breplanner\b|\badaptive planning\b",
    )
    return any(re.search(pattern, q) for pattern in denial_patterns)


def _single_responsive_fallback_passage(
    *,
    question: str,
    evidence: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    query_terms = _coverage_terms(question)
    best: Mapping[str, Any] | None = None
    best_score = 0.0
    for item in evidence:
        if item.get("evidence_type") != "passage":
            continue
        if _is_article_root_evidence(item) and _article_title_like(str(item.get("passage_text", ""))):
            continue
        score = _text_term_overlap_score(query_terms, str(item.get("passage_text", "")))
        if score > best_score:
            best = item
            best_score = score
    if best is None or best_score < 0.2:
        return None
    return best


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
    for concept_id in sorted(endpoint_concepts):
        concept_items = [
            item
            for item in evidence
            if item.get("evidence_type") == "passage"
            and str(item.get("concept_id", "")) == concept_id
        ]
        if concept_items:
            endpoints.append(max(concept_items, key=_passage_answer_quality_score))
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
        "exact_support_snippet": quote,
        "uncertainty": "low",
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
    question_contract = _question_contract(question=question, intent_class=intent_class)
    repair_directive = _repair_directive(previous_reason_codes or [], intent_class=intent_class)
    output_contract: dict[str, Any] = {
        "schema_version": "aq3-provider-candidate/v3",
        "status_values": sorted(PROVIDER_STATUS_VALUES),
        "relation_values": [
            "contrasts_with",
            "complements",
            "causes",
            "contains",
            "depends_on",
            "navigates_to",
            "part_of",
            "precedes",
            "supersedes",
            "same_as",
            "insufficient_basis",
            None,
        ],
        "required_json_keys": [
            "schema_version",
            "status",
            "relation",
            "selected_evidence_ids",
            "answer_text",
            "claims",
            "abstention_reason",
        ],
        "optional_json_keys": ["missing_facets"],
        "claim_contract": (
            "For answer_candidate, each claim must contain claim_id, surface_text, "
            "claim_role, facet_ids, support_mode, and support_refs. answer_text must be "
            "natural prose with runtime claim anchors such as [[claim_1]], not final "
            "citation locators. Prefer one claim that covers all visible required facets "
            "when possible, and keep answer_text to one or two short sentences. Each "
            "support_ref must copy evidence_id, locator_id, and "
            "exact_support_snippet byte-for-byte from one supplied evidence text. Do not "
            "invent IDs, locators, graph edges, provenance fields, or quotations. A "
            "precedes graph edge proves ordering only; do not upgrade it to dependency, "
            "causality, or requirement unless endpoint passage text explicitly supports "
            "that stronger relation. facet_ids are verifier hints only: the visible "
            "answer and claim surfaces must actually state each required facet."
        ),
        "max_claim_count": 2,
        "repair_directive": repair_directive,
    }
    if not repair:
        output_contract["answer_candidate_json_example"] = {
            "schema_version": "aq3-provider-candidate/v3",
            "status": "answer_candidate",
            "relation": "complements",
            "selected_evidence_ids": [item["evidence_id"] for item in evidence_payload[:2]],
            "answer_text": (
                "The evidence indicates that the first component and second component "
                "work together in the approved runtime path [[claim_1]]."
            ),
            "claims": [
                {
                    "claim_id": "claim_1",
                    "surface_text": (
                        "The supplied sources describe complementary parts of the "
                        "approved runtime path."
                    ),
                    "claim_role": "relationship",
                    "facet_ids": [
                        facet["facet_id"] for facet in question_contract["required_facets"][:2]
                    ],
                    "support_mode": "multi_evidence_exact",
                    "support_refs": [
                        {
                            "evidence_id": "COPY_SUPPLIED_EVIDENCE_ID",
                            "locator_id": "COPY_SUPPLIED_LOCATOR_ID",
                            "exact_support_snippet": "COPY EXACT TEXT FROM THAT EVIDENCE",
                            "uncertainty": "low",
                        }
                    ],
                }
            ],
            "missing_facets": [],
            "abstention_reason": None,
        }
    else:
        output_contract["answer_candidate_json_example"] = {
            "schema_version": "aq3-provider-candidate/v3",
            "status": "answer_candidate",
            "relation": "complements",
            "selected_evidence_ids": [item["evidence_id"] for item in evidence_payload[:2]],
            "answer_text": "Use the supplied evidence only; answer the missing facets directly [[claim_1]].",
            "claims": [
                {
                    "claim_id": "claim_1",
                    "surface_text": "The visible answer directly states the missing required facets.",
                    "claim_role": "relationship",
                    "facet_ids": [facet["facet_id"] for facet in question_contract["required_facets"][:2]],
                    "support_mode": "multi_evidence_exact",
                    "support_refs": [
                        {
                            "evidence_id": "COPY_SUPPLIED_EVIDENCE_ID",
                            "locator_id": "COPY_SUPPLIED_LOCATOR_ID",
                            "exact_support_snippet": "COPY EXACT TEXT FROM THAT EVIDENCE",
                            "uncertainty": "low",
                        }
                    ],
                }
            ],
            "missing_facets": previous_reason_codes or [],
            "abstention_reason": None,
        }
    task = {
        "schema_version": "aq3-provider-task/v2",
        "stage_id": "M26.PA.7-FINAL-CORRECTIVE",
        "case_id": trace_id,
        "attempt_kind": "bounded_repair" if repair else "initial_multi_evidence_draft",
        "question": question,
        "intent_class": intent_class,
        "question_contract": question_contract,
        "evidence_bundle": evidence_payload,
        "minimum_evidence_rule": _minimum_evidence_rule(intent_class),
        "claim_strategy": {
            "prefer_single_claim": intent_class == "direct_grounded_knowledge",
            "max_claim_count": 2,
            "max_support_refs_per_claim": 2,
            "concise_answer_text": True,
        },
        "previous_reason_codes": previous_reason_codes or [],
        "output_contract": {
            **output_contract,
            "abstain_json_example": {
                "schema_version": "aq3-provider-candidate/v3",
                "status": "abstain",
                "relation": "insufficient_basis",
                "selected_evidence_ids": [],
                "answer_text": "",
                "claims": [],
                "missing_facets": [
                    facet["facet_id"] for facet in question_contract["required_facets"]
                ],
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
        "text_role": _evidence_text_role(item),
        "section_granularity": _section_granularity(item),
        "edge_id": str(item.get("edge_id", "")),
        "edge_source": str(item.get("edge_source", "")),
        "edge_target": str(item.get("edge_target", "")),
        "relation_type": str(item.get("relation_type", "")),
        "provenance_record_sha256": str(item.get("provenance_record_sha256", "")),
        "retrieved_at": str(item.get("retrieved_at", "")),
        "channels": [str(channel) for channel in item.get("channels", [])],
        "retrieval_metadata": dict(item.get("retrieval_metadata", {}))
        if isinstance(item.get("retrieval_metadata"), Mapping)
        else {},
    }


def _question_contract(*, question: str, intent_class: str) -> dict[str, Any]:
    terms = sorted(_coverage_terms(question))
    facets: list[dict[str, Any]] = []
    if intent_class == "cross_document_comparison":
        facets = [
            {"facet_id": "compare_left", "terms": terms[:6], "required": True},
            {"facet_id": "compare_right", "terms": terms[:6], "required": True},
            {"facet_id": "comparison_relation", "terms": ["compare", "contrast"], "required": True},
        ]
    elif intent_class == "complementary_synthesis":
        facets = [
            {"facet_id": "component_a", "terms": terms[:6], "required": True},
            {"facet_id": "component_b", "terms": terms[:6], "required": True},
            {
                "facet_id": "synthesis_relation",
                "terms": ["together", "complement"],
                "required": True,
            },
        ]
    elif intent_class == "graph_relationship":
        facets = [
            {
                "facet_id": "graph_edge",
                "terms": ["graph", "edge", "relationship"],
                "required": True,
            },
            {"facet_id": "source_endpoint", "terms": terms[:6], "required": True},
            {"facet_id": "target_endpoint", "terms": terms[:6], "required": True},
            {"facet_id": "relation_semantics", "terms": ["relation"], "required": True},
        ]
    elif intent_class == "provenance_source_trace":
        facets = [
            {"facet_id": "passage_claim", "terms": terms[:6], "required": True},
            {"facet_id": "provenance_record", "terms": ["provenance", "source"], "required": True},
        ]
    elif intent_class == "temporal_conflict":
        facets = [
            {
                "facet_id": "older_or_first_record",
                "terms": ["older", "first", "before"],
                "required": True,
            },
            {
                "facet_id": "newer_or_second_record",
                "terms": ["newer", "second", "after"],
                "required": True,
            },
            {"facet_id": "temporal_relation", "terms": ["changed", "version"], "required": True},
        ]
    else:
        facets = _direct_question_facets(question)
        if not facets:
            facets = [{"facet_id": "direct_answer", "terms": terms[:8], "required": True}]
    return {
        "required_facets": facets,
        "material_claim_policy": (
            "every material assertion must be represented by a claim.surface_text "
            "and runtime anchor"
        ),
        "graph_relation_policy": (
            "structural graph relations may identify navigation/order only unless "
            "endpoint passage text supports stronger semantics"
        ),
    }


def _direct_question_facets(question: str) -> list[dict[str, Any]]:
    question_casefold = question.casefold()
    facets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(facet_id: str, terms: Sequence[str]) -> None:
        if facet_id in seen:
            return
        facets.append({"facet_id": facet_id, "terms": list(terms), "required": True})
        seen.add(facet_id)

    named_entities = _named_question_entities(question)
    for entity in named_entities[:6]:
        add(f"entity_{_facet_id_for_term(entity)}", [entity])
    if "source of trust" in question_casefold:
        add("source_of_trust", ["source", "trust", "anchor", "authority"])
    if re.search(r"\bdoes\b.*\bprove\b|\bcan we safely infer\b|\bwhat can(?:'t|not) we infer\b", question_casefold):
        add("non_entailment_boundary", ["infer", "prove", "depend"])
        if any(
            term in question_casefold
            for term in ("precedes", "preceding", "comes before", "ordering", "sequence", "relation graph")
        ):
            add("ordering_boundary", ["ordering", "sequence", "precedes"])
    if "responsible for" in question_casefold or "each responsible" in question_casefold:
        add("responsibility_mapping", ["responsible", "for"])
    if "router" in question_casefold:
        add("router_selection", ["router"])
    if "router" in question_casefold and re.search(
        r"\b(request|input|decide|route|downstream|path|where)\b", question_casefold
    ):
        add("router_inputs", ["query", "feature", "path", "look", "decide", "request"])
        add(
            "routing_constraints",
            ["cost", "latency", "risk", "drift", "override", "fallback", "guardrail"],
        )
        add("downstream_selection", ["path", "mode", "fallback", "order", "pre-filter", "route"])
    if "dag" in question_casefold:
        add("dag_structure", ["dag", "dependency", "parallel"])
    if "query router" in question_casefold and "dag" in question_casefold:
        add("flow_composition", ["compose", "composition", "flow", "path"])
    if "adaptive planning" in question_casefold or "replan" in question_casefold:
        add("adaptive_replanning", ["adaptive", "replan", "plan"])
    if "local repair" in question_casefold or "global replan" in question_casefold:
        add("local_repair", ["local", "repair", "bounded"])
        add("global_replan", ["global", "replan", "invalidated", "assumption"])
    if "state machine" in question_casefold:
        add("state_machine", ["state", "machine", "transition"])
    lifecycle_context = any(
        marker in question_casefold
        for marker in (
            "client disconnect",
            "disconnect",
            "admission to completion",
            "intake to completion",
            "from admission",
            "from intake",
        )
    )
    full_lifecycle = any(
        marker in question_casefold
        for marker in (
            "admission to completion",
            "intake to completion",
            "from admission",
            "from intake",
            "surrounding control system",
            "keep the run trustworthy",
        )
    )
    if lifecycle_context and (full_lifecycle or any(term in question_casefold for term in ("admission", "intake", "policy"))):
        add("lifecycle_trust_envelope", ["admission", "completion", "observability"])
        add("admission_policy", ["admission", "policy", "owner"])
    if lifecycle_context and (
        full_lifecycle
        or any(
            term in question_casefold
            for term in ("disconnect", "persisted", "persist", "durable", "recover", "resume")
        )
    ):
        add("durable_state_authority", ["durable", "persisted", "state", "authority"])
    if lifecycle_context and (
        full_lifecycle
        or any(
            term in question_casefold
            for term in (
                "keeps working",
                "keep working",
                "keeps running",
                "keep running",
                "continues",
                "continue",
                "long-running",
            )
        )
    ):
        add("continued_execution", ["continue", "continued", "execution", "disconnect"])
    if lifecycle_context and (
        full_lifecycle
        or any(
            term in question_casefold
            for term in ("verification", "verified", "completion", "complete", "correct", "success", "acceptance")
        )
    ):
        add("verification_completion", ["verification", "completion", "complete", "acceptance"])
    if lifecycle_context and (
        full_lifecycle
        or any(
            term in question_casefold
            for term in ("observability", "reattach", "status", "headless", "inspect", "inspection", "resume")
        )
    ):
        add("observability_reattachment", ["observability", "reattach", "status", "resume"])
    if "verification" in question_casefold or "human approval" in question_casefold:
        add("verification_or_approval", ["verification", "approval"])
    if "human approval" in question_casefold:
        add("human_approval", ["human", "approval"])
    if "persisted" in question_casefold or "progress" in question_casefold:
        add("persisted_progress", ["persisted", "progress", "state"])
    if "parallel" in question_casefold or "branches" in question_casefold:
        add("parallel_branches", ["parallel", "branches"])
    if (
        any(term in question_casefold for term in ("pausing a venture", "pause a venture", "pausing", "survival decision"))
        and any(term in question_casefold for term in ("runway", "timing", "people", "resource", "constraint"))
    ):
        add("venture_pause_rationality", ["pause", "pausing", "venture", "survival", "rational"])
        add("conviction_problem_boundary", ["conviction", "believes", "believe", "problem"])
        add("runway_constraint", ["runway"])
        add("timing_constraint", ["timing"])
        add("people_constraint", ["people"])
        add("resource_constraint", ["resource", "resources", "constraints"])
    if (
        "demand" in question_casefold
        and any(term in question_casefold for term in ("viable business", "value capture", "economics", "delivery", "repeatability"))
    ):
        add("demand_not_business_proof", ["demand", "prove", "viable", "business"])
        add("value_capture", ["value", "capture", "willingness", "pay"])
        add("business_economics", ["economics"])
        add("business_delivery", ["delivery"])
        add("business_repeatability", ["repeatability", "repeatable", "repeat", "again", "return", "retained"])
    if (
        any(term in question_casefold for term in ("changes direction", "changed in the problem", "founder drift", "aimless"))
        and any(term in question_casefold for term in ("problem", "constraint", "market reality"))
    ):
        add("problem_evidence_changed", ["problem", "evidence", "learning"])
        add("constraint_change", ["constraint", "constraints", "runway", "resource", "timing"])
        add("market_reality_change", ["market", "reality", "customer", "adoption"])
        add("drift_boundary", ["drift", "aimless", "direction", "pitch"])
    if (
        any(term in question_casefold for term in ("pain point", "pain", "痛點"))
        and any(term in question_casefold for term in ("adopt", "adoption", "change willingness", "願意改變", "願意採用", "市場"))
    ):
        add("pain_acknowledgement", ["pain", "problem", "痛點"])
        add("change_willingness", ["willing", "change", "adopt", "adoption", "改變", "採用"])
        add("adoption_conditions", ["cost", "trust", "risk", "workflow", "conditions", "條件"])
        add("market_movement", ["market", "customer", "hospitality", "hotel", "市場", "旅宿"])
    if (
        "venture" in question_casefold
        and "product" in question_casefold
        and any(term in question_casefold for term in ("operations", "resources", "team", "finance", "risk"))
    ):
        add("venture_not_product", ["venture", "product", "system"])
        add("operations_system", ["operations", "operation", "delivery"])
        add("venture_resources", ["resources", "resource", "runway"])
        add("team_capacity", ["team", "people"])
        add("finance_model", ["finance", "financial", "margin", "cash", "runway"])
        add("risk_management", ["risk", "risks"])
    if (
        "comfyui" in question_casefold
        and any(term in question_casefold for term in ("red nodes", "out of memory", "memory", "workflow"))
    ):
        add("comfyui_failure_modes", ["comfyui", "red", "nodes", "memory", "workflow"])
        add("comfyui_checkpoints", ["checkpoints", "checkpoint"])
        add("comfyui_loras", ["loras", "lora"])
        add("comfyui_vae", ["vae"])
        add("comfyui_clip_t5xxl", ["clip", "t5xxl"])
        add("comfyui_quantization", ["gguf", "fp8"])
        add("comfyui_requirements", ["requirements", "required", "designed", "workflow", "release", "version", "matches", "stack"])
        add(
            "comfyui_memory_debug_order",
            [
                "boring on purpose",
                "minimal working state",
                "one variable at a time",
            ],
        )
    if re.search(r"\bsources?\b", question_casefold):
        add("multi_source_selection", ["source", "sources"])
    if "unlimited authority" in question_casefold or "without giving the replanner" in question_casefold:
        add("authority_boundary", ["authority", "boundary", "policy"])
    if not facets:
        add("direct_answer", sorted(_coverage_terms(question))[:6])
    return facets


def _named_question_entities(question: str) -> list[str]:
    entities: list[str] = []

    def add(entity: str) -> None:
        entity = " ".join(str(entity).strip(" ?:.,").split())
        if entity and entity.casefold() not in {item.casefold() for item in entities}:
            entities.append(entity)

    shared_part = re.search(
        r"\b([A-Z][A-Za-z0-9 .'/&-]{2,}?)\s+Part\s+(\d+)\b",
        question,
    )
    if shared_part:
        root = " ".join(shared_part.group(1).split())
        root = re.sub(
            r"^(?:If the relation graph records|The production graph says|"
            r"Does the precedes edge between|Can the precedes edge between|Does)\s+",
            "",
            root,
            flags=re.I,
        ).strip()
        for part in re.findall(r"\bPart\s+(\d+)\b", question, flags=re.I):
            add(f"{root} Part {part}")

    patterns = (
        r"Harness Theory Part \d+",
        r"Graphology",
        r"Sigma\.js",
        r"Obsidian",
        r"production router",
        r"adaptive planning",
        r"adaptive replanning",
        r"query router",
        r"state machine",
        r"DAG",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, question, flags=re.I):
            add(match.group(0))
    return entities


def _facet_id_for_term(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", term.casefold()).strip("_") or "facet"


def _minimum_evidence_rule(intent_class: str) -> dict[str, Any]:
    if intent_class == "cross_document_comparison":
        return {"minimum_evidence": 2, "minimum_distinct_source_identities": 2}
    if intent_class == "complementary_synthesis":
        return {"minimum_evidence": 2, "minimum_distinct_source_identities": 2}
    if intent_class == "graph_relationship":
        return {
            "minimum_evidence": 1,
            "requires_graph_edge": True,
            "requires_complete_graph_edge_fact": True,
        }
    if intent_class == "provenance_source_trace":
        return {"minimum_evidence": 2, "requires_passage": True, "requires_provenance": True}
    if intent_class == "temporal_conflict":
        return {"minimum_evidence": 2, "minimum_distinct_source_or_version_identities": 2}
    return {"minimum_evidence": 1}


def _repair_directive(previous_reason_codes: Sequence[str], *, intent_class: str) -> dict[str, Any]:
    reason_codes = sorted({str(code) for code in previous_reason_codes if str(code)})
    directives: list[str] = []
    if intent_class == "graph_relationship":
        directives.append("keep relation as ordering unless endpoint text explicitly supports more")
    if intent_class == "provenance_source_trace":
        directives.append("use one passage plus one provenance record")
    if any(code in {"M26-PA7-ME-003", "M26-PA7-ME-004", "M26-PA7-ME-005", "M26-PA7-ME-006"} for code in reason_codes):
        directives.append("return one compact JSON object with the required keys only")
    if "M26-PA7-ME-009" in reason_codes:
        directives.append("select only supplied evidence ids")
    if any(code in {"M26-PA7-ME-015", "M26-PA7-ME-016", "M26-PA7-ME-019", "M26-PA7-ME-020"} for code in reason_codes):
        directives.append("copy exact evidence text byte-for-byte into support refs")
    if any(code in {"M26-PA7-ME-032", "M26-PA7-ME-034", "M26-PA7-ME-045", "M26-PA7-ME-046"} for code in reason_codes):
        directives.append("rewrite the visible answer so every sentence is proposition-bound to supported claims")
    if not directives:
        directives.append("repair only the failing fields; keep the answer grounded and concise")
    return {
        "intent_class": intent_class,
        "previous_reason_codes": reason_codes,
        "directives": directives,
    }


def _parse_multi_provider_json(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(text) > 12_000:
        raise _verification_failure("M26-PA7-ME-001", "provider output exceeded bounded length")
    stripped = text.strip()
    if not stripped:
        raise _verification_failure("M26-PA7-ME-002", "provider output is empty")
    parsed, parse_meta = _extract_single_provider_json_object(stripped)
    value = _object(parsed, "provider JSON")
    required = {
        "schema_version",
        "status",
        "relation",
        "selected_evidence_ids",
        "answer_text",
        "claims",
        "abstention_reason",
    }
    optional = {"missing_facets", "unanswered_dimensions"}
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    parse_meta = {**parse_meta, "missing_keys": missing, "unknown_keys": unknown}
    if missing:
        raise _verification_failure(
            "M26-PA7-ME-005",
            "provider JSON missing required fields: " + ",".join(missing),
        )
    if unknown:
        raise _verification_failure(
            "M26-PA7-ME-006",
            "provider JSON contains unknown fields: " + ",".join(unknown),
        )
    return dict(value), parse_meta


def _extract_single_provider_json_object(stripped: str) -> tuple[Any, dict[str, Any]]:
    try:
        return json.loads(stripped), {"parse_subtype": "exact_json"}
    except json.JSONDecodeError:
        pass
    match = JSON_FENCE.fullmatch(stripped)
    if match is not None:
        try:
            return json.loads(match.group("body")), {"parse_subtype": "fenced_json"}
        except json.JSONDecodeError as exc:
            raise _verification_failure("M26-PA7-ME-004", "provider JSON is malformed") from exc
    decoder = json.JSONDecoder()
    decoded: list[tuple[int, int, Any]] = []
    malformed_start_seen = False
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            malformed_start_seen = True
            continue
        if isinstance(value, Mapping):
            decoded.append((index, index + end, value))
    if len(decoded) == 1:
        return decoded[0][2], {
            "parse_subtype": "single_object_with_wrapper",
            "ignored_prefix_chars": decoded[0][0],
            "ignored_suffix_chars": max(len(stripped) - decoded[0][1], 0),
        }
    if len(decoded) > 1:
        raise _verification_failure("M26-PA7-ME-003", "provider output contains multiple JSON objects")
    subtype = "truncated_or_malformed" if malformed_start_seen else "no_json_object"
    raise _verification_failure(
        "M26-PA7-ME-003",
        f"provider output is not one unambiguous JSON object: {subtype}",
    )


def _verify_multi_evidence_provider_output(
    *,
    trace_id: str,
    question: str,
    intent_class: str,
    evidence: Sequence[Mapping[str, Any]],
    provider_text: str,
    semantic_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if _secret_like(provider_text):
        raise _verification_failure("M26-PA7-ME-007", "provider output contains secret-like text")
    parsed, parse_meta = _parse_multi_provider_json(provider_text)
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
            "provider_parse": parse_meta,
            "material_claims": [],
            "required_facets": _required_facet_ids(question=question, intent_class=intent_class),
            "covered_facets": [],
            "missing_facets": _required_facet_ids(question=question, intent_class=intent_class),
        }

    claims = _list(parsed.get("claims"), "provider claims")
    if not claims:
        raise _verification_failure("M26-PA7-ME-011", "answer candidate has no claims")
    claim_records: list[dict[str, Any]] = []
    used_evidence_ids: set[str] = set()
    used_graph_edges: set[str] = set()
    covered_facets: set[str] = set()
    generic_model_explanation_without_support = False
    semantic_review_enabled = semantic_review is not None
    required_facets = set(_required_facet_ids(question=question, intent_class=intent_class))
    for index, raw_claim in enumerate(claims, start=1):
        claim = _object(raw_claim, "provider claim")
        required = {"claim_id", "claim_role"}
        if not required.issubset(claim):
            raise _verification_failure("M26-PA7-ME-012", "claim missing required fields")
        optional_claim_keys = {
            "surface_text",
            "facet_ids",
            "support_mode",
            "claim_type",
            "evidence_labels",
            "covers",
            "unanswered_dimensions",
            "support_refs",
        }
        if set(claim) - required - optional_claim_keys:
            raise _verification_failure("M26-PA7-ME-013", "claim contains unknown fields")
        claim_id = str(claim.get("claim_id") or f"claim_{index}")
        claim_role = str(claim.get("claim_role") or "direct")
        claim_type = str(claim.get("claim_type") or _claim_type_for_role(claim_role))
        surface_text = str(claim.get("surface_text") or "").strip()
        is_model_explanation = _is_model_explanation_claim(claim_type, claim_role)
        if "support_refs" in claim:
            support_refs = _list(claim.get("support_refs"), "claim support refs")
        else:
            support_refs = []
        if not support_refs and not is_model_explanation:
            raise _verification_failure("M26-PA7-ME-014", "claim has no support refs")
        if not support_refs and is_model_explanation:
            generic_model_explanation_without_support = True
            _verify_model_explanation_surface(
                surface_text=surface_text,
                answer_text=str(parsed.get("answer_text") or ""),
            )
        requested_facets = {
            str(item)
            for item in (claim.get("facet_ids") or [])
            if isinstance(item, (str, int)) and str(item)
        }
        ref_records: list[dict[str, Any]] = []
        for ref in support_refs:
            support = _object(ref, "claim support ref")
            if "exact_support_snippet" in support and "exact_quote" not in support:
                support = {**support, "exact_quote": support["exact_support_snippet"]}
            ref_required = {"evidence_id", "locator_id", "exact_quote"}
            if not ref_required.issubset(support):
                raise _verification_failure("M26-PA7-ME-015", "support ref missing fields")
            if set(support) - ref_required - {"exact_support_snippet", "uncertainty"}:
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
        if (
            _claim_requires_multi_source(intent_class, claim_role)
            and _distinct_source_count(
                evidence_by_id[str(ref["evidence_id"])] for ref in ref_records
            )
            < 2
            and not is_model_explanation
            and not semantic_review_enabled
        ):
            raise _verification_failure("M26-PA7-ME-021", "relational claim lacks two sources")
        if not surface_text:
            surface_text = " ".join(str(ref["exact_quote"]) for ref in ref_records)
        if not semantic_review_enabled:
            _verify_claim_surface_semantics(
                question=question,
                intent_class=intent_class,
                relation=str(parsed.get("relation") or ""),
                claim_role=claim_role,
                claim_type=claim_type,
                surface_text=surface_text,
                support_refs=ref_records,
                evidence_by_id=evidence_by_id,
            )
            claim_facets = set(
                _validated_claim_facets(
                    question=question,
                    intent_class=intent_class,
                    claim_role=claim_role,
                    claim_type=claim_type,
                    surface_text=surface_text,
                    support_refs=ref_records,
                    evidence_by_id=evidence_by_id,
                    requested_facet_ids=requested_facets,
                    answer_text=str(parsed.get("answer_text") or ""),
                )
            )
        else:
            claim_facets = requested_facets & required_facets
            if not claim_facets and is_model_explanation:
                claim_facets = requested_facets
        covered_facets |= claim_facets & required_facets
        claim_records.append(
            {
                "claim_id": claim_id,
                "claim_role": claim_role,
                "claim_type": claim_type,
                "surface_text": surface_text,
                "facet_ids": sorted(claim_facets),
                "support_mode": str(
                    claim.get("support_mode")
                    or (
                        "model_explanation"
                        if is_model_explanation and not ref_records
                        else "exact_quote"
                    )
                ),
                "evidence_labels": [
                    str(item) for item in claim.get("evidence_labels", []) if str(item)
                ],
                "covers": [
                    str(item) for item in claim.get("covers", []) if str(item)
                ],
                "unanswered_dimensions": [
                    str(item)
                    for item in claim.get("unanswered_dimensions", [])
                    if str(item)
                ],
                "material": True,
                "support_refs": ref_records,
                "support_verdict": (
                    "generic_model_explanation"
                    if is_model_explanation and not ref_records
                    else "supported_exact_multi_evidence_bundle"
                ),
            }
        )
    if not semantic_review_enabled or intent_class in {
        "graph_relationship",
        "provenance_source_trace",
    }:
        _enforce_intent_minimums(
            intent_class=intent_class,
            evidence=[evidence_by_id[item] for item in used_evidence_ids],
        )
    selected_or_used = selected_ids or sorted(used_evidence_ids)
    if not set(used_evidence_ids).issubset(set(selected_or_used)):
        raise _verification_failure("M26-PA7-ME-022", "claim used evidence outside selection")
    if (
        selected_ids
        and not used_evidence_ids
        and not generic_model_explanation_without_support
    ):
        raise _verification_failure("M26-PA7-ME-028", "selected evidence was not used by claims")
    answer_text = str(parsed.get("answer_text") or "")
    try:
        _verify_answer_material_anchors(answer_text=answer_text, claims=claim_records)
    except VerifiedAnswerGateError as exc:
        if exc.code not in {"M26-PA7-ME-038", "M26-PA7-ME-039"}:
            raise
    semantic_review_summary = None
    if semantic_review_enabled:
        semantic_review_summary = _validate_semantic_entailment_review(
            semantic_review=semantic_review,
            claim_records=claim_records,
        )
        covered_facets |= required_facets
    missing_facets = sorted(required_facets - covered_facets)
    if missing_facets:
        raise _verification_failure("M26-PA7-ME-029", "answer candidate misses required facets")
    _verify_question_evidence_relevance(
        question=question,
        intent_class=intent_class,
        claims=claim_records,
        used_evidence_ids=used_evidence_ids,
        evidence_by_id=evidence_by_id,
    )
    return {
        "case_id": trace_id,
        "terminal_status": "verified_answer_ready_candidate",
        "provider_status": str(status),
        "relation": parsed.get("relation"),
        "answer_text": answer_text,
        "selected_evidence_ids": selected_or_used,
        "selected_graph_edge_ids": sorted(used_graph_edges),
        "used_evidence_ids": sorted(used_evidence_ids),
        "required_facets": sorted(required_facets),
        "covered_facets": sorted(covered_facets & required_facets),
        "missing_facets": missing_facets,
        "material_claims": claim_records,
        "provider_parse": parse_meta,
        "support_verification": {
            "material_claim_count": len(claim_records),
            "supported_claim_count": len(claim_records),
            "unsupported_claim_count": 0,
            "citation_precision": 1.0,
            "support_threshold_met": True,
        },
        "semantic_review_verified": semantic_review_summary is not None,
        "semantic_review": semantic_review_summary or {},
    }


def _required_facet_ids(*, question: str, intent_class: str) -> list[str]:
    return [
        str(item["facet_id"])
        for item in _question_contract(
            question=question,
            intent_class=intent_class,
        )["required_facets"]
    ]


SEMANTIC_REVIEW_SCHEMA_VERSION = "m26-claim-entailment-review/v1"
SEMANTIC_REVIEW_ENTAILED = "ENTAILED"
SEMANTIC_REVIEW_GENERIC_EXPLANATION = "GENERIC_EXPLANATION"
SEMANTIC_REVIEW_BLOCKING_VERDICTS = {"CONTRADICTED", "INSUFFICIENT"}


def _validate_semantic_entailment_review(
    *,
    semantic_review: Mapping[str, Any] | None,
    claim_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    review = _object(semantic_review, "semantic entailment review")
    if review.get("schema_version") != SEMANTIC_REVIEW_SCHEMA_VERSION:
        raise _verification_failure(
            "M26-PA7-ME-058",
            "semantic review schema is invalid",
        )
    raw_coverage = review.get("visible_coverage")
    coverage = _object(raw_coverage, "semantic visible coverage")
    if coverage.get("verdict") != "COVERED":
        raise _verification_failure(
            "M26-PA7-ME-059",
            "visible answer has uncovered material assertions",
        )
    uncovered = coverage.get("uncovered_assertions", [])
    if not isinstance(uncovered, list):
        raise _verification_failure(
            "M26-PA7-ME-060",
            "semantic visible coverage is malformed",
        )
    raw_judgments = _list(review.get("claim_judgments"), "semantic claim judgments")
    claim_by_id = {
        str(claim.get("claim_id", "")): claim
        for claim in claim_records
        if str(claim.get("claim_id", ""))
    }
    judgments_by_claim: dict[str, dict[str, Any]] = {}
    for raw_judgment in raw_judgments:
        judgment = _object(raw_judgment, "semantic claim judgment")
        if set(judgment) - {"claim_id", "verdict", "evidence_ids"}:
            raise _verification_failure(
                "M26-PA7-ME-061",
                "semantic review judgment contains unknown fields",
            )
        claim_id = str(judgment.get("claim_id", ""))
        if claim_id not in claim_by_id:
            raise _verification_failure(
                "M26-PA7-ME-062",
                "semantic review references unknown claim",
            )
        if claim_id in judgments_by_claim:
            raise _verification_failure(
                "M26-PA7-ME-063",
                "semantic review has duplicate claim judgment",
            )
        verdict = str(judgment.get("verdict", ""))
        if verdict not in {
            SEMANTIC_REVIEW_ENTAILED,
            SEMANTIC_REVIEW_GENERIC_EXPLANATION,
            *SEMANTIC_REVIEW_BLOCKING_VERDICTS,
        }:
            raise _verification_failure(
                "M26-PA7-ME-064",
                "semantic review verdict is invalid",
            )
        evidence_ids = [str(item) for item in _list(judgment.get("evidence_ids"), "semantic evidence ids")]
        local_allowed = {
            str(ref.get("evidence_id", ""))
            for ref in _list(
                claim_by_id[claim_id].get("support_refs"),
                "semantic claim local support refs",
            )
            if str(ref.get("evidence_id", ""))
        }
        if not set(evidence_ids).issubset(local_allowed):
            raise _verification_failure(
                "M26-PA7-ME-065",
                "semantic review used evidence outside claim-local support",
            )
        judgments_by_claim[claim_id] = {
            "claim_id": claim_id,
            "verdict": verdict,
            "evidence_ids": evidence_ids,
        }

    for claim_id, claim in claim_by_id.items():
        judgment = judgments_by_claim.get(claim_id)
        if judgment is None:
            raise _verification_failure(
                "M26-PA7-ME-066",
                "semantic review is missing a material claim judgment",
            )
        claim_type = str(claim.get("claim_type", ""))
        support_refs = _list(claim.get("support_refs"), "semantic claim support refs")
        verdict = str(judgment["verdict"])
        if claim_type == "MODEL_EXPLANATION" and not support_refs:
            if verdict != SEMANTIC_REVIEW_GENERIC_EXPLANATION:
                raise _verification_failure(
                    "M26-PA7-ME-067",
                    "generic model explanation verdict is invalid",
                )
            continue
        if verdict in SEMANTIC_REVIEW_BLOCKING_VERDICTS:
            raise _verification_failure(
                "M26-PA7-ME-068",
                "semantic review rejected a material claim",
            )
        if verdict != SEMANTIC_REVIEW_ENTAILED:
            raise _verification_failure(
                "M26-PA7-ME-069",
                "semantic review did not entail a material claim",
            )
        if not judgment["evidence_ids"]:
            raise _verification_failure(
                "M26-PA7-ME-070",
                "semantic review entailed claim without local evidence",
            )

    return {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "claim_judgments": [
            judgments_by_claim[claim_id] for claim_id in sorted(judgments_by_claim)
        ],
        "visible_coverage": {
            "verdict": "COVERED",
            "uncovered_assertions": [],
        },
    }


def _validated_claim_facets(
    *,
    question: str,
    intent_class: str,
    claim_role: str,
    claim_type: str,
    surface_text: str,
    support_refs: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    requested_facet_ids: set[str],
    answer_text: str,
) -> list[str]:
    """Accept facet coverage only when visible/support text carries the proposition."""
    inferred = set(
        _infer_covered_facets(
            question=question,
            intent_class=intent_class,
            claim_role=claim_role,
            surface_text=surface_text,
            support_refs=support_refs,
            evidence_by_id=evidence_by_id,
        )
    )
    if claim_type == "MODEL_EXPLANATION" and not support_refs:
        visible_text = _strip_runtime_markers(f"{answer_text} {surface_text}")
        visible_terms = _coverage_terms(visible_text)
        if not visible_terms:
            return []
        return sorted(
            str(facet["facet_id"])
            for facet in _question_contract(question=question, intent_class=intent_class)[
                "required_facets"
            ]
            if str(facet.get("facet_id", "")) in requested_facet_ids
            and _facet_terms(facet) & visible_terms
        )
    if intent_class != "direct_grounded_knowledge":
        return sorted(inferred)

    visible_text = _strip_runtime_markers(f"{answer_text} {surface_text}")
    visible_terms = _coverage_terms(visible_text)
    support_text = " ".join(str(ref.get("exact_quote", "")) for ref in support_refs)
    support_terms = _coverage_terms(support_text)
    support_casefold = support_text.casefold()
    evidence_items = [
        evidence_by_id[str(ref.get("evidence_id", ""))]
        for ref in support_refs
        if str(ref.get("evidence_id", "")) in evidence_by_id
    ]
    evidence_text = " ".join(str(item.get("passage_text", "")) for item in evidence_items)
    evidence_terms = _coverage_terms(
        evidence_text
    )
    evidence_casefold = evidence_text.casefold()
    candidate_facets = inferred | (requested_facet_ids & set(_required_facet_ids(question=question, intent_class=intent_class)))
    accepted: set[str] = set()
    for facet in _question_contract(question=question, intent_class=intent_class)[
        "required_facets"
    ]:
        facet_id = str(facet.get("facet_id", ""))
        if facet_id not in candidate_facets:
            continue
        if _direct_facet_signal_met(
            facet_id=facet_id,
            facet_terms=_facet_terms(facet),
            visible_text=visible_text,
            visible_terms=visible_terms,
            support_text=support_casefold,
            support_terms=support_terms,
            evidence_text=evidence_casefold,
            evidence_terms=evidence_terms,
        ):
            accepted.add(facet_id)
    return sorted(accepted)


def _strip_runtime_markers(text: str) -> str:
    stripped = CLAIM_ANCHOR_RE.sub(" ", str(text))
    stripped = LEGACY_CITATION_RE.sub(" ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _direct_facet_signal_met(
    *,
    facet_id: str,
    facet_terms: set[str],
    visible_text: str,
    visible_terms: set[str],
    support_text: str,
    support_terms: set[str],
    evidence_text: str,
    evidence_terms: set[str],
) -> bool:
    visible_casefold = visible_text.casefold()
    exact_phrases = _direct_facet_required_phrases(facet_id)
    if exact_phrases:
        return any(phrase in visible_casefold for phrase in exact_phrases) and any(
            phrase in support_text
            for phrase in exact_phrases
        )
    quote_groups = _direct_facet_required_quote_groups(facet_id)
    if quote_groups:
        support_casefold = support_text.casefold()
        return all(any(term in support_casefold for term in group) for group in quote_groups)
    if facet_id == "non_entailment_boundary":
        return _has_non_entailment_boundary(visible_casefold)
    if facet_id == "ordering_boundary":
        return bool(visible_terms & ORDER_SURFACE_TERMS) and "precede" in (
            visible_terms | support_terms | evidence_terms
        )
    if facet_id == "direct_answer":
        return bool(visible_terms & (support_terms | evidence_terms))
    if not facet_terms:
        return bool(visible_terms & (support_terms | evidence_terms))
    visible_overlap = visible_terms & facet_terms
    grounded_overlap = (support_terms | evidence_terms) & facet_terms
    if not visible_overlap or not grounded_overlap:
        return False
    needed = 1
    combined_overlap = visible_overlap | grounded_overlap
    if facet_id.startswith("entity_"):
        needed = min(needed, len(facet_terms))
    return len(combined_overlap) >= needed


def _has_non_entailment_boundary(text_casefold: str) -> bool:
    negative = bool(
        re.search(
            r"\b(no|not|cannot|can't|does not|doesn't|do not|don't|insufficient|only)\b",
            text_casefold,
        )
    )
    boundary = bool(
        re.search(
            r"\b(infer|prove|proves|depend|depends|dependency|require|requires|causal|cause)\b",
            text_casefold,
        )
    )
    return negative and boundary


def _verify_question_evidence_relevance(
    *,
    question: str,
    intent_class: str,
    claims: Sequence[Mapping[str, Any]],
    used_evidence_ids: set[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    if intent_class != "direct_grounded_knowledge":
        return
    subjects = _question_relevance_subjects(question)
    if not subjects:
        return
    evidence_items = [
        evidence_by_id[evidence_id]
        for evidence_id in sorted(used_evidence_ids)
        if evidence_id in evidence_by_id
    ]
    support_text_by_evidence_id: dict[str, list[str]] = {}
    for claim in claims:
        for ref in _list(claim.get("support_refs", []), "verified claim support refs"):
            evidence_id = str(_object(ref, "verified claim support ref").get("evidence_id", ""))
            support_text_by_evidence_id.setdefault(evidence_id, []).append(
                str(_object(ref, "verified claim support ref").get("exact_quote", ""))
            )
    relevance_items = [
        (
            str(item.get("evidence_id", "")),
            " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("section_title", "")),
                    str(item.get("concept_id", "")),
                    str(item.get("section_id", "")),
                    str(item.get("passage_text", "")),
                    " ".join(
                        support_text_by_evidence_id.get(str(item.get("evidence_id", "")), [])
                    ),
                ]
            ),
        )
        for item in evidence_items
    ]
    if not relevance_items:
        return

    request_groups = _requested_attribute_groups(question=question, subjects=subjects)
    for subject in subjects:
        subject_norm = _normalized_relevance_text(subject)
        if not subject_norm:
            continue
        subject_terms = set(subject_norm.split())
        subject_items = [
            evidence_id
            for evidence_id, text in relevance_items
            if _contains_normalized_unit(text, subject_norm)
        ]
        if not subject_items:
            evidence_terms = _meaningful_terms(" ".join(text for _, text in relevance_items))
            decomposed = sorted((subject_terms & evidence_terms) - _relevance_common_terms())
            detail = (
                "decomposed terms: " + ", ".join(decomposed[:8])
                if decomposed
                else "no subject-unit evidence"
            )
            raise _verification_failure(
                QUESTION_EVIDENCE_RELEVANCE_CODE,
                (
                    f"{QUESTION_EVIDENCE_RELEVANCE_HARD_STOP}: compound subject "
                    f"'{subject}' is not established as a coherent unit in used evidence; "
                    f"{detail}"
                ),
            )
        missing_groups = [
            sorted(group)
            for group in request_groups
            if not any(_text_supports_attribute_group(text, group) for _, text in relevance_items)
        ]
        if missing_groups:
            group_labels = ["/".join(group[:3]) for group in missing_groups]
            raise _verification_failure(
                QUESTION_EVIDENCE_RELEVANCE_CODE,
                (
                    f"{QUESTION_EVIDENCE_RELEVANCE_HARD_STOP}: used evidence establishes "
                    f"compound subject '{subject}' but not requested attribute/action "
                    f"{', '.join(group_labels)}"
                ),
            )


def _is_question_evidence_relevance_hard_stop(exc: VerifiedAnswerGateError) -> bool:
    return (
        exc.code == QUESTION_EVIDENCE_RELEVANCE_CODE
        and QUESTION_EVIDENCE_RELEVANCE_HARD_STOP in exc.safe_message
    )


def _question_relevance_subjects(question: str) -> list[str]:
    subjects: list[str] = []

    def add(candidate: str, *, require_specific_entity: bool = False) -> None:
        cleaned = re.sub(r"\s+", " ", str(candidate).strip(" ?!.,;:'\"()[]{}"))
        cleaned = re.sub(
            r"^(?:(?:what|which|when|where|why|how|does|do|did|can|should|could)\s+)+",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        if not cleaned:
            return
        if require_specific_entity and not _looks_like_specific_question_subject(cleaned):
            return
        normalized = _normalized_relevance_text(cleaned)
        if not normalized or len(normalized.split()) < 2:
            return
        if normalized not in {
            _normalized_relevance_text(existing)
            for existing in subjects
        }:
            subjects.append(cleaned)

    for entity in _named_question_entities(question):
        add(entity)
    for match in re.finditer(r"['\"]([^'\"]{4,})['\"]", question):
        add(match.group(1))
    boundary = (
        r"(?=\s+(?:for|when|where|while|during|after|before|because|if|that|"
        r"which|who|whose|with|without|using|from|in|on|at|to|as|"
        r"is|are|was|were)\b|[?.,;:]|$)"
    )
    broad_subject_patterns = (
        rf"\bby\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{{5,}}?){boundary}",
        rf"\bof\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{{5,}}?){boundary}",
        rf"\bfor\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{{5,}}?){boundary}",
        r"\bthe\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{5,}?)['’]s\s+"
        r"(?:[a-z][a-z0-9-]*)(?:\s+[a-z][a-z0-9-]*){0,4}\b",
        r"\b(?:does|do|did|can|should|could|would)\s+the\s+"
        r"([A-Za-z0-9][A-Za-z0-9 .'/&-]{5,}?)\s+"
        r"(?:announce|announced|launch|launched|release|released|ship|shipped|"
        r"specify|specified|define|defines|state|states|require|requires|store|stores|"
        r"use|uses|set|sets|list|lists|own|owns|route|routes)\b",
    )
    for pattern in broad_subject_patterns:
        for match in re.finditer(pattern, question, flags=re.I):
            add(match.group(1), require_specific_entity=True)
    patterns = (
        r"\bfor\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{5,}?)\??$",
        r"\bdid\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{5,}?)\s+"
        r"(?:announce|announced|launch|launched|release|released|ship|shipped)\b",
        r"\bwas\s+announced\s+for\s+the\s+([A-Za-z0-9][A-Za-z0-9 .'/&-]{5,}?)\??$",
    )
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.I)
        if match is not None:
            add(match.group(1))
    return subjects


def _looks_like_specific_question_subject(candidate: str) -> bool:
    normalized = _normalized_relevance_text(candidate)
    tokens = normalized.split()
    if len(tokens) < 2:
        return False
    if re.search(r"[A-Za-z0-9]+-[A-Za-z0-9]+", candidate):
        return True
    if re.search(r"\b[A-Z]{2,}\b|[A-Z][a-z]+[A-Z][A-Za-z]*", candidate):
        return True
    if tokens[0] in {"nonexistent", "invented", "fictional", "fake", "unsupported"}:
        return len(tokens) >= 3
    entity_type_terms = {
        "agent",
        "api",
        "bridge",
        "engine",
        "entity",
        "framework",
        "graph",
        "lattice",
        "module",
        "pipeline",
        "platform",
        "protocol",
        "router",
        "server",
        "service",
        "system",
        "workflow",
    }
    return len(tokens) >= 3 and tokens[-1] in entity_type_terms


def _requested_attribute_groups(
    *,
    question: str,
    subjects: Sequence[str],
) -> list[set[str]]:
    question_norm = _normalized_relevance_text(question)
    for subject in subjects:
        subject_norm = _normalized_relevance_text(subject)
        if subject_norm:
            question_norm = re.sub(
                rf"\b{re.escape(subject_norm)}\b",
                " ",
                question_norm,
            )
    groups: list[set[str]] = []

    def add(*terms: str) -> None:
        group = {term for term in terms if term}
        if group and group not in groups:
            groups.append(group)

    terms = set(question_norm.split())
    if "date" in terms:
        if "launch" in terms:
            add("date", "launch")
        if "integration" in terms:
            add("date", "integration")
        if "release" in terms:
            add("date", "release")
        if "announce" in terms or "announced" in terms:
            add("date", "announce")
    return groups


def _normalized_relevance_text(text: str) -> str:
    lowered = str(text).casefold().replace("-", " ")
    tokens = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", lowered)
    return " ".join(tokens)


def _contains_normalized_unit(text: str, unit: str) -> bool:
    normalized_text = f" {_normalized_relevance_text(text)} "
    normalized_unit = _normalized_relevance_text(unit)
    if not normalized_unit:
        return False
    if f" {normalized_unit} " in normalized_text:
        return True
    unit_tokens = normalized_unit.split()
    variants: list[str] = []
    if len(unit_tokens) >= 2 and not unit_tokens[-1].endswith("s"):
        variants.append(" ".join([*unit_tokens[:-1], f"{unit_tokens[-1]}s"]))
    if len(unit_tokens) >= 2 and unit_tokens[-1].endswith("s"):
        variants.append(" ".join([*unit_tokens[:-1], unit_tokens[-1].removesuffix("s")]))
    return any(f" {variant} " in normalized_text for variant in variants)


def _relevance_common_terms() -> set[str]:
    return {
        "announce",
        "announced",
        "date",
        "integration",
        "launch",
        "module",
        "nonexistent",
        "platform",
        "project",
        "protocol",
        "release",
        "system",
        "team",
        "ticketing",
    }


def _text_supports_attribute_group(text: str, group: set[str]) -> bool:
    normalized_terms = set(_normalized_relevance_text(text).split())
    if not normalized_terms:
        return False
    for term in group:
        if term == "announce":
            if not any(token.startswith("announce") for token in normalized_terms):
                return False
            continue
        if term not in normalized_terms:
            return False
    return True


def _question_requires_non_entailment_boundary(question: str) -> bool:
    q = question.casefold()
    return "precedes" in q and bool(
        re.search(r"\b(prove|proves|infer|depends?|dependency|require|requires|causal|cause)\b", q)
    )


def _infer_covered_facets(
    *,
    question: str,
    intent_class: str,
    claim_role: str,
    surface_text: str,
    support_refs: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    support_items = [
        evidence_by_id[str(ref.get("evidence_id", ""))]
        for ref in support_refs
        if str(ref.get("evidence_id", "")) in evidence_by_id
    ]
    evidence_types = {str(item.get("evidence_type", "passage")) for item in support_items}
    source_count = _distinct_source_count(support_items)
    required = _required_facet_ids(question=question, intent_class=intent_class)
    if intent_class == "graph_relationship":
        facets: list[str] = []
        if "graph_edge" in evidence_types:
            facets.append("graph_edge")
        passage_concepts = {
            str(item.get("concept_id", ""))
            for item in support_items
            if item.get("evidence_type") == "passage"
        }
        edge = next(
            (item for item in support_items if item.get("evidence_type") == "graph_edge"), None
        )
        if edge is not None:
            complete_edge_fact = bool(
                str(edge.get("edge_source", ""))
                and str(edge.get("edge_target", ""))
                and str(edge.get("relation_type", ""))
            )
            if complete_edge_fact or str(edge.get("edge_source", "")) in passage_concepts:
                facets.append("source_endpoint")
            if complete_edge_fact or str(edge.get("edge_target", "")) in passage_concepts:
                facets.append("target_endpoint")
            facets.append("relation_semantics")
        return facets
    if intent_class == "provenance_source_trace":
        return [
            facet
            for facet in ("passage_claim", "provenance_record")
            if (facet == "passage_claim" and "passage" in evidence_types)
            or (facet == "provenance_record" and "provenance" in evidence_types)
        ]
    if intent_class == "temporal_conflict":
        return required if "temporal_record" in evidence_types and source_count >= 2 else []
    if intent_class in {"cross_document_comparison", "complementary_synthesis"}:
        return (
            required if source_count >= 2 and claim_role in {"relationship", "comparison"} else []
        )
    if intent_class == "direct_grounded_knowledge":
        if not surface_text.strip():
            surface_text = " ".join(str(ref.get("exact_quote", "")) for ref in support_refs)
        surface_terms = _coverage_terms(surface_text)
        support_terms = _coverage_terms(" ".join(str(ref.get("exact_quote", "")) for ref in support_refs))
        covered = []
        for facet in _question_contract(question=question, intent_class=intent_class)[
            "required_facets"
        ]:
            facet_terms = _facet_terms(facet)
            if facet_terms and facet_terms & surface_terms and facet_terms & support_terms:
                covered.append(str(facet["facet_id"]))
        return covered
    return required[:1] if support_items else []


def _verify_claim_surface_semantics(
    *,
    question: str,
    intent_class: str,
    relation: str,
    claim_role: str,
    claim_type: str,
    surface_text: str,
    support_refs: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    surface = re.sub(r"\s+", " ", surface_text).strip()
    if not surface or len(surface) > 1_200:
        raise _verification_failure("M26-PA7-ME-030", "claim surface text is invalid")
    if claim_type == "MODEL_EXPLANATION" and not support_refs:
        _verify_model_explanation_surface(surface_text=surface, answer_text=surface)
        return
    if claim_type == "MODEL_EXPLANATION" and support_refs:
        raise _verification_failure(
            "M26-PA7-ME-052",
            "generic model explanation must not carry corpus citation refs",
        )
    support_text = " ".join(str(ref.get("exact_quote", "")) for ref in support_refs)
    support_terms = _meaningful_terms(support_text)
    surface_terms = _meaningful_terms(surface)
    question_terms = _coverage_terms(question)
    if not support_terms or not surface_terms:
        raise _verification_failure("M26-PA7-ME-031", "claim surface has no support terms")
    if _question_requires_non_entailment_boundary(question) and not _has_non_entailment_boundary(
        surface.casefold()
    ):
        raise _verification_failure(
            "M26-PA7-ME-047",
            "false-premise precedes question lacks explicit non-entailment boundary",
        )
    shared_support_terms = surface_terms & support_terms
    shared_question_terms = surface_terms & question_terms
    is_synthesis = claim_type == "EVIDENCE_SYNTHESIS" or claim_role in {
        "relationship",
        "comparison",
        "temporal",
    }
    if is_synthesis:
        _verify_synthesis_premise_binding(
            surface_terms=surface_terms,
            question_terms=question_terms,
            support_refs=support_refs,
        )
    elif len(shared_support_terms) < 2:
        raise _verification_failure(
            "M26-PA7-ME-032",
            "direct claim surface is not bound to cited support",
        )
    if is_synthesis and len(shared_support_terms) < 2 and not shared_question_terms:
        raise _verification_failure(
            "M26-PA7-ME-032",
            "claim surface is not semantically aligned to exact support",
        )
    if is_synthesis:
        surface_casefold = surface.casefold()
        if any(phrase in surface_casefold for phrase in SYNTHESIS_CONTRADICTION_PHRASES):
            raise _verification_failure(
                "M26-PA7-ME-048",
                "claim surface makes an unsupported equivalence claim",
            )
    support_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", support_text))
    question_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", question))
    unsupported_numbers = (
        set(re.findall(r"\b\d+(?:\.\d+)?\b", surface)) - support_numbers - question_numbers
    )
    if unsupported_numbers:
        raise _verification_failure("M26-PA7-ME-033", "claim surface introduces unsupported number")
    _verify_hard_truth_boundary_mutations(
        surface_text=surface,
        support_text=support_text,
        question=question,
    )
    strengthened = surface_terms & MODALITY_STRENGTHENING_TERMS
    if (
        strengthened
        and not strengthened.issubset(support_terms | question_terms)
        and not (
            _has_non_entailment_boundary(surface.casefold())
            and strengthened.issubset(support_terms | question_terms | {"must", "requires"})
        )
    ):
        raise _verification_failure(
            "M26-PA7-ME-034",
            "claim surface strengthens modality beyond evidence",
        )
    evidence_items = [
        evidence_by_id[str(ref["evidence_id"])]
        for ref in support_refs
        if str(ref.get("evidence_id", "")) in evidence_by_id
    ]
    graph_edges = [item for item in evidence_items if item.get("evidence_type") == "graph_edge"]
    if intent_class == "graph_relationship" or claim_role == "relationship":
        for edge in graph_edges:
            relation_type = str(edge.get("relation_type", ""))
            if relation_type == "precedes" or relation == "precedes":
                dependency_upgrade = bool(surface_terms & DEPENDENCY_TERMS) and not (
                    _has_non_entailment_boundary(surface.casefold())
                )
                ordering_ack = (
                    bool(surface_terms & ORDER_SURFACE_TERMS)
                    or "does not prove" in surface.casefold()
                )
                endpoint_text = " ".join(
                    str(item.get("passage_text", ""))
                    for item in evidence_items
                    if item.get("evidence_type") == "passage"
                )
                endpoint_terms = _meaningful_terms(endpoint_text)
                if dependency_upgrade and not (surface_terms & DEPENDENCY_TERMS).issubset(
                    endpoint_terms
                ):
                    raise _verification_failure(
                        "M26-PA7-ME-035",
                        "precedes graph edge was upgraded to dependency semantics",
                    )
                if not ordering_ack and not dependency_upgrade:
                    raise _verification_failure(
                        "M26-PA7-ME-036",
                        "precedes graph edge is nonresponsive without ordering semantics",
                    )
                _verify_graph_direction_not_reversed(
                    surface=surface,
                    edge=edge,
                    evidence_items=evidence_items,
                )


def _verify_synthesis_premise_binding(
    *,
    surface_terms: set[str],
    question_terms: set[str],
    support_refs: Sequence[Mapping[str, Any]],
) -> None:
    if len(support_refs) < 2:
        return
    premise_targets = surface_terms | question_terms
    contributing_refs = 0
    for ref in support_refs:
        ref_terms = _meaningful_terms(str(ref.get("exact_quote", "")))
        if len(ref_terms & premise_targets) >= 1:
            contributing_refs += 1
    if contributing_refs < 2:
        raise _verification_failure(
            "M26-PA7-ME-052",
            "synthesis citation refs are not bound to contributing premises",
        )


def _verify_hard_truth_boundary_mutations(
    *,
    surface_text: str,
    support_text: str,
    question: str = "",
) -> None:
    surface = re.sub(r"\s+", " ", str(surface_text)).strip()
    support = re.sub(r"\s+", " ", str(support_text)).strip()
    if not surface or not support:
        return
    surface_casefold = surface.casefold()
    support_casefold = support.casefold()
    surface_terms = _meaningful_terms(surface)
    support_terms = _meaningful_terms(support)
    question_terms = _coverage_terms(question)
    shared_terms = (surface_terms & support_terms) - _relevance_common_terms()

    causal_upgrade = surface_terms & CAUSALITY_UPGRADE_TERMS
    if (
        causal_upgrade
        and not causal_upgrade.issubset(support_terms | question_terms)
        and not support_terms & CAUSALITY_SUPPORT_TERMS
    ):
        raise _verification_failure(
            "M26-PA7-ME-053",
            "claim surface upgrades association or ordering into causality",
        )

    for number in re.findall(r"\b\d+(?:\.\d+)?\b", surface):
        if not re.search(rf"\b(?:exactly|precisely)\s+{re.escape(number)}\b", surface_casefold):
            continue
        if re.search(
            rf"\b(?:about|approximately|around|at least|more than|over)\s+{re.escape(number)}\b",
            support_casefold,
        ) and not re.search(
            rf"\b(?:exactly|precisely)\s+{re.escape(number)}\b",
            support_casefold,
        ):
            raise _verification_failure(
                "M26-PA7-ME-033",
                "claim surface converts approximate or bounded quantity into exact quantity",
            )

    if (
        surface_terms & UNIVERSAL_SCOPE_TERMS
        and support_terms & PARTIAL_SCOPE_TERMS
        and not support_terms & UNIVERSAL_SCOPE_TERMS
    ):
        raise _verification_failure(
            "M26-PA7-ME-054",
            "claim surface expands partial scope into universal scope",
        )

    support_entities = _hard_boundary_entities(support)
    surface_entities = _hard_boundary_entities(surface)
    question_entities = _hard_boundary_entities(question)
    invented_entities = surface_entities - support_entities - question_entities
    if invented_entities and support_entities and (shared_terms or len(surface_terms & support_terms) >= 2):
        raise _verification_failure(
            "M26-PA7-ME-055",
            "claim surface swaps or invents a named entity",
        )

    if (
        _has_material_negation(surface_casefold) != _has_material_negation(support_casefold)
        and shared_terms
        and not _has_non_entailment_boundary(surface_casefold)
    ):
        raise _verification_failure(
            "M26-PA7-ME-056",
            "claim surface flips factual polarity",
        )


def _hard_boundary_entities(text: str) -> set[str]:
    normalized = re.sub(r"[_-]+", " ", str(text))
    entities = {
        re.sub(r"\s+", " ", item).strip().casefold()
        for item in re.findall(
            r"\b(?:[A-Z][A-Za-z0-9]*(?:\s+[A-Z0-9][A-Za-z0-9]*)+|Entity\s+[A-Z0-9]+)\b",
            normalized,
        )
    }
    return {
        item
        for item in entities
        if item not in {"the", "a", "an"}
        and not item.startswith(("the ", "a ", "an "))
    }


def _has_material_negation(text_casefold: str) -> bool:
    text = re.sub(r"\bnot only\b", " ", text_casefold)
    return bool(
        re.search(
            r"\b(?:no|not|never|cannot|can't|does not|doesn't|do not|don't|without)\b",
            text,
        )
    )


def _verify_graph_direction_not_reversed(
    *,
    surface: str,
    edge: Mapping[str, Any],
    evidence_items: Sequence[Mapping[str, Any]],
) -> None:
    relation_type = str(edge.get("relation_type", ""))
    if relation_type != "precedes":
        return
    aliases_by_concept: dict[str, set[str]] = {}
    for item in evidence_items:
        concept = str(item.get("concept_id") or "")
        if concept:
            aliases_by_concept.setdefault(concept, set()).add(_normalized_graph_endpoint(concept))
            passage = str(item.get("passage_text", ""))
            for match in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z0-9][A-Za-z0-9]*)*\s+Part\s+\d+\b", passage):
                aliases_by_concept.setdefault(concept, set()).add(
                    _normalized_graph_endpoint(match)
                )
    source_aliases = aliases_by_concept.get(str(edge.get("edge_source")), set())
    target_aliases = aliases_by_concept.get(str(edge.get("edge_target")), set())
    surface_normalized = _normalized_graph_endpoint(surface)
    for target in target_aliases:
        for source in source_aliases:
            if not target or not source:
                continue
            reversed_pattern = (
                rf"\b{re.escape(target)}\b.{{0,80}}\bprecedes?\b.{{0,80}}\b"
                rf"{re.escape(source)}\b"
            )
            if re.search(reversed_pattern, surface_normalized):
                raise _verification_failure(
                    "M26-PA7-ME-057",
                    "claim surface reverses graph edge direction",
                )


def _normalized_graph_endpoint(text: str) -> str:
    normalized = str(text).casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _verify_model_explanation_surface(*, surface_text: str, answer_text: str) -> None:
    visible_text = re.sub(r"\s+", " ", f"{answer_text} {surface_text}").strip()
    if _secret_like(visible_text):
        raise _verification_failure(
            "M26-PA7-ME-040",
            "model explanation contains secret-like text",
        )
    visible_casefold = visible_text.casefold()
    if any(pattern.search(visible_text) for pattern in MODEL_EXPLANATION_ATTRIBUTION_PATTERNS):
        raise _verification_failure(
            "M26-PA7-ME-050",
            "model explanation falsely attributes a source claim",
        )
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", visible_text))
    if numbers:
        raise _verification_failure(
            "M26-PA7-ME-033",
            "model explanation introduces unsupported number",
        )
    if not any(term in visible_casefold for term in MODEL_EXPLANATION_GENERIC_TERMS):
        raise _verification_failure(
            "M26-PA7-ME-051",
            "model explanation is not generic enough",
        )


def _is_model_explanation_claim(claim_type: str, claim_role: str) -> bool:
    return claim_type == "MODEL_EXPLANATION" or claim_role == "model_explanation"


def _verify_answer_material_anchors(
    *,
    answer_text: str,
    claims: Sequence[Mapping[str, Any]],
) -> None:
    answer = str(answer_text or "").strip()
    if not answer:
        return
    claim_ids = {str(claim.get("claim_id", "")) for claim in claims}
    v2_anchors = set(CLAIM_ANCHOR_RE.findall(answer))
    if v2_anchors and not v2_anchors.issubset(claim_ids):
        raise _verification_failure(
            "M26-PA7-ME-037", "answer text references unknown claim anchor"
        )
    return


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
        edge = graph_edges[0]
        if not (
            str(edge.get("edge_source", ""))
            and str(edge.get("edge_target", ""))
            and str(edge.get("relation_type", ""))
        ):
            raise _verification_failure("M26-PA7-ME-025", "graph intent missing complete graph edge fact")
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
    return intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
    } and claim_role in {"relationship", "comparison"}


def _claim_type_for_role(claim_role: str) -> str:
    if claim_role in {"relationship", "comparison", "temporal"}:
        return "EVIDENCE_SYNTHESIS"
    if claim_role == "model_explanation":
        return "MODEL_EXPLANATION"
    return "EVIDENCE_FACT"


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
    provider_status = str(verified.get("provider_status", ""))
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
                "claim_type": str(claim.get("claim_type", "EVIDENCE_FACT")),
                "surface_text": str(claim.get("surface_text", "")),
                "facet_ids": list(claim.get("facet_ids", [])),
                "support_mode": str(claim.get("support_mode", "exact_quote")),
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
    fallback_answer = _render_answer(intent_class, str(verified.get("relation")), claim_texts)
    natural_answer_fallback_used = False
    try:
        answer_text = _verified_natural_answer_text(
            verified.get("answer_text"),
            citations=citations,
            material_claims=verified.get("material_claims", []),
            fallback=fallback_answer,
            semantic_review_verified=bool(verified.get("semantic_review_verified")),
        )
    except VerifiedAnswerGateError as exc:
        if exc.code not in {
            "M26-PA7-ME-041",
            "M26-PA7-ME-042",
            "M26-PA7-ME-043",
            "M26-PA7-ME-044",
        }:
            raise
        answer_text = fallback_answer
        natural_answer_fallback_used = True
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
            "used_evidence_ids": list(verified.get("used_evidence_ids", [])),
            "required_facets": list(verified.get("required_facets", [])),
            "covered_facets": list(verified.get("covered_facets", [])),
            "missing_facets": list(verified.get("missing_facets", [])),
        },
        "multi_evidence_verification": {
            "claim_count": len(public_claims),
            "support_ref_count": sum(item["support_ref_count"] for item in public_claims),
            "distinct_source_count": len(
                {source for item in public_claims for source in item["source_identities"]}
            ),
            "provider_status": provider_status,
            "natural_answer_fallback_used": natural_answer_fallback_used,
            "locator_validity": 1.0,
            "support_precision": 1.0,
            "unsupported_accepted_claims": 0,
            "single_primary_passage_used": False,
            "bounded_repair_attempted": repair_attempted,
            "required_facets": list(verified.get("required_facets", [])),
            "covered_facets": list(verified.get("covered_facets", [])),
            "missing_facets": list(verified.get("missing_facets", [])),
            "provider_parse": dict(verified.get("provider_parse", {}))
            if isinstance(verified.get("provider_parse"), Mapping)
            else {},
            "provider_attempt_telemetry": _provider_attempt_telemetry(calls),
            "semantic_review": dict(verified.get("semantic_review", {}))
            if isinstance(verified.get("semantic_review"), Mapping)
            else {},
            "dropped_claim_count": 0,
        },
        "safe_abstention": False,
        "reason_codes": [],
        "provider_call_count": len(calls),
        "payg_equivalent_cost_usd": _calls_cost(calls),
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "unsupported_accepted_claims": 0,
        "repair_attempted": repair_attempted,
        "answer_source": "safe_abstention",
    }


def _verified_natural_answer_text(
    raw_answer: Any,
    *,
    citations: Sequence[Mapping[str, Any]],
    material_claims: Sequence[Mapping[str, Any]],
    fallback: str,
    semantic_review_verified: bool = False,
) -> str:
    answer = str(raw_answer or "").strip()
    if not answer:
        return fallback
    if _secret_like(answer):
        raise _verification_failure("M26-PA7-ME-040", "natural answer contains secret-like text")
    citations_by_claim: dict[str, list[str]] = {}
    for citation in citations:
        citations_by_claim.setdefault(str(citation.get("claim_id", "")), []).append(
            f"[{citation.get('citation_id')}]"
        )
    claim_ids = {str(claim.get("claim_id", "")) for claim in material_claims}
    anchors = set(CLAIM_ANCHOR_RE.findall(answer))
    if anchors:
        if not anchors.issubset(claim_ids):
            raise _verification_failure(
                "M26-PA7-ME-041", "natural answer references unknown claim"
            )
        for claim_id in sorted(anchors, key=len, reverse=True):
            if claim_id not in citations_by_claim:
                raise _verification_failure(
                    "M26-PA7-ME-043", "natural answer citation marker mismatch"
                )
            answer = answer.replace(f"[[{claim_id}]]", "".join(citations_by_claim[claim_id]))
    elif LEGACY_CITATION_RE.search(answer):
        citation_ids = {str(item.get("citation_id", "")) for item in citations}
        markers = set(LEGACY_CITATION_RE.findall(answer))
        if not markers or not markers.issubset(citation_ids):
            raise _verification_failure(
                "M26-PA7-ME-043", "natural answer citation marker mismatch"
            )
    if not semantic_review_verified:
        _verify_visible_answer_claim_alignment(answer, claims=material_claims)
    return answer


def _verify_visible_answer_claim_alignment(
    answer_text: str,
    claims: Sequence[Mapping[str, Any]],
) -> None:
    claim_by_id = {str(claim.get("claim_id", "")): claim for claim in claims}
    all_claim_terms: set[str] = set()
    all_claim_numbers: set[str] = set()
    for claim in claims:
        all_claim_terms |= _coverage_terms(str(claim.get("surface_text", "")))
        for ref in _list(claim.get("support_refs", []), "claim support refs"):
            all_claim_terms |= _meaningful_terms(str(ref.get("exact_quote", "")))
            all_claim_numbers |= set(
                re.findall(r"\b\d+(?:\.\d+)?\b", str(ref.get("exact_quote", "")))
            )
    material_sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", str(answer_text))
        if item.strip() and not item.strip().startswith("Note:")
    ]
    for sentence in material_sentences:
        anchors = set(CLAIM_ANCHOR_RE.findall(sentence))
        citation_markers = set(LEGACY_CITATION_RE.findall(sentence))
        sentence_visible = CLAIM_ANCHOR_RE.sub("", sentence)
        sentence_visible = LEGACY_CITATION_RE.sub("", sentence_visible)
        sentence_visible = re.sub(r"\s+", " ", sentence_visible).strip()
        sentence_terms = _meaningful_terms(sentence_visible)
        sentence_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", sentence_visible))
        if not sentence_terms and (anchors or citation_markers):
            continue
        if sentence_terms <= {"no", "yes"} and len(sentence_visible) <= 8:
            continue
        if anchors or citation_markers:
            claim_terms: set[str] = set()
            claim_numbers: set[str] = set()
            claim_support_parts: list[str] = []
            cited_claim_ids = set(anchors)
            cited_claim_ids |= {
                marker.rsplit("_ref_", 1)[0]
                for marker in citation_markers
                if "_ref_" in marker
            }
            for claim_id in cited_claim_ids:
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    raise _verification_failure(
                        "M26-PA7-ME-043", "natural answer citation marker mismatch"
                    )
                claim_terms |= _coverage_terms(str(claim.get("surface_text", "")))
                claim_support_parts.append(str(claim.get("surface_text", "")))
                for ref in _list(claim.get("support_refs", []), "claim support refs"):
                    claim_support_parts.append(str(ref.get("exact_quote", "")))
                    claim_terms |= _meaningful_terms(str(ref.get("exact_quote", "")))
                    claim_numbers |= set(
                        re.findall(r"\b\d+(?:\.\d+)?\b", str(ref.get("exact_quote", "")))
                    )
        else:
            claim_terms = all_claim_terms
            claim_numbers = all_claim_numbers
            claim_support_parts = [
                str(claim.get("surface_text", ""))
                for claim in claims
            ]
            for claim in claims:
                claim_support_parts.extend(
                    str(ref.get("exact_quote", ""))
                    for ref in _list(claim.get("support_refs", []), "claim support refs")
                )
        if not sentence_terms or len(sentence_terms & claim_terms) < 1:
            raise _verification_failure(
                "M26-PA7-ME-045", "visible answer sentence is not proposition-bound to claim"
            )
        unsupported_numbers = sentence_numbers - claim_numbers - set(
            re.findall(
                r"\b\d+(?:\.\d+)?\b",
                " ".join(str(claim.get("surface_text", "")) for claim in claim_by_id.values()),
            )
        )
        if unsupported_numbers:
            raise _verification_failure(
                "M26-PA7-ME-033", "visible answer introduces unsupported number"
            )
        if sentence_terms & MODALITY_STRENGTHENING_TERMS and not (
            sentence_terms & MODALITY_STRENGTHENING_TERMS
        ).issubset(claim_terms):
            raise _verification_failure(
                "M26-PA7-ME-046",
                "visible answer strengthens modality beyond claim/support",
            )
        _verify_hard_truth_boundary_mutations(
            surface_text=sentence_visible,
            support_text=" ".join(claim_support_parts),
        )


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
            "deterministic_evidence_synthesis_used": False,
            "provider_attempt_telemetry": _provider_attempt_telemetry(calls),
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


def _evidence_utilization_trace(response: Mapping[str, Any]) -> dict[str, Any]:
    selected = _list(response.get("selected_evidence", []), "selected evidence")
    citations = _list(response.get("citations", []), "citations")
    selected_ids = [str(item.get("evidence_id", "")) for item in selected]
    used_ids = sorted(
        {str(item.get("evidence_id", "")) for item in citations if str(item.get("evidence_id", ""))}
    )
    selected_set = set(selected_ids)
    used_set = set(used_ids)
    selected_count = len(selected_ids)
    used_fraction = len(used_set) / selected_count if selected_count else 0.0
    return {
        "selected_evidence_count": selected_count,
        "used_evidence_count": len(used_set),
        "selected_evidence_used_fraction": round(used_fraction, 6),
        "selected_gt_zero_used_zero_failure": selected_count > 0 and not used_set,
        "unused_selected_evidence_count": len(selected_set - used_set),
        "used_evidence_ids": used_ids,
        "unused_selected_evidence_ids": sorted(selected_set - used_set),
        "used_evidence_type_counts": dict(
            sorted(
                Counter(
                    str(item.get("evidence_type", "passage"))
                    for item in citations
                    if str(item.get("evidence_id", "")) in used_set
                ).items()
            )
        ),
        "used_source_identities": sorted(
            {
                str(item.get("source_identity") or item.get("source_id") or "")
                for item in citations
                if item.get("source_identity") or item.get("source_id")
            }
        ),
    }


def _normalize_provider_result(result: Mapping[str, Any]) -> dict[str, Any]:
    provider_text = str(result.get("provider_text", result.get("text", "")))
    usage = result.get("usage", {})
    if not isinstance(usage, Mapping):
        usage = {}
    parse_telemetry = _provider_text_parse_telemetry(provider_text)
    return {
        "provider_text": provider_text,
        "provider_text_char_count": len(provider_text),
        "call_class": str(result.get("call_class", "")),
        "stop_reason": str(result.get("stop_reason") or result.get("finish_reason") or ""),
        "content_block_types": [
            str(item)
            for item in result.get("content_block_types", [])
            if isinstance(item, (str, int))
        ],
        "parse_telemetry": parse_telemetry,
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


def _provider_text_parse_telemetry(provider_text: str) -> dict[str, Any]:
    if _secret_like(provider_text):
        return {"parse_ok": False, "parse_error_code": "M26-PA7-ME-007"}
    try:
        _, meta = _parse_multi_provider_json(provider_text)
    except VerifiedAnswerGateError as exc:
        return {
            "parse_ok": False,
            "parse_error_code": exc.code,
            "parse_error_message": exc.safe_message[:160],
        }
    return {"parse_ok": True, **meta}


def _provider_attempt_telemetry(calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "attempt": index,
            "call_class": str(call.get("call_class", "")),
            "stop_reason": str(call.get("stop_reason", "")),
            "truncation_detected": bool(
                call.get("truncation_detected")
                or str(call.get("stop_reason", "")) == "max_tokens"
            ),
            "content_block_types": list(call.get("content_block_types", [])),
            "provider_text_char_count": int(call.get("provider_text_char_count", 0)),
            "output_tokens": int(
                (call.get("usage") if isinstance(call.get("usage"), Mapping) else {}).get(
                    "output_tokens", 0
                )
            ),
            "parse_telemetry": dict(call.get("parse_telemetry", {}))
            if isinstance(call.get("parse_telemetry"), Mapping)
            else {},
        }
        for index, call in enumerate(calls, start=1)
    ]


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
    bundle: ProductionAnswerBundle,
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
        question=question,
    )


def _build_candidate_pool(
    *,
    bundle: ProductionAnswerBundle,
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
    for candidate in candidates.values():
        document = documents.get(str(candidate.get("section_id", "")), {})
        signal = _query_context_signal(
            question=question,
            text=_candidate_context_text(candidate, document),
        )
        candidate.update(signal)
        candidate["source_key"] = str(document.get("source_id") or candidate["section_id"])
        candidate["concept_key"] = str(document.get("concept_id") or candidate["source_key"])
        candidate["score"] += float(signal.get("query_context_score", 0.0)) * 0.75
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
        "graph_relevance_scores": [],
    }


def _add_graph_expanded_candidates(
    *,
    bundle: ProductionAnswerBundle,
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
    order_query = bool(query_terms & ORDER_QUERY_TERMS)
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
        order_query=order_query,
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
            order_query=order_query,
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
    order_query: bool,
    hop: int,
) -> None:
    channel = f"graph_{hop}hop"
    for seed_concept, seed_score in frontier:
        ranked_edges = sorted(
            relation_index.get(seed_concept, []),
            key=lambda edge: (
                -_edge_navigation_score(
                    edge=edge,
                    seed_concept=seed_concept,
                    doc_by_concept=doc_by_concept,
                    query_terms=query_terms,
                    order_query=order_query,
                )
            ),
        )
        for edge in ranked_edges[:6]:
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
            relation_weight = _relation_navigation_weight(
                str(edge.get("relation_type", "")),
                order_query=order_query,
                relevance=relevance,
            )
            if relation_weight < 0 and relevance <= 0:
                continue
            graph_score = seed_score * hop_weight + confidence * 0.25 + relevance * 2.0
            graph_score += relation_weight
            if hop == 2 and relevance < 0.15:
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
            candidate["graph_relevance_scores"].append(round(relevance, 6))
            candidate.setdefault("graph_seed_concepts", set()).add(seed_concept)


def _edge_navigation_score(
    *,
    edge: Mapping[str, Any],
    seed_concept: str,
    doc_by_concept: Mapping[str, Mapping[str, Any]],
    query_terms: set[str],
    order_query: bool,
) -> float:
    source = str(edge.get("source", ""))
    target = str(edge.get("target", ""))
    neighbour = target if source == seed_concept else source
    document = doc_by_concept.get(neighbour, {})
    relevance = _text_term_overlap_score(query_terms, _document_text(document))
    confidence = float(edge.get("confidence", 0.0) or 0.0)
    return (
        relevance * 3.0
        + confidence * 0.25
        + _relation_navigation_weight(
            str(edge.get("relation_type", "")),
            order_query=order_query,
            relevance=relevance,
        )
    )


def _relation_navigation_weight(
    relation_type: str,
    *,
    order_query: bool,
    relevance: float,
) -> float:
    if relation_type == "precedes":
        return 0.45 if order_query else -0.6
    if relation_type in {"contains", "part_of"}:
        return 0.25 if relevance > 0 else -0.05
    if relation_type:
        return 0.5
    return 0.0


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
        item["rerank_score"] = (
            float(item.get("score", 0.0))
            + channel_count * 0.35
            + graph_bonus
            + float(item.get("query_context_score", 0.0))
            - _candidate_structural_relation_penalty(item)
            - _candidate_weak_query_context_penalty(item)
        )
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
    query_term_count = max(
        (int(candidate.get("query_context_term_count") or 0) for candidate in candidates),
        default=0,
    )
    has_context_rich_candidate = any(
        int(candidate.get("query_context_coverage_count") or 0) >= 2
        or int(candidate.get("query_context_phrase_match_count") or 0) > 0
        for candidate in candidates
    )
    for candidate in candidates:
        section_id = str(candidate["section_id"])
        if (
            query_term_count >= 3
            and has_context_rich_candidate
            and int(candidate.get("graph_hop") or 0) > 0
            and int(candidate.get("query_context_coverage_count") or 0) <= 1
            and int(candidate.get("query_context_phrase_match_count") or 0) == 0
        ):
            continue
        source_key = str(candidate.get("source_key") or section_id.split("#", 1)[0])
        concept_key = str(candidate.get("concept_key") or source_key)
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
        "graph_relevance_scores": list(candidate.get("graph_relevance_scores", []))[:4],
        "structural_relation_only": _candidate_structural_relation_penalty(candidate) > 0,
        "query_context_terms": list(candidate.get("query_context_terms", []))[:12],
        "query_context_coverage_terms": list(
            candidate.get("query_context_coverage_terms", [])
        )[:12],
        "query_context_coverage_count": int(candidate.get("query_context_coverage_count") or 0),
        "query_context_coverage_ratio": round(
            float(candidate.get("query_context_coverage_ratio") or 0.0),
            6,
        ),
        "query_context_phrase_matches": list(
            candidate.get("query_context_phrase_matches", [])
        )[:8],
        "query_context_score": round(float(candidate.get("query_context_score") or 0.0), 6),
    }


def _candidate_structural_relation_penalty(candidate: Mapping[str, Any]) -> float:
    relation_types = {str(item) for item in candidate.get("relation_types", set()) if str(item)}
    if not relation_types or not relation_types.issubset(STRUCTURAL_RELATION_TYPES):
        return 0.0
    relevance_scores = [
        float(score)
        for score in candidate.get("graph_relevance_scores", [])
        if isinstance(score, (int, float))
    ]
    if max(relevance_scores or [0.0]) >= 0.25:
        return 0.0
    if relation_types == {"precedes"}:
        return 0.45
    return 0.15


def _candidate_weak_query_context_penalty(candidate: Mapping[str, Any]) -> float:
    query_term_count = int(candidate.get("query_context_term_count") or 0)
    coverage_count = int(candidate.get("query_context_coverage_count") or 0)
    phrase_count = int(candidate.get("query_context_phrase_match_count") or 0)
    graph_hop = int(candidate.get("graph_hop") or 0)
    if query_term_count < 3:
        return 0.0
    if coverage_count <= 0:
        return 3.0
    if graph_hop > 0 and coverage_count <= 1 and phrase_count <= 0:
        return 2.5
    if query_term_count >= 4 and coverage_count == 1 and phrase_count <= 0:
        return 1.0
    return 0.0


def _augment_evidence_for_intent(
    *,
    bundle: ProductionAnswerBundle,
    base_evidence: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Any],
    trace_id: str,
    intent_class: str,
    budget: int,
    question: str,
) -> list[dict[str, Any]]:
    evidence = [dict(item) for item in base_evidence]
    if intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
        "temporal_conflict",
        "direct_grounded_knowledge",
    }:
        evidence = _ensure_query_coverage_passages(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            question=question,
            limit=budget,
        )
    if intent_class == "direct_grounded_knowledge":
        evidence = _ensure_required_facet_coverage_passages(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            question=question,
            intent_class=intent_class,
            limit=budget,
        )
    if intent_class in {
        "cross_document_comparison",
        "complementary_synthesis",
        "temporal_conflict",
    }:
        evidence = _ensure_distinct_passage_sources(
            bundle=bundle,
            evidence=evidence,
            trace_id=trace_id,
            question=question,
            minimum=2,
            limit=budget,
        )
    if intent_class == "graph_relationship":
        evidence = _graph_evidence_bundle(
            bundle=bundle,
            evidence=evidence,
            lexical_results=lexical_results,
            trace_id=trace_id,
            question=question,
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
    bundle: ProductionAnswerBundle,
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
    locator_id = (
        "m26pa7loc_"
        + canonical_sha256(
            {
                "trace_id": trace_id,
                "section_id": section_id,
                "passage_sha256": passage_sha,
            }
        )[:32]
    )
    evidence_id = (
        "m26pa7ev_"
        + canonical_sha256(
            {
                "trace_id": trace_id,
                "ordinal": ordinal,
                "locator_id": locator_id,
                "channels": list(channels),
            }
        )[:32]
    )
    citation = _first_citation(lexical_result, document)
    record = _provenance_record_for_document(bundle, document)
    source_identity = _citation_source_identity(citation, section_id)
    return {
        "evidence_id": evidence_id,
        "evidence_type": "passage",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": bundle.artifact_keys["lexical_index"],
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
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    question: str,
    minimum: int,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    selected_sections = {str(item.get("section_id", "")) for item in selected}
    source_identities = {_source_identity(item) for item in selected}
    if len(source_identities) >= minimum:
        return selected
    ordinal = len(selected) + 1
    query_terms = _meaningful_terms(question)
    documents = sorted(
        _release_documents(bundle),
        key=lambda document: (
            -_text_term_overlap_score(query_terms, _document_text(document)),
            _is_article_root_document(document),
            str(document.get("section_id", "")),
        ),
    )
    for document in documents:
        section_id = str(document.get("section_id", ""))
        if section_id in selected_sections:
            continue
        item = _evidence_item(
            bundle=bundle,
            document=document,
            lexical_result={},
            trace_id=trace_id,
            ordinal=ordinal,
            channels=["release_distinct_source", "query_coverage"],
            retrieval_metadata={
                "query_overlap_score": _text_term_overlap_score(
                    query_terms,
                    _document_text(document),
                ),
                "coverage_terms": sorted(query_terms & _meaningful_terms(_document_text(document))),
            },
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


def _ensure_required_facet_coverage_passages(
    *,
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    question: str,
    intent_class: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    selected_sections = {str(item.get("section_id", "")) for item in selected}
    prepend: list[dict[str, Any]] = []
    prepend_sections: set[str] = set()
    ordinal = len(selected) + 1
    for facet in _question_contract(question=question, intent_class=intent_class)[
        "required_facets"
    ]:
        if str(facet.get("facet_id", "")) == "direct_answer":
            continue
        facet_terms = _facet_terms(facet)
        if not facet_terms:
            continue
        existing_matches = [
            (index, item)
            for index, item in enumerate(selected)
            if item.get("evidence_type") == "passage"
            and str(item.get("section_id", "")) not in prepend_sections
            and _direct_facet_text_matches(facet, str(item.get("passage_text", "")))
        ]
        existing = None
        if existing_matches:
            existing = sorted(
                existing_matches,
                key=lambda indexed_item: (
                    -_query_context_signal(
                        question=question,
                        text=_evidence_context_text(indexed_item[1]),
                    )["query_context_score"],
                    indexed_item[0],
                ),
            )[0][1]
        if existing is not None:
            prepend.append(dict(existing))
            prepend_sections.add(str(existing.get("section_id", "")))
            continue
        documents = sorted(
            _release_documents(bundle),
            key=lambda document: (
                -_direct_facet_match_score(facet, _document_text(document)),
                -_text_term_overlap_score(facet_terms, _document_text(document)),
                _is_article_root_document(document),
                -_passage_text_quality(str(document.get("body") or document.get("excerpt") or "")),
                str(document.get("section_id", "")),
            ),
        )
        document = next(
            (
                item
                for item in documents
                if str(item.get("section_id", "")) not in selected_sections
                and _direct_facet_text_matches(facet, _document_text(item))
            ),
            None,
        )
        if document is None:
            continue
        item = _evidence_item(
            bundle=bundle,
            document=document,
            lexical_result={},
            trace_id=trace_id,
            ordinal=ordinal,
            channels=["required_facet_coverage", "query_coverage"],
            retrieval_metadata={
                "required_facet_id": str(facet.get("facet_id", "")),
                "required_facet_terms": sorted(facet_terms),
                "covered_facet_terms": sorted(_direct_facet_covered_markers(facet, _document_text(document))),
            },
        )
        prepend.append(item)
        prepend_sections.add(str(document.get("section_id", "")))
        selected_sections.add(str(document.get("section_id", "")))
        ordinal += 1
    return [
        *prepend,
        *[
            item
            for item in selected
            if str(item.get("section_id", "")) not in prepend_sections
        ],
    ]


def _facet_terms(facet: Mapping[str, Any]) -> set[str]:
    terms: set[str] = set()
    raw_terms = facet.get("terms", [])
    if not isinstance(raw_terms, Sequence) or isinstance(raw_terms, (str, bytes)):
        raw_terms = []
    for term in raw_terms:
        terms |= _meaningful_terms(str(term))
    return terms


def _direct_facet_required_phrases(facet_id: str) -> tuple[str, ...]:
    return DIRECT_FACET_EXACT_PHRASES.get(str(facet_id), ())


def _direct_facet_required_quote_groups(facet_id: str) -> tuple[tuple[str, ...], ...]:
    return DIRECT_FACET_REQUIRED_QUOTE_TERM_GROUPS.get(str(facet_id), ())


def _direct_facet_phrase_score(facet_id: str, text: str) -> int:
    text_casefold = str(text).casefold()
    return sum(
        1
        for phrase in _direct_facet_required_phrases(facet_id)
        if phrase in text_casefold
    )


def _direct_facet_match_score(facet: Mapping[str, Any], text: str) -> int:
    facet_id = str(facet.get("facet_id", ""))
    phrase_score = _direct_facet_phrase_score(facet_id, text)
    if _direct_facet_required_phrases(facet_id):
        return phrase_score
    quote_groups = _direct_facet_required_quote_groups(facet_id)
    if quote_groups:
        return sum(
            1
            for group in quote_groups
            if any(term in str(text).casefold() for term in group)
        )
    return len(_facet_terms(facet) & _meaningful_terms(str(text)))


def _direct_facet_text_matches(facet: Mapping[str, Any], text: str) -> bool:
    groups = _direct_facet_required_quote_groups(str(facet.get("facet_id", "")))
    if groups:
        text_casefold = str(text).casefold()
        return all(any(term in text_casefold for term in group) for group in groups)
    return _direct_facet_match_score(facet, text) >= 1


def _direct_facet_covered_markers(
    facet: Mapping[str, Any],
    text: str,
) -> set[str]:
    facet_id = str(facet.get("facet_id", ""))
    phrases = {
        phrase
        for phrase in _direct_facet_required_phrases(facet_id)
        if phrase in str(text).casefold()
    }
    if phrases:
        return phrases
    groups = _direct_facet_required_quote_groups(facet_id)
    if groups:
        text_casefold = str(text).casefold()
        return {
            term
            for group in groups
            for term in group
            if term in text_casefold
        }
    return _facet_terms(facet) & _meaningful_terms(str(text))


def _ensure_query_coverage_passages(
    *,
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    question: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    selected_sections = {str(item.get("section_id", "")) for item in selected}
    query_terms = _query_context_terms(question)
    if not query_terms:
        return selected
    covered_terms: set[str] = set()
    for item in selected:
        evidence_text = " ".join(
            str(item.get(key, ""))
            for key in (
                "title",
                "section_title",
                "passage_text",
                "concept_id",
                "section_id",
                "source_id",
                "source_identity",
            )
        )
        covered_terms |= query_terms & _meaningful_terms(evidence_text)
    if query_terms.issubset(covered_terms):
        return selected
    ordinal = len(selected) + 1
    coverage_items: list[dict[str, Any]] = []
    documents = sorted(
        _release_documents(bundle),
        key=lambda document: (
            -int(
                bool(
                    _query_context_signal(question=question, text=_document_context_text(document))[
                        "query_context_phrase_match_count"
                    ]
                )
            ),
            -len((query_terms - covered_terms) & _meaningful_terms(_document_context_text(document))),
            -_query_context_signal(question=question, text=_document_context_text(document))[
                "query_context_score"
            ],
            _is_article_root_document(document),
            str(document.get("section_id", "")),
        ),
    )
    for document in documents:
        if len(coverage_items) >= max(2, min(4, limit // 2)):
            break
        section_id = str(document.get("section_id", ""))
        if section_id in selected_sections:
            continue
        document_text = _document_context_text(document)
        signal = _query_context_signal(question=question, text=document_text)
        document_terms = _meaningful_terms(document_text)
        gained = (query_terms - covered_terms) & document_terms
        if not gained:
            continue
        if (
            len(query_terms) >= 3
            and int(signal.get("query_context_coverage_count") or 0) <= 1
            and int(signal.get("query_context_phrase_match_count") or 0) == 0
        ):
            continue
        item = _evidence_item(
            bundle=bundle,
            document=document,
            lexical_result={},
            trace_id=trace_id,
            ordinal=ordinal,
            channels=["query_coverage"],
            retrieval_metadata={
                "query_overlap_score": signal["query_context_coverage_ratio"],
                "coverage_terms": sorted(gained),
                "query_context_terms": signal["query_context_terms"],
                "query_context_coverage_terms": signal["query_context_coverage_terms"],
                "query_context_phrase_matches": signal["query_context_phrase_matches"],
                "query_context_score": signal["query_context_score"],
            },
        )
        coverage_items.append(item)
        selected_sections.add(section_id)
        covered_terms |= gained
        ordinal += 1
        if query_terms.issubset(covered_terms):
            break
    if not coverage_items:
        return selected
    first_selected_metadata = (
        selected[0].get("retrieval_metadata", {}) if selected and isinstance(selected[0], Mapping) else {}
    )
    first_selected_context_ratio = 0.0
    first_selected_context_score = 0.0
    if isinstance(first_selected_metadata, Mapping):
        try:
            first_selected_context_ratio = float(
                first_selected_metadata.get("query_context_coverage_ratio", 0.0)
            )
        except (TypeError, ValueError):
            first_selected_context_ratio = 0.0
        try:
            first_selected_context_score = float(
                first_selected_metadata.get("query_context_score", 0.0)
            )
        except (TypeError, ValueError):
            first_selected_context_score = 0.0
    first_supplement_metadata = coverage_items[0].get("retrieval_metadata", {})
    first_supplement_context_score = 0.0
    if isinstance(first_supplement_metadata, Mapping):
        try:
            first_supplement_context_score = float(
                first_supplement_metadata.get("query_context_score", 0.0)
            )
        except (TypeError, ValueError):
            first_supplement_context_score = 0.0
    if (
        first_selected_context_ratio < 0.5
        and first_supplement_context_score > first_selected_context_score
    ):
        return [coverage_items[0], *selected, *coverage_items[1:]]
    return [*selected, *coverage_items]


def _graph_evidence_bundle(
    *,
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Any],
    trace_id: str,
    question: str,
    limit: int,
) -> list[dict[str, Any]]:
    passages = [dict(item) for item in evidence if item.get("evidence_type") == "passage"]
    edge = _first_authoritative_edge(
        passages,
        lexical_results,
        bundle,
        question=question,
    )
    if edge is None:
        return passages
    endpoint_passages = _endpoint_passages(
        bundle=bundle,
        existing=passages,
        edge=edge,
        trace_id=trace_id,
        question=question,
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
    bundle: ProductionAnswerBundle,
    *,
    question: str,
) -> Mapping[str, Any] | None:
    query_terms = _meaningful_terms(question)
    order_query = bool(query_terms & ORDER_QUERY_TERMS)
    candidates: list[Mapping[str, Any]] = []
    for item in passages:
        for edge in item.get("relation_expansions", []):
            if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
                candidates.append(edge)
    for result in lexical_results:
        if not isinstance(result, Mapping):
            continue
        for edge in result.get("relation_expansions", []):
            if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
                candidates.append(edge)
    for edge in bundle.graph_v2.get("edges", []):
        if isinstance(edge, Mapping) and _edge_has_endpoint_documents(edge, bundle):
            candidates.append(edge)
    if not candidates:
        return None
    docs = _documents_by_concept(bundle)
    return max(
        candidates,
        key=lambda edge: _edge_endpoint_relevance_score(
            edge=edge,
            docs_by_concept=docs,
            query_terms=query_terms,
            order_query=order_query,
        ),
    )


def _edge_endpoint_relevance_score(
    *,
    edge: Mapping[str, Any],
    docs_by_concept: Mapping[str, Sequence[Mapping[str, Any]]],
    query_terms: set[str],
    order_query: bool,
) -> float:
    source_docs = docs_by_concept.get(str(edge.get("source", "")), [])
    target_docs = docs_by_concept.get(str(edge.get("target", "")), [])
    source_docs = sorted(
        source_docs,
        key=lambda document: (
            -_text_term_overlap_score(query_terms, _document_text(document)),
            _is_article_root_document(document),
        ),
    )
    target_docs = sorted(
        target_docs,
        key=lambda document: (
            -_text_term_overlap_score(query_terms, _document_text(document)),
            _is_article_root_document(document),
        ),
    )
    endpoint_text = " ".join(
        _document_text(document) for document in [*source_docs[:4], *target_docs[:4]]
    )
    relevance = _text_term_overlap_score(query_terms, endpoint_text)
    coverage = len(query_terms & _meaningful_terms(endpoint_text))
    return (
        relevance * 5.0
        + coverage * 0.2
        + _relation_navigation_weight(
            str(edge.get("relation_type", "")),
            order_query=order_query,
            relevance=relevance,
        )
    )


def _edge_has_endpoint_documents(edge: Mapping[str, Any], bundle: ProductionAnswerBundle) -> bool:
    concepts = _release_concepts(bundle)
    return str(edge.get("source", "")) in concepts and str(edge.get("target", "")) in concepts


def _endpoint_passages(
    *,
    bundle: ProductionAnswerBundle,
    existing: Sequence[Mapping[str, Any]],
    edge: Mapping[str, Any],
    trace_id: str,
    question: str,
    start_ordinal: int,
) -> list[dict[str, Any]]:
    by_concept = _documents_by_concept(bundle)
    query_terms = _meaningful_terms(question)
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
        documents = sorted(
            by_concept.get(concept_id, []),
            key=lambda document: (
                -_text_term_overlap_score(query_terms, _document_text(document)),
                _is_article_root_document(document),
                -_passage_text_quality(str(document.get("body") or document.get("excerpt") or "")),
                str(document.get("section_id", "")),
            ),
        )
        if not documents:
            continue
        endpoint_items.append(
            _evidence_item(
                bundle=bundle,
                document=documents[0],
                lexical_result={},
                trace_id=trace_id,
                ordinal=ordinal,
                channels=["graph_endpoint", "query_coverage"],
                retrieval_metadata={
                    "query_overlap_score": _text_term_overlap_score(
                        query_terms,
                        _document_text(documents[0]),
                    ),
                    "coverage_terms": sorted(
                        query_terms & _meaningful_terms(_document_text(documents[0]))
                    ),
                },
            )
        )
        ordinal += 1
    return endpoint_items


def _graph_edge_evidence_item(
    *,
    bundle: ProductionAnswerBundle,
    edge: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
) -> dict[str, Any]:
    edge_id = str(edge.get("edge_id", ""))
    source = str(edge.get("source", ""))
    target = str(edge.get("target", ""))
    relation_type = str(edge.get("relation_type", "related_to"))
    source_label = _graph_endpoint_display_label(bundle, source)
    target_label = _graph_endpoint_display_label(bundle, target)
    statement = (
        f"Production graph navigation edge {edge_id} states "
        f"{source_label} ({source}) {relation_type} {target_label} ({target}) "
        f"with confidence {edge.get('confidence')} and review "
        f"{edge.get('review_status', 'approved')}."
    )
    relation_metadata = _graph_relation_metadata(relation_type)
    text_sha = sha256_bytes(statement.encode("utf-8"))
    locator_id = (
        "m26pa7edge_"
        + canonical_sha256(
            {"trace_id": trace_id, "edge_id": edge_id, "statement_sha256": text_sha}
        )[:32]
    )
    evidence_id = (
        "m26pa7ev_"
        + canonical_sha256({"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id})[
            :32
        ]
    )
    return {
        "evidence_id": evidence_id,
        "evidence_type": "graph_edge",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": bundle.artifact_keys["graph_v2"],
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
        "edge_source_label": source_label,
        "edge_target_label": target_label,
        "relation_type": relation_type,
        "relation_metadata": relation_metadata,
        "provenance_record_sha256": canonical_sha256(str(edge.get("provenance_ref", ""))),
        "retrieved_at": "",
        "retrieval_metadata": {
            "graph_edge_role": "navigation_identity",
            "structural_relation": relation_type in STRUCTURAL_RELATION_TYPES,
            "relation_metadata": relation_metadata,
        },
    }


def _graph_endpoint_display_label(bundle: ProductionAnswerBundle, concept_id: str) -> str:
    concept = str(concept_id)
    for document in _release_documents(bundle):
        if str(document.get("concept_id", "")) != concept:
            continue
        for key in ("title", "section_title", "source_identity", "source_id"):
            value = str(document.get(key, "")).strip()
            if value:
                return value
    return concept


def _provenance_evidence_bundle(
    *,
    bundle: ProductionAnswerBundle,
    evidence: Sequence[Mapping[str, Any]],
    trace_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in evidence]
    for passage in selected:
        if passage.get("evidence_type") != "passage":
            continue
        record = _provenance_record_for_evidence(bundle, passage)
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
    bundle: ProductionAnswerBundle,
    record: Mapping[str, Any],
    passage: Mapping[str, Any],
    trace_id: str,
    ordinal: int,
) -> dict[str, Any]:
    subject = record.get("subject") if isinstance(record.get("subject"), Mapping) else {}
    source_id = str(record.get("source_id") or passage.get("source_id", ""))
    origin = record.get("origin") if isinstance(record.get("origin"), Mapping) else {}
    claims = record.get("claims") if isinstance(record.get("claims"), list) else []
    first_claim = claims[0] if claims and isinstance(claims[0], Mapping) else {}
    claim_id = str(first_claim.get("claim_id") or source_id or "provenance_claim")
    claim_text = str(
        first_claim.get("text")
        or record.get("canonical_url")
        or origin.get("path")
        or "Provenance record is present for this production source."
    )
    statement = (
        f"Provenance record for {subject.get('concept_id', passage.get('concept_id'))} "
        f"contains {claim_id}: {claim_text}"
    )
    text_sha = sha256_bytes(statement.encode("utf-8"))
    locator_id = (
        "m26pa7prov_"
        + canonical_sha256(
            {"trace_id": trace_id, "passage": passage["evidence_id"], "statement_sha256": text_sha}
        )[:32]
    )
    evidence_id = (
        "m26pa7ev_"
        + canonical_sha256({"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id})[
            :32
        ]
    )
    return {
        "evidence_id": evidence_id,
        "evidence_type": "provenance",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": bundle.artifact_keys["provenance"],
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
    bundle: ProductionAnswerBundle,
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
    bundle: ProductionAnswerBundle,
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
    locator_id = (
        "m26pa7time_"
        + canonical_sha256(
            {"trace_id": trace_id, "passage": passage["evidence_id"], "statement_sha256": text_sha}
        )[:32]
    )
    evidence_id = (
        "m26pa7ev_"
        + canonical_sha256({"trace_id": trace_id, "ordinal": ordinal, "locator_id": locator_id})[
            :32
        ]
    )
    return {
        "evidence_id": evidence_id,
        "evidence_type": "temporal_record",
        "locator_id": locator_id,
        "release_id": bundle.release_id,
        "artifact_key": bundle.artifact_keys["provenance"],
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
        "source_id": str(document.get("source_id") or document.get("concept_id", "unknown")),
        "uri": str(
            document.get("canonical_url")
            or document.get("path")
            or document.get("section_id", "unknown")
        ),
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
    summary["evidence_text_role"] = _evidence_text_role(evidence)
    summary["section_granularity"] = _section_granularity(evidence)
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


def _evidence_text_role(evidence: Mapping[str, Any]) -> str:
    evidence_type = str(evidence.get("evidence_type", "passage"))
    if evidence_type != "passage":
        return evidence_type
    text = str(evidence.get("passage_text", ""))
    if _article_title_like(text):
        return "article_title_or_heading"
    if _thin_heading(text):
        return "thin_heading"
    if _is_article_root_evidence(evidence):
        return "article_root_passage"
    return "section_passage"


def _section_granularity(evidence: Mapping[str, Any]) -> str:
    if evidence.get("evidence_type") != "passage":
        return str(evidence.get("evidence_type", "derived_record"))
    return "article_root" if _is_article_root_evidence(evidence) else "section"


def _is_article_root_evidence(evidence: Mapping[str, Any]) -> bool:
    return str(evidence.get("section_id", "")) == str(evidence.get("concept_id", "")) or str(
        evidence.get("section_title", "")
    ).casefold() in {"article overview", "overview"}


def _parent_expansion_summary(
    bundle: ProductionAnswerBundle,
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


def _provenance_records_by_concept(bundle: ProductionAnswerBundle) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for record in bundle.provenance.get("records", []):
        if not isinstance(record, Mapping):
            continue
        subject = record.get("subject")
        if isinstance(subject, Mapping) and isinstance(subject.get("concept_id"), str):
            records[str(subject["concept_id"])] = record
    return records


def _provenance_records_by_source(bundle: ProductionAnswerBundle) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for record in bundle.provenance.get("records", []):
        if not isinstance(record, Mapping):
            continue
        source_id = record.get("source_id")
        if isinstance(source_id, str) and source_id:
            records[source_id] = record
    return records


def _provenance_record_for_document(
    bundle: ProductionAnswerBundle,
    document: Mapping[str, Any],
) -> Mapping[str, Any]:
    concept_record = _provenance_records_by_concept(bundle).get(str(document.get("concept_id", "")))
    if concept_record:
        return concept_record
    return _provenance_records_by_source(bundle).get(str(document.get("source_id", "")), {})


def _provenance_record_for_evidence(
    bundle: ProductionAnswerBundle,
    evidence: Mapping[str, Any],
) -> Mapping[str, Any]:
    concept_record = _provenance_records_by_concept(bundle).get(str(evidence.get("concept_id", "")))
    if concept_record:
        return concept_record
    return _provenance_records_by_source(bundle).get(str(evidence.get("source_id", "")), {})


def _release_documents(bundle: ProductionAnswerBundle) -> list[dict[str, Any]]:
    cache_key = id(bundle)
    cached = _RELEASE_DOCUMENTS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    documents = bundle.lexical_index.get("documents")
    if not isinstance(documents, list):
        raise PA7ArbitraryQueryError("PA7_LEXICAL_INDEX_INVALID", "documents missing")
    loaded = [dict(document) for document in documents if isinstance(document, Mapping)]
    _RELEASE_DOCUMENTS_CACHE[cache_key] = loaded
    return loaded


def _documents_by_concept(
    bundle: ProductionAnswerBundle,
) -> dict[str, list[Mapping[str, Any]]]:
    by_concept: dict[str, list[Mapping[str, Any]]] = {}
    for document in _release_documents(bundle):
        by_concept.setdefault(str(document.get("concept_id", "")), []).append(document)
    return by_concept


def _release_concepts(bundle: ProductionAnswerBundle) -> set[str]:
    cache_key = id(bundle)
    cached = _RELEASE_CONCEPTS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    concepts = {str(document.get("concept_id", "")) for document in _release_documents(bundle)}
    _RELEASE_CONCEPTS_CACHE[cache_key] = concepts
    return concepts


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
    segments = _exact_quote_segments(normalized)
    quote = next(
        (
            segment
            for segment in segments
            if len(segment) >= 48
            and not _thin_heading(segment)
            and not _article_title_like(segment)
        ),
        "",
    )
    if not quote:
        quote = segments[0] if segments else normalized
    if len(quote) <= max_chars:
        return quote
    return quote[:max_chars].rsplit(" ", 1)[0].rstrip()


def _exact_quote_segments(text: str) -> list[str]:
    segments: list[str] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        segment = text[start : match.start()].strip()
        if segment:
            segments.append(segment)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        segments.append(tail)
    return segments


def _thin_heading(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("#") and len(TOKEN_RE.findall(stripped)) <= 4


def _article_title_like(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text).strip()
    if len(stripped) > 320:
        return False
    title_markers = (
        " | ",
        " Series Part ",
        " Theory Part ",
        " Part 0",
        " Part 1",
        " Part 2",
        " Part 3",
        " Part 4",
        " Part 5",
        " Part 6",
        " Part 7",
        " Part 8",
        " Part 9",
    )
    if any(marker in stripped for marker in title_markers):
        return True
    words = TOKEN_RE.findall(stripped)
    prose_verbs = r"\b(is|are|should|can|must|does|do|keeps|records|limits|connects)\b"
    return (
        len(words) <= 16 and stripped[:1].isupper() and not re.search(prose_verbs, stripped, re.I)
    )


def _looks_like_prompt_injection(question: str) -> bool:
    return any(pattern.search(question) for pattern in PROMPT_INJECTION_PATTERNS)


def _looks_like_underspecified_workflow_question(question: str) -> bool:
    lowered = question.casefold().strip()
    if not re.fullmatch(
        r"(?:what|which)\s+should\s+i\s+use\s+for\s+(?:this|that|the)\s+workflow\??",
        lowered,
    ):
        return False
    return len(_meaningful_terms(lowered) - {"should", "use", "workflow"}) <= 1


def _intent_class(question: str) -> str:
    for intent, patterns in INTENT_PATTERNS:
        if any(pattern.search(question) for pattern in patterns):
            if intent == "temporal_conflict" and not _temporal_conflict_question(question):
                continue
            return intent
    return "direct_grounded_knowledge"


def _temporal_conflict_question(question: str) -> bool:
    q = " ".join(str(question).casefold().split())
    explicit_context = any(
        marker in q
        for marker in (
            "source record",
            "source records",
            "source/version",
            "version record",
            "version records",
            "temporal record",
            "temporal records",
            "provenance record",
            "retrieved at",
            "retrieval time",
            "older",
            "newer",
            "first record",
            "second record",
            "timestamp",
            "edited",
            "updated",
            "release",
            "version",
        )
    )
    if not explicit_context:
        return False
    if "what changed" in q or "changed between" in q or "older" in q or "newer" in q:
        return True
    return bool(re.search(r"\b(?:time|temporal|version|record|source|edited|updated)\b", q))


def _secret_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_VALUE_PATTERNS)


def _render_claim_clause(claim: Mapping[str, Any], fragments: Sequence[str]) -> str:
    claim_id = str(claim.get("claim_id", "claim"))
    cited_fragments = [
        f"{fragment} [{claim_id}_ref_{index}]" for index, fragment in enumerate(fragments, start=1)
    ]
    if not cited_fragments:
        return str(claim.get("surface_text", "")).strip()
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
            "parts of the same operating model: " + " In contrast, ".join(compact_claims)
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
        return "The temporal evidence should be read as a source/version comparison: " + " ".join(
            compact_claims
        )
    return " ".join(compact_claims)


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
    overlap = query_terms & evidence_terms
    if _requires_precise_overlap(query_terms):
        return len(overlap) >= 2 and any(
            term in overlap and _looks_like_random_identifier(term) for term in query_terms
        )
    if overlap:
        return True
    return _has_semantic_admission_signal(evidence)


def _has_semantic_admission_signal(evidence: Sequence[Mapping[str, Any]]) -> bool:
    passages = [
        item for item in evidence if str(item.get("evidence_type", "passage")) == "passage"
    ]
    if len(passages) < 2:
        return False
    semantic_channels = {
        "query_coverage",
        "required_facet_coverage",
        "release_distinct_source",
        "semantic_requirement_recovery",
    }
    has_signal = False
    for item in passages:
        channels = {str(channel) for channel in item.get("channels", [])}
        if channels & semantic_channels or any(channel.startswith("graph_") for channel in channels):
            has_signal = True
            break
        metadata = item.get("retrieval_metadata", {})
        if isinstance(metadata, Mapping) and _metadata_has_semantic_admission_signal(
            metadata, dense_channel_present="dense" in channels
        ):
            has_signal = True
            break
    if not has_signal:
        return False
    if len({_source_identity(item) for item in passages}) < 2 and len(passages) < 3:
        return False
    return sum(_passage_text_quality(str(item.get("passage_text", ""))) for item in passages) > 0


def _metadata_has_semantic_admission_signal(
    metadata: Mapping[str, Any], *, dense_channel_present: bool
) -> bool:
    for key in ("semantic_requirement_score", "query_overlap_score", "rerank_score"):
        if key not in metadata:
            continue
        try:
            if float(metadata.get(key, 0.0)) > 0:
                return True
        except (TypeError, ValueError):
            continue
    graph_scores = metadata.get("graph_relevance_scores")
    if isinstance(graph_scores, Sequence) and not isinstance(graph_scores, (str, bytes)):
        for score in graph_scores:
            try:
                if float(score) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    coverage_terms = metadata.get("coverage_terms")
    if (
        isinstance(coverage_terms, Sequence)
        and not isinstance(coverage_terms, (str, bytes))
        and any(str(item).strip() for item in coverage_terms)
    ):
        return True
    return dense_channel_present and "rerank_score" in metadata


def _requires_precise_overlap(query_terms: set[str]) -> bool:
    exactness_terms = {
        "checksum",
        "digest",
        "hash",
        "sha",
        "sha256",
        "token",
        "secret",
    }
    return (
        len(query_terms) >= 6
        and bool(query_terms & exactness_terms)
        and any(_looks_like_random_identifier(term) for term in query_terms)
    )


def _looks_like_random_identifier(term: str) -> bool:
    if len(term) < 4:
        return False
    letters = [char for char in term.casefold() if char.isalpha()]
    if len(letters) < 4:
        return False
    vowel_count = sum(1 for char in letters if char in "aeiou")
    return vowel_count == 0


def _meaningful_terms(text: str) -> set[str]:
    terms = {
        term.casefold()
        for term in TOKEN_RE.findall(text)
        if term.casefold() not in STOP_TERMS and len(term) > 2
    }
    singulars = {
        term[:-1]
        for term in terms
        if len(term) > 4 and term.endswith("s") and not term.endswith("ss")
    }
    return terms | singulars


def _query_context_terms(text: str) -> set[str]:
    terms = _coverage_terms(text) - QUERY_CONTEXT_UTILITY_TERMS
    return terms or _coverage_terms(text)


def _query_context_token_sequence(text: str) -> list[str]:
    terms = _query_context_terms(text)
    sequence: list[str] = []
    for token in TOKEN_RE.findall(text):
        normalized = token.casefold()
        if normalized in terms:
            sequence.append(normalized)
        elif (
            len(normalized) > 4
            and normalized.endswith("s")
            and not normalized.endswith("ss")
            and normalized[:-1] in terms
        ):
            sequence.append(normalized[:-1])
    return sequence


def _query_context_phrases(text: str) -> list[str]:
    sequence = _query_context_token_sequence(text)
    phrases: list[str] = []
    seen: set[str] = set()
    for size in (4, 3, 2):
        for index in range(0, max(len(sequence) - size + 1, 0)):
            phrase = " ".join(sequence[index : index + size])
            if phrase and phrase not in seen:
                phrases.append(phrase)
                seen.add(phrase)
    return phrases


def _normalized_context_text(text: str) -> str:
    return " ".join(token.casefold() for token in TOKEN_RE.findall(text))


def _document_text(document: Mapping[str, Any]) -> str:
    return " ".join(
        str(document.get(key, ""))
        for key in ("title", "section_title", "description", "body", "excerpt", "concept_id")
    )


def _document_context_text(document: Mapping[str, Any]) -> str:
    return " ".join(
        str(document.get(key, ""))
        for key in (
            "source_id",
            "section_id",
            "concept_id",
            "title",
            "section_title",
            "description",
            "body",
            "excerpt",
        )
    )


def _evidence_context_text(item: Mapping[str, Any]) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in (
            "source_id",
            "source_identity",
            "section_id",
            "concept_id",
            "title",
            "section_title",
            "passage_text",
        )
    )


def _candidate_context_text(
    candidate: Mapping[str, Any],
    document: Mapping[str, Any],
) -> str:
    dense = candidate.get("dense") if isinstance(candidate.get("dense"), Mapping) else {}
    lexical = candidate.get("lexical") if isinstance(candidate.get("lexical"), Mapping) else {}
    return " ".join(
        [
            _document_context_text(document),
            str(lexical.get("snippet", "")),
            str(lexical.get("title", "")),
            str(dense.get("snippet", "")),
            str(dense.get("source_id", "")),
        ]
    )


def _query_context_signal(*, question: str, text: str) -> dict[str, Any]:
    query_terms = _query_context_terms(question)
    text_terms = _meaningful_terms(text)
    coverage_terms = sorted(query_terms & text_terms)
    normalized_text = _normalized_context_text(text)
    phrase_matches = [
        phrase for phrase in _query_context_phrases(question) if phrase in normalized_text
    ]
    coverage_count = len(coverage_terms)
    coverage_ratio = coverage_count / max(len(query_terms), 1)
    score = coverage_ratio * 8.0 + min(coverage_count, 5) * 0.8
    score += min(len(phrase_matches), 4) * 4.0
    if coverage_count <= 0:
        score -= 2.0
    elif len(query_terms) >= 3 and coverage_count == 1 and not phrase_matches:
        score -= 1.5
    return {
        "query_context_terms": sorted(query_terms),
        "query_context_term_count": len(query_terms),
        "query_context_coverage_terms": coverage_terms,
        "query_context_coverage_count": coverage_count,
        "query_context_coverage_ratio": coverage_ratio,
        "query_context_phrase_matches": phrase_matches,
        "query_context_phrase_match_count": len(phrase_matches),
        "query_context_score": score,
    }


def _coverage_terms(text: str) -> set[str]:
    return _meaningful_terms(text) - GENERIC_RELATIONAL_TERMS


def _is_article_root_document(document: Mapping[str, Any]) -> bool:
    section_id = str(document.get("section_id", ""))
    concept_id = str(document.get("concept_id", ""))
    section_title = str(document.get("section_title", "")).casefold()
    return section_id == concept_id or section_title in {"article overview", "overview"}


def _passage_answer_quality_score(item: Mapping[str, Any]) -> float:
    text = str(item.get("passage_text") or item.get("body") or item.get("excerpt") or "")
    score = _passage_text_quality(text)
    if _is_article_root_document(item):
        score -= 0.75
    return score


def _passage_text_quality(text: str) -> float:
    segments = _exact_quote_segments(str(text))
    meaningful = [
        segment
        for segment in segments
        if len(segment) >= 48 and not _thin_heading(segment) and not _article_title_like(segment)
    ]
    return len(meaningful) + min(len(str(text)), 1200) / 1200.0


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


def _production_qdrant_filter() -> dict[str, Any]:
    return {
        "must": [
            {"key": "release_id", "match": {"value": FULL_PRODUCTION_RELEASE_ID}},
            {"key": "source_commit_sha", "match": {"value": FULL_PRODUCTION_SOURCE_SHA}},
            {
                "key": "admission_sha256",
                "match": {"value": FULL_PRODUCTION_ADMISSION_SHA256},
            },
            {"key": "candidate_release_eligible", "match": {"value": True}},
            {"key": "production_authority", "match": {"value": False}},
        ]
    }


def _validate_qdrant_payload_identity(payload: Mapping[str, Any]) -> None:
    expected = {
        "release_id": FULL_PRODUCTION_RELEASE_ID,
        "source_commit_sha": FULL_PRODUCTION_SOURCE_SHA,
        "admission_sha256": FULL_PRODUCTION_ADMISSION_SHA256,
        "candidate_release_eligible": True,
        "production_authority": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PA7ArbitraryQueryError(
                "PA7_QDRANT_PAYLOAD_IDENTITY_MISMATCH",
                f"Qdrant dense payload identity mismatch: {key}",
            )
    text_sha = str(payload.get("text_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", text_sha):
        raise PA7ArbitraryQueryError(
            "PA7_QDRANT_PAYLOAD_IDENTITY_MISMATCH",
            "Qdrant dense payload text digest is invalid",
        )


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
        "r2_write_operations": 0,
    }


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PA7ArbitraryQueryError("PA7_OBJECT_INVALID", label)
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PA7ArbitraryQueryError("PA7_LIST_INVALID", label)
    return value
