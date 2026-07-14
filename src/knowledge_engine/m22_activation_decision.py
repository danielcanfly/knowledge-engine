from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError
from .m22_reasoning_modes import (
    MAX_HOPS,
    MAX_MODEL_CALLS,
    MAX_RETRIEVALS,
    MAX_STEPS,
    MAX_TIMEOUT_MS,
    MAX_TOTAL_TOKENS,
    PROTECTED_MUTATION_KEYS,
    validate_reasoning_mode_policy,
)

ACTIVATION_THRESHOLD = 4
MAX_CONCEPTS = 16
MAX_RELATIONS = 32
MAX_EVIDENCE_SOURCES = 16
DISPOSITIONS = ("direct_only", "activate", "blocked")

FEATURE_FIELDS = {
    "concept_count",
    "relation_count",
    "comparison_required",
    "causal_chain_required",
    "synthesis_required",
    "temporal_sequence_required",
    "ambiguity_score",
    "evidence_sources_required",
    "direct_answer_available",
    "not_found",
    "acl_sufficient",
    "estimated_hops",
    "estimated_steps",
    "estimated_retrievals",
    "estimated_model_calls",
    "estimated_total_tokens",
    "estimated_timeout_ms",
}

BUDGET_FIELD_MAP = {
    "estimated_hops": "max_hops",
    "estimated_steps": "max_steps",
    "estimated_retrievals": "max_retrievals",
    "estimated_model_calls": "max_model_calls",
    "estimated_total_tokens": "max_total_tokens",
    "estimated_timeout_ms": "timeout_ms",
}


@dataclass(frozen=True)
class ActivationDecision:
    mode: str
    disposition: str
    score: int
    reason_codes: tuple[str, ...]
    policy_sha256: str
    features_sha256: str
    decision_sha256: str
    planner_constructed: bool
    planner_invocations: int
    model_call_count: int
    production_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-m22-activation-decision/v1",
            "mode": self.mode,
            "disposition": self.disposition,
            "score": self.score,
            "reason_codes": list(self.reason_codes),
            "policy_sha256": self.policy_sha256,
            "features_sha256": self.features_sha256,
            "decision_sha256": self.decision_sha256,
            "planner_constructed": self.planner_constructed,
            "planner_invocations": self.planner_invocations,
            "model_call_count": self.model_call_count,
            "production_authority": self.production_authority,
        }


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M22-ACT-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-ACT-102 {label} shape is invalid")


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise IntegrityError(f"M22-ACT-103 {label} must be boolean")
    return value


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"M22-ACT-104 {label} must be an integer")
    if value < minimum or value > maximum:
        raise IntegrityError(f"M22-ACT-105 {label} is outside the governed bound")
    return value


def _validate_features(payload: Any) -> dict[str, Any]:
    features = _require_mapping(payload, label="features")
    _require_exact_keys(features, expected=FEATURE_FIELDS, label="features")

    result = {
        "concept_count": _require_int(
            features.get("concept_count"),
            label="concept_count",
            minimum=1,
            maximum=MAX_CONCEPTS,
        ),
        "relation_count": _require_int(
            features.get("relation_count"),
            label="relation_count",
            minimum=0,
            maximum=MAX_RELATIONS,
        ),
        "comparison_required": _require_bool(
            features.get("comparison_required"),
            label="comparison_required",
        ),
        "causal_chain_required": _require_bool(
            features.get("causal_chain_required"),
            label="causal_chain_required",
        ),
        "synthesis_required": _require_bool(
            features.get("synthesis_required"),
            label="synthesis_required",
        ),
        "temporal_sequence_required": _require_bool(
            features.get("temporal_sequence_required"),
            label="temporal_sequence_required",
        ),
        "ambiguity_score": _require_int(
            features.get("ambiguity_score"),
            label="ambiguity_score",
            minimum=0,
            maximum=100,
        ),
        "evidence_sources_required": _require_int(
            features.get("evidence_sources_required"),
            label="evidence_sources_required",
            minimum=1,
            maximum=MAX_EVIDENCE_SOURCES,
        ),
        "direct_answer_available": _require_bool(
            features.get("direct_answer_available"),
            label="direct_answer_available",
        ),
        "not_found": _require_bool(
            features.get("not_found"),
            label="not_found",
        ),
        "acl_sufficient": _require_bool(
            features.get("acl_sufficient"),
            label="acl_sufficient",
        ),
        "estimated_hops": _require_int(
            features.get("estimated_hops"),
            label="estimated_hops",
            minimum=0,
            maximum=MAX_HOPS,
        ),
        "estimated_steps": _require_int(
            features.get("estimated_steps"),
            label="estimated_steps",
            minimum=0,
            maximum=MAX_STEPS,
        ),
        "estimated_retrievals": _require_int(
            features.get("estimated_retrievals"),
            label="estimated_retrievals",
            minimum=0,
            maximum=MAX_RETRIEVALS,
        ),
        "estimated_model_calls": _require_int(
            features.get("estimated_model_calls"),
            label="estimated_model_calls",
            minimum=0,
            maximum=MAX_MODEL_CALLS,
        ),
        "estimated_total_tokens": _require_int(
            features.get("estimated_total_tokens"),
            label="estimated_total_tokens",
            minimum=0,
            maximum=MAX_TOTAL_TOKENS,
        ),
        "estimated_timeout_ms": _require_int(
            features.get("estimated_timeout_ms"),
            label="estimated_timeout_ms",
            minimum=0,
            maximum=MAX_TIMEOUT_MS,
        ),
    }

    if result["not_found"] and result["direct_answer_available"]:
        raise IntegrityError(
            "M22-ACT-106 not_found conflicts with direct_answer_available"
        )
    if result["estimated_steps"] < result["estimated_hops"]:
        raise IntegrityError(
            "M22-ACT-107 estimated_steps must be at least estimated_hops"
        )
    if result["estimated_retrievals"] < result["estimated_hops"]:
        raise IntegrityError(
            "M22-ACT-108 estimated_retrievals must be at least estimated_hops"
        )
    return result


