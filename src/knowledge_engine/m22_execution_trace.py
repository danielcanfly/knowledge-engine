from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError
from .m22_bounded_plan import compile_bounded_reasoning_plan
from .m22_reasoning_modes import PROTECTED_MUTATION_KEYS

STEP_STATUSES = (
    "completed",
    "failed",
    "skipped_budget",
    "skipped_dependency",
)
TRACE_OUTCOMES = ("completed", "failed", "budget_stopped")
ERROR_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class ExecutionUsage:
    retrievals: int
    model_calls: int
    total_tokens: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, int]:
        return {
            "retrievals": self.retrievals,
            "model_calls": self.model_calls,
            "total_tokens": self.total_tokens,
            "elapsed_ms": self.elapsed_ms,
        }


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M22-EXEC-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-EXEC-102 {label} shape is invalid")


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise IntegrityError(f"M22-EXEC-103 {label} must be boolean")
    return value


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"M22-EXEC-104 {label} must be an integer")
    if value < minimum or value > maximum:
        raise IntegrityError(f"M22-EXEC-105 {label} is outside the governed bound")
    return value


def _require_refs(
    value: Any,
    *,
    label: str,
    maximum: int = 32,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M22-EXEC-106 {label} must be a list")
    refs = tuple(value)
    if len(refs) > maximum:
        raise IntegrityError(f"M22-EXEC-107 {label} count is outside the governed bound")
    if any(not isinstance(item, str) or not REF_PATTERN.fullmatch(item) for item in refs):
        raise IntegrityError(f"M22-EXEC-108 {label} contains an invalid reference")
    if len(set(refs)) != len(refs):
        raise IntegrityError(f"M22-EXEC-109 {label} contains duplicates")
    return refs


def _validate_protected_state(payload: Any) -> None:
    state = _require_mapping(payload, label="protected_state")
    if tuple(sorted(state)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-EXEC-110 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if state.get(name) is not False:
            raise IntegrityError(
                f"M22-EXEC-111 protected mutation was dispatched: {name}"
            )


def _validate_plan(
    supplied: Any,
    planning_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    plan = _require_mapping(supplied, label="bounded_plan")
    expected = compile_bounded_reasoning_plan(planning_evidence)
    if dict(plan) != expected:
        raise IntegrityError("M22-EXEC-112 bounded plan does not match planning evidence")
    if plan.get("schema_version") != "knowledge-engine-m22-bounded-plan/v1":
        raise IntegrityError("M22-EXEC-113 unsupported bounded plan schema")
    if (
        plan.get("planner_constructed") is not True
        or plan.get("planner_invocations") != 1
        or plan.get("execution_started") is not False
        or plan.get("model_call_count") != 0
        or plan.get("production_authority") is not False
    ):
        raise IntegrityError("M22-EXEC-114 bounded plan authority is invalid")
    return dict(plan)


def _validate_result(
    payload: Any,
    *,
    expected_step: Mapping[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    result = _require_mapping(payload, label="step_result")
    _require_exact_keys(
        result,
        expected={
            "step_id",
            "step_type",
            "plan_sha256",
            "input_refs",
            "status",
            "retrievals_used",
            "model_calls_used",
            "tokens_used",
            "elapsed_ms",
            "output_refs",
            "acl_passed",
            "provenance_complete",
            "citations_complete",
            "error_code",
        },
        label="step_result",
    )
    if result.get("step_id") != expected_step.get("step_id"):
        raise IntegrityError("M22-EXEC-115 step ID does not match bounded plan")
    if result.get("step_type") != expected_step.get("step_type"):
        raise IntegrityError("M22-EXEC-116 step type does not match bounded plan")
    if result.get("plan_sha256") != plan_sha256:
        raise IntegrityError("M22-EXEC-117 step result plan identity mismatch")

    input_refs = _require_refs(result.get("input_refs"), label="input_refs")
    if input_refs != tuple(expected_step.get("input_refs", ())):
        raise IntegrityError("M22-EXEC-118 step input references do not match plan")
    output_refs = _require_refs(result.get("output_refs"), label="output_refs")

    status = result.get("status")
    if status not in STEP_STATUSES:
        raise IntegrityError("M22-EXEC-119 unsupported step status")

    retrievals = _require_int(
        result.get("retrievals_used"),
        label="retrievals_used",
        minimum=0,
        maximum=expected_step.get("retrievals_reserved", -1),
    )
    model_calls = _require_int(
        result.get("model_calls_used"),
        label="model_calls_used",
        minimum=0,
        maximum=expected_step.get("model_calls_reserved", -1),
    )
    tokens = _require_int(
        result.get("tokens_used"),
        label="tokens_used",
        minimum=0,
        maximum=1_000_000,
    )
    elapsed_ms = _require_int(
        result.get("elapsed_ms"),
        label="elapsed_ms",
        minimum=0,
        maximum=3_600_000,
    )
    acl_passed = _require_bool(result.get("acl_passed"), label="acl_passed")
    provenance_complete = _require_bool(
        result.get("provenance_complete"),
        label="provenance_complete",
    )
    citations_complete = _require_bool(
        result.get("citations_complete"),
        label="citations_complete",
    )
    error_code = result.get("error_code")

    if status == "completed":
        if error_code is not None:
            raise IntegrityError("M22-EXEC-120 completed step cannot contain error code")
        if not acl_passed:
            raise IntegrityError("M22-EXEC-121 completed step requires ACL pass")
        if expected_step.get("retrievals_reserved", 0) and retrievals == 0:
            raise IntegrityError(
                "M22-EXEC-122 completed retrieval step requires retrieval evidence"
            )
        if expected_step.get("step_type") == "verify_acl_provenance_citations" and (
            not provenance_complete or not citations_complete
        ):
            raise IntegrityError(
                "M22-EXEC-123 final verification evidence is incomplete"
            )
    elif status == "failed":
        if not isinstance(error_code, str) or not ERROR_PATTERN.fullmatch(error_code):
            raise IntegrityError("M22-EXEC-124 failed step requires governed error code")
    else:
        if any((retrievals, model_calls, tokens, elapsed_ms)) or output_refs:
            raise IntegrityError("M22-EXEC-125 skipped step cannot report resource use")
        if acl_passed or provenance_complete or citations_complete:
            raise IntegrityError("M22-EXEC-126 skipped step cannot claim verification")
        expected_error = (
            "budget_exceeded"
            if status == "skipped_budget"
            else "dependency_not_completed"
        )
        if error_code != expected_error:
            raise IntegrityError("M22-EXEC-127 skipped step error code is invalid")

    return {
        "step_id": result["step_id"],
        "step_type": result["step_type"],
        "plan_sha256": result["plan_sha256"],
        "input_refs": list(input_refs),
        "status": status,
        "retrievals_used": retrievals,
        "model_calls_used": model_calls,
        "tokens_used": tokens,
        "elapsed_ms": elapsed_ms,
        "output_refs": list(output_refs),
        "acl_passed": acl_passed,
        "provenance_complete": provenance_complete,
        "citations_complete": citations_complete,
        "error_code": error_code,
    }


def validate_bounded_execution_trace(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="execution evidence")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "planning_evidence",
            "bounded_plan",
            "step_results",
            "protected_state",
        },
        label="execution evidence",
    )
    if root.get("schema_version") != "knowledge-engine-m22-execution-evidence/v1":
        raise IntegrityError("M22-EXEC-128 unsupported execution evidence schema")

    planning_evidence = _require_mapping(
        root.get("planning_evidence"),
        label="planning_evidence",
    )
    plan = _validate_plan(root.get("bounded_plan"), planning_evidence)
    _validate_protected_state(root.get("protected_state"))

    supplied_results = root.get("step_results")
    if isinstance(supplied_results, (str, bytes)) or not isinstance(
        supplied_results, Sequence
    ):
        raise IntegrityError("M22-EXEC-129 step_results must be a list")
    expected_steps = plan.get("steps")
    if not isinstance(expected_steps, list) or len(supplied_results) != len(expected_steps):
        raise IntegrityError("M22-EXEC-130 step result count must match bounded plan")

    normalized: list[dict[str, Any]] = []
    terminal_status: str | None = None
    stop_step_id: str | None = None
    for supplied, expected_step in zip(supplied_results, expected_steps, strict=True):
        result = _validate_result(
            supplied,
            expected_step=expected_step,
            plan_sha256=plan["plan_sha256"],
        )
        if terminal_status is not None and result["status"] != "skipped_dependency":
            raise IntegrityError(
                "M22-EXEC-131 steps after terminal stop must skip dependency"
            )
        if terminal_status is None and result["status"] in {"failed", "skipped_budget"}:
            terminal_status = result["status"]
            stop_step_id = result["step_id"]
        elif terminal_status is None and result["status"] == "skipped_dependency":
            raise IntegrityError(
                "M22-EXEC-132 dependency skip requires an earlier terminal stop"
            )
        normalized.append(result)

    usage = ExecutionUsage(
        retrievals=sum(item["retrievals_used"] for item in normalized),
        model_calls=sum(item["model_calls_used"] for item in normalized),
        total_tokens=sum(item["tokens_used"] for item in normalized),
        elapsed_ms=sum(item["elapsed_ms"] for item in normalized),
    )
    budget = _require_mapping(plan.get("budget_reservation"), label="budget_reservation")
    limits = {
        "retrievals": budget.get("max_retrievals"),
        "model_calls": budget.get("max_model_calls"),
        "total_tokens": budget.get("max_total_tokens"),
        "elapsed_ms": budget.get("timeout_ms"),
    }
    for field, limit in limits.items():
        value = getattr(usage, field)
        if isinstance(limit, bool) or not isinstance(limit, int) or value > limit:
            raise IntegrityError(f"M22-EXEC-133 execution usage exceeds budget: {field}")

    if terminal_status == "failed":
        outcome = "failed"
        stop_reason = "step_failed"
    elif terminal_status == "skipped_budget":
        outcome = "budget_stopped"
        stop_reason = "budget_exceeded"
    else:
        if any(item["status"] != "completed" for item in normalized):
            raise IntegrityError("M22-EXEC-134 complete trace contains skipped steps")
        outcome = "completed"
        stop_reason = None

    if outcome == "completed":
        final = normalized[-1]
        if final["step_type"] != "verify_acl_provenance_citations":
            raise IntegrityError("M22-EXEC-135 final verification step is missing")
        if not (
            final["acl_passed"]
            and final["provenance_complete"]
            and final["citations_complete"]
        ):
            raise IntegrityError("M22-EXEC-136 final verification did not pass")

    trace_material = {
        "plan_sha256": plan["plan_sha256"],
        "outcome": outcome,
        "stop_step_id": stop_step_id,
        "stop_reason": stop_reason,
        "step_results": normalized,
        "usage": usage.to_dict(),
    }
    return {
        "schema_version": "knowledge-engine-m22-execution-trace/v1",
        "plan_sha256": plan["plan_sha256"],
        "trace_sha256": _canonical_sha256(trace_material),
        "outcome": outcome,
        "stop_step_id": stop_step_id,
        "stop_reason": stop_reason,
        "step_results": normalized,
        "usage": usage.to_dict(),
        "execution_evidence_validated": True,
        "external_execution_performed_by_validator": False,
        "final_answer_generated": False,
        "production_authority": False,
    }


__all__ = [
    "STEP_STATUSES",
    "TRACE_OUTCOMES",
    "ExecutionUsage",
    "validate_bounded_execution_trace",
]
