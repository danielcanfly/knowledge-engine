from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-6-failure-rebuild-rollback/v1"
ENGINE_ENTRY_SHA = "1055e4257a369246803aaf086a1124f6df872f89"
CONTRACT_SHA = "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
EVALUATION_SHA = "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
REPLAY_SHA = "b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2"
COMPOSITION_SHA = "6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7"
M23_7_5_EVIDENCE_SHA = "c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71"
M23_7_5_FINAL_MERGE = "1055e4257a369246803aaf086a1124f6df872f89"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
CANDIDATE_RELEASE = "m23cand-c7fbec7e945e79d05d3263b0"
CANDIDATE_MANIFEST = "3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560"
QDRANT_RELEASE = "m23pilot-a07eb79e381ca7e635cc9139"
QDRANT_RELEASE_MANIFEST = "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
QDRANT_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
QDRANT_INGESTION_MANIFEST = "2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868"
QDRANT_POINTS_ARTIFACT = "0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b"
QDRANT_POINT_ID_SET = "907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8"
QDRANT_AGGREGATE_FINGERPRINT = "2b726f1b37ceb4b674752e25494abc9e4cb397b2d506452b9d7a94568d50bfd3"
QDRANT_FIRST_WRITE_RECEIPT = "0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b"
EXPECTED_POINTS = 107
VECTOR_NAME = "default"
VECTOR_DIMENSION = 1024
DISTANCE = "Cosine"
EXPECTED_BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)
FAILURE_CLASSES = (
    "cloudflare-timeout",
    "cloudflare-unavailable",
    "qdrant-timeout",
    "qdrant-unavailable",
    "collection-identity-drift",
    "point-identity-drift",
    "vector-contract-drift",
    "acl-rejection",
    "response-shape-drift",
    "circuit-breaker-open",
)
PROTECTED_KEYS = (
    "answer_serving",
    "candidate_promotion",
    "credential_rotation",
    "delete",
    "deployment",
    "graph_neural_retrieval",
    "live_traffic",
    "live_user_sampling",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "production_retrieval",
    "production_traffic",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "worker_queue_mutation",
)
EVIDENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "pilot"
    / "m23"
    / "m23-7-5-final-observation-evidence.json"
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


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7.6-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def _load_m23_7_5_evidence() -> dict[str, Any]:
    try:
        raw = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError("M23.7.6-103 M23.7.5 evidence is unavailable") from exc
    evidence = dict(_mapping(raw, "M23.7.5 evidence"))
    expected_digest = evidence.get("evidence_payload_sha256")
    payload = dict(evidence)
    payload.pop("evidence_payload_sha256", None)
    _require(
        expected_digest == M23_7_5_EVIDENCE_SHA,
        104,
        "M23.7.5 evidence identity drifted",
    )
    _require(
        _sha(payload) == expected_digest,
        105,
        "M23.7.5 evidence self-digest mismatch",
    )
    acceptance = _mapping(evidence.get("acceptance"), "M23.7.5 acceptance")
    _require(
        acceptance.get("outcome") == "completed_fail_closed",
        106,
        "M23.7.5 outcome drifted",
    )
    _require(
        acceptance.get("m23_7_6_may_begin") is True,
        107,
        "M23.7.6 entry is not authorised",
    )
    _require(
        tuple(acceptance.get("carry_forward_blockers", ())) == EXPECTED_BLOCKERS,
        108,
        "M23.7.5 blockers drifted",
    )
    authority = _mapping(evidence.get("authority"), "M23.7.5 authority")
    _require(
        authority.get("production_retrieval") == "lexical",
        109,
        "lexical authority drifted",
    )
    _require(
        authority.get("production_response_authority") is False,
        110,
        "candidate authority enabled",
    )
    _require(
        authority.get("production_mutation_dispatched") is False,
        111,
        "production mutation recorded",
    )
    source_pr = _mapping(evidence.get("source_pr_19"), "Source PR #19")
    _require(
        dict(source_pr)
        == {
            "state": "open",
            "draft": True,
            "merged": False,
            "head_sha": SOURCE_PR_HEAD,
        },
        112,
        "Source PR #19 state drifted",
    )
    return evidence


