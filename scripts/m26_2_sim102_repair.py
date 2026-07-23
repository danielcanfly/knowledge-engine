from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "knowledge_engine" / "m26_retrieval_envelope.py"

OLD_GRAPH = '''        for seed, neighbor in ((source, target), (target, source)):
            if seed in selected and neighbor in node_audiences:
                if AUDIENCE_RANK[node_audiences[str(neighbor)]] > maximum_audience_rank:
                    filtered.add(f"graph-node:{neighbor}")
'''
NEW_GRAPH = '''        for seed, neighbor in ((source, target), (target, source)):
            if (
                seed in selected
                and neighbor in node_audiences
                and AUDIENCE_RANK[node_audiences[str(neighbor)]] > maximum_audience_rank
            ):
                filtered.add(f"graph-node:{neighbor}")
'''

OLD_CITATION = '''            audience = source.get("audience")
            if audience in AUDIENCE_RANK:
                if AUDIENCE_RANK[str(audience)] > maximum_audience_rank:
                    filtered.add(f"citation-source:{source.get('source_id', concept_id)}")
'''
NEW_CITATION = '''            audience = source.get("audience")
            if (
                audience in AUDIENCE_RANK
                and AUDIENCE_RANK[str(audience)] > maximum_audience_rank
            ):
                filtered.add(f"citation-source:{source.get('source_id', concept_id)}")
'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if source.count(OLD_GRAPH) != 1 or source.count(OLD_CITATION) != 1:
        raise AssertionError("expected SIM102 repair targets are not unique")
    source = source.replace(OLD_GRAPH, NEW_GRAPH, 1)
    source = source.replace(OLD_CITATION, NEW_CITATION, 1)
    TARGET.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
