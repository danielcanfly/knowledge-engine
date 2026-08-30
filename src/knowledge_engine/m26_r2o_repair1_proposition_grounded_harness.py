from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BANK_DIR = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "m26_r2o_repair1_proposition_grounded_bank"
)
RELATION_AUTHORITY_REGISTRY = BANK_DIR / "RELATION_AUTHORITY_REGISTRY.jsonl"
COMPARISON_AUTHORITY_REGISTRY = BANK_DIR / "COMPARISON_AUTHORITY_REGISTRY.jsonl"

BANK_SCHEMA_VERSION = "m26-r2o-proposition-grounded-bank/v1"
AUDIT_SCHEMA_VERSION = "m26-r2o-proposition-grounded-audit/v1"
LIVE_MATRIX_SCHEMA_VERSION = "m26-r2o-frozen-live-matrix/v2"
HOSTILE_SEMANTIC_REVIEW_REQUIRED = "HOSTILE_SEMANTIC_REVIEW_REQUIRED"

CONTROL_BEHAVIORS = {"partial", "abstain", "clarify-compatible"}
PLACEHOLDER_PHRASES = {
    "stay within the proposition supported by the exact snippet",
    "generic placeholder",
}
GOLD_MODES = {"extractive", "structural", "sentinel_synthesis", "context_only"}
CONTEXT_SUPPORT_ROLES = {"context", "negative_distractor"}
RELATION_KINDS = {
    "definition",
    "role",
    "effect",
    "causal",
    "purpose",
    "process",
    "comparison_dimension",
    "relationship",
    "example",
    "tradeoff",
    "component",
    "capability",
    "requirement",
    "enumeration",
    "factual",
    "context_only",
    "provenance",
    "graph",
    "temporal",
    "conflict",
}
RELATION_CERTIFICATE_KEYS = {
    "relation_kind",
    "subject",
    "predicate",
    "object_or_complement",
    "source_support_ids",
    "positive_family_eligibility",
    "negative_family_eligibility",
    "certificate_mode",
}
EVALUATOR_NATIVE_PHRASES = (
    "compare the two cited sections",
    "synthesize the two cited sections",
    "what relationship does the source state for",
    "how would you restate the supported point",
    "what exact factual point is stated in",
    "using only the cited source",
    "cited source",
    "cited sections",
    "supported point",
    "the stated claim",
    "gold",
    "evidence",
    "according to the provided snippet",
    "restating the source",
)
HIGH_RISK_POSITIVE_FAMILIES = {
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
EXPECTED_RELATION_KINDS_BY_HIGH_RISK_FAMILY = {
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def load_relation_authority_registry(
    bank_dir: Path = BANK_DIR,
) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["authority_id"]): row
        for row in _read_jsonl(bank_dir / "RELATION_AUTHORITY_REGISTRY.jsonl")
        if row.get("authority_id")
    }


def load_comparison_authority_registry(
    bank_dir: Path = BANK_DIR,
) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["comparison_authority_id"]): row
        for row in _read_jsonl(bank_dir / "COMPARISON_AUTHORITY_REGISTRY.jsonl")
        if row.get("comparison_authority_id")
    }


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