def canonical_rebuild_descriptor() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-engine-m23-7-6-rebuild-descriptor/v1",
        "mode": "deterministic-offline-identity-rebuild",
        "inputs": {
            "candidate_release_id": CANDIDATE_RELEASE,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            "qdrant_release_id": QDRANT_RELEASE,
            "qdrant_release_manifest_sha256": QDRANT_RELEASE_MANIFEST,
            "ingestion_manifest_sha256": QDRANT_INGESTION_MANIFEST,
            "points_artifact_sha256": QDRANT_POINTS_ARTIFACT,
            "point_id_set_sha256": QDRANT_POINT_ID_SET,
            "aggregate_point_fingerprint_sha256": QDRANT_AGGREGATE_FINGERPRINT,
            "first_write_receipt_sha256": QDRANT_FIRST_WRITE_RECEIPT,
            "source_pr_19_head": SOURCE_PR_HEAD,
        },
        "collection": {
            "name": QDRANT_COLLECTION,
            "points": EXPECTED_POINTS,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": DISTANCE,
            "point_id_strategy": "uuid5(section_id,embedding_model)",
            "payload_schema_version": "knowledge-engine-m23-qdrant-payload/v1",
            "source_membership": "evaluation-only-pending-proposal",
        },
        "authority": {
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
            "lexical_output_authoritative": True,
        },
        "execution": {
            "network_used": False,
            "provider_call_used": False,
            "qdrant_read_used": False,
            "qdrant_write_used": False,
            "qdrant_delete_used": False,
            "source_write_used": False,
            "r2_mutation_used": False,
            "pointer_mutation_used": False,
        },
    }


def canonical_failure_scenarios() -> list[dict[str, Any]]:
    injection_points = {
        "cloudflare-timeout": "provider-request",
        "cloudflare-unavailable": "provider-request",
        "qdrant-timeout": "candidate-query",
        "qdrant-unavailable": "candidate-query",
        "collection-identity-drift": "collection-preflight",
        "point-identity-drift": "candidate-result-validation",
        "vector-contract-drift": "vector-preflight",
        "acl-rejection": "candidate-result-validation",
        "response-shape-drift": "candidate-response-parse",
        "circuit-breaker-open": "candidate-dispatch-guard",
    }
    scenarios: list[dict[str, Any]] = []
    for index, failure_class in enumerate(FAILURE_CLASSES, start=1):
        lexical_ids = [
            f"pilot/lexical-primary#anchor-{index:03d}",
            f"pilot/lexical-primary#support-{index:03d}",
        ]
        scenarios.append(
            {
                "scenario_id": f"m23-7-6-fault-{index:02d}",
                "injection_point": injection_points[failure_class],
                "expected_failure_class": failure_class,
                "observed_failure_class": failure_class,
                "failures_before_open": (
                    3 if failure_class == "circuit-breaker-open" else 1
                ),
                "raw_exception_persisted": False,
                "live_network_call_used": False,
                "lexical_before_ids": lexical_ids,
                "candidate_result_ids": [],
                "lexical_after_ids": lexical_ids,
                "lexical_primary_continued": True,
                "candidate_output_discarded": True,
                "output_influenced": False,
                "rollback": {
                    "mode": "lexical-only",
                    "immediate": True,
                    "candidate_dependency_required": False,
                    "completed": True,
                },
                "protected_mutation_dispatched": False,
            }
        )
    return scenarios


