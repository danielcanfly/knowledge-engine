from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.m26_context_compiler import (
    ContextCompilerError,
    compile_context_package,
    run_context_benchmark,
    run_context_case,
    validate_context_policy,
)
from knowledge_engine.m26_retrieval_envelope import (
    assemble_retrieval_envelope,
    build_retrieval_plan,
    sha256_value,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_entry_contract_is_m26_2_accepted_and_synthetic_only() -> None:
    acceptance = load(PILOT / "m26-2-acceptance.json")
    entry = load(PILOT / "m26-3-entry-contract.json")
    verify_self_digest(entry)
    assert acceptance["status"] == "m26_2_retrieval_envelope_accepted"
    assert entry["accepted_predecessor"]["final_main_seal"] == (
        "31d6aa093181cb9efbf48d1da70c70ae9181773b"
    )
    assert entry["accepted_predecessor"]["evidence_artifact_id"] == 8558250962
    assert entry["authority_boundary"]["synthetic_only"] is True
    forbidden = {
        key: value
        for key, value in entry["authority_boundary"].items()
        if key != "synthetic_only"
    }
    assert set(forbidden.values()) == {False}
    assert entry["next_stage"] == {
        "stage_id": "M26.4",
        "authorized": False,
        "requires_status": "m26_3_context_compiler_accepted",
    }


def test_context_contract_registry_is_digest_bound_and_closed() -> None:
    registry = load(PILOT / "m26-3-contract-registry.json")
    verify_self_digest(registry)
    assert registry["accepted_predecessor_status"] == "m26_2_retrieval_envelope_accepted"
    assert registry["authority"] == {
        "synthetic_only": True,
        "provider_calls": False,
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


def test_context_policy_fails_closed_on_forbidden_authority() -> None:
    policy = load(PILOT / "m26-3-context-policy.json")
    validated = validate_context_policy(policy)
    assert validated["authority"]["provider_calls"] is False

    tampered = json.loads(json.dumps(policy))
    tampered["authority"]["provider_calls"] = True
    unsigned = dict(tampered)
    unsigned.pop("self_sha256")
    tampered["self_sha256"] = sha256_value(unsigned)
    with pytest.raises(ContextCompilerError, match="CONTEXT_AUTHORITY_INVALID"):
        validate_context_policy(tampered)


def test_context_benchmark_passes_all_synthetic_cases() -> None:
    report = run_context_benchmark(
        load(PILOT / "m26-3-benchmark-cases.json"),
        retrieval_cases=load(PILOT / "m26-2-benchmark-cases.json"),
        corpus=load(PILOT / "m26-2-synthetic-corpus.json"),
        retrieval_policy=load(PILOT / "m26-2-retrieval-policy.json"),
        context_policy=load(PILOT / "m26-3-context-policy.json"),
    )
    verify_self_digest(report)
    assert report["status"] == "m26_3_context_compiler_ready"
    assert report["case_count"] == 9
    assert report["passed_count"] == 9
    assert report["failed_count"] == 0
    assert report["metrics"]["provider_call_count"] == 0
    assert report["metrics"]["real_corpus_binding_count"] == 0
    assert report["metrics"]["semantic_or_hybrid_use_count"] == 0
    assert report["metrics"]["production_answer_serving_count"] == 0
    assert report["metrics"]["compiled_context_count"] == 6
    assert report["metrics"]["abstain_required_count"] == 3


def test_conflicting_evidence_is_mandatory_and_cited() -> None:
    context_case = next(
        case
        for case in load(PILOT / "m26-3-benchmark-cases.json")["cases"]
        if case["case_id"] == "context_conflict_public"
    )
    result = run_context_case(
        context_case,
        retrieval_cases=load(PILOT / "m26-2-benchmark-cases.json"),
        corpus=load(PILOT / "m26-2-synthetic-corpus.json"),
        retrieval_policy=load(PILOT / "m26-2-retrieval-policy.json"),
        context_policy=load(PILOT / "m26-3-context-policy.json"),
    )
    assert result["passed"] is True
    assert result["status"] == "compiled_with_warnings"
    assert "CONFLICTING_EVIDENCE" in result["reason_codes"]

    retrieval_case = next(
        case
        for case in load(PILOT / "m26-2-benchmark-cases.json")["cases"]
        if case["case_id"] == "conflict_public"
    )
    plan = build_retrieval_plan(
        retrieval_case["request"],
        load(PILOT / "m26-2-retrieval-policy.json"),
    )
    envelope, _trace, gap = assemble_retrieval_envelope(
        retrieval_case["request"],
        plan,
        load(PILOT / "m26-2-synthetic-corpus.json"),
        load(PILOT / "m26-2-retrieval-policy.json"),
    )
    package = compile_context_package(envelope, gap, load(PILOT / "m26-3-context-policy.json"))
    manifest = package["context_manifest"]
    assert manifest is not None
    assert set(manifest["mandatory_conflict_passage_ids"]) <= set(manifest["selected_passage_ids"])
    assert len(package["citations"]) >= 2
    assert all(
        citation["passage_id"] in manifest["selected_passage_ids"]
        for citation in package["citations"]
    )


def test_acl_no_match_does_not_leak_restricted_text() -> None:
    context_case = next(
        case
        for case in load(PILOT / "m26-3-benchmark-cases.json")["cases"]
        if case["case_id"] == "context_acl_negative_public"
    )
    result = run_context_case(
        context_case,
        retrieval_cases=load(PILOT / "m26-2-benchmark-cases.json"),
        corpus=load(PILOT / "m26-2-synthetic-corpus.json"),
        retrieval_policy=load(PILOT / "m26-2-retrieval-policy.json"),
        context_policy=load(PILOT / "m26-3-context-policy.json"),
    )
    assert result["passed"] is True
    assert result["status"] == "abstain_required"
    assert result["safe_for_provider_mock"] is False


def test_prompt_injection_is_quarantined_as_evidence_not_instruction() -> None:
    retrieval_case = next(
        case
        for case in load(PILOT / "m26-2-benchmark-cases.json")["cases"]
        if case["case_id"] == "prompt_injection_public"
    )
    policy = load(PILOT / "m26-2-retrieval-policy.json")
    plan = build_retrieval_plan(retrieval_case["request"], policy)
    envelope, _trace, gap = assemble_retrieval_envelope(
        retrieval_case["request"],
        plan,
        load(PILOT / "m26-2-synthetic-corpus.json"),
        policy,
    )
    package = compile_context_package(envelope, gap, load(PILOT / "m26-3-context-policy.json"))
    assert package["status"] == "compiled_with_warnings"
    assert package["diagnostics"]["prompt_injection_quarantined"] is True
    system_text = package["instruction_blocks"][0]["text"].lower()
    assert "not instructions" in system_text
    assert package["provider_calls"] is False


def test_budget_too_small_for_mandatory_conflict_forces_abstention() -> None:
    retrieval_case = next(
        case
        for case in load(PILOT / "m26-2-benchmark-cases.json")["cases"]
        if case["case_id"] == "conflict_public"
    )
    retrieval_policy = load(PILOT / "m26-2-retrieval-policy.json")
    plan = build_retrieval_plan(retrieval_case["request"], retrieval_policy)
    envelope, _trace, gap = assemble_retrieval_envelope(
        retrieval_case["request"],
        plan,
        load(PILOT / "m26-2-synthetic-corpus.json"),
        retrieval_policy,
    )
    context_policy = load(PILOT / "m26-3-context-policy.json")
    context_policy["bounds"]["default_token_budget"] = 128
    unsigned = dict(context_policy)
    unsigned.pop("self_sha256")
    context_policy["self_sha256"] = sha256_value(unsigned)
    package = compile_context_package(envelope, gap, context_policy)
    assert package["status"] == "abstain_required"
    assert package["safe_for_provider_mock"] is False
    assert package["context_manifest"] is None


def test_docs_pin_stop_lines_and_downstream_boundary() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in DOCS.glob("m26-3-*.md"))
    lowered = text.lower()
    assert "does not call a provider" in lowered
    assert "does not authorise live provider calls" in lowered or "does not authorise" in lowered
    assert "source, foundation, release, production pointer" in lowered
    assert "m26_3_context_compiler_accepted" in text
