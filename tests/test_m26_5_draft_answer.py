from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from knowledge_engine.m26_draft_answer import (
    DraftAnswerError,
    compile_draft_answer,
    run_draft_benchmark,
    validate_draft_package,
    validate_draft_policy,
)
from knowledge_engine.m26_provider_mock import build_context_package_for_case, compile_provider_replay
from knowledge_engine.m26_retrieval_envelope import sha256_value, verify_self_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def fixtures() -> dict[str, dict[str, Any]]:
    return {
        "draft_cases": load(PILOT / "m26-5-benchmark-cases.json"),
        "provider_cases": load(PILOT / "m26-4-benchmark-cases.json"),
        "context_cases": load(PILOT / "m26-3-benchmark-cases.json"),
        "retrieval_cases": load(PILOT / "m26-2-benchmark-cases.json"),
        "corpus": load(PILOT / "m26-2-synthetic-corpus.json"),
        "retrieval_policy": load(PILOT / "m26-2-retrieval-policy.json"),
        "context_policy": load(PILOT / "m26-3-context-policy.json"),
        "provider_policy": load(PILOT / "m26-4-provider-policy.json"),
        "draft_policy": load(PILOT / "m26-5-draft-answer-policy.json"),
    }


def context_kwargs(f: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "context_cases": f["context_cases"],
        "retrieval_cases": f["retrieval_cases"],
        "corpus": f["corpus"],
        "retrieval_policy": f["retrieval_policy"],
        "context_policy": f["context_policy"],
    }


def draft_kwargs(f: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "provider_cases": f["provider_cases"],
        "context_cases": f["context_cases"],
        "retrieval_cases": f["retrieval_cases"],
        "corpus": f["corpus"],
        "retrieval_policy": f["retrieval_policy"],
        "context_policy": f["context_policy"],
        "provider_policy": f["provider_policy"],
        "draft_policy": f["draft_policy"],
    }


