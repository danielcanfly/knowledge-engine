from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m22_execution_trace import validate_bounded_execution_trace
from .m22_reasoning_modes import PROTECTED_MUTATION_KEYS

ANSWER_DISPOSITIONS = ("answered", "fallback")
FALLBACK_REASONS = (
    "reasoning_failed",
    "budget_exceeded",
    "insufficient_evidence",
    "citation_incomplete",
    "acl_blocked",
    "not_found",
    "direct_answer_preserved",
)
AUDIENCES = ("public", "internal", "restricted")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
CLAIM_ID_PATTERN = re.compile(r"^claim-[0-9]{2}$")
CITATION_ID_PATTERN = re.compile(r"^citation-[0-9]{2}$")
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
        raise IntegrityError(f"M22-ANSWER-101 {label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M22-ANSWER-102 {label} shape is invalid")


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise IntegrityError(f"M22-ANSWER-103 {label} must be boolean")
    return value


def _require_sequence(value: Any, *, label: str, maximum: int) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M22-ANSWER-104 {label} must be a list")
    items = tuple(value)
    if len(items) > maximum:
        raise IntegrityError(f"M22-ANSWER-105 {label} exceeds the governed bound")
    return items


def _require_refs(
    value: Any,
    *,
    label: str,
    maximum: int = 32,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    refs = _require_sequence(value, label=label, maximum=maximum)
    if require_nonempty and not refs:
        raise IntegrityError(f"M22-ANSWER-106 {label} cannot be empty")
    if any(not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref) for ref in refs):
        raise IntegrityError(f"M22-ANSWER-107 {label} contains an invalid reference")
    if len(set(refs)) != len(refs):
        raise IntegrityError(f"M22-ANSWER-108 {label} contains duplicates")
    return refs


