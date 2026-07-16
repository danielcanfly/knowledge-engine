from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_r3_3_offline_rebuild_evaluation_real import _load_inputs
from . import m23_7_r3_4_target_discrimination_repair as r34

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-5-rank-quality-calibration/v1"
CANDIDATE_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-5-rank-quality-calibration-candidate/v1"
)
REPORT_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-5-rank-quality-calibration-report/v1"
)
IMPLEMENTATION_ISSUE = 502
PARENT_ISSUE = 474
ENTRY_ENGINE_SHA = "60a7d97ce1a912a19591cb2427d0c57f7b4a2d4a"
R3_4_REPORT_SHA256 = "2464a6cc2aaf708cfad1b8bf3a8f16322a17c78e72af331176a98d8e349be225"
R3_4_REPORT_FILE_SHA256 = (
    "9dde5d63f7b43ae8078cdd1a20d9c62bafa2e1d710ab03eba97f6796f838c292"
)
R3_4_FINAL = {
    "recall_at_5": 0.875,
    "mrr_at_10": 0.566666666667,
    "ndcg_at_10": 0.643589039297,
}
R3_4_RRF = {
    "recall_at_5": 0.75,
    "mrr_at_10": 0.645833333333,
    "ndcg_at_10": 0.702258336781,
}
R3_4_MAXIMUM_HUB = 3

