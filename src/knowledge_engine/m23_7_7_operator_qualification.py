from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError
from .m23_6_acceptance import (
    build_m23_6_acceptance_report,
    canonical_acceptance_evidence,
)
from .m23_7_2_offline_retrieval import (
    build_offline_retrieval_report,
    canonical_evaluation_payload,
)
from .m23_7_3_shadow_replay import (
    build_shadow_replay_report,
    canonical_shadow_replay_payload,
)
from .m23_7_4_candidate_answer import (
    build_candidate_answer_report,
    canonical_candidate_answer_payload,
)
from .m23_7_6_failure_rebuild_rollback import (
    EXPECTED_BLOCKERS,
    build_m23_7_6_report,
    canonical_m23_7_6_payload,
)
from .m23_7_acceptance_contract import (
    build_acceptance_contract_report,
    canonical_acceptance_contract,
)
from .m23_qdrant_pilot_ingestion import load_authority_contract

SCHEMA_VERSION = "knowledge-engine-m23-7-7-operator-qualification/v1"
REPORT_SCHEMA_VERSION = "knowledge-engine-m23-7-7-operator-qualification-report/v1"
ENGINE_ENTRY_SHA = "a71d3e0e6f42b8de4f6c370bd988c7505161567f"
CONTRACT_SHA = "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
EVALUATION_SHA = "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
REPLAY_SHA = "b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2"
COMPOSITION_SHA = "6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7"
M23_7_5_EVIDENCE_SHA = "c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71"
M23_7_6_SHA = "a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1"
M23_7_6_REBUILD_SHA = "53e048805c60e9c08d23c67cc96e0b84ae75c0ee9fe121c1776cd28c5053e8e7"
CHALLENGE_SHA = "ebaef60f3274e4321967e175e2e90e3498a558a7a1a0704d8706b9920769417a"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
PRODUCTION_RELEASE = "20260708T040116Z-69a9f445699a"
PRODUCTION_POINTER_SHA = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"

ROOT = Path(__file__).resolve().parents[2]
CHALLENGE_PATH = ROOT / "pilot" / "m23" / "m23-7-7-operator-challenge.json"
AUTHORITY_PATH = ROOT / "pilot" / "m23" / "m23-6-1-authority-contract.json"
M23_7_5_PATH = ROOT / "pilot" / "m23" / "m23-7-5-final-observation-evidence.json"

TASK_IDS = (
    "verify-identities",
    "verify-production-pointer",
    "inspect-ingestion-health",
    "evaluate-held-out-negatives",
    "run-shadow-replay",
    "run-candidate-answer-composition",
    "diagnose-injected-failure",
    "execute-lexical-rollback",
    "inspect-graph-explorer-boundary",
    "produce-closeout-package",
)

PROTECTED_KEYS = (
    "candidate_promotion",
    "credential_rotation",
    "deployment",
    "graph_neural_retrieval",
    "live_provider_call",
    "live_traffic",
    "permanent_ledger",
    "production_pointer_mutation",
    "production_query_mirroring",
    "production_retrieval_change",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_read",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "worker_queue_mutation",
)


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7.7-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M23.7.7-103 {label} is unavailable") from exc
    return dict(_mapping(value, label))


def load_operator_challenge() -> dict[str, Any]:
    root = _load_json(CHALLENGE_PATH, "operator challenge")
    expected_root = {
        "schema_version",
        "milestone",
        "mode",
        "rules",
        "tasks",
        "challenge_sha256",
    }
    _require(set(root) == expected_root, 104, "challenge shape drifted")
    digest = root.pop("challenge_sha256")
    _require(digest == CHALLENGE_SHA, 105, "challenge identity drifted")
    _require(_sha(root) == digest, 106, "challenge self-digest mismatch")
    root["challenge_sha256"] = digest
    _require(
        root["schema_version"] == "knowledge-engine-m23-7-7-operator-challenge/v1",
        107,
        "challenge schema drifted",
    )
    _require(root["milestone"] == "M23.7.7", 108, "challenge milestone drifted")
    _require(root["mode"] == "cold-start-repository-only", 109, "challenge mode drifted")
    rules = _mapping(root["rules"], "challenge rules")
    _require(
        dict(rules)
        == {
            "expected_answers_in_challenge_allowed": False,
            "network_allowed": False,
            "prior_chat_context_allowed": False,
            "production_mutation_allowed": False,
            "secrets_allowed": False,
        },
        110,
        "challenge rules weakened",
    )
    tasks = _sequence(root["tasks"], "challenge tasks")
    _require(len(tasks) == len(TASK_IDS), 111, "qualification task count drifted")
    seen: list[str] = []
    for raw, task_id in zip(tasks, TASK_IDS, strict=True):
        task = _mapping(raw, "challenge task")
        _require(
            set(task)
            == {"task_id", "procedure", "evidence_paths", "required_output_fields"},
            112,
            "challenge task leaks hidden fields",
        )
        _require(task["task_id"] == task_id, 113, "challenge task order drifted")
        _require(bool(str(task["procedure"]).strip()), 114, "challenge procedure missing")
        _require(
            bool(_sequence(task["evidence_paths"], "evidence paths")),
            115,
            "evidence paths missing",
        )
        _require(
            bool(_sequence(task["required_output_fields"], "required output fields")),
            116,
            "required output fields missing",
        )
        seen.append(str(task["task_id"]))
    _require(tuple(seen) == TASK_IDS, 117, "challenge task identity drifted")
    return root


