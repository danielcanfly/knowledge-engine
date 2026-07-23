from __future__ import annotations

import hashlib
import json
from pathlib import Path

from knowledge_engine.m26_retrieval_envelope import run_benchmark

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


ACCEPTANCE = load(PILOT / "m26-2-acceptance.json")
POLICY = load(PILOT / "m26-2-retrieval-policy.json")
CORPUS = load(PILOT / "m26-2-synthetic-corpus.json")
CASES = load(PILOT / "m26-2-benchmark-cases.json")


def test_acceptance_identity_and_self_digest() -> None:
    assert ACCEPTANCE["schema_version"] == "knowledge-engine-m26-2-acceptance/v1"
    assert ACCEPTANCE["status"] == "m26_2_retrieval_envelope_accepted"
    unsigned = dict(ACCEPTANCE)
    claimed = unsigned.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert ACCEPTANCE["predecessor"] == {
        "main_seal_sha": "d3cf8cc72d951174f10c0a8328f848143c24e004",
        "status": "m26_1_architecture_authority_accepted",
    }
    assert ACCEPTANCE["implementation"] == {
        "pull_request_number": 1059,
        "base_sha": "d3cf8cc72d951174f10c0a8328f848143c24e004",
        "final_head_sha": "68604fc1d80015ea5706709a1c2eda205bd1feaa",
        "merge_sha": "7507c61f245f1027b1935c8cbcd1826f82d03e52",
        "changed_file_count": 14,
        "unresolved_review_thread_count": 0,
        "expected_head_merge": True,
    }


def test_frozen_artifact_hashes_are_exact() -> None:
    bindings = {
        "retrieval_policy_sha256": PILOT / "m26-2-retrieval-policy.json",
        "synthetic_corpus_sha256": PILOT / "m26-2-synthetic-corpus.json",
        "benchmark_cases_sha256": PILOT / "m26-2-benchmark-cases.json",
        "contract_registry_sha256": PILOT / "m26-2-contract-registry.json",
        "entry_contract_sha256": PILOT / "m26-2-entry-contract.json",
    }
    for key, path in bindings.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ACCEPTANCE[
            "frozen_identities"
        ][key]


def test_deterministic_benchmark_reproduces_accepted_report() -> None:
    report = run_benchmark(CASES, corpus=CORPUS, policy=POLICY)
    assert report["status"] == "m26_2_retrieval_envelope_ready"
    assert report["case_count"] == 9
    assert report["passed_count"] == 9
    assert report["failed_count"] == 0
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == ACCEPTANCE[
        "frozen_identities"
    ]["benchmark_report_sha256"]
    result_by_id = {item["case_id"]: item for item in report["results"]}
    assert result_by_id["no_match_public"]["reason_codes"] == ["NO_MATCH"]
    assert result_by_id["acl_negative_public"]["reason_codes"] == [
        "NO_AUTHORISED_MATCH"
    ]


def test_quality_security_and_latency_gates_are_closed() -> None:
    assert ACCEPTANCE["benchmark"] == {
        "case_count": 9,
        "passed_count": 9,
        "failed_count": 0,
        "case_pass_rate": 1.0,
        "acl_leakage_count": 0,
        "semantic_or_hybrid_use_count": 0,
        "provider_call_count": 0,
        "real_corpus_binding_count": 0,
    }
    assert all(ACCEPTANCE["quality_and_security"].values())
    latency = ACCEPTANCE["latency"]
    assert latency["iterations"] == 100
    assert latency["p95_ms"] < latency["p95_gate_ms"]
    assert latency["max_ms"] < latency["max_gate_ms"]
    assert latency["all_gates_passed"] is True


def test_authority_boundary_and_m26_3_entry() -> None:
    authority = ACCEPTANCE["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert all(value is False for key, value in authority.items() if key != "synthetic_only")
    assert ACCEPTANCE["execution_roles"] == {
        "chatgpt_primary_executor": True,
        "codex_used": False,
        "codex_escalations": 0,
        "daniel_gate_required": False,
    }
    assert ACCEPTANCE["next_stage"] == {
        "authorized": True,
        "stage_id": "M26.3",
        "name": "Context Compiler and Evidence Budgeting",
        "predecessor_status_required": "m26_2_retrieval_envelope_accepted",
        "synthetic_only": True,
        "provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "production_answer_serving_permitted": False,
    }


def test_required_workflow_and_evidence_identities_are_frozen() -> None:
    assert ACCEPTANCE["required_workflows"] == {
        "CI": 29994182155,
        "M17 Architecture Canon Acceptance": 29994182135,
        "M18 Graph v2 acceptance": 29994182171,
        "M26.1 Architecture Authority": 29994182161,
        "M26.2 Retrieval Envelope": 29994182146,
        "R2 Release Integration": 29994182131,
    }
    assert ACCEPTANCE["evidence_artifact"] == {
        "workflow_run_id": 29994182146,
        "artifact_id": 8558250962,
        "name": "m26-2-retrieval-envelope-evidence",
        "digest": "sha256:f6683b286f5db33af3fe0f8f7c05ce40649bd1ca7c9c4c247225980d338e0e8a",
        "retention_days": 30,
    }