def _primary_support(case: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in case.get("gold_support", []):
        if str(item.get("support_role")) == "primary":
            return item
    return None


def _certificate_keys_present(certificate: Mapping[str, Any], keys: set[str]) -> bool:
    return keys <= set(certificate)


def _canonical_text(text: str) -> str:
    cleaned = re.sub(r"[`*_#>\-|:.(),;]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _support_by_id(case: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["support_id"]): item
        for item in case.get("gold_support", [])
        if str(item.get("support_id", "")).strip()
    }


def _render_provenance_proposition(certificate: Mapping[str, Any]) -> str:
    return (
        f"{certificate['primary_concept_id']} is bound to provenance record "
        f"{certificate['provenance_record_id']} whose subject is "
        f"{certificate['provenance_subject_concept_id']}."
    )


def _render_graph_proposition(graph_support: Mapping[str, Any]) -> str:
    certificate = graph_support["graph_certificate"]
    return (
        f"{certificate['source_node_id']} {certificate['relation_type']} "
        f"{certificate['target_node_id']}."
    )


def _render_temporal_proposition(certificate: Mapping[str, Any]) -> str:
    count = int(certificate["observed_temporal_record_count"])
    noun = "record" if count == 1 else "records"
    return f"Only {count} {noun} is available; a newer-version ordering cannot be established."


def _prop_text_is_in_support(
    prop: Mapping[str, Any],
    supports: Sequence[Mapping[str, Any]],
) -> bool:
    proposition_text = str(prop.get("proposition_text", "")).strip()
    source_text = "\n\n".join(str(s.get("exact_support_snippet", "")).strip() for s in supports)
    if not proposition_text or not source_text:
        return False
    if proposition_text in source_text:
        return True
    normalized_prop = _canonical_text(proposition_text)
    normalized_source = _canonical_text(source_text)
    return bool(normalized_prop) and normalized_prop in normalized_source


def validate_gold_authority(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    supports = _support_by_id(case)
    for prop in case.get("required_propositions", []):
        prop_id = str(prop.get("proposition_id", ""))
        gold_mode = str(prop.get("gold_mode", ""))
        if gold_mode not in GOLD_MODES:
            errors.append("GOLD_MODE_INVALID")
        refs = [str(ref) for ref in prop.get("support_refs", [])]
        ref_supports = [supports[ref] for ref in refs if ref in supports]
        for support in ref_supports:
            support_role = str(support.get("support_role", ""))
            if support_role == "context":
                errors.append("CONTEXT_SUPPORT_USED_AS_REQUIRED_AUTHORITY")
            if support_role == "negative_distractor":
                errors.append("NEGATIVE_DISTRACTOR_USED_AS_AUTHORITY")
            if prop_id not in support.get("authority_for", []):
                errors.append("AUTHORITY_FOR_MISMATCH")

        if gold_mode in {
            "extractive",
            "context_only",
            "sentinel_synthesis",
        } and not _prop_text_is_in_support(prop, ref_supports):
            errors.append("EXTRACTIVE_PROP_NOT_IN_SUPPORT")
        if gold_mode == "sentinel_synthesis":
            if prop.get("hostile_semantic_review_required") is not True:
                errors.append("SENTINEL_HOSTILE_REVIEW_NOT_REQUIRED")
            if not prop.get("sentinel_atomic_mapping"):
                errors.append("SENTINEL_ATOMIC_MAPPING_MISSING")

        if gold_mode == "structural":
            certificate_type = str(prop.get("structural_certificate_type", ""))
            expected: str | None = None
            if certificate_type == "provenance":
                certificate = case.get("provenance_certificate") or {}
                if _certificate_keys_present(
                    certificate,
                    {
                        "primary_concept_id",
                        "provenance_record_id",
                        "provenance_subject_concept_id",
                    },
                ):
                    expected = _render_provenance_proposition(certificate)
                if expected != prop.get("proposition_text"):
                    errors.append("PROVENANCE_PROP_CERT_MISMATCH")
                    errors.append("STRUCTURAL_PROP_CERT_MISMATCH")
            elif certificate_type == "graph":
                graph_supports = [
                    support
                    for support in ref_supports
                    if str(support.get("support_role")) == "graph_edge"
                    and support.get("graph_certificate")
                ]
                expected = _render_graph_proposition(graph_supports[0]) if graph_supports else None
                if expected != prop.get("proposition_text"):
                    errors.append("GRAPH_PROP_CERT_MISMATCH")
                    errors.append("STRUCTURAL_PROP_CERT_MISMATCH")
            elif certificate_type == "temporal":
                certificate = case.get("temporal_certificate") or {}
                if _certificate_keys_present(
                    certificate,
                    {"observed_temporal_record_count"},
                ):
                    expected = _render_temporal_proposition(certificate)
                if expected != prop.get("proposition_text"):
                    errors.append("TEMPORAL_PROP_CERT_MISMATCH")
                    errors.append("STRUCTURAL_PROP_CERT_MISMATCH")
            else:
                errors.append("STRUCTURAL_PROP_CERT_MISMATCH")

    question = str(case.get("question", ""))
    if question == "What kind of skill does a Product Manager need?":
        for support in [
            supports[ref]
            for prop in case.get("required_propositions", [])
            for ref in prop.get("support_refs", [])
            if ref in supports
        ]:
            source = str(support.get("source_identity", "")).lower()
            if (
                "pm-" not in source
                or "atlas-of-agent" in source
                or "harness-theory" in source
                or "founder" in source
                or "venture" in source
            ):
                errors.append("SENTINEL_UNRELATED_AUTHORITY")
    if question == "What is a skill in an AI agent architecture?":
        for prop in case.get("required_propositions", []):
            refs = [str(ref) for ref in prop.get("support_refs", [])]
            if refs != [f"{case['case_id']}-SUP01"]:
                errors.append("SENTINEL_UNRELATED_AUTHORITY")
    if question == "What is the role of user research in product management?":
        for prop in case.get("required_propositions", []):
            refs = [str(ref) for ref in prop.get("support_refs", [])]
            if refs != ["SENTINEL-Q3-CONTROL-SUP01"]:
                errors.append("SENTINEL_UNRELATED_AUTHORITY")
    return errors


def _is_positive(case: Mapping[str, Any]) -> bool:
    return str(case.get("expected_behavior")) in {"answer", "partial"}


def _natural_question_pass(case: Mapping[str, Any]) -> bool:
    if str(case.get("family")) == "provenance_source_trace":
        return True
    if not _is_positive(case):
        return True
    question = str(case.get("question", "")).lower()
    return not any(phrase in question for phrase in EVALUATOR_NATIVE_PHRASES)


def _hashlike_positive_subject(case: Mapping[str, Any]) -> bool:
    if not _is_positive(case):
        return False
    if str(case.get("family")) in {"provenance_source_trace", "graph_relationship"}:
        return False
    return bool(
        re.search(
            r"(section_[0-9a-f]{8,}|dec[_ -][0-9a-f]{12,}|[0-9a-f]{24,})",
            str(case.get("question", "")),
            re.I,
        )
    )


def _registry_authority_ids(case: Mapping[str, Any]) -> set[str]:
    return {
        str(authority_id)
        for prop in case.get("required_propositions", [])
        for authority_id in (prop.get("relation_certificate") or {}).get(
            "source_relation_authority_ids", []
        )
    }


def validate_relation_alignment(case: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    family = str(case.get("family", ""))
    positive = _is_positive(case)
    if not _natural_question_pass(case):
        errors.append("EVALUATOR_NATIVE_POSITIVE_QUESTION")
    if _hashlike_positive_subject(case):
        errors.append("HASHLIKE_POSITIVE_USER_SUBJECT")

    relation_kinds: set[str] = set()
    positive_eligibility: set[str] = set()
    for prop in case.get("required_propositions", []):
        certificate = prop.get("relation_certificate") or {}
        if set(certificate) < RELATION_CERTIFICATE_KEYS:
            errors.append("RELATION_CERTIFICATE_INCOMPLETE")
            continue
        relation_kind = str(certificate.get("relation_kind"))
        if relation_kind not in RELATION_KINDS:
            errors.append("RELATION_KIND_INVALID")
        relation_kinds.add(relation_kind)
        positive_eligibility.update(
            str(item) for item in certificate.get("positive_family_eligibility", [])
        )
        support_refs = {str(ref) for ref in prop.get("support_refs", [])}
        source_support_ids = {
            str(ref) for ref in certificate.get("source_support_ids", [])
        }
        if not support_refs <= source_support_ids:
            errors.append("RELATION_CERT_SUPPORT_MISMATCH")

    if positive and family not in positive_eligibility:
        errors.append("QUESTION_FAMILY_RELATION_MISMATCH")
    if not positive and family in positive_eligibility:
        errors.append("NEGATIVE_ACCIDENTALLY_POSITIVE_RELATION")

    if positive and family == "causal_why" and relation_kinds.isdisjoint(
        {"causal", "effect", "purpose"}
    ):
        errors.append("POSITIVE_CAUSAL_WITHOUT_CAUSAL_CERT")
        errors.append("BOOKKEEPING_AS_CAUSAL")
    if positive and family == "trade_offs" and "tradeoff" not in relation_kinds:
        errors.append("POSITIVE_TRADEOFF_WITHOUT_TRADEOFF_CERT")
        errors.append("DEFINITION_PAIR_AS_TRADEOFF")
    if positive and family == "impact_effect" and relation_kinds.isdisjoint(
        {"effect", "causal"}
    ):
        errors.append("POSITIVE_EFFECT_WITHOUT_EFFECT_CERT")
        errors.append("IDENTITY_AS_EFFECT")
    if positive and family == "architecture_components" and relation_kinds.isdisjoint(
        {"component", "enumeration"}
    ):
        errors.append("POSITIVE_COMPONENT_WITHOUT_COMPONENT_CERT")
    if positive and family == "capability_skill_requirement" and relation_kinds.isdisjoint(
        {"capability", "requirement", "definition"}
    ):
        errors.append("POSITIVE_CAPABILITY_WITHOUT_CAPABILITY_CERT")
        errors.append("BOOKKEEPING_AS_REQUIREMENT")
    if positive and family == "comparison":
        comparison = case.get("comparison_certificate") or {}
        if not (
            comparison.get("left_subject")
            and comparison.get("right_subject")
            and comparison.get("dimension")
            and "comparison_dimension" in relation_kinds
            and comparison.get("comparison_authority_id")
        ):
            errors.append("POSITIVE_COMPARISON_WITHOUT_DIMENSION_CERT")
            errors.append("UNRELATED_FACT_COMPARISON")
    if positive and family == "relationship" and "relationship" not in relation_kinds:
        errors.append("POSITIVE_RELATIONSHIP_WITHOUT_RELATION_CERT")
        errors.append("COOCCURRENCE_AS_RELATIONSHIP")
    if positive and family == "conflicting_evidence":
        support_refs = {
            ref
            for prop in case.get("required_propositions", [])
            for ref in prop.get("support_refs", [])
        }
        if "conflict" not in relation_kinds or len(support_refs) < 2:
            errors.append("SINGLE_SOURCE_CONFLICT")
    if positive and family == "temporal_version":
        temporal = case.get("temporal_certificate") or {}
        observed = int(temporal.get("observed_temporal_record_count", 0))
        required = int(temporal.get("minimum_required_for_positive", 2))
        if "temporal" not in relation_kinds or observed < required:
            errors.append("SINGLE_RECORD_POSITIVE_TEMPORAL")
    if positive and family in HIGH_RISK_POSITIVE_FAMILIES and relation_kinds.isdisjoint(
        EXPECTED_RELATION_KINDS_BY_HIGH_RISK_FAMILY[family]
    ):
        errors.append("HIGH_RISK_POSITIVE_WITHOUT_EXPLICIT_AUTHORITY")
    requested_relation = str(case.get("requested_unsupported_relation_kind", ""))
    if requested_relation and not positive and requested_relation in relation_kinds:
        errors.append("NEGATIVE_REQUESTED_RELATION_PRESENT")
    if positive and family == "multi_part" and not (
        (case.get("multipart_clause_certificate") or {}).get("supported_prop_ids")
    ):
        errors.append("MULTIPART_CLAUSE_COVERAGE_FAIL")
    if str(case.get("expected_behavior")) == "partial" and not case.get(
        "unanswered_dimensions_expected"
    ):
        errors.append("PARTIAL_UNANSWERED_COVERAGE_FAIL")
    if positive and family == "broad_synthesis" and not (
        (case.get("broad_synthesis_certificate") or {}).get("atomic_prop_ids")
    ):
        errors.append("BROAD_SYNTHESIS_ATOMIC_SUPPORT_FAIL")
    return errors


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
        "graph_certificate",
        "provenance_certificate",
        "temporal_certificate",
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
        if "authority_for" not in support:
            errors.append("missing_authority_for")
    for prop in case.get("required_propositions", []):
        if not set(prop.get("support_refs", [])) <= support_ids:
            errors.append(f"bad_support_refs:{case['case_id']}")
        if not str(prop.get("proposition_text", "")).strip():
            errors.append("empty_proposition_text")
        if not str(prop.get("entailment_note", "")).strip():
            errors.append("empty_entailment_note")
        if not str(prop.get("relation_type", "")).strip():
            errors.append("empty_relation_type")
        if str(prop.get("gold_mode", "")) not in GOLD_MODES:
            errors.append("GOLD_MODE_INVALID")
        if not isinstance(prop.get("relation_certificate"), Mapping):
            errors.append("RELATION_CERTIFICATE_INCOMPLETE")
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
    primary_support = _primary_support(case)
    if primary_support is not None:
        if case.get("graph_edge_required"):
            graph_certificate = case.get("graph_certificate") or {}
            if not _certificate_keys_present(
                graph_certificate,
                {
                    "graph_edge_id",
                    "graph_relation_type",
                    "graph_directed",
                    "primary_concept_id",
                    "primary_section_id",
                    "primary_source_identity",
                },
            ):
                errors.append("graph_certificate_incomplete")
        if case.get("provenance_required"):
            provenance_certificate = case.get("provenance_certificate") or {}
            if not _certificate_keys_present(
                provenance_certificate,
                {
                    "primary_concept_id",
                    "primary_section_id",
                    "primary_source_identity",
                    "provenance_record_id",
                    "provenance_subject_concept_id",
                    "subject_match",
                },
            ):
                errors.append("provenance_certificate_incomplete")
            explicit_mapping_note = provenance_certificate.get("explicit_mapping_note")
            if provenance_certificate.get("subject_match") is False and not explicit_mapping_note:
                errors.append("provenance_certificate_missing_mapping_note")
        if case.get("family") == "temporal_version":
            temporal_certificate = case.get("temporal_certificate") or {}
            if not _certificate_keys_present(
                temporal_certificate,
                {
                    "primary_concept_id",
                    "primary_section_id",
                    "primary_source_identity",
                    "temporal_evidence_mode",
                    "minimum_required_for_positive",
                    "observed_temporal_record_count",
                },
            ):
                errors.append("temporal_certificate_incomplete")
            if temporal_certificate.get("temporal_evidence_mode") != "insufficient":
                errors.append("temporal_certificate_mode_invalid")
            if int(case.get("temporal_versions_required", 0)) != 0:
                errors.append("temporal_versions_required_nonzero")
    errors.extend(validate_gold_authority(case))
    errors.extend(validate_relation_alignment(case))
    return errors


def validate_bank(bank_dir: Path = BANK_DIR) -> list[str]:
    rows = load_bank(bank_dir)
    errors: list[str] = []
    relation_registry = load_relation_authority_registry(bank_dir)
    comparison_registry = load_comparison_authority_registry(bank_dir)
    if not relation_registry:
        errors.append("RELATION_AUTHORITY_REGISTRY_MISSING")
    for authority in relation_registry.values():
        if "case_id" in authority:
            errors.append("REGISTRY_CASE_ID_FIELD")
        if "family" in authority:
            errors.append("REGISTRY_FAMILY_AUTHORITY_FIELD")
        snippet = str(authority.get("exact_support_snippet", ""))
        cues = authority.get("cue_spans", [])
        if not cues or not all(str(cue) in snippet for cue in cues):
            errors.append("EXTRACTIVE_CUE_BYTE_MATCH_FAIL")
    for comparison in comparison_registry.values():
        if comparison.get("left_authority_id") not in relation_registry:
            errors.append("COMPARISON_AUTHORITY_REF_MISSING")
        if comparison.get("right_authority_id") not in relation_registry:
            errors.append("COMPARISON_AUTHORITY_REF_MISSING")
    for row in rows:
        errors.extend(validate_case_structure(row))
        for authority_id in _registry_authority_ids(row):
            if authority_id not in relation_registry:
                errors.append("RELATION_AUTHORITY_REF_MISSING")
        if row.get("family") == "comparison" and _is_positive(row):
            comparison_id = str(
                (row.get("comparison_certificate") or {}).get(
                    "comparison_authority_id", ""
                )
            )
            if comparison_id not in comparison_registry:
                errors.append("COMPARISON_AUTHORITY_REF_MISSING")
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
    graph_certificate = case.get("graph_certificate") or {}
    provenance_certificate = case.get("provenance_certificate") or {}
    temporal_certificate = case.get("temporal_certificate") or {}
    deterministic_checks["graph_certificate_valid"] = (not case.get("graph_edge_required")) or (
        bool(graph_certificate)
        and _certificate_keys_present(
            graph_certificate,
            {
                "graph_edge_id",
                "graph_relation_type",
                "graph_directed",
                "primary_concept_id",
                "primary_section_id",
                "primary_source_identity",
            },
        )
    )
    deterministic_checks["provenance_certificate_valid"] = (
        not case.get("provenance_required")
    ) or (
        bool(provenance_certificate)
        and _certificate_keys_present(
            provenance_certificate,
            {
                "primary_concept_id",
                "primary_section_id",
                "primary_source_identity",
                "provenance_record_id",
                "provenance_subject_concept_id",
                "subject_match",
            },
        )
        and (
            provenance_certificate.get("subject_match") is True
            or bool(provenance_certificate.get("explicit_mapping_note"))
        )
    )
    deterministic_checks["temporal_certificate_valid"] = (
        case.get("family") != "temporal_version"
        or (
            bool(temporal_certificate)
            and temporal_certificate.get("temporal_evidence_mode") == "insufficient"
            and int(case.get("temporal_versions_required", 0)) == 0
        )
    )
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
            "graph_required": deterministic_checks["graph_certificate_valid"],
            "provenance_required": deterministic_checks["provenance_certificate_valid"],
            "temporal_versions_required": int(case.get("temporal_versions_required", 0)),
        },
        "partial_unanswered_dimension_check": deterministic_checks["partial_unanswered_dimensions"],
        "claim_local_exact_support_snippets": snippets,
        "deterministic_checks": deterministic_checks,
        "verdict": "PASS" if passed else "FAIL",
    }
