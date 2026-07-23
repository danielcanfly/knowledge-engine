from __future__ import annotations

import hashlib
import json
from pathlib import Path

from knowledge_engine.m26_retrieval_envelope import (
    assemble_retrieval_envelope,
    build_retrieval_plan,
    run_benchmark,
    verify_self_digest,
)
from test_m26_1_architecture_authority import validate

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
DOCS = ROOT / "docs" / "architecture" / "m26"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


POLICY = load(PILOT / "m26-2-retrieval-policy.json")
CORPUS = load(PILOT / "m26-2-synthetic-corpus.json")
CASES = load(PILOT / "m26-2-benchmark-cases.json")
REGISTRY = load(PILOT / "m26-2-contract-registry.json")
ENTRY = load(PILOT / "m26-2-entry-contract.json")


def test_m26_1_acceptance_exactly_authorises_synthetic_m26_2() -> None:
    acceptance = load(PILOT / "m26-1-acceptance.json")
    assert acceptance["status"] == "m26_1_architecture_authority_accepted"
    assert acceptance["next_stage"] == {
        "authorized": True,
        "name": "Retrieval Envelope and Evidence Assembly",
        "predecessor_status_required": "m26_1_architecture_authority_accepted",
        "provider_calls_permitted": False,
        "real_corpus_binding_permitted": False,
        "stage_id": "M26.2",
    }
    assert acceptance["authority_boundary"]["provider_calls"] is False
    assert acceptance["authority_boundary"]["real_corpus_bound"] is False


def test_policy_corpus_and_cases_are_digest_bound_and_default_deny() -> None:
    for artifact in (POLICY, CORPUS, CASES, REGISTRY, ENTRY):
        verify_self_digest(artifact)
    assert POLICY["entry_main_sha"] == "d3cf8cc72d951174f10c0a8328f848143c24e004"
    assert POLICY["authority"] == {
        "synthetic_only": True,
        "real_corpus_binding": False,
        "authoritative_retrieval_lane": "lexical",
        "provider_calls": False,
        "semantic_retrieval": False,
        "hybrid_retrieval": False,
        "production_answer_serving": False,
        "source_mutation": False,
        "release_mutation": False,
        "qdrant_or_r2_mutation": False,
    }
    assert POLICY["security"]["raw_fallback"] is False
    assert CORPUS["synthetic"] is True
    assert CORPUS["real_corpus"] is False
    assert CASES["authority"]["provider_calls"] is False
    assert CASES["authority"]["semantic_or_hybrid"] is False
    assert ENTRY["predecessor_status"] == "m26_1_architecture_authority_accepted"
    assert ENTRY["target_status"] == "m26_2_retrieval_envelope_accepted"
    assert ENTRY["next_stage"]["authorized"] is False
    for contract in REGISTRY["contracts"]:
        path = ROOT / contract["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == contract["sha256"]


def test_new_schemas_are_closed_draft_2020_12_contracts() -> None:
    for name in (
        "m26-retrieval-trace-v1.schema.json",
        "m26-retrieval-gap-report-v1.schema.json",
        "m26-synthetic-corpus-v1.schema.json",
    ):
        schema = load(SCHEMAS / name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_generated_m26_1_and_m26_2_contracts_validate() -> None:
    request = CASES["cases"][0]["request"]
    plan = build_retrieval_plan(request, POLICY)
    envelope, trace, gap = assemble_retrieval_envelope(request, plan, CORPUS, POLICY)
    validate(request, load(SCHEMAS / "m26-question-request-v1.schema.json"))
    validate(plan, load(SCHEMAS / "m26-retrieval-plan-v1.schema.json"))
    validate(envelope, load(SCHEMAS / "m26-evidence-envelope-v1.schema.json"))
    validate(trace, load(SCHEMAS / "m26-retrieval-trace-v1.schema.json"))
    validate(gap, load(SCHEMAS / "m26-retrieval-gap-report-v1.schema.json"))
    validate(CORPUS, load(SCHEMAS / "m26-synthetic-corpus-v1.schema.json"))


def test_benchmark_population_covers_required_failure_classes() -> None:
    ids = {item["case_id"] for item in CASES["cases"]}
    assert ids == {
        "direct_public",
        "m26_1_fixture_compat",
        "multi_facet_internal",
        "graph_public",
        "acl_negative_public",
        "stale_public",
        "conflict_public",
        "prompt_injection_public",
        "no_match_public",
    }
    report = run_benchmark(CASES, corpus=CORPUS, policy=POLICY)
    assert report["status"] == "m26_2_retrieval_envelope_ready"
    assert all(item["passed"] for item in report["results"])


def test_reuse_is_explicit_and_parallel_retrieval_is_forbidden() -> None:
    source = (ROOT / "src" / "knowledge_engine" / "m26_retrieval_envelope.py").read_text(
        encoding="utf-8"
    )
    assert "from .m14_retrieval import AUDIENCE_RANK, retrieve_wiki_first" in source
    assert "from .m14_citation_runtime import enrich_runtime_citations" in source
    lowered = source.lower()
    assert "semantic_index=none" in lowered
    assert "provider_called" in lowered
    assert "openai" not in lowered
    assert "anthropic" not in lowered
    assert "import qdrant" not in lowered
    assert "from qdrant" not in lowered
    assert "import boto3" not in lowered


def test_documented_stop_lines_and_quality_diagnostics_are_complete() -> None:
    document = (DOCS / "m26-2-retrieval-envelope.md").read_text(encoding="utf-8")
    lowered = document.lower()
    required = {
        "m26_2_retrieval_envelope_accepted",
        "release-pinned lexical",
        "no silent exclusion",
        "first divergent stage",
        "facet coverage",
        "citation presence is not claim support",
        "real corpus",
        "provider call",
        "semantic or hybrid",
        "production answer serving",
        "m26.3",
    }
    assert all(value in lowered for value in required)


def test_fixture_source_content_digests_are_exact() -> None:
    for source in CORPUS["source_documents"]:
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["content_sha256"]