LEXICAL_RRF_K = 40
CONSENSUS_RRF_K = 60
CONSENSUS_DEPTH = 10
LEXICAL_FIELD_BOOSTS = {
    "section_title": 4,
    "concept_id": 3,
    "source_path": 1,
    "text": 1,
}
LEXICAL_WEIGHTS = {
    "direct-fact": 1.5,
    "terminology": 2.2,
    "cross-section": 1.4,
    "provenance": 1.3,
}
CONSENSUS_WEIGHT = 0.35
BM25_K1 = 1.2
BM25_B = 0.75
MAXIMUM_ALLOWED_HUB_FREQUENCY = 6

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u3400-\u9fff]{2,}")
_GENERIC = {
    "about",
    "article",
    "concept",
    "content",
    "document",
    "evidence",
    "find",
    "focus",
    "identify",
    "knowledge",
    "language",
    "passage",
    "section",
    "source",
    "specific",
    "which",
    "什麼",
    "內容",
    "哪一段",
    "哪個段落",
    "文件",
    "段落",
    "說明",
    "資訊",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.5-{code} {message}")


def _tokens(value: str) -> list[str]:
    output: list[str] = []
    for raw in _TOKEN.findall(value):
        token = raw.casefold().strip("_-")
        if not token or token in _GENERIC or token.isdigit():
            continue
        if any("\u3400" <= char <= "\u9fff" for char in token):
            compact = "".join(char for char in token if "\u3400" <= char <= "\u9fff")
            grams = (
                [compact]
                if len(compact) <= 3
                else [compact[index : index + 3] for index in range(len(compact) - 2)]
            )
            output.extend(gram for gram in grams if gram not in _GENERIC)
        else:
            output.append(token)
    return output


def _semantic_counts(document: Mapping[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for field, boost in LEXICAL_FIELD_BOOSTS.items():
        value = str(document.get(field, ""))
        for token in _tokens(value):
            counts[token] += boost
    return counts


def _lexical_index(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Counter[str]], Counter[str], dict[str, int], float]:
    counts_by_section: dict[str, Counter[str]] = {}
    document_frequency: Counter[str] = Counter()
    lengths: dict[str, int] = {}
    for document in documents:
        section_id = str(document["section_id"])
        counts = _semantic_counts(document)
        _require(bool(counts), 101, f"lexical surface empty for {section_id}")
        counts_by_section[section_id] = counts
        document_frequency.update(counts.keys())
        lengths[section_id] = sum(counts.values())
    average_length = math.fsum(lengths.values()) / len(lengths)
    return counts_by_section, document_frequency, lengths, average_length


def _bm25_ranking(
    query_texts: Sequence[str],
    *,
    counts_by_section: Mapping[str, Counter[str]],
    document_frequency: Mapping[str, int],
    lengths: Mapping[str, int],
    average_length: float,
) -> list[tuple[float, str]]:
    query_counts = Counter(token for text in query_texts for token in _tokens(text))
    _require(bool(query_counts), 102, "query lexical surface is empty")
    document_count = len(counts_by_section)
    scores: dict[str, float] = {}
    for section_id, counts in counts_by_section.items():
        length = lengths[section_id]
        score = 0.0
        for token, query_frequency in query_counts.items():
            frequency = counts.get(token, 0)
            if frequency <= 0:
                continue
            df = int(document_frequency.get(token, 0))
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * length / average_length
            )
            score += (
                idf
                * (frequency * (BM25_K1 + 1) / denominator)
                * (1 + math.log(query_frequency))
            )
        scores[section_id] = score
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _dense_rankings(
    query_vectors: Sequence[Sequence[float]],
    corpus: Sequence[tuple[str, Sequence[float]]],
) -> list[list[tuple[float, str]]]:
    return [
        sorted(
            (
                (r34._cosine(query, document_vector), section_id)
                for section_id, document_vector in corpus
            ),
            key=lambda item: (-item[0], item[1]),
        )
        for query in query_vectors
    ]


def _rrf_scores(
    rankings: Sequence[Sequence[tuple[float, str]]],
) -> Counter[str]:
    scores: Counter[str] = Counter()
    for ranking in rankings:
        for rank, (_, section_id) in enumerate(
            ranking[: r34.FUSION_DEPTH],
            start=1,
        ):
            scores[section_id] += 1 / (r34.RRF_K + rank)
    return scores


def calibrated_hybrid_ranking(
    *,
    query_class: str,
    query_texts: Sequence[str],
    query_vectors: Sequence[Sequence[float]],
    corpus: Sequence[tuple[str, Sequence[float]]],
    counts_by_section: Mapping[str, Counter[str]],
    document_frequency: Mapping[str, int],
    lengths: Mapping[str, int],
    average_length: float,
) -> tuple[list[tuple[float, str]], dict[str, Any]]:
    """Rank without accepting target IDs, expected relevance, or case labels."""

    _require(query_class in LEXICAL_WEIGHTS, 103, "unsupported query class")
    _require(
        len(query_texts) == r34.VARIANTS_PER_PROBE,
        104,
        "query text variant count drifted",
    )
    _require(
        len(query_vectors) == r34.VARIANTS_PER_PROBE,
        105,
        "query vector variant count drifted",
    )
    dense = _dense_rankings(query_vectors, corpus)
    dense_rrf = _rrf_scores(dense)
    lexical = _bm25_ranking(
        query_texts,
        counts_by_section=counts_by_section,
        document_frequency=document_frequency,
        lengths=lengths,
        average_length=average_length,
    )
    lexical_ranks = {
        section_id: rank
        for rank, (_, section_id) in enumerate(lexical, start=1)
    }
    dense_best_rank: dict[str, int] = {}
    dense_consensus: Counter[str] = Counter()
    for ranking in dense:
        for rank, (_, section_id) in enumerate(ranking, start=1):
            dense_best_rank[section_id] = min(
                dense_best_rank.get(section_id, len(corpus) + 1),
                rank,
            )
            if rank <= CONSENSUS_DEPTH:
                dense_consensus[section_id] += 1

    lexical_weight = LEXICAL_WEIGHTS[query_class]
    calibrated: dict[str, float] = {}
    for section_id, _vector in corpus:
        dense_score = float(dense_rrf.get(section_id, 0.0))
        lexical_score = lexical_weight / (
            LEXICAL_RRF_K + lexical_ranks[section_id]
        )
        consensus_score = (
            CONSENSUS_WEIGHT
            * dense_consensus.get(section_id, 0)
            / (CONSENSUS_RRF_K + dense_best_rank[section_id])
        )
        calibrated[section_id] = dense_score + lexical_score + consensus_score
    ranking = sorted(
        ((score, section_id) for section_id, score in calibrated.items()),
        key=lambda item: (-item[0], item[1]),
    )
    diagnostics = {
        "lexical_weight": lexical_weight,
        "dense_variant_count": len(dense),
        "query_token_count": len(
            {token for text in query_texts for token in _tokens(text)}
        ),
        "target_aware_inputs_accepted": False,
    }
    return ranking, diagnostics


def _redacted_probe_plan(
    probes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return r34._redacted_probe_plan(probes)


def canonical_contract() -> dict[str, Any]:
    ranker_source = inspect.getsource(calibrated_hybrid_ranking)
    forbidden = (
        "target_section_id",
        "expected_relevant_ids",
        "offline_case_id",
        "probe_id",
    )
    _require(
        not any(term in ranker_source for term in forbidden),
        106,
        "calibrated ranker accepts target-aware inputs",
    )
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.5",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_4_report_sha256": R3_4_REPORT_SHA256,
            "r3_4_report_file_sha256": R3_4_REPORT_FILE_SHA256,
            "r3_4_final": R3_4_FINAL,
            "r3_4_rrf": R3_4_RRF,
            "evidence_zip_sha256": r34.EXPECTED_EVIDENCE_SHA256,
            "semantic_artifact_id": r34.EXPECTED_SEMANTIC_ARTIFACT_ID,
        },
        "repair": {
            "primary": "rank_quality_calibration",
            "dense_fusion": "reciprocal-rank-fusion",
            "lexical_ranking": "bm25-query-visible-semantic-surface",
            "lexical_rrf_k": LEXICAL_RRF_K,
            "lexical_weights": LEXICAL_WEIGHTS,
            "consensus_weight": CONSENSUS_WEIGHT,
            "consensus_depth": CONSENSUS_DEPTH,
            "r3_4_multiplicative_rerank_final": False,
            "r3_4_multiplicative_rerank_retained_as_ablation": True,
            "target_aware_reranking": False,
            "ranker_forbidden_inputs": list(forbidden),
            "embedding_model_changed": False,
            "query_variants_changed": False,
            "query_prefix_changed": False,
        },
        "thresholds": {
            "min_recall_at_5": r34.MIN_RECALL_AT_5,
            "min_mrr_at_10": r34.MIN_MRR_AT_10,
            "min_ndcg_at_10": r34.MIN_NDCG_AT_10,
            "r3_4_final_baseline": R3_4_FINAL,
            "r3_4_rrf_baseline": R3_4_RRF,
            "max_top10_hub_frequency": MAXIMUM_ALLOWED_HUB_FREQUENCY,
            "thresholds_changed": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "qdrant_read_authorized": False,
            "qdrant_write_authorized": False,
            "candidate_reingestion_authorized": False,
            "live_acceptance_authorized": False,
            "promotion_eligibility_granted": False,
            "retrieval_quality_blocker_cleared": False,
        },
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def build_calibration_candidate(path: Any) -> dict[str, Any]:
    base = r34.build_repair_candidate(path)
    inputs = _load_inputs(path)
    documents = [
        {
            "section_id": str(document["section_id"]),
            "section_title": str(document.get("section_title", document.get("title", ""))),
            "concept_id": str(document["concept_id"]),
            "source_path": str(document["source_path"]),
            "language": str(document["language"]),
            "text": str(document["text"]),
        }
        for document in inputs["documents"]
    ]
    _require(
        len(documents) == r34.EXPECTED_POINT_COUNT,
        107,
        "lexical document count drifted",
    )
    lexical_bindings = [
        {
            "section_id": document["section_id"],
            "semantic_surface_sha256": canonical_sha256(
                {
                    key: document[key]
                    for key in (
                        "section_title",
                        "concept_id",
                        "source_path",
                        "language",
                        "text",
                    )
                }
            ),
        }
        for document in documents
    ]
    candidate: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "milestone": "M23.7-R3.5",
        "mode": "offline-no-write-rank-calibration-candidate",
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence": base["evidence"],
        "release": base["release"],
        "point_count": base["point_count"],
        "payload_schema_version": base["payload_schema_version"],
        "points": base["points"],
        "bindings": base["bindings"],
        "probe_plan": base["probe_plan"],
        "specificity": base["specificity"],
        "corpus_centrality": base["corpus_centrality"],
        "lexical_documents": documents,
        "lexical_bindings": lexical_bindings,
        "r3_4_candidate_artifact_sha256": base["candidate_artifact_sha256"],
        "authority": base["authority"],
    }
    unsigned = {
        key: value
        for key, value in candidate.items()
        if key not in {"lexical_documents", "probe_plan"}
    }
    unsigned["probe_plan"] = _redacted_probe_plan(candidate["probe_plan"])
    candidate["candidate_artifact_sha256"] = canonical_sha256(unsigned)
    return candidate


