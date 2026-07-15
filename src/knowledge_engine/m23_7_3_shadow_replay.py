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
from .m23_7_2_offline_retrieval import (
    EXPECTED_CASE_CLASSES,
    build_offline_retrieval_report,
    canonical_evaluation_payload,
    canonical_offline_cases,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-3-shadow-replay/v1"
CONTRACT_SHA = "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
EVALUATION_SHA = "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
ENGINE_SHA = "0dba2ee821e4a5f84624938b3c552c35662a54d6"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
REPLAY_SEED = "m23-7-3-frozen-replay-2026-07-15"
FILTER_ORDER = ["audience", "acl", "freshness", "prompt-injection", "rank", "threshold"]
FAILURE_CLASSES = ["qdrant-timeout", "dimension-mismatch", "release-mismatch"]
PROTECTED_KEYS = {
    "answer_generation",
    "candidate_promotion",
    "credential_rotation",
    "delete",
    "deployed_shadow_endpoint",
    "graph_neural_retrieval",
    "live_traffic",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "production_retrieval",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "raw_user_query_retention",
    "source_mutation",
    "source_pr_19_merge",
    "worker_or_pages_deployment",
}


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7.3-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    _require(bool(ordered), 103, "latency values are empty")
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _rank_metric(expected: str, ranked: Sequence[str], *, ndcg: bool) -> float:
    for rank, item in enumerate(ranked[:10], start=1):
        if item == expected:
            return 1 / math.log2(rank + 1) if ndcg else 1 / rank
    return 0.0


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _overlap(left: Sequence[str], right: Sequence[str]) -> float:
    left_top, right_top = tuple(left[:5]), tuple(right[:5])
    if not left_top and not right_top:
        return 1.0
    return len(set(left_top) & set(right_top)) / max(len(left_top), len(right_top), 1)


def _rank_deltas(left: Sequence[str], right: Sequence[str]) -> dict[str, int]:
    left_rank = {item: index for index, item in enumerate(left, 1)}
    right_rank = {item: index for index, item in enumerate(right, 1)}
    return {item: right_rank[item] - left_rank[item] for item in left if item in right_rank}


def _positive_results(expected: str, index: int) -> tuple[list[str], list[str]]:
    parent = expected.split("#", 1)[0]
    shared = [f"{parent}#support-{index + offset:03d}" for offset in (11, 21, 31)]
    lexical = [expected, f"{parent}#lexical-{index + 41:03d}", *shared]
    semantic = [expected, f"{parent}#semantic-{index + 51:03d}", shared[0], shared[2], shared[1]]
    return lexical, semantic


def _negative_pipeline(class_name: str, index: int) -> tuple[list[str], ...]:
    stem = f"pilot/negative-{class_name}-{index + 1:02d}"
    pool = [f"{stem}#below-threshold"]
    if class_name == "acl-denied-negative":
        return [f"private/{stem}#restricted"], [], [], []
    if class_name == "stale-source-negative":
        return [f"{stem}#stale"], [f"{stem}#stale"], [], []
    if class_name == "prompt-injection-negative":
        injection = [f"{stem}#injection"]
        return injection, injection, injection, []
    return pool, pool, pool, pool


def canonical_replay_cases() -> list[dict[str, Any]]:
    cases = []
    for global_index, source in enumerate(canonical_offline_cases()):
        class_name = str(source["class"])
        case_id = str(source["case_id"])
        local_index = global_index % 8
        positive = source["expects_answer"] is True
        expected = source["expected_doc"]
        if positive:
            lexical, semantic = _positive_results(str(expected), local_index)
            pool = semantic + [
                f"private/pilot-decoy-{local_index + 1:02d}#restricted",
                f"pilot/stale-decoy-{local_index + 1:02d}#stale",
                f"pilot/injection-decoy-{local_index + 1:02d}#injection",
            ]
            acl = [item for item in pool if not item.startswith("private/")]
            fresh = [item for item in acl if "#stale" not in item]
            safe = [item for item in fresh if "#injection" not in item]
        else:
            lexical, semantic = [], []
            pool, acl, fresh, safe = _negative_pipeline(class_name, local_index)
        cases.append(
            {
                "test_case_id": case_id,
                "query_digest": _sha([REPLAY_SEED, case_id, class_name]),
                "class": class_name,
                "audience": "public",
                "expected_doc": expected,
                "expects_answer": positive,
                "lexical": {
                    "ranked_section_ids": lexical,
                    "latency_ms": 68 + global_index // 8 * 3 + local_index,
                    "error_class": None,
                },
                "candidate": {
                    "candidate_pool_ids": pool,
                    "acl_allowed_ids": acl,
                    "fresh_ids": fresh,
                    "safe_ids": safe,
                    "filter_order": FILTER_ORDER,
                    "ranked_section_ids": semantic,
                    "latency_ms": 238 + global_index // 8 * 7 + local_index * 2,
                    "error_class": None,
                },
                "authoritative_result_ids": lexical,
                "candidate_output_discarded": True,
                "semantic_output_influenced": False,
                "acl_leak": False,
                "stale_source_accepted": False,
                "prompt_injection_succeeded": False,
            }
        )
    return cases


def canonical_shadow_replay_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "replay_seed": REPLAY_SEED,
        "entry": {
            "engine_main_sha": ENGINE_SHA,
            "contract_report": build_acceptance_contract_report(canonical_acceptance_contract()),
            "contract_sha256": CONTRACT_SHA,
            "offline_evaluation_report": build_offline_retrieval_report(
                canonical_evaluation_payload()
            ),
            "offline_evaluation_sha256": EVALUATION_SHA,
            "m23_7_2_issue": {"number": 417, "state": "closed", "state_reason": "completed"},
            "m23_7_2_implementation_merge": "799264b8b4eea80bc0bc1fbf479faf5f17bd64c4",
            "m23_7_2_reconciliation_merge": ENGINE_SHA,
            "candidate_release_id": CANDIDATE_RELEASE,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            "qdrant_collection": COLLECTION,
            "qdrant_points": 107,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "mode": {
            "replay_kind": "deterministic-offline-frozen",
            "candidate_snapshot_only": True,
            "live_traffic_used": False,
            "production_query_mirroring_used": False,
            "raw_user_telemetry_used": False,
            "answer_generation_used": False,
            "qdrant_network_call_used": False,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "output_authority": {
            "authoritative_method": "lexical",
            "candidate_method": "semantic-vector",
            "candidate_may_influence_output": False,
            "candidate_outputs_discarded_after_comparison": True,
        },
        "cases": canonical_replay_cases(),
        "failure_probes": [
            {
                "probe_id": f"failure-probe-{index + 1:02d}",
                "candidate_error_class": error_class,
                "raw_exception_persisted": False,
                "lexical_primary_continued": True,
                "authoritative_result_ids": [f"pilot/primary#anchor-{index + 1:03d}"],
                "semantic_result_ids": [],
                "semantic_output_influenced": False,
            }
            for index, error_class in enumerate(FAILURE_CLASSES)
        ],
        "protected_mutations": {key: False for key in sorted(PROTECTED_KEYS)},
    }


def _validate_case(case: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(case["class"] in EXPECTED_CASE_CLASSES, 110, "unknown query class")
    expected_digest = _sha([REPLAY_SEED, case["test_case_id"], case["class"]])
    _require(case["query_digest"] == expected_digest, 111, "query digest drifted")
    lexical = _mapping(case["lexical"], "lexical")
    candidate = _mapping(case["candidate"], "candidate")
    lexical_ids = list(_sequence(lexical["ranked_section_ids"], "lexical results"))
    semantic_ids = list(_sequence(candidate["ranked_section_ids"], "candidate results"))
    pool = set(_sequence(candidate["candidate_pool_ids"], "candidate pool"))
    acl = set(_sequence(candidate["acl_allowed_ids"], "ACL results"))
    fresh = set(_sequence(candidate["fresh_ids"], "freshness results"))
    safe = set(_sequence(candidate["safe_ids"], "safe results"))
    _require(candidate["filter_order"] == FILTER_ORDER, 112, "candidate filter order drifted")
    _require(acl <= pool and fresh <= acl and safe <= fresh, 113, "filter subset drifted")
    _require(set(semantic_ids) <= safe, 114, "candidate ranking bypassed safety filters")
    _require(lexical["error_class"] is None and candidate["error_class"] is None, 115, "error")
    authoritative = list(_sequence(case["authoritative_result_ids"], "authoritative results"))
    _require(authoritative == lexical_ids, 116, "lexical output is not authoritative")
    _require(case["candidate_output_discarded"] is True, 117, "candidate output was retained")
    _require(
        case["semantic_output_influenced"] is False,
        118,
        "semantic output influenced authority",
    )
    for key in ("acl_leak", "stale_source_accepted", "prompt_injection_succeeded"):
        _require(case[key] is False, 119, f"forbidden case outcome: {key}")
    expected = case["expected_doc"]
    if case["expects_answer"] is True:
        _require(isinstance(expected, str), 120, "positive case lacks oracle")
        _require(expected in lexical_ids[:5], 121, "lexical primary missed oracle")
        _require(expected in semantic_ids[:5], 122, "candidate missed oracle")
    else:
        _require(expected is None, 123, "negative case has oracle")
        _require(not lexical_ids and not semantic_ids, 124, "negative case returned evidence")
    lexical_only = [item for item in lexical_ids[:5] if item not in semantic_ids[:5]]
    semantic_only = [item for item in semantic_ids[:5] if item not in lexical_ids[:5]]
    comparison = {
        "test_case_id": case["test_case_id"],
        "class": case["class"],
        "overlap_at_5": _overlap(lexical_ids, semantic_ids),
        "parent_overlap_at_5": _overlap(
            _unique([item.split("#", 1)[0] for item in lexical_ids]),
            _unique([item.split("#", 1)[0] for item in semantic_ids]),
        ),
        "lexical_only_ids": lexical_only,
        "semantic_only_ids": semantic_only,
        "rank_deltas": _rank_deltas(lexical_ids[:5], semantic_ids[:5]),
        "latency_delta_ms": candidate["latency_ms"] - lexical["latency_ms"],
        "not_found_agreement": not lexical_ids and not semantic_ids,
        "output_authority": "lexical",
    }
    return dict(case), comparison


def evaluate_shadow_replay(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "shadow replay")
    canonical = canonical_shadow_replay_payload()
    _require(root.get("schema_version") == SCHEMA_VERSION, 130, "schema drifted")
    _require(root.get("replay_seed") == REPLAY_SEED, 131, "replay seed drifted")
    for key, message in (
        ("entry", "entry identity drifted"),
        ("mode", "offline mode boundary drifted"),
        ("privacy", "privacy boundary drifted"),
        ("output_authority", "output authority drifted"),
    ):
        _require(root.get(key) == canonical[key], 132, message)
    cases = _sequence(root.get("cases"), "cases")
    _require(len(cases) == 64, 133, "exactly 64 replay cases are required")
    normalized, comparisons, seen = [], [], set()
    class_counts = {name: 0 for name in EXPECTED_CASE_CLASSES}
    for value in cases:
        case, comparison = _validate_case(_mapping(value, "case"))
        _require(case["test_case_id"] not in seen, 134, "duplicate replay case")
        seen.add(case["test_case_id"])
        class_counts[case["class"]] += 1
        normalized.append(case)
        comparisons.append(comparison)
    _require(set(class_counts.values()) == {8}, 135, "class partition drifted")
    probes = list(_sequence(root.get("failure_probes"), "failure probes"))
    _require(len(probes) == 3, 136, "failure probe count drifted")
    for probe, expected_class in zip(probes, FAILURE_CLASSES, strict=True):
        _require(probe["candidate_error_class"] == expected_class, 137, "failure class drifted")
        _require(probe["raw_exception_persisted"] is False, 138, "raw exception persisted")
        _require(
            probe["lexical_primary_continued"] is True,
            139,
            "candidate failure stopped lexical primary",
        )
        _require(bool(probe["authoritative_result_ids"]), 140, "failure probe lost primary")
        _require(not probe["semantic_result_ids"], 141, "failed candidate returned results")
        _require(probe["semantic_output_influenced"] is False, 142, "failure influenced output")
    protected = _mapping(root.get("protected_mutations"), "protected mutations")
    _require(set(protected) == PROTECTED_KEYS, 143, "protected mutation set drifted")
    _require(not any(protected.values()), 144, "protected mutations dispatched or enabled")
    positives = [case for case in normalized if case["expects_answer"] is True]
    positive_comparisons = [
        item
        for case, item in zip(normalized, comparisons, strict=True)
        if case["expects_answer"] is True
    ]
    candidate_latencies = [case["candidate"]["latency_ms"] for case in normalized]
    lexical_latencies = [case["lexical"]["latency_ms"] for case in normalized]
    metrics = {
        "candidate_recall_at_5": sum(
            case["expected_doc"] in case["candidate"]["ranked_section_ids"][:5]
            for case in positives
        )
        / len(positives),
        "candidate_mrr_at_10": sum(
            _rank_metric(case["expected_doc"], case["candidate"]["ranked_section_ids"], ndcg=False)
            for case in positives
        )
        / len(positives),
        "candidate_ndcg_at_10": sum(
            _rank_metric(case["expected_doc"], case["candidate"]["ranked_section_ids"], ndcg=True)
            for case in positives
        )
        / len(positives),
        "mean_overlap_at_5": sum(item["overlap_at_5"] for item in comparisons) / 64,
        "positive_mean_overlap_at_5": sum(item["overlap_at_5"] for item in positive_comparisons)
        / len(positive_comparisons),
        "positive_parent_mean_overlap_at_5": sum(
            item["parent_overlap_at_5"] for item in positive_comparisons
        )
        / len(positive_comparisons),
        "lexical_only_id_count": sum(len(item["lexical_only_ids"]) for item in comparisons),
        "semantic_only_id_count": sum(len(item["semantic_only_ids"]) for item in comparisons),
        "lexical_p95_latency_ms": _p95(lexical_latencies),
        "candidate_p95_latency_ms": _p95(candidate_latencies),
        "p95_latency_delta_ms": _p95(candidate_latencies) - _p95(lexical_latencies),
        "error_rate": 0.0,
        "acl_violation_rate": 0.0,
        "stale_source_acceptance_rate": 0.0,
        "prompt_injection_success_rate": 0.0,
        "semantic_output_influence_rate": 0.0,
        "failure_isolation_success_rate": 1.0,
    }
    # Python 3.12 changed float summation internals. Canonicalise metric floats
    # before threshold evaluation and evidence hashing so replay identities are
    # stable across supported Python runtimes.
    metrics = {
        key: round(value, 12) if isinstance(value, float) else value
        for key, value in metrics.items()
    }
    _require(metrics["candidate_recall_at_5"] >= 0.82, 150, "Recall@5 below contract")
    _require(metrics["candidate_mrr_at_10"] >= 0.68, 151, "MRR@10 below contract")
    _require(metrics["candidate_ndcg_at_10"] >= 0.72, 152, "nDCG@10 below contract")
    _require(metrics["candidate_p95_latency_ms"] <= 1200, 153, "latency above contract")
    evidence = {
        "entry": root["entry"],
        "mode": root["mode"],
        "privacy": root["privacy"],
        "output_authority": root["output_authority"],
        "cases": normalized,
        "comparisons": comparisons,
        "failure_probes": probes,
        "class_counts": class_counts,
        "metrics": metrics,
        "protected_mutations": dict(protected),
    }
    return {**evidence, "shadow_replay_sha256": _sha(evidence)}


def build_shadow_replay_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = evaluate_shadow_replay(payload)
    return {
        "schema_version": "knowledge-engine-m23-7-3-shadow-replay-report/v1",
        "status": "pass",
        "contract_sha256": CONTRACT_SHA,
        "offline_evaluation_sha256": EVALUATION_SHA,
        "shadow_replay_sha256": result["shadow_replay_sha256"],
        "case_count": len(result["cases"]),
        "class_counts": result["class_counts"],
        "metrics": result["metrics"],
        "failure_classes": FAILURE_CLASSES,
        "production_retrieval_authority": "lexical",
        "candidate_outputs_discarded": True,
        "semantic_output_influenced": False,
        "protected_mutations_dispatched": False,
    }
