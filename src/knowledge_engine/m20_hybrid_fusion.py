from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError
from .m20_retrieval_modes import (
    HYBRID_MODE,
    LEXICAL_MODE,
    VECTOR_MODE,
    RetrievalModeController,
    RetrievalRuntime,
)

RRF_K = 60
MAX_FUSION_CANDIDATES = 40
FUSION_METHOD = "reciprocal_rank_fusion"
FALLBACK_QUERY_VECTOR_UNAVAILABLE = "query_vector_unavailable"
FALLBACK_SEMANTIC_UNAVAILABLE = "semantic_unavailable"
FALLBACK_VECTOR_EXECUTION_UNAVAILABLE = "vector_execution_unavailable"


@dataclass(frozen=True)
class FusionEvidence:
    lexical_rank: int | None
    vector_rank: int | None
    lexical_contribution: float
    vector_contribution: float
    fused_score: float


def _rank_contribution(rank: int | None) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (RRF_K + rank)


def _section_id(item: Mapping[str, Any], label: str) -> str:
    value = item.get("section_id")
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"M20-FUSION-101 {label} result lacks section identity")
    return value


def _concept_id(item: Mapping[str, Any], label: str) -> str:
    value = item.get("concept_id")
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"M20-FUSION-102 {label} result lacks concept identity")
    return value


def _audience(item: Mapping[str, Any], label: str) -> str:
    value = item.get("audience")
    if not isinstance(value, str) or not value:
        raise IntegrityError(f"M20-FUSION-103 {label} result lacks audience identity")
    return value


def _release_identity(result: Mapping[str, Any]) -> tuple[str, str]:
    release = result.get("release")
    if not isinstance(release, Mapping):
        raise IntegrityError("M20-FUSION-104 retrieval result lacks release identity")
    release_id = release.get("release_id")
    manifest_sha256 = release.get("manifest_sha256")
    if not isinstance(release_id, str) or not isinstance(manifest_sha256, str):
        raise IntegrityError("M20-FUSION-104 retrieval result lacks release identity")
    return release_id, manifest_sha256


def _validate_ranked_results(
    results: Any,
    *,
    label: str,
    allowed_audiences: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(results, list):
        raise IntegrityError(f"M20-FUSION-105 {label} results must be a list")
    if len(results) > MAX_FUSION_CANDIDATES:
        raise IntegrityError(f"M20-FUSION-106 {label} result count exceeds fusion bounds")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, Mapping):
            raise IntegrityError(f"M20-FUSION-107 {label} result must be an object")
        section_id = _section_id(item, label)
        if section_id in seen:
            raise IntegrityError(f"M20-FUSION-108 duplicate {label} section: {section_id}")
        seen.add(section_id)
        audience = _audience(item, label)
        if audience not in allowed_audiences:
            raise IntegrityError(f"M20-FUSION-109 unauthorized {label} result: {section_id}")
        normalized.append(dict(item))
    return normalized