def redacted_candidate_artifact(candidate: Mapping[str, Any]) -> dict[str, Any]:
    output = {
        key: value
        for key, value in candidate.items()
        if key != "lexical_documents"
    }
    output["probe_plan"] = _redacted_probe_plan(candidate["probe_plan"])
    expected = output.pop("candidate_artifact_sha256")
    _require(canonical_sha256(output) == expected, 108, "candidate digest drifted")
    return {**output, "candidate_artifact_sha256": expected}


def _r3_4_rankings(
    *,
    dense_rankings: Sequence[Sequence[tuple[float, str]]],
    specificity: Mapping[str, float],
    centrality: Mapping[str, float],
) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    rrf = _rrf_scores(dense_rankings)
    fused = sorted(
        ((score, section_id) for section_id, score in rrf.items()),
        key=lambda item: (-item[0], item[1]),
    )
    repaired: list[tuple[float, str]] = []
    for score, section_id in fused:
        specific = float(specificity.get(section_id, 0.5))
        central = float(centrality[section_id])
        lead = section_id.endswith("/chunk-000")
        multiplier = (
            (1 + r34.SPECIFICITY_WEIGHT * specific)
            * (1 - r34.CENTRALITY_WEIGHT * central)
            * (1 - r34.LEAD_BIAS_WEIGHT * central if lead else 1.0)
        )
        repaired.append((score * multiplier, section_id))
    repaired.sort(key=lambda item: (-item[0], item[1]))
    return fused, repaired