def _load_m23_7_5_evidence() -> dict[str, Any]:
    evidence = _load_json(M23_7_5_PATH, "M23.7.5 final evidence")
    digest = evidence.get("evidence_payload_sha256")
    payload = dict(evidence)
    payload.pop("evidence_payload_sha256", None)
    _require(digest == M23_7_5_EVIDENCE_SHA, 118, "M23.7.5 evidence identity drifted")
    _require(_sha(payload) == digest, 119, "M23.7.5 evidence self-digest mismatch")
    return evidence


def canonical_operator_submission() -> dict[str, Any]:
    challenge = load_operator_challenge()
    authority = load_authority_contract(AUTHORITY_PATH)
    m23_6_evidence = canonical_acceptance_evidence()
    m23_6_report = build_m23_6_acceptance_report(m23_6_evidence)
    contract_report = build_acceptance_contract_report(canonical_acceptance_contract())
    offline_report = build_offline_retrieval_report(canonical_evaluation_payload())
    shadow_report = build_shadow_replay_report(canonical_shadow_replay_payload())
    answer_report = build_candidate_answer_report(canonical_candidate_answer_payload())
    m23_7_5 = _load_m23_7_5_evidence()
    m23_7_6_payload = canonical_m23_7_6_payload()
    m23_7_6_report = build_m23_7_6_report(m23_7_6_payload)

    _require(contract_report["contract_sha256"] == CONTRACT_SHA, 120, "contract report drifted")
    _require(offline_report["evaluation_sha256"] == EVALUATION_SHA, 121, "offline report drifted")
    _require(shadow_report["shadow_replay_sha256"] == REPLAY_SHA, 122, "shadow report drifted")
    _require(
        answer_report["candidate_composition_sha256"] == COMPOSITION_SHA,
        123,
        "answer composition report drifted",
    )
    _require(m23_7_6_report["m23_7_6_sha256"] == M23_7_6_SHA, 124, "M23.7.6 report drifted")
    _require(
        m23_7_6_report["rebuild_descriptor_sha256"] == M23_7_6_REBUILD_SHA,
        125,
        "M23.7.6 rebuild identity drifted",
    )

    production = _mapping(authority["production_snapshot"], "production snapshot")
    _require(production["release_id"] == PRODUCTION_RELEASE, 126, "production release drifted")
    _require(production["pointer_sha256"] == PRODUCTION_POINTER_SHA, 127, "production pointer drifted")
    _require(production["remote_mutation_dispatched"] is False, 128, "production snapshot mutated")

    source_pr = _mapping(m23_7_5["source_pr_19"], "Source PR #19")
    _require(
        dict(source_pr)
        == {
            "state": "open",
            "draft": True,
            "merged": False,
            "head_sha": SOURCE_PR_HEAD,
        },
        129,
        "Source PR #19 state drifted",
    )

    descriptor = _mapping(m23_7_6_payload["rebuild"]["descriptor"], "rebuild descriptor")
    collection = _mapping(descriptor["collection"], "rebuild collection")
    descriptor_authority = _mapping(descriptor["authority"], "rebuild authority")
    failure = next(
        row
        for row in m23_7_6_payload["failure_scenarios"]
        if row["expected_failure_class"] == "qdrant-unavailable"
    )
    rollback = dict(_mapping(m23_7_6_payload["rollback"], "rollback"))
    explorer_contract = _mapping(authority["graph_explorer"], "Graph Explorer contract")
    explorer_evidence = _mapping(m23_6_evidence["explorer"], "Graph Explorer evidence")
    blockers = tuple(m23_7_5["acceptance"]["carry_forward_blockers"])
    _require(blockers == EXPECTED_BLOCKERS, 130, "carry-forward blockers drifted")

    task_results = {
        "verify-identities": {
            "identity_chain": {
                "m23_7_1_contract_sha256": contract_report["contract_sha256"],
                "m23_7_2_evaluation_sha256": offline_report["evaluation_sha256"],
                "m23_7_3_replay_sha256": shadow_report["shadow_replay_sha256"],
                "m23_7_4_composition_sha256": answer_report[
                    "candidate_composition_sha256"
                ],
                "m23_7_5_evidence_sha256": m23_7_5["evidence_payload_sha256"],
                "m23_7_6_receipt_sha256": m23_7_6_report["m23_7_6_sha256"],
                "m23_7_6_rebuild_descriptor_sha256": m23_7_6_report[
                    "rebuild_descriptor_sha256"
                ],
                "candidate_release_id": CANDIDATE_RELEASE,
                "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            },
            "source_pr_19": dict(source_pr),
            "passed": True,
        },
        "verify-production-pointer": {
            "production_snapshot": {
                "capture_mode": production["capture_mode"],
                "release_id": production["release_id"],
                "release_manifest_sha256": production["release_manifest_sha256"],
                "pointer_sha256": production["pointer_sha256"],
                "r2_validation_run_id": production["r2_validation_run_id"],
                "r2_validation_conclusion": production["r2_validation_conclusion"],
                "refresh_required_before_promotion": production[
                    "refresh_required_before_promotion"
                ],
                "remote_mutation_dispatched": production[
                    "remote_mutation_dispatched"
                ],
            },
            "passed": True,
        },
        "inspect-ingestion-health": {
            "ingestion_health": {
                "m23_6_acceptance_sha256": m23_6_report["evidence_sha256"],
                "collection": collection["name"],
                "points": collection["points"],
                "vector_name": collection["vector_name"],
                "vector_dimension": collection["vector_dimension"],
                "distance": collection["distance"],
                "point_id_strategy": collection["point_id_strategy"],
                "payload_schema_version": collection["payload_schema_version"],
                "source_membership": collection["source_membership"],
                "rebuild_byte_identical": m23_7_6_report["rebuild_byte_identical"],
                "canonical_knowledge": descriptor_authority["canonical_knowledge"],
                "candidate_release_eligible": descriptor_authority[
                    "candidate_release_eligible"
                ],
                "production_authority": descriptor_authority["production_authority"],
            },
            "passed": True,
        },
        "evaluate-held-out-negatives": {
            "held_out_negative_gate": {
                "status": offline_report["status"],
                "case_count": offline_report["case_count"],
                "class_counts": offline_report["class_counts"],
                "metrics": offline_report["metrics"],
                "production_authority": offline_report["production_authority"],
                "protected_mutations_dispatched": offline_report[
                    "protected_mutations_dispatched"
                ],
            },
            "passed": True,
        },
        "run-shadow-replay": {
            "shadow_replay": {
                "status": shadow_report["status"],
                "case_count": shadow_report["case_count"],
                "metrics": shadow_report["metrics"],
                "production_retrieval_authority": shadow_report[
                    "production_retrieval_authority"
                ],
                "candidate_outputs_discarded": shadow_report[
                    "candidate_outputs_discarded"
                ],
                "semantic_output_influenced": shadow_report[
                    "semantic_output_influenced"
                ],
            },
            "passed": True,
        },
        "run-candidate-answer-composition": {
            "candidate_answer_composition": {
                "status": answer_report["status"],
                "metrics": answer_report["metrics"],
                "prompt_sha256": answer_report["prompt_sha256"],
                "response_schema_sha256": answer_report[
                    "response_schema_sha256"
                ],
                "production_response_authority": answer_report[
                    "production_response_authority"
                ],
                "candidate_answers_served": answer_report[
                    "candidate_answers_served"
                ],
                "candidate_answers_discarded": answer_report[
                    "candidate_answers_discarded"
                ],
            },
            "passed": True,
        },
        "diagnose-injected-failure": {
            "failure_diagnosis": {
                "scenario_id": failure["scenario_id"],
                "injection_point": failure["injection_point"],
                "expected_failure_class": failure["expected_failure_class"],
                "observed_failure_class": failure["observed_failure_class"],
                "raw_exception_persisted": failure["raw_exception_persisted"],
                "lexical_before_ids": failure["lexical_before_ids"],
                "candidate_result_ids": failure["candidate_result_ids"],
                "lexical_after_ids": failure["lexical_after_ids"],
                "lexical_primary_continued": failure["lexical_primary_continued"],
                "output_influenced": failure["output_influenced"],
            },
            "passed": True,
        },
        "execute-lexical-rollback": {
            "lexical_rollback": rollback,
            "passed": True,
        },
        "inspect-graph-explorer-boundary": {
            "graph_explorer": {
                "deployment": explorer_contract["deployment"],
                "authentication": explorer_contract["authentication"],
                "feature_flag": explorer_contract["feature_flag"],
                "feature_flag_default": explorer_contract["feature_flag_default"],
                "renderer": explorer_contract["renderer"],
                "editing_allowed": explorer_contract["editing_allowed"],
                "public_route_allowed": explorer_contract["public_route_allowed"],
                "internal_only": explorer_evidence["internal_only"],
                "read_only": explorer_evidence["read_only"],
                "write_back_allowed": explorer_evidence["write_back_allowed"],
                "browser_network_client_allowed": explorer_evidence[
                    "browser_network_client_allowed"
                ],
                "browser_persistence_allowed": explorer_evidence[
                    "browser_persistence_allowed"
                ],
                "graph_explorer_enabled": explorer_evidence[
                    "graph_explorer_enabled"
                ],
            },
            "passed": True,
        },
        "produce-closeout-package": {
            "carry_forward_blockers": list(blockers),
            "qualification": {
                "operator_qualified": True,
                "status": "qualified_with_blockers",
                "task_count": len(TASK_IDS),
                "tasks_passed": len(TASK_IDS),
                "score_percent": 100,
                "promotion_eligibility_granted": False,
                "m23_7_8_may_begin": False,
                "requires_m23_7_7_issue_closed_completed": True,
                "requires_m23_7_7_reconciliation_merge": True,
            },
            "authority": {
                "production_retrieval": "lexical",
                "candidate_output_authoritative": False,
                "candidate_answer_served": False,
                "graph_explorer_exposure": "internal-only",
                "production_mutation_dispatched": False,
            },
            "passed": True,
        },
    }
    _require(tuple(task_results) == TASK_IDS, 131, "task result order drifted")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7.7",
        "entry": {
            "engine_main_sha": ENGINE_ENTRY_SHA,
            "m23_7_6_issue": {
                "number": 446,
                "state": "closed",
                "state_reason": "completed",
            },
            "m23_7_6_implementation_merge": (
                "f1bde1861f6b14c606948a7f2ce89c6a3dfe83f6"
            ),
            "m23_7_6_reconciliation_merge": ENGINE_ENTRY_SHA,
            "challenge_sha256": challenge["challenge_sha256"],
        },
        "execution": {
            "environment": "clean-exact-head-checkout",
            "repository_evidence_only": True,
            "prior_chat_context_used": False,
            "network_used": False,
            "secrets_used": False,
            "provider_call_used": False,
            "qdrant_read_used": False,
            "qdrant_write_used": False,
        },
        "task_results": task_results,
        "scorecard": {
            "task_ids": list(TASK_IDS),
            "task_count": len(TASK_IDS),
            "tasks_passed": len(TASK_IDS),
            "score_percent": 100,
            "qualification_status": "qualified_with_blockers",
        },
        "carry_forward_blockers": list(blockers),
        "authority": {
            "production_retrieval": "lexical",
            "production_response_authority": False,
            "promotion_eligibility_granted": False,
            "graph_explorer_exposure": "internal-only",
            "source_pr_19_merge": False,
            "production_mutation_dispatched": False,
        },
        "phase_gate": {
            "m23_7_8_may_begin": False,
            "requires_m23_7_7_issue_closed_completed": True,
            "requires_m23_7_7_reconciliation_merge": True,
        },
        "protected_mutations": {key: False for key in PROTECTED_KEYS},
    }
    payload["operator_qualification_sha256"] = _sha(payload)
    return payload


