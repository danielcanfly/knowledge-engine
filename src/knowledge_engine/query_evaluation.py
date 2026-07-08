from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryEvaluationPolicy:
    """Deterministic runtime query evaluation thresholds."""

    min_selected_for_answer: int = 1
    min_citation_coverage: float = 1.0
    raw_fallback_allowed: bool = False


def _stable_json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _citation_count(results: list[dict[str, Any]]) -> int:
    return sum(len(result.get("citations", [])) for result in results)


def _citation_coverage(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    cited = sum(1 for result in results if result.get("citations"))
    return cited / len(results)


def evaluate_runtime_query(
    *,
    release: dict[str, Any],
    query: str,
    audiences: set[str],
    status: str,
    results: list[dict[str, Any]],
    retrieval: dict[str, Any],
    non_answer_reason: str | None,
    policy: QueryEvaluationPolicy | None = None,
) -> dict[str, Any]:
    """Return deterministic machine-verifiable evaluation evidence for one query.

    The evaluator only consumes already ACL-filtered results. It does not inspect hidden
    candidates, raw evidence, or canonical Source, so evaluation evidence cannot broaden
    the caller's audience.
    """

    effective_policy = policy or QueryEvaluationPolicy()
    selected_count = int(retrieval.get("selected_count", len(results)))
    candidate_count = int(retrieval.get("candidate_count", 0))
    acl_filtered_count = int(retrieval.get("acl_filtered_count", 0))
    raw_fallback_used = bool(retrieval.get("raw_fallback_used", False))
    citation_count = _citation_count(results)
    citation_coverage = _citation_coverage(results)

    reasons: list[str] = []
    if raw_fallback_used and not effective_policy.raw_fallback_allowed:
        reasons.append("raw_fallback_disallowed")
    if status == "answered" and selected_count < effective_policy.min_selected_for_answer:
        reasons.append("insufficient_selected_results")
    if status == "answered" and citation_coverage < effective_policy.min_citation_coverage:
        reasons.append("insufficient_citation_coverage")
    if status != "answered" and non_answer_reason:
        reasons.append(non_answer_reason)
    if status == "not_found" and candidate_count == 0:
        reasons.append("no_retrieval_candidates")

    reasons = sorted(set(reasons))
    passed = not reasons
    metrics = {
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "citation_count": citation_count,
        "citation_coverage": round(citation_coverage, 6),
        "acl_filtered_count": acl_filtered_count,
        "raw_fallback_used": raw_fallback_used,
    }
    identity_payload = {
        "release": {
            "release_id": release["release_id"],
            "manifest_sha256": release["manifest_sha256"],
        },
        "query": query,
        "audiences": sorted(audiences),
        "status": status,
        "metrics": metrics,
        "reasons": reasons,
        "policy": {
            "min_selected_for_answer": effective_policy.min_selected_for_answer,
            "min_citation_coverage": effective_policy.min_citation_coverage,
            "raw_fallback_allowed": effective_policy.raw_fallback_allowed,
        },
    }
    evaluation_id = "qeval_" + hashlib.sha256(_stable_json(identity_payload)).hexdigest()[:32]
    return {
        "schema_version": "1.0",
        "evaluation_id": evaluation_id,
        "passed": passed,
        "release_blocking": not passed,
        "reasons": reasons,
        "metrics": metrics,
        "policy": identity_payload["policy"],
    }
