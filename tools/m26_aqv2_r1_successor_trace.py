from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]+")

CASES = (
    ("S02", "F002", "What does Harness Theory say an agent harness is responsible for?", "harness-theory-part-1", "A working definition of a harness"),
    ("S03", "F003", "What is the difference between a workflow and an agent?", "ai-agentic-workflow-series-6", "workflow shell, agent islands"),
    ("S07", "F021", "What evidence should a user inspect in Codex after a task is marked done?", "codex-agent-harness-command-center-part-3", "Tools need boundaries, and engineering work needs evidence"),
    ("S11", "F058", "What does Daniel mean by production RAG, and how does it differ from a toy RAG demo?", "from-rag-to-production-rag-part-3", "where production and demo part ways"),
    ("S12", "F082", "When does a LoRA adapter not need to be merged into its base model?", "local-llm-fine-tuning-08", "Why adapters do not have to be merged"),
    ("S14", "F085", "What does a citation check catch that a faithfulness check can miss?", "from-rag-to-production-rag-part-3", "where production and demo part ways"),
    ("S20", "F128", "What should a validator do in an LLM application?", "pm-llm-application-engineering-02", "four gates"),
    ("S21", "F129", "How do tasks let work outlive an HTTP request?", "stateless-mcp-architecture-part-2", "Tasks: let the work outlive the HTTP request"),
    ("S22", "F144", "What makes an MCP contract healthy rather than merely full of fields?", "mcp-engineering-deep-dive-03", "A good contract does not mean more fields"),
    ("S26", "F158", "Why are tasks different from request-scoped state?", "stateless-mcp-architecture-part-2", "Separate the responsibilities a session used to collect"),
    ("S27", "F162", "Why does a retrieval miss need to be separated from a generation failure?", "rag-engineering-in-practice-06", "did retrieval fail, or did generation fail"),
)


def tokens(value: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(value)]


