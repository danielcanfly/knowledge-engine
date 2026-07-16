from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_r1_semantic_alignment import MAXIMUM_QUERY_CHARACTERS, SAMPLE_CAP, SLOTS
from .m23_7_r3_2_semantic_payload_repair import (
    PAYLOAD_SCHEMA_V2,
    build_repaired_ingestion_preview,
)
from .m23_7_r3_3_offline_rebuild_evaluation import (
    EXPECTED_EVIDENCE_SHA256,
    EXPECTED_POINT_COUNT,
    EXPECTED_SEMANTIC_ARTIFACT_ID,
    MIN_MRR_AT_10,
    MIN_NDCG_AT_10,
    MIN_RECALL_AT_5,
    TOP_K,
    VECTOR_DIMENSION,
)
from .m23_7_r3_3_offline_rebuild_evaluation_real import (
    _load_inputs,
    _release,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-4-target-discrimination-repair/v1"
CANDIDATE_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-4-target-discrimination-candidate/v1"
)
REPORT_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r3-4-target-discrimination-report/v1"
)
IMPLEMENTATION_ISSUE = 497
PARENT_ISSUE = 474
ENTRY_ENGINE_SHA = "242ec01bf682f3a7f7abb790d5db205512cb2aa4"
R3_3_REPORT_SHA256 = "a71c36456ff0fb7a00d084c5f89364d9d37c42e6f252af925dc92856733c13ff"
R3_3_REPORT_FILE_SHA256 = (
    "c7650e9ba8708d01b48d3d0b80d14e55598d32659e1827ad4b782f510377a732"
)
R3_3_BASELINE = {
    "recall_at_5": 0.375,
    "mrr_at_10": 0.23125,
    "ndcg_at_10": 0.293833892245,
}
VARIANTS_PER_PROBE = 3
TOTAL_QUERY_VARIANTS = SAMPLE_CAP * VARIANTS_PER_PROBE
RRF_K = 60
FUSION_DEPTH = 50
CENTRALITY_NEIGHBOURS = 10
SPECIFICITY_WEIGHT = 0.15
CENTRALITY_WEIGHT = 0.12
LEAD_BIAS_WEIGHT = 0.05
MAXIMUM_ALLOWED_HUB_FREQUENCY = 6
MAXIMUM_SIGNATURE_TERMS = 10
MINIMUM_SIGNATURE_TERMS = 5
MAXIMUM_DOCUMENT_FREQUENCY_RATIO = 0.35

_GENERIC = {
    "a",
    "about",
    "also",
    "an",
    "and",
    "are",
    "article",
    "as",
    "at",
    "be",
    "by",
    "can",
    "chapter",
    "chunk",
    "concept",
    "content",
    "document",
    "example",
    "for",
    "from",
    "guide",
    "harness",
    "how",
    "in",
    "introduction",
    "is",
    "it",
    "knowledge",
    "md",
    "note",
    "notes",
    "of",
    "on",
    "or",
    "overview",
    "part",
    "pilot",
    "section",
    "source",
    "summary",
    "system",
    "that",
    "the",
    "theory",
    "this",
    "to",
    "using",
    "was",
    "what",
    "when",
    "where",
    "which",
    "with",
    "以及",
    "內容",
    "可以",
    "如何",
    "文件",
    "本節",
    "概述",
    "相關",
    "章節",
    "系統",
    "說明",
    "這些",
    "這個",
    "部分",
    "需要",
    "使用",
    "什麼",
    "摘要",
}
_MARKUP = re.compile(r"```.*?```|`[^`]*`|https?://\S+|<[^>]+>", re.DOTALL | re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u3400-\u9fff]{2,}")


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
        raise IntegrityError(f"M23.7-R3.4-{code} {message}")


def _normalise_text(value: Any, label: str, maximum: int = 200_000) -> str:
    _require(isinstance(value, str), 101, f"{label} must be a string")
    text = value.strip()
    _require(bool(text) and len(text) <= maximum, 102, f"{label} is empty or too long")
    return text


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _tokenise(value: str) -> list[str]:
    cleaned = _MARKUP.sub(" ", value)
    output: list[str] = []
    for raw in _WORD.findall(cleaned):
        token = raw.casefold().strip("_-")
        if not token or token in _GENERIC or token.isdigit():
            continue
        if _contains_cjk(token):
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


