from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BANK_DIR = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "m26_r2o_repair1_proposition_grounded_bank"
)

BANK_SCHEMA_VERSION = "m26-r2o-proposition-grounded-bank/v1"
AUDIT_SCHEMA_VERSION = "m26-r2o-proposition-grounded-audit/v1"
LIVE_MATRIX_SCHEMA_VERSION = "m26-r2o-frozen-live-matrix/v2"
HOSTILE_SEMANTIC_REVIEW_REQUIRED = "HOSTILE_SEMANTIC_REVIEW_REQUIRED"

CONTROL_BEHAVIORS = {"partial", "abstain", "clarify-compatible"}
PLACEHOLDER_PHRASES = {
    "stay within the proposition supported by the exact snippet",
    "generic placeholder",
}


def load_bank(bank_dir: Path = BANK_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in (
        "broad_bank.primary.jsonl",
        "broad_bank.holdout.jsonl",
        "broad_bank.sentinels.jsonl",
    ):
        rows.extend(
            json.loads(line)
            for line in (bank_dir / name).read_text().splitlines()
            if line
        )
    return rows


def canonical_bank_sha(bank_dir: Path = BANK_DIR) -> str:
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


def _hash_sort(seed: str, case_id: str) -> str:
    return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()


def _support_ids(case: Mapping[str, Any]) -> set[str]:
    return {str(item["support_id"]) for item in case.get("gold_support", [])}


def validate_case_structure(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "case_id",
        "family",
        "pool",
        "risk_tags",
        "question",
        "expected_behavior",
        "expected_behavior_set",
        "expected_terminal_set",
        "minimum_material_claims",
        "maximum_unsupported_claims",
        "required_propositions",
        "forbidden_inferences",
        "gold_support",
        "unanswered_dimensions_expected",
        "distinct_source_minimum",
        "graph_edge_required",
        "provenance_required",
        "temporal_versions_required",
        "paraphrase_group",
        "negative_control_of",
        "derivation_notes",
    }
    missing = required - set(case)
    if missing:
        errors.append(f"missing_keys={sorted(missing)}")
    behaviors = set(case.get("expected_behavior_set", []))
    if str(case.get("expected_behavior")) not in behaviors:
        errors.append("expected_behavior_set_missing_expected_behavior")
    if not case.get("required_propositions"):
        errors.append("required_propositions_empty")
    if any(
        phrase in json.dumps(case.get("required_propositions", []), sort_keys=True).lower()
        for phrase in PLACEHOLDER_PHRASES
    ):
        errors.append("generic_placeholder_proposition")
    support_ids = _support_ids(case)
    if not support_ids:
        errors.append("gold_support_empty")
    if len(support_ids) != len(case.get("gold_support", [])):
        errors.append("duplicate_support_ids")
    for support in case.get("gold_support", []):
        if not str(support.get("support_id", "")).strip():
            errors.append("empty_support_id")
        if not str(support.get("exact_support_snippet", "")).strip():
            errors.append("empty_support_snippet")
    for prop in case.get("required_propositions", []):
        if not set(prop.get("support_refs", [])) <= support_ids:
            errors.append(f"bad_support_refs:{case['case_id']}")
        if not str(prop.get("proposition_text", "")).strip():
            errors.append("empty_proposition_text")
        if not str(prop.get("entailment_note", "")).strip():
            errors.append("empty_entailment_note")
        if not str(prop.get("relation_type", "")).strip():
            errors.append("empty_relation_type")
    for item in case.get("forbidden_inferences", []):
        if not {
            "inference_id",
            "forbidden_text_or_relation",
            "reason",
        } <= set(item):
            errors.append("bad_forbidden_inference_shape")
    if case.get("graph_edge_required") and not any(
        str(item.get("support_role")) == "graph_edge" for item in case.get("gold_support", [])
    ):
        errors.append("missing_graph_edge_certificate")
    if case.get("provenance_required") and not any(
        str(item.get("support_role")) == "provenance_record"
        for item in case.get("gold_support", [])
    ):
        errors.append("missing_provenance_certificate")
    temporal_required = int(case.get("temporal_versions_required", 0))
    if temporal_required > 0 and len(case.get("gold_support", [])) < temporal_required:
        errors.append("missing_temporal_certificate")
    return errors


def validate_bank(bank_dir: Path = BANK_DIR) -> list[str]:
    rows = load_bank(bank_dir)
    errors: list[str] = []
    for row in rows:
        errors.extend(validate_case_structure(row))
    prim = [row for row in rows if row["pool"] == "primary"]
    hold = [row for row in rows if row["pool"] == "holdout"]
    prim_pairs = {
        (s["source_identity"], s["section_id"])
        for row in prim
        for s in row.get("gold_support", [])
    }
    hold_pairs = {
        (s["source_identity"], s["section_id"])
        for row in hold
        for s in row.get("gold_support", [])
    }
    if prim_pairs & hold_pairs:
        errors.append("primary_holdout_source_pair_overlap")
    return errors


def select_primary_live_matrix(
    *,
    bank_records: Sequence[Mapping[str, Any]],
    runtime_candidate_sha: str,
    bank_sha: str,
    broad_primary_count: int = 48,
) -> list[dict[str, Any]]:
    seed = hashlib.sha256(f"{runtime_candidate_sha}:{bank_sha}".encode()).hexdigest()
    sentinels = sorted(
        (record for record in bank_records if record["pool"] == "sentinel"),
        key=lambda record: str(record["case_id"]),
    )
    primary = [record for record in bank_records if record["pool"] == "primary"]
    selected: dict[str, Mapping[str, Any]] = {}

    def sort_key(record: Mapping[str, Any]) -> tuple[str, str]:
        case_id = str(record["case_id"])
        return _hash_sort(seed, case_id), case_id

    families = sorted({str(record["family"]) for record in primary})
    for family in families:
        candidates = [record for record in primary if record["family"] == family]
        if candidates:
            chosen = sorted(candidates, key=sort_key)[0]
            selected[str(chosen["case_id"])] = chosen

    control_candidates = [
        record
        for record in sorted(primary, key=sort_key)
        if record["expected_behavior"] in CONTROL_BEHAVIORS
    ]
    for record in control_candidates:
        if (
            sum(1 for item in selected.values() if item["expected_behavior"] in CONTROL_BEHAVIORS)
            >= 18
        ):
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
                "runtime_candidate_sha": runtime_candidate_sha,
                "bank_sha256": bank_sha,
                "selection_seed": seed,
            }
        )
    return matrix


