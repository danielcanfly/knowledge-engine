from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m22_grounded_answer import (
    ANSWER_DISPOSITIONS,
    FALLBACK_REASONS,
    validate_grounded_answer_package,
)
from .m22_reasoning_modes import PROTECTED_MUTATION_KEYS

RECOMMENDATIONS = ("promote_candidate", "hold", "reject")
CASE_ID_PATTERN = re.compile(r"^case-[0-9]{2}$")
CASE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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
        raise IntegrityError(f"M22-EVAL-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-EVAL-102 {label} shape is invalid")


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntegrityError(f"M22-EVAL-103 {label} must be an integer")
    if value < minimum or value > maximum:
        raise IntegrityError(f"M22-EVAL-104 {label} is outside the governed bound")
    return value


def _require_sequence(value: Any, *, label: str, maximum: int) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M22-EVAL-105 {label} must be a list")
    items = tuple(value)
    if len(items) > maximum:
        raise IntegrityError(f"M22-EVAL-106 {label} exceeds the governed bound")
    return items


def _require_sha_list(
    value: Any,
    *,
    label: str,
    maximum: int = 32,
) -> tuple[str, ...]:
    items = _require_sequence(value, label=label, maximum=maximum)
    if any(not isinstance(item, str) or not SHA256_PATTERN.fullmatch(item) for item in items):
        raise IntegrityError(f"M22-EVAL-107 {label} contains an invalid SHA-256")
    if len(set(items)) != len(items):
        raise IntegrityError(f"M22-EVAL-108 {label} contains duplicates")
    return items


