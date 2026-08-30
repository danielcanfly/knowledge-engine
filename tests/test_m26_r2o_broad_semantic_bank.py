from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "evals" / "m26_broad_semantic"
LEXICAL = ROOT / "pilot" / "m24" / "canonical-release" / "artifacts" / "lexical-index.json"
GRAPH = ROOT / "pilot" / "m24" / "canonical-release" / "artifacts" / "graph-v2.json"
PROVENANCE = ROOT / "pilot" / "m24" / "canonical-release" / "artifacts" / "provenance.json"

REQUIRED_FAMILIES = {
    "simple_definition",
    "contextual_definition",
    "role_responsibility",
    "impact_effect",
    "causal_why",
    "how_process",
    "comparison",
    "relationship",
    "examples",
    "trade_offs",
    "architecture_components",
    "capability_skill_requirement",
    "enumerative_list",
    "multi_part",
    "broad_synthesis",
    "narrow_factual",
    "ambiguous_clarification",
    "insufficient_evidence",
    "partially_sufficient_evidence",
    "conflicting_evidence",
    "lexical_similarity_low_relevance",
    "short_query",
    "long_compositional_query",
    "paraphrase_equivalence",
    "adversarial_category_mutation",
    "causal_strengthening_negative",
    "universalization_negative",
    "modality_necessity_strengthening_negative",
    "temporal_version",
    "provenance_source_trace",
    "graph_relationship",
    "mixed_domain_distractor",
}

NEGATIVE_BEHAVIORS = {"abstain", "partial", "clarify-compatible"}


def _records() -> list[dict]:
    records: list[dict] = []
    for path in sorted(BANK.glob("broad_bank.*.jsonl")):
        records.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    return records


def _accepted_text_blobs() -> list[str]:
    lexical = json.loads(LEXICAL.read_text())
    graph = GRAPH.read_text()
    provenance = json.loads(PROVENANCE.read_text())
    blobs = [str(item["body"]) for item in lexical["documents"]]
    blobs.append(graph)
    for record in provenance["records"]:
        for claim in record.get("claims", []):
            blobs.append(str(claim.get("text", "")))
    return blobs


def test_r2o_broad_bank_schema_counts_and_families() -> None:
    schema = json.loads((BANK / "broad_case_schema.json").read_text())
    validator = Draft202012Validator(schema)
    records = _records()
    pools = Counter(str(record["pool"]) for record in records)
    families = Counter(str(record["family"]) for record in records)
    ids = [str(record["case_id"]) for record in records]

    assert not [error.message for record in records for error in validator.iter_errors(record)]
    assert len(records) >= 80
    assert pools["primary"] >= 56
    assert pools["holdout"] >= 24
    assert pools["sentinel"] == 7
    assert len(ids) == len(set(ids))
    assert REQUIRED_FAMILIES <= set(families)
    assert all(families[family] >= 2 for family in REQUIRED_FAMILIES)


def test_r2o_broad_bank_gold_support_and_control_integrity() -> None:
    records = _records()
    accepted_blobs = _accepted_text_blobs()

    for record in records:
        support = record["gold_support"]
        assert support
        for item in support:
            snippet = str(item["exact_support_snippet"])
            assert any(snippet in blob for blob in accepted_blobs)
        if record["expected_behavior"] == "partial":
            assert record["unanswered_dimensions_expected"]
            assert record["forbidden_inferences"]
        if record["expected_behavior"] in {"abstain", "clarify-compatible"}:
            assert record["forbidden_inferences"] or record["unanswered_dimensions_expected"]
        if "negative_control" in record["risk_tags"]:
            assert record["negative_control_of"]
            assert record["forbidden_inferences"]
        if record["graph_edge_required"]:
            assert any(item["support_role"] == "graph_edge" for item in support)
        if record["provenance_required"]:
            assert any(item["support_role"] == "provenance_record" for item in support)


def test_r2o_broad_bank_paraphrase_and_holdout_split() -> None:
    records = _records()
    grouped: dict[str, list[dict]] = defaultdict(list)
    primary_pairs = {
        (record["family"], record["gold_support"][0]["section_id"])
        for record in records
        if record["pool"] == "primary"
    }
    holdout_pairs = {
        (record["family"], record["gold_support"][0]["section_id"])
        for record in records
        if record["pool"] == "holdout"
    }
    for record in records:
        group = str(record["paraphrase_group"])
        if group:
            grouped[group].append(record)

    assert primary_pairs.isdisjoint(holdout_pairs)
    assert sum(1 for group in grouped.values() if len(group) >= 3) >= 10
    control_count = sum(
        1 for record in records if record["expected_behavior"] in NEGATIVE_BEHAVIORS
    )
    assert control_count >= len(records) // 4