def _validate_protected_state(payload: Any) -> None:
    state = _require_mapping(payload, label="protected_state")
    if tuple(sorted(state)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-ACT-109 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if state.get(name) is not False:
            raise IntegrityError(
                f"M22-ACT-110 protected mutation was dispatched: {name}"
            )


def _budget_fits(
    policy: Mapping[str, Any],
    features: Mapping[str, Any],
) -> bool:
    budget = _require_mapping(policy.get("budget"), label="policy budget")
    return all(
        features[estimate_field] <= budget.get(limit_field, -1)
        for estimate_field, limit_field in BUDGET_FIELD_MAP.items()
    )


def _score(features: Mapping[str, Any]) -> tuple[int, tuple[str, ...]]:
    score = 0
    reasons: list[str] = []
    weighted_signals = (
        ("comparison_required", 2, "comparison_required"),
        ("causal_chain_required", 2, "causal_chain_required"),
        ("synthesis_required", 2, "synthesis_required"),
        ("temporal_sequence_required", 1, "temporal_sequence_required"),
    )
    for field, weight, reason in weighted_signals:
        if features[field]:
            score += weight
            reasons.append(reason)

    if features["concept_count"] >= 3:
        score += 2
        reasons.append("multiple_concepts")
    elif features["concept_count"] == 2:
        score += 1
        reasons.append("two_concepts")

    if features["relation_count"] >= 2:
        score += 2
        reasons.append("multiple_relations")
    elif features["relation_count"] == 1:
        score += 1
        reasons.append("one_relation")

    if features["evidence_sources_required"] >= 3:
        score += 2
        reasons.append("multiple_evidence_sources")
    elif features["evidence_sources_required"] == 2:
        score += 1
        reasons.append("two_evidence_sources")

    if features["ambiguity_score"] >= 70:
        score += 2
        reasons.append("high_ambiguity")
    elif features["ambiguity_score"] >= 40:
        score += 1
        reasons.append("moderate_ambiguity")

    if features["estimated_hops"] >= 2:
        score += 2
        reasons.append("multi_hop_estimate")

    if features["direct_answer_available"]:
        score -= 3
        reasons.append("direct_answer_available")

    return score, tuple(sorted(reasons))


def decide_reasoning_activation(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="activation evidence")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "policy",
            "features",
            "protected_state",
        },
        label="activation evidence",
    )
    if root.get("schema_version") != "knowledge-engine-m22-activation-evidence/v1":
        raise IntegrityError(
            "M22-ACT-111 unsupported activation evidence schema"
        )

    policy = _require_mapping(root.get("policy"), label="policy")
    policy_report = validate_reasoning_mode_policy(policy)
    features = _validate_features(root.get("features"))
    _validate_protected_state(root.get("protected_state"))

    mode = policy_report["mode"]
    score, feature_reasons = _score(features)
    budget_fits = _budget_fits(policy, features)

    if not features["acl_sufficient"]:
        disposition = "blocked"
        reasons = ("acl_insufficient",)
    elif features["not_found"]:
        disposition = "direct_only"
        reasons = ("not_found",)
    elif mode == "off":
        disposition = "direct_only"
        reasons = ("mode_off",)
    elif not budget_fits:
        disposition = "blocked"
        reasons = ("budget_exceeded",)
    elif mode == "force":
        disposition = "activate"
        reasons = ("mode_force",)
    elif score >= ACTIVATION_THRESHOLD and features["estimated_hops"] >= 2:
        disposition = "activate"
        reasons = feature_reasons
    else:
        disposition = "direct_only"
        reasons = tuple(
            sorted((*feature_reasons, "below_activation_threshold"))
        )

    features_sha256 = _canonical_sha256(features)
    decision_material = {
        "mode": mode,
        "disposition": disposition,
        "score": score,
        "reason_codes": list(reasons),
        "policy_sha256": policy_report["policy_sha256"],
        "features_sha256": features_sha256,
    }
    decision = ActivationDecision(
        mode=mode,
        disposition=disposition,
        score=score,
        reason_codes=reasons,
        policy_sha256=policy_report["policy_sha256"],
        features_sha256=features_sha256,
        decision_sha256=_canonical_sha256(decision_material),
        planner_constructed=False,
        planner_invocations=0,
        model_call_count=0,
        production_authority=False,
    )
    return decision.to_dict()


__all__ = [
    "ACTIVATION_THRESHOLD",
    "DISPOSITIONS",
    "ActivationDecision",
    "decide_reasoning_activation",
]
