from __future__ import annotations

import copy
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import ConfigurationError, IntegrityError

LEXICAL_MODE = "lexical"
HYBRID_MODE = "hybrid"
VECTOR_MODE = "vector"
RETRIEVAL_MODES = frozenset({LEXICAL_MODE, HYBRID_MODE, VECTOR_MODE})
MAX_QUERY_LENGTH = 8_000
MAX_RESULTS = 20
MAX_VECTOR_DIMENSION = 65_536
UNIT_NORM_TOLERANCE = 1e-4


class RetrievalRuntime(Protocol):
    semantic_diagnostic_enabled: bool

    def query(
        self,
        query: str,
        allowed_audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict[str, Any]: ...

    def query_vector_diagnostic(
        self,
        query_vector: Sequence[float],
        allowed_audiences: set[str],
        *,
        limit: int = 10,
    ) -> dict[str, Any]: ...

    def semantic_capability(self) -> dict[str, Any]: ...


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _bool_env(name: str, default: bool) -> bool:
    raw = (_env(name, "true" if default else "false") or "").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"M20-MODE-001 {name} must be a boolean")


def _optional_int_env(name: str) -> int | None:
    raw = _env(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"M20-MODE-002 {name} must be an integer") from exc


@dataclass(frozen=True)
class RetrievalModeSettings:
    mode: str = LEXICAL_MODE
    app_env: str = "development"
    channel: str = "production"
    expected_model_id: str | None = None
    expected_dimension: int | None = None
    semantic_diagnostic_enabled: bool = False

    @classmethod
    def from_env(cls) -> RetrievalModeSettings:
        settings = cls(
            mode=(_env("RETRIEVAL_MODE", LEXICAL_MODE) or LEXICAL_MODE).lower(),
            app_env=(_env("APP_ENV", "development") or "development").lower(),
            channel=_env("KNOWLEDGE_CHANNEL", "production") or "production",
            expected_model_id=_env("EXPECTED_SEMANTIC_MODEL_ID"),
            expected_dimension=_optional_int_env("EXPECTED_SEMANTIC_DIMENSION"),
            semantic_diagnostic_enabled=_bool_env(
                "SEMANTIC_DIAGNOSTIC_ENABLED",
                False,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in RETRIEVAL_MODES:
            raise ConfigurationError(
                "M20-MODE-003 RETRIEVAL_MODE must be lexical, hybrid, or vector"
            )
        if self.app_env not in {"development", "test", "staging", "production"}:
            raise ConfigurationError(f"M20-MODE-004 unsupported APP_ENV: {self.app_env}")
        if self.mode != LEXICAL_MODE and self.app_env == "production":
            raise ConfigurationError(
                "M20-MODE-005 semantic retrieval modes are forbidden in production"
            )
        if self.mode != LEXICAL_MODE and self.channel == "production":
            raise ConfigurationError(
                "M20-MODE-006 semantic retrieval modes are forbidden on production channel"
            )
        if self.mode == LEXICAL_MODE:
            return
        if not self.expected_model_id:
            raise ConfigurationError(
                "M20-MODE-007 semantic retrieval requires EXPECTED_SEMANTIC_MODEL_ID"
            )
        if (
            self.expected_dimension is None
            or not 1 <= self.expected_dimension <= MAX_VECTOR_DIMENSION
        ):
            raise ConfigurationError(
                "M20-MODE-008 semantic retrieval requires a bounded exact dimension"
            )
        if not self.semantic_diagnostic_enabled:
            raise ConfigurationError(
                "M20-MODE-009 semantic retrieval requires explicit diagnostic enablement"
            )

    @property
    def semantic_required(self) -> bool:
        return self.mode != LEXICAL_MODE

    @property
    def authoritative_mode(self) -> str:
        if self.mode == VECTOR_MODE:
            return "vector_diagnostic"
        return LEXICAL_MODE

    @property
    def shadow_only(self) -> bool:
        return self.mode == HYBRID_MODE


def _validate_request(
    query: str,
    allowed_audiences: set[str],
    limit: int,
) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise IntegrityError("M20-MODE-101 query must contain 1 to 8000 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RESULTS:
        raise IntegrityError("M20-MODE-102 limit must be an integer between 1 and 20")
    if not allowed_audiences or any(
        not isinstance(audience, str) or not audience for audience in allowed_audiences
    ):
        raise IntegrityError("M20-MODE-103 allowed audiences must be non-empty strings")


def _validate_query_vector(
    query_vector: Sequence[float] | None,
    dimension: int,
) -> tuple[float, ...]:
    if query_vector is None:
        raise IntegrityError("M20-MODE-104 semantic mode requires a query vector")
    if isinstance(query_vector, (str, bytes, bytearray)) or len(query_vector) != dimension:
        raise IntegrityError(
            f"M20-MODE-105 query vector must contain exactly {dimension} values"
        )
    values: list[float] = []
    for index, item in enumerate(query_vector):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise IntegrityError(f"M20-MODE-106 query vector value {index} must be numeric")
        value = float(item)
        if not math.isfinite(value):
            raise IntegrityError(f"M20-MODE-107 query vector value {index} must be finite")
        values.append(value)
    norm = math.sqrt(math.fsum(value * value for value in values))
    if abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise IntegrityError(
            f"M20-MODE-108 query vector must be L2-normalised; norm={norm:.8f}"
        )
    return tuple(values)


def _release_identity(result: Mapping[str, Any]) -> tuple[str, str]:
    release = result.get("release")
    if not isinstance(release, Mapping):
        raise IntegrityError("M20-MODE-109 retrieval result lacks release identity")
    release_id = release.get("release_id")
    manifest_sha256 = release.get("manifest_sha256")
    if not isinstance(release_id, str) or not isinstance(manifest_sha256, str):
        raise IntegrityError("M20-MODE-109 retrieval result lacks release identity")
    return release_id, manifest_sha256


class RetrievalModeController:
    def __init__(self, settings: RetrievalModeSettings) -> None:
        settings.validate()
        self.settings = settings

    @classmethod
    def from_env(cls) -> RetrievalModeController:
        return cls(RetrievalModeSettings.from_env())

    def capability(self, runtime: RetrievalRuntime) -> dict[str, Any]:
        semantic = runtime.semantic_capability()
        semantic_ready = semantic.get("status") == "ready"
        model_matches = (
            self.settings.expected_model_id is None
            or semantic.get("model_id") == self.settings.expected_model_id
        )
        dimension_matches = (
            self.settings.expected_dimension is None
            or semantic.get("dimension") == self.settings.expected_dimension
        )
        diagnostic_matches = (
            not self.settings.semantic_required
            or (
                self.settings.semantic_diagnostic_enabled
                and bool(runtime.semantic_diagnostic_enabled)
            )
        )
        ready = (
            not self.settings.semantic_required
            or (
                semantic_ready
                and model_matches
                and dimension_matches
                and diagnostic_matches
            )
        )
        reason = None
        if not ready:
            if not semantic_ready:
                reason = "semantic_unavailable"
            elif not model_matches:
                reason = "model_mismatch"
            elif not dimension_matches:
                reason = "dimension_mismatch"
            else:
                reason = "diagnostic_disabled"
        return {
            "configured_mode": self.settings.mode,
            "authoritative_mode": self.settings.authoritative_mode,
            "shadow_only": self.settings.shadow_only,
            "diagnostic_only": self.settings.mode == VECTOR_MODE,
            "fusion_applied": False,
            "production_authority": False,
            "semantic_required": self.settings.semantic_required,
            "semantic_ready": semantic_ready,
            "ready": ready,
            "reason": reason,
            "model_id": semantic.get("model_id") if semantic_ready else None,
            "dimension": semantic.get("dimension") if semantic_ready else None,
        }

    def _require_semantic_ready(self, runtime: RetrievalRuntime) -> None:
        capability = self.capability(runtime)
        if not capability["ready"]:
            raise IntegrityError(
                "M20-MODE-110 semantic retrieval is not ready: "
                f"{capability['reason']}"
            )

    def query(
        self,
        runtime: RetrievalRuntime,
        query: str,
        allowed_audiences: set[str],
        *,
        query_vector: Sequence[float] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        _validate_request(query, allowed_audiences, limit)
        if self.settings.mode == LEXICAL_MODE:
            if query_vector is not None:
                raise IntegrityError(
                    "M20-MODE-111 lexical mode does not accept a semantic query vector"
                )
            lexical = copy.deepcopy(
                runtime.query(query, allowed_audiences, limit=limit)
            )
            retrieval = lexical.setdefault("retrieval", {})
            retrieval.update(
                {
                    "configured_mode": LEXICAL_MODE,
                    "authoritative_mode": LEXICAL_MODE,
                    "shadow_only": False,
                    "diagnostic_only": False,
                    "fusion_applied": False,
                    "production_authority": False,
                }
            )
            return lexical

        self._require_semantic_ready(runtime)
        assert self.settings.expected_dimension is not None
        vector = _validate_query_vector(query_vector, self.settings.expected_dimension)
        semantic = copy.deepcopy(
            runtime.query_vector_diagnostic(
                vector,
                allowed_audiences,
                limit=limit,
            )
        )
        semantic_retrieval = semantic.setdefault("retrieval", {})
        semantic_retrieval.update(
            {
                "configured_mode": self.settings.mode,
                "authoritative_mode": "vector_diagnostic",
                "shadow_only": self.settings.shadow_only,
                "diagnostic_only": True,
                "fusion_applied": False,
                "production_authority": False,
            }
        )

        if self.settings.mode == VECTOR_MODE:
            semantic["query"] = query
            return semantic

        lexical = copy.deepcopy(runtime.query(query, allowed_audiences, limit=limit))
        if _release_identity(lexical) != _release_identity(semantic):
            raise IntegrityError(
                "M20-MODE-112 lexical and semantic release identities differ"
            )
        retrieval = lexical.setdefault("retrieval", {})
        retrieval.update(
            {
                "configured_mode": HYBRID_MODE,
                "mode": "hybrid_shadow",
                "authoritative_mode": LEXICAL_MODE,
                "shadow_only": True,
                "diagnostic_only": False,
                "fusion_applied": False,
                "production_authority": False,
                "semantic_result_count": len(semantic.get("results", [])),
            }
        )
        lexical["shadow_evaluation"] = {
            "status": semantic.get("status"),
            "release": semantic.get("release"),
            "results": semantic.get("results", []),
            "retrieval": semantic_retrieval,
            "not_found_reason": semantic.get("not_found_reason"),
            "diagnostic_only": True,
            "fusion_applied": False,
            "production_authority": False,
        }
        return lexical


__all__ = [
    "HYBRID_MODE",
    "LEXICAL_MODE",
    "MAX_QUERY_LENGTH",
    "MAX_RESULTS",
    "RETRIEVAL_MODES",
    "RetrievalModeController",
    "RetrievalModeSettings",
    "VECTOR_MODE",
]
