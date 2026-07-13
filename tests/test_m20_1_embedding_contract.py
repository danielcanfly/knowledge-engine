from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.m20_embedding_contract import (
    BENCHMARK_RESULT_SCHEMA,
    BILINGUAL_BENCHMARK_SCHEMA,
    EMBEDDING_CONTRACT_SCHEMA,
    ContractError,
    benchmark_result,
    canonical_sha256,
    cosine_similarity,
    evaluate_rankings,
    lexical_rankings,
    load_json,
    validate_benchmark_suite,
    validate_provider_contract,
)

ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "benchmarks/m20/bilingual-blog-benchmark-v1.json"
CONTRACT_PATH = ROOT / "benchmarks/m20/provider-contract.fixture.json"


def suite() -> dict:
    return load_json(SUITE_PATH)


def contract() -> dict:
    return load_json(CONTRACT_PATH)


def test_schema_constants_are_versioned() -> None:
    assert EMBEDDING_CONTRACT_SCHEMA.endswith("/v1")
    assert BILINGUAL_BENCHMARK_SCHEMA.endswith("/v1")
    assert BENCHMARK_RESULT_SCHEMA.endswith("/v1")


def test_provider_contract_pins_identity_and_preprocessing() -> None:
    validated = validate_provider_contract(contract())
    assert validated["model"]["vector_dimension"] == 64
    assert validated["preprocessing"]["unicode_normalization"] == "NFKC"
    assert validated["preprocessing"]["normalization"] == "l2"
    assert validated["batching"] == {
        "batch_size": 32,
        "preserve_input_order": True,
        "deterministic": True,
    }
    assert validated["authority"] == {
        "canonical_source": "markdown",
        "vectors_are_derived": True,
        "runtime_network_required": False,
        "write_back": False,
        "production_authority": False,
    }


def test_provider_contract_rejects_unpinned_model_and_authority() -> None:
    raw = contract()
    del raw["model"]["revision"]
    del raw["model"]["digest_sha256"]
    with pytest.raises(ContractError, match="pin revision or digest"):
        validate_provider_contract(raw)

    raw = contract()
    raw["authority"]["write_back"] = True
    with pytest.raises(ContractError, match="authority"):
        validate_provider_contract(raw)


def test_benchmark_suite_is_bilingual_bounded_and_deterministic() -> None:
    validated = validate_benchmark_suite(suite())
    assert len(validated["documents"]) == 8
    assert len(validated["queries"]) == 12
    assert {item["language"] for item in validated["documents"]} == {"en", "zh-TW"}
    assert {item["kind"] for item in validated["queries"]}.issuperset(
        {"exact-name", "paraphrase", "zh-to-en", "en-to-zh", "not-found"}
    )
    assert [item["section_id"] for item in validated["documents"]] == sorted(
        item["section_id"] for item in validated["documents"]
    )
    assert validated["read_only"] is True
    assert validated["production_authority"] is False


def test_benchmark_rejects_hash_drift_duplicate_ids_and_unknown_targets() -> None:
    raw = suite()
    raw["documents"][0]["text"] += " drift"
    with pytest.raises(ContractError, match="hash mismatch"):
        validate_benchmark_suite(raw)

    raw = suite()
    raw["documents"][1]["section_id"] = raw["documents"][0]["section_id"]
    with pytest.raises(ContractError, match="section IDs must be unique"):
        validate_benchmark_suite(raw)

    raw = suite()
    raw["queries"][0]["expected_section_ids"] = ["missing/section"]
    with pytest.raises(ContractError, match="unknown sections"):
        validate_benchmark_suite(raw)


def test_lexical_baseline_is_deterministic_and_acl_safe() -> None:
    raw = suite()
    first = lexical_rankings(raw)
    second = lexical_rankings(copy.deepcopy(raw))
    assert first == second
    assert first["q01-harness-exact-en"][0] == (
        "blog/en/harness-theory-part-01#working-definition"
    )
    assert "blog/zh/internal#candidate-release-secret" not in first["q12-acl-negative"]
    assert "blog/zh/internal#candidate-release-secret" not in {
        item for ranking in first.values() for item in ranking
    }


def test_lexical_baseline_emits_stable_metrics_and_digest() -> None:
    raw = suite()
    rankings = lexical_rankings(raw)
    result = benchmark_result(raw, rankings, method="deterministic-lexical-baseline")
    assert result["schema_version"] == BENCHMARK_RESULT_SCHEMA
    assert result["metrics"]["exact_name_recall_at_k"] == 1.0
    assert 0 <= result["metrics"]["not_found_accuracy"] <= 1
    assert 0 <= result["metrics"]["cross_language_recall_at_k"] <= 1
    digest = result.pop("result_sha256")
    assert digest == canonical_sha256(result)


def test_candidate_rankings_require_complete_query_coverage() -> None:
    raw = suite()
    rankings = lexical_rankings(raw)
    rankings.pop(next(iter(rankings)))
    with pytest.raises(ContractError, match="coverage mismatch"):
        evaluate_rankings(raw, rankings)


def test_candidate_rankings_reject_duplicates_and_unknown_sections() -> None:
    raw = suite()
    rankings = lexical_rankings(raw)
    rankings["q01-harness-exact-en"] = [
        "blog/en/harness-theory-part-01#working-definition",
        "blog/en/harness-theory-part-01#working-definition",
    ]
    with pytest.raises(ContractError, match="duplicate sections"):
        evaluate_rankings(raw, rankings)

    rankings = lexical_rankings(raw)
    rankings["q01-harness-exact-en"] = ["unknown"]
    with pytest.raises(ContractError, match="unknown sections"):
        evaluate_rankings(raw, rankings)


def test_provider_and_benchmark_identities_must_match() -> None:
    raw_contract = contract()
    raw_contract["identities"]["source_commit_sha"] = "0" * 40
    rankings = lexical_rankings(suite())
    with pytest.raises(ContractError, match="identities do not match"):
        benchmark_result(
            suite(),
            rankings,
            method="candidate-rankings",
            provider_contract=raw_contract,
        )


def test_cosine_similarity_is_correct_and_fail_closed() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    with pytest.raises(ContractError, match="identical dimensions"):
        cosine_similarity([1.0], [1.0, 2.0])
    with pytest.raises(ContractError, match="non-zero norm"):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_fixture_contract_and_suite_are_canonical_json_objects() -> None:
    for path in (SUITE_PATH, CONTRACT_PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert path.read_text(encoding="utf-8").endswith("\n")
