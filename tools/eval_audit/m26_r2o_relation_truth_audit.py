from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BANK_DIR = REPO / "evals" / "m26_r2o_repair1_proposition_grounded_bank"
HIGH_RISK_FAMILIES = {
    "architecture_components",
    "impact_effect",
    "causal_why",
    "trade_offs",
    "capability_skill_requirement",
    "comparison",
    "relationship",
    "conflicting_evidence",
    "temporal_version",
    "provenance_source_trace",
    "graph_relationship",
}
EXPECTED_RELATIONS = {
    "architecture_components": {"component", "enumeration"},
    "impact_effect": {"effect", "causal"},
    "causal_why": {"causal", "effect", "purpose"},
    "trade_offs": {"tradeoff"},
    "capability_skill_requirement": {"capability", "requirement", "definition"},
    "comparison": {"comparison_dimension"},
    "relationship": {"relationship"},
    "conflicting_evidence": {"conflict"},
    "temporal_version": {"temporal"},
    "provenance_source_trace": {"provenance"},
    "graph_relationship": {"graph"},
}
NATURAL_FORBIDDEN = (
    "cited source",
    "cited sections",
    "supported point",
    "the stated claim",
    "gold",
    "evidence",
    "according to the provided snippet",
    "restating the source",
)
HIGH_RISK_CUE_PATTERNS = {
    "effect": (
        r"\benables?\b",
        r"\bprevents?\b",
        r"\breduces?\b",
        r"\bincreases?\b",
        r"\bleads to\b",
        r"\bresults? in\b",
        r"\bproduces?\b",
        r"\baffects?\b",
    ),
    "causal": (
        r"\bbecause\b",
        r"\bso that\b",
        r"\bin order to\b",
        r"\btherefore\b",
        r"\bfor the purpose of\b",
        r"\bprevents\b.{0,80}\bby\b",
        r"\benables\b.{0,80}\bby\b",
    ),
    "tradeoff": (
        r"\btrade[- ]?off\b",
        r"\bversus\b",
        r"\bvs\.\b",
        r"\bat the cost of\b",
        r"\bwhile\b",
        r"\bhowever\b",
        r"\bbut\b",
    ),
    "requirement": (
        r"\bmust\b",
        r"\brequired\b",
        r"\brequires\b",
        r"\bshould\b",
        r"\bneeds?\b",
        r"\bcalls for\b",
        r"\bacceptance criteria\b",
    ),
    "capability": (
        r"\bcan execute\b",
        r"\bcan\b",
        r"\bcapable\b",
        r"\bsupports?\b",
    ),
    "relationship": (
        r"\baccounts for\b",
        r"\badopts?\b",
        r"\bbound to\b",
        r"\brelated to\b",
        r"\breplaces\b",
        r"\bmaps? to\b",
    ),
    "component": (
        r"\bconsists of\b",
        r"\bincludes these components\b",
        r"\bcomponents?\b",
        r"\bparts?\b",
        r"\blayers?\b",
        r"\belements?\b",
        r"\bseparates?\b",
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_bank(bank_dir: Path = BANK_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in (
        "broad_bank.primary.jsonl",
        "broad_bank.holdout.jsonl",
        "broad_bank.sentinels.jsonl",
    ):
        rows.extend(read_jsonl(bank_dir / name))
    return rows


def load_registry(bank_dir: Path = BANK_DIR) -> dict[str, dict[str, Any]]:
    return {
        row["authority_id"]: row
        for row in read_jsonl(bank_dir / "RELATION_AUTHORITY_REGISTRY.jsonl")
    }


def load_comparison_registry(bank_dir: Path = BANK_DIR) -> dict[str, dict[str, Any]]:
    return {
        row["comparison_authority_id"]: row
        for row in read_jsonl(bank_dir / "COMPARISON_AUTHORITY_REGISTRY.jsonl")
    }


def is_positive(case: Mapping[str, Any]) -> bool:
    return str(case.get("expected_behavior")) in {"answer", "partial"}


def relation_certificates(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        prop.get("relation_certificate", {})
        for prop in case.get("required_propositions", [])
        if isinstance(prop.get("relation_certificate"), Mapping)
    ]


def support_by_id(case: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(support["support_id"]): support
        for support in case.get("gold_support", [])
        if support.get("support_id")
    }


def question_errors(case: Mapping[str, Any]) -> list[str]:
    if not is_positive(case):
        return []
    family = str(case.get("family"))
    question = str(case.get("question", ""))
    lowered = question.lower()
    errors = []
    if family != "provenance_source_trace" and any(
        phrase in lowered for phrase in NATURAL_FORBIDDEN
    ):
        errors.append("EVALUATOR_NATIVE_POSITIVE_QUESTION")
    if family not in {"provenance_source_trace", "graph_relationship"} and re.search(
        r"(section_[0-9a-f]{8,}|dec[_ -][0-9a-f]{12,}|[0-9a-f]{24,})",
        question,
        re.I,
    ):
        errors.append("HASHLIKE_POSITIVE_USER_SUBJECT")
    comparison = case.get("comparison_certificate") or {}
    if family == "comparison":
        if not all(
            str(comparison.get(key, "")).strip()
            for key in ("left_subject", "right_subject", "dimension")
        ):
            errors.append("UNRELATED_FACT_COMPARISON")
        else:
            for key in ("left_subject", "right_subject", "dimension"):
                if str(comparison[key]).lower() not in lowered:
                    errors.append("UNRELATED_FACT_COMPARISON")
                    break
    return errors


def registry_errors(
    registry: Mapping[str, Mapping[str, Any]],
    comparison_registry: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    for authority in registry.values():
        if "case_id" in authority:
            errors.append("REGISTRY_CASE_ID_FIELD")
        if "family" in authority:
            errors.append("REGISTRY_FAMILY_AUTHORITY_FIELD")
        snippet = str(authority.get("exact_support_snippet", ""))
        cues = authority.get("cue_spans", [])
        if not cues or not all(str(cue) in snippet for cue in cues):
            errors.append("EXTRACTIVE_CUE_BYTE_MATCH_FAIL")
        relation = str(authority.get("relation_kind", ""))
        if (
            relation in HIGH_RISK_CUE_PATTERNS
            and str(authority.get("certificate_mode")) == "extractive"
            and not any(
                re.search(pattern, snippet, re.I)
                for pattern in HIGH_RISK_CUE_PATTERNS[relation]
            )
        ):
            errors.append(f"HIGH_RISK_CUE_MISSING:{relation}")
    for comparison in comparison_registry.values():
        for key in (
            "left_authority_id",
            "right_authority_id",
            "left_subject",
            "right_subject",
            "dimension",
            "left_value_proposition",
            "right_value_proposition",
            "comparison_statement",
        ):
            if not str(comparison.get(key, "")).strip():
                errors.append("COMPARISON_AUTHORITY_INCOMPLETE")
        if (
            comparison.get("left_authority_id") not in registry
            or comparison.get("right_authority_id") not in registry
        ):
            errors.append("COMPARISON_AUTHORITY_REF_MISSING")
    return errors


def case_errors(
    case: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
    comparison_registry: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    errors = question_errors(case)
    family = str(case.get("family"))
    positive = is_positive(case)
    relations = {str(cert.get("relation_kind")) for cert in relation_certificates(case)}
    authority_ids = [
        str(authority_id)
        for cert in relation_certificates(case)
        for authority_id in cert.get("source_relation_authority_ids", [])
    ]
    if positive and family in HIGH_RISK_FAMILIES and relations.isdisjoint(
        EXPECTED_RELATIONS[family]
    ):
        code = {
            "causal_why": "BOOKKEEPING_AS_CAUSAL",
            "impact_effect": "IDENTITY_AS_EFFECT",
            "trade_offs": "DEFINITION_PAIR_AS_TRADEOFF",
            "capability_skill_requirement": "BOOKKEEPING_AS_REQUIREMENT",
            "comparison": "UNRELATED_FACT_COMPARISON",
            "relationship": "COOCCURRENCE_AS_RELATIONSHIP",
            "conflicting_evidence": "SINGLE_SOURCE_CONFLICT",
            "temporal_version": "SINGLE_RECORD_POSITIVE_TEMPORAL",
        }.get(family, f"HIGH_RISK_POSITIVE_WITHOUT_EXPLICIT_AUTHORITY:{family}")
        errors.append(code)
    for authority_id in authority_ids:
        authority = registry.get(authority_id)
        if authority is None:
            errors.append("RELATION_AUTHORITY_REF_MISSING")
            continue
        if (
            positive
            and family != "comparison"
            and family not in authority.get("positive_family_eligibility", [])
        ):
            errors.append("POSITIVE_FAMILY_NOT_REGISTRY_ELIGIBLE")
    if not positive and case.get("requested_unsupported_relation_kind"):
        requested = str(case["requested_unsupported_relation_kind"])
        supported_relations = {
            str(registry.get(authority_id, {}).get("relation_kind"))
            for authority_id in authority_ids
        }
        if requested in supported_relations:
            errors.append("NEGATIVE_REQUESTED_RELATION_PRESENT")
    if family == "comparison" and positive:
        comparison_id = str(
            (case.get("comparison_certificate") or {}).get(
                "comparison_authority_id",
                "",
            )
        )
        if comparison_id not in comparison_registry:
            errors.append("UNRELATED_FACT_COMPARISON")
    if family == "temporal_version" and positive:
        temporal = case.get("temporal_certificate") or {}
        if int(temporal.get("observed_temporal_record_count", 0)) < int(
            temporal.get("minimum_required_for_positive", 2)
        ):
            errors.append("SINGLE_RECORD_POSITIVE_TEMPORAL")
    if family == "conflicting_evidence" and positive:
        support_ids = {
            ref
            for prop in case.get("required_propositions", [])
            for ref in prop.get("support_refs", [])
        }
        if len(support_ids) < 2:
            errors.append("SINGLE_SOURCE_CONFLICT")
    for prop in case.get("required_propositions", []):
        cert = prop.get("relation_certificate") or {}
        support_ids = set(support_by_id(case))
        if not set(prop.get("support_refs", [])) <= support_ids:
            errors.append("BAD_SUPPORT_REF")
        if not set(prop.get("support_refs", [])) <= set(cert.get("source_support_ids", [])):
            errors.append("RELATION_CERT_SUPPORT_MISMATCH")
    return sorted(set(errors))


def audit_rows(bank_dir: Path = BANK_DIR) -> list[dict[str, str]]:
    registry = load_registry(bank_dir)
    comparison_registry = load_comparison_registry(bank_dir)
    rows: list[dict[str, str]] = []
    for error in registry_errors(registry, comparison_registry):
        rows.append(
            {
                "case_id": "__registry__",
                "pool": "",
                "family": "",
                "expected_behavior": "",
                "relation_kinds": "",
                "PASS_FAIL": "FAIL",
                "reason": error,
            }
        )
    for case in load_bank(bank_dir):
        errors = case_errors(case, registry, comparison_registry)
        rows.append(
            {
                "case_id": str(case.get("case_id", "")),
                "pool": str(case.get("pool", "")),
                "family": str(case.get("family", "")),
                "expected_behavior": str(case.get("expected_behavior", "")),
                "relation_kinds": "|".join(
                    sorted(
                        str(cert.get("relation_kind", ""))
                        for cert in relation_certificates(case)
                    )
                ),
                "PASS_FAIL": "FAIL" if errors else "PASS",
                "reason": "|".join(errors) if errors else "ok",
            }
        )
    sentinel_audit = bank_dir / "SENTINEL_RELATION_AUDIT.csv"
    if sentinel_audit.exists():
        with sentinel_audit.open() as fh:
            sentinel_rows = list(csv.DictReader(fh))
        if len(sentinel_rows) != 7:
            rows.append(
                {
                    "case_id": "__sentinel_audit__",
                    "pool": "sentinel",
                    "family": "",
                    "expected_behavior": "",
                    "relation_kinds": "",
                    "PASS_FAIL": "FAIL",
                    "reason": "SENTINEL_RELATION_AUDIT_COVERAGE_FAIL",
                }
            )
    return rows


def write_audit_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    fields = [
        "case_id",
        "pool",
        "family",
        "expected_behavior",
        "relation_kinds",
        "PASS_FAIL",
        "reason",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-dir", type=Path, default=BANK_DIR)
    parser.add_argument("--output", type=Path, default=BANK_DIR / "INDEPENDENT_RELATION_AUDIT.csv")
    args = parser.parse_args()
    rows = audit_rows(args.bank_dir)
    write_audit_csv(args.output, rows)
    fails = [row for row in rows if row["PASS_FAIL"] != "PASS"]
    print(f"independent_relation_audit_rows={len(rows)}")
    print(f"independent_relation_audit_fails={len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
