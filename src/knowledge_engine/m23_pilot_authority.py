from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-pilot-authority/v1"
ACCEPTANCE_SCHEMA_VERSION = "knowledge-engine-m23-pilot-authority-acceptance/v1"
ENGINE_SHA = "e6557ff8b3f6eb8ce7cd206df5bf0a4794ae34fb"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"
SOURCE_PR_HEAD_SHA = "deb3ad1e631c2149183d10561fbceb0a1848a989"
EVIDENCE_ZIP_SHA256 = "1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272"
SEMANTIC_ARTIFACT_ID = "semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d"
QDRANT_COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
QDRANT_VECTOR_NAME = "default"
QDRANT_DIMENSION = 1024
QDRANT_DISTANCE = "Cosine"
EMBEDDING_PROVIDER = "cloudflare-workers-ai"
EMBEDDING_MODEL = "@cf/baai/bge-m3"
UNRELATED_COLLECTION = "llamaindex_demo_hybrid"
SOURCE_ADOPTION_LANE = "evaluation-only-pending-proposal"
PRODUCTION_RELEASE_ID = "20260708T040116Z-69a9f445699a"
PRODUCTION_MANIFEST_SHA256 = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
PRODUCTION_POINTER_SHA256 = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"

REQUIRED_CANDIDATE_IDENTITY_FIELDS = (
    "engine_commit_sha",
    "source_commit_sha",
    "foundation_commit_sha",
    "source_adoption_lane",
    "source_bundle_sha256",
    "lexical_index_sha256",
    "provenance_sha256",
    "graph_v2_sha256",
    "semantic_manifest_sha256",
    "semantic_vectors_sha256",
    "embedding_provider",
    "embedding_model",
    "vector_dimension",
    "qdrant_collection",
    "qdrant_manifest_sha256",
    "authority_profile",
)

REQUIRED_QDRANT_PAYLOAD_FIELDS = (
    "payload_schema_version",
    "section_id",
    "article_id",
    "document_id",
    "concept_id",
    "source_path",
    "source_sha256",
    "text_sha256",
    "audience",
    "source_membership",
    "release_id",
    "release_manifest_sha256",
    "graph_node_id",
    "embedding_provider",
    "embedding_model",
    "vector_dimension",
    "vector_name",
    "canonical_knowledge",
    "candidate_release_eligible",
    "production_authority",
)