def select_holdout_live_matrix(
    *,
    bank_records: Sequence[Mapping[str, Any]],
    runtime_candidate_sha: str,
    bank_sha: str,
    limit: int = 24,
) -> list[dict[str, Any]]:
    seed = hashlib.sha256(f"{runtime_candidate_sha}:{bank_sha}".encode()).hexdigest()
    holdouts = [record for record in bank_records if record["pool"] == "holdout"]
    selected: list[Mapping[str, Any]] = []

    for record in sorted(holdouts, key=lambda row: _hash_sort(seed, str(row["case_id"]))):
        if record["expected_behavior"] in CONTROL_BEHAVIORS and sum(
            1 for item in selected if item["expected_behavior"] in CONTROL_BEHAVIORS
        ) < 8:
            selected.append(record)
    for record in sorted(holdouts, key=lambda row: _hash_sort(seed, str(row["case_id"]))):
        if len(selected) >= limit:
            break
        if record not in selected:
            selected.append(record)
    selected = sorted(selected[:limit], key=lambda row: str(row["case_id"]))
    matrix: list[dict[str, Any]] = []
    for index, record in enumerate(selected, start=1):
        matrix.append(
            {
                "trial_id": f"HOLDOUT-{index:03d}",
                "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
                "case_id": str(record["case_id"]),
                "family": str(record["family"]),
                "pool": str(record["pool"]),
                "question": str(record["question"]),
                "expected_behavior": str(record["expected_behavior"]),
                "runtime_candidate_sha": runtime_candidate_sha,
                "bank_sha256": bank_sha,
                "selection_seed": seed,
            }
        )
    return matrix


