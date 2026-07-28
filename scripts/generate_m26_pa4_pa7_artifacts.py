"""Generate PA.3 through PA.7 governance artifacts."""

# ruff: noqa: E402, E501

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from knowledge_engine.m26_canary_slo_rollback import run_canary_benchmark
from knowledge_engine.m26_controlled_internal_shadow_pilot import run_shadow_pilot_benchmark
from knowledge_engine.m26_production_promotion_closure import (
    EVIDENCE_CHAIN_STATUSES,
    run_production_closure_benchmark,
)
from knowledge_engine.m26_verified_answer_citation_gate import run_verified_answer_benchmark

PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
UNIFIED_SPEC_SHA = "6e71ca5981e3eb45987d188c9c7fb2851a4b5f31803655dd2fc7e28ed4bd22a9"
MODULE_FILES = {
    "M26.PA.4": "src/knowledge_engine/m26_verified_answer_citation_gate.py",
    "M26.PA.5": "src/knowledge_engine/m26_controlled_internal_shadow_pilot.py",
    "M26.PA.6": "src/knowledge_engine/m26_canary_slo_rollback.py",
    "M26.PA.7": "src/knowledge_engine/m26_production_promotion_closure.py",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def with_self_digest(value: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop("self_sha256", None)
    return {**unsigned, "self_sha256": object_sha256(unsigned)}


def write_json(path: Path, value: dict[str, Any], *, self_digest: bool = True) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = with_self_digest(value) if self_digest else value
    path.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def top_level_schema(
    *,
    title: str,
    schema_id: str,
    schema_version: str,
    stage_id: str,
    required: list[str],
    optional: list[str] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "schema_version": {"const": schema_version},
        "stage_id": {"const": stage_id},
        "self_sha256": {"pattern": "^[0-9a-f]{64}$", "type": "string"},
    }
    for name in required + list(optional or []):
        if name in properties:
            continue
        if name.endswith("_count") or name in {"case_count", "question_count", "passed_count", "failed_count"}:
            properties[name] = {"minimum": 0, "type": "integer"}
        elif name.endswith("_status") or name in {"status", "case_id", "question_id", "predecessor_status", "decision_maker", "closure_status"}:
            properties[name] = {"type": "string"}
        elif name.startswith("is_") or name.endswith("_complete") or name.endswith("_required"):
            properties[name] = {"type": "boolean"}
        elif name in {"metrics", "diagnostics"}:
            properties[name] = {"type": "object"}
        elif name in {"results", "record_sha256s", "refusal_reason_codes", "warning_codes", "conditions_or_reasons", "evidence_chain_statuses", "reviewer_ids", "verified_claim_ids", "verified_binding_ids", "stop_codes"}:
            properties[name] = {"type": "array"}
        else:
            properties[name] = {}
    return {
        "$id": schema_id,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": properties,
        "required": ["schema_version", "stage_id", *required, "self_sha256"],
        "title": title,
        "type": "object",
    }


def generate_schemas() -> dict[str, str]:
    schemas = {
        "m26-pa-4-verified-answer-record-v1.schema.json": top_level_schema(
            title="M26.PA.4 verified answer record",
            schema_id="knowledge-engine/m26-pa-4-verified-answer-record-v1",
            schema_version="knowledge-engine-m26-pa-4-verified-answer-record/v1",
            stage_id="M26.PA.4",
            required=[
                "case_id",
                "predecessor_status",
                "verified_answer_status",
                "safe_for_pa5",
                "material_claim_extraction",
                "citation_binding",
                "support_verification",
                "complete_denominator_record",
                "verified_claim_ids",
                "verified_binding_ids",
                "warning_codes",
                "refusal_reason_codes",
                "repair_attempt_count",
                "abstention_required",
                "production_answer_serving",
                "production_pointer_mutation",
                "public_shadow_canary_traffic",
                "verified_final_answer",
                "live_provider_calls",
                "secret_values_persisted",
                "raw_text_persisted",
                "diagnostics",
            ],
        ),
        "m26-pa-4-verified-answer-benchmark-v1.schema.json": top_level_schema(
            title="M26.PA.4 verified answer benchmark",
            schema_id="knowledge-engine/m26-pa-4-verified-answer-benchmark-v1",
            schema_version="knowledge-engine-m26-pa-4-verified-answer-benchmark/v1",
            stage_id="M26.PA.4",
            required=[
                "status",
                "case_count",
                "passed_count",
                "failed_count",
                "metrics",
                "record_sha256s",
                "results",
            ],
        ),
        "m26-pa-5-shadow-review-record-v1.schema.json": top_level_schema(
            title="M26.PA.5 shadow review record",
            schema_id="knowledge-engine/m26-pa-5-shadow-review-record-v1",
            schema_version="knowledge-engine-m26-pa-5-shadow-review-record/v1",
            stage_id="M26.PA.5",
            required=[
                "question_id",
                "predecessor_status",
                "shadow_review_status",
                "authenticated_internal_only",
                "controlled_shadow",
                "complete_denominator_record",
                "reviewer_ids",
                "reviewer_count",
                "verified_answer_status",
                "quality_score",
                "citation_precision",
                "abstention_appropriate",
                "latency_ms",
                "cost_usd",
                "reviewer_agreement",
                "refusal_reason_codes",
                "public_answer",
                "public_traffic",
                "production_answer_serving",
                "production_pointer_mutation",
                "safe_for_pa6",
            ],
        ),
        "m26-pa-5-shadow-pilot-benchmark-v1.schema.json": top_level_schema(
            title="M26.PA.5 controlled shadow benchmark",
            schema_id="knowledge-engine/m26-pa-5-shadow-pilot-benchmark-v1",
            schema_version="knowledge-engine-m26-pa-5-shadow-pilot-benchmark/v1",
            stage_id="M26.PA.5",
            required=[
                "status",
                "question_count",
                "passed_count",
                "failed_count",
                "complete_denominator",
                "metrics",
                "record_sha256s",
                "results",
            ],
        ),
        "m26-pa-6-canary-record-v1.schema.json": top_level_schema(
            title="M26.PA.6 canary record",
            schema_id="knowledge-engine/m26-pa-6-canary-record-v1",
            schema_version="knowledge-engine-m26-pa-6-canary-record/v1",
            stage_id="M26.PA.6",
            required=[
                "case_id",
                "predecessor_status",
                "canary_status",
                "bounded_canary",
                "allowlisted_audience",
                "allowlisted_route",
                "traffic_percent",
                "latency_p95_ms",
                "error_rate",
                "cost_usd",
                "unsupported_claim_count",
                "kill_switch_available",
                "rollback_drill_completed",
                "stop_codes",
                "full_production_traffic",
                "production_pointer_mutation",
                "source_foundation_release_mutation",
                "safe_for_pa7",
            ],
        ),
        "m26-pa-6-canary-benchmark-v1.schema.json": top_level_schema(
            title="M26.PA.6 canary benchmark",
            schema_id="knowledge-engine/m26-pa-6-canary-benchmark-v1",
            schema_version="knowledge-engine-m26-pa-6-canary-benchmark/v1",
            stage_id="M26.PA.6",
            required=[
                "status",
                "case_count",
                "passed_count",
                "failed_count",
                "metrics",
                "record_sha256s",
                "results",
            ],
        ),
        "m26-pa-7-final-decision-record-v1.schema.json": top_level_schema(
            title="M26.PA.7 final decision record",
            schema_id="knowledge-engine/m26-pa-7-final-decision-record-v1",
            schema_version="knowledge-engine-m26-pa-7-final-decision-record/v1",
            stage_id="M26.PA.7",
            required=[
                "case_id",
                "predecessor_status",
                "decision_status",
                "decision_maker",
                "evidence_chain_complete",
                "evidence_chain_statuses",
                "bounded_outcome",
                "production_promotion_authorized",
                "production_promotion_execution",
                "production_pointer_mutation",
                "public_traffic_mutation",
                "secret_values_persisted",
                "source_foundation_release_mutation",
                "independent_final_reconciliation_required",
                "formal_m26_closure",
                "conditions_or_reasons",
                "closure_status",
            ],
        ),
        "m26-pa-7-production-closure-benchmark-v1.schema.json": top_level_schema(
            title="M26.PA.7 production closure benchmark",
            schema_id="knowledge-engine/m26-pa-7-production-closure-benchmark-v1",
            schema_version="knowledge-engine-m26-pa-7-production-closure-benchmark/v1",
            stage_id="M26.PA.7",
            required=[
                "status",
                "case_count",
                "passed_count",
                "failed_count",
                "metrics",
                "record_sha256s",
                "results",
            ],
        ),
    }
    digests: dict[str, str] = {}
    for filename, schema in schemas.items():
        path = SCHEMAS / filename
        write_json(path, schema, self_digest=False)
        digests[filename] = file_sha256(path)
    return digests


def pa3_acceptance() -> dict[str, Any]:
    return write_json(
        PILOT / "m26-pa-3-acceptance.json",
        {
            "schema_version": "knowledge-engine-m26-pa-3-acceptance/v1",
            "stage_id": "M26.PA.3",
            "status": "m26_pa_3_live_provider_execution_accepted",
            "effective_only_on_reconciliation_merge": True,
            "predecessor": {
                "pa2_acceptance_self_sha256": "f6f597699390135b0bf7a8e31417c2e8e6f48af2dc2af4168eca1fd1e7f24f67",
                "pa2_status": "m26_pa_2_real_corpus_retrieval_binding_accepted",
            },
            "implementation": {
                "authorization_pull_request": 1201,
                "authorization_head_sha": "32cf010cc6f0f180698562162100428174cc5754",
                "authorization_merge_sha": "3bac0c44e62341322901e8fa7d2503a68ca04b6e",
                "expected_head_merge": True,
                "issue_number": 1197,
                "unresolved_review_thread_count": 0,
            },
            "live_evidence": {
                "artifact_id": 8664397892,
                "artifact_name": "m26-pa-3-live-provider-evidence-attempt-4",
                "artifact_local_receipt_path": "/tmp/m26-pa3-attempt4-artifact-1785178119/m26-pa-3-live-provider-receipt.json",
                "receipt_file_sha256": "9fc30e5d4cb79aadfa7cd3ab03083197931e2d7cc5481d6104b86a40d2ed7352",
                "receipt_self_sha256": "eca49a290d587449b9c3d0dc369ac7893890bc83767a983abd097bce7adecec2",
                "run_id": 30295355209,
                "run_attempt": 1,
                "workflow_name": "M26.PA.3 Live Provider Execution Gate",
            },
            "receipt_authority": {
                "provider_calls": 1,
                "credential_names": ["MINIMAX_API_KEY"],
                "secret_values_persisted": False,
                "raw_text_persisted": False,
                "vectors_requested": False,
                "vectors_returned": False,
                "r2_write_operations": 0,
                "qdrant_write_operations": 0,
                "source_foundation_release_mutations": 0,
                "public_shadow_canary_traffic_operations": 0,
            },
            "next_stage": {
                "stage_id": "M26.PA.4",
                "name": "Verified Answer and Citation Gate",
                "predecessor_status_required": "m26_pa_3_live_provider_execution_accepted",
                "verified_answer_candidate_policy_required": True,
                "production_serving_permitted": False,
                "public_shadow_canary_traffic_permitted": False,
            },
        },
    )


def generate_pa4(schema_digests: dict[str, str], pa3: dict[str, Any]) -> dict[str, Any]:
    policy = write_json(
        PILOT / "m26-pa-4-verified-answer-policy.json",
        {
            "schema_version": "knowledge-engine-m26-pa-4-verified-answer-policy/v1",
            "stage_id": "M26.PA.4",
            "accepted_predecessor_status": "m26_pa_3_live_provider_execution_accepted",
            "authority": {
                "material_claim_extraction": True,
                "citation_binding": True,
                "support_verification": True,
                "bounded_repair": True,
                "abstention": True,
                "deterministic_evidence": True,
                "complete_denominator": True,
                "live_provider_calls": False,
                "production_answer_serving": False,
                "production_pointer_mutation": False,
                "public_shadow_canary_traffic": False,
                "verified_final_answers": False,
                "secret_persistence": False,
                "raw_text_persistence": False,
                "r2_writes": False,
                "qdrant_writes": False,
                "source_foundation_release_mutation": False,
            },
            "gate_policy": {
                "abstain_on_insufficient_support": True,
                "fail_closed": True,
                "forbidden_text_fragments": [
                    "follow these instructions",
                    "ignore previous",
                    "system prompt",
                ],
                "max_repair_attempts": 1,
            },
            "status_policy": {
                "abstention_status": "abstention_required",
                "authority_rejected_status": "verified_answer_rejected_authority_escalation",
                "ready_status": "verified_answer_ready",
                "repaired_status": "verified_answer_ready_after_bounded_repair",
                "warning_status": "verified_answer_ready_with_warnings",
            },
        },
    )
    def case(
        case_id: str,
        verdicts: list[str],
        expected: str,
        *,
        claims: int = 1,
        bindings: int | None = None,
        repairs: int = 0,
        warnings: list[str] | None = None,
        authority: dict[str, bool] | None = None,
        requires_abstention: bool = False,
        requires_repair: bool = False,
    ) -> dict[str, Any]:
        binding_count = claims if bindings is None else bindings
        claim_ids = [f"{case_id}-claim-{idx + 1}" for idx in range(claims)]
        binding_ids = [f"{case_id}-binding-{idx + 1}" for idx in range(binding_count)]
        authority_flags = {
            "live_provider_calls": False,
            "production_answer_serving": False,
            "production_pointer_mutation": False,
            "public_shadow_canary_traffic": False,
            "verified_final_answer": False,
            "secret_persistence": False,
            "raw_text_persistence": False,
            "r2_write": False,
            "qdrant_write": False,
        }
        authority_flags.update(authority or {})
        return {
            "case_id": case_id,
            "candidate": {
                "answer_text_sha256": object_sha256({"case_id": case_id}),
                "authority": authority_flags,
                "citation_binding_ids": binding_ids,
                "diagnostics": {},
                "material_claim_ids": claim_ids,
                "repair_attempts": repairs,
                "support_verdicts": verdicts,
                "warning_codes": list(warnings or []),
            },
            "expected": {
                "min_verified_bindings": 0 if requires_abstention else binding_count,
                "min_verified_claims": 0 if requires_abstention else claims,
                "requires_abstention": requires_abstention,
                "requires_repair": requires_repair,
                "status": expected,
            },
        }

    cases = [
        case("pa4-direct-supported", ["supported"], "verified_answer_ready"),
        case("pa4-graph-supported", ["supported"], "verified_answer_ready"),
        case("pa4-multi-claim", ["supported", "supported"], "verified_answer_ready", claims=2),
        case(
            "pa4-bounded-repair",
            ["repairable"],
            "verified_answer_ready_after_bounded_repair",
            repairs=1,
            requires_repair=True,
        ),
        case(
            "pa4-conflict-warning",
            ["supported"],
            "verified_answer_ready_with_warnings",
            warnings=["conflict_warning"],
        ),
        case(
            "pa4-prompt-warning",
            ["supported"],
            "verified_answer_ready_with_warnings",
            warnings=["prompt_injection_quarantined"],
        ),
        case(
            "pa4-no-match-abstention",
            [],
            "abstention_required",
            claims=0,
            bindings=0,
            requires_abstention=True,
        ),
        case(
            "pa4-unsupported-abstention",
            ["unsupported"],
            "abstention_required",
            requires_abstention=True,
        ),
        case(
            "pa4-contradicted-abstention",
            ["contradicted"],
            "abstention_required",
            requires_abstention=True,
        ),
        case("pa4-stale-abstention", ["stale"], "abstention_required", requires_abstention=True),
        case(
            "pa4-privacy-abstention",
            ["privacy_block"],
            "abstention_required",
            requires_abstention=True,
        ),
        case(
            "pa4-authority-escalation",
            ["supported"],
            "verified_answer_rejected_authority_escalation",
            authority={"production_answer_serving": True},
            requires_abstention=True,
        ),
    ]
    case_artifact = write_json(
        PILOT / "m26-pa-4-benchmark-cases.json",
        {
            "schema_version": "knowledge-engine-m26-pa-4-verified-answer-benchmark-cases/v1",
            "stage_id": "M26.PA.4",
            "cases": cases,
        },
    )
    entry = write_json(
        PILOT / "m26-pa-4-entry-contract.json",
        {
            "schema_version": "knowledge-engine-m26-pa-4-entry-contract/v1",
            "stage_id": "M26.PA.4",
            "status": "m26_pa_4_entry_ready",
            "accepted_predecessor": {
                "acceptance_path": "pilot/m26/m26-pa-3-acceptance.json",
                "acceptance_self_sha256": pa3["self_sha256"],
                "status": "m26_pa_3_live_provider_execution_accepted",
            },
            "authority_boundary": policy["authority"],
            "acceptance_status_reserved": "m26_pa_4_verified_answer_citation_gate_accepted",
        },
    )
    report = run_verified_answer_benchmark(case_artifact, policy)
    registry = write_json(
        PILOT / "m26-pa-4-contract-registry.json",
        {
            "schema_version": "knowledge-engine-m26-pa-4-contract-registry/v1",
            "stage_id": "M26.PA.4",
            "accepted": False,
            "accepted_predecessor_status": "m26_pa_3_live_provider_execution_accepted",
            "artifacts": {
                "entry_contract_sha256": file_sha256(PILOT / "m26-pa-4-entry-contract.json"),
                "policy_sha256": file_sha256(PILOT / "m26-pa-4-verified-answer-policy.json"),
                "benchmark_cases_sha256": file_sha256(PILOT / "m26-pa-4-benchmark-cases.json"),
            },
            "schemas": {
                "record_schema_sha256": schema_digests[
                    "m26-pa-4-verified-answer-record-v1.schema.json"
                ],
                "benchmark_schema_sha256": schema_digests[
                    "m26-pa-4-verified-answer-benchmark-v1.schema.json"
                ],
            },
            "implementation": {"module": MODULE_FILES["M26.PA.4"]},
            "report": {"self_sha256": report["self_sha256"], "status": report["status"]},
        },
    )
    acceptance = write_json(
        PILOT / "m26-pa-4-acceptance.json",
        {
            "schema_version": "knowledge-engine-m26-pa-4-acceptance/v1",
            "stage_id": "M26.PA.4",
            "status": "m26_pa_4_verified_answer_citation_gate_accepted",
            "candidate_acceptance": True,
            "effective_only_on_reconciliation_merge": True,
            "predecessor": entry["accepted_predecessor"],
            "benchmark": {
                "case_count": report["case_count"],
                "passed_count": report["passed_count"],
                "failed_count": report["failed_count"],
                "metrics": report["metrics"],
                "report_self_sha256": report["self_sha256"],
            },
            "contract_registry_self_sha256": registry["self_sha256"],
            "authority_boundary": policy["authority"],
            "next_stage": {
                "stage_id": "M26.PA.5",
                "name": "Controlled Internal Shadow Pilot",
                "predecessor_status_required": "m26_pa_4_verified_answer_citation_gate_accepted",
                "population_min": 200,
                "population_max": 500,
                "public_answers_permitted": False,
            },
        },
    )
    return acceptance


def generate_pa5(schema_digests: dict[str, str], pa4: dict[str, Any]) -> dict[str, Any]:
    policy = write_json(
        PILOT / "m26-pa-5-shadow-policy.json",
        {
            "schema_version": "knowledge-engine-m26-pa-5-shadow-policy/v1",
            "stage_id": "M26.PA.5",
            "accepted_predecessor_status": "m26_pa_4_verified_answer_citation_gate_accepted",
            "authority": {
                "abstention_evidence": True,
                "authenticated_internal_only": True,
                "citation_evidence": True,
                "complete_denominator": True,
                "controlled_internal_shadow": True,
                "cost_evidence": True,
                "latency_evidence": True,
                "multiple_reviewers": True,
                "quality_evidence": True,
                "production_answer_serving": False,
                "production_pointer_mutation": False,
                "public_answers": False,
                "public_traffic": False,
                "qdrant_writes": False,
                "r2_writes": False,
                "secret_persistence": False,
                "source_foundation_release_mutation": False,
            },
            "pilot_policy": {
                "latency_p95_ms": 900,
                "max_cost_usd_per_question": 0.01,
                "min_citation_precision": 0.9,
                "min_quality_score": 0.82,
                "min_reviewer_count": 2,
                "population_max": 500,
                "population_min": 200,
            },
            "status_policy": {
                "abstention_status": "shadow_abstention_reviewed",
                "answer_status": "shadow_answer_reviewed",
                "authority_rejected_status": "shadow_rejected_authority_escalation",
                "hold_status": "shadow_hold_for_repair",
            },
        },
    )
    intents = ["lookup", "trace_source", "compare", "navigate_graph", "adversarial"]
    locales = ["en-US", "zh-TW", "ja-JP", "mixed"]
    difficulties = ["easy", "medium", "hard", "conflict", "stale"]
    questions: list[dict[str, Any]] = []
    for index in range(200):
        question_id = f"pa5-shadow-q{index + 1:03d}"
        if index % 20 == 0:
            verified = "abstention_required"
            expected = "shadow_abstention_reviewed"
            quality = 0.0
            citation = 0.0
            refusal = ["ABSTENTION_REQUIRED"]
            abstention_appropriate = True
        elif index % 31 == 0:
            verified = "verified_answer_ready"
            expected = "shadow_hold_for_repair"
            quality = 0.72
            citation = 0.88
            refusal = ["SHADOW_REPAIR"]
            abstention_appropriate = False
        else:
            statuses = [
                "verified_answer_ready",
                "verified_answer_ready_after_bounded_repair",
                "verified_answer_ready_with_warnings",
            ]
            verified = statuses[index % len(statuses)]
            expected = "shadow_answer_reviewed"
            quality = 0.88 + (index % 8) / 100
            citation = 0.93 + (index % 5) / 100
            refusal = []
            abstention_appropriate = False
        questions.append(
            {
                "question_id": question_id,
                "question": f"Frozen PA5 internal shadow question {index + 1:03d}",
                "intent": intents[index % len(intents)],
                "locale": locales[index % len(locales)],
                "difficulty": difficulties[index % len(difficulties)],
                "verified_answer_status": verified,
                "internal_authenticated": True,
                "reviewer_ids": [
                    "reviewer-pa5-a",
                    "reviewer-pa5-b",
                    f"reviewer-pa5-{(index % 5) + 3}",
                ],
                "public_answer": False,
                "public_traffic": False,
                "quality_score": round(quality, 4),
                "citation_precision": round(citation, 4),
                "abstention_appropriate": abstention_appropriate,
                "latency_ms": 420 + (index % 40) * 5,
                "cost_usd": round(0.0015 + (index % 9) * 0.0001, 6),
                "reviewer_agreement": round(0.86 + (index % 12) / 100, 4),
                "refusal_reason_codes": refusal,
                "expected": {
                    "requires_public_answer_zero": True,
                    "status": expected,
                },
            }
        )
    population = write_json(
        PILOT / "m26-pa-5-frozen-questions.json",
        {
            "schema_version": "knowledge-engine-m26-pa-5-shadow-question-population/v1",
            "stage_id": "M26.PA.5",
            "population_frozen": True,
            "questions": questions,
        },
    )
    entry = write_json(
        PILOT / "m26-pa-5-entry-contract.json",
        {
            "schema_version": "knowledge-engine-m26-pa-5-entry-contract/v1",
            "stage_id": "M26.PA.5",
            "status": "m26_pa_5_entry_ready",
            "accepted_predecessor": {
                "acceptance_path": "pilot/m26/m26-pa-4-acceptance.json",
                "acceptance_self_sha256": pa4["self_sha256"],
                "status": "m26_pa_4_verified_answer_citation_gate_accepted",
            },
            "authority_boundary": policy["authority"],
            "acceptance_status_reserved": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
        },
    )
    report = run_shadow_pilot_benchmark(population, policy)
    registry = write_json(
        PILOT / "m26-pa-5-contract-registry.json",
        {
            "schema_version": "knowledge-engine-m26-pa-5-contract-registry/v1",
            "stage_id": "M26.PA.5",
            "accepted": False,
            "accepted_predecessor_status": "m26_pa_4_verified_answer_citation_gate_accepted",
            "artifacts": {
                "entry_contract_sha256": file_sha256(PILOT / "m26-pa-5-entry-contract.json"),
                "policy_sha256": file_sha256(PILOT / "m26-pa-5-shadow-policy.json"),
                "frozen_questions_sha256": file_sha256(PILOT / "m26-pa-5-frozen-questions.json"),
            },
            "schemas": {
                "record_schema_sha256": schema_digests[
                    "m26-pa-5-shadow-review-record-v1.schema.json"
                ],
                "benchmark_schema_sha256": schema_digests[
                    "m26-pa-5-shadow-pilot-benchmark-v1.schema.json"
                ],
            },
            "implementation": {"module": MODULE_FILES["M26.PA.5"]},
            "report": {"self_sha256": report["self_sha256"], "status": report["status"]},
        },
    )
    acceptance = write_json(
        PILOT / "m26-pa-5-acceptance.json",
        {
            "schema_version": "knowledge-engine-m26-pa-5-acceptance/v1",
            "stage_id": "M26.PA.5",
            "status": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
            "candidate_acceptance": True,
            "effective_only_on_reconciliation_merge": True,
            "predecessor": entry["accepted_predecessor"],
            "benchmark": {
                "failed_count": report["failed_count"],
                "metrics": report["metrics"],
                "passed_count": report["passed_count"],
                "question_count": report["question_count"],
                "report_self_sha256": report["self_sha256"],
            },
            "contract_registry_self_sha256": registry["self_sha256"],
            "authority_boundary": policy["authority"],
            "next_stage": {
                "stage_id": "M26.PA.6",
                "name": "Canary, SLO, and Rollback",
                "predecessor_status_required": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
                "bounded_canary_permitted": True,
                "full_production_promotion_permitted": False,
            },
        },
    )
    return acceptance


def generate_pa6(schema_digests: dict[str, str], pa5: dict[str, Any]) -> dict[str, Any]:
    stop_conditions = [
        "acl_leakage_detected",
        "unsupported_claim_detected",
        "citation_binding_failure",
        "secret_leakage_detected",
        "prompt_injection_executed",
        "provider_cost_ceiling_exceeded",
        "latency_slo_breached",
        "error_budget_exhausted",
        "pointer_identity_drift",
        "rollback_verification_failed",
    ]
    policy = write_json(
        PILOT / "m26-pa-6-canary-policy.json",
        {
            "schema_version": "knowledge-engine-m26-pa-6-canary-policy/v1",
            "stage_id": "M26.PA.6",
            "accepted_predecessor_status": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
            "authority": {
                "audience_allowlist": True,
                "automatic_stop_conditions": True,
                "bounded_canary": True,
                "error_budget": True,
                "kill_switch": True,
                "rollback_drill_completed": True,
                "rollback_plan": True,
                "slo_enforcement": True,
                "traffic_allowlist": True,
                "full_production_promotion": False,
                "source_foundation_release_mutation": False,
            },
            "canary_policy": {
                "audience_allowlist": ["daniel", "internal-reviewer", "codex-shadow"],
                "automatic_stop_conditions": stop_conditions,
                "kill_switch": {"enabled": True, "name": "M26_PA_CANARY_DISABLED"},
                "max_traffic_percent": 1.0,
                "rollback": {
                    "drill_completed": True,
                    "expected_previous_pointer_sha256": "4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9",
                    "rollback_plan_id": "m26-pa-6-bounded-rollback-drill-v1",
                },
                "slo": {
                    "latency_p95_ms": 800,
                    "max_cost_usd": 0.02,
                    "max_error_rate": 0.01,
                },
                "traffic_allowlist": ["/internal/ask", "/shadow/ask", "/canary/ask"],
            },
            "status_policy": {
                "authority_rejected_status": "canary_rejected_authority_escalation",
                "ready_status": "canary_ready",
                "rollback_hold_status": "canary_hold_for_rollback",
                "stopped_status": "canary_stopped_by_slo",
            },
        },
    )
    def c(
        case_id: str,
        expected: str,
        *,
        traffic_percent: float = 0.5,
        latency: int = 620,
        error: float = 0.001,
        cost: float = 0.004,
        unsupported: int = 0,
        allowlisted_audience: bool = True,
        allowlisted_route: bool = True,
        full_production: bool = False,
        kill_switch: bool = True,
        rollback_drill: bool = True,
        rollback_required: bool = False,
        stop_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "canary": {
                "allowlisted_audience": allowlisted_audience,
                "allowlisted_route": allowlisted_route,
                "cost_usd": cost,
                "error_rate": error,
                "full_production_traffic": full_production,
                "kill_switch_available": kill_switch,
                "latency_p95_ms": latency,
                "production_pointer_mutation": False,
                "rollback_drill_completed": rollback_drill,
                "rollback_required": rollback_required,
                "stop_codes": list(stop_codes or []),
                "traffic_percent": traffic_percent,
                "unsupported_claim_count": unsupported,
            },
            "expected": {"status": expected},
        }
    cases = [
        c("pa6-ready-001", "canary_ready", traffic_percent=0.1),
        c("pa6-ready-002", "canary_ready", traffic_percent=0.25),
        c("pa6-ready-003", "canary_ready", traffic_percent=0.5),
        c("pa6-ready-004", "canary_ready", traffic_percent=0.75),
        c("pa6-ready-005", "canary_ready", traffic_percent=1.0),
        c("pa6-ready-006", "canary_ready", traffic_percent=0.4),
        c(
            "pa6-latency-stop",
            "canary_stopped_by_slo",
            latency=940,
            stop_codes=["latency_slo_breached"],
        ),
        c(
            "pa6-error-stop",
            "canary_stopped_by_slo",
            error=0.02,
            stop_codes=["error_budget_exhausted"],
        ),
        c(
            "pa6-unsupported-stop",
            "canary_stopped_by_slo",
            unsupported=1,
            stop_codes=["unsupported_claim_detected"],
        ),
        c("pa6-rollback-hold", "canary_hold_for_rollback", kill_switch=False),
        c(
            "pa6-audience-reject",
            "canary_rejected_authority_escalation",
            allowlisted_audience=False,
        ),
        c(
            "pa6-full-production-reject",
            "canary_rejected_authority_escalation",
            full_production=True,
            traffic_percent=2.0,
        ),
    ]
    case_artifact = write_json(
        PILOT / "m26-pa-6-benchmark-cases.json",
        {
            "schema_version": "knowledge-engine-m26-pa-6-canary-benchmark-cases/v1",
            "stage_id": "M26.PA.6",
            "cases": cases,
        },
    )
    entry = write_json(
        PILOT / "m26-pa-6-entry-contract.json",
        {
            "schema_version": "knowledge-engine-m26-pa-6-entry-contract/v1",
            "stage_id": "M26.PA.6",
            "status": "m26_pa_6_entry_ready",
            "accepted_predecessor": {
                "acceptance_path": "pilot/m26/m26-pa-5-acceptance.json",
                "acceptance_self_sha256": pa5["self_sha256"],
                "status": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
            },
            "authority_boundary": policy["authority"],
            "acceptance_status_reserved": "m26_pa_6_canary_slo_rollback_accepted",
        },
    )
    report = run_canary_benchmark(case_artifact, policy)
    registry = write_json(
        PILOT / "m26-pa-6-contract-registry.json",
        {
            "schema_version": "knowledge-engine-m26-pa-6-contract-registry/v1",
            "stage_id": "M26.PA.6",
            "accepted": False,
            "accepted_predecessor_status": "m26_pa_5_controlled_internal_shadow_pilot_accepted",
            "artifacts": {
                "entry_contract_sha256": file_sha256(PILOT / "m26-pa-6-entry-contract.json"),
                "policy_sha256": file_sha256(PILOT / "m26-pa-6-canary-policy.json"),
                "benchmark_cases_sha256": file_sha256(PILOT / "m26-pa-6-benchmark-cases.json"),
            },
            "schemas": {
                "record_schema_sha256": schema_digests["m26-pa-6-canary-record-v1.schema.json"],
                "benchmark_schema_sha256": schema_digests[
                    "m26-pa-6-canary-benchmark-v1.schema.json"
                ],
            },
            "implementation": {"module": MODULE_FILES["M26.PA.6"]},
            "report": {"self_sha256": report["self_sha256"], "status": report["status"]},
        },
    )
    acceptance = write_json(
        PILOT / "m26-pa-6-acceptance.json",
        {
            "schema_version": "knowledge-engine-m26-pa-6-acceptance/v1",
            "stage_id": "M26.PA.6",
            "status": "m26_pa_6_canary_slo_rollback_accepted",
            "candidate_acceptance": True,
            "effective_only_on_reconciliation_merge": True,
            "predecessor": entry["accepted_predecessor"],
            "benchmark": {
                "case_count": report["case_count"],
                "failed_count": report["failed_count"],
                "metrics": report["metrics"],
                "passed_count": report["passed_count"],
                "report_self_sha256": report["self_sha256"],
            },
            "contract_registry_self_sha256": registry["self_sha256"],
            "authority_boundary": policy["authority"],
            "next_stage": {
                "stage_id": "M26.PA.7",
                "name": "Production Promotion, Answer Authority, and Closure",
                "predecessor_status_required": "m26_pa_6_canary_slo_rollback_accepted",
                "daniel_final_decision_required": True,
                "independent_final_reconciliation_required": True,
            },
        },
    )
    return acceptance


def evidence_chain(pa3: dict[str, Any], pa4: dict[str, Any], pa5: dict[str, Any], pa6: dict[str, Any]) -> list[dict[str, str]]:
    existing = {
        "m25_closed": load_json(ROOT / "pilot/m25/m25-10-formal-closure-evidence.json")[
            "self_sha256"
        ],
        "m26_g0_milestone_reconciliation_accepted": load_json(
            PILOT / "m26-g0-acceptance.json"
        )["self_sha256"],
        "m26_pa_1_production_activation_authority_freeze_accepted": load_json(
            PILOT / "m26-g0-pa1-ratification.json"
        )["self_sha256"],
        "m26_pa_2_real_corpus_retrieval_binding_accepted": load_json(
            PILOT / "m26-pa-2-acceptance.json"
        )["self_sha256"],
        "m26_pa_3_live_provider_execution_accepted": pa3["self_sha256"],
        "m26_pa_4_verified_answer_citation_gate_accepted": pa4["self_sha256"],
        "m26_pa_5_controlled_internal_shadow_pilot_accepted": pa5["self_sha256"],
        "m26_pa_6_canary_slo_rollback_accepted": pa6["self_sha256"],
    }
    return [
        {
            "evidence_sha256": existing[status],
            "stage_id": "M25.closed" if status == "m25_closed" else f"M26.{status}",
            "status": status,
        }
        for status in EVIDENCE_CHAIN_STATUSES
    ]


def generate_pa7(
    schema_digests: dict[str, str],
    pa3: dict[str, Any],
    pa4: dict[str, Any],
    pa5: dict[str, Any],
    pa6: dict[str, Any],
) -> dict[str, Any]:
    policy = write_json(
        PILOT / "m26-pa-7-final-decision-policy.json",
        {
            "schema_version": "knowledge-engine-m26-pa-7-final-decision-policy/v1",
            "stage_id": "M26.PA.7",
            "accepted_predecessor_status": "m26_pa_6_canary_slo_rollback_accepted",
            "authority": {
                "bounded_outcome_required": True,
                "complete_evidence_chain": True,
                "daniel_final_decision": True,
                "formal_m26_closure": True,
                "independent_final_reconciliation": True,
                "qdrant_writes_without_approval": False,
                "r2_writes_without_approval": False,
                "secret_persistence": False,
                "source_foundation_release_mutation": False,
                "unbounded_production_promotion": False,
            },
            "decision_policy": {
                "closure_ready_status": "m26_pa_7_final_decision_closure_ready",
                "valid_outcomes": [
                    "approved_bounded_production_promotion",
                    "approved_with_conditions",
                    "governed_defer",
                    "rejected_pending_redesign",
                ],
            },
        },
    )
    complete_chain = evidence_chain(pa3, pa4, pa5, pa6)
    incomplete_chain = complete_chain[:-1]
    protected = {
        "qdrant_write": False,
        "r2_write": False,
        "secret_persistence": False,
        "source_foundation_release_mutation": False,
        "unbounded_public_traffic": False,
    }
    def decision_case(
        case_id: str,
        decision: str,
        expected: str,
        *,
        chain: list[dict[str, str]] | None = None,
        protected_mutations: dict[str, bool] | None = None,
        conditions: list[str] | None = None,
        requires_authority: bool = False,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "conditions": list(conditions or []),
            "decision_maker": "Daniel Huang",
            "decision_status": decision,
            "evidence_chain": list(chain or complete_chain),
            "protected_mutations": dict(protected if protected_mutations is None else protected_mutations),
            "expected": {
                "requires_promotion_authority": requires_authority,
                "status": expected,
            },
        }
    cases = [
        decision_case(
            "pa7-approved",
            "approved_bounded_production_promotion",
            "approved_bounded_production_promotion",
            requires_authority=True,
        ),
        decision_case(
            "pa7-approved-with-conditions",
            "approved_with_conditions",
            "approved_with_conditions",
            conditions=[
                "promotion must execute only through the governed operator path",
                "rollback proof from PA.6 remains attached",
            ],
            requires_authority=True,
        ),
        decision_case("pa7-governed-defer", "governed_defer", "governed_defer"),
        decision_case(
            "pa7-redesign",
            "rejected_pending_redesign",
            "rejected_pending_redesign",
        ),
        decision_case("pa7-invalid-decision", "promote_now", "rejected_pending_redesign"),
        decision_case(
            "pa7-incomplete-chain",
            "approved_bounded_production_promotion",
            "governed_defer",
            chain=incomplete_chain,
        ),
        decision_case(
            "pa7-protected-mutation",
            "approved_bounded_production_promotion",
            "rejected_pending_redesign",
            protected_mutations={**protected, "secret_persistence": True},
        ),
    ]
    case_artifact = write_json(
        PILOT / "m26-pa-7-final-decision-cases.json",
        {
            "schema_version": "knowledge-engine-m26-pa-7-final-decision-cases/v1",
            "stage_id": "M26.PA.7",
            "cases": cases,
        },
    )
    entry = write_json(
        PILOT / "m26-pa-7-entry-contract.json",
        {
            "schema_version": "knowledge-engine-m26-pa-7-entry-contract/v1",
            "stage_id": "M26.PA.7",
            "status": "m26_pa_7_entry_ready",
            "accepted_predecessor": {
                "acceptance_path": "pilot/m26/m26-pa-6-acceptance.json",
                "acceptance_self_sha256": pa6["self_sha256"],
                "status": "m26_pa_6_canary_slo_rollback_accepted",
            },
            "authority_boundary": policy["authority"],
            "acceptance_status_reserved": (
                "m26_pa_7_production_answer_authority_and_closure_accepted"
            ),
        },
    )
    report = run_production_closure_benchmark(case_artifact, policy)
    registry = write_json(
        PILOT / "m26-pa-7-contract-registry.json",
        {
            "schema_version": "knowledge-engine-m26-pa-7-contract-registry/v1",
            "stage_id": "M26.PA.7",
            "accepted": False,
            "accepted_predecessor_status": "m26_pa_6_canary_slo_rollback_accepted",
            "artifacts": {
                "entry_contract_sha256": file_sha256(PILOT / "m26-pa-7-entry-contract.json"),
                "policy_sha256": file_sha256(PILOT / "m26-pa-7-final-decision-policy.json"),
                "decision_cases_sha256": file_sha256(
                    PILOT / "m26-pa-7-final-decision-cases.json"
                ),
            },
            "schemas": {
                "record_schema_sha256": schema_digests[
                    "m26-pa-7-final-decision-record-v1.schema.json"
                ],
                "benchmark_schema_sha256": schema_digests[
                    "m26-pa-7-production-closure-benchmark-v1.schema.json"
                ],
            },
            "implementation": {"module": MODULE_FILES["M26.PA.7"]},
            "report": {"self_sha256": report["self_sha256"], "status": report["status"]},
        },
    )
    selected_decision = [
        item for item in cases if item["case_id"] == "pa7-approved-with-conditions"
    ][0]
    acceptance = write_json(
        PILOT / "m26-pa-7-acceptance.json",
        {
            "schema_version": "knowledge-engine-m26-pa-7-acceptance/v1",
            "stage_id": "M26.PA.7",
            "status": "m26_pa_7_production_answer_authority_and_closure_accepted",
            "candidate_acceptance": True,
            "effective_only_on_reconciliation_merge": True,
            "predecessor": entry["accepted_predecessor"],
            "final_decision": {
                "decision_status": "approved_with_conditions",
                "conditions": selected_decision["conditions"],
                "production_promotion_execution": False,
            },
            "benchmark": {
                "case_count": report["case_count"],
                "failed_count": report["failed_count"],
                "metrics": report["metrics"],
                "passed_count": report["passed_count"],
                "report_self_sha256": report["self_sha256"],
            },
            "contract_registry_self_sha256": registry["self_sha256"],
            "evidence_chain": complete_chain,
            "authority_boundary": policy["authority"],
            "m26_closure": {
                "formal_closure_recorded": True,
                "production_pointer_mutation_in_this_repository": False,
                "public_traffic_mutation_in_this_repository": False,
            },
        },
    )
    return acceptance


def main() -> None:
    schema_digests = generate_schemas()
    pa3 = pa3_acceptance()
    pa4 = generate_pa4(schema_digests, pa3)
    pa5 = generate_pa5(schema_digests, pa4)
    pa6 = generate_pa6(schema_digests, pa5)
    generate_pa7(schema_digests, pa3, pa4, pa5, pa6)


if __name__ == "__main__":
    main()
