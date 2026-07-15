from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

ENGINE_ENTRY_SHA = "d2d82d087d67669ab95a8ead91815f94f5ec04eb"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
QDRANT_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
QUERY_CLASSES = (
    "direct-fact",
    "terminology",
    "cross-section",
    "provenance",
    "acl-negative",
    "no-answer",
)
PROTECTED = (
    "answer_generation",
    "deployment",
    "graph_neural_retrieval",
    "permanent_ledger",
    "production_pointer",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_write_or_delete",
    "r2_write",
    "semantic_judge",
    "source_write",
)


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_contract() -> dict[str, Any]:
    cases = [
        {
            "case_id": f"m23q-{index:02d}",
            "query_class": QUERY_CLASSES[(index - 1) % len(QUERY_CLASSES)],
            "expected_relevant_ids": (
                [] if index % 6 == 0 else [f"section-{index:03d}"]
            ),
            "acl_allowed": index % 6 != 5,
            "no_answer_expected": index % 6 == 0,
        }
        for index in range(1, 25)
    ]
    contract: dict[str, Any] = {
        "schema_version": "knowledge-engine-m23-quality-contract/v1",
        "entry": {
            "engine_sha": ENGINE_ENTRY_SHA,
            "candidate_release": CANDIDATE_RELEASE,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            "qdrant_collection": QDRANT_COLLECTION,
            "qdrant_points": 107,
            "source_pr_19_head": SOURCE_PR_HEAD,
            "source_pr_19_draft_open_unmerged": True,
        },
        "suite": {
            "case_count": 24,
            "query_classes": list(QUERY_CLASSES),
            "cases": cases,
            "provider_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "metrics": {
            "recall_at_5_floor": 0.80,
            "mrr_at_10_floor": 0.70,
            "ndcg_at_10_floor": 0.75,
            "provenance_coverage_floor": 1.0,
            "acl_leakage_ceiling": 0.0,
            "no_answer_false_positive_ceiling": 0.10,
            "lexical_recall_regression_ceiling": 0.05,
            "deterministic_replay_required": True,
        },
        "evidence": {
            "case_level_ranked_ids_required": True,
            "case_level_scores_required": True,
            "failure_reasons_required": True,
            "aggregate_digest_required": True,
        },
        "authority": {
            "production_retrieval_mode": "lexical",
            "semantic_output_evaluation_only": True,
            "candidate_activation_authorized": False,
            "production_authority": False,
        },
        "protected_state": {key: False for key in PROTECTED},
    }
    contract["contract_sha256"] = _sha(contract)
    return contract


def validate_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(payload)
    digest = root.pop("contract_sha256", None)
    if digest != _sha(root):
        raise IntegrityError("M23.7.1-101 contract digest mismatch")
    if root.get("schema_version") != "knowledge-engine-m23-quality-contract/v1":
        raise IntegrityError("M23.7.1-102 unsupported schema")
    entry = root.get("entry")
    if not isinstance(entry, Mapping):
        raise IntegrityError("M23.7.1-103 entry must be an object")
    expected_entry = {
        "engine_sha": ENGINE_ENTRY_SHA,
        "candidate_release": CANDIDATE_RELEASE,
        "candidate_manifest_sha256": CANDIDATE_MANIFEST,
        "qdrant_collection": QDRANT_COLLECTION,
        "qdrant_points": 107,
        "source_pr_19_head": SOURCE_PR_HEAD,
        "source_pr_19_draft_open_unmerged": True,
    }
    if dict(entry) != expected_entry:
        raise IntegrityError("M23.7.1-104 entry identity mismatch")
    suite = root.get("suite")
    if not isinstance(suite, Mapping):
        raise IntegrityError("M23.7.1-105 suite must be an object")
    cases = suite.get("cases")
    if (
        isinstance(cases, (str, bytes))
        or not isinstance(cases, Sequence)
        or len(cases) != 24
    ):
        raise IntegrityError("M23.7.1-106 exactly 24 cases are required")
    ids = [case.get("case_id") for case in cases if isinstance(case, Mapping)]
    if ids != [f"m23q-{index:02d}" for index in range(1, 25)]:
        raise IntegrityError("M23.7.1-107 case identity or order mismatch")
    classes = [
        case.get("query_class") for case in cases if isinstance(case, Mapping)
    ]
    if set(classes) != set(QUERY_CLASSES) or any(
        classes.count(name) != 4 for name in QUERY_CLASSES
    ):
        raise IntegrityError("M23.7.1-108 query-class balance mismatch")
    if (
        suite.get("provider_calls_allowed") is not False
        or suite.get("network_calls_allowed") is not False
    ):
        raise IntegrityError("M23.7.1-109 external execution was authorised")
    metrics = root.get("metrics")
    if (
        not isinstance(metrics, Mapping)
        or metrics.get("provenance_coverage_floor") != 1.0
    ):
        raise IntegrityError("M23.7.1-110 metric contract mismatch")
    authority = root.get("authority")
    if not isinstance(authority, Mapping) or dict(authority) != {
        "production_retrieval_mode": "lexical",
        "semantic_output_evaluation_only": True,
        "candidate_activation_authorized": False,
        "production_authority": False,
    }:
        raise IntegrityError("M23.7.1-111 authority boundary mismatch")
    protected = root.get("protected_state")
    if not isinstance(protected, Mapping) or set(protected) != set(PROTECTED):
        raise IntegrityError("M23.7.1-112 protected state incomplete")
    if any(protected[key] is not False for key in PROTECTED):
        raise IntegrityError("M23.7.1-113 protected mutation authorised")
    return {**root, "contract_sha256": digest}


def build_acceptance_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_contract(payload)
    report = {
        "schema_version": "knowledge-engine-m23-quality-contract-acceptance/v1",
        "status": "pass",
        "contract_sha256": validated["contract_sha256"],
        "case_count": 24,
        "query_class_count": 6,
        "production_retrieval_mode": "lexical",
        "candidate_activation_authorized": False,
        "protected_mutations_dispatched": False,
    }
    report["report_sha256"] = _sha(report)
    return report
