from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "knowledge_engine" / "m26_retrieval_envelope.py"

INSERT_AFTER = '''def _source_catalog(corpus: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["source_id"]): dict(item) for item in corpus["source_documents"]}


'''

HELPER = '''def _query_specific_acl_count(
    corpus: Mapping[str, Any],
    plan: Mapping[str, Any],
    retrieved: Mapping[str, Any],
    *,
    maximum_audience_rank: int,
) -> int:
    """Count only restricted candidates reached by this query, without exposing their text."""
    filtered: set[str] = set()
    terms = set(plan["lexical"]["query_terms"])
    for document in corpus["lexical_index"].get("documents", []):
        if not isinstance(document, Mapping):
            continue
        audience = document.get("audience")
        if audience not in AUDIENCE_RANK:
            continue
        if AUDIENCE_RANK[str(audience)] <= maximum_audience_rank:
            continue
        searchable = " ".join(
            str(document.get(key, ""))
            for key in ("title", "section_title", "description", "body", "excerpt")
        )
        searchable_terms = set(query_terms(searchable)) | {
            str(item).casefold() for item in document.get("terms", [])
        }
        if terms & searchable_terms:
            filtered.add(f"section:{document.get('section_id', document.get('concept_id'))}")

    selected = {
        str(result["concept_id"])
        for result in retrieved.get("results", [])
        if isinstance(result, Mapping) and isinstance(result.get("concept_id"), str)
    }
    node_audiences = {
        str(node["concept_id"]): str(node["audience"])
        for node in corpus.get("graph", {}).get("nodes", [])
        if isinstance(node, Mapping)
        and isinstance(node.get("concept_id"), str)
        and node.get("audience") in AUDIENCE_RANK
    }
    for edge in corpus.get("graph", {}).get("edges", []):
        if not isinstance(edge, Mapping):
            continue
        source = edge.get("source", edge.get("from", edge.get("from_concept_id")))
        target = edge.get("target", edge.get("to", edge.get("to_concept_id")))
        for seed, neighbor in ((source, target), (target, source)):
            if seed in selected and neighbor in node_audiences:
                if AUDIENCE_RANK[node_audiences[str(neighbor)]] > maximum_audience_rank:
                    filtered.add(f"graph-node:{neighbor}")

    allowed_relations = set(plan["graph"]["relation_types"])
    for edge in corpus.get("graph_v2", {}).get("edges", []):
        if not isinstance(edge, Mapping) or edge.get("relation_type") not in allowed_relations:
            continue
        source = edge.get("source")
        target = edge.get("target")
        edge_audience = edge.get("audience")
        if source in selected and target in node_audiences:
            target_restricted = (
                AUDIENCE_RANK[node_audiences[str(target)]] > maximum_audience_rank
            )
            edge_restricted = (
                edge_audience in AUDIENCE_RANK
                and AUDIENCE_RANK[str(edge_audience)] > maximum_audience_rank
            )
            if target_restricted or edge_restricted:
                filtered.add(f"relation:{edge.get('edge_id', f'{source}:{target}')}")

    records = {
        str(record["subject"]["concept_id"]): record
        for record in corpus.get("provenance", {}).get("records", [])
        if isinstance(record, Mapping)
        and isinstance(record.get("subject"), Mapping)
        and isinstance(record["subject"].get("concept_id"), str)
    }
    for concept_id in selected:
        record = records.get(concept_id, {})
        for source in record.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            audience = source.get("audience")
            if audience in AUDIENCE_RANK:
                if AUDIENCE_RANK[str(audience)] > maximum_audience_rank:
                    filtered.add(f"citation-source:{source.get('source_id', concept_id)}")
    return len(filtered)


'''

OLD = '''    retrieval_acl = int(retrieved["retrieval"].get("acl_filtered_section_count", 0))
    citation_acl = int(retrieved["retrieval"].get("citation_source_acl_filtered_count", 0))
    existing_acl = sum(item["reason"] == "acl" for item in excluded)
    acl_filtered = max(retrieval_acl + citation_acl, existing_acl)
'''

NEW = '''    query_acl = _query_specific_acl_count(
        corpus,
        plan,
        retrieved,
        maximum_audience_rank=maximum_rank,
    )
    existing_acl = sum(item["reason"] == "acl" for item in excluded)
    acl_filtered = max(query_acl, existing_acl)
'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if "def _query_specific_acl_count(" not in source:
        if INSERT_AFTER not in source:
            raise AssertionError("source-catalog insertion point is absent")
        source = source.replace(INSERT_AFTER, INSERT_AFTER + HELPER, 1)
    if OLD not in source:
        raise AssertionError("global ACL aggregation block is absent")
    source = source.replace(OLD, NEW, 1)
    TARGET.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