def live_matrix_summary(matrix: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pools = Counter(str(record["pool"]) for record in matrix)
    controls = sum(1 for record in matrix if record["expected_behavior"] in CONTROL_BEHAVIORS)
    return {
        "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
        "total": len(matrix),
        "sentinels": pools["sentinel"],
        "broad_primary": pools["primary"],
        "control_count": controls,
        "families": sorted({str(record["family"]) for record in matrix}),
    }


def audit_captured_result(case: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    terminal = str(
        result.get("terminal_status")
        or result.get("status")
        or result.get("terminal")
        or ""
    )
    answer_text = str(result.get("answer_text") or result.get("answer") or "")
    claims = list(result.get("claims") or result.get("material_claims") or [])
    citations = list(result.get("citations") or [])
    expected_terminals = {str(item) for item in case.get("expected_terminal_set", [])}
    support_ids = _support_ids(case)
    cited_ids = {
        str(item.get("source_identity", ""))
        + "::"
        + str(item.get("support_id", item.get("id", "")))
        for item in [*citations, *claims]
        if isinstance(item, Mapping)
    }
    required_refs = {
        ref
        for prop in case.get("required_propositions", [])
        for ref in prop.get("support_refs", [])
    }
    support_check = required_refs <= support_ids
    snippets = [
        support["exact_support_snippet"]
        for support in case.get("gold_support", [])
        if support["exact_support_snippet"] in answer_text
        or any(
            support["exact_support_snippet"] in json.dumps(item, sort_keys=True)
            for item in [*claims, *citations]
        )
    ]
    deterministic_checks = {
        "terminal_match": terminal in expected_terminals,
        "support_refs_resolve": support_check,
        "gold_support_observed": bool(snippets) or case.get("expected_behavior") != "answer",
        "unsupported_claim_count_ok": int(result.get("unsupported_accepted_claims") or 0)
        <= int(case["maximum_unsupported_claims"]),
        "distinct_source_minimum": len(
            {
                str(item.get("source_identity", ""))
                for item in case.get("gold_support", [])
                if str(item.get("source_identity", ""))
            }
        ) >= int(case["distinct_source_minimum"]),
        "graph_required": (not case.get("graph_edge_required")) or any(
            str(item.get("support_role")) == "graph_edge" for item in case.get("gold_support", [])
        ),
        "provenance_required": (not case.get("provenance_required")) or any(
            str(item.get("support_role")) == "provenance_record"
            for item in case.get("gold_support", [])
        ),
        "partial_unanswered_dimensions": (
            not case.get("unanswered_dimensions_expected")
            or set(str(x) for x in case.get("unanswered_dimensions_expected", []))
            <= set(str(x) for x in result.get("unanswered_dimensions", []))
        ),
        "forbidden_inference_documented": bool(case.get("forbidden_inferences")),
        "support_ids_observed": case.get("expected_behavior") == "abstain" or bool(cited_ids),
    }
    passed = all(deterministic_checks.values())
    host_review = (
        HOSTILE_SEMANTIC_REVIEW_REQUIRED
        if case.get("expected_behavior") in {"answer", "partial", "clarify-compatible"}
        else "DETERMINISTICALLY_AUDITED"
    )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "case_id": str(case["case_id"]),
        "terminal": terminal,
        "answer_text": answer_text,
        "claim_count": len(claims),
        "citation_count": len(citations),
        "expected_behavior_match": terminal in expected_terminals,
        "required_proposition_coverage": host_review,
        "forbidden_inference_violations": [],
        "unsupported_accepted_claim_count": int(result.get("unsupported_accepted_claims") or 0),
        "distinct_source_minimum": deterministic_checks["distinct_source_minimum"],
        "graph_provenance_temporal_structural_checks": {
            "graph_required": deterministic_checks["graph_required"],
            "provenance_required": deterministic_checks["provenance_required"],
            "temporal_versions_required": int(case.get("temporal_versions_required", 0)),
        },
        "partial_unanswered_dimension_check": deterministic_checks["partial_unanswered_dimensions"],
        "claim_local_exact_support_snippets": snippets,
        "deterministic_checks": deterministic_checks,
        "verdict": "PASS" if passed else "FAIL",
    }
