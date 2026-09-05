from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(sys.argv[1])
SOURCE_ROOT = Path(sys.argv[2])
OUT = Path(sys.argv[3])
sys.path.insert(0, str(ROOT / "src"))

from knowledge_engine.m14_retrieval import retrieve_wiki_first  # noqa: E402
from knowledge_engine.m26_pa7_arbitrary_query_runtime import (  # noqa: E402
    _answer_bearing_query_focus,
    _coverage_terms,
    _select_evidence,
)
from knowledge_engine.m26_production_answer_bundle import ProductionAnswerBundle  # noqa: E402


RELEASE = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
LEX_SHA = "1ee4e01ff7b08ef6f54b445112db25565eb8f72b932ec89473947fb7ba4dc3bf"
SEM_SHA = "0982aaa55893bb2f95a8c0e0571cf5bef8beffb56346c9edf05c5a2e83597012"
SRC_SHA = "3b63e70b99b25cc0e83a2ceb56bf8b515402f92774af0a839839abd6cb0b864f"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_bundle() -> ProductionAnswerBundle:
    rel = SOURCE_ROOT / "candidate-release"
    lexical_rows = jsonl(rel / "lexical-documents.jsonl")
    semantic_rows = jsonl(rel / "semantic-inputs.jsonl")
    provenance_rows = jsonl(rel / "provenance.jsonl")
    nodes = jsonl(SOURCE_ROOT / "candidate-nodes.jsonl")
    edges = jsonl(SOURCE_ROOT / "candidate-edges.jsonl")
    # The R0 candidate graph is structural JSONL. Convert it into the
    # renderer-neutral shape consumed by the baseline retrieval seam.
    graph_nodes = []
    for node in nodes:
        graph_nodes.append(
            {
                "concept_id": str(node["node_id"]),
                "audience": "public",
            }
        )
    graph_edges = []
    for edge in edges:
        graph_edges.append(
            {
                "source": str(edge["source"]),
                "target": str(edge["target"]),
            }
        )
    # Disable relation expansion for the baseline trace. This preserves the
    # exact lexical candidate path and avoids inventing graph-v2 authority.
    graph = {"nodes": graph_nodes, "edges": graph_edges}
    semantic = {
        "schema_version": "knowledge-engine-semantic-index/v1",
        "documents": [
            {
                "section_id": str(row["section_id"]),
                "terms": str(row.get("text", "")).split(),
            }
            for row in semantic_rows
        ],
    }
    provenance = {"records": provenance_rows}
    manifest = {
        "release_id": RELEASE,
        "source_count": 180,
        "candidate_only": True,
        "production_pointer_authorized": False,
    }
    return ProductionAnswerBundle(
        manifest=manifest,
        graph=graph,
        graph_v2={},
        lexical_index={"documents": lexical_rows},
        provenance=provenance,
        manifest_sha256="candidate-only",
        artifact_sha256={"lexical_index": LEX_SHA, "semantic_inputs": SEM_SHA},
        artifact_keys={"lexical_index": f"candidate/{RELEASE}/lexical-documents.jsonl"},
        loaded_at="2026-09-05T00:00:00Z",
        semantic_inputs=semantic,
        document_source_index=json.loads((SOURCE_ROOT / "candidate-release" / "source-index.json").read_text()),
    )


def source_slug(source_id: str) -> str:
    return source_id.removeprefix("daniel_blog_en__")


def candidate_source(item: dict) -> str:
    document = item.get("document") if isinstance(item.get("document"), dict) else item
    return str(document.get("source_id", ""))