FORBIDDEN_SERIALIZED_TERMS = (
    "api_key",
    "authorization_header",
    "bearer_token",
    "client_secret",
    "private_key",
    "production_write",
    'graph_neural_retrieval_enabled":true',
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fail(code: str, message: str) -> None:
    raise IntegrityError(f"M23-AUTH-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("101", f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        _fail("102", f"{label} must be an array")
    return value


def _expect(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        _fail("103", f"{label} must equal {expected!r}")


def _expect_false(mapping: Mapping[str, Any], keys: Sequence[str], label: str) -> None:
    for key in keys:
        if mapping.get(key) is not False:
            _fail("104", f"{label}.{key} must be false")


def _digest_without_self(contract: Mapping[str, Any]) -> str:
    unsigned = dict(contract)
    unsigned.pop("contract_sha256", None)
    return canonical_sha256(unsigned)


def validate_authority_contract(raw_contract: Mapping[str, Any]) -> dict[str, Any]:
    contract = dict(_mapping(raw_contract, "contract"))
    _expect(contract.get("schema_version"), SCHEMA_VERSION, "schema_version")
    _expect(contract.get("milestone"), "M23.6.1", "milestone")

    identities = _mapping(contract.get("identities"), "identities")
    _expect(identities.get("engine_commit_sha"), ENGINE_SHA, "identities.engine_commit_sha")
    _expect(identities.get("source_commit_sha"), SOURCE_SHA, "identities.source_commit_sha")
    _expect(
        identities.get("foundation_commit_sha"),
        FOUNDATION_SHA,
        "identities.foundation_commit_sha",
    )
    _expect(
        identities.get("m23_5_evidence_zip_sha256"),
        EVIDENCE_ZIP_SHA256,
        "identities.m23_5_evidence_zip_sha256",
    )
    _expect(
        identities.get("m23_5_semantic_artifact_id"),
        SEMANTIC_ARTIFACT_ID,
        "identities.m23_5_semantic_artifact_id",
    )

    production = _mapping(contract.get("production_snapshot"), "production_snapshot")
    _expect(
        production.get("capture_mode"),
        "accepted-read-only-snapshot-plus-nonmutating-ci",
        "production_snapshot.capture_mode",
    )
    _expect(production.get("release_id"), PRODUCTION_RELEASE_ID, "production_snapshot.release_id")
    _expect(
        production.get("release_manifest_sha256"),
        PRODUCTION_MANIFEST_SHA256,
        "production_snapshot.release_manifest_sha256",
    )
    _expect(
        production.get("pointer_sha256"),
        PRODUCTION_POINTER_SHA256,
        "production_snapshot.pointer_sha256",
    )
    _expect(production.get("source_pr"), 248, "production_snapshot.source_pr")
    _expect(
        production.get("r2_validation_run_id"),
        29352865671,
        "production_snapshot.r2_validation_run_id",
    )
    _expect(
        production.get("r2_validation_conclusion"),
        "success",
        "production_snapshot.r2_validation_conclusion",
    )
    _expect(
        production.get("remote_mutation_dispatched"),
        False,
        "production_snapshot.remote_mutation_dispatched",
    )
    _expect(
        production.get("refresh_required_before_promotion"),
        True,
        "production_snapshot.refresh_required_before_promotion",
    )

    source_lane = _mapping(contract.get("source_adoption"), "source_adoption")
    _expect(source_lane.get("lane"), SOURCE_ADOPTION_LANE, "source_adoption.lane")
    _expect(source_lane.get("source_pr_number"), 19, "source_adoption.source_pr_number")
    _expect(
        source_lane.get("source_pr_head_sha"),
        SOURCE_PR_HEAD_SHA,
        "source_adoption.source_pr_head_sha",
    )
    _expect(
        source_lane.get("source_pr_state"), "draft-open-unmerged", "source_adoption.source_pr_state"
    )
    _expect(
        source_lane.get("canonical_source_sha"), SOURCE_SHA, "source_adoption.canonical_source_sha"
    )
    _expect(
        source_lane.get("pending_proposal_point_count"),
        107,
        "source_adoption.pending_proposal_point_count",
    )
    _expect(
        source_lane.get("candidate_requires_canonical_rebuild"),
        True,
        "source_adoption.candidate_requires_canonical_rebuild",
    )
    _expect(
        source_lane.get("adoption_invalidates_derived_identity"),
        True,
        "source_adoption.adoption_invalidates_derived_identity",
    )
    _expect_false(
        source_lane,
        (
            "source_merge_authorized",
            "pending_canonical_knowledge",
            "pending_candidate_release_eligible",
            "pending_production_authority",
        ),
        "source_adoption",
    )

    candidate = _mapping(contract.get("candidate_identity_contract"), "candidate_identity_contract")
    _expect(
        candidate.get("schema_version"),
        "knowledge-engine-m23-candidate-identity/v1",
        "candidate_identity_contract.schema_version",
    )
    _expect(
        tuple(
            _sequence(
                candidate.get("required_fields"), "candidate_identity_contract.required_fields"
            )
        ),
        REQUIRED_CANDIDATE_IDENTITY_FIELDS,
        "candidate_identity_contract.required_fields",
    )
    _expect(candidate.get("id_prefix"), "m23cand-", "candidate_identity_contract.id_prefix")
    _expect(
        candidate.get("id_digest_hex_length"),
        24,
        "candidate_identity_contract.id_digest_hex_length",
    )
    _expect(candidate.get("canonical_json"), True, "candidate_identity_contract.canonical_json")
    _expect(
        candidate.get("identity_complete_before_publish"),
        True,
        "candidate_identity_contract.identity_complete_before_publish",
    )
    _expect(
        candidate.get("cross_release_merge_allowed"),
        False,
        "candidate_identity_contract.cross_release_merge_allowed",
    )

    qdrant = _mapping(contract.get("qdrant"), "qdrant")
    _expect(qdrant.get("collection"), QDRANT_COLLECTION, "qdrant.collection")
    _expect(qdrant.get("vector_name"), QDRANT_VECTOR_NAME, "qdrant.vector_name")
    _expect(qdrant.get("dimension"), QDRANT_DIMENSION, "qdrant.dimension")
    _expect(qdrant.get("distance"), QDRANT_DISTANCE, "qdrant.distance")
    _expect(qdrant.get("embedding_provider"), EMBEDDING_PROVIDER, "qdrant.embedding_provider")
    _expect(qdrant.get("embedding_model"), EMBEDDING_MODEL, "qdrant.embedding_model")
    _expect(qdrant.get("blocked_collection"), UNRELATED_COLLECTION, "qdrant.blocked_collection")
    _expect(
        tuple(_sequence(qdrant.get("payload_fields"), "qdrant.payload_fields")),
        REQUIRED_QDRANT_PAYLOAD_FIELDS,
        "qdrant.payload_fields",
    )
    _expect(
        qdrant.get("first_write_requires_empty_collection"),
        True,
        "qdrant.first_write_requires_empty_collection",
    )
    _expect(qdrant.get("write_default"), "deny", "qdrant.write_default")
    _expect(qdrant.get("first_write_authorized"), False, "qdrant.first_write_authorized")
    _expect(qdrant.get("delete_authorized"), False, "qdrant.delete_authorized")

    r2 = _mapping(contract.get("candidate_r2"), "candidate_r2")
    _expect(
        r2.get("namespace_template"),
        "candidates/m23/{candidate_release_id}/",
        "candidate_r2.namespace_template",
    )
    _expect(
        r2.get("production_namespace_allowed"), False, "candidate_r2.production_namespace_allowed"
    )
    _expect(r2.get("automatic_delete"), False, "candidate_r2.automatic_delete")
    _expect(r2.get("retain_through_m23_7"), True, "candidate_r2.retain_through_m23_7")
    _expect(
        r2.get("cleanup_review_days_after_m23_7"),
        30,
        "candidate_r2.cleanup_review_days_after_m23_7",
    )
    _expect(
        r2.get("physical_delete_requires_separate_authority"),
        True,
        "candidate_r2.physical_delete_requires_separate_authority",
    )

    worker = _mapping(contract.get("worker_queue"), "worker_queue")
    _expect(
        worker.get("worker_name"), "llm-wiki-m23-pilot-embed-consumer", "worker_queue.worker_name"
    )
    _expect(worker.get("queue_name"), "llm-wiki-m23-pilot-embed", "worker_queue.queue_name")
    _expect(
        worker.get("dead_letter_queue_name"),
        "llm-wiki-m23-pilot-embed-dlq",
        "worker_queue.dead_letter_queue_name",
    )
    _expect(worker.get("max_delivery_attempts"), 3, "worker_queue.max_delivery_attempts")
    _expect(worker.get("max_batch_messages"), 4, "worker_queue.max_batch_messages")
    _expect(worker.get("max_sections_per_message"), 25, "worker_queue.max_sections_per_message")
    _expect(worker.get("max_concurrency"), 2, "worker_queue.max_concurrency")
    _expect(worker.get("max_sections_per_run"), 500, "worker_queue.max_sections_per_run")
    _expect(worker.get("max_sections_per_day"), 2000, "worker_queue.max_sections_per_day")
    _expect(worker.get("max_estimated_usd_per_run"), 0.5, "worker_queue.max_estimated_usd_per_run")
    _expect(worker.get("max_estimated_usd_per_day"), 2.0, "worker_queue.max_estimated_usd_per_day")
    _expect(worker.get("price_estimate_required"), True, "worker_queue.price_estimate_required")
    _expect(worker.get("deployment_authorized"), False, "worker_queue.deployment_authorized")

    answer = _mapping(contract.get("candidate_answer_provider"), "candidate_answer_provider")
    _expect(answer.get("state"), "disabled-until-m23.7.4", "candidate_answer_provider.state")
    _expect(answer.get("provider_selected"), False, "candidate_answer_provider.provider_selected")
    _expect(answer.get("max_attempts"), 2, "candidate_answer_provider.max_attempts")
    _expect(answer.get("max_input_tokens"), 4000, "candidate_answer_provider.max_input_tokens")
    _expect(answer.get("max_output_tokens"), 800, "candidate_answer_provider.max_output_tokens")
    _expect(
        answer.get("max_estimated_usd_per_query"),
        0.05,
        "candidate_answer_provider.max_estimated_usd_per_query",
    )
    _expect(
        answer.get("max_estimated_usd_per_day"),
        5.0,
        "candidate_answer_provider.max_estimated_usd_per_day",
    )
    _expect(
        answer.get("production_answer_authority"),
        False,
        "candidate_answer_provider.production_answer_authority",
    )

    runtime = _mapping(contract.get("candidate_runtime"), "candidate_runtime")
    _expect(runtime.get("base_path"), "/internal/candidate/m23", "candidate_runtime.base_path")
    _expect(
        runtime.get("retrieval_path"),
        "/internal/candidate/m23/retrieve",
        "candidate_runtime.retrieval_path",
    )
    _expect(
        runtime.get("graph_path"),
        "/internal/candidate/m23/graph/neighborhood",
        "candidate_runtime.graph_path",
    )
    _expect(
        runtime.get("authentication"),
        "cloudflare-access-jwt-fixed-audience",
        "candidate_runtime.authentication",
    )
    _expect(runtime.get("public_route_allowed"), False, "candidate_runtime.public_route_allowed")
    _expect(runtime.get("read_only"), True, "candidate_runtime.read_only")
    _expect(
        runtime.get("planner_multi_hop_allowed"),
        False,
        "candidate_runtime.planner_multi_hop_allowed",
    )
    _expect(runtime.get("single_hop_max"), 1, "candidate_runtime.single_hop_max")

    explorer = _mapping(contract.get("graph_explorer"), "graph_explorer")
    _expect(
        explorer.get("source_package"), "packages/graph-explorer", "graph_explorer.source_package"
    )
    _expect(explorer.get("renderer"), "sigma@3.0.3", "graph_explorer.renderer")
    _expect(
        explorer.get("deployment"), "cloudflare-pages-internal-preview", "graph_explorer.deployment"
    )
    _expect(
        explorer.get("authentication"),
        "cloudflare-access-jwt-fixed-audience",
        "graph_explorer.authentication",
    )
    _expect(explorer.get("feature_flag"), "GRAPH_EXPLORER_ENABLED", "graph_explorer.feature_flag")
    _expect(explorer.get("feature_flag_default"), False, "graph_explorer.feature_flag_default")
    _expect(explorer.get("public_route_allowed"), False, "graph_explorer.public_route_allowed")
    _expect(explorer.get("editing_allowed"), False, "graph_explorer.editing_allowed")

    defaults = _mapping(contract.get("locked_defaults"), "locked_defaults")
    _expect(defaults.get("RETRIEVAL_MODE"), "lexical", "locked_defaults.RETRIEVAL_MODE")
    _expect(defaults.get("GRAPH_EXPLORER_ENABLED"), False, "locked_defaults.GRAPH_EXPLORER_ENABLED")
    _expect(
        defaults.get("AUTO_EXTRACTION_ENABLED"), False, "locked_defaults.AUTO_EXTRACTION_ENABLED"
    )
    _expect(defaults.get("MULTIHOP_MODE"), "off", "locked_defaults.MULTIHOP_MODE")
    _expect(
        defaults.get("GRAPH_NEURAL_RETRIEVAL_ENABLED"),
        False,
        "locked_defaults.GRAPH_NEURAL_RETRIEVAL_ENABLED",
    )

    authority = _mapping(contract.get("authority"), "authority")
    _expect_false(
        authority,
        (
            "qdrant_write",
            "r2_mutation",
            "pointer_mutation",
            "source_mutation",
            "source_pr_19_merge",
            "production_traffic_change",
            "public_graph_explorer",
            "permanent_ledger_mutation",
            "graph_neural_retrieval",
            "physical_delete",
            "credential_rotation",
            "production_mutation_dispatched",
        ),
        "authority",
    )

    serialized = canonical_json(contract).lower()
    for term in FORBIDDEN_SERIALIZED_TERMS:
        if term in serialized:
            _fail("105", f"forbidden serialized term: {term}")

    declared_digest = contract.get("contract_sha256")
    expected_digest = _digest_without_self(contract)
    _expect(declared_digest, expected_digest, "contract_sha256")
    return contract


def load_authority_contract(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("106", f"unable to read contract: {exc.__class__.__name__}")
    return validate_authority_contract(_mapping(raw, "contract"))


def build_acceptance_report(contract: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_authority_contract(contract)
    report = {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "milestone": "M23.6.1",
        "contract_sha256": validated["contract_sha256"],
        "checks": [
            "exact-baseline-identities",
            "read-only-production-snapshot",
            "source-pr-19-evaluation-only-lane",
            "candidate-identity-schema",
            "qdrant-named-vector-and-payload",
            "candidate-r2-namespace-and-retention",
            "worker-queue-cost-and-retry-ceilings",
            "answer-provider-disabled-ceilings",
            "candidate-runtime-internal-auth",
            "graph-explorer-internal-readonly",
            "lexical-default-and-forbidden-mode-guards",
            "all-mutation-authority-false",
        ],
        "decision": "accepted-for-m23.6.2-contract-work",
        "qdrant_write_authorized": False,
        "production_mutation_dispatched": False,
        "next_legal_action": "M23.6.2 deterministic Qdrant ingestion manifest",
    }
    report["report_sha256"] = canonical_sha256(report)
    return report
