from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from .errors import IntegrityError
from .m21_entity_resolution import (
    FOUNDATION_SHA,
    SOURCE_SHA,
    build_resolution_candidate_packet,
)

SCHEMA = "knowledge-engine-m25-identity-gold-suite/v1"
ITEM_SCHEMA = "knowledge-engine-m25-identity-gold-item/v1"
REPORT_SCHEMA = "knowledge-engine-m25-identity-baseline-report/v1"
SPLIT_SCHEMA = "knowledge-engine-m25-identity-split-manifest/v1"
LEDGER_SCHEMA = "knowledge-engine-m25-identity-adjudication-ledger/v1"
ENGINE_BASE_SHA = "744cfdc830da4a7bcfd4ed6ec3cf55972b042358"
PREDECESSOR_STATUS = "m25_3_extraction_worker_accepted"
ENGINE_SHA = "a" * 40
SPLITS = ("train", "calibration", "final")
CLASS_LABELS = (
    "exact_match",
    "approved_alias",
    "duplicate",
    "near_match_distinct",
    "parent_child_distinct",
    "polysemy_ambiguous",
    "contradiction_without_identity",
    "supersession_without_identity_collapse",
    "ambiguous_insufficient_evidence",
    "blocked_policy",
)
MERGE_OUTCOMES = {"exact_existing_match", "attach_alias_candidate"}
DISTINCT_CLASSES = {
    "near_match_distinct",
    "parent_child_distinct",
    "supersession_without_identity_collapse",
    "polysemy_ambiguous",
    "ambiguous_insufficient_evidence",
    "blocked_policy",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sign(value: dict[str, Any], field: str) -> dict[str, Any]:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = digest(unsigned)
    return value


def evidence(seed: str) -> list[dict[str, Any]]:
    excerpt = f"evidence:{seed}"
    return [
        {
            "snapshot_id": f"snapshot_{digest(seed)[:16]}",
            "plan_sha256": hashlib.sha256(f"plan:{seed}".encode()).hexdigest(),
            "derivative_id": f"derivative_{digest(seed)[:16]}",
            "start": 0,
            "end": len(excerpt),
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
    ]


def candidate(
    candidate_id: str,
    label: str,
    *,
    kind: str = "concept",
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    language: str = "en",
    confidence: float = 0.8,
    **extra: Any,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "candidate_id": candidate_id,
        "kind": kind,
        "label": label,
        "normalized_label": " ".join(label.split()).casefold(),
        "language": language,
        "confidence": confidence,
        "aliases": aliases or [],
        "controlled_tags": tags or [],
        "evidence_spans": evidence(candidate_id),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }
    value.update(extra)
    return value


def source_concept(
    x_kos_id: str,
    title: str,
    *,
    aliases: list[str] | None = None,
    terms: list[str] | None = None,
    tags: list[str] | None = None,
    audience: str = "public",
) -> dict[str, Any]:
    return {
        "x_kos_id": x_kos_id,
        "concept_path": f"concepts/{x_kos_id}.md",
        "title": title,
        "normalized_title": " ".join(title.split()).casefold(),
        "aliases": aliases or [],
        "bilingual_terms": terms or [],
        "tags": tags or [],
        "audience": audience,
        "source_sha256": hashlib.sha256(x_kos_id.encode()).hexdigest(),
    }


def governed_tag(candidate_id: str, tag: str) -> dict[str, Any]:
    return {
        "tag_candidate_id": f"tag_{candidate_id}_{digest(tag)[:8]}",
        "source_candidate_id": candidate_id,
        "source_tag": tag,
        "canonical_tag": tag,
        "dimension": "domain",
        "confidence": 0.7,
        "evidence_spans": evidence(f"tag:{candidate_id}:{tag}"),
        "status": "pending_review",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
    }


def extraction(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema": "knowledge-engine-extraction-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "source_text_untrusted": True,
        "plan_sha256": "1" * 64,
        "checkpoint_sha256": "2" * 64,
        "inventory_sha256": "3" * 64,
        "identity": {
            "engine_sha": ENGINE_SHA,
            "source_sha": SOURCE_SHA,
            "foundation_sha": FOUNDATION_SHA,
        },
        "allowed_tags": sorted(
            {
                tag
                for item in candidates
                for tag in item.get("controlled_tags", [])
                if isinstance(tag, str)
            }
            or {"benchmark"}
        ),
        "derivative_count": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    return sign(packet, "packet_sha256")


def governed(
    extraction_packet: dict[str, Any],
    tags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema": "knowledge-engine-governed-candidates/v1",
        "authority": "candidate_only",
        "canonical_knowledge": False,
        "production_authority": False,
        "review_required": True,
        "foundation_sha": FOUNDATION_SHA,
        "extraction_packet_sha256": extraction_packet["packet_sha256"],
        "identity": extraction_packet["identity"],
        "relation_ontology": {
            "schema_version": "knowledge-os-relation-ontology/v0.1",
            "ontology_id": "daniel-knowledge-os/relation-ontology",
            "version": "0.1.0",
            "sha256": "4" * 64,
        },
        "tag_taxonomy": {
            "schema_version": "knowledge-os-tag-taxonomy/v0.1",
            "taxonomy_id": "daniel-knowledge-os/tag-taxonomy",
            "version": "0.1.0",
            "sha256": "5" * 64,
        },
        "typed_relation_count": 0,
        "governed_tag_count": len(tags or []),
        "typed_relation_candidates": [],
        "governed_tag_candidates": tags or [],
    }
    return sign(packet, "packet_sha256")


def source_index(concepts: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {
        "schema": "knowledge-engine-source-resolution-index/v1",
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "authority": "reviewed_source_index",
        "concept_count": len(concepts),
        "concepts": concepts,
    }
    return sign(index, "index_sha256")


def _case(
    candidates: list[dict[str, Any]],
    concepts: list[dict[str, Any]],
    *,
    tags: list[dict[str, Any]] | None = None,
    audiences: Mapping[str, str] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "candidates": candidates,
        "source_concepts": concepts,
        "governed_tags": tags or [],
        "candidate_audiences": dict(
            audiences or {item["candidate_id"]: "public" for item in candidates}
        ),
        "claim_assertions": claims or [],
    }


def _expected(
    outcomes: Iterable[str],
    *,
    contradictions: int = 0,
    blocked: bool = False,
    required_signals: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "resolution_outcomes": sorted(outcomes),
        "contradiction_count": contradictions,
        "packaging_blocked": blocked,
        "required_explanation_signals": sorted(set(required_signals)),
    }


def _templates() -> dict[str, list[tuple[dict[str, Any], dict[str, Any], str]]]:
    return {
        "exact_match": [
            (
                _case(
                    [candidate("c_exact_rag", "Retrieval Augmented Generation")],
                    [source_concept("kos_rag", "Retrieval Augmented Generation")],
                ),
                _expected(["exact_existing_match"], required_signals=["exact_normalized_title"]),
                "Exact canonical title equality identifies one existing concept.",
            ),
            (
                _case(
                    [candidate("c_exact_harness", "Agent Harness")],
                    [source_concept("kos_harness", "Agent Harness")],
                ),
                _expected(["exact_existing_match"], required_signals=["exact_normalized_title"]),
                "Exact title equality must remain review-only but unambiguous.",
            ),
            (
                _case(
                    [candidate("c_exact_lineage", "Data Lineage")],
                    [source_concept("kos_lineage", "Data Lineage")],
                ),
                _expected(["exact_existing_match"], required_signals=["exact_normalized_title"]),
                "A final held-out exact title case verifies deterministic replay.",
            ),
        ],
        "approved_alias": [
            (
                _case(
                    [candidate("c_alias_rag", "RAG", kind="alias", target_label="Retrieval Augmented Generation")],
                    [source_concept("kos_rag", "Retrieval Augmented Generation")],
                ),
                _expected(["attach_alias_candidate"], required_signals=["unique_alias_target"]),
                "A new alias may attach only to one uniquely owned canonical target.",
            ),
            (
                _case(
                    [candidate("c_alias_aop", "AOP", kind="alias", target_label="Annual Operating Plan")],
                    [source_concept("kos_aop", "Annual Operating Plan")],
                ),
                _expected(["attach_alias_candidate"], required_signals=["unique_alias_target"]),
                "Abbreviation ownership is unique and remains pending review.",
            ),
            (
                _case(
                    [candidate("c_alias_kri", "KRI", kind="alias", target_label="Key Risk Indicator")],
                    [source_concept("kos_kri", "Key Risk Indicator")],
                ),
                _expected(["attach_alias_candidate"], required_signals=["unique_alias_target"]),
                "Held-out alias attachment verifies no silent canonical write.",
            ),
        ],
        "duplicate": [
            (
                _case(
                    [candidate("c_dup_agent_a", "Agent"), candidate("c_dup_agent_b", "Agent")],
                    [],
                ),
                _expected(["probable_duplicate"], blocked=True, required_signals=["within_batch_exact_label_or_explicit_hint"]),
                "Two same-audience candidates with the same normalized label form a duplicate cluster.",
            ),
            (
                _case(
                    [
                        candidate("c_dup_forecast_a", "Forecast"),
                        candidate("c_dup_forecast_b", "Operating Forecast"),
                        candidate("c_dup_hint", "Forecast", kind="duplicate_hint", target_label="Operating Forecast"),
                    ],
                    [],
                ),
                _expected(["probable_duplicate"], blocked=True, required_signals=["within_batch_exact_label_or_explicit_hint"]),
                "An explicit duplicate hint may cluster otherwise different labels.",
            ),
            (
                _case(
                    [candidate("c_dup_cache_a", "Semantic Cache"), candidate("c_dup_cache_b", "Semantic Cache")],
                    [],
                ),
                _expected(["probable_duplicate"], blocked=True, required_signals=["within_batch_exact_label_or_explicit_hint"]),
                "Held-out duplicate clustering must be deterministic.",
            ),
        ],
        "near_match_distinct": [
            (
                _case(
                    [candidate("c_near_revenue", "Revenue Forecast")],
                    [source_concept("kos_revenue_recognition", "Revenue Recognition")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["near_match_distinction"]),
                "Lexical resemblance without identity evidence must not merge.",
            ),
            (
                _case(
                    [candidate("c_near_model", "Model Monitoring")],
                    [source_concept("kos_model_governance", "Model Governance")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["near_match_distinction"]),
                "Related operating concepts remain separate identities.",
            ),
            (
                _case(
                    [candidate("c_near_guest", "Guest Journey Analytics")],
                    [source_concept("kos_guest_mapping", "Guest Journey Mapping")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["near_match_distinction"]),
                "Final near-match case measures explicit distinction evidence coverage.",
            ),
        ],
        "parent_child_distinct": [
            (
                _case(
                    [candidate("c_parent_wbr", "Weekly Business Review")],
                    [source_concept("kos_business_review", "Business Review")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["parent_child_distinction"]),
                "A weekly review is a narrower child, not the same identity as the generic review.",
            ),
            (
                _case(
                    [candidate("c_parent_drift", "Model Drift Detection")],
                    [source_concept("kos_model_monitoring", "Model Monitoring")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["parent_child_distinction"]),
                "A detection capability is a child of monitoring and must remain distinct.",
            ),
            (
                _case(
                    [candidate("c_parent_index", "Vector Index Maintenance")],
                    [source_concept("kos_vector_retrieval", "Vector Retrieval")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["parent_child_distinction"]),
                "Held-out parent-child pair tests non-collapse and explanation coverage.",
            ),
        ],
        "polysemy_ambiguous": [
            (
                _case(
                    [candidate("c_poly_agent", "Agent")],
                    [source_concept("kos_ai_agent", "Agent"), source_concept("kos_travel_agent", "Agent")],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["polysemy_collision"]),
                "The same surface form may denote an AI agent or a travel agent.",
            ),
            (
                _case(
                    [candidate("c_poly_model", "Model")],
                    [source_concept("kos_ml_model", "Model"), source_concept("kos_financial_model", "Model")],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["polysemy_collision"]),
                "Model is polysemous across machine learning and finance.",
            ),
            (
                _case(
                    [candidate("c_poly_pipeline", "Pipeline")],
                    [source_concept("kos_data_pipeline", "Pipeline"), source_concept("kos_sales_pipeline", "Pipeline")],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["polysemy_collision"]),
                "Held-out polysemy must fail closed instead of selecting one owner.",
            ),
        ],
        "contradiction_without_identity": [
            (
                _case(
                    [
                        candidate("claim_rag_yes", "RAG needs an index", kind="claim", subject_label="RAG", body="yes"),
                        candidate("claim_rag_no", "RAG does not need an index", kind="claim", subject_label="RAG", body="no"),
                    ],
                    [source_concept("kos_rag", "RAG")],
                    claims=[
                        {"candidate_id": "claim_rag_yes", "predicate": "requires", "scope": {"context": "runtime"}, "polarity": "positive", "value": "index"},
                        {"candidate_id": "claim_rag_no", "predicate": "requires", "scope": {"context": "runtime"}, "polarity": "negative", "value": "index"},
                    ],
                ),
                _expected([], contradictions=1, blocked=True, required_signals=["contradiction_candidate"]),
                "Opposite claims about one resolved subject are contradictions, not identity merges.",
            ),
            (
                _case(
                    [
                        candidate("claim_cache_yes", "Cache is required", kind="claim", subject_label="Semantic Cache", body="yes"),
                        candidate("claim_cache_no", "Cache is optional", kind="claim", subject_label="Semantic Cache", body="no"),
                    ],
                    [source_concept("kos_cache", "Semantic Cache")],
                    claims=[
                        {"candidate_id": "claim_cache_yes", "predicate": "required", "scope": {"environment": "production"}, "polarity": "positive", "value": "true"},
                        {"candidate_id": "claim_cache_no", "predicate": "required", "scope": {"environment": "production"}, "polarity": "negative", "value": "true"},
                    ],
                ),
                _expected([], contradictions=1, blocked=True, required_signals=["contradiction_candidate"]),
                "Contradiction detection must preserve the subject identity and block packaging.",
            ),
            (
                _case(
                    [
                        candidate("claim_acl_public", "Public access", kind="claim", subject_label="Access Policy", body="public"),
                        candidate("claim_acl_private", "Private access", kind="claim", subject_label="Access Policy", body="private"),
                    ],
                    [source_concept("kos_access", "Access Policy")],
                    claims=[
                        {"candidate_id": "claim_acl_public", "predicate": "audience", "scope": {"surface": "vault"}, "polarity": "positive", "value": "public"},
                        {"candidate_id": "claim_acl_private", "predicate": "audience", "scope": {"surface": "vault"}, "polarity": "positive", "value": "restricted"},
                    ],
                ),
                _expected([], contradictions=1, blocked=True, required_signals=["contradiction_candidate"]),
                "Held-out incompatible values are contradictions without collapsing identities.",
            ),
        ],
        "supersession_without_identity_collapse": [
            (
                _case(
                    [candidate("c_super_retention_2026", "2026 Data Retention Policy", supersedes_label="2025 Data Retention Policy")],
                    [source_concept("kos_retention_2025", "2025 Data Retention Policy")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["supersession_distinction"]),
                "A new policy version supersedes but does not share identity with the prior version.",
            ),
            (
                _case(
                    [candidate("c_super_taxonomy_v2", "Metric Taxonomy v2", supersedes_label="Metric Taxonomy v1")],
                    [source_concept("kos_taxonomy_v1", "Metric Taxonomy v1")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["supersession_distinction"]),
                "Versioned taxonomies require temporal linkage rather than identity collapse.",
            ),
            (
                _case(
                    [candidate("c_super_runbook_2026", "Incident Runbook 2026", supersedes_label="Incident Runbook 2025")],
                    [source_concept("kos_runbook_2025", "Incident Runbook 2025")],
                ),
                _expected(["distinct_new_candidate"], required_signals=["supersession_distinction"]),
                "Held-out supersession case measures explicit temporal explanation coverage.",
            ),
        ],
        "ambiguous_insufficient_evidence": [
            (
                _case(
                    [candidate("c_amb_alias_shared", "Shared", kind="alias", target_label="Unknown Target")],
                    [source_concept("kos_alpha", "Alpha"), source_concept("kos_beta", "Beta")],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["alias_target_or_ownership_ambiguous"]),
                "An alias with no uniquely resolved target must remain ambiguous.",
            ),
            (
                _case(
                    [candidate("c_amb_term", "代理", language="zh")],
                    [source_concept("kos_proxy", "Proxy", terms=["代理"]), source_concept("kos_agent", "Agent", terms=["代理"])],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["exact_bilingual_term"]),
                "A bilingual term owned by multiple concepts is insufficient for identity selection.",
            ),
            (
                _case(
                    [candidate("c_amb_title", "Control")],
                    [source_concept("kos_control_a", "Control"), source_concept("kos_control_b", "Control")],
                ),
                _expected(["ambiguous"], blocked=True, required_signals=["exact_normalized_title"]),
                "Held-out duplicate canonical titles must fail closed as ambiguous.",
            ),
        ],
        "blocked_policy": [
            (
                _case(
                    [candidate("c_block_private", "Private Knowledge")],
                    [source_concept("kos_private", "Private Knowledge", audience="restricted")],
                    audiences={"c_block_private": "public"},
                ),
                _expected(["reject"], blocked=True, required_signals=["audience_acl_mismatch"]),
                "A public candidate cannot resolve into a restricted canonical concept.",
            ),
            (
                _case(
                    [candidate("c_block_same_a", "Shared Scope"), candidate("c_block_same_b", "Shared Scope")],
                    [],
                    audiences={"c_block_same_a": "public", "c_block_same_b": "restricted"},
                ),
                _expected(["reject"], blocked=True, required_signals=["cross_audience_candidate_collision"]),
                "Cross-audience candidate collisions are rejected before identity handling.",
            ),
            (
                _case(
                    [candidate("c_block_internal", "Internal Control")],
                    [source_concept("kos_internal", "Internal Control", audience="internal")],
                    audiences={"c_block_internal": "public"},
                ),
                _expected(["reject"], blocked=True, required_signals=["audience_acl_mismatch"]),
                "Held-out ACL mismatch verifies fail-closed behavior.",
            ),
        ],
    }


def build_provisional_suite(annotation_policy_sha256: str) -> dict[str, Any]:
    if len(annotation_policy_sha256) != 64:
        raise IntegrityError("M25-GOLD-101 invalid annotation policy digest")
    templates = _templates()
    if set(templates) != set(CLASS_LABELS):
        raise IntegrityError("M25-GOLD-102 class taxonomy drift")
    items: list[dict[str, Any]] = []
    for class_label in CLASS_LABELS:
        rows = templates[class_label]
        if len(rows) != len(SPLITS):
            raise IntegrityError("M25-GOLD-103 split coverage drift")
        for split, (case, expected, rationale) in zip(SPLITS, rows, strict=True):
            item_id = f"gold_{split}_{class_label}"
            family_id = f"family_{digest(item_id)[:20]}"
            evidence_sha = digest(case)
            item = {
                "schema_version": ITEM_SCHEMA,
                "item_id": item_id,
                "semantic_family_id": family_id,
                "class_label": class_label,
                "split": split,
                "annotation_status": "provisional_pending_daniel",
                "annotation_policy_sha256": annotation_policy_sha256,
                "evidence": {
                    "uri": f"benchmark://m25-4/{item_id}",
                    "sha256": evidence_sha,
                    "evidence_bound": True,
                },
                "rationale": rationale,
                "case": case,
                "expected": expected,
                "candidate_only": True,
                "canonical_knowledge": False,
                "production_authority": False,
            }
            item["item_sha256"] = digest(item)
            items.append(item)
    suite = {
        "schema_version": SCHEMA,
        "suite_id": "m25-concept-identity-gold-v1",
        "suite_revision": "provisional-1",
        "engine_base_sha": ENGINE_BASE_SHA,
        "predecessor_status": PREDECESSOR_STATUS,
        "resolver_module": "knowledge_engine.m21_entity_resolution",
        "resolver_source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
        "annotation_policy_sha256": annotation_policy_sha256,
        "annotation_authority": "daniel",
        "approval_status": "pending_daniel",
        "class_labels": list(CLASS_LABELS),
        "splits": list(SPLITS),
        "item_count": len(items),
        "items": sorted(items, key=lambda item: item["item_id"]),
        "candidate_only": True,
        "canonical_knowledge": False,
        "production_authority": False,
    }
    suite["suite_sha256"] = digest(suite)
    return suite


def build_split_manifest(suite: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_suite(suite, require_approval=False)
    assignments = [
        {
            "item_id": item["item_id"],
            "semantic_family_id": item["semantic_family_id"],
            "class_label": item["class_label"],
            "split": item["split"],
            "item_sha256": item["item_sha256"],
        }
        for item in validated["items"]
    ]
    manifest = {
        "schema_version": SPLIT_SCHEMA,
        "suite_id": validated["suite_id"],
        "suite_sha256": validated["suite_sha256"],
        "split_policy": "one unique semantic family in exactly one immutable split",
        "final_split_calibration_permitted": False,
        "assignments": assignments,
    }
    manifest["manifest_sha256"] = digest(manifest)
    return manifest


def build_adjudication_ledger(suite: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_suite(suite, require_approval=False)
    ledger = {
        "schema_version": LEDGER_SCHEMA,
        "suite_id": validated["suite_id"],
        "suite_sha256": validated["suite_sha256"],
        "policy_status": "pending_daniel",
        "label_decision_status": "pending_daniel",
        "disputed_item_count": 0,
        "disputed_items": [],
        "silent_label_changes_permitted": False,
        "decision_required": {
            "approve_annotation_policy": True,
            "approve_all_provisional_labels": True,
            "decide_disputed_labels": False,
        },
        "decision": None,
    }
    ledger["ledger_sha256"] = digest(ledger)
    return ledger


def _verify_signed(value: Mapping[str, Any], field: str, code: str) -> None:
    unsigned = dict(value)
    claimed = unsigned.pop(field, None)
    if not isinstance(claimed, str) or claimed != digest(unsigned):
        raise IntegrityError(code)


def validate_suite(
    suite: Mapping[str, Any], *, require_approval: bool = False
) -> dict[str, Any]:
    if not isinstance(suite, Mapping) or suite.get("schema_version") != SCHEMA:
        raise IntegrityError("M25-GOLD-104 invalid suite schema")
    _verify_signed(suite, "suite_sha256", "M25-GOLD-105 suite digest mismatch")
    if suite.get("engine_base_sha") != ENGINE_BASE_SHA:
        raise IntegrityError("M25-GOLD-106 Engine baseline drift")
    if suite.get("predecessor_status") != PREDECESSOR_STATUS:
        raise IntegrityError("M25-GOLD-107 predecessor drift")
    if suite.get("resolver_source_sha") != SOURCE_SHA or suite.get("foundation_sha") != FOUNDATION_SHA:
        raise IntegrityError("M25-GOLD-108 resolver identity drift")
    if tuple(suite.get("class_labels", [])) != CLASS_LABELS:
        raise IntegrityError("M25-GOLD-109 class taxonomy drift")
    if tuple(suite.get("splits", [])) != SPLITS:
        raise IntegrityError("M25-GOLD-110 split taxonomy drift")
    items = suite.get("items")
    if not isinstance(items, list) or suite.get("item_count") != len(items) or len(items) != 30:
        raise IntegrityError("M25-GOLD-111 item denominator drift")
    if require_approval and suite.get("approval_status") != "approved_by_daniel":
        raise IntegrityError("M25-GOLD-112 Daniel approval required")
    expected_status = "approved" if require_approval else None
    item_ids: set[str] = set()
    families: set[str] = set()
    case_digests: set[str] = set()
    coverage: Counter[tuple[str, str]] = Counter()
    for item in items:
        if not isinstance(item, Mapping) or item.get("schema_version") != ITEM_SCHEMA:
            raise IntegrityError("M25-GOLD-113 invalid gold item")
        _verify_signed(item, "item_sha256", "M25-GOLD-114 item digest mismatch")
        item_id = item.get("item_id")
        family = item.get("semantic_family_id")
        if not isinstance(item_id, str) or item_id in item_ids:
            raise IntegrityError("M25-GOLD-115 duplicate item id")
        if not isinstance(family, str) or family in families:
            raise IntegrityError("M25-GOLD-116 semantic-family leakage")
        item_ids.add(item_id)
        families.add(family)
        class_label = item.get("class_label")
        split = item.get("split")
        if class_label not in CLASS_LABELS or split not in SPLITS:
            raise IntegrityError("M25-GOLD-117 invalid class or split")
        coverage[(class_label, split)] += 1
        if expected_status is not None and item.get("annotation_status") != expected_status:
            raise IntegrityError("M25-GOLD-118 unapproved label")
        if item.get("annotation_policy_sha256") != suite.get("annotation_policy_sha256"):
            raise IntegrityError("M25-GOLD-119 policy binding drift")
        evidence_value = item.get("evidence")
        if not isinstance(evidence_value, Mapping) or evidence_value.get("evidence_bound") is not True:
            raise IntegrityError("M25-GOLD-120 evidence missing")
        case = item.get("case")
        case_sha = digest(case)
        if evidence_value.get("sha256") != case_sha or case_sha in case_digests:
            raise IntegrityError("M25-GOLD-121 evidence digest or duplicate-case drift")
        case_digests.add(case_sha)
        if (
            item.get("candidate_only") is not True
            or item.get("canonical_knowledge") is not False
            or item.get("production_authority") is not False
        ):
            raise IntegrityError("M25-GOLD-122 authority drift")
    if set(coverage) != {(label, split) for label in CLASS_LABELS for split in SPLITS}:
        raise IntegrityError("M25-GOLD-123 class/split coverage drift")
    if any(count != 1 for count in coverage.values()):
        raise IntegrityError("M25-GOLD-124 non-uniform class/split denominator")
    return deepcopy(dict(suite))


def run_case(case: Mapping[str, Any]) -> dict[str, Any]:
    candidates = deepcopy(case["candidates"])
    concepts = deepcopy(case["source_concepts"])
    extract = extraction(candidates)
    governed_packet = governed(extract, deepcopy(case.get("governed_tags", [])))
    return build_resolution_candidate_packet(
        extract,
        governed_packet,
        source_index(concepts),
        candidate_audiences=deepcopy(case["candidate_audiences"]),
        claim_assertions=deepcopy(case.get("claim_assertions", [])),
    )


def _wilson(successes: int, total: int, z: float = 1.959964) -> dict[str, float]:
    if total <= 0:
        return {"lower": 0.0, "upper": 0.0}
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return {
        "lower": round(max(0.0, (centre - margin) / denominator), 6),
        "upper": round(min(1.0, (centre + margin) / denominator), 6),
    }


def _actual_signals(packet: Mapping[str, Any]) -> set[str]:
    signals: set[str] = set()
    for resolution in packet.get("resolutions", []):
        signals.update(resolution.get("strong_signals", []))
        signals.update(resolution.get("weak_signals", []))
    if packet.get("contradictions"):
        signals.add("contradiction_candidate")
    return signals


def run_benchmark(suite: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_suite(suite, require_approval=False)
    results: list[dict[str, Any]] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    class_totals: Counter[str] = Counter()
    class_decision_pass: Counter[str] = Counter()
    split_totals: Counter[str] = Counter()
    split_decision_pass: Counter[str] = Counter()
    for item in validated["items"]:
        packet = run_case(item["case"])
        actual_outcomes = sorted(item["outcome"] for item in packet["resolutions"])
        expected = item["expected"]
        actual_signals = _actual_signals(packet)
        required_signals = set(expected["required_explanation_signals"])
        decision_pass = actual_outcomes == expected["resolution_outcomes"]
        contradiction_pass = packet["contradiction_count"] == expected["contradiction_count"]
        blocking_pass = packet["packaging_blocked"] is expected["packaging_blocked"]
        explanation_pass = required_signals <= actual_signals
        no_false_merge = not (
            item["class_label"] in DISTINCT_CLASSES
            and bool(set(actual_outcomes) & MERGE_OUTCOMES)
        )
        semantic_pass = decision_pass and contradiction_pass and blocking_pass and no_false_merge
        primary_actual = (
            "contradiction_candidate"
            if packet["contradiction_count"]
            else (actual_outcomes[0] if len(actual_outcomes) == 1 else "+".join(actual_outcomes))
        )
        confusion[item["class_label"]][primary_actual or "none"] += 1
        class_totals[item["class_label"]] += 1
        split_totals[item["split"]] += 1
        if semantic_pass:
            class_decision_pass[item["class_label"]] += 1
            split_decision_pass[item["split"]] += 1
        missing_signals = sorted(required_signals - actual_signals)
        error_codes = []
        if not decision_pass:
            error_codes.append("decision_mismatch")
        if not contradiction_pass:
            error_codes.append("contradiction_mismatch")
        if not blocking_pass:
            error_codes.append("blocking_mismatch")
        if not no_false_merge:
            error_codes.append("false_identity_merge")
        if missing_signals:
            error_codes.append("explanation_signal_gap")
        results.append(
            {
                "item_id": item["item_id"],
                "class_label": item["class_label"],
                "split": item["split"],
                "expected_resolution_outcomes": expected["resolution_outcomes"],
                "actual_resolution_outcomes": actual_outcomes,
                "expected_contradiction_count": expected["contradiction_count"],
                "actual_contradiction_count": packet["contradiction_count"],
                "expected_packaging_blocked": expected["packaging_blocked"],
                "actual_packaging_blocked": packet["packaging_blocked"],
                "required_explanation_signals": sorted(required_signals),
                "actual_explanation_signals": sorted(actual_signals),
                "missing_explanation_signals": missing_signals,
                "semantic_pass": semantic_pass,
                "explanation_pass": explanation_pass,
                "no_false_merge": no_false_merge,
                "error_codes": error_codes,
                "resolution_packet_sha256": packet["packet_sha256"],
            }
        )
    total = len(results)
    semantic_successes = sum(item["semantic_pass"] for item in results)
    explanation_successes = sum(item["explanation_pass"] for item in results)
    false_merge_count = sum(not item["no_false_merge"] for item in results)
    report = {
        "schema_version": REPORT_SCHEMA,
        "suite_id": validated["suite_id"],
        "suite_sha256": validated["suite_sha256"],
        "suite_approval_status": validated["approval_status"],
        "baseline_status": "provisional_pending_daniel",
        "resolver_module": validated["resolver_module"],
        "resolver_source_sha": validated["resolver_source_sha"],
        "resolver_threshold_or_code_changed": False,
        "final_split_used_for_calibration": False,
        "denominators": {
            "total": total,
            "by_class": dict(sorted(class_totals.items())),
            "by_split": dict(sorted(split_totals.items())),
        },
        "metrics": {
            "semantic_decision_accuracy": round(semantic_successes / total, 6),
            "semantic_decision_accuracy_ci95": _wilson(semantic_successes, total),
            "explanation_signal_coverage": round(explanation_successes / total, 6),
            "explanation_signal_coverage_ci95": _wilson(explanation_successes, total),
            "false_merge_count": false_merge_count,
            "false_merge_rate": round(false_merge_count / total, 6),
            "per_class_semantic_accuracy": {
                label: round(class_decision_pass[label] / class_totals[label], 6)
                for label in CLASS_LABELS
            },
            "per_split_semantic_accuracy": {
                split: round(split_decision_pass[split] / split_totals[split], 6)
                for split in SPLITS
            },
        },
        "confusion_matrix": {
            label: dict(sorted(confusion[label].items())) for label in CLASS_LABELS
        },
        "error_taxonomy": {
            code: sum(code in result["error_codes"] for result in results)
            for code in (
                "decision_mismatch",
                "contradiction_mismatch",
                "blocking_mismatch",
                "false_identity_merge",
                "explanation_signal_gap",
            )
        },
        "results": sorted(results, key=lambda item: item["item_id"]),
        "candidate_only": True,
        "canonical_knowledge": False,
        "production_authority": False,
        "m25_5_authorized": False,
    }
    report["report_sha256"] = digest(report)
    return report


__all__ = [
    "CLASS_LABELS",
    "ENGINE_BASE_SHA",
    "PREDECESSOR_STATUS",
    "SPLITS",
    "build_adjudication_ledger",
    "build_provisional_suite",
    "build_split_manifest",
    "canonical_bytes",
    "digest",
    "run_benchmark",
    "run_case",
    "validate_suite",
]
