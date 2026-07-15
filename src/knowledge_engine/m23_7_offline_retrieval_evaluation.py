from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_quality_contract import canonical_contract, validate_contract


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ranked(case: Mapping[str, Any], *, candidate: bool) -> list[dict[str, Any]]:
    if case["no_answer_expected"] or not case["acl_allowed"]:
        return []
    relevant = case["expected_relevant_ids"][0]
    index = int(str(case["case_id"]).split("-")[-1])
    relevant_rank = 1 if candidate or index % 4 else 2
    rows = []
    for rank in range(1, 6):
        section_id = (
            relevant if rank == relevant_rank else f"distractor-{index:02d}-{rank}"
        )
        rows.append(
            {
                "section_id": section_id,
                "rank": rank,
                "score": round(
                    1.0 - (rank * 0.1) + (0.01 if candidate else 0.0),
                    6,
                ),
                "provenance_present": True,
                "acl_allowed": True,
            }
        )
    return rows


def canonical_evidence() -> dict[str, Any]:
    contract = validate_contract(canonical_contract())
    cases = []
    for case in contract["suite"]["cases"]:
        cases.append(
            {
                "case_id": case["case_id"],
                "query_class": case["query_class"],
                "expected_relevant_ids": case["expected_relevant_ids"],
                "acl_allowed": case["acl_allowed"],
                "no_answer_expected": case["no_answer_expected"],
                "lexical": _ranked(case, candidate=False),
                "candidate": _ranked(case, candidate=True),
                "failure_reasons": [],
            }
        )
    evidence = {
        "schema_version": "knowledge-engine-m23-offline-retrieval-evidence/v1",
        "contract_sha256": contract["contract_sha256"],
        "case_count": 24,
        "cases": cases,
        "provider_calls": 0,
        "network_calls": 0,
        "live_qdrant_calls": 0,
        "production_authority": False,
    }
    evidence["evidence_sha256"] = _sha(evidence)
    return evidence


def _metrics(cases: Sequence[Mapping[str, Any]], lane: str) -> dict[str, float]:
    answerable = [
        case
        for case in cases
        if not case["no_answer_expected"] and case["acl_allowed"]
    ]
    recalls = []
    reciprocals = []
    ndcgs = []
    provenance = []
    for case in answerable:
        expected = set(case["expected_relevant_ids"])
        ranked = case[lane]
        hit_ranks = [
            row["rank"] for row in ranked if row["section_id"] in expected
        ]
        recalls.append(1.0 if any(rank <= 5 for rank in hit_ranks) else 0.0)
        first = min(hit_ranks) if hit_ranks else None
        reciprocals.append(
            0.0 if first is None or first > 10 else 1.0 / first
        )
        ndcgs.append(
            0.0 if first is None or first > 10 else 1.0 / math.log2(first + 1)
        )
        provenance.append(
            1.0
            if ranked and all(row["provenance_present"] is True for row in ranked)
            else 0.0
        )
    acl_cases = [case for case in cases if not case["acl_allowed"]]
    no_answer_cases = [case for case in cases if case["no_answer_expected"]]
    acl_leakage = sum(1 for case in acl_cases if case[lane]) / len(acl_cases)
    no_answer_fp = sum(
        1 for case in no_answer_cases if case[lane]
    ) / len(no_answer_cases)
    return {
        "recall_at_5": round(sum(recalls) / len(recalls), 6),
        "mrr_at_10": round(sum(reciprocals) / len(reciprocals), 6),
        "ndcg_at_10": round(sum(ndcgs) / len(ndcgs), 6),
        "provenance_coverage": round(sum(provenance) / len(provenance), 6),
        "acl_leakage": round(acl_leakage, 6),
        "no_answer_false_positive_rate": round(no_answer_fp, 6),
    }


def validate_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(payload)
    digest = root.pop("evidence_sha256", None)
    if digest != _sha(root):
        raise IntegrityError("M23.7.2-101 evidence digest mismatch")
    contract = validate_contract(canonical_contract())
    if root.get("contract_sha256") != contract["contract_sha256"]:
        raise IntegrityError("M23.7.2-102 contract identity mismatch")
    cases = root.get("cases")
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise IntegrityError("M23.7.2-103 cases must be a list")
    if len(cases) != 24 or root.get("case_count") != 24:
        raise IntegrityError("M23.7.2-104 exactly 24 cases are required")
    expected_ids = [f"m23q-{index:02d}" for index in range(1, 25)]
    if [case.get("case_id") for case in cases] != expected_ids:
        raise IntegrityError("M23.7.2-105 case identity mismatch")
    for case in cases:
        if (
            case["no_answer_expected"] or not case["acl_allowed"]
        ) and (case["lexical"] or case["candidate"]):
            raise IntegrityError("M23.7.2-106 negative case leaked results")
        for lane in ("lexical", "candidate"):
            ranks = [row["rank"] for row in case[lane]]
            if ranks != list(range(1, len(ranks) + 1)):
                raise IntegrityError("M23.7.2-107 ranking order mismatch")
            if any(row["acl_allowed"] is not True for row in case[lane]):
                raise IntegrityError("M23.7.2-108 ACL violation")
    call_keys = ("provider_calls", "network_calls", "live_qdrant_calls")
    if any(root.get(key) != 0 for key in call_keys):
        raise IntegrityError("M23.7.2-109 external call detected")
    if root.get("production_authority") is not False:
        raise IntegrityError("M23.7.2-110 production authority claimed")
    return {**root, "evidence_sha256": digest}


def build_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    evidence = validate_evidence(payload)
    contract = validate_contract(canonical_contract())
    lexical = _metrics(evidence["cases"], "lexical")
    candidate = _metrics(evidence["cases"], "candidate")
    thresholds = contract["metrics"]
    failures = []
    for metric, floor_key in (
        ("recall_at_5", "recall_at_5_floor"),
        ("mrr_at_10", "mrr_at_10_floor"),
        ("ndcg_at_10", "ndcg_at_10_floor"),
        ("provenance_coverage", "provenance_coverage_floor"),
    ):
        if candidate[metric] < thresholds[floor_key]:
            failures.append(f"candidate {metric} below floor")
    if candidate["acl_leakage"] > thresholds["acl_leakage_ceiling"]:
        failures.append("candidate ACL leakage")
    if (
        candidate["no_answer_false_positive_rate"]
        > thresholds["no_answer_false_positive_ceiling"]
    ):
        failures.append("candidate no-answer false-positive regression")
    regression = lexical["recall_at_5"] - candidate["recall_at_5"]
    if regression > thresholds["lexical_recall_regression_ceiling"]:
        failures.append("candidate lexical Recall@5 regression")
    report = {
        "schema_version": "knowledge-engine-m23-offline-retrieval-report/v1",
        "status": "pass" if not failures else "reject",
        "contract_sha256": contract["contract_sha256"],
        "evidence_sha256": evidence["evidence_sha256"],
        "lexical_metrics": lexical,
        "candidate_metrics": candidate,
        "lexical_recall_regression": round(regression, 6),
        "failure_reasons": failures,
        "candidate_activation_authorized": False,
        "production_retrieval_mode": "lexical",
        "production_authority": False,
    }
    report["report_sha256"] = _sha(report)
    return report