def _require_sha(value: Any, *, label: str, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise IntegrityError(f"M22-ANSWER-109 {label} must be a lowercase SHA-256")
    return value


def _validate_protected_state(payload: Any) -> None:
    state = _require_mapping(payload, label="protected_state")
    if tuple(sorted(state)) != tuple(sorted(PROTECTED_MUTATION_KEYS)):
        raise IntegrityError("M22-ANSWER-110 protected-state evidence is incomplete")
    for name in PROTECTED_MUTATION_KEYS:
        if state.get(name) is not False:
            raise IntegrityError(
                f"M22-ANSWER-111 protected mutation was dispatched: {name}"
            )


def _extract_expected_audience(execution_evidence: Mapping[str, Any]) -> str:
    planning = _require_mapping(
        execution_evidence.get("planning_evidence"),
        label="planning_evidence",
    )
    policy = _require_mapping(planning.get("policy"), label="policy")
    audience = policy.get("audience")
    if audience not in AUDIENCES:
        raise IntegrityError("M22-ANSWER-112 policy audience is invalid")
    return audience


def _validate_execution_trace(
    execution_evidence: Mapping[str, Any],
    supplied_trace: Any,
) -> dict[str, Any]:
    trace = _require_mapping(supplied_trace, label="execution_trace")
    expected = validate_bounded_execution_trace(execution_evidence)
    if dict(trace) != expected:
        raise IntegrityError(
            "M22-ANSWER-113 execution trace does not match execution evidence"
        )
    if trace.get("schema_version") != "knowledge-engine-m22-execution-trace/v1":
        raise IntegrityError("M22-ANSWER-114 unsupported execution trace schema")
    if (
        trace.get("execution_evidence_validated") is not True
        or trace.get("external_execution_performed_by_validator") is not False
        or trace.get("final_answer_generated") is not False
        or trace.get("production_authority") is not False
    ):
        raise IntegrityError("M22-ANSWER-115 execution trace authority is invalid")
    return dict(trace)


def _available_output_refs(trace: Mapping[str, Any]) -> set[str]:
    results = _require_sequence(
        trace.get("step_results"),
        label="step_results",
        maximum=64,
    )
    available: set[str] = set()
    for item in results:
        result = _require_mapping(item, label="step_result")
        if result.get("status") != "completed":
            continue
        refs = _require_refs(result.get("output_refs"), label="output_refs")
        available.update(refs)
    return available


def _validate_citation(
    payload: Any,
    *,
    expected_audience: str,
    available_refs: set[str],
) -> dict[str, Any]:
    citation = _require_mapping(payload, label="citation")
    _require_exact_keys(
        citation,
        expected={
            "citation_id",
            "source_ref",
            "evidence_refs",
            "audience",
            "acl_passed",
            "provenance_complete",
        },
        label="citation",
    )
    citation_id = citation.get("citation_id")
    if not isinstance(citation_id, str) or not CITATION_ID_PATTERN.fullmatch(citation_id):
        raise IntegrityError("M22-ANSWER-116 citation ID is invalid")
    source_ref = citation.get("source_ref")
    if not isinstance(source_ref, str) or not REF_PATTERN.fullmatch(source_ref):
        raise IntegrityError("M22-ANSWER-117 citation source reference is invalid")
    evidence_refs = _require_refs(
        citation.get("evidence_refs"),
        label="citation evidence_refs",
        require_nonempty=True,
    )
    if not set(evidence_refs).issubset(available_refs):
        raise IntegrityError("M22-ANSWER-118 citation evidence is outside the trace")
    if citation.get("audience") != expected_audience:
        raise IntegrityError("M22-ANSWER-119 citation audience does not match policy")
    acl_passed = _require_bool(citation.get("acl_passed"), label="citation acl_passed")
    provenance_complete = _require_bool(
        citation.get("provenance_complete"),
        label="citation provenance_complete",
    )
    if not acl_passed or not provenance_complete:
        raise IntegrityError("M22-ANSWER-120 citation verification is incomplete")
    return {
        "citation_id": citation_id,
        "source_ref": source_ref,
        "evidence_refs": list(evidence_refs),
        "audience": expected_audience,
        "acl_passed": True,
        "provenance_complete": True,
    }


def _validate_claim(
    payload: Any,
    *,
    available_refs: set[str],
    citation_ids: set[str],
) -> dict[str, Any]:
    claim = _require_mapping(payload, label="claim")
    _require_exact_keys(
        claim,
        expected={
            "claim_id",
            "claim_sha256",
            "evidence_refs",
            "citation_ids",
            "acl_passed",
            "provenance_complete",
            "supported",
        },
        label="claim",
    )
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not CLAIM_ID_PATTERN.fullmatch(claim_id):
        raise IntegrityError("M22-ANSWER-121 claim ID is invalid")
    claim_sha256 = _require_sha(claim.get("claim_sha256"), label="claim_sha256")
    evidence_refs = _require_refs(
        claim.get("evidence_refs"),
        label="claim evidence_refs",
        require_nonempty=True,
    )
    if not set(evidence_refs).issubset(available_refs):
        raise IntegrityError("M22-ANSWER-122 claim evidence is outside the trace")
    linked_citations = _require_refs(
        claim.get("citation_ids"),
        label="claim citation_ids",
        require_nonempty=True,
    )
    if not set(linked_citations).issubset(citation_ids):
        raise IntegrityError("M22-ANSWER-123 claim references an unknown citation")
    acl_passed = _require_bool(claim.get("acl_passed"), label="claim acl_passed")
    provenance_complete = _require_bool(
        claim.get("provenance_complete"),
        label="claim provenance_complete",
    )
    supported = _require_bool(claim.get("supported"), label="claim supported")
    if not acl_passed or not provenance_complete or not supported:
        raise IntegrityError("M22-ANSWER-124 claim grounding is incomplete")
    return {
        "claim_id": claim_id,
        "claim_sha256": claim_sha256,
        "evidence_refs": list(evidence_refs),
        "citation_ids": list(linked_citations),
        "acl_passed": True,
        "provenance_complete": True,
        "supported": True,
    }


def _validate_answered_candidate(
    candidate: Mapping[str, Any],
    *,
    trace: Mapping[str, Any],
    expected_audience: str,
    available_refs: set[str],
) -> dict[str, Any]:
    if trace.get("outcome") != "completed":
        raise IntegrityError("M22-ANSWER-125 answered candidate requires completed trace")
    if candidate.get("fallback_reason") is not None:
        raise IntegrityError("M22-ANSWER-126 answered candidate cannot have fallback reason")
    answer_sha256 = _require_sha(candidate.get("answer_sha256"), label="answer_sha256")
    citations_raw = _require_sequence(
        candidate.get("citations"),
        label="citations",
        maximum=32,
    )
    claims_raw = _require_sequence(
        candidate.get("claims"),
        label="claims",
        maximum=32,
    )
    if not citations_raw or not claims_raw:
        raise IntegrityError("M22-ANSWER-127 answered candidate requires claims and citations")

    citations = [
        _validate_citation(
            item,
            expected_audience=expected_audience,
            available_refs=available_refs,
        )
        for item in citations_raw
    ]
    citation_ids = [item["citation_id"] for item in citations]
    if len(set(citation_ids)) != len(citation_ids):
        raise IntegrityError("M22-ANSWER-128 citation IDs must be unique")
    if citation_ids != [f"citation-{index:02d}" for index in range(1, len(citations) + 1)]:
        raise IntegrityError("M22-ANSWER-129 citation IDs must be sequential")

    claims = [
        _validate_claim(
            item,
            available_refs=available_refs,
            citation_ids=set(citation_ids),
        )
        for item in claims_raw
    ]
    claim_ids = [item["claim_id"] for item in claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise IntegrityError("M22-ANSWER-130 claim IDs must be unique")
    if claim_ids != [f"claim-{index:02d}" for index in range(1, len(claims) + 1)]:
        raise IntegrityError("M22-ANSWER-131 claim IDs must be sequential")

    claim_order = _require_refs(
        candidate.get("claim_order"),
        label="claim_order",
        maximum=32,
        require_nonempty=True,
    )
    if list(claim_order) != claim_ids:
        raise IntegrityError("M22-ANSWER-132 claim order does not match claims")
    used_citations = {
        citation_id for claim in claims for citation_id in claim["citation_ids"]
    }
    if used_citations != set(citation_ids):
        raise IntegrityError("M22-ANSWER-133 every citation must support a claim")

    return {
        "disposition": "answered",
        "audience": expected_audience,
        "answer_sha256": answer_sha256,
        "claim_order": list(claim_order),
        "claims": claims,
        "citations": citations,
        "fallback_reason": None,
    }


def _validate_fallback_candidate(
    candidate: Mapping[str, Any],
    *,
    trace: Mapping[str, Any],
    expected_audience: str,
) -> dict[str, Any]:
    if candidate.get("answer_sha256") is not None:
        raise IntegrityError("M22-ANSWER-134 fallback cannot contain answer identity")
    if candidate.get("claims") != [] or candidate.get("citations") != []:
        raise IntegrityError("M22-ANSWER-135 fallback cannot contain claims or citations")
    if candidate.get("claim_order") != []:
        raise IntegrityError("M22-ANSWER-136 fallback cannot contain claim order")
    reason = candidate.get("fallback_reason")
    if reason not in FALLBACK_REASONS:
        raise IntegrityError("M22-ANSWER-137 fallback reason is invalid")

    outcome = trace.get("outcome")
    required = {
        "failed": "reasoning_failed",
        "budget_stopped": "budget_exceeded",
    }.get(outcome)
    if required is not None and reason != required:
        raise IntegrityError("M22-ANSWER-138 fallback reason does not match trace outcome")
    if outcome == "completed" and reason in {"reasoning_failed", "budget_exceeded"}:
        raise IntegrityError("M22-ANSWER-139 completed trace has invalid fallback reason")

    return {
        "disposition": "fallback",
        "audience": expected_audience,
        "answer_sha256": None,
        "claim_order": [],
        "claims": [],
        "citations": [],
        "fallback_reason": reason,
    }


def validate_grounded_answer_package(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _require_mapping(payload, label="answer evidence")
    _require_exact_keys(
        root,
        expected={
            "schema_version",
            "execution_evidence",
            "execution_trace",
            "answer_candidate",
            "protected_state",
        },
        label="answer evidence",
    )
    if root.get("schema_version") != "knowledge-engine-m22-answer-evidence/v1":
        raise IntegrityError("M22-ANSWER-140 unsupported answer evidence schema")

    execution_evidence = _require_mapping(
        root.get("execution_evidence"),
        label="execution_evidence",
    )
    trace = _validate_execution_trace(
        execution_evidence,
        root.get("execution_trace"),
    )
    _validate_protected_state(root.get("protected_state"))
    expected_audience = _extract_expected_audience(execution_evidence)
    available_refs = _available_output_refs(trace)

    candidate = _require_mapping(root.get("answer_candidate"), label="answer_candidate")
    _require_exact_keys(
        candidate,
        expected={
            "disposition",
            "audience",
            "answer_sha256",
            "claim_order",
            "claims",
            "citations",
            "fallback_reason",
        },
        label="answer_candidate",
    )
    if candidate.get("audience") != expected_audience:
        raise IntegrityError("M22-ANSWER-141 answer audience does not match policy")

    disposition = candidate.get("disposition")
    if disposition not in ANSWER_DISPOSITIONS:
        raise IntegrityError("M22-ANSWER-142 answer disposition is invalid")
    if disposition == "answered":
        normalized = _validate_answered_candidate(
            candidate,
            trace=trace,
            expected_audience=expected_audience,
            available_refs=available_refs,
        )
    else:
        normalized = _validate_fallback_candidate(
            candidate,
            trace=trace,
            expected_audience=expected_audience,
        )

    package_material = {
        "trace_sha256": trace["trace_sha256"],
        "candidate": normalized,
    }
    return {
        "schema_version": "knowledge-engine-m22-grounded-answer-package/v1",
        "trace_sha256": trace["trace_sha256"],
        "package_sha256": _canonical_sha256(package_material),
        **normalized,
        "answer_evidence_validated": True,
        "answer_content_generated_by_validator": False,
        "provider_call_performed": False,
        "production_authority": False,
    }


__all__ = [
    "ANSWER_DISPOSITIONS",
    "AUDIENCES",
    "FALLBACK_REASONS",
    "validate_grounded_answer_package",
]