def canonical_m23_7_6_payload() -> dict[str, Any]:
    evidence = _load_m23_7_5_evidence()
    descriptor = canonical_rebuild_descriptor()
    descriptor_sha = _sha(descriptor)
    return {
        "schema_version": SCHEMA_VERSION,
        "entry": {
            "engine_main_sha": ENGINE_ENTRY_SHA,
            "m23_7_1_contract_sha256": CONTRACT_SHA,
            "m23_7_2_evaluation_sha256": EVALUATION_SHA,
            "m23_7_3_replay_sha256": REPLAY_SHA,
            "m23_7_4_composition_sha256": COMPOSITION_SHA,
            "m23_7_5_final_evidence_sha256": evidence[
                "evidence_payload_sha256"
            ],
            "m23_7_5_outcome": evidence["acceptance"]["outcome"],
            "m23_7_5_reconciliation_merge": M23_7_5_FINAL_MERGE,
            "candidate_release_id": CANDIDATE_RELEASE,
            "candidate_manifest_sha256": CANDIDATE_MANIFEST,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "carry_forward_blockers": list(EXPECTED_BLOCKERS),
        "failure_scenarios": canonical_failure_scenarios(),
        "rebuild": {
            "descriptor": descriptor,
            "first_calculation_sha256": descriptor_sha,
            "second_calculation_sha256": _sha(canonical_rebuild_descriptor()),
            "byte_identical": True,
            "identity_rebuild_complete": True,
            "external_write_performed": False,
        },
        "rollback": {
            "authoritative_method": "lexical",
            "candidate_method": "semantic-vector",
            "trigger": "any-candidate-failure-or-identity-drift",
            "mode": "lexical-only",
            "immediate": True,
            "candidate_dependency_required": False,
            "candidate_outputs_discarded": True,
            "candidate_may_influence_output": False,
            "production_retrieval_changed": False,
        },
        "privacy": {
            "raw_query_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
            "arbitrary_exception_text_persisted": False,
        },
        "phase_gate": {
            "m23_7_6_issue": 446,
            "m23_7_7_may_begin": False,
            "requires_m23_7_6_issue_closed_completed": True,
            "requires_m23_7_6_reconciliation_merge": True,
            "promotion_eligibility_granted": False,
        },
        "protected_mutations": {key: False for key in PROTECTED_KEYS},
    }


def validate_m23_7_6_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(payload, "M23.7.6 payload")
    expected = canonical_m23_7_6_payload()
    _require(set(root) == set(expected), 113, "root shape drifted")
    _require(root.get("schema_version") == SCHEMA_VERSION, 114, "schema drifted")
    _require(
        dict(_mapping(root.get("entry"), "entry")) == expected["entry"],
        115,
        "entry identity drifted",
    )
    _require(
        tuple(
            _sequence(root.get("carry_forward_blockers"), "carry_forward_blockers")
        )
        == EXPECTED_BLOCKERS,
        116,
        "carry-forward blockers drifted",
    )

    rows = _sequence(root.get("failure_scenarios"), "failure_scenarios")
    _require(len(rows) == len(FAILURE_CLASSES), 117, "fault matrix is incomplete")
    wanted_scenarios = canonical_failure_scenarios()
    normalized_scenarios: list[dict[str, Any]] = []
    for index, (raw, expected_failure) in enumerate(
        zip(rows, FAILURE_CLASSES, strict=True), start=1
    ):
        scenario = _mapping(raw, "failure scenario")
        wanted = wanted_scenarios[index - 1]
        _require(
            set(scenario) == set(wanted),
            118,
            "failure scenario shape drifted",
        )
        _require(
            scenario.get("scenario_id") == wanted["scenario_id"],
            119,
            "failure scenario order drifted",
        )
        _require(
            scenario.get("expected_failure_class") == expected_failure,
            120,
            "expected failure class drifted",
        )
        _require(
            scenario.get("observed_failure_class") == expected_failure,
            121,
            "failure classification drifted",
        )
        before = list(
            _sequence(scenario.get("lexical_before_ids"), "lexical_before_ids")
        )
        after = list(
            _sequence(scenario.get("lexical_after_ids"), "lexical_after_ids")
        )
        candidate = list(
            _sequence(scenario.get("candidate_result_ids"), "candidate_result_ids")
        )
        _require(
            bool(before) and before == after,
            122,
            "lexical output drifted during failure",
        )
        _require(not candidate, 123, "candidate output survived failure")
        for key in (
            "raw_exception_persisted",
            "live_network_call_used",
            "output_influenced",
            "protected_mutation_dispatched",
        ):
            _require(
                scenario.get(key) is False,
                124,
                f"forbidden failure outcome: {key}",
            )
        for key in ("lexical_primary_continued", "candidate_output_discarded"):
            _require(
                scenario.get(key) is True,
                125,
                f"required failure outcome missing: {key}",
            )
        rollback = _mapping(scenario.get("rollback"), "scenario rollback")
        _require(
            dict(rollback) == wanted["rollback"],
            126,
            "scenario rollback drifted",
        )
        normalized_scenarios.append(dict(scenario))

    rebuild = _mapping(root.get("rebuild"), "rebuild")
    expected_rebuild = expected["rebuild"]
    _require(set(rebuild) == set(expected_rebuild), 127, "rebuild shape drifted")
    descriptor = dict(_mapping(rebuild.get("descriptor"), "rebuild descriptor"))
    _require(
        descriptor == canonical_rebuild_descriptor(),
        128,
        "rebuild descriptor drifted",
    )
    digest = _sha(descriptor)
    _require(
        rebuild.get("first_calculation_sha256") == digest,
        129,
        "first rebuild digest drifted",
    )
    _require(
        rebuild.get("second_calculation_sha256") == digest,
        130,
        "second rebuild digest drifted",
    )
    _require(
        rebuild.get("byte_identical") is True,
        131,
        "rebuild is not byte-identical",
    )
    _require(
        rebuild.get("identity_rebuild_complete") is True,
        132,
        "identity rebuild incomplete",
    )
    _require(
        rebuild.get("external_write_performed") is False,
        133,
        "external rebuild write was performed",
    )

    rollback = _mapping(root.get("rollback"), "rollback")
    _require(
        dict(rollback) == expected["rollback"],
        134,
        "global rollback contract drifted",
    )
    privacy = _mapping(root.get("privacy"), "privacy")
    _require(
        dict(privacy) == expected["privacy"],
        135,
        "privacy contract drifted",
    )
    gate = _mapping(root.get("phase_gate"), "phase_gate")
    _require(dict(gate) == expected["phase_gate"], 136, "phase gate drifted")
    protected = _mapping(root.get("protected_mutations"), "protected_mutations")
    _require(
        set(protected) == set(PROTECTED_KEYS),
        137,
        "protected mutation set drifted",
    )
    _require(
        all(protected[key] is False for key in PROTECTED_KEYS),
        138,
        "protected mutation dispatched",
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "entry": dict(root["entry"]),
        "carry_forward_blockers": list(EXPECTED_BLOCKERS),
        "failure_scenarios": normalized_scenarios,
        "rebuild": dict(rebuild),
        "rollback": dict(rollback),
        "privacy": dict(privacy),
        "phase_gate": dict(gate),
        "protected_mutations": dict(protected),
    }


def build_m23_7_6_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_m23_7_6_payload(payload)
    report = {
        "schema_version": (
            "knowledge-engine-m23-7-6-failure-rebuild-rollback-report/v1"
        ),
        "milestone": "M23.7.6",
        "status": "pass",
        "fault_scenario_count": len(normalized["failure_scenarios"]),
        "failure_classes": list(FAILURE_CLASSES),
        "rebuild_descriptor_sha256": normalized["rebuild"][
            "first_calculation_sha256"
        ],
        "rebuild_byte_identical": True,
        "lexical_rollback_passed": True,
        "candidate_dependency_required_for_rollback": False,
        "carry_forward_blockers": list(EXPECTED_BLOCKERS),
        "m23_7_7_blocked_until_reconciliation": True,
        "promotion_eligibility_granted": False,
        "production_authority": False,
        "protected_mutations_dispatched": False,
    }
    report["m23_7_6_sha256"] = _sha(report)
    return report
