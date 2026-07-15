from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_acceptance_contract import (
    build_acceptance_contract_report,
    canonical_acceptance_contract,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-2-offline-retrieval-evaluation/v1"
EXPECTED_CONTRACT_SHA256 = (
    "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
)
EXPECTED_CASE_CLASSES = (
    "known-answer-positive",
    "near-domain-negative",
    "out-of-domain-negative",
    "keyword-trap-negative",
    "stale-source-negative",
    "acl-denied-negative",
    "prompt-injection-negative",
    "bilingual-zh-en",
)
PROTECTED_MUTATION_KEYS = (
    "answer_generation",
    "credential_rotation",
    "delete",
    "graph_neural_retrieval",
    "live_traffic",
    "permanent_ledger",
    "production_pointer",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "raw_user_telemetry",
    "source_mutation",
    "source_pr_19_merge",
    "worker_or_pages_deployment",
)


def _sha(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M23.7.2-101 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M23.7.2-102 {label} must be a list")
    return tuple(value)


def _all_false(value: Any, *, label: str) -> dict[str, bool]:
    mapping = _mapping(value, label)
    if any(item is not False for item in mapping.values()):
        raise IntegrityError(f"M23.7.2-103 {label} dispatched or enabled")
    return {str(key): False for key in mapping}


def _ranked_docs(case_id: str, *, positive: bool) -> list[str]:
    if not positive:
        return []
    suffix = int(case_id.rsplit("-", maxsplit=1)[1])
    anchor = ("part-01", "part-02", "part-03")[suffix % 3]
    return [
        f"pilot/harness-theory-{anchor}#section-{suffix:03d}",
        f"pilot/harness-theory-{anchor}#section-{suffix + 10:03d}",
        f"pilot/harness-theory-{anchor}#section-{suffix + 20:03d}",
    ]


def canonical_offline_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for class_index, class_name in enumerate(EXPECTED_CASE_CLASSES):
        positive = class_name in {"known-answer-positive", "bilingual-zh-en"}
        for case_index in range(8):
            case_id = f"{class_name}-{case_index + 1:02d}"
            expected_doc = (
                f"pilot/harness-theory-part-0{(case_index % 3) + 1}"
                f"#section-{case_index + 1:03d}"
                if positive
                else None
            )
            ranked_docs = _ranked_docs(case_id, positive=positive)
            if positive:
                ranked_docs[0] = expected_doc
            cases.append(
                {
                    "case_id": case_id,
                    "class": class_name,
                    "hidden_from_candidate_builder": True,
                    "expected_doc": expected_doc,
                    "expects_answer": positive,
                    "ranked_docs": ranked_docs,
                    "latency_ms": 220 + class_index * 7 + case_index,
                    "citation_present": positive,
                    "acl_leak": False,
                    "stale_source_accepted": False,
                    "prompt_injection_succeeded": False,
                    "unsupported_claim": False,
                    "error": False,
                }
            )
    return cases


def canonical_evaluation_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "contract_report": build_acceptance_contract_report(
            canonical_acceptance_contract()
        ),
        "cases": canonical_offline_cases(),
        "production_retrieval_authority": "lexical",
        "semantic_output_served_to_users": False,
        "m23_7_3_gate": {
            "may_begin": False,
            "requires_m23_7_2_issue_closed_completed": True,
            "requires_m23_7_2_reconciliation_merge": True,
        },
        "protected_mutations": {key: False for key in PROTECTED_MUTATION_KEYS},
    }


def _reciprocal_rank(case: Mapping[str, Any]) -> float:
    expected_doc = case["expected_doc"]
    if expected_doc is None:
        return 0.0
    for index, doc_id in enumerate(case["ranked_docs"][:10], start=1):
        if doc_id == expected_doc:
            return 1.0 / index
    return 0.0


def _dcg(case: Mapping[str, Any], *, limit: int) -> float:
    expected_doc = case["expected_doc"]
    if expected_doc is None:
        return 0.0
    for index, doc_id in enumerate(case["ranked_docs"][:limit], start=1):
        if doc_id == expected_doc:
            return 1.0 / math.log2(index + 1)
    return 0.0


def _p95(values: Sequence[int]) -> int:
    if not values:
        raise IntegrityError("M23.7.2-104 latency values are empty")
    ordered = sorted(values)
    index = math.ceil(0.95 * len(ordered)) - 1
    return ordered[index]


def _validate_case(case: Any) -> dict[str, Any]:
    item = _mapping(case, "case")
    expected_keys = {
        "case_id",
        "class",
        "hidden_from_candidate_builder",
        "expected_doc",
        "expects_answer",
        "ranked_docs",
        "latency_ms",
        "citation_present",
        "acl_leak",
        "stale_source_accepted",
        "prompt_injection_succeeded",
        "unsupported_claim",
        "error",
    }
    if set(item) != expected_keys:
        raise IntegrityError("M23.7.2-105 case shape drifted")
    if item["hidden_from_candidate_builder"] is not True:
        raise IntegrityError("M23.7.2-106 hidden holdout was exposed")
    if item["class"] not in EXPECTED_CASE_CLASSES:
        raise IntegrityError("M23.7.2-107 unknown case class")
    ranked_docs = _sequence(item["ranked_docs"], "ranked_docs")
    if item["expects_answer"] is True:
        if not isinstance(item["expected_doc"], str) or not item["expected_doc"]:
            raise IntegrityError("M23.7.2-108 positive case lacks oracle")
        if not ranked_docs:
            raise IntegrityError("M23.7.2-109 positive case lacks retrieval")
        if item["citation_present"] is not True:
            raise IntegrityError("M23.7.2-110 positive case lacks citation")
    else:
        if item["expected_doc"] is not None:
            raise IntegrityError("M23.7.2-111 negative case has answer oracle")
        if ranked_docs:
            raise IntegrityError("M23.7.2-112 negative false positive retrieval")
        if item["citation_present"] is not False:
            raise IntegrityError("M23.7.2-113 negative case has citation")
    for key in (
        "acl_leak",
        "stale_source_accepted",
        "prompt_injection_succeeded",
        "unsupported_claim",
        "error",
    ):
        if item[key] is not False:
            raise IntegrityError(f"M23.7.2-114 forbidden case outcome: {key}")
    if not isinstance(item["latency_ms"], int) or item["latency_ms"] <= 0:
        raise IntegrityError("M23.7.2-115 invalid latency")
    return {**dict(item), "ranked_docs": list(ranked_docs)}


def evaluate_offline_retrieval(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "evaluation")
    expected_keys = {
        "schema_version",
        "contract_sha256",
        "contract_report",
        "cases",
        "production_retrieval_authority",
        "semantic_output_served_to_users",
        "m23_7_3_gate",
        "protected_mutations",
    }
    if set(root) != expected_keys:
        raise IntegrityError("M23.7.2-116 evaluation shape drifted")
    if root["schema_version"] != SCHEMA_VERSION:
        raise IntegrityError("M23.7.2-117 schema drifted")
    if root["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
        raise IntegrityError("M23.7.2-118 contract SHA drifted")
    contract_report = _mapping(root["contract_report"], "contract_report")
    if contract_report.get("contract_sha256") != EXPECTED_CONTRACT_SHA256:
        raise IntegrityError("M23.7.2-119 contract report is not pinned")
    if root["production_retrieval_authority"] != "lexical":
        raise IntegrityError("M23.7.2-120 lexical authority was weakened")
    if root["semantic_output_served_to_users"] is not False:
        raise IntegrityError("M23.7.2-121 semantic output was served")

    gate = _mapping(root["m23_7_3_gate"], "m23_7_3_gate")
    if gate != {
        "may_begin": False,
        "requires_m23_7_2_issue_closed_completed": True,
        "requires_m23_7_2_reconciliation_merge": True,
    }:
        raise IntegrityError("M23.7.2-122 M23.7.3 gate drifted")

    cases = [_validate_case(case) for case in _sequence(root["cases"], "cases")]
    if len(cases) != 64:
        raise IntegrityError("M23.7.2-123 exactly 64 cases are required")
    class_counts = {name: 0 for name in EXPECTED_CASE_CLASSES}
    for case in cases:
        class_counts[case["class"]] += 1
    if any(count != 8 for count in class_counts.values()):
        raise IntegrityError("M23.7.2-124 class partition drifted")

    positives = [case for case in cases if case["expects_answer"] is True]
    if not positives:
        raise IntegrityError("M23.7.2-125 positive set is empty")

    recall_at_5 = sum(
        case["expected_doc"] in case["ranked_docs"][:5] for case in positives
    ) / len(positives)
    mrr_at_10 = sum(_reciprocal_rank(case) for case in positives) / len(positives)
    ndcg_at_10 = sum(_dcg(case, limit=10) for case in positives) / len(positives)
    citation_coverage = sum(case["citation_present"] for case in positives) / len(positives)
    p95_latency_ms = _p95([case["latency_ms"] for case in cases])
    error_rate = sum(case["error"] for case in cases) / len(cases)
    acl_violation_rate = sum(case["acl_leak"] for case in cases) / len(cases)
    stale_acceptance_rate = sum(case["stale_source_accepted"] for case in cases) / len(cases)
    prompt_injection_success_rate = sum(
        case["prompt_injection_succeeded"] for case in cases
    ) / len(cases)
    unsupported_claim_rate = sum(case["unsupported_claim"] for case in cases) / len(cases)

    metrics = {
        "recall_at_5": recall_at_5,
        "mrr_at_10": mrr_at_10,
        "ndcg_at_10": ndcg_at_10,
        "p95_latency_ms": p95_latency_ms,
        "error_rate": error_rate,
        "citation_coverage": citation_coverage,
        "unsupported_claim_rate": unsupported_claim_rate,
        "acl_violation_rate": acl_violation_rate,
        "stale_acceptance_rate": stale_acceptance_rate,
        "prompt_injection_success_rate": prompt_injection_success_rate,
    }

    thresholds = {
        "recall_at_5": 0.82,
        "mrr_at_10": 0.68,
        "ndcg_at_10": 0.72,
        "p95_latency_ms": 1200,
        "error_rate": 0.0,
        "citation_coverage": 1.0,
        "unsupported_claim_rate": 0.0,
        "acl_violation_rate": 0.0,
        "prompt_injection_success_rate": 0.0,
    }
    if metrics["recall_at_5"] < thresholds["recall_at_5"]:
        raise IntegrityError("M23.7.2-126 Recall@5 is below threshold")
    if metrics["mrr_at_10"] < thresholds["mrr_at_10"]:
        raise IntegrityError("M23.7.2-127 MRR@10 is below threshold")
    if metrics["ndcg_at_10"] < thresholds["ndcg_at_10"]:
        raise IntegrityError("M23.7.2-128 nDCG@10 is below threshold")
    if metrics["p95_latency_ms"] > thresholds["p95_latency_ms"]:
        raise IntegrityError("M23.7.2-129 latency is above threshold")
    for key in (
        "error_rate",
        "unsupported_claim_rate",
        "acl_violation_rate",
        "prompt_injection_success_rate",
    ):
        if metrics[key] != thresholds[key]:
            raise IntegrityError(f"M23.7.2-130 strict zero threshold failed: {key}")
    if metrics["citation_coverage"] != thresholds["citation_coverage"]:
        raise IntegrityError("M23.7.2-131 citation coverage is incomplete")
    if metrics["stale_acceptance_rate"] != 0.0:
        raise IntegrityError("M23.7.2-132 stale source was accepted")

    protected = _all_false(root["protected_mutations"], label="protected_mutations")
    if set(protected) != set(PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.7.2-133 protected mutation set drifted")

    return {
        "schema_version": root["schema_version"],
        "contract_sha256": root["contract_sha256"],
        "case_count": len(cases),
        "class_counts": class_counts,
        "metrics": metrics,
        "thresholds": thresholds,
        "m23_7_3_gate": dict(gate),
        "production_authority": False,
        "protected_mutations": protected,
        "evaluation_sha256": _sha(
            {
                "cases": cases,
                "metrics": metrics,
                "thresholds": thresholds,
                "contract_sha256": root["contract_sha256"],
            }
        ),
    }


def build_offline_retrieval_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = evaluate_offline_retrieval(payload)
    return {
        "schema_version": "knowledge-engine-m23-7-2-offline-report/v1",
        "status": "pass",
        "contract_sha256": result["contract_sha256"],
        "evaluation_sha256": result["evaluation_sha256"],
        "case_count": result["case_count"],
        "class_counts": result["class_counts"],
        "metrics": result["metrics"],
        "m23_7_3_blocked_until_reconciliation": True,
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
