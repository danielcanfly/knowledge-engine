from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError

SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
REASONING_MODES = ("off", "auto", "force")
AUDIENCES = ("public", "internal", "restricted")
PROTECTED_MUTATION_KEYS = (
    "source_mutation_dispatched",
    "production_mutation_dispatched",
    "production_pointer_updated",
    "retained_r2_state_created",
    "credentials_modified",
    "permanent_ledger_written",
    "rollback_dispatched",
)

MAX_HOPS = 4
MAX_STEPS = 12
MAX_RETRIEVALS = 16
MAX_MODEL_CALLS = 4
MAX_TOTAL_TOKENS = 16_000
MAX_TIMEOUT_MS = 45_000


@dataclass(frozen=True)
class ReasoningModeReport:
    mode: str
    enabled: bool
    audience: str
    engine_sha: str
    source_sha: str
    foundation_sha: str
    release_id: str
    manifest_sha256: str
    policy_sha256: str
    planner_construction_permitted: bool
    model_calls_permitted: bool
    activation_decision_required: bool
    production_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-m22-reasoning-mode/v1",
            "mode": self.mode,
            "enabled": self.enabled,
            "audience": self.audience,
            "engine_sha": self.engine_sha,
            "source_sha": self.source_sha,
            "foundation_sha": self.foundation_sha,
            "release_id": self.release_id,
            "manifest_sha256": self.manifest_sha256,
            "policy_sha256": self.policy_sha256,
            "planner_construction_permitted": self.planner_construction_permitted,
            "model_calls_permitted": self.model_calls_permitted,
            "activation_decision_required": self.activation_decision_required,
            "production_authority": self.production_authority,
        }


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M22-MODE-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
    code: int,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-MODE-{code} {label} shape is invalid")


def _require_sha(value: Any, *, label: str, code: int) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise IntegrityError(f"M22-MODE-{code} {label} must be a 40-character commit SHA")
    if any(character not in "0123456789abcdef" for character in value):
        raise IntegrityError(f"M22-MODE-{code + 1} {label} must be lowercase hexadecimal")
    return value


def _require_sha256(value: Any, *, label: str, code: int) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise IntegrityError(f"M22-MODE-{code} {label} must be a 64-character SHA-256")
    if any(character not in "0123456789abcdef" for character in value):
        raise IntegrityError(f"M22-MODE-{code + 1} {label} must be lowercase hexadecimal")
    return value


def _require_bool(value: Any, *, label: str, code: int) -> bool:
    if not isinstance(value, bool):
        raise IntegrityError(f"M22-MODE-{code} {label} must be boolean")
    return value


def _require_bounded_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
    code: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"M22-MODE-{code} {label} must be an integer")
    if value < minimum or value > maximum:
        raise IntegrityError(
            f"M22-MODE-{code + 1} {label} must be between {minimum} and {maximum}"
        )
    return value


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_identity(payload: Any) -> tuple[str, str, str, str, str]:
    identity = _require_mapping(payload, label="identity")
    _require_exact_keys(
        identity,
        expected={
            "engine_sha",
            "source_sha",
            "foundation_sha",
            "release_id",
            "manifest_sha256",
        },
        label="identity",
        code=102,
    )
    engine_sha = _require_sha(identity.get("engine_sha"), label="Engine SHA", code=103)
    source_sha = _require_sha(identity.get("source_sha"), label="Source SHA", code=105)
    foundation_sha = _require_sha(
        identity.get("foundation_sha"),
        label="Foundation SHA",
        code=107,
    )
    if source_sha != SOURCE_SHA:
        raise IntegrityError("M22-MODE-109 Source release identity mismatch")
    if foundation_sha != FOUNDATION_SHA:
        raise IntegrityError("M22-MODE-110 Foundation release identity mismatch")

    release_id = identity.get("release_id")
    if not isinstance(release_id, str) or not release_id or len(release_id) > 128:
        raise IntegrityError("M22-MODE-111 release ID must be a bounded non-empty string")
    if any(character.isspace() for character in release_id):
        raise IntegrityError("M22-MODE-112 release ID must not contain whitespace")
    manifest_sha256 = _require_sha256(
        identity.get("manifest_sha256"),
        label="manifest SHA-256",
        code=113,
    )
    return engine_sha, source_sha, foundation_sha, release_id, manifest_sha256


def _validate_budget(payload: Any, *, mode: str) -> dict[str, int]:
    budget = _require_mapping(payload, label="budget")
    _require_exact_keys(
        budget,
        expected={
            "max_hops",
            "max_steps",
            "max_retrievals",
            "max_model_calls",
            "max_total_tokens",
            "timeout_ms",
        },
        label="budget",
        code=115,
    )
    maximums = {
        "max_hops": MAX_HOPS,
        "max_steps": MAX_STEPS,
        "max_retrievals": MAX_RETRIEVALS,
        "max_model_calls": MAX_MODEL_CALLS,
        "max_total_tokens": MAX_TOTAL_TOKENS,
        "timeout_ms": MAX_TIMEOUT_MS,
    }
    values = {
        field: _require_bounded_int(
            budget.get(field),
            label=field,
            minimum=0 if mode == "off" else 1,
            maximum=maximum,
            code=116 + index * 2,
        )
        for index, (field, maximum) in enumerate(maximums.items())
    }
    if mode == "off" and any(values.values()):
        raise IntegrityError("M22-MODE-128 off mode requires a zero execution budget")
    if values["max_steps"] < values["max_hops"]:
        raise IntegrityError("M22-MODE-129 max_steps must be at least max_hops")
    if values["max_retrievals"] < values["max_hops"]:
        raise IntegrityError("M22-MODE-130 max_retrievals must be at least max_hops")
    return values


