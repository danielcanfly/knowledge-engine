from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class M25FormalClosureError(ValueError):
    pass


EXPECTED_STATUS = "m25_closed"
EXPECTED_RELEASE_ID = "m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043"
EXPECTED_PRODUCTION_POINTER_SHA256 = (
    "4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9"
)
EXPECTED_PRODUCTION_MANIFEST_SHA256 = (
    "72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b"
)
EXPECTED_PROMOTION_RUN = 30115946458
EXPECTED_LATEST_MAIN = "e88b50cb8f0084a6ec1ea1d9aadc9af7bce54bf6"
EXPECTED_OWNER_OUTCOME = "approved_bounded_large_scale_ingestion"
EXPECTED_OWNER_DECISION_TIME = "2026-07-27T03:36:26Z"
EXPECTED_OWNER_DECISION_PATH = "pilot/m25/m25-10-owner-decision.json"
EXPECTED_FINAL_ACCEPTANCE_PATH = "pilot/m25/m25-10-final-acceptance.json"
VALID_OUTCOMES = {
    "approved_bounded_large_scale_ingestion",
    "approved_with_conditions",
    "governed_defer",
    "rejected_pending_redesign",
}
PROTECTED_MUTATIONS = {
    "access",
    "answer_serving",
    "credentials",
    "dns",
    "foundation",
    "pages",
    "production_pointer",
    "public_traffic",
    "qdrant",
    "r2_production",
    "semantic_or_hybrid_serving",
    "source",
    "workers",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def self_digest(value: dict[str, Any]) -> str:
    candidate = dict(value)
    candidate["self_sha256"] = ""
    return hashlib.sha256(canonical_json(candidate).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise M25FormalClosureError(f"{path} must contain a JSON object")
    return value


def validate_closure_evidence(path: Path) -> dict[str, Any]:
    evidence = load_json(path)
    if evidence.get("schema_version") != (
        "knowledge-engine-m25-10-formal-closure-evidence/v1"
    ):
        raise M25FormalClosureError("schema version mismatch")
    if evidence.get("status") != EXPECTED_STATUS:
        raise M25FormalClosureError("closure evidence status mismatch")
    if evidence.get("self_sha256") != self_digest(evidence):
        raise M25FormalClosureError("self digest mismatch")

    owner_decision = evidence.get("owner_decision")
    if not isinstance(owner_decision, dict):
        raise M25FormalClosureError("owner decision missing")
    if owner_decision.get("path") != EXPECTED_OWNER_DECISION_PATH:
        raise M25FormalClosureError("owner decision path mismatch")
    if owner_decision.get("outcome") != EXPECTED_OWNER_OUTCOME:
        raise M25FormalClosureError("owner decision outcome mismatch")
    if owner_decision.get("decided_at_utc") != EXPECTED_OWNER_DECISION_TIME:
        raise M25FormalClosureError("owner decision timestamp mismatch")

    final_acceptance = evidence.get("final_acceptance")
    if not isinstance(final_acceptance, dict):
        raise M25FormalClosureError("final acceptance missing")
    if final_acceptance.get("path") != EXPECTED_FINAL_ACCEPTANCE_PATH:
        raise M25FormalClosureError("final acceptance path mismatch")
    if final_acceptance.get("status") != "m25_closed":
        raise M25FormalClosureError("final acceptance status mismatch")

    identities = evidence.get("production_identities")
    if not isinstance(identities, dict):
        raise M25FormalClosureError("production identities missing")
    expected_identities = {
        "release_id": EXPECTED_RELEASE_ID,
        "production_pointer_sha256": EXPECTED_PRODUCTION_POINTER_SHA256,
        "production_manifest_sha256": EXPECTED_PRODUCTION_MANIFEST_SHA256,
        "promotion_workflow_run": EXPECTED_PROMOTION_RUN,
        "qdrant_filtered_points": 4197,
    }
    for key, expected in expected_identities.items():
        if identities.get(key) != expected:
            raise M25FormalClosureError(f"production identity drift: {key}")

    protected = evidence.get("protected_mutations")
    if not isinstance(protected, dict) or set(protected) != PROTECTED_MUTATIONS:
        raise M25FormalClosureError("protected mutation surface mismatch")
    if any(value is not False for value in protected.values()):
        raise M25FormalClosureError("protected mutation escalation detected")

    chain = evidence.get("evidence_chain")
    if not isinstance(chain, list) or len(chain) != 10:
        raise M25FormalClosureError("M25 evidence chain denominator mismatch")
    stages = {row.get("stage") for row in chain}
    if stages != {f"M25.{index}" for index in range(1, 11)}:
        raise M25FormalClosureError("M25 stage set mismatch")
    if chain[-1].get("status") != "production_pointer_promoted":
        raise M25FormalClosureError("M25.10 promotion status missing")

    denominator = evidence.get("denominator_accounting", {}).get(
        "admitted_blog_corpus"
    )
    if not isinstance(denominator, dict):
        raise M25FormalClosureError("denominator accounting missing")
    expected_denominator = {
        "documents": 156,
        "articles": 156,
        "series_or_collections": 25,
        "section_nodes": 4041,
        "graph_nodes": 4222,
        "graph_edges": 8525,
        "semantic_documents": 4197,
    }
    for key, expected in expected_denominator.items():
        if denominator.get(key) != expected:
            raise M25FormalClosureError(f"denominator drift: {key}")
    if evidence["denominator_accounting"].get("unaccounted_sources") != 0:
        raise M25FormalClosureError("unaccounted sources must remain zero")

    decision_gate = evidence.get("decision_gate")
    if not isinstance(decision_gate, dict):
        raise M25FormalClosureError("decision gate missing")
    if decision_gate.get("decision_required") is not False:
        raise M25FormalClosureError("owner decision should be resolved")
    if decision_gate.get("selected_outcome") != EXPECTED_OWNER_OUTCOME:
        raise M25FormalClosureError("selected outcome mismatch")
    if set(decision_gate.get("valid_outcomes", [])) != VALID_OUTCOMES:
        raise M25FormalClosureError("valid owner outcomes mismatch")

    m26 = evidence.get("m26_forward_state")
    if not isinstance(m26, dict):
        raise M25FormalClosureError("M26 forward state missing")
    if m26.get("current_main_sha") != EXPECTED_LATEST_MAIN:
        raise M25FormalClosureError("latest main baseline drift")
    if "still denies live provider calls" not in m26.get("m26_caveat", ""):
        raise M25FormalClosureError("M26 caveat missing")

    return {
        "status": "m25_formal_closure_evidence_valid",
        "release_id": identities["release_id"],
        "stage_count": len(chain),
        "protected_mutation_count": len(protected),
        "decision_required": False,
    }


def validate_repository(root: Path) -> dict[str, Any]:
    return validate_closure_evidence(
        root / "pilot" / "m25" / "m25-10-formal-closure-evidence.json"
    )