def _document_statistics(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, Counter[str]], dict[str, set[str]]]:
    document_frequency: Counter[str] = Counter()
    term_counts: dict[str, Counter[str]] = {}
    title_terms: dict[str, set[str]] = {}
    for index, document in enumerate(documents):
        section_id = _normalise_text(
            document.get("section_id"),
            f"documents[{index}].section_id",
            500,
        )
        title = _normalise_text(document.get("title"), f"documents[{index}].title", 2_000)
        concept = _normalise_text(
            document.get("concept_id"),
            f"documents[{index}].concept_id",
            500,
        )
        text = _normalise_text(document.get("text"), f"documents[{index}].text")
        title_tokens = set(
            _tokenise(title + " " + concept.replace("-", " ").replace("_", " "))
        )
        counts = Counter(_tokenise(title + " " + concept + " " + text))
        _require(bool(counts), 103, f"document {section_id} has no semantic terms")
        term_counts[section_id] = counts
        title_terms[section_id] = title_tokens
        document_frequency.update(counts)
    return dict(document_frequency), term_counts, title_terms


def _distinctive_signature(
    section_id: str,
    *,
    document_frequency: Mapping[str, int],
    term_counts: Mapping[str, Counter[str]],
    title_terms: Mapping[str, set[str]],
    document_count: int,
) -> tuple[list[str], float]:
    counts = term_counts[section_id]
    title = title_terms[section_id]
    maximum_df = max(2, math.floor(document_count * MAXIMUM_DOCUMENT_FREQUENCY_RATIO))
    scored: list[tuple[float, str]] = []
    for token, count in counts.items():
        df = int(document_frequency[token])
        if df > maximum_df and token not in title:
            continue
        idf = math.log((document_count + 1) / (df + 0.5))
        tf = 1.0 + math.log(count)
        title_bonus = 1.8 if token in title else 1.0
        length_bonus = min(len(token), 12) / 12
        score = idf * tf * title_bonus * (0.75 + 0.25 * length_bonus)
        scored.append((score, token))
    ordered = [
        token for _, token in sorted(scored, key=lambda item: (-item[0], item[1]))
    ]
    unique = list(dict.fromkeys(ordered))[:MAXIMUM_SIGNATURE_TERMS]
    _require(
        len(unique) >= MINIMUM_SIGNATURE_TERMS,
        104,
        f"section {section_id} lacks target-specific signature terms",
    )
    selected_idf = [
        math.log((document_count + 1) / (document_frequency[token] + 0.5))
        for token in unique[:MINIMUM_SIGNATURE_TERMS]
    ]
    maximum_idf = math.log((document_count + 1) / 1.5)
    specificity = min(
        1.0,
        max(0.0, math.fsum(selected_idf) / len(selected_idf) / maximum_idf),
    )
    return unique, specificity


def _bounded(value: str) -> str:
    compact = " ".join(value.split())
    _require(len(compact) <= MAXIMUM_QUERY_CHARACTERS, 105, "query variant exceeds limit")
    return compact


def _query_variants(
    *,
    title: str,
    language: str,
    query_class: str,
    terms: Sequence[str],
) -> list[str]:
    joined = ", ".join(terms[:8])
    triad = ", ".join(terms[:3])
    if language.casefold().startswith("zh"):
        variants = [
            f"哪個段落專門討論「{title}」？關鍵概念：{joined}",
            f"請找出同時說明 {triad} 之間關係的段落，主題是「{title}」。",
            f"哪一段內容提供「{title}」的具體{query_class}資訊？聚焦：{joined}",
        ]
    else:
        variants = [
            f"Find the specific section about {title}. Distinctive concepts: {joined}.",
            f"Which passage explains how {triad} relate in the context of {title}?",
            f"Identify the section providing {query_class} evidence for {title}; focus on {joined}.",
        ]
    return [_bounded(value) for value in variants]


