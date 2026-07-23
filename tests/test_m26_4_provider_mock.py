from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_provider_mock import (
    ProviderMockError,
    build_context_package_for_case,
    compile_provider_replay,
    run_provider_benchmark,
    run_provider_case,
    validate_provider_policy,
)
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
        "provider_cases": load(PILOT / "m26-4-benchmark-cases.json"),
        "context_cases": load(PILOT / "m26-3-benchmark-cases.json"),
        "retrieval_cases": load(PILOT / "m26-2-benchmark-cases.json"),
        "corpus": load(PILOT / "m26-2-synthetic-corpus.json"),
        "retrieval_policy": load(PILOT / "m26-2-retrieval-policy.json"),
        "context_policy": load(PILOT / "m26-3-context-policy.json"),
        "provider_policy": load(PILOT / "m26-4-provider-policy.json"),
    }


def provider_kwargs(f: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "context_cases": f["context_cases"],
        "retrieval_cases": f["retrieval_cases"],
        "corpus": f["corpus"],
        "retrieval_policy": f["retrieval_policy"],
        "context_policy": f["context_policy"],
        "provider_policy": f["provider_policy"],
    }


def test_entry_contract_is_m26_3_accepted_and_synthetic_only() -> None:
    acceptance = load(PILOT / "m26-3-acceptance.json")
    entry = load(PILOT / "m26-4-entry-contract.json")
    verify_self_digest(entry)
    assert acceptance["status"] == "m26_3_context_compiler_accepted"
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "7a5b757a227e3d7bd0dd859181fc44511e003420"
    )
    assert entry["accepted_predecessor"]["evidence_artifact_id"] == 8559677787
    assert entry["authority_boundary"]["synthetic_only"] is True
    assert entry["authority_boundary"]["provider_mock_replay_permitted"] is True
    forbidden = {
        key: value
        for key, value in entry["authority_boundary"].items()
        if key not in {"synthetic_only", "provider_mock_replay_permitted"}
    }
    assert set(forbidden.values()) == {False}
    assert entry["next_stage"] == {
        "stage_id": "M26.5",
        "authorized": False,
        "requires_status": "m26_4_provider_mock_replay_privacy_accepted",
    }


def test_provider_contract_registry_is_digest_bound_and_closed() -> None:
    registry = load(PILOT / "m26-4-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == "m26_3_context_compiler_accepted"
    assert registry["authority"] == {
        "synthetic_only": True,
        "provider_mock_replay": True,
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
            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False


def test_provider_policy_fails_closed_on_live_provider_authority() -> None:
    policy = load(PILOT / "m26-4-provider-policy.json")
    validated = validate_provider_policy(policy)
    assert validated["authority"]["live_provider_calls"] is False
    assert validated["mock_runtime"]["network"] is False

    tampered = json.loads(json.dumps(policy))
    tampered["authority"]["live_provider_calls"] = True
    unsigned = dict(tampered)
    unsigned.pop("self_sha256")
    tampered["self_sha256"] = sha256_value(unsigned)
    with pytest.raises(ProviderMockError, match="PROVIDER_AUTHORITY_INVALID"):
        validate_provider_policy(tampered)


def test_provider_benchmark_passes_all_synthetic_cases() -> None:
    f = fixtures()
    report = run_provider_benchmark(f["provider_cases"], **provider_kwargs(f))
    verify_self_digest(report)
    assert report["status"] == "m26_4_provider_mock_ready"
    assert report["case_count"] == 10
    assert report["passed_count"] == 10
    assert report["failed_count"] == 0
    assert report["metrics"]["mock_draft_count"] == 6
    assert report["metrics"]["abstain_replay_count"] == 3
    assert report["metrics"]["privacy_blocked_count"] == 1
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["credentials_used_count"] == 0
    assert report["metrics"]["live_network_call_count"] == 0
    assert report["metrics"]["real_corpus_binding_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0


def test_safe_context_package_produces_non_final_mock_draft_with_bound_citations() -> None:
    f = fixtures()
    provider_case = next(
        case for case in f["provider_cases"]["cases"] if case["case_id"] == "provider_graph_public"
    )
    package = build_context_package_for_case(
        provider_case,
        context_cases=f["context_cases"],
        retrieval_cases=f["retrieval_cases"],
        corpus=f["corpus"],
        retrieval_policy=f["retrieval_policy"],
        context_policy=f["context_policy"],
    )
    replay = compile_provider_replay(package, f["provider_policy"])
    verify_self_digest(replay)
    assert replay["status"] == "mock_draft"
    assert replay["safe_for_m26_5"] is True
    assert replay["provider_called"] is False
    assert replay["credentials_used"] is False
    assert replay["network_called"] is False
    assert replay["production_answer_serving"] is False
    assert replay["mock_draft"]["non_final"] is True
    selected = set(package["context_manifest"]["selected_passage_ids"])
    assert replay["citation_bindings"]
    assert all(binding["passage_id"] in selected for binding in replay["citation_bindings"])


def test_abstain_context_is_replayed_without_mock_draft_or_provider_call() -> None:
    f = fixtures()
    provider_case = next(
        case
        for case in f["provider_cases"]["cases"]
        if case["case_id"] == "provider_acl_negative_public"
    )
    result = run_provider_case(provider_case, **provider_kwargs(f))
    assert result["passed"] is True
    assert result["status"] == "abstain_replayed"
    assert result["safe_for_m26_5"] is False
    assert result["citation_count"] == 0
    assert result["provider_called"] is False


def test_conflict_and_prompt_injection_replays_preserve_warnings_without_raw_instructions() -> None:
    f = fixtures()
    conflict_case = next(
        case for case in f["provider_cases"]["cases"] if case["case_id"] == "provider_conflict_public"
    )
    conflict = run_provider_case(conflict_case, **provider_kwargs(f))
    assert conflict["passed"] is True
    assert conflict["status"] == "mock_draft_with_warnings"
    assert "CONFLICTING_EVIDENCE" in conflict["reason_codes"]

    injection_case = next(
        case
        for case in f["provider_cases"]["cases"]
        if case["case_id"] == "provider_prompt_injection_public"
    )
    package = build_context_package_for_case(
        injection_case,
        context_cases=f["context_cases"],
        retrieval_cases=f["retrieval_cases"],
        corpus=f["corpus"],
        retrieval_policy=f["retrieval_policy"],
        context_policy=f["context_policy"],
    )
    replay = compile_provider_replay(package, f["provider_policy"])
    assert replay["status"] == "mock_draft_with_warnings"
    assert replay["replay_diagnostics"]["prompt_injection_quarantined"] is True
    serialized = json.dumps(replay, ensure_ascii=False).casefold()
    assert "follow these instructions" not in serialized
    assert "ignore previous" not in serialized


def test_privacy_review_blocks_secret_like_mock_output() -> None:
    f = fixtures()
    provider_case = next(
        case
        for case in f["provider_cases"]["cases"]
        if case["case_id"] == "provider_privacy_secret_block"
    )
    result = run_provider_case(provider_case, **provider_kwargs(f))
    assert result["passed"] is True
    assert result["status"] == "privacy_blocked"
    assert result["safe_for_m26_5"] is False
    assert result["privacy_status"] == "blocked"


def test_docs_pin_stop_lines_and_downstream_boundary() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in DOCS.glob("m26-4-*.md"))
    lowered = text.lower()
    assert "does not call a live provider" in lowered
    assert "does not authorise live provider calls" in lowered
    assert "source, foundation, release, production pointer" in lowered
    assert "m26_4_provider_mock_replay_privacy_accepted" in text
