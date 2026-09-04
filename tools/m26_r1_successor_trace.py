from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from knowledge_engine.m14_retrieval import retrieve_wiki_first

SOURCE_AUTHORITY = {
    "release_id": "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440",
    "source_repository_commit": "a738f20b16f10925c8adfe4d625be8db30fb269c",
    "source_admission_sha256": "ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d",
    "pack_sha256": "59012fe3818cc1c1e45bed4812cef19f00075bb644b7e0b5fe3cb3a68e0498f8",
}

CASES = (
    ("S02", "What does Harness Theory say an agent harness is responsible for?", "daniel_blog_en__harness-theory-part-1"),
    ("S03", "What is the difference between a workflow and an agent?", "daniel_blog_en__ai-agentic-workflow-series-6"),
    ("S07", "What evidence should a user inspect in Codex after a task is marked done?", "daniel_blog_en__codex-agent-harness-command-center-part-3"),
    ("S11", "What does Daniel mean by production RAG, and how does it differ from a toy RAG demo?", "daniel_blog_en__from-rag-to-production-rag-part-3"),
    ("S12", "When does a LoRA adapter not need to be merged into its base model?", "daniel_blog_en__local-llm-fine-tuning-08"),
    ("S14", "What does a citation check catch that a faithfulness check can miss?", "daniel_blog_en__from-rag-to-production-rag-part-3"),
    ("S20", "What should a validator do in an LLM application?", "daniel_blog_en__pm-llm-application-engineering-02"),
    ("S21", "How do tasks let work outlive an HTTP request?", "daniel_blog_en__stateless-mcp-architecture-part-2"),
    ("S22", "What makes an MCP contract healthy rather than merely full of fields?", "daniel_blog_en__mcp-engineering-deep-dive-03"),
    ("S26", "Why are tasks different from request-scoped state?", "daniel_blog_en__stateless-mcp-architecture-part-2"),
    ("S27", "Why does a retrieval miss need to be separated from a generation failure?", "daniel_blog_en__rag-engineering-in-practice-06"),
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _semantic_index(path: Path) -> dict[str, Any] | None:
    rows = _load_jsonl(path)
    if not rows:
        return None
    return {"schema_version": "knowledge-engine-semantic-index/v1", "documents": rows}


def _compatibility_graph(documents: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, str] = {}
    for document in documents:
        concept_id = str(document["concept_id"])
        nodes.setdefault(concept_id, str(document.get("audience") or "public"))
    return {
        "schema_version": "knowledge-os-graph/v1",
        "nodes": [
            {"concept_id": concept_id, "audience": audience}
            for concept_id, audience in sorted(nodes.items())
        ],
        "edges": [],
    }


def _expected_rank(all_results: list[dict[str, Any]], expected_source_id: str) -> int | None:
    for index, result in enumerate(all_results, start=1):
        citations = result.get("citations") or []
        if any(str(item.get("source_id")) == expected_source_id for item in citations if isinstance(item, dict)):
            return index
        # The isolated candidate JSONL uses source_id directly while the synthetic
        # provenance envelope below intentionally contains no external locators.
        if str(result.get("source_id") or "") == expected_source_id:
            return index
        if str(result.get("concept_id") or "") and str(result.get("_candidate_source_id") or "") == expected_source_id:
            return index
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexical", type=Path, required=True)
    parser.add_argument("--semantic", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    documents = _load_jsonl(args.lexical)
    # m14 retrieval returns concept/section identities. Candidate source_id is
    # mapped via concept_id so rank can be measured without mutating provenance.
    concept_to_source: dict[str, str] = {}
    for document in documents:
        concept_to_source[str(document["concept_id"])] = str(document.get("source_id") or "")

    lexical_index = {"documents": documents}
    semantic_index = _semantic_index(args.semantic)
    graph = _compatibility_graph(documents)
    provenance = {"records": []}

    case_rows: list[dict[str, Any]] = []
    for case_id, question, expected_source_id in CASES:
        # limit=20 is the maximum supported by the production scorer and is used
        # only to observe rank. Runtime admission remains top-8.
        result = retrieve_wiki_first(
            query=question,
            allowed_audiences={"public", "internal"},
            lexical_index=lexical_index,
            graph=graph,
            provenance=provenance,
            semantic_index=semantic_index,
            relation_aware_expansion=False,
            limit=20,
        )
        observed: list[dict[str, Any]] = []
        expected_rank: int | None = None
        expected_section_id = ""
        for index, item in enumerate(result.get("results", []), start=1):
            source_id = concept_to_source.get(str(item.get("concept_id") or ""), "")
            row = {
                "rank": index,
                "source_id": source_id,
                "concept_id": item.get("concept_id"),
                "section_id": item.get("section_id"),
                "section_title": item.get("section_title"),
                "score": item.get("score"),
                "score_components": item.get("score_components"),
            }
            observed.append(row)
            if source_id == expected_source_id and expected_rank is None:
                expected_rank = index
                expected_section_id = str(item.get("section_id") or "")

        candidate_hit_top8 = expected_rank is not None and expected_rank <= 8
        first_bad_stage = (
            "NOT_CANDIDATE_GENERATION_TOP8"
            if candidate_hit_top8
            else "CANDIDATE_GENERATION_OR_RANKING_BEFORE_TOP8"
        )
        case_rows.append(
            {
                "case_id": case_id,
                "question": question,
                "expected_source_id": expected_source_id,
                "expected_rank_within_top20": expected_rank,
                "expected_section_id": expected_section_id,
                "candidate_hit_top8": candidate_hit_top8,
                "first_bad_stage": first_bad_stage,
                "top20": observed,
            }
        )

    payload = {
        "schema_version": "m26-aqv2-r1-successor-first-bad-trace/v1",
        "authority": SOURCE_AUTHORITY,
        "lexical_document_count": len(documents),
        "semantic_document_count": len((semantic_index or {}).get("documents", [])),
        "runtime_top_k": 8,
        "cases": case_rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "lexical_document_count": payload["lexical_document_count"],
        "semantic_document_count": payload["semantic_document_count"],
        "cases": [
            {
                "case_id": row["case_id"],
                "expected_rank_within_top20": row["expected_rank_within_top20"],
                "candidate_hit_top8": row["candidate_hit_top8"],
                "first_bad_stage": row["first_bad_stage"],
            }
            for row in case_rows
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
