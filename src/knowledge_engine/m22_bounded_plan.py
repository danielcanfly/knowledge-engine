from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import IntegrityError
from .m22_activation_decision import decide_reasoning_activation
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

PLAN_OPERATIONS = (
    "compare",
    "causal_chain",
    "synthesize",
    "temporal_sequence",
    "disambiguate",
)
STEP_TYPES = (
    "retrieve_seed_concepts",
    "expand_typed_relations",
    "retrieve_supporting_evidence",
    "compare_concepts",
    "trace_causal_chain",
    "assemble_synthesis_inputs",
    "order_temporal_evidence",
    "resolve_ambiguity_candidates",
    "verify_acl_provenance_citations",
)
MAX_CONCEPT_REFS = 16
MAX_EVIDENCE_SOURCE_REFS = 16
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    step_type: str
    depends_on: tuple[str, ...]
    input_refs: tuple[str, ...]
    retrievals_reserved: int
    model_calls_reserved: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "depends_on": list(self.depends_on),
            "input_refs": list(self.input_refs),
            "retrievals_reserved": self.retrievals_reserved,
            "model_calls_reserved": self.model_calls_reserved,
        }


@dataclass(frozen=True)
class BoundedPlan:
    operation: str
    policy_sha256: str
    activation_decision_sha256: str
    request_sha256: str
    plan_sha256: str
    steps: tuple[PlanStep, ...]
    budget_reservation: Mapping[str, int]
    planner_constructed: bool
    planner_invocations: int
    execution_started: bool
    model_call_count: int
    production_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-m22-bounded-plan/v1",
            "operation": self.operation,
            "policy_sha256": self.policy_sha256,
            "activation_decision_sha256": self.activation_decision_sha256,
            "request_sha256": self.request_sha256,
            "plan_sha256": self.plan_sha256,
            "steps": [step.to_dict() for step in self.steps],
            "budget_reservation": dict(self.budget_reservation),
            "planner_constructed": self.planner_constructed,
            "planner_invocations": self.planner_invocations,
            "execution_started": self.execution_started,
            "model_call_count": self.model_call_count,
            "production_authority": self.production_authority,
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
        raise IntegrityError(f"M22-PLAN-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-PLAN-102 {label} shape is invalid")


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise IntegrityError(f"M22-PLAN-103 {label} must be boolean")
    return value


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"M22-PLAN-104 {label} must be an integer")
    if value < minimum or value > maximum:
        raise IntegrityError(f"M22-PLAN-105 {label} is outside the governed bound")
    return value


