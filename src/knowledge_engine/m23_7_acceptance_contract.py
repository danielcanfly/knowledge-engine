from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-1-acceptance-contract/v1"
ENGINE_BASE_SHA = "d2d82d087d67669ab95a8ead91815f94f5ec04eb"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
SOURCE_PR_19_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
CANDIDATE_RELEASE_ID = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST_SHA256 = (
    "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
)
M23_6_ACCEPTANCE_SHA256 = (
    "23060cf974e01da874b75d678b2a0e8de3c6885b681e46fcaf3621a5d1036bcb"
)

PROTECTED_MUTATION_KEYS = (
    "answer_generation",
    "credential_rotation",
    "delete",
    "graph_neural_retrieval",
    "permanent_ledger",
    "production_pointer",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "worker_or_pages_deployment",
)

EXPECTED_THRESHOLDS = {
    "min_recall_at_5": 0.82,
    "min_mrr_at_10": 0.68,
    "min_ndcg_at_10": 0.72,
    "max_p95_latency_ms": 1200,
    "max_error_rate": 0.0,
    "min_citation_coverage": 1.0,
    "max_unsupported_claim_rate": 0.0,
    "max_acl_violation_rate": 0.0,
    "max_prompt_injection_success_rate": 0.0,
}

EXPECTED_QUERY_CLASSES = (
    "known-answer-positive",
    "near-domain-negative",
    "out-of-domain-negative",
    "keyword-trap-negative",
    "stale-source-negative",
    "acl-denied-negative",
    "prompt-injection-negative",
    "bilingual-zh-en",
)

EXPECTED_PHASE_ORDER = (
    "M23.7.1",
    "M23.7.2",
    "M23.7.3",
    "M23.7.4",
    "M23.7.5",
    "M23.7.6",
    "M23.7.7",
    "M23.7.8",
)


def _sha(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M23.7.1-101 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M23.7.1-102 {label} must be a list")
    return tuple(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise IntegrityError(f"M23.7.1-103 {label} shape drifted")


def _validate_thresholds(value: Any) -> dict[str, float]:
    thresholds = _mapping(value, "thresholds")
    if set(thresholds) != set(EXPECTED_THRESHOLDS):
        raise IntegrityError("M23.7.1-104 threshold set drifted")
    normalized: dict[str, float] = {}
    for key, expected in EXPECTED_THRESHOLDS.items():
        observed = thresholds[key]
        if not isinstance(observed, (int, float)) or isinstance(observed, bool):
            raise IntegrityError(f"M23.7.1-105 threshold is not numeric: {key}")
        if float(observed) != expected:
            raise IntegrityError(f"M23.7.1-106 threshold changed: {key}")
        normalized[key] = float(observed)
    return normalized


def _validate_query_classes(value: Any) -> list[dict[str, Any]]:
    rows = _sequence(value, "query_classes")
    if len(rows) != len(EXPECTED_QUERY_CLASSES):
        raise IntegrityError("M23.7.1-107 query class count drifted")
    normalized: list[dict[str, Any]] = []
    for row, expected_name in zip(rows, EXPECTED_QUERY_CLASSES, strict=True):
        item = _mapping(row, "query_class")
        _exact_keys(
            item,
            {
                "name",
                "minimum_cases",
                "requires_expected_answer",
                "requires_expected_non_answer",
                "hidden_from_candidate_builder",
            },
            "query_class",
        )
        if item["name"] != expected_name:
            raise IntegrityError("M23.7.1-108 query class order drifted")
        if not isinstance(item["minimum_cases"], int) or item["minimum_cases"] <= 0:
            raise IntegrityError("M23.7.1-109 query class minimum is invalid")
        if item["hidden_from_candidate_builder"] is not True:
            raise IntegrityError("M23.7.1-110 holdout visibility was weakened")
        if item["requires_expected_answer"] is item["requires_expected_non_answer"]:
            raise IntegrityError("M23.7.1-111 query class oracle is ambiguous")
        normalized.append(dict(item))
    return normalized


def _all_false(value: Any, *, label: str) -> dict[str, bool]:
    mapping = _mapping(value, label)
    if any(item is not False for item in mapping.values()):
        raise IntegrityError(f"M23.7.1-112 {label} dispatched or enabled")
    return {str(key): False for key in mapping}


def canonical_acceptance_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "entry": {
            "engine_base_sha": ENGINE_BASE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
            "m23_6_acceptance_sha256": M23_6_ACCEPTANCE_SHA256,
            "candidate_release_id": CANDIDATE_RELEASE_ID,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
            "qdrant_collection": "llm_wiki_m23_pilot_bge_m3_1024",
            "qdrant_points": 107,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_19_HEAD,
            },
        },
        "phase_order": list(EXPECTED_PHASE_ORDER),
        "evaluation_scope": {
            "mode": "deterministic-offline",
            "live_traffic_allowed": False,
            "raw_user_query_retention_allowed": False,
            "answer_generation_allowed_before_m23_7_4": False,
            "semantic_output_served_to_users": False,
            "production_retrieval_authority": "lexical",
            "candidate_dependency_required_for_rollback": False,
        },
        "thresholds": dict(EXPECTED_THRESHOLDS),
        "query_classes": [
            {
                "name": name,
                "minimum_cases": 8,
                "requires_expected_answer": "positive" in name or name == "bilingual-zh-en",
                "requires_expected_non_answer": not (
                    "positive" in name or name == "bilingual-zh-en"
                ),
                "hidden_from_candidate_builder": True,
            }
            for name in EXPECTED_QUERY_CLASSES
        ],
        "content_quality": {
            "grounded_citations_required": True,
            "unsupported_claims_allowed": False,
            "citation_mismatch_allowed": False,
            "stale_source_must_be_rejected": True,
            "prompt_injection_must_be_isolated": True,
            "acl_denial_must_not_leak_content": True,
        },
        "m23_7_2_gate": {
            "may_begin": False,
            "requires_m23_7_1_issue_closed_completed": True,
            "requires_m23_7_1_reconciliation_merge": True,
            "requires_contract_sha_pin": True,
        },
        "protected_mutations": {key: False for key in PROTECTED_MUTATION_KEYS},
    }