def text(document: dict[str, Any], key: str, fallback: str = "") -> str:
    value = document.get(key)
    if value is None:
        return fallback
    return str(value)


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    concept_id = text(document, "concept_id") or text(document, "source_id") or text(document, "id")
    title = text(document, "title", concept_id)
    description = text(document, "description")
    section_id = text(document, "section_id") or f"{concept_id}#overview"
    section_title = text(document, "section_title", title)
    body = text(document, "body") or text(document, "excerpt") or description
    excerpt = text(document, "excerpt") or body[:320] or description
    terms = document.get("terms")
    if not isinstance(terms, list) or not all(isinstance(item, str) for item in terms):
        terms = tokens(" ".join((title, section_title, description, body)))
    return {
        **document,
        "concept_id": concept_id,
        "title": title,
        "description": description,
        "section_id": section_id,
        "section_title": section_title,
        "body": body,
        "excerpt": excerpt,
        "terms": terms,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise TypeError(f"line {lineno} is not an object")
            docs.append(normalize(raw))
    return docs


def baseline_score(document: dict[str, Any], query_terms: list[str]) -> float:
    def term_score(value: str, weight: int) -> int:
        counts = Counter(tokens(value))
        return weight * sum(counts[term] for term in query_terms)

    explicit = (
        term_score(document["title"], 4)
        + term_score(document["section_title"], 3)
        + term_score(document["description"], 2)
        + term_score(document["body"], 1)
    )
    if explicit:
        return float(explicit)
    term_counts = Counter(item.lower() for item in document["terms"])
    return float(sum(term_counts[term] for term in query_terms))


def idf_weights(documents: list[dict[str, Any]], query_terms: list[str]) -> dict[str, float]:
    unique_terms = set(query_terms)
    dfs = {term: 0 for term in unique_terms}
    for document in documents:
        present = set(tokens(" ".join((document["title"], document["section_title"], document["description"], document["body"]))))
        for term in unique_terms & present:
            dfs[term] += 1
    n = max(1, len(documents))
    return {term: math.log((n + 1.0) / (dfs[term] + 1.0)) + 1.0 for term in unique_terms}


def idf_score(document: dict[str, Any], query_terms: list[str], weights: dict[str, float]) -> float:
    fields = ((document["title"], 4.0), (document["section_title"], 3.0), (document["description"], 2.0), (document["body"], 1.0))
    score = 0.0
    matched: set[str] = set()
    for value, field_weight in fields:
        counts = Counter(tokens(value))
        for term in query_terms:
            if counts[term]:
                matched.add(term)
                # log-TF prevents a long document from winning merely by repeating common words.
                score += field_weight * weights[term] * (1.0 + math.log(counts[term]))
    if not score:
        counts = Counter(item.lower() for item in document["terms"])
        for term in query_terms:
            if counts[term]:
                matched.add(term)
                score += weights[term] * (1.0 + math.log(counts[term]))
    # Reward breadth of distinct query coverage without changing candidate limit.
    if matched:
        score *= 1.0 + 0.08 * max(0, len(matched) - 1)
    return score


def ordered_documents(documents: list[dict[str, Any]], question: str, scorer: str) -> list[tuple[float, dict[str, Any]]]:
    q_terms = tokens(question)
    weights = idf_weights(documents, q_terms) if scorer == "idf" else {}
    scored = []
    for document in documents:
        value = baseline_score(document, q_terms) if scorer == "baseline" else idf_score(document, q_terms, weights)
        if value > 0:
            scored.append((value, document))
    return sorted(scored, key=lambda item: (-item[0], item[1]["concept_id"], item[1]["section_id"]))


def concept_topk(ordered: list[tuple[float, dict[str, Any]]], limit: int = 8) -> list[tuple[float, dict[str, Any]]]:
    results: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in ordered:
        concept = item[1]["concept_id"]
        if concept in seen:
            continue
        seen.add(concept)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def contains_slug(document: dict[str, Any], slug: str) -> bool:
    needle = slug.casefold()
    return needle in json.dumps(document, ensure_ascii=False, sort_keys=True).casefold()


def contains_section(document: dict[str, Any], section_hint: str) -> bool:
    needle = " ".join(section_hint.casefold().split())
    haystack = " ".join((document["section_title"], document["body"], document["excerpt"])).casefold()
    return needle in " ".join(haystack.split())


def rank_of(ordered: list[tuple[float, dict[str, Any]]], predicate) -> int | None:
    for index, (_, document) in enumerate(ordered, 1):
        if predicate(document):
            return index
    return None


def concept_rank_of(ordered: list[tuple[float, dict[str, Any]]], slug: str) -> int | None:
    seen: set[str] = set()
    rank = 0
    for _, document in ordered:
        concept = document["concept_id"]
        if concept in seen:
            continue
        seen.add(concept)
        rank += 1
        if contains_slug(document, slug):
            return rank
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lexical-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load_started = time.perf_counter()
    documents = load_jsonl(args.lexical_jsonl)
    load_ms = (time.perf_counter() - load_started) * 1000
    result: dict[str, Any] = {
        "schema_version": "m26-aqv2-r1-first-bad-stage-trace/v1",
        "document_count": len(documents),
        "load_ms": round(load_ms, 3),
        "first_document_keys": sorted(documents[0].keys()) if documents else [],
        "cases": [],
    }
    for slice_id, failure_id, question, slug, section_hint in CASES:
        row: dict[str, Any] = {"slice_id": slice_id, "failure_id": failure_id, "question": question, "expected_slug": slug, "section_hint": section_hint}
        for scorer in ("baseline", "idf"):
            started = time.perf_counter()
            ordered = ordered_documents(documents, question, scorer)
            elapsed_ms = (time.perf_counter() - started) * 1000
            top8 = concept_topk(ordered, 8)
            top4 = top8[:4]
            row[scorer] = {
                "elapsed_ms": round(elapsed_ms, 3),
                "scored_document_count": len(ordered),
                "expected_section_document_rank": rank_of(ordered, lambda d, s=slug, h=section_hint: contains_slug(d, s) and contains_section(d, h)),
                "expected_source_document_rank": rank_of(ordered, lambda d, s=slug: contains_slug(d, s)),
                "expected_source_concept_rank": concept_rank_of(ordered, slug),
                "candidate_top8_hit": any(contains_slug(d, slug) for _, d in top8),
                "selected_top4_hit": any(contains_slug(d, slug) for _, d in top4),
                "top8": [
                    {"rank": i + 1, "score": round(score, 6), "concept_id": d["concept_id"], "section_id": d["section_id"], "section_title": d["section_title"]}
                    for i, (score, d) in enumerate(top8)
                ],
            }
        result["cases"].append(row)

    for scorer in ("baseline", "idf"):
        timings = [float(row[scorer]["elapsed_ms"]) for row in result["cases"]]
        result[f"{scorer}_latency_ms"] = {
            "median": round(statistics.median(timings), 3),
            "max": round(max(timings), 3),
        }
        result[f"{scorer}_candidate_top8_hits"] = sum(bool(row[scorer]["candidate_top8_hit"]) for row in result["cases"])
        result[f"{scorer}_selected_top4_hits"] = sum(bool(row[scorer]["selected_top4_hit"]) for row in result["cases"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