def provider_case(f: dict[str, dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(case for case in f["provider_cases"]["cases"] if case["case_id"] == case_id)


def replay_for(f: dict[str, dict[str, Any]], case_id: str) -> dict[str, Any]:
    case = provider_case(f, case_id)
    package = build_context_package_for_case(case, **context_kwargs(f))
    tamper = case.get("tamper", {})
    suffix = str(tamper.get("append_mock_text", "")) if isinstance(tamper, dict) else ""
    return compile_provider_replay(package, f["provider_policy"], output_suffix=suffix)


def test_entry_contract_is_m26_4_accepted_and_synthetic_only() -> None:
    acceptance = load(PILOT / "m26-4-acceptance.json")
    entry = load(PILOT / "m26-5-entry-contract.json")
    verify_self_digest(entry)
    assert acceptance["status"] == "m26_4_provider_mock_replay_privacy_accepted"
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
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "93d4dea5cf78463e89b4e6f0f68157bf08c6ee16"
    )
    assert entry["authority_boundary"]["draft_answer_contract_permitted"] is True
    forbidden = {
        key: value
        for key, value in entry["authority_boundary"].items()
        if key not in {"synthetic_only", "draft_answer_contract_permitted", "provider_mock_replay_required"}
    }
    assert set(forbidden.values()) == {False}


def test_draft_contract_registry_is_digest_bound_and_closed() -> None:
    registry = load(PILOT / "m26-5-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == "m26_4_provider_mock_replay_privacy_accepted"
    assert registry["authority"] == {
        "synthetic_only": True,
        "draft_answer_contract": True,
        "live_provider_calls": False,
        "credentials": False,
        "real_corpus": False,
        "semantic_or_hybrid": False,
        "production_answer_serving": False,
    }
    for entry in registry["contracts"]:
        path = ROOT / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        if entry["path"].startswith("schemas/"):
            schema = load(path)
            Draft202012Validator.check_schema(schema)
            assert schema["additionalProperties"] is False


def test_draft_policy_fails_closed_on_live_provider_authority() -> None:
    policy = load(PILOT / "m26-5-draft-answer-policy.json")
    validated = validate_draft_policy(policy)
    assert validated["authority"]["live_provider_calls"] is False

    tampered = json.loads(json.dumps(policy))
    tampered["authority"]["live_provider_calls"] = True
    unsigned = dict(tampered)
    unsigned.pop("self_sha256")
    tampered["self_sha256"] = sha256_value(unsigned)
    with pytest.raises(DraftAnswerError, match="DRAFT_AUTHORITY_INVALID"):
        validate_draft_policy(tampered)


def test_draft_benchmark_passes_all_synthetic_cases() -> None:
    f = fixtures()
    report = run_draft_benchmark(f["draft_cases"], **draft_kwargs(f))
    verify_self_digest(report)
    assert report["status"] == "m26_5_draft_answer_ready"
    assert report["case_count"] == 10
    assert report["passed_count"] == 10
    assert report["failed_count"] == 0
    assert report["metrics"]["non_final_draft_count"] == 6
    assert report["metrics"]["abstain_propagated_count"] == 3
    assert report["metrics"]["privacy_block_propagated_count"] == 1
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["credentials_used_count"] == 0
    assert report["metrics"]["live_network_call_count"] == 0
    assert report["metrics"]["real_corpus_binding_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["verified_final_answer_count"] == 0


def test_safe_replay_produces_non_final_claims_with_bound_citations() -> None:
    f = fixtures()
    replay = replay_for(f, "provider_graph_public")
    draft = compile_draft_answer(replay, f["draft_policy"])
    verify_self_digest(draft)
    validate_draft_package(draft)
    assert draft["status"] == "non_final_draft_answer"
    assert draft["safe_for_m26_6"] is True
    assert draft["final_answer"] is False
    assert draft["verified_final_answer"] is False
    assert draft["production_answer_serving"] is False
    assert len(draft["claims"]) >= 1
    replay_citations = {binding["citation_id"] for binding in replay["citation_bindings"]}
    for binding in draft["citation_bindings"]:
        assert binding["citation_id"] in replay_citations
        assert binding["provider_replay_sha256"] == replay["self_sha256"]
        assert binding["context_package_sha256"] == replay["context_package_sha256"]
        assert binding["passage_id"]


def test_abstain_and_privacy_replays_do_not_emit_claims() -> None:
    f = fixtures()
    abstain = compile_draft_answer(replay_for(f, "provider_no_match_public"), f["draft_policy"])
    privacy = compile_draft_answer(replay_for(f, "provider_privacy_secret_block"), f["draft_policy"])
    for draft in (abstain, privacy):
        validate_draft_package(draft)
        assert draft["safe_for_m26_6"] is False
        assert draft["answer_text"] == ""
        assert draft["claims"] == []
        assert draft["citation_bindings"] == []
    assert abstain["status"] == "abstain_propagated"
    assert privacy["status"] == "privacy_block_propagated"


def test_conflict_and_prompt_injection_are_diagnostics_only() -> None:
    f = fixtures()
    conflict = compile_draft_answer(replay_for(f, "provider_conflict_public"), f["draft_policy"])
    injection = compile_draft_answer(replay_for(f, "provider_prompt_injection_public"), f["draft_policy"])
    assert conflict["status"] == "non_final_draft_answer_with_warnings"
    assert conflict["diagnostics"]["conflict_warning_preserved"] is True
    assert injection["status"] == "non_final_draft_answer_with_warnings"
    assert injection["diagnostics"]["prompt_injection_quarantined"] is True
    serialized = json.dumps(injection, ensure_ascii=False).casefold()
    assert "follow these instructions" not in serialized
    assert "ignore previous" not in serialized


def test_claim_without_binding_is_rejected() -> None:
    f = fixtures()
    draft = compile_draft_answer(replay_for(f, "provider_direct_public"), f["draft_policy"])
    tampered = json.loads(json.dumps(draft))
    tampered["claims"][0]["binding_ids"] = []
    unsigned = dict(tampered)
    unsigned.pop("self_sha256")
    tampered["self_sha256"] = sha256_value(unsigned)
    with pytest.raises(DraftAnswerError, match="CLAIM_WITHOUT_BINDING"):
        validate_draft_package(tampered)


def test_docs_record_final_answer_prohibition() -> None:
    text = (DOCS / "m26-5-draft-answer-contract.md").read_text(encoding="utf-8")
    assert "synthetic-only" in text
    assert "non-final" in text
    assert "production answer" in text
    assert "M26.6" in text