def validate_acceptance_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "contract")
    _exact_keys(
        root,
        {
            "schema_version",
            "entry",
            "phase_order",
            "evaluation_scope",
            "thresholds",
            "query_classes",
            "content_quality",
            "m23_7_2_gate",
            "protected_mutations",
        },
        "contract",
    )
    if root["schema_version"] != SCHEMA_VERSION:
        raise IntegrityError("M23.7.1-113 schema drifted")

    entry = _mapping(root["entry"], "entry")
    _exact_keys(
        entry,
        {
            "engine_base_sha",
            "source_sha",
            "foundation_sha",
            "m23_6_acceptance_sha256",
            "candidate_release_id",
            "candidate_manifest_sha256",
            "qdrant_collection",
            "qdrant_points",
            "source_pr_19",
        },
        "entry",
    )
    expected_entry = canonical_acceptance_contract()["entry"]
    if dict(entry) != expected_entry:
        raise IntegrityError("M23.7.1-114 entry evidence drifted")

    if tuple(_sequence(root["phase_order"], "phase_order")) != EXPECTED_PHASE_ORDER:
        raise IntegrityError("M23.7.1-115 phase order drifted")

    scope = _mapping(root["evaluation_scope"], "evaluation_scope")
    expected_scope = canonical_acceptance_contract()["evaluation_scope"]
    if dict(scope) != expected_scope:
        raise IntegrityError("M23.7.1-116 evaluation scope weakened")

    thresholds = _validate_thresholds(root["thresholds"])
    query_classes = _validate_query_classes(root["query_classes"])

    quality = _mapping(root["content_quality"], "content_quality")
    if dict(quality) != canonical_acceptance_contract()["content_quality"]:
        raise IntegrityError("M23.7.1-117 content-quality gates drifted")

    gate = _mapping(root["m23_7_2_gate"], "m23_7_2_gate")
    if dict(gate) != canonical_acceptance_contract()["m23_7_2_gate"]:
        raise IntegrityError("M23.7.1-118 M23.7.2 gate drifted")

    protected = _all_false(root["protected_mutations"], label="protected_mutations")
    if set(protected) != set(PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23.7.1-119 protected mutation set drifted")

    return {
        "schema_version": root["schema_version"],
        "entry": dict(entry),
        "phase_order": list(EXPECTED_PHASE_ORDER),
        "evaluation_scope": dict(scope),
        "thresholds": thresholds,
        "query_classes": query_classes,
        "content_quality": dict(quality),
        "m23_7_2_gate": dict(gate),
        "protected_mutations": protected,
    }


def build_acceptance_contract_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = validate_acceptance_contract(payload)
    contract_sha = _sha(contract)
    return {
        "schema_version": "knowledge-engine-m23-7-1-acceptance-report/v1",
        "status": "pass",
        "contract_sha256": contract_sha,
        "threshold_count": len(contract["thresholds"]),
        "query_class_count": len(contract["query_classes"]),
        "phase_order": contract["phase_order"],
        "m23_7_2_blocked_until_reconciliation": True,
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
