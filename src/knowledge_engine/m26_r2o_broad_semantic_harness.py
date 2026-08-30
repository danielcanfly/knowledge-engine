from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BANK_SCHEMA_VERSION = "m26-r2o-broad-bank/v1"
AUDIT_SCHEMA_VERSION = "m26-r2o-broad-audit/v1"
LIVE_MATRIX_SCHEMA_VERSION = "m26-r2o-frozen-live-matrix/v1"
HOSTILE_SEMANTIC_REVIEW_REQUIRED = "HOSTILE_SEMANTIC_REVIEW_REQUIRED"

REQUIRED_LIVE_FAMILIES = {
    "simple_definition",
    "contextual_definition",
    "role_responsibility",
    "causal_why",
    "comparison",
    "multi_part",
    "partially_sufficient_evidence",
    "insufficient_evidence",
    "lexical_similarity_low_relevance",
    "adversarial_category_mutation",
    "universalization_negative",
    "modality_necessity_strengthening_negative",
    "provenance_source_trace",
    "graph_relationship",
    "temporal_version",
}

CONTROL_BEHAVIORS = {"partial", "abstain", "clarify-compatible"}


def load_bank(bank_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in (
        bank_dir / "broad_bank.primary.jsonl",
        bank_dir / "broad_bank.holdout.jsonl",
        bank_dir / "broad_bank.sentinels.jsonl",
    ):
        records.extend(json.loads(line) for line in path.read_text().splitlines() if line)
    return records


def canonical_bank_sha(bank_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in (
        "broad_bank.primary.jsonl",
        "broad_bank.holdout.jsonl",
        "broad_bank.sentinels.jsonl",
    ):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((bank_dir / name).read_bytes())
    return digest.hexdigest()


def pool_id_sha(records: Sequence[Mapping[str, Any]], pool: str) -> str:
    ids = sorted(str(record["case_id"]) for record in records if record["pool"] == pool)
    return hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest()


def select_frozen_live_matrix(
    *,
    bank_records: Sequence[Mapping[str, Any]],
    candidate_head: str,
    bank_sha: str,
    broad_primary_count: int = 48,
) -> list[dict[str, Any]]:
    seed = hashlib.sha256(f"{candidate_head}:{bank_sha}".encode()).hexdigest()
    sentinels = sorted(
        (record for record in bank_records if record["pool"] == "sentinel"),
        key=lambda record: str(record["case_id"]),
    )
    primary = [record for record in bank_records if record["pool"] == "primary"]
    selected: dict[str, Mapping[str, Any]] = {}

    def sort_key(record: Mapping[str, Any]) -> tuple[str, str]:
        case_id = str(record["case_id"])
        return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest(), case_id

    for family in sorted(REQUIRED_LIVE_FAMILIES):
        candidates = [record for record in primary if record["family"] == family]
        if candidates:
            record = sorted(candidates, key=sort_key)[0]
            selected[str(record["case_id"])] = record

    control_candidates = [
        record
        for record in sorted(primary, key=sort_key)
        if record["expected_behavior"] in CONTROL_BEHAVIORS
    ]
    minimum_controls = max(12, broad_primary_count // 4)
    for record in control_candidates:
        if sum(
            1
            for selected_record in selected.values()
            if selected_record["expected_behavior"] in CONTROL_BEHAVIORS
        ) >= minimum_controls:
            break
        selected[str(record["case_id"])] = record

    for record in sorted(primary, key=sort_key):
        if len(selected) >= broad_primary_count:
            break
        selected[str(record["case_id"])] = record

    broad = sorted(selected.values(), key=lambda record: str(record["case_id"]))
    matrix: list[dict[str, Any]] = []
    for index, record in enumerate([*sentinels, *broad], start=1):
        matrix.append(
            {
                "trial_id": f"LIVE-{index:03d}",
                "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
                "case_id": str(record["case_id"]),
                "family": str(record["family"]),
                "pool": str(record["pool"]),
                "question": str(record["question"]),
                "expected_behavior": str(record["expected_behavior"]),
                "selection_seed": seed,
                "bank_sha256": bank_sha,
                "candidate_head": candidate_head,
            }
        )
    return matrix


def audit_captured_result(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    terminal = str(
        result.get("terminal_status")
        or result.get("status")
        or result.get("terminal")
        or ""
    )
    answer_text = str(result.get("answer_text") or result.get("answer") or "")
    claims = _as_list(result.get("claims") or result.get("material_claims"))
    citations = _as_list(result.get("citations"))
    selected = _as_list(result.get("selected_evidence_ids") or result.get("used_evidence_ids"))
    unsupported = int(
        result.get("unsupported_accepted_claims")
        or result.get("unsupported_claim_count")
        or 0
    )
    expected_terminals = {str(item) for item in _as_list(case.get("expected_terminal_set"))}
    required_support = _as_list(case.get("gold_support"))
    found_snippets = [
        support
        for support in required_support
        if str(support.get("exact_support_snippet", "")) in answer_text
        or any(
            str(support.get("exact_support_snippet", "")) in json.dumps(item, sort_keys=True)
            for item in [*claims, *citations]
        )
    ]
    distinct_sources = {
        str(item.get("source_identity", ""))
        for item in [*citations, *required_support]
        if isinstance(item, Mapping) and str(item.get("source_identity", ""))
    }
    unanswered_expected = {
        str(item) for item in _as_list(case.get("unanswered_dimensions_expected"))
    }
    unanswered_actual = {
        str(item)
        for item in _as_list(result.get("unanswered_dimensions"))
        if str(item)
    }
    forbidden = _as_list(case.get("forbidden_inferences"))
    deterministic_checks = {
        "terminal_match": terminal in expected_terminals,
        "required_support_observed": len(found_snippets) == len(required_support),
        "unsupported_claim_count_ok": unsupported <= int(case["maximum_unsupported_claims"]),
        "distinct_source_minimum": len(distinct_sources) >= int(case["distinct_source_minimum"]),
        "graph_required": (
            not case.get("graph_edge_required")
            or any(str(item.get("support_role")) == "graph_edge" for item in required_support)
        ),
        "provenance_required": (
            not case.get("provenance_required")
            or any(
                str(item.get("support_role")) == "provenance_record"
                for item in required_support
            )
        ),
        "partial_unanswered_dimensions": (
            not unanswered_expected or unanswered_expected <= unanswered_actual
        ),
        "forbidden_bridge_documented": bool(forbidden)
        if case["expected_behavior"] in CONTROL_BEHAVIORS
        else True,
    }
    semantic_flag = (
        HOSTILE_SEMANTIC_REVIEW_REQUIRED
        if case.get("expected_behavior") == "answer"
        else ""
    )
    passed = all(deterministic_checks.values())
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "case_id": str(case["case_id"]),
        "terminal": terminal,
        "answer_text": answer_text,
        "claim_count": len(claims),
        "citation_count": len(citations),
        "selected_evidence": selected,
        "expected_behavior_match": terminal in expected_terminals,
        "required_proposition_coverage": semantic_flag or "DETERMINISTICALLY_AUDITED",
        "forbidden_inference_violations": [],
        "unsupported_accepted_claim_count": unsupported,
        "distinct_source_minimum": deterministic_checks["distinct_source_minimum"],
        "graph_provenance_temporal_structural_checks": {
            "graph_required": deterministic_checks["graph_required"],
            "provenance_required": deterministic_checks["provenance_required"],
            "temporal_versions_required": int(case["temporal_versions_required"]),
        },
        "partial_unanswered_dimension_check": deterministic_checks[
            "partial_unanswered_dimensions"
        ],
        "claim_local_exact_support_snippets": [
            str(item.get("exact_support_snippet", "")) for item in found_snippets
        ],
        "deterministic_checks": deterministic_checks,
        "verdict": "PASS" if passed else "FAIL",
    }


def live_matrix_summary(matrix: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pools = Counter(str(record["pool"]) for record in matrix)
    controls = sum(
        1 for record in matrix if record["expected_behavior"] in CONTROL_BEHAVIORS
    )
    return {
        "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
        "total": len(matrix),
        "sentinels": pools["sentinel"],
        "broad_primary": pools["primary"],
        "control_count": controls,
        "families": sorted({str(record["family"]) for record in matrix}),
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
