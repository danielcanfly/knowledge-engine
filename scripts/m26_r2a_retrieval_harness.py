from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from knowledge_engine.m14_retrieval import retrieve_wiki_first
from knowledge_engine.m26_pa7_arbitrary_query_runtime import (
    _build_candidate_pool,
    _candidate_public_metadata,
    _document_context_text,
    _dynamic_evidence_budget,
    _intent_class,
    _list,
    _normalize_request_question,
    _query_context_terms,
    _release_documents,
    _rerank_candidates,
    _select_diverse_candidates,
    _select_evidence,
    dense_channel_from_env,
)
from knowledge_engine.m26_production_answer_bundle import (
    FULL_PRODUCTION_QDRANT_COLLECTION,
    load_production_answer_bundle,
)
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256

QUERIES = [
    ("Q1", "What kind of skill does a Product Manager need?"),
    ("Q2", "What should a Product Manager learn to conduct user research well?"),
    ("Q3", "What is a skill in an AI agent architecture?"),
    ("Q4", "How should an AI agent choose tools safely?"),
    ("Q5", "What metrics help a Product Manager understand retention?"),
    ("Q6", "What is the role of user research in product management?"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--remote-dense", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("M26_PA7_DENSE_COLLECTION", FULL_PRODUCTION_QDRANT_COLLECTION)
    bundle = load_production_answer_bundle()
    dense_channel = dense_channel_from_env(require_remote=args.remote_dense)
    documents = {str(item["section_id"]): item for item in _release_documents(bundle)}
    rows: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for query_id, question in QUERIES:
        trace = trace_query(
            query_id=query_id,
            question=question,
            phase=args.phase,
            bundle=bundle,
            documents=documents,
            dense_channel=dense_channel,
        )
        traces.append(trace)
        rows.append(matrix_row(trace))
        (out / f"{args.phase}_{query_id}.json").write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n"
        )
    (out / f"{args.phase}_traces.json").write_text(
        json.dumps(traces, indent=2, sort_keys=True) + "\n"
    )
    with (out / f"{args.phase}_matrix.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def trace_query(
    *,
    query_id: str,
    question: str,
    phase: str,
    bundle: Any,
    documents: Mapping[str, Mapping[str, Any]],
    dense_channel: Any,
) -> dict[str, Any]:
    normalized = _normalize_request_question(question)
    intent_class = _intent_class(normalized)
    dense = dense_channel.search(question=normalized, bundle=bundle, top_k=8)
    lexical = retrieve_wiki_first(
        query=normalized,
        allowed_audiences={"public", "internal"},
        lexical_index=bundle.lexical_index,
        graph=bundle.graph,
        relation_graph=bundle.graph_v2,
        relation_aware_expansion=True,
        provenance=bundle.provenance,
        semantic_index=None,
        limit=8,
    )
    lexical_results = _list(lexical.get("results"), "lexical results")
    dense_candidates = _list(dense.get("candidates"), "dense candidates")
    pool = _build_candidate_pool(
        bundle=bundle,
        documents=documents,
        lexical_results=lexical_results,
        dense_candidates=dense_candidates,
        question=normalized,
        intent_class=intent_class,
    )
    budget = _dynamic_evidence_budget(question=normalized, intent_class=intent_class)
    ordered = _rerank_candidates(pool, budget=budget)
    selected_candidates = _select_diverse_candidates(ordered, budget=budget)
    evidence = _select_evidence(
        bundle=bundle,
        lexical_result=lexical,
        dense_result=dense,
        trace_id=f"m26r2a_{phase}_{query_id.lower()}",
        question=normalized,
        intent_class=intent_class,
    )
    query_terms = query_context_terms(normalized)
    return {
        "phase": phase,
        "query_id": query_id,
        "question": question,
        "normalized_question": normalized,
        "intent_class": intent_class,
        "budget": budget,
        "query_terms": sorted(query_terms),
        "lexical_top8": [
            public_result(item, documents, query_terms=query_terms, rank=rank)
            for rank, item in enumerate(lexical_results[:8], start=1)
        ],
        "dense_top8": [
            public_result(item, documents, query_terms=query_terms, rank=rank)
            for rank, item in enumerate(dense_candidates[:8], start=1)
        ],
        "candidate_pool_top20": [
            public_candidate(item, documents, query_terms=query_terms, rank=rank)
            for rank, item in enumerate(ordered[:20], start=1)
        ],
        "selected_candidates": [
            public_candidate(item, documents, query_terms=query_terms, rank=rank)
            for rank, item in enumerate(selected_candidates, start=1)
        ],
        "selected_evidence": [
            public_evidence(item, query_terms=query_terms, rank=rank)
            for rank, item in enumerate(evidence, start=1)
        ],
    }


def public_result(
    item: Any,
    documents: Mapping[str, Mapping[str, Any]],
    *,
    query_terms: set[str],
    rank: int,
) -> dict[str, Any]:
    data = dict(item) if isinstance(item, Mapping) else {}
    document = documents.get(str(data.get("section_id", "")), {})
    text = _document_context_text(document) or str(
        data.get("text") or data.get("passage_text") or ""
    )
    return {
        "rank": rank,
        "source_id": str(data.get("source_id") or document.get("source_id", "")),
        "source_identity": str(data.get("source_identity") or document.get("source_identity", "")),
        "section_id": str(data.get("section_id", "")),
        "concept_id": str(data.get("concept_id") or document.get("concept_id", "")),
        "title": title_for(document),
        "score": number(data.get("score")),
        "coverage_terms": sorted(coverage_terms(text, query_terms)),
        "coverage_count": len(coverage_terms(text, query_terms)),
        "snippet": snippet(text, query_terms),
    }


def public_candidate(
    item: Mapping[str, Any],
    documents: Mapping[str, Mapping[str, Any]],
    *,
    query_terms: set[str],
    rank: int,
) -> dict[str, Any]:
    document = documents.get(str(item.get("section_id", "")), {})
    text = _document_context_text(document)
    metadata = _candidate_public_metadata(item)
    return {
        "rank": rank,
        "source_id": str(document.get("source_id", "")),
        "source_identity": str(document.get("source_identity", "")),
        "section_id": str(item.get("section_id", "")),
        "concept_id": str(document.get("concept_id", "")),
        "title": title_for(document),
        "channels": sorted(str(channel) for channel in item.get("channels", [])),
        "score": number(item.get("score")),
        "rerank_score": number(item.get("rerank_score")),
        "seed_rank": int(item.get("seed_rank", 999)),
        "coverage_terms": sorted(coverage_terms(text, query_terms)),
        "coverage_count": len(coverage_terms(text, query_terms)),
        "metadata": metadata,
        "snippet": snippet(text, query_terms),
    }


def public_evidence(
    item: Mapping[str, Any],
    *,
    query_terms: set[str],
    rank: int,
) -> dict[str, Any]:
    text = str(item.get("passage_text", ""))
    return {
        "rank": rank,
        "source_id": str(item.get("source_id", "")),
        "source_identity": str(item.get("source_identity", "")),
        "section_id": str(item.get("section_id", "")),
        "concept_id": str(item.get("concept_id", "")),
        "channels": list(item.get("channels", [])),
        "coverage_terms": sorted(coverage_terms(text, query_terms)),
        "coverage_count": len(coverage_terms(text, query_terms)),
        "retrieval_metadata": item.get("retrieval_metadata", {}),
        "passage_sha256": canonical_sha256(text),
        "snippet": snippet(text, query_terms),
    }


def matrix_row(trace: Mapping[str, Any]) -> dict[str, str]:
    selected = trace["selected_evidence"]
    ai_sources = [item for item in selected if "ai" in item["source_identity"].casefold()]
    pm_sources = [
        item
        for item in selected
        if "pm-" in item["source_identity"].casefold()
        or "product-manager" in item["source_identity"].casefold()
        or "product" in item["source_identity"].casefold()
    ]
    top = selected[0] if selected else {}
    coverage = [str(item.get("coverage_count", 0)) for item in selected]
    return {
        "query_id": str(trace["query_id"]),
        "phase": str(trace["phase"]),
        "question": str(trace["question"]),
        "intent_class": str(trace["intent_class"]),
        "lexical_top8": compact_sources(trace["lexical_top8"]),
        "dense_top8": compact_sources(trace["dense_top8"]),
        "selected_sources": compact_sources(selected),
        "selected_context_coverage": ",".join(coverage),
        "diagnosis": (
            f"top={top.get('source_identity','')}; "
            f"pm_sources={len(pm_sources)}; ai_sources={len(ai_sources)}; "
            f"top_coverage={top.get('coverage_terms', [])}"
        ),
        "pass_fail": "CAPTURED",
    }


def compact_sources(items: Sequence[Any]) -> str:
    return " | ".join(
        compact_source(item)
        for item in items
        if isinstance(item, Mapping)
    )


def compact_source(item: Mapping[str, Any]) -> str:
    source = item.get("source_identity") or item.get("source_id")
    return f"{item.get('rank')}:{source}[{item.get('coverage_count')}]"


def query_context_terms(text: str) -> set[str]:
    return _query_context_terms(text)


def coverage_terms(text: str, query_terms: set[str]) -> set[str]:
    folded = str(text).casefold()
    return {term for term in query_terms if term in folded}


def title_for(document: Mapping[str, Any]) -> str:
    for key in ("section_title", "title", "article_title", "source_title"):
        value = str(document.get(key, "")).strip()
        if value:
            return value
    return ""


def snippet(text: str, query_terms: set[str], *, max_chars: int = 260) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    folded = compact.casefold()
    positions = [folded.find(term) for term in sorted(query_terms) if folded.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - 80)
    end = min(len(compact), start + max_chars)
    return compact[start:end].strip()


def number(value: Any) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
