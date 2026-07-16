from __future__ import annotations

import copy
import hashlib
import inspect
import math
from collections.abc import Sequence
from typing import Any

import pytest

from knowledge_engine import m23_7_r3_7_live_acceptance as subject

OFFLINE_CASES = (
    "m23q-01",
    "m23q-02",
    "m23q-03",
    "m23q-04",
    "m23q-07",
    "m23q-08",
    "m23q-09",
    "m23q-10",
)


def _unit(index: int) -> list[float]:
    vector = [0.0] * subject.VECTOR_DIMENSION
    vector[index] = 1.0
    return vector


def _fixtures() -> tuple[dict[str, Any], dict[str, Any], list[list[float]]]:
    points: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    for index in range(subject.EXPECTED_POINT_COUNT):
        section_id = f"docs/topic-{index:03d}/chunk-{index:03d}"
        point_id = f"00000000-0000-0000-0000-{index:012d}"
        token = f"quasar{index}"
        payload = {
            "payload_schema_version": subject.PAYLOAD_SCHEMA,
            "section_id": section_id,
            "section_title": f"{token} decision boundary",
            "language": "en",
            "concept_id": f"concept-{token}",
            "source_path": f"docs/topic-{index:03d}.md",
            "source_membership": "r3-6-candidate-live-acceptance-only",
            "candidate_collection": subject.EXPECTED_COLLECTION,
            "candidate_artifact_sha256": subject.r36.R3_5_CANDIDATE_ARTIFACT_SHA256,
            "candidate_reingestion_issue": subject.r36.IMPLEMENTATION_ISSUE,
            "vector_name": subject.VECTOR_NAME,
            "vector_dimension": subject.VECTOR_DIMENSION,
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
        }
        points.append(
            {
                "id": point_id,
                "payload": payload,
                "vector": {subject.VECTOR_NAME: _unit(index)},
            }
        )
        documents.append(
            {
                "section_id": section_id,
                "section_title": f"{token} decision boundary",
                "concept_id": f"concept-{token}-orbit{index}",
                "source_path": f"docs/topic-{index:03d}.md",
                "language": "en",
                "text": f"{token} orbit{index} policy{index} " * 3,
            }
        )

    probes: list[dict[str, Any]] = []
    query_vectors: list[list[float]] = []
    for index, offline_case in enumerate(OFFLINE_CASES):
        target = points[index]["payload"]["section_id"]
        variants: list[dict[str, str]] = []
        for variant_index in range(subject.VARIANTS_PER_PROBE):
            text = (
                f"Find quasar{index} orbit{index} policy{index} "
                f"variant{variant_index}"
            )
            variants.append(
                {
                    "variant_id": f"probe-{index}-v{variant_index}",
                    "query_text": text,
                    "query_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            query_vectors.append(_unit(index))
        probes.append(
            {
                "probe_id": f"r1-probe-{index + 1:02d}",
                "offline_case_id": offline_case,
                "query_class": "terminology" if index in {1, 5} else "direct-fact",
                "target_section_id": target,
                "expected_relevant_ids": [target],
                "variants": variants,
            }
        )

    candidate = {
        "candidate_artifact_sha256": subject.r36.R3_5_CANDIDATE_ARTIFACT_SHA256,
        "points": points,
        "lexical_documents": documents,
        "probe_plan": probes,
    }
    ids_sha = subject.r36.canonical_sha256(sorted(point["id"] for point in points))
    aggregate = subject.r36.aggregate_fingerprint(points)
    manifest = {
        "manifest_sha256": "f" * 64,
        "ids_sha256": ids_sha,
        "aggregate_fingerprint_sha256": aggregate,
        "points": points,
    }
    return candidate, manifest, query_vectors


class FakeClient:
    def __init__(
        self,
        points: list[dict[str, Any]],
        query_vectors: Sequence[Sequence[float]],
        *,
        drift_after_queries: bool = False,
    ) -> None:
        self.points = copy.deepcopy(points)
        self.query_vectors = [list(vector) for vector in query_vectors]
        self.vector_cursor = 0
        self.query_count = 0
        self.retrieve_count = 0
        self.drift_after_queries = drift_after_queries
        self.network_calls = 0

    def collection_snapshot(self) -> dict[str, Any]:
        self.network_calls += 1
        return {
            "status": "green",
            "points_count": subject.EXPECTED_POINT_COUNT,
            "indexed_vectors_count": subject.EXPECTED_POINT_COUNT,
            "vector_name": subject.VECTOR_NAME,
            "vector_size": subject.VECTOR_DIMENSION,
            "vector_distance": subject.r36.EXPECTED_DISTANCE,
            "sparse_vectors": None,
        }

    def retrieve_points(self, _ids: Sequence[str]) -> list[dict[str, Any]]:
        self.network_calls += 1
        self.retrieve_count += 1
        output = copy.deepcopy(self.points)
        if self.drift_after_queries and self.retrieve_count == 2:
            output[0]["vector"][subject.VECTOR_NAME][0] = 0.5
        return output

    def embed(self, _variant_id: str, _text: str) -> Sequence[float]:
        self.network_calls += 1
        vector = self.query_vectors[self.vector_cursor]
        self.vector_cursor += 1
        return vector

    def query(
        self,
        vector: Sequence[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        self.network_calls += 1
        self.query_count += 1
        scored = []
        for point in self.points:
            candidate = point["vector"][subject.VECTOR_NAME]
            score = math.fsum(
                left * right for left, right in zip(vector, candidate, strict=True)
            )
            scored.append((score, point))
        scored.sort(key=lambda item: (-item[0], item[1]["payload"]["section_id"]))
        return [
            {
                "id": point["id"],
                "score": score,
                "payload": copy.deepcopy(point["payload"]),
            }
            for score, point in scored[:limit]
        ]


def _patch_synthetic_identities(
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict[str, Any],
) -> None:
    frozen_contract = subject.canonical_contract()
    monkeypatch.setattr(subject, "canonical_contract", lambda: frozen_contract)
    monkeypatch.setattr(subject, "R3_6_MANIFEST_SHA256", manifest["manifest_sha256"])
    monkeypatch.setattr(
        subject,
        "R3_6_IDS_SHA256",
        manifest["ids_sha256"],
    )
    monkeypatch.setattr(
        subject,
        "R3_6_AGGREGATE_SHA256",
        manifest["aggregate_fingerprint_sha256"],
    )
    monkeypatch.setattr(
        subject,
        "ACCEPTED_METRICS",
        {"recall_at_5": 1.0, "mrr_at_10": 1.0, "ndcg_at_10": 1.0},
    )
    monkeypatch.setattr(
        subject,
        "ACCEPTED_TARGET_RANKS",
        {offline_case: 1 for offline_case in OFFLINE_CASES},
    )


def _clock(step_ms: int = 1):
    value = 0

    def read() -> int:
        nonlocal value
        current = value
        value += step_ms * 1_000_000
        return current

    return read


def test_contract_freezes_live_quality_latency_and_read_only_authority() -> None:
    contract = subject.canonical_contract()
    assert contract["contract_sha256"] == subject.CONTRACT_SHA256
    assert contract["queries"]["query_count"] == 24
    assert contract["queries"]["separate_live_calls"] is True
    assert contract["quality"]["min_recall_at_5"] == 0.82
    assert contract["quality"]["min_mrr_at_10"] == 0.68
    assert contract["quality"]["min_ndcg_at_10"] == 0.72
    assert contract["latency"]["max_live_p95_ms"] == 1200
    assert contract["latency"]["batch_amortisation_allowed"] is False
    assert contract["authority"]["qdrant_read_authorized"] is True
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["authority"]["qdrant_delete_authorized"] is False
    source = inspect.getsource(subject.HttpLiveAcceptanceClient)
    assert ".put(" not in source
    assert ".delete(" not in source


def test_live_calibrated_ranker_has_no_target_aware_inputs() -> None:
    source = inspect.getsource(subject.live_calibrated_ranking)
    for forbidden in (
        "target_section_id",
        "expected_relevant_ids",
        "offline_case_id",
        "probe_id",
    ):
        assert forbidden not in source


def test_full_live_acceptance_passes_with_exact_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, manifest, query_vectors = _fixtures()
    _patch_synthetic_identities(monkeypatch, manifest)
    client = FakeClient(manifest["points"], query_vectors)

    report = subject.run_live_acceptance(
        candidate,
        manifest,
        client,
        clock_ns=_clock(),
    )

    assert report["status"] == "pass_live_acceptance"
    assert all(report["gates"].values()), report["gates"]
    assert report["query_count"] == 24
    assert report["query_identity_count"] == 24
    assert report["metrics"] == {
        "recall_at_5": 1.0,
        "mrr_at_10": 1.0,
        "ndcg_at_10": 1.0,
    }
    assert report["target_ranks"] == {
        offline_case: 1 for offline_case in OFFLINE_CASES
    }
    assert report["latency"]["live_p95_ms"] <= 1200
    assert report["pre_post_point_identity_equal"] is True
    assert report["authority"]["qdrant_read_dispatched"] is True
    assert report["authority"]["qdrant_write_dispatched"] is False
    assert report["authority"]["retrieval_quality_blocker_cleared"] is False


def test_latency_budget_fails_closed_without_quality_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, manifest, query_vectors = _fixtures()
    _patch_synthetic_identities(monkeypatch, manifest)
    client = FakeClient(manifest["points"], query_vectors)

    report = subject.run_live_acceptance(
        candidate,
        manifest,
        client,
        clock_ns=_clock(step_ms=500),
    )

    assert report["status"] == "completed_fail_closed_live_acceptance"
    assert report["gates"]["live_p95_latency"] is False
    assert report["gates"]["accepted_metric_parity"] is True
    assert "blocked_pending_latency" in report["retained_blockers"]
    assert report["authority"]["retrieval_quality_blocker_cleared"] is False


def test_post_query_point_drift_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, manifest, query_vectors = _fixtures()
    _patch_synthetic_identities(monkeypatch, manifest)
    client = FakeClient(
        manifest["points"],
        query_vectors,
        drift_after_queries=True,
    )

    with pytest.raises(subject.LiveAcceptanceError, match="fingerprint drifted"):
        subject.run_live_acceptance(
            candidate,
            manifest,
            client,
            clock_ns=_clock(),
        )


def test_ranked_payload_identity_drift_is_rejected() -> None:
    _candidate, manifest, _query_vectors = _fixtures()
    points = []
    for index, point in enumerate(manifest["points"][: subject.DENSE_LIMIT]):
        payload = copy.deepcopy(point["payload"])
        if index == 0:
            payload["production_authority"] = True
        points.append(
            {
                "id": point["id"],
                "score": 1.0 - index / 100,
                "payload": payload,
            }
        )
    known = {point["payload"]["section_id"] for point in manifest["points"]}
    with pytest.raises(subject.LiveAcceptanceError, match="payload field drifted"):
        subject._validate_ranked_points(points, known)
