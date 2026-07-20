from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ConfigurationError, IntegrityError

LEXICAL_MODE = "lexical"
SEMANTIC_SHADOW_MODE = "semantic_shadow"
HYBRID_SHADOW_MODE = "hybrid_shadow"
SUPPORTED_REQUESTED_MODES = frozenset({
    LEXICAL_MODE,
    SEMANTIC_SHADOW_MODE,
    HYBRID_SHADOW_MODE,
})
MAX_SHADOW_RESULTS = 50


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _bool_env(name: str, default: bool) -> bool:
    raw = (_env(name, "true" if default else "false") or "").casefold()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"M24-RUNTIME-001 {name} must be a boolean")


@dataclass(frozen=True)
class M24RetrievalRuntimeSettings:
    requested_mode: str = LEXICAL_MODE
    channel: str = "production"
    flagged_implementation_enabled: bool = False
    activation_authorized: bool = False

    @classmethod
    def from_env(cls) -> M24RetrievalRuntimeSettings:
        settings = cls(
            requested_mode=(
                _env("M24_RETRIEVAL_REQUESTED_MODE", LEXICAL_MODE) or LEXICAL_MODE
            ).casefold(),
            channel=(_env("KNOWLEDGE_CHANNEL", "production") or "production").casefold(),
            flagged_implementation_enabled=_bool_env(
                "M24_SEMANTIC_HYBRID_IMPLEMENTATION_ENABLED",
                False,
            ),
            activation_authorized=_bool_env(
                "M24_SEMANTIC_ACTIVATION_AUTHORIZED",
                False,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.requested_mode not in SUPPORTED_REQUESTED_MODES:
            raise ConfigurationError(
                "M24-RUNTIME-002 requested mode must be lexical, "
                "semantic_shadow, or hybrid_shadow"
            )
        if self.channel not in {"production", "internal", "staging", "test"}:
            raise ConfigurationError(f"M24-RUNTIME-003 unsupported channel: {self.channel}")
        if self.activation_authorized:
            raise ConfigurationError(
                "M24-RUNTIME-004 semantic activation requires a later activation "
                "reconciliation"
            )
        if (
            self.requested_mode != LEXICAL_MODE
            and not self.flagged_implementation_enabled
        ):
            raise ConfigurationError(
                "M24-RUNTIME-005 semantic/hybrid shadow requires the flagged "
                "implementation switch"
            )
        if self.requested_mode != LEXICAL_MODE and self.channel == "production":
            raise ConfigurationError(
                "M24-RUNTIME-006 semantic/hybrid shadow is not allowed on the "
                "production channel"
            )

    @property
    def shadow_requested(self) -> bool:
        return self.requested_mode != LEXICAL_MODE


def _require_lexical_result(lexical_result: Mapping[str, Any]) -> None:
    if not isinstance(lexical_result, Mapping):
        raise IntegrityError("M24-RUNTIME-101 lexical result must be an object")
    results = lexical_result.get("results")
    if not isinstance(results, list) or len(results) > MAX_SHADOW_RESULTS:
        raise IntegrityError("M24-RUNTIME-102 lexical results must be a bounded list")


def _shape_shadow_preview(shadow_result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(shadow_result, Mapping):
        raise IntegrityError("M24-RUNTIME-103 shadow result must be an object")
    results = shadow_result.get("results")
    if not isinstance(results, list) or len(results) > MAX_SHADOW_RESULTS:
        raise IntegrityError("M24-RUNTIME-104 shadow results must be a bounded list")

    authority = shadow_result.get("authority", {})
    if not isinstance(authority, Mapping):
        raise IntegrityError("M24-RUNTIME-105 shadow authority must be an object")
    forbidden_true_flags = {
        "semantic_output_production_authority",
        "semantic_output_served_to_production",
        "answer_generation_dispatched",
        "qdrant_write_dispatched",
        "r2_mutation_dispatched",
        "source_mutation_dispatched",
        "pointer_mutation_dispatched",
        "production_mutation_dispatched",
    }
    enabled = sorted(
        key for key in forbidden_true_flags if authority.get(key) is True
    )
    if enabled:
        raise IntegrityError(
            "M24-RUNTIME-106 shadow result carries forbidden authority: "
            + ", ".join(enabled)
        )

    preview_results: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, Mapping):
            raise IntegrityError("M24-RUNTIME-107 shadow item must be an object")
        point_id = item.get("point_id", item.get("section_id"))
        section_id = item.get("section_id")
        if not isinstance(point_id, str) or not point_id:
            raise IntegrityError("M24-RUNTIME-108 shadow item lacks stable identity")
        if section_id is not None and (not isinstance(section_id, str) or not section_id):
            raise IntegrityError("M24-RUNTIME-109 shadow section ID is invalid")
        preview_results.append(
            {
                "rank": index,
                "point_id": point_id,
                "section_id": section_id,
                "score_present": isinstance(item.get("score"), (int, float))
                and not isinstance(item.get("score"), bool),
            }
        )

    return {
        "status": shadow_result.get("status"),
        "result_count": len(preview_results),
        "results": preview_results,
        "diagnostic_only": True,
        "response_authoritative": False,
        "production_authority": False,
        "raw_query_persisted": False,
        "raw_answer_persisted": False,
    }


def apply_m24_flagged_retrieval(
    lexical_result: Mapping[str, Any],
    settings: M24RetrievalRuntimeSettings | None = None,
    *,
    shadow_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or M24RetrievalRuntimeSettings()
    settings.validate()
    _require_lexical_result(lexical_result)

    if shadow_result is not None and not settings.shadow_requested:
        raise IntegrityError(
            "M24-RUNTIME-110 shadow result supplied while lexical mode is requested"
        )
    if settings.shadow_requested and shadow_result is None:
        raise IntegrityError(
            "M24-RUNTIME-111 semantic/hybrid shadow requires an explicit shadow result"
        )

    result = copy.deepcopy(dict(lexical_result))
    retrieval = result.setdefault("retrieval", {})
    if not isinstance(retrieval, dict):
        raise IntegrityError("M24-RUNTIME-112 retrieval metadata must be an object")
    retrieval.update(
        {
            "m24_flagged_runtime": True,
            "m24_requested_mode": settings.requested_mode,
            "m24_channel": settings.channel,
            "production_retrieval": LEXICAL_MODE,
            "authoritative_mode": LEXICAL_MODE,
            "semantic_hybrid_implementation_enabled": (
                settings.flagged_implementation_enabled
            ),
            "semantic_activation_authorized": False,
            "semantic_answer_serving_enabled": False,
            "semantic_promotion_enabled": False,
            "hybrid_retrieval_enabled": False,
            "fusion_applied": False,
            "production_authority": False,
            "lexical_fallback_available": True,
            "activation_gate_required": "m24_semantic_activation_reconciliation",
        }
    )

    if shadow_result is not None:
        result["m24_shadow_preview"] = _shape_shadow_preview(shadow_result)
        retrieval["shadow_preview_attached"] = True
    else:
        retrieval["shadow_preview_attached"] = False

    return result


__all__ = [
    "HYBRID_SHADOW_MODE",
    "LEXICAL_MODE",
    "M24RetrievalRuntimeSettings",
    "SEMANTIC_SHADOW_MODE",
    "apply_m24_flagged_retrieval",
]