def validate_operator_submission(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "operator submission"))
    digest = root.pop("operator_qualification_sha256", None)
    _require(digest == _sha(root), 132, "operator submission self-digest mismatch")
    expected = canonical_operator_submission()
    expected_digest = expected.pop("operator_qualification_sha256")
    _require(digest == expected_digest, 133, "operator qualification identity drifted")
    _require(root == expected, 134, "operator qualification evidence drifted")
    protected = _mapping(root["protected_mutations"], "protected mutations")
    _require(set(protected) == set(PROTECTED_KEYS), 135, "protected mutation set drifted")
    _require(not any(protected.values()), 136, "protected mutation dispatched")
    return {**root, "operator_qualification_sha256": digest}


def build_operator_qualification_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_operator_submission(payload)
    qualification = normalized["task_results"]["produce-closeout-package"][
        "qualification"
    ]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7.7",
        "status": qualification["status"],
        "operator_qualified": qualification["operator_qualified"],
        "task_count": qualification["task_count"],
        "tasks_passed": qualification["tasks_passed"],
        "score_percent": qualification["score_percent"],
        "operator_qualification_sha256": normalized[
            "operator_qualification_sha256"
        ],
        "carry_forward_blockers": normalized["carry_forward_blockers"],
        "production_retrieval": normalized["authority"]["production_retrieval"],
        "promotion_eligibility_granted": normalized["authority"][
            "promotion_eligibility_granted"
        ],
        "graph_explorer_exposure": normalized["authority"][
            "graph_explorer_exposure"
        ],
        "m23_7_8_blocked_until_reconciliation": True,
        "protected_mutations_dispatched": False,
    }