def _validate_protected_state(payload: Any) -> None:
    state = _require_mapping(payload, label="protected_state")
    if tuple(sorted(state)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-EVAL-109 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if state.get(name) is not False:
            raise IntegrityError(
                f"M22-EVAL-110 protected mutation was dispatched: {name}"
            )


def _validate_variant(payload: Any, *, label: str) -> dict[str, Any]:
    variant = _require_mapping(payload, label=label)
    _require_exact_keys(
        variant,
        expected={"answer_evidence", "grounded_package"},
        label=label,
    )
    answer_evidence = _require_mapping(
        variant.get("answer_evidence"),
        label=f"{label}.answer_evidence",
    )
    package = _require_mapping(
        variant.get("grounded_package"),
        label=f"{label}.grounded_package",
    )
    expected = validate_grounded_answer_package(answer_evidence)
    if dict(package) != expected:
        raise IntegrityError(f"M22-EVAL-111 {label} package does not match evidence")
    if package.get("schema_version") != (
        "knowledge-engine-m22-grounded-answer-package/v1"
    ):
        raise IntegrityError(f"M22-EVAL-112 {label} package schema is unsupported")
    if (
        package.get("answer_evidence_validated") is not True
        or package.get("answer_content_generated_by_validator") is not False
        or package.get("provider_call_performed") is not False
        or package.get("production_authority") is not False
    ):
        raise IntegrityError(f"M22-EVAL-113 {label} package authority is invalid")

    execution_trace = _require_mapping(
        answer_evidence.get("execution_trace"),
        label=f"{label}.execution_trace",
    )
    usage = _require_mapping(
        execution_trace.get("usage"),
        label=f"{label}.execution_trace.usage",
    )
    normalized_usage = {
        "total_tokens": _require_int(
            usage.get("total_tokens"),
            label=f"{label}.total_tokens",
            minimum=0,
            maximum=1_000_000,
        ),
        "model_calls": _require_int(
            usage.get("model_calls"),
            label=f"{label}.model_calls",
            minimum=0,
            maximum=1000,
        ),
        "elapsed_ms": _require_int(
            usage.get("elapsed_ms"),
            label=f"{label}.elapsed_ms",
            minimum=0,
            maximum=3_600_000,
        ),
    }
    return {
        "package": dict(package),
        "usage": normalized_usage,
    }


def _validate_rubric(payload: Any) -> dict[str, Any]:
    rubric = _require_mapping(payload, label="rubric")
    _require_exact_keys(
        rubric,
        expected={
            "expected_disposition",
            "expected_fallback_reason",
            "required_claim_sha256s",
            "forbidden_claim_sha256s",
            "min_citations",
            "max_total_tokens",
            "max_model_calls",
            "max_elapsed_ms",
        },
        label="rubric",
    )
    expected_disposition = rubric.get("expected_disposition")
    if expected_disposition not in ANSWER_DISPOSITIONS:
        raise IntegrityError("M22-EVAL-114 expected disposition is invalid")
    fallback_reason = rubric.get("expected_fallback_reason")
    if expected_disposition == "answered":
        if fallback_reason is not None:
            raise IntegrityError(
                "M22-EVAL-115 answered rubric cannot require fallback reason"
            )
    elif fallback_reason not in FALLBACK_REASONS:
        raise IntegrityError("M22-EVAL-116 fallback rubric reason is invalid")

    required = _require_sha_list(
        rubric.get("required_claim_sha256s"),
        label="required_claim_sha256s",
    )
    forbidden = _require_sha_list(
        rubric.get("forbidden_claim_sha256s"),
        label="forbidden_claim_sha256s",
    )
    if set(required).intersection(forbidden):
        raise IntegrityError("M22-EVAL-117 required and forbidden claims overlap")

    min_citations = _require_int(
        rubric.get("min_citations"),
        label="min_citations",
        minimum=0,
        maximum=32,
    )
    if expected_disposition == "fallback" and min_citations != 0:
        raise IntegrityError("M22-EVAL-118 fallback rubric cannot require citations")
    return {
        "expected_disposition": expected_disposition,
        "expected_fallback_reason": fallback_reason,
        "required_claim_sha256s": list(required),
        "forbidden_claim_sha256s": list(forbidden),
        "min_citations": min_citations,
        "max_total_tokens": _require_int(
            rubric.get("max_total_tokens"),
            label="max_total_tokens",
            minimum=0,
            maximum=1_000_000,
        ),
        "max_model_calls": _require_int(
            rubric.get("max_model_calls"),
            label="max_model_calls",
            minimum=0,
            maximum=1000,
        ),
        "max_elapsed_ms": _require_int(
            rubric.get("max_elapsed_ms"),
            label="max_elapsed_ms",
            minimum=0,
            maximum=3_600_000,
        ),
    }


def _score_variant(
    variant: Mapping[str, Any],
    rubric: Mapping[str, Any],
) -> dict[str, Any]:
    package = _require_mapping(variant.get("package"), label="package")
    usage = _require_mapping(variant.get("usage"), label="usage")
    disposition_correct = package.get("disposition") == rubric["expected_disposition"]
    fallback_correct = (
        package.get("fallback_reason") == rubric["expected_fallback_reason"]
    )
    claim_hashes = {
        claim.get("claim_sha256")
        for claim in package.get("claims", [])
        if isinstance(claim, Mapping)
    }
    required = set(rubric["required_claim_sha256s"])
    forbidden = set(rubric["forbidden_claim_sha256s"])
    required_covered = required.issubset(claim_hashes)
    forbidden_absent = not claim_hashes.intersection(forbidden)
    citations_sufficient = len(package.get("citations", [])) >= rubric["min_citations"]
    cost_compliant = (
        usage["total_tokens"] <= rubric["max_total_tokens"]
        and usage["model_calls"] <= rubric["max_model_calls"]
        and usage["elapsed_ms"] <= rubric["max_elapsed_ms"]
    )

    score = 0
    score += 25 if disposition_correct else 0
    score += 10 if fallback_correct else 0
    score += 25 if required_covered else 0
    score += 15 if forbidden_absent else 0
    score += 15 if citations_sufficient else 0
    score += 10 if cost_compliant else 0
    passed = all(
        (
            disposition_correct,
            fallback_correct,
            required_covered,
            forbidden_absent,
            citations_sufficient,
            cost_compliant,
        )
    )
    return {
        "package_sha256": package["package_sha256"],
        "score": score,
        "passed": passed,
        "disposition_correct": disposition_correct,
        "fallback_correct": fallback_correct,
        "required_claims_covered": required_covered,
        "forbidden_claims_absent": forbidden_absent,
        "citations_sufficient": citations_sufficient,
        "cost_compliant": cost_compliant,
        "usage": dict(usage),
    }


def _validate_case(payload: Any, *, expected_index: int) -> dict[str, Any]:
    case = _require_mapping(payload, label="evaluation_case")
    _require_exact_keys(
        case,
        expected={"case_id", "case_key", "rubric", "baseline", "candidate"},
        label="evaluation_case",
    )
    case_id = case.get("case_id")
    expected_case_id = f"case-{expected_index:02d}"
    if case_id != expected_case_id or not CASE_ID_PATTERN.fullmatch(str(case_id)):
        raise IntegrityError("M22-EVAL-119 case IDs must be sequential")
    case_key = case.get("case_key")
    if not isinstance(case_key, str) or not CASE_KEY_PATTERN.fullmatch(case_key):
        raise IntegrityError("M22-EVAL-120 case key is invalid")

    rubric = _validate_rubric(case.get("rubric"))
    baseline = _validate_variant(case.get("baseline"), label="baseline")
    candidate = _validate_variant(case.get("candidate"), label="candidate")
    baseline_score = _score_variant(baseline, rubric)
    candidate_score = _score_variant(candidate, rubric)
    regression = baseline_score["passed"] and not candidate_score["passed"]
    regression = regression or candidate_score["score"] < baseline_score["score"]
    return {
        "case_id": case_id,
        "case_key": case_key,
        "rubric_sha256": _canonical_sha256(rubric),
        "baseline": baseline_score,
        "candidate": candidate_score,
        "quality_gain": candidate_score["score"] - baseline_score["score"],
        "regression": regression,
    }


def evaluate_controlled_variants(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="evaluation evidence")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "suite_id",
            "minimum_quality_gain",
            "cases",
            "protected_state",
        },
        label="evaluation evidence",
    )
    if root.get("schema_version") != "knowledge-engine-m22-evaluation-evidence/v1":
        raise IntegrityError("M22-EVAL-121 unsupported evaluation evidence schema")
    suite_id = root.get("suite_id")
    if not isinstance(suite_id, str) or not CASE_KEY_PATTERN.fullmatch(suite_id):
        raise IntegrityError("M22-EVAL-122 suite ID is invalid")
    minimum_quality_gain = _require_int(
        root.get("minimum_quality_gain"),
        label="minimum_quality_gain",
        minimum=0,
        maximum=100,
    )
    _validate_protected_state(root.get("protected_state"))

    cases_raw = _require_sequence(root.get("cases"), label="cases", maximum=64)
    if not cases_raw:
        raise IntegrityError("M22-EVAL-123 evaluation suite cannot be empty")
    cases = [
        _validate_case(item, expected_index=index)
        for index, item in enumerate(cases_raw, start=1)
    ]
    keys = [item["case_key"] for item in cases]
    if len(set(keys)) != len(keys):
        raise IntegrityError("M22-EVAL-124 case keys must be unique")

    baseline_score = sum(item["baseline"]["score"] for item in cases)
    candidate_score = sum(item["candidate"]["score"] for item in cases)
    case_count = len(cases)
    baseline_average = baseline_score // case_count
    candidate_average = candidate_score // case_count
    quality_gain = candidate_average - baseline_average
    candidate_all_passed = all(item["candidate"]["passed"] for item in cases)
    any_regression = any(item["regression"] for item in cases)

    reason_codes: list[str] = []
    if not candidate_all_passed:
        reason_codes.append("candidate_case_failed")
    if any_regression:
        reason_codes.append("baseline_regression")
    if candidate_all_passed and not any_regression:
        if quality_gain >= minimum_quality_gain:
            recommendation = "promote_candidate"
            reason_codes.append("quality_gain_reached")
        else:
            recommendation = "hold"
            reason_codes.append("quality_gain_below_threshold")
    else:
        recommendation = "reject"

    aggregate = {
        "case_count": case_count,
        "baseline_average_score": baseline_average,
        "candidate_average_score": candidate_average,
        "quality_gain": quality_gain,
        "minimum_quality_gain": minimum_quality_gain,
        "candidate_all_passed": candidate_all_passed,
        "any_regression": any_regression,
        "baseline_usage": {
            field: sum(item["baseline"]["usage"][field] for item in cases)
            for field in ("total_tokens", "model_calls", "elapsed_ms")
        },
        "candidate_usage": {
            field: sum(item["candidate"]["usage"][field] for item in cases)
            for field in ("total_tokens", "model_calls", "elapsed_ms")
        },
    }
    evaluation_material = {
        "suite_id": suite_id,
        "cases": cases,
        "aggregate": aggregate,
        "recommendation": recommendation,
        "reason_codes": reason_codes,
    }
    return {
        "schema_version": "knowledge-engine-m22-offline-evaluation/v1",
        "suite_id": suite_id,
        "evaluation_sha256": _canonical_sha256(evaluation_material),
        "cases": cases,
        "aggregate": aggregate,
        "recommendation": recommendation,
        "reason_codes": reason_codes,
        "evaluation_only": True,
        "rollout_performed": False,
        "traffic_changed": False,
        "production_authority": False,
    }


__all__ = [
    "RECOMMENDATIONS",
    "evaluate_controlled_variants",
]