def candidate_text(item: dict) -> str:
    document = item.get("document") if isinstance(item.get("document"), dict) else item
    return " ".join(str(document.get(key, "")) for key in ("title", "section_title", "body", "excerpt"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle()
    doc_by_section = {str(item["section_id"]): item for item in bundle.lexical_index["documents"]}
    repaired = "--repaired" in sys.argv
    if repaired:
        from knowledge_engine.m26_pa7_arbitrary_query_runtime import _augment_source_coverage_candidates
    cohort_path = Path(__file__).parent / "R1_COHORT_TO_TRACE.csv"
    cases = list(csv.DictReader(cohort_path.open()))
    traces = []
    for case in cases:
        question = case["question"]
        expected_slug = case["source_slug"]
        started = time.perf_counter()
        lexical = retrieve_wiki_first(
            query=question,
            allowed_audiences={"public", "internal"},
            lexical_index=bundle.lexical_index,
            graph=bundle.graph,
            relation_graph=None,
            relation_aware_expansion=False,
            provenance=bundle.provenance,
            semantic_index=bundle.semantic_inputs,
            limit=8,
        )
        lexical_results = lexical.get("results", [])
        if repaired:
            lexical = _augment_source_coverage_candidates(
                lexical_result=lexical,
                lexical_index=bundle.lexical_index,
                question=question,
            )
            lexical_results = lexical.get("results", [])
        candidate_slugs = [
            source_slug(str(doc_by_section.get(str(item.get("section_id")), {}).get("source_id", "")))
            for item in lexical_results
        ]
        candidate_hit = expected_slug in candidate_slugs
        selected = _select_evidence(
            bundle=bundle,
            lexical_result=lexical,
            dense_result={"candidates": []},
            trace_id=f"r1-baseline-{case['case_id']}",
            question=question,
            intent_class="direct_grounded_knowledge",
            allow_graph_expansion=False,
        )
        selected_slugs = [source_slug(str(item.get("source_id", ""))) for item in selected]
        selected_hit = expected_slug in selected_slugs
        expected_terms = sorted(_coverage_terms(question))
        candidate_text_hit = any(
            expected_slug
            == source_slug(str(doc_by_section.get(str(item.get("section_id")), {}).get("source_id", "")))
            and set(expected_terms)
            & set(candidate_text(doc_by_section.get(str(item.get("section_id")), {})).lower().split())
            for item in lexical_results
        )
        selected_text_hit = any(
            expected_slug == source_slug(str(item.get("source_id", "")))
            and set(expected_terms) & set(str(item.get("passage_text", "")).lower().split())
            for item in selected
        )
        if candidate_hit and not selected_hit:
            first_bad = "SELECTION"
            drop_reason = "answer-bearing candidate ranked/dropped before selected evidence"
        elif not candidate_hit:
            first_bad = "RETRIEVAL"
            drop_reason = "expected source absent from lexical candidate list"
        elif selected_hit and not selected_text_hit:
            first_bad = "EVIDENCE"
            drop_reason = "selected source lacks expected facet text"
        else:
            first_bad = "NONE"
            drop_reason = ""
        traces.append(
            {
                "case_id": case["case_id"],
                "question": question,
                "expected_source_slug": expected_slug,
                "expected_source_path": case["expected_article_path"],
                "release_id": RELEASE,
                "source_count": 180,
                "lexical_rows": 4424,
                "semantic_rows": 4424,
                "candidate_count": len(lexical_results),
                "candidate_generation": lexical_results,
                "candidate_expected_source_hit": candidate_hit,
                "candidate_expected_facet_hit": candidate_text_hit,
                "selected_count": len(selected),
                "selected_evidence": selected,
                "selected_expected_source_hit": selected_hit,
                "selected_expected_facet_hit": selected_text_hit,
                "first_bad_stage": first_bad,
                "drop_reason": drop_reason,
                "coverage_terms": expected_terms,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
    (OUT / "baseline_trace.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in traces) + "\n"
    )
    (OUT / "baseline_summary.csv").write_text(
        "case_id,expected_source_slug,candidate_count,candidate_hit,selected_count,selected_hit,first_bad_stage,elapsed_ms\n"
        + "\n".join(
            f"{x['case_id']},{x['expected_source_slug']},{x['candidate_count']},{int(x['candidate_expected_source_hit'])},{x['selected_count']},{int(x['selected_expected_source_hit'])},{x['first_bad_stage']},{x['elapsed_ms']}"
            for x in traces
        )
        + "\n"
    )
    print(json.dumps({"cases": len(traces), "first_bad": {s: sum(x["first_bad_stage"] == s for x in traces) for s in sorted({x["first_bad_stage"] for x in traces})}, "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
