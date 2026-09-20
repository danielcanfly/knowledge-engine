from pathlib import Path

from knowledge_engine.m26_golden_production_provider import (
    PackagedGoldenEvaluationProvider,
    packaged_golden_evaluation_provider,
)


def test_packaged_provider_exposes_immutable_dataset_without_faking_runs() -> None:
    provider = packaged_golden_evaluation_provider()
    assert provider is not None

    golden = provider.list_golden_sets(None)
    assert golden["source"] == "packaged_m23_golden_query_registry"
    assert golden["freshness"] == "snapshot"
    assert golden["run_request_contract"] == {
        "status": "blocked",
        "reason_code": "GOLDEN_RUN_START_NOT_AUTHORIZED",
    }

    sets = golden["sets"]
    assert len(sets) == 1
    dataset = sets[0]
    assert dataset["dataset_id"] == "m23-golden-queries"
    assert dataset["state"] == "active"
    assert len(dataset["cases"]) == 16
    assert dataset["dataset_hash"]
    assert dataset["scoring_contract"]["hash"]

    assert provider.list_evaluation_runs(None) == {}


def test_packaged_provider_uses_explicit_asset_identity() -> None:
    provider = packaged_golden_evaluation_provider()
    assert provider is not None
    assert isinstance(provider, PackagedGoldenEvaluationProvider)
    assert provider.path == Path(provider.path)
    assert provider.path.name == "m23-1-golden-queries.json"