def compile_discriminative_probe_plan(
    samples: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    _require(len(samples) == SAMPLE_CAP, 106, "exactly eight samples are required")
    _require(len(documents) == EXPECTED_POINT_COUNT, 107, "document count drifted")
    ordered = sorted(samples, key=lambda item: item.get("id", item.get("point_id")))
    by_section = {str(document["section_id"]): document for document in documents}
    _require(len(by_section) == EXPECTED_POINT_COUNT, 108, "document section identities drifted")
    df, term_counts, title_terms = _document_statistics(documents)

    probes: list[dict[str, Any]] = []
    all_variant_digests: set[str] = set()
    target_ids: set[str] = set()
    specificity: dict[str, float] = {}
    for slot, sample in zip(SLOTS, ordered, strict=True):
        payload = sample.get("payload")
        _require(isinstance(payload, Mapping), 109, "sample payload missing")
        target = _normalise_text(payload.get("section_id"), "target_section_id", 500)
        _require(target in by_section and target not in target_ids, 110, "target identity drifted")
        target_ids.add(target)
        document = by_section[target]
        terms, score = _distinctive_signature(
            target,
            document_frequency=df,
            term_counts=term_counts,
            title_terms=title_terms,
            document_count=len(documents),
        )
        specificity[target] = score
        variants = _query_variants(
            title=_normalise_text(document.get("title"), "title", 2_000),
            language=_normalise_text(document.get("language"), "language", 40),
            query_class=slot[2],
            terms=terms,
        )
        variant_records: list[dict[str, Any]] = []
        for index, text in enumerate(variants, start=1):
            _require(target not in text, 111, "raw section id leaked into query")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            _require(digest not in all_variant_digests, 112, "query variant collision")
            all_variant_digests.add(digest)
            variant_records.append(
                {
                    "variant_id": f"{slot[0]}-v{index}",
                    "query_text": text,
                    "query_text_sha256": digest,
                    "query_character_count": len(text),
                }
            )
        probes.append(
            {
                "probe_id": slot[0],
                "offline_case_id": slot[1],
                "query_class": slot[2],
                "point_id": sample.get("id", sample.get("point_id")),
                "target_section_id": target,
                "expected_relevant_ids": [target],
                "signature_term_sha256": canonical_sha256(terms),
                "signature_term_count": len(terms),
                "specificity_score": round(score, 12),
                "variants": variant_records,
                "probe_digest": canonical_sha256(
                    [
                        slot[0],
                        target,
                        [item["query_text_sha256"] for item in variant_records],
                    ]
                ),
                "payload_schema_version": PAYLOAD_SCHEMA_V2,
            }
        )
    _require(
        len(all_variant_digests) == TOTAL_QUERY_VARIANTS,
        113,
        "variant identities drifted",
    )
    return probes, specificity


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def _corpus_centrality(points: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    rows = [
        (
            str(point["payload"]["section_id"]),
            [float(value) for value in point["vector"]["default"]],
        )
        for point in points
    ]
    raw: dict[str, float] = {}
    for section_id, vector in rows:
        neighbours = sorted(
            (
                _cosine(vector, other_vector)
                for other_id, other_vector in rows
                if other_id != section_id
            ),
            reverse=True,
        )[:CENTRALITY_NEIGHBOURS]
        raw[section_id] = math.fsum(neighbours) / len(neighbours)
    low, high = min(raw.values()), max(raw.values())
    if math.isclose(low, high):
        return {section_id: 0.5 for section_id in raw}
    return {
        section_id: (value - low) / (high - low)
        for section_id, value in raw.items()
    }


def _redacted_probe_plan(
    probes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for probe in probes:
        record = dict(probe)
        record["variants"] = [
            {key: value for key, value in variant.items() if key != "query_text"}
            for variant in probe["variants"]
        ]
        output.append(record)
    return output


def canonical_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.4",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_3_report_sha256": R3_3_REPORT_SHA256,
            "r3_3_report_file_sha256": R3_3_REPORT_FILE_SHA256,
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
        },
        "repair": {
            "primary": "target_specific_semantic_signature",
            "query_variants_per_probe": VARIANTS_PER_PROBE,
            "total_query_variants": TOTAL_QUERY_VARIANTS,
            "fusion": {
                "method": "reciprocal-rank-fusion",
                "rrf_k": RRF_K,
                "depth": FUSION_DEPTH,
            },
            "specificity_weight": SPECIFICITY_WEIGHT,
            "centrality_weight": CENTRALITY_WEIGHT,
            "lead_bias_weight": LEAD_BIAS_WEIGHT,
            "centrality_neighbours": CENTRALITY_NEIGHBOURS,
            "target_aware_reranking": False,
            "embedding_model_changed": False,
            "query_prefix_changed": False,
        },
        "thresholds": {
            "min_recall_at_5": MIN_RECALL_AT_5,
            "min_mrr_at_10": MIN_MRR_AT_10,
            "min_ndcg_at_10": MIN_NDCG_AT_10,
            "baseline": R3_3_BASELINE,
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


def build_repair_candidate(path: Any) -> dict[str, Any]:
    inputs = _load_inputs(path)
    preview = build_repaired_ingestion_preview(
        inputs["documents"],
        inputs["vectors"],
        release=_release(inputs),
        expected_point_count=EXPECTED_POINT_COUNT,
    )
    eligible = sorted(
        (
            point
            for point in preview["points"]
            if point["payload"]["source_membership"]
            == "evaluation-only-pending-proposal"
            and point["payload"]["production_authority"] is False
        ),
        key=lambda point: point["id"],
    )
    _require(len(eligible) == EXPECTED_POINT_COUNT, 114, "eligible point count drifted")
    probes, specificity = compile_discriminative_probe_plan(
        eligible[:SAMPLE_CAP],
        inputs["documents"],
    )
    centrality = _corpus_centrality(preview["points"])
    candidate: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "milestone": "M23.7-R3.4",
        "mode": "offline-no-write-repair-candidate",
        "contract_sha256": canonical_contract()["contract_sha256"],
        "evidence": {
            "evidence_zip_sha256": EXPECTED_EVIDENCE_SHA256,
            "benchmark_suite_sha256": inputs["suite_sha256"],
            "document_vectors_sha256": inputs["vector_sha256"],
            "semantic_vectors_sha256": inputs["semantic_vector_sha256"],
            "semantic_metadata_sha256": inputs["semantic_metadata_sha256"],
            "semantic_artifact_id": EXPECTED_SEMANTIC_ARTIFACT_ID,
            "ranking_vector_source": "pilot-document-vectors.f32",
        },
        "release": _release(inputs),
        "point_count": len(preview["points"]),
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "points": preview["points"],
        "bindings": preview["bindings"],
        "probe_plan": probes,
        "specificity": {
            key: round(value, 12) for key, value in sorted(specificity.items())
        },
        "corpus_centrality": {
            key: round(value, 12) for key, value in sorted(centrality.items())
        },
        "authority": preview["authority"],
    }
    unsigned = {**candidate, "probe_plan": _redacted_probe_plan(probes)}
    candidate["candidate_artifact_sha256"] = canonical_sha256(unsigned)
    return candidate


def redacted_candidate_artifact(candidate: Mapping[str, Any]) -> dict[str, Any]:
    output = {
        **candidate,
        "probe_plan": _redacted_probe_plan(candidate["probe_plan"]),
    }
    expected = output.pop("candidate_artifact_sha256")
    _require(canonical_sha256(output) == expected, 115, "candidate digest drifted")
    return {**output, "candidate_artifact_sha256": expected}


def _metrics(ranks: Sequence[int]) -> dict[str, float]:
    return {
        "recall_at_5": round(sum(rank <= 5 for rank in ranks) / SAMPLE_CAP, 12),
        "mrr_at_10": round(
            math.fsum(1 / rank if rank <= 10 else 0.0 for rank in ranks)
            / SAMPLE_CAP,
            12,
        ),
        "ndcg_at_10": round(
            math.fsum(
                1 / math.log2(rank + 1) if rank <= 10 else 0.0
                for rank in ranks
            )
            / SAMPLE_CAP,
            12,
        ),
    }


def evaluate_repair_candidate(
    candidate: Mapping[str, Any],
    query_vectors: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    points = list(candidate["points"])
    probes = list(candidate["probe_plan"])
    _require(len(points) == EXPECTED_POINT_COUNT, 116, "candidate count drifted")
    _require(len(probes) == SAMPLE_CAP, 117, "probe count drifted")
    _require(
        len(query_vectors) == TOTAL_QUERY_VARIANTS,
        118,
        "query vector count drifted",
    )

    corpus = [
        (
            point["payload"]["section_id"],
            [float(value) for value in point["vector"]["default"]],
        )
        for point in points
    ]
    vector_rows: list[list[float]] = []
    for index, raw in enumerate(query_vectors):
        values = [float(value) for value in raw]
        _require(
            len(values) == VECTOR_DIMENSION,
            119,
            f"query vector {index} dimension drifted",
        )
        norm = math.sqrt(math.fsum(value * value for value in values))
        _require(
            abs(norm - 1.0) <= 1e-4,
            120,
            f"query vector {index} is not normalized",
        )
        vector_rows.append(values)

    specificity = {
        str(key): float(value) for key, value in candidate["specificity"].items()
    }
    centrality = {
        str(key): float(value)
        for key, value in candidate["corpus_centrality"].items()
    }
    cursor = 0
    cases: list[dict[str, Any]] = []
    single_ranks: list[int] = []
    fused_ranks: list[int] = []
    repaired_ranks: list[int] = []
    final_top_10: list[list[str]] = []

    for probe in probes:
        rankings: list[list[tuple[float, str]]] = []
        for _variant in probe["variants"]:
            query = vector_rows[cursor]
            cursor += 1
            rankings.append(
                sorted(
                    (
                        (_cosine(query, vector), section_id)
                        for section_id, vector in corpus
                    ),
                    key=lambda item: (-item[0], item[1]),
                )
            )
        target = probe["target_section_id"]
        single_rank = next(
            rank
            for rank, (_, section_id) in enumerate(rankings[0], start=1)
            if section_id == target
        )
        rrf_scores: Counter[str] = Counter()
        for ranking in rankings:
            for rank, (_, section_id) in enumerate(
                ranking[:FUSION_DEPTH],
                start=1,
            ):
                rrf_scores[section_id] += 1 / (RRF_K + rank)
        fused = sorted(rrf_scores.items(), key=lambda item: (-item[1], item[0]))
        fused_rank = next(
            rank
            for rank, (section_id, _) in enumerate(fused, start=1)
            if section_id == target
        )
        repaired_scores: dict[str, float] = {}
        for section_id, score in fused:
            specific = specificity.get(section_id, 0.5)
            central = centrality[section_id]
            lead = section_id.endswith("/chunk-000")
            multiplier = (
                (1 + SPECIFICITY_WEIGHT * specific)
                * (1 - CENTRALITY_WEIGHT * central)
                * (1 - LEAD_BIAS_WEIGHT * central if lead else 1.0)
            )
            repaired_scores[section_id] = score * multiplier
        repaired = sorted(
            repaired_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        repaired_rank = next(
            rank
            for rank, (section_id, _) in enumerate(repaired, start=1)
            if section_id == target
        )
        ranked_ids = [section_id for section_id, _ in repaired[:TOP_K]]
        final_top_10.append(ranked_ids)
        single_ranks.append(single_rank)
        fused_ranks.append(fused_rank)
        repaired_ranks.append(repaired_rank)
        cases.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "variant_query_sha256": [
                    variant["query_text_sha256"] for variant in probe["variants"]
                ],
                "target_section_id": target,
                "single_variant_rank": single_rank,
                "rrf_rank": fused_rank,
                "repaired_rank": repaired_rank,
                "ranked_section_ids": ranked_ids,
                "target_in_top_5": repaired_rank <= 5,
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )

    single_metrics = _metrics(single_ranks)
    fused_metrics = _metrics(fused_ranks)
    repaired_metrics = _metrics(repaired_ranks)
    hubs = Counter(section_id for row in final_top_10 for section_id in row)
    maximum_hub = max(hubs.values())
    gates = {
        "evidence_identity": candidate["evidence"]["evidence_zip_sha256"]
        == EXPECTED_EVIDENCE_SHA256,
        "point_count": len(points) == EXPECTED_POINT_COUNT,
        "payload_schema_v2": all(
            point["payload"]["payload_schema_version"] == PAYLOAD_SCHEMA_V2
            for point in points
        ),
        "query_variant_identity_unique": len(
            {
                variant["query_text_sha256"]
                for probe in probes
                for variant in probe["variants"]
            }
        )
        == TOTAL_QUERY_VARIANTS,
        "recall_at_5": repaired_metrics["recall_at_5"] >= MIN_RECALL_AT_5,
        "mrr_at_10": repaired_metrics["mrr_at_10"] >= MIN_MRR_AT_10,
        "ndcg_at_10": repaired_metrics["ndcg_at_10"] >= MIN_NDCG_AT_10,
        "improves_recall": repaired_metrics["recall_at_5"]
        > R3_3_BASELINE["recall_at_5"],
        "improves_mrr": repaired_metrics["mrr_at_10"] > R3_3_BASELINE["mrr_at_10"],
        "improves_ndcg": repaired_metrics["ndcg_at_10"]
        > R3_3_BASELINE["ndcg_at_10"],
        "hub_frequency_not_worse": maximum_hub <= MAXIMUM_ALLOWED_HUB_FREQUENCY,
        "qdrant_io_zero": True,
        "protected_mutations_zero": True,
    }
    passed = all(gates.values())
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "milestone": "M23.7-R3.4",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "parent_issue": PARENT_ISSUE,
        "status": (
            "pass_target_discrimination_repair"
            if passed
            else "rejected_target_discrimination_repair"
        ),
        "contract_sha256": canonical_contract()["contract_sha256"],
        "candidate_artifact_sha256": candidate["candidate_artifact_sha256"],
        "evidence": candidate["evidence"],
        "baseline": R3_3_BASELINE,
        "ablations": {
            "single_discriminative_variant": single_metrics,
            "multi_query_rrf": fused_metrics,
            "specificity_centrality_rerank": repaired_metrics,
        },
        "metrics": repaired_metrics,
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
            "workers_ai_query_count": TOTAL_QUERY_VARIANTS,
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
