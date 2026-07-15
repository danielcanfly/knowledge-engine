from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_5_live_shadow import (
    CANDIDATE_MANIFEST,
    CANDIDATE_RELEASE,
    COLLECTION,
    EXPECTED_POINTS,
    QDRANT_MANIFEST,
    QDRANT_RELEASE,
    SAMPLE_CAP,
    VECTOR_DIMENSION,
    VECTOR_NAME,
    ShadowFailure,
    canonical_observation_contract,
    run_bounded_observation,
    validate_observation_contract,
)


def point(index: int, *, audience: str = "public") -> dict:
    section_id = f"pilot/live-shadow#section-{index:03d}"
    return {
        "id": f"00000000-0000-0000-0000-{index:012d}",
        "score": 1.0 - index / 1000,
        "payload": {
            "section_id": section_id,
            "article_id": "pilot/live-shadow",
            "document_id": "pilot/live-shadow",
            "concept_id": f"concept-{index:03d}",
            "source_path": "pilot/live-shadow.md",
            "source_sha256": "a" * 64,
            "text_sha256": "b" * 64,
            "graph_node_id": f"node-{index:03d}",
            "audience": audience,
            "source_membership": "evaluation-only-pending-proposal",
            "release_id": QDRANT_RELEASE,
            "release_manifest_sha256": QDRANT_MANIFEST,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "embedding_model": "@cf/baai/bge-m3",
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        },
    }


class Clock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        self.value += 1_000_000
        return self.value


class FakeClient:
    def __init__(self, *, failures: int = 0, audience: str = "public") -> None:
        self.points = [point(index, audience=audience) for index in range(1, SAMPLE_CAP + 1)]
        self.query_index = 0
        self.failures = failures

    def collection_snapshot(self) -> dict:
        return {
            "status": "green",
            "points_count": EXPECTED_POINTS,
            "indexed_vectors_count": 0,
            "vector_name": VECTOR_NAME,
            "vector_dimension": VECTOR_DIMENSION,
            "distance": "Cosine",
            "sparse_vectors": None,
            "read_only": True,
        }

    def sample_points(self, limit: int) -> list[dict]:
        return copy.deepcopy(self.points[:limit])

    def embed(self, text: str) -> list[float]:
        assert text.startswith("pilot/live-shadow#section-")
        if self.failures > 0:
            self.failures -= 1
            raise ShadowFailure("cloudflare-timeout")
        return [1.0] + [0.0] * (VECTOR_DIMENSION - 1)

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        assert len(vector) == VECTOR_DIMENSION
        item = copy.deepcopy(self.points[self.query_index])
        self.query_index += 1
        return [item][:top_k]


def test_contract_locks_privacy_sampling_and_authority():
    contract = validate_observation_contract(canonical_observation_contract())
    assert contract["sampling"]["maximum_probes"] == 8
    assert contract["privacy"]["retention_days"] == 7
    assert contract["privacy"]["raw_query_persisted"] is False
    assert contract["privacy"]["raw_answer_persisted"] is False
    assert contract["authority"]["authoritative_method"] == "lexical"
    assert contract["authority"]["candidate_may_influence_output"] is False
    assert contract["entry"]["candidate_release_id"] == CANDIDATE_RELEASE
    assert contract["entry"]["candidate_manifest_sha256"] == CANDIDATE_MANIFEST


def test_canonical_live_observation_passes_and_is_privacy_safe():
    report = run_bounded_observation(FakeClient(), clock_ns=Clock())
    assert report["status"] == "pass"
    assert report["metrics"]["sample_count"] == SAMPLE_CAP
    assert report["metrics"]["failure_count"] == 0
    assert report["metrics"]["error_rate"] == 0.0
    assert report["metrics"]["overlap_at_5_mean"] == 1.0
    assert report["metrics"]["acl_violation_rate"] == 0.0
    assert report["metrics"]["output_influence_rate"] == 0.0
    assert report["raw_queries_persisted"] is False
    assert report["raw_answers_persisted"] is False
    assert report["service_urls_persisted"] is False
    assert report["candidate_outputs_served"] is False
    assert report["candidate_outputs_discarded"] is True
    assert report["production_response_authority"] is False
    assert report["protected_mutations_dispatched"] is False
    assert all(case["output_influenced"] is False for case in report["cases"])
    assert all(case["primary_completed_before_shadow"] is True for case in report["cases"])
    assert all(len(case["query_digest"]) == 64 for case in report["cases"])
    assert "query_text" not in repr(report)
    assert "answer_text" not in repr(report)
    assert "api_key" not in repr(report)
    assert "https://" not in repr(report)


def test_report_is_deterministic_for_same_live_receipts():
    first = run_bounded_observation(FakeClient(), clock_ns=Clock())
    second = run_bounded_observation(FakeClient(), clock_ns=Clock())
    assert first == second


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda item: item["sampling"].__setitem__("maximum_probes", 64),
            "observation contract drifted",
        ),
        (
            lambda item: item["privacy"].__setitem__("raw_query_persisted", True),
            "observation contract drifted",
        ),
        (
            lambda item: item["authority"].__setitem__("candidate_may_influence_output", True),
            "observation contract drifted",
        ),
        (
            lambda item: item["protected_mutations"].__setitem__("qdrant_write", True),
            "observation contract drifted",
        ),
    ],
)
def test_contract_fails_closed_on_drift(mutator, match):
    contract = canonical_observation_contract()
    mutator(contract)
    with pytest.raises(IntegrityError, match=match):
        validate_observation_contract(contract)


def test_acl_mismatch_fails_before_shadow_query():
    with pytest.raises(IntegrityError, match="ACL rejection"):
        run_bounded_observation(FakeClient(audience="internal"), clock_ns=Clock())


def test_provider_failure_is_classified_but_acceptance_fails_closed():
    with pytest.raises(IntegrityError, match="error-rate budget exceeded"):
        run_bounded_observation(FakeClient(failures=1), clock_ns=Clock())


def test_collection_identity_drift_fails_closed():
    client = FakeClient()
    original_snapshot = client.collection_snapshot

    def bad_snapshot() -> dict:
        value = original_snapshot()
        value["points_count"] = 106
        return value

    client.collection_snapshot = bad_snapshot  # type: ignore[method-assign]
    with pytest.raises(IntegrityError, match="collection health drifted"):
        run_bounded_observation(client, clock_ns=Clock())


def test_sample_cap_cannot_be_exceeded():
    client = FakeClient()
    client.sample_points = lambda limit: [point(index) for index in range(1, limit + 2)]  # type: ignore[method-assign]
    with pytest.raises(IntegrityError, match="sample size is outside"):
        run_bounded_observation(client, clock_ns=Clock())


def test_live_scope_is_exact_nonproduction_collection():
    contract = canonical_observation_contract()
    assert contract["entry"]["qdrant_collection"] == COLLECTION
    assert contract["entry"]["qdrant_points"] == 107
    assert contract["approval"]["live_user_sampling_allowed"] is False
    assert contract["approval"]["internal_synthetic_probes_allowed"] is True