def reciprocal_rank_fuse(
    lexical_results: Sequence[Mapping[str, Any]],
    vector_results: Sequence[Mapping[str, Any]],
    *,
    allowed_audiences: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise IntegrityError("M20-FUSION-110 limit must be an integer between 1 and 20")
    lexical = _validate_ranked_results(
        list(lexical_results), label="lexical", allowed_audiences=allowed_audiences
    )
    vector = _validate_ranked_results(
        list(vector_results), label="vector", allowed_audiences=allowed_audiences
    )

    records: dict[str, dict[str, Any]] = {}
    for label, ranked in (("lexical", lexical), ("vector", vector)):
        for rank, item in enumerate(ranked, start=1):
            section_id = _section_id(item, label)
            concept_id = _concept_id(item, label)
            audience = _audience(item, label)
            record = records.setdefault(
                section_id,
                {
                    "section_id": section_id,
                    "concept_id": concept_id,
                    "audience": audience,
                    "lexical_rank": None,
                    "vector_rank": None,
                    "lexical_result": None,
                    "vector_score": None,
                },
            )
            if record["concept_id"] != concept_id or record["audience"] != audience:
                raise IntegrityError(
                    f"M20-FUSION-111 identity mismatch for fused section: {section_id}"
                )
            record[f"{label}_rank"] = rank
            if label == "lexical":
                record["lexical_result"] = copy.deepcopy(item)
            else:
                score = item.get("score")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    raise IntegrityError(
                        f"M20-FUSION-112 vector score is invalid for section: {section_id}"
                    )
                score_value = float(score)
                if not math.isfinite(score_value):
                    raise IntegrityError(
                        f"M20-FUSION-112 vector score is invalid for section: {section_id}"
                    )
                record["vector_score"] = round(score_value, 8)

    fused: list[dict[str, Any]] = []
    for record in records.values():
        lexical_rank = record["lexical_rank"]
        vector_rank = record["vector_rank"]
        lexical_contribution = _rank_contribution(lexical_rank)
        vector_contribution = _rank_contribution(vector_rank)
        fused_score = lexical_contribution + vector_contribution
        evidence = FusionEvidence(
            lexical_rank=lexical_rank,
            vector_rank=vector_rank,
            lexical_contribution=round(lexical_contribution, 12),
            vector_contribution=round(vector_contribution, 12),
            fused_score=round(fused_score, 12),
        )
        fused.append(
            {
                "section_id": record["section_id"],
                "concept_id": record["concept_id"],
                "audience": record["audience"],
                "fused_score": evidence.fused_score,
                "lexical_rank": evidence.lexical_rank,
                "vector_rank": evidence.vector_rank,
                "lexical_contribution": evidence.lexical_contribution,
                "vector_contribution": evidence.vector_contribution,
                "vector_score": record["vector_score"],
                "lexical_result": record["lexical_result"],
            }
        )

    sentinel = MAX_FUSION_CANDIDATES + 1
    fused.sort(
        key=lambda item: (
            -item["fused_score"],
            item["lexical_rank"] if item["lexical_rank"] is not None else sentinel,
            item["vector_rank"] if item["vector_rank"] is not None else sentinel,
            item["section_id"],
        )
    )
    return fused[:limit]


class HybridFusionController:
    def __init__(self, mode_controller: RetrievalModeController) -> None:
        self.mode_controller = mode_controller

    def _lexical_fallback(
        self,
        runtime: RetrievalRuntime,
        query: str,
        allowed_audiences: set[str],
        *,
        limit: int,
        reason: str,
    ) -> dict[str, Any]:
        lexical = copy.deepcopy(runtime.query(query, allowed_audiences, limit=limit))
        retrieval = lexical.setdefault("retrieval", {})
        retrieval.update(
            {
                "configured_mode": HYBRID_MODE,
                "authoritative_mode": LEXICAL_MODE,
                "fusion_method": FUSION_METHOD,
                "fusion_applied": False,
                "fallback_applied": True,
                "fallback_reason": reason,
                "production_authority": False,
            }
        )
        lexical["fused_candidates"] = []
        return lexical

    def query(
        self,
        runtime: RetrievalRuntime,
        query: str,
        allowed_audiences: set[str],
        *,
        query_vector: Sequence[float] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        mode = self.mode_controller.settings.mode
        if mode != HYBRID_MODE:
            return self.mode_controller.query(
                runtime,
                query,
                allowed_audiences,
                query_vector=query_vector,
                limit=limit,
            )
        if query_vector is None:
            return self._lexical_fallback(
                runtime,
                query,
                allowed_audiences,
                limit=limit,
                reason=FALLBACK_QUERY_VECTOR_UNAVAILABLE,
            )

        capability = self.mode_controller.capability(runtime)
        if not capability["ready"]:
            reason = capability.get("reason")
            if reason == FALLBACK_SEMANTIC_UNAVAILABLE:
                return self._lexical_fallback(
                    runtime,
                    query,
                    allowed_audiences,
                    limit=limit,
                    reason=FALLBACK_SEMANTIC_UNAVAILABLE,
                )
            raise IntegrityError(f"M20-FUSION-113 semantic capability mismatch: {reason}")

        try:
            shadow = self.mode_controller.query(
                runtime,
                query,
                allowed_audiences,
                query_vector=query_vector,
                limit=limit,
            )
        except IntegrityError as exc:
            message = str(exc)
            if "semantic retrieval is not ready: semantic_unavailable" in message:
                return self._lexical_fallback(
                    runtime,
                    query,
                    allowed_audiences,
                    limit=limit,
                    reason=FALLBACK_VECTOR_EXECUTION_UNAVAILABLE,
                )
            raise

        shadow_evaluation = shadow.get("shadow_evaluation")
        if not isinstance(shadow_evaluation, Mapping):
            raise IntegrityError("M20-FUSION-114 hybrid shadow evidence is missing")
        if _release_identity(shadow) != _release_identity(shadow_evaluation):
            raise IntegrityError("M20-FUSION-115 lexical and vector release identities differ")

        lexical_results = shadow.get("results", [])
        vector_results = shadow_evaluation.get("results", [])
        fused = reciprocal_rank_fuse(
            lexical_results,
            vector_results,
            allowed_audiences=allowed_audiences,
            limit=limit,
        )
        retrieval = shadow.setdefault("retrieval", {})
        retrieval.update(
            {
                "configured_mode": HYBRID_MODE,
                "mode": "hybrid_fused_candidates",
                "authoritative_mode": LEXICAL_MODE,
                "fusion_method": FUSION_METHOD,
                "rrf_k": RRF_K,
                "fusion_applied": True,
                "fallback_applied": False,
                "fallback_reason": None,
                "fused_candidate_count": len(fused),
                "production_authority": False,
            }
        )
        shadow["fused_candidates"] = fused
        return shadow


__all__ = [
    "FUSION_METHOD",
    "HybridFusionController",
    "MAX_FUSION_CANDIDATES",
    "RRF_K",
    "reciprocal_rank_fuse",
]
