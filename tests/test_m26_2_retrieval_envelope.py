from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine.m26_retrieval_envelope import (
    RetrievalEnvelopeError,
    assemble_retrieval_envelope,
    build_retrieval_plan,
    run_benchmark,
    sha256_value,
    with_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"


def load(name: str) -> dict:
    value = json.loads((PILOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


POLICY = load("m26-2-retrieval-policy.json")
CORPUS = load("m26-2-synthetic-corpus.json")
CASES = load("m26-2-benchmark-cases.json")


def case(case_id: str) -> dict:
    return next(item for item in CASES["cases"] if item["case_id"] == case_id)


def execute(case_id: str) -> tuple[dict, dict, dict, dict]:
    request = case(case_id)["request"]
    plan = build_retrieval_plan(request, POLICY)
    envelope, trace, gap = assemble_retrieval_envelope(request, plan, CORPUS, POLICY)
    return request, plan, envelope, trace | {"gap": gap}


def test_full_synthetic_benchmark_is_green_and_deterministic() -> None:
    first = run_benchmark(CASES, corpus=CORPUS, policy=POLICY)
    second = run_benchmark(CASES, corpus=CORPUS, policy=POLICY)
    assert first == second
    assert first["status"] == "m26_2_retrieval_envelope_ready"
    assert first["case_count"] == 9
    assert first["passed_count"] == 9
    assert first["failed_count"] == 0
    assert first["metrics"] == {
        "case_pass_rate": 1.0,
        "acl_leakage_count": 0,
        "semantic_or_hybrid_use_count": 0,
        "provider_call_count": 0,
        "real_corpus_binding_count": 0,
    }
    assert first["authority"]["m26_3_authorized"] is False


def test_direct_and_m26_1_compat_cases_keep_exact_passages() -> None:
    for case_id in ("direct_public", "m26_1_fixture_compat"):
        _, plan, envelope, merged = execute(case_id)
        gap = merged["gap"]
        assert envelope["sufficiency"] == "sufficient"
        assert envelope["passages"]
        assert envelope["retrieval_plan_sha256"] == sha256_value(plan)
        for passage in envelope["passages"]:
            assert hashlib.sha256(passage["text"].encode()).hexdigest() == passage["text_sha256"]
            assert passage["locator"]["start_line"] is not None
            assert passage["locator"]["end_line"] is not None
            assert passage["audience"] == "public"
        assert gap["safe_for_context_compiler"] is True


def test_multi_facet_query_covers_depth_instead_of_thin_answer_input() -> None:
    _, _, envelope, merged = execute("multi_facet_internal")
    gap = merged["gap"]
    assert envelope["sufficiency"] == "sufficient"
    assert set(gap["covered_facets"]) == {
        "answer_completeness",
        "citation_support",
        "latency",
        "retrieval_contract",
    }
    assert gap["missing_facets"] == []
    concepts = {passage["concept_id"] for passage in envelope["passages"]}
    assert {
        "concepts/retrieval-envelope",
        "concepts/citation-verification",
        "concepts/answer-completeness",
        "concepts/latency-budget",
    } <= concepts


def test_graph_path_is_discovery_metadata_not_factual_support() -> None:
    _, _, envelope, _ = execute("graph_public")
    assert envelope["relation_paths"]
    assert all(path["depth"] == 1 for path in envelope["relation_paths"])
    assert all(path["factual_support"] is False for path in envelope["relation_paths"])
    path_ids = {path["path_id"] for path in envelope["relation_paths"]}
    assert any(set(passage["relation_path_ids"]) & path_ids for passage in envelope["passages"])


def test_acl_is_applied_before_text_exposure() -> None:
    _, _, envelope, merged = execute("acl_negative_public")
    gap = merged["gap"]
    serialized = json.dumps(envelope, ensure_ascii=False).casefold()
    assert envelope["sufficiency"] == "no_match"
    assert envelope["passages"] == []
    assert envelope["population"]["acl_filtered"] >= 1
    assert "visible only to the restricted audience" not in serialized
    assert "restricted operator procedure" not in serialized
    assert gap["first_divergent_stage"] == "candidate_recall"
    assert "NO_AUTHORISED_MATCH" in gap["reason_codes"]


def test_stale_conflict_injection_and_no_match_are_distinct() -> None:
    _, _, stale, stale_merged = execute("stale_public")
    assert stale["sufficiency"] == "insufficient"
    assert any(item["reason"] == "stale" for item in stale["excluded_evidence"])
    assert "NO_EXACT_PASSAGE" in stale_merged["gap"]["reason_codes"]

    _, _, conflict, conflict_merged = execute("conflict_public")
    assert conflict["sufficiency"] == "conflicting"
    assert "CONFLICTING_EVIDENCE" in conflict_merged["gap"]["reason_codes"]

    _, _, injection, injection_merged = execute("prompt_injection_public")
    signals = {
        signal
        for passage in injection["passages"]
        for signal in passage["prompt_injection_signals"]
    }
    assert {"ignore_previous", "system_prompt_request"} <= signals
    assert "PROMPT_INJECTION_SIGNAL_PRESENT" in injection_merged["gap"]["reason_codes"]

    _, _, missing, missing_merged = execute("no_match_public")
    assert missing["sufficiency"] == "no_match"
    assert missing["population"]["acl_filtered"] == 0
    assert missing_merged["gap"]["reason_codes"] == ["NO_MATCH"]


def test_secret_like_passage_is_excluded_without_logging_value() -> None:
    corpus = copy.deepcopy(CORPUS)
    source = next(
        item
        for item in corpus["source_documents"]
        if item["source_id"] == "src-retrieval"
    )
    source["text"] = source["text"] + "\n" + "pass" + "word=fixture-secret-value"
    source["content_sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    source["snapshot_sha256"] = hashlib.sha256(("snapshot:" + source["text"]).encode()).hexdigest()
    source["default_locator"]["end_line"] = len(source["text"].splitlines())
    record = next(
        item
        for item in corpus["provenance"]["records"]
        if item["subject"]["concept_id"] == "concepts/retrieval-envelope"
    )
    record["sources"][0]["content_sha256"] = source["content_sha256"]
    record["claims"][0]["evidence"][0]["locator"]["end_line"] = len(source["text"].splitlines())
    unsigned = dict(corpus)
    unsigned.pop("self_sha256")
    corpus = with_self_digest(unsigned)
    request = case("direct_public")["request"]
    plan = build_retrieval_plan(request, POLICY)
    envelope, _, _ = assemble_retrieval_envelope(request, plan, corpus, POLICY)
    serialized = json.dumps(envelope, ensure_ascii=False)
    assert "fixture-secret-value" not in serialized
    assert any(item["reason"] == "unsafe" for item in envelope["excluded_evidence"])


def test_population_accounting_has_no_silent_exclusion() -> None:
    for item in CASES["cases"]:
        request = item["request"]
        plan = build_retrieval_plan(request, POLICY)
        envelope, _, _ = assemble_retrieval_envelope(request, plan, CORPUS, POLICY)
        population = envelope["population"]
        assert population["retrieved"] == (
            population["included"] + population["excluded"] + population["acl_filtered"]
        )
        assert len(envelope["passages"]) == population["included"]
        assert len(envelope["excluded_evidence"]) == (
            population["excluded"] + population["acl_filtered"]
        )


def test_release_drift_unknown_fields_and_authority_escalation_fail_closed() -> None:
    request = copy.deepcopy(case("direct_public")["request"])
    request["release"]["manifest_sha256"] = "9" * 64
    plan = build_retrieval_plan(request, POLICY)
    with pytest.raises(RetrievalEnvelopeError, match="RELEASE_IDENTITY_MISMATCH"):
        assemble_retrieval_envelope(request, plan, CORPUS, POLICY)

    request = copy.deepcopy(case("direct_public")["request"])
    request["unexpected"] = True
    with pytest.raises(RetrievalEnvelopeError, match="QUESTION_REQUEST_INVALID"):
        build_retrieval_plan(request, POLICY)

    request = copy.deepcopy(case("direct_public")["request"])
    request["policy"]["tool_calls"] = True
    with pytest.raises(RetrievalEnvelopeError, match="QUESTION_AUTHORITY_ESCALATION"):
        build_retrieval_plan(request, POLICY)