def _require_ref_list(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M22-PLAN-106 {label} must be a list")
    refs = tuple(value)
    if len(refs) < minimum or len(refs) > maximum:
        raise IntegrityError(f"M22-PLAN-107 {label} count is outside the governed bound")
    if any(not isinstance(item, str) or not REF_PATTERN.fullmatch(item) for item in refs):
        raise IntegrityError(f"M22-PLAN-108 {label} contains an invalid reference")
    if len(set(refs)) != len(refs):
        raise IntegrityError(f"M22-PLAN-109 {label} contains duplicates")
    return tuple(sorted(refs))


def _validate_protected_state(payload: Any) -> None:
    state = _require_mapping(payload, label="protected_state")
    if tuple(sorted(state)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-PLAN-110 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if state.get(name) is not False:
            raise IntegrityError(
                f"M22-PLAN-111 protected mutation was dispatched: {name}"
            )


def _validate_decision(
    payload: Any,
    activation_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    supplied = _require_mapping(payload, label="activation_decision")
    expected = decide_reasoning_activation(activation_evidence)
    if dict(supplied) != expected:
        raise IntegrityError("M22-PLAN-112 activation decision does not match evidence")
    if expected.get("disposition") != "activate":
        raise IntegrityError("M22-PLAN-113 activation decision does not permit planning")
    if (
        expected.get("planner_constructed") is not False
        or expected.get("planner_invocations") != 0
        or expected.get("model_call_count") != 0
        or expected.get("production_authority") is not False
    ):
        raise IntegrityError("M22-PLAN-114 activation decision authority is invalid")
    return expected


def _validate_request(payload: Any) -> dict[str, Any]:
    request = _require_mapping(payload, label="plan_request")
    _require_exact_keys(
        request,
        expected={
            "operation",
            "concept_refs",
            "evidence_source_refs",
            "relation_expansion_required",
            "verification_required",
            "estimated_hops",
            "estimated_steps",
            "estimated_retrievals",
            "estimated_model_calls",
            "estimated_total_tokens",
            "estimated_timeout_ms",
        },
        label="plan_request",
    )
    operation = request.get("operation")
    if operation not in PLAN_OPERATIONS:
        raise IntegrityError("M22-PLAN-115 unsupported plan operation")
    concept_refs = _require_ref_list(
        request.get("concept_refs"),
        label="concept_refs",
        minimum=2 if operation == "compare" else 1,
        maximum=MAX_CONCEPT_REFS,
    )
    evidence_refs = _require_ref_list(
        request.get("evidence_source_refs"),
        label="evidence_source_refs",
        minimum=1,
        maximum=MAX_EVIDENCE_SOURCE_REFS,
    )
    relation_required = _require_bool(
        request.get("relation_expansion_required"),
        label="relation_expansion_required",
    )
    verification_required = _require_bool(
        request.get("verification_required"),
        label="verification_required",
    )
    if verification_required is not True:
        raise IntegrityError("M22-PLAN-116 verification cannot be disabled")

    values = {
        "estimated_hops": _require_int(
            request.get("estimated_hops"),
            label="estimated_hops",
            minimum=2,
            maximum=MAX_HOPS,
        ),
        "estimated_steps": _require_int(
            request.get("estimated_steps"),
            label="estimated_steps",
            minimum=1,
            maximum=MAX_STEPS,
        ),
        "estimated_retrievals": _require_int(
            request.get("estimated_retrievals"),
            label="estimated_retrievals",
            minimum=1,
            maximum=MAX_RETRIEVALS,
        ),
        "estimated_model_calls": _require_int(
            request.get("estimated_model_calls"),
            label="estimated_model_calls",
            minimum=0,
            maximum=MAX_MODEL_CALLS,
        ),
        "estimated_total_tokens": _require_int(
            request.get("estimated_total_tokens"),
            label="estimated_total_tokens",
            minimum=0,
            maximum=MAX_TOTAL_TOKENS,
        ),
        "estimated_timeout_ms": _require_int(
            request.get("estimated_timeout_ms"),
            label="estimated_timeout_ms",
            minimum=1,
            maximum=MAX_TIMEOUT_MS,
        ),
    }
    if values["estimated_steps"] < values["estimated_hops"]:
        raise IntegrityError(
            "M22-PLAN-117 estimated_steps must be at least estimated_hops"
        )
    if values["estimated_retrievals"] < values["estimated_hops"]:
        raise IntegrityError(
            "M22-PLAN-118 estimated_retrievals must be at least estimated_hops"
        )
    if operation in {"causal_chain", "temporal_sequence"} and not relation_required:
        raise IntegrityError(
            "M22-PLAN-119 selected operation requires relation expansion"
        )
    return {
        "operation": operation,
        "concept_refs": concept_refs,
        "evidence_source_refs": evidence_refs,
        "relation_expansion_required": relation_required,
        "verification_required": verification_required,
        **values,
    }


def _budget_limits(policy: Mapping[str, Any]) -> Mapping[str, int]:
    return _require_mapping(policy.get("budget"), label="policy budget")


def _validate_budget_fit(
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    activation_evidence: Mapping[str, Any],
) -> None:
    budget = _budget_limits(policy)
    field_map = {
        "estimated_hops": "max_hops",
        "estimated_steps": "max_steps",
        "estimated_retrievals": "max_retrievals",
        "estimated_model_calls": "max_model_calls",
        "estimated_total_tokens": "max_total_tokens",
        "estimated_timeout_ms": "timeout_ms",
    }
    for request_field, policy_field in field_map.items():
        if request[request_field] > budget.get(policy_field, -1):
            raise IntegrityError(
                f"M22-PLAN-120 plan exceeds policy budget: {request_field}"
            )

    activation_features = _require_mapping(
        activation_evidence.get("features"),
        label="activation features",
    )
    for request_field in field_map:
        if request[request_field] > activation_features.get(request_field, -1):
            raise IntegrityError(
                f"M22-PLAN-121 plan exceeds activation estimate: {request_field}"
            )


def _append_step(
    steps: list[PlanStep],
    *,
    step_type: str,
    input_refs: tuple[str, ...],
    retrievals_reserved: int,
    model_calls_reserved: int,
) -> None:
    step_id = f"step-{len(steps) + 1:02d}"
    depends_on = () if not steps else (steps[-1].step_id,)
    steps.append(
        PlanStep(
            step_id=step_id,
            step_type=step_type,
            depends_on=depends_on,
            input_refs=input_refs,
            retrievals_reserved=retrievals_reserved,
            model_calls_reserved=model_calls_reserved,
        )
    )


def _compile_steps(request: Mapping[str, Any]) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = []
    _append_step(
        steps,
        step_type="retrieve_seed_concepts",
        input_refs=request["concept_refs"],
        retrievals_reserved=1,
        model_calls_reserved=0,
    )
    if request["relation_expansion_required"]:
        _append_step(
            steps,
            step_type="expand_typed_relations",
            input_refs=request["concept_refs"],
            retrievals_reserved=1,
            model_calls_reserved=0,
        )
    if request["evidence_source_refs"]:
        _append_step(
            steps,
            step_type="retrieve_supporting_evidence",
            input_refs=request["evidence_source_refs"],
            retrievals_reserved=1,
            model_calls_reserved=0,
        )

    operation_step = {
        "compare": "compare_concepts",
        "causal_chain": "trace_causal_chain",
        "synthesize": "assemble_synthesis_inputs",
        "temporal_sequence": "order_temporal_evidence",
        "disambiguate": "resolve_ambiguity_candidates",
    }[request["operation"]]
    _append_step(
        steps,
        step_type=operation_step,
        input_refs=request["concept_refs"],
        retrievals_reserved=0,
        model_calls_reserved=request["estimated_model_calls"],
    )
    _append_step(
        steps,
        step_type="verify_acl_provenance_citations",
        input_refs=request["evidence_source_refs"],
        retrievals_reserved=0,
        model_calls_reserved=0,
    )
    return tuple(steps)


def _validate_compiled_plan(
    steps: tuple[PlanStep, ...],
    request: Mapping[str, Any],
) -> None:
    if not steps or len(steps) > request["estimated_steps"]:
        raise IntegrityError("M22-PLAN-122 compiled step count exceeds estimate")
    if len(steps) > MAX_STEPS:
        raise IntegrityError("M22-PLAN-123 compiled step count exceeds global bound")
    seen: set[str] = set()
    retrievals = 0
    model_calls = 0
    for step in steps:
        if step.step_type not in STEP_TYPES:
            raise IntegrityError("M22-PLAN-124 compiled step type is not governed")
        if step.step_id in seen:
            raise IntegrityError("M22-PLAN-125 duplicate compiled step ID")
        if any(dependency not in seen for dependency in step.depends_on):
            raise IntegrityError("M22-PLAN-126 plan dependency is not forward-safe")
        seen.add(step.step_id)
        retrievals += step.retrievals_reserved
        model_calls += step.model_calls_reserved
    if retrievals > request["estimated_retrievals"]:
        raise IntegrityError("M22-PLAN-127 compiled retrieval reservation exceeds estimate")
    if model_calls > request["estimated_model_calls"]:
        raise IntegrityError("M22-PLAN-128 compiled model-call reservation exceeds estimate")
    if steps[-1].step_type != "verify_acl_provenance_citations":
        raise IntegrityError("M22-PLAN-129 final verification step is required")


def compile_bounded_reasoning_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="bounded planning evidence")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "policy",
            "activation_evidence",
            "activation_decision",
            "plan_request",
            "protected_state",
        },
        label="bounded planning evidence",
    )
    if root.get("schema_version") != "knowledge-engine-m22-plan-evidence/v1":
        raise IntegrityError("M22-PLAN-130 unsupported planning evidence schema")

    policy = _require_mapping(root.get("policy"), label="policy")
    policy_report = validate_reasoning_mode_policy(policy)
    if policy_report.get("mode") == "off":
        raise IntegrityError("M22-PLAN-131 off mode cannot construct a plan")

    activation_evidence = _require_mapping(
        root.get("activation_evidence"),
        label="activation_evidence",
    )
    if dict(activation_evidence.get("policy", {})) != dict(policy):
        raise IntegrityError("M22-PLAN-132 activation evidence policy mismatch")
    decision = _validate_decision(
        root.get("activation_decision"),
        activation_evidence,
    )
    request = _validate_request(root.get("plan_request"))
    _validate_protected_state(root.get("protected_state"))
    _validate_budget_fit(request, policy, activation_evidence)

    steps = _compile_steps(request)
    _validate_compiled_plan(steps, request)
    request_sha256 = _canonical_sha256(request)
    budget_reservation = {
        "max_hops": request["estimated_hops"],
        "max_steps": len(steps),
        "max_retrievals": sum(step.retrievals_reserved for step in steps),
        "max_model_calls": sum(step.model_calls_reserved for step in steps),
        "max_total_tokens": request["estimated_total_tokens"],
        "timeout_ms": request["estimated_timeout_ms"],
    }
    plan_material = {
        "operation": request["operation"],
        "policy_sha256": policy_report["policy_sha256"],
        "activation_decision_sha256": decision["decision_sha256"],
        "request_sha256": request_sha256,
        "steps": [step.to_dict() for step in steps],
        "budget_reservation": budget_reservation,
    }
    plan = BoundedPlan(
        operation=request["operation"],
        policy_sha256=policy_report["policy_sha256"],
        activation_decision_sha256=decision["decision_sha256"],
        request_sha256=request_sha256,
        plan_sha256=_canonical_sha256(plan_material),
        steps=steps,
        budget_reservation=budget_reservation,
        planner_constructed=True,
        planner_invocations=1,
        execution_started=False,
        model_call_count=0,
        production_authority=False,
    )
    return plan.to_dict()


__all__ = [
    "MAX_CONCEPT_REFS",
    "MAX_EVIDENCE_SOURCE_REFS",
    "PLAN_OPERATIONS",
    "STEP_TYPES",
    "BoundedPlan",
    "PlanStep",
    "compile_bounded_reasoning_plan",
]
