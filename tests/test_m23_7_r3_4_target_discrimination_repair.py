from __future__ import annotations

import hashlib
import math

from knowledge_engine import m23_7_r3_4_target_discrimination_repair as r34


def _unit(values: dict[int, float]) -> list[float]:
    vector = [0.0] * r34.VECTOR_DIMENSION
    for index, value in values.items():
        vector[index] = value
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


def _documents() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for index in range(r34.EXPECTED_POINT_COUNT):
        unique = [
            f"quasar{index}",
            f"nebula{index}",
            f"orbit{index}",
            f"signal{index}",
            f"vector{index}",
            f"policy{index}",
        ]
        text = " ".join(unique * 3)
        output.append(
            {
                "section_id": f"docs/topic-{index:03d}/chunk-{index:03d}",
                "concept_id": f"concept-{unique[0]}-{unique[1]}",
                "language": "en" if index % 2 == 0 else "zh-TW",
                "title": f"{unique[0]} {unique[1]} decision boundary",
                "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "source_path": f"docs/topic-{index:03d}.md",
                "source_sha256": hashlib.sha256(f"source-{index}".encode()).hexdigest(),
                "audience": "public",
            }
        )
    return output


def _samples(documents: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": f"point-{index:03d}",
            "payload": {
                "payload_schema_version": r34.PAYLOAD_SCHEMA_V2,
                "section_id": documents[index]["section_id"],
            },
        }
        for index in range(r34.SAMPLE_CAP)
    ]


def _candidate() -> tuple[dict[str, object], list[list[float]]]:
    points = []
    for index in range(r34.EXPECTED_POINT_COUNT):
        section_id = f"docs/topic-{index:03d}/chunk-{index:03d}"
        points.append(
            {
                "payload": {
                    "section_id": section_id,
                    "payload_schema_version": r34.PAYLOAD_SCHEMA_V2,
                },
                "vector": {"default": _unit({index: 1.0})},
            }
        )
    probes = []
    query_vectors: list[list[float]] = []
    for index in range(r34.SAMPLE_CAP):
        target = points[index]["payload"]["section_id"]
        variants = []
        distractors = [8 + index * 10 + offset for offset in range(9)]
        query = _unit(
            {
                index: 0.95,
                **{
                    row: 0.1 - offset * 0.005
                    for offset, row in enumerate(distractors)
                },
            }
        )
        for variant_index in range(r34.VARIANTS_PER_PROBE):
            text = f"probe {index} variant {variant_index}"
            variants.append(
                {
                    "variant_id": (
                        f"r1-probe-{index + 1:02d}-v{variant_index + 1}"
                    ),
                    "query_text": text,
                    "query_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
            query_vectors.append(query)
        probes.append(
            {
                "probe_id": f"r1-probe-{index + 1:02d}",
                "offline_case_id": f"m23q-{index + 1:02d}",
                "query_class": "direct-fact",
                "target_section_id": target,
                "variants": variants,
            }
        )
    candidate = {
        "points": points,
        "probe_plan": probes,
        "specificity": {
            point["payload"]["section_id"]: 0.8 for point in points
        },
        "corpus_centrality": {
            point["payload"]["section_id"]: 0.2 for point in points
        },
        "evidence": {
            "evidence_zip_sha256": r34.EXPECTED_EVIDENCE_SHA256,
        },
        "candidate_artifact_sha256": "a" * 64,
    }
    return candidate, query_vectors


def test_contract_freezes_thresholds_and_authority() -> None:
    contract = r34.canonical_contract()
    assert contract["implementation_issue"] == 497
    assert contract["repair"]["total_query_variants"] == 24
    assert contract["repair"]["target_aware_reranking"] is False
    assert contract["thresholds"]["min_recall_at_5"] == 0.82
    assert contract["thresholds"]["thresholds_changed"] is False
    assert contract["authority"]["qdrant_read_authorized"] is False
    assert contract["authority"]["qdrant_write_authorized"] is False
    assert contract["authority"]["production_retrieval"] == "lexical"


def test_compiler_builds_24_unique_target_specific_variants() -> None:
    documents = _documents()
    probes, specificity = r34.compile_discriminative_probe_plan(
        _samples(documents),
        documents,
    )
    assert len(probes) == 8
    assert len(specificity) == 8
    variants = [variant for probe in probes for variant in probe["variants"]]
    assert len(variants) == 24
    assert len({variant["query_text_sha256"] for variant in variants}) == 24
    assert all(
        probe["target_section_id"] not in variant["query_text"]
        for probe in probes
        for variant in probe["variants"]
    )
    assert all(probe["signature_term_count"] >= 5 for probe in probes)


def test_perfect_discriminative_vectors_pass_all_gates() -> None:
    candidate, query_vectors = _candidate()
    report = r34.evaluate_repair_candidate(candidate, query_vectors)
    assert report["status"] == "pass_target_discrimination_repair"
    assert report["metrics"] == {
        "recall_at_5": 1.0,
        "mrr_at_10": 1.0,
        "ndcg_at_10": 1.0,
    }
    assert report["maximum_top10_hub_frequency"] <= 6
    assert report["external_calls"]["qdrant_reads"] == 0
    assert report["external_calls"]["qdrant_writes"] == 0
    assert report["exit"]["live_acceptance_still_required"] is True


def test_wrong_vectors_reject_repair() -> None:
    candidate, _ = _candidate()
    wrong = [_unit({106: 1.0}) for _ in range(r34.TOTAL_QUERY_VARIANTS)]
    report = r34.evaluate_repair_candidate(candidate, wrong)
    assert report["status"] == "rejected_target_discrimination_repair"
    assert report["gates"]["recall_at_5"] is False
    assert report["exit"]["next_gate"] == "repair_iteration_required"


def test_redacted_candidate_removes_raw_queries() -> None:
    candidate, _ = _candidate()
    unsigned = {
        **candidate,
        "probe_plan": r34._redacted_probe_plan(candidate["probe_plan"]),
    }
    candidate["candidate_artifact_sha256"] = r34.canonical_sha256(unsigned)
    redacted = r34.redacted_candidate_artifact(candidate)
    assert all(
        "query_text" not in variant
        for probe in redacted["probe_plan"]
        for variant in probe["variants"]
    )
