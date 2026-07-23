from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m26_retrieval_envelope import sha256_value, verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_m26_5_acceptance_contract_is_self_digest_bound() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    verify_self_digest(acceptance)
    unsigned = dict(acceptance)
    claimed = unsigned.pop("self_sha256")
    assert claimed == sha256_value(unsigned)
    assert acceptance["status"] == "m26_5_draft_answer_contract_accepted"


def test_m26_5_acceptance_records_exact_implementation_chain() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    assert acceptance["predecessor"] == {
        "status": "m26_4_provider_mock_replay_privacy_accepted",
        "main_seal_sha": "93d4dea5cf78463e89b4e6f0f68157bf08c6ee16",
    }
    assert acceptance["implementation"] == {
        "pull_request_number": 1074,
        "base_sha": "4862761c2b90fbe5074f964bc234c42cce5bb5d5",
        "accepted_predecessor_main_seal_sha": "93d4dea5cf78463e89b4e6f0f68157bf08c6ee16",
        "final_head_sha": "488ccee804a31130311a5ec3ddb1aff908f5b332",
        "merge_sha": "f94f1ff4ccb8162b4e60112ccbd20c69744949c6",
        "expected_head_merge": True,
        "changed_file_count": 11,
        "unresolved_review_thread_count": 0,
    }
    assert acceptance["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1072,
        "state": "closed",
        "state_reason": "completed",
    }


def test_m26_5_frozen_identities_match_artifacts() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    frozen = acceptance["frozen_identities"]
    expected = {
        "benchmark_cases_sha256": "pilot/m26/m26-5-benchmark-cases.json",
        "draft_policy_sha256": "pilot/m26/m26-5-draft-answer-policy.json",
        "entry_contract_sha256": "pilot/m26/m26-5-entry-contract.json",
        "citation_binding_schema_sha256": "schemas/m26-citation-binding-v1.schema.json",
        "draft_answer_schema_sha256": "schemas/m26-5-draft-answer-v1.schema.json",
    }
    for key, path in expected.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == frozen[key]
    registry = load(PILOT / "m26-5-contract-registry.json")
    assert registry["self_sha256"] == frozen["contract_registry_self_sha256"]


def test_m26_5_acceptance_authority_and_benchmark_are_closed() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    assert acceptance["benchmark"] == {
        "case_count": 10,
        "passed_count": 10,
        "failed_count": 0,
        "non_final_draft_count": 6,
        "abstain_propagated_count": 3,
        "privacy_block_propagated_count": 1,
        "provider_call_count": 0,
        "credentials_used_count": 0,
        "live_network_call_count": 0,
        "real_corpus_binding_count": 0,
        "semantic_or_hybrid_use_count": 0,
        "production_answer_serving_count": 0,
        "verified_final_answer_count": 0,
    }
    authority = acceptance["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["draft_answer_contract"] is True
    assert authority["provider_mock_replay_required"] is True
    forbidden = {
        key: value
        for key, value in authority.items()
        if key not in {"synthetic_only", "draft_answer_contract", "provider_mock_replay_required"}
    }
    assert set(forbidden.values()) == {False}


def test_m26_5_acceptance_next_stage_is_limited() -> None:
    acceptance = load(PILOT / "m26-5-acceptance.json")
    assert acceptance["next_stage"] == {
        "stage_id": "M26.6",
        "name": "Synthetic Answer Evaluation and Refusal Gate",
        "authorized": True,
        "predecessor_status_required": "m26_5_draft_answer_contract_accepted",
        "synthetic_only": True,
        "answer_evaluation_permitted": True,
        "refusal_gate_permitted": True,
        "live_provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "production_answer_serving_permitted": False,
        "verified_final_answer_permitted": False,
    }
