from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_r1_semantic_alignment import (
    FIELD_PRIORITY,
    SAMPLE_CAP,
    _identifier_tokens,
    canonical_manifest,
    compile_probe_plan,
)

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-1-query-diagnostics/v1"
ENTRY_ENGINE_SHA = "a4be8373a03ac127cd1c8c99af450a2f78230cc0"
RECEIPT_SHA256 = "43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe"
PAIRS = {
    "direct-fact": ("r1-probe-01", "r1-probe-05"),
    "terminology": ("r1-probe-02", "r1-probe-06"),
    "cross-section": ("r1-probe-03", "r1-probe-07"),
    "provenance": ("r1-probe-04", "r1-probe-08"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.1-{code} {message}")


def _tokens(payload: Mapping[str, Any]) -> list[str]:
    output: list[str] = []
    for field in FIELD_PRIORITY:
        for token in _identifier_tokens(payload.get(field)):
            if token not in output:
                output.append(token)
    return output[:8]


def reconstruct_query_identities(
    samples: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    probes = compile_probe_plan(canonical_manifest(), samples)
    ordered = sorted(samples, key=lambda item: item.get("point_id", item.get("id")))
    records: list[dict[str, Any]] = []
    for probe, sample in zip(probes, ordered, strict=True):
        payload = sample.get("payload")
        _require(isinstance(payload, Mapping), 101, "sample payload invalid")
        text = probe["query_text"]
        records.append(
            {
                "probe_id": probe["probe_id"],
                "query_class": probe["query_class"],
                "target_section_id": probe["target_section_id"],
                "normalised_identifier_tokens": _tokens(payload),
                "query_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "compiler_query_digest": probe["query_digest"],
                "raw_query_persisted": False,
            }
        )
    groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        groups[record["query_text_sha256"]].append(record["probe_id"])
    collisions = [
        {"query_text_sha256": digest, "probe_ids": sorted(ids), "size": len(ids)}
        for digest, ids in sorted(groups.items())
        if len(ids) > 1
    ]
    return records, collisions


def analyse_redacted_rankings(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _require(len(cases) == SAMPLE_CAP, 102, "eight cases required")
    by_probe: dict[str, list[str]] = {}
    hubs: Counter[str] = Counter()
    for case in cases:
        probe_id = case.get("probe_id")
        _require(isinstance(probe_id, str) and probe_id, 103, "probe id missing")
        _require(probe_id not in by_probe, 104, "duplicate probe id")
        ranked = case.get("top3_ranked_section_ids")
        valid = isinstance(ranked, list) and len(ranked) == 3
        _require(valid, 105, "redacted top-three ranking invalid")
        by_probe[probe_id] = list(ranked)
        hubs.update(ranked)
    pairs = [
        {
            "query_class": query_class,
            "probe_ids": list(probe_ids),
            "top3_equal": by_probe[probe_ids[0]] == by_probe[probe_ids[1]],
        }
        for query_class, probe_ids in PAIRS.items()
    ]
    return {
        "same_class_pairs": pairs,
        "all_same_class_top3_equal": all(item["top3_equal"] for item in pairs),
        "maximum_hub_frequency": max(hubs.values()),
        "hub_frequency": [
            {"section_id": section_id, "count": count}
            for section_id, count in hubs.most_common()
        ],
    }


def build_preliminary_report(
    samples: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records, collisions = reconstruct_query_identities(samples)
    ranking = analyse_redacted_rankings(cases)
    expected = {tuple(sorted(pair)) for pair in PAIRS.values()}
    observed = {tuple(item["probe_ids"]) for item in collisions if item["size"] == 2}
    compiler_unique = len({item["compiler_query_digest"] for item in records}) == 8
    text_unique = len({item["query_text_sha256"] for item in records}) == 8
    h1 = observed == expected and ranking["all_same_class_top3_equal"]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.1",
        "status": "phase_a_b_complete_vector_diagnostics_pending",
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_live_receipt_sha256": RECEIPT_SHA256,
        },
        "query_identity": {
            "records": records,
            "collision_groups": collisions,
            "all_expected_pairs_collide": observed == expected,
            "compiler_digests_unique": compiler_unique,
            "query_text_digests_unique": text_unique,
            "probe_bound_digest_masks_text_collision": compiler_unique and not text_unique,
        },
        "ranking_evidence": ranking,
        "hypotheses": {
            "H1_identifier_humanisation_query_collision": (
                "confirmed_by_query_and_top3_evidence" if h1 else "not_confirmed"
            ),
            "H2_prefix_or_normalisation_mismatch": "pending_vector_diagnostics",
            "H3_vector_payload_binding_error": "pending_vector_diagnostics",
            "H4_corpus_hubness": "supported_by_top3_pending_full_top10",
            "H5_multilingual_alignment_failure": "pending_vector_diagnostics",
            "H6_target_label_validity_error": "pending_source_review",
            "H7_top_k_request_defect": "pending_local_cosine_replay",
            "H8_batch_mapping_defect": "pending_full_receipt_validation",
        },
        "root_cause": {
            "primary": "identifier_humanisation_query_collision" if h1 else None,
            "final_seal": False,
            "repair_proposal_included": False,
        },
        "privacy": {
            "raw_queries_persisted": False,
            "raw_answers_persisted": False,
            "credentials_persisted": False,
            "service_urls_persisted": False,
        },
        "authority": {
            "production_retrieval": "lexical",
            "promotion_eligibility_granted": False,
            "qdrant_write": 0,
            "protected_mutations_dispatched": False,
        },
        "remaining_blockers": ["blocked_pending_retrieval_quality"],
        "exit": {
            "r3_1_complete": False,
            "parent_r3_complete": False,
            "issue_474_must_remain_open": True,
            "next_legal_action": "read_only_vector_and_payload_diagnostics",
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report
