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


def test_m26_4_acceptance_contract_is_self_digest_bound() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    verify_self_digest(acceptance)
    unsigned = dict(acceptance)
    claimed = unsigned.pop("self_sha256")
    assert claimed == sha256_value(unsigned)
    assert acceptance["status"] == "m26_4_provider_mock_replay_privacy_accepted"


def test_m26_4_acceptance_records_exact_implementation_chain() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    assert acceptance["predecessor"] == {
        "status": "m26_3_context_compiler_accepted",
        "main_seal_sha": "7a5b757a227e3d7bd0dd859181fc44511e003420",
    }
    assert acceptance["implementation"] == {
        "pull_request_number": 1069,
        "base_sha": "7a5b757a227e3d7bd0dd859181fc44511e003420",
        "final_head_sha": "e4155ec6597a1e4d1585ea5a8dd303ff96a40a39",
        "merge_sha": "ddc5ea7ad2e3a8bb1742a0ebc00ac8e320bf7870",
        "expected_head_merge": True,
        "changed_file_count": 11,
        "unresolved_review_thread_count": 0,
    }
    assert acceptance["issue"] == {
        "repository": "danielcanfly/knowledge-engine",
        "number": 1068,
        "state": "closed",
        "state_reason": "completed",
    }


def test_m26_4_frozen_identities_match_artifacts() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    frozen = acceptance["frozen_identities"]
    expected = {
        "benchmark_cases_sha256": "pilot/m26/m26-4-benchmark-cases.json",
        "entry_contract_sha256": "pilot/m26/m26-4-entry-contract.json",
        "provider_policy_sha256": "pilot/m26/m26-4-provider-policy.json",
        "privacy_review_schema_sha256": "schemas/m26-privacy-review-v1.schema.json",
        "provider_replay_schema_sha256": "schemas/m26-provider-replay-v1.schema.json",
    }
    for key, path in expected.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == frozen[key]
    registry = load(PILOT / "m26-4-contract-registry.json")
    assert registry["self_sha256"] == frozen["contract_registry_self_sha256"]


def test_m26_4_acceptance_authority_and_benchmark_are_closed() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    assert acceptance["benchmark"] == {
        "case_count": 10,
        "passed_count": 10,
        "failed_count": 0,
        "mock_draft_count": 6,
        "abstain_replay_count": 3,
        "privacy_blocked_count": 1,
        "provider_call_count": 0,
        "credentials_used_count": 0,
        "live_network_call_count": 0,
        "real_corpus_binding_count": 0,
        "semantic_or_hybrid_use_count": 0,
        "production_answer_serving_count": 0,
    }
    authority = acceptance["authority_boundary"]
    assert authority["synthetic_only"] is True
    assert authority["provider_mock_replay"] is True
    allowed_true = {"synthetic_only", "provider_mock_replay"}
    forbidden = {
        key: value
        for key, value in authority.items()
        if key not in allowed_true
    }
    assert set(forbidden.values()) == {False}


def test_m26_4_acceptance_next_stage_is_limited() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    assert acceptance["next_stage"] == {
        "stage_id": "M26.5",
        "name": "Draft Answer Contract and Citation Binding",
        "authorized": True,
        "predecessor_status_required": "m26_4_provider_mock_replay_privacy_accepted",
        "synthetic_only": True,
        "draft_answer_contract_permitted": True,
        "live_provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "production_answer_serving_permitted": False,
    }