def _validate_boundaries(payload: Any, *, mode: str) -> None:
    boundaries = _require_mapping(payload, label="boundaries")
    _require_exact_keys(
        boundaries,
        expected={
            "acl_enforced",
            "audience_broadening_forbidden",
            "provenance_required",
            "citations_required",
            "deterministic_replay_required",
            "fallback_required",
            "planner_allowed",
            "model_calls_allowed",
            "graph_neural_retrieval_allowed",
            "source_write_permitted",
            "production_authority",
        },
        label="boundaries",
        code=131,
    )
    required_true = (
        "acl_enforced",
        "audience_broadening_forbidden",
        "provenance_required",
        "citations_required",
        "deterministic_replay_required",
        "fallback_required",
    )
    for index, field in enumerate(required_true):
        if _require_bool(
            boundaries.get(field),
            label=field,
            code=132 + index,
        ) is not True:
            raise IntegrityError(f"M22-MODE-140 required safety boundary is false: {field}")

    planner_allowed = _require_bool(
        boundaries.get("planner_allowed"),
        label="planner_allowed",
        code=141,
    )
    model_calls_allowed = _require_bool(
        boundaries.get("model_calls_allowed"),
        label="model_calls_allowed",
        code=142,
    )
    expected_enabled = mode != "off"
    if planner_allowed is not expected_enabled:
        raise IntegrityError("M22-MODE-143 planner permission conflicts with reasoning mode")
    if model_calls_allowed is not expected_enabled:
        raise IntegrityError("M22-MODE-144 model-call permission conflicts with reasoning mode")

    forbidden_true = (
        "graph_neural_retrieval_allowed",
        "source_write_permitted",
        "production_authority",
    )
    for index, field in enumerate(forbidden_true):
        if _require_bool(
            boundaries.get(field),
            label=field,
            code=145 + index,
        ) is not False:
            raise IntegrityError(f"M22-MODE-150 forbidden authority was granted: {field}")


def _validate_protected_state(payload: Any) -> None:
    protected = _require_mapping(payload, label="protected state")
    if tuple(sorted(protected)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-MODE-151 protected-state evidence is incomplete")
    for field in PROTECTED_MUTATION_KEYS:
        if protected.get(field) is not False:
            raise IntegrityError(f"M22-MODE-152 protected mutation was dispatched: {field}")


def validate_reasoning_mode_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="reasoning policy")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "mode",
            "enabled",
            "audience",
            "identity",
            "budget",
            "boundaries",
            "protected_state",
        },
        label="reasoning policy",
        code=153,
    )
    if root.get("schema_version") != "knowledge-engine-m22-reasoning-policy/v1":
        raise IntegrityError("M22-MODE-154 unsupported reasoning policy schema")

    mode = root.get("mode")
    if mode not in REASONING_MODES:
        raise IntegrityError("M22-MODE-155 reasoning mode must be off, auto, or force")
    enabled = _require_bool(root.get("enabled"), label="enabled", code=156)
    if enabled is not (mode != "off"):
        raise IntegrityError("M22-MODE-157 enabled flag conflicts with reasoning mode")

    audience = root.get("audience")
    if audience not in AUDIENCES:
        raise IntegrityError("M22-MODE-158 audience is invalid")

    engine_sha, source_sha, foundation_sha, release_id, manifest_sha256 = _validate_identity(
        root.get("identity")
    )
    _validate_budget(root.get("budget"), mode=mode)
    _validate_boundaries(root.get("boundaries"), mode=mode)
    _validate_protected_state(root.get("protected_state"))

    report = ReasoningModeReport(
        mode=mode,
        enabled=enabled,
        audience=audience,
        engine_sha=engine_sha,
        source_sha=source_sha,
        foundation_sha=foundation_sha,
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        policy_sha256=_canonical_sha256(root),
        planner_construction_permitted=mode != "off",
        model_calls_permitted=mode != "off",
        activation_decision_required=mode == "auto",
        production_authority=False,
    )
    return report.to_dict()


def evaluate_reasoning_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    policy = validate_reasoning_mode_policy(payload)
    mode = policy["mode"]
    if mode == "off":
        disposition = "direct_only"
    elif mode == "auto":
        disposition = "await_activation_decision"
    else:
        disposition = "planner_required"
    return {
        "schema_version": "knowledge-engine-m22-reasoning-gate/v1",
        "mode": mode,
        "disposition": disposition,
        "planner_constructed": False,
        "planner_invocations": 0,
        "model_call_count": 0,
        "policy_sha256": policy["policy_sha256"],
        "production_authority": False,
    }


__all__ = [
    "AUDIENCES",
    "FOUNDATION_SHA",
    "MAX_HOPS",
    "MAX_MODEL_CALLS",
    "MAX_RETRIEVALS",
    "MAX_STEPS",
    "MAX_TIMEOUT_MS",
    "MAX_TOTAL_TOKENS",
    "PROTECTED_MUTATION_KEYS",
    "REASONING_MODES",
    "SOURCE_SHA",
    "ReasoningModeReport",
    "evaluate_reasoning_gate",
    "validate_reasoning_mode_policy",
]