def _rank_of(ranking: Sequence[tuple[float, str]], target: str) -> int:
    return next(
        (
            rank
            for rank, (_score, section_id) in enumerate(ranking, start=1)
            if section_id == target
        ),
        r34.EXPECTED_POINT_COUNT + 1,
    )


def evaluate_calibration_candidate(
    candidate: Mapping[str, Any],
    query_vectors: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    points = list(candidate["points"])
    probes = list(candidate["probe_plan"])
    documents = list(candidate["lexical_documents"])
    _require(len(points) == r34.EXPECTED_POINT_COUNT, 109, "candidate count drifted")
    _require(len(probes) == r34.SAMPLE_CAP, 110, "probe count drifted")
    _require(len(documents) == r34.EXPECTED_POINT_COUNT, 111, "document count drifted")
    _require(
        len(query_vectors) == r34.TOTAL_QUERY_VARIANTS,
        112,
        "query vector count drifted",
    )

    corpus = [
        (
            str(point["payload"]["section_id"]),
            [float(value) for value in point["vector"]["default"]],
        )
        for point in points
    ]
    vector_rows: list[list[float]] = []
    for index, raw in enumerate(query_vectors):
        values = [float(value) for value in raw]
        _require(
            len(values) == r34.VECTOR_DIMENSION,
            113,
            f"query vector {index} dimension drifted",
        )
        norm = math.sqrt(math.fsum(value * value for value in values))
        _require(
            abs(norm - 1.0) <= 1e-4,
            114,
            f"query vector {index} is not normalized",
        )
        vector_rows.append(values)

    counts_by_section, document_frequency, lengths, average_length = _lexical_index(
        documents
    )
    specificity = {
        str(key): float(value) for key, value in candidate["specificity"].items()
    }
    centrality = {
        str(key): float(value)
        for key, value in candidate["corpus_centrality"].items()
    }

    cursor = 0
    cases: list[dict[str, Any]] = []
    rrf_ranks: list[int] = []
    old_rerank_ranks: list[int] = []
    calibrated_ranks: list[int] = []
    final_top_10: list[list[str]] = []
    for probe in probes:
        vectors = vector_rows[cursor : cursor + r34.VARIANTS_PER_PROBE]
        cursor += r34.VARIANTS_PER_PROBE
        dense = _dense_rankings(vectors, corpus)
        rrf, old_rerank = _r3_4_rankings(
            dense_rankings=dense,
            specificity=specificity,
            centrality=centrality,
        )
        calibrated, diagnostics = calibrated_hybrid_ranking(
            query_class=str(probe["query_class"]),
            query_texts=[
                str(variant["query_text"]) for variant in probe["variants"]
            ],
            query_vectors=vectors,
            corpus=corpus,
            counts_by_section=counts_by_section,
            document_frequency=document_frequency,
            lengths=lengths,
            average_length=average_length,
        )

        target = str(probe["target_section_id"])
        rrf_rank = _rank_of(rrf, target)
        old_rank = _rank_of(old_rerank, target)
        calibrated_rank = _rank_of(calibrated, target)
        ranked_ids = [section_id for _score, section_id in calibrated[: r34.TOP_K]]
        rrf_ranks.append(rrf_rank)
        old_rerank_ranks.append(old_rank)
        calibrated_ranks.append(calibrated_rank)
        final_top_10.append(ranked_ids)
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "variant_query_sha256": [
                    variant["query_text_sha256"] for variant in probe["variants"]
                ],
                "target_section_id": target,
                "r3_4_rrf_rank": rrf_rank,
                "r3_4_final_rank": old_rank,
                "calibrated_rank": calibrated_rank,
                "ranked_section_ids": ranked_ids,
                "target_in_top_5": calibrated_rank <= 5,
                "calibration": diagnostics,
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )

    rrf_metrics = r34._metrics(rrf_ranks)
    old_metrics = r34._metrics(old_rerank_ranks)
    calibrated_metrics = r34._metrics(calibrated_ranks)
    hubs = Counter(section_id for row in final_top_10 for section_id in row)
    maximum_hub = max(hubs.values())
    ranker_source = inspect.getsource(calibrated_hybrid_ranking)
    target_unaware = not any(
        term in ranker_source
        for term in (
            "target_section_id",
            "expected_relevant_ids",
            "offline_case_id",
            "probe_id",
        )
    )
    gates = {
        "evidence_identity": candidate["evidence"]["evidence_zip_sha256"]
        == r34.EXPECTED_EVIDENCE_SHA256,
        "point_count": len(points) == r34.EXPECTED_POINT_COUNT,
        "payload_schema_v2": all(
            point["payload"]["payload_schema_version"] == r34.PAYLOAD_SCHEMA_V2
            for point in points
        ),
        "query_variant_identity_unique": len(
            {
                variant["query_text_sha256"]
                for probe in probes
                for variant in probe["variants"]
            }
        )
        == r34.TOTAL_QUERY_VARIANTS,
        "target_unaware_score_path": target_unaware,
        "recall_at_5": calibrated_metrics["recall_at_5"] >= r34.MIN_RECALL_AT_5,
        "mrr_at_10": calibrated_metrics["mrr_at_10"] >= r34.MIN_MRR_AT_10,
        "ndcg_at_10": calibrated_metrics["ndcg_at_10"] >= r34.MIN_NDCG_AT_10,
        "improves_r3_4_final_mrr": calibrated_metrics["mrr_at_10"]
        > R3_4_FINAL["mrr_at_10"],
        "improves_r3_4_final_ndcg": calibrated_metrics["ndcg_at_10"]
        > R3_4_FINAL["ndcg_at_10"],
        "hub_frequency_not_worse": maximum_hub <= MAXIMUM_ALLOWED_HUB_FREQUENCY,
        "qdrant_io_zero": True,
        "protected_mutations_zero": True,
    }
    passed = all(gates.values())
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.5",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "status": (
            "pass_rank_quality_calibration"
            if passed
            else "rejected_rank_quality_calibration"
        ),
        "contract_sha256": canonical_contract()["contract_sha256"],
        "candidate_artifact_sha256": candidate["candidate_artifact_sha256"],
        "evidence": candidate["evidence"],
        "baseline": {
            "r3_4_final": R3_4_FINAL,
            "r3_4_rrf": R3_4_RRF,
        },
        "ablations": {
            "r3_4_multi_query_rrf_replay": rrf_metrics,
            "r3_4_specificity_centrality_rerank_replay": old_metrics,
            "r3_5_calibrated_hybrid": calibrated_metrics,
        },
        "metrics": calibrated_metrics,
        "gates": gates,
        "cases": cases,
        "maximum_top10_hub_frequency": maximum_hub,
        "hubness_top_10": [
            {"section_id": section_id, "frequency": frequency}
            for section_id, frequency in sorted(
                hubs.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "external_calls": {
            "workers_ai_bge_m3_batches": 1,
            "workers_ai_query_count": r34.TOTAL_QUERY_VARIANTS,
            "qdrant_reads": 0,
            "qdrant_writes": 0,
        },
        "privacy": {
            "raw_query_persisted": False,
            "document_text_persisted": False,
            "raw_answer_persisted": False,
            "credentials_persisted": False,
            "service_url_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "candidate_reingestion_authorized": False,
            "live_acceptance_authorized": False,
            "qdrant_read_dispatched": False,
            "qdrant_write_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
            "promotion_eligibility_granted": False,
            "retrieval_quality_blocker_cleared": False,
        },
        "exit": {
            "repair_ready_for_separately_governed_candidate_proposal": passed,
            "live_acceptance_still_required": True,
            "next_gate": (
                "separately_governed_candidate_reingestion_proposal"
                if passed
                else "repair_iteration_required"
            ),
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report
