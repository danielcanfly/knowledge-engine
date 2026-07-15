from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

SCHEMA_VERSION = "knowledge-engine-m23-7-r1-semantic-alignment/v1"
REPORT_SCHEMA_VERSION = (
    "knowledge-engine-m23-7-r1-semantic-alignment-report/v1"
)
ENTRY_ENGINE_SHA = "1c34c3b6a05b4aeca956f8f008a88f434c93e7d7"
SOURCE_PR_HEAD = "deb3ad1e631c2149183d10561fbceb0a1848a989"
DECISION_PACKET_SHA256 = (
    "89e5f6c8e748e089d0360ffc6a440b91bbb85a157397c1e6a9aa706f26a10f18"
)
DECISION_REPORT_SHA256 = (
    "b8d4278dec2c777a2ed3c888ff20f8e5d4e5a80315dc8b15179f4e63045fe92f"
)
REPAIR_HANDOFF_SHA256 = (
    "7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9"
)
QUALITY_CONTRACT_SHA256 = (
    "7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1"
)
OFFLINE_EVALUATION_SHA256 = (
    "9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce"
)
QDRANT_RELEASE = "m23pilot-a07eb79e381ca7e635cc9139"
QDRANT_MANIFEST = (
    "a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9"
)
SAMPLE_CAP = 8
MINIMUM_SEMANTIC_TOKENS = 3
MAXIMUM_QUERY_CHARACTERS = 240

BLOCKERS = (
    "blocked_pending_latency",
    "blocked_pending_retrieval_quality",
)

SLOTS = (
    ("r1-probe-01", "m23q-01", "direct-fact", "section-001"),
    ("r1-probe-02", "m23q-02", "terminology", "section-002"),
    ("r1-probe-03", "m23q-03", "cross-section", "section-003"),
    ("r1-probe-04", "m23q-04", "provenance", "section-004"),
    ("r1-probe-05", "m23q-07", "direct-fact", "section-007"),
    ("r1-probe-06", "m23q-08", "terminology", "section-008"),
    ("r1-probe-07", "m23q-09", "cross-section", "section-009"),
    ("r1-probe-08", "m23q-10", "provenance", "section-010"),
)

TEMPLATES = {
    "direct-fact": "What does the knowledge source explain about {topic}?",
    "terminology": "What is {topic} in this knowledge source?",
    "cross-section": (
        "How does {topic} relate to the surrounding document context?"
    ),
    "provenance": "Which source section supports the concept {topic}?",
}

FIELD_PRIORITY = (
    "concept_id",
    "section_id",
    "article_id",
    "document_id",
    "source_path",
)

GENERIC_TOKENS = {
    "article",
    "concept",
    "doc",
    "docs",
    "document",
    "knowledge",
    "live",
    "md",
    "node",
    "os",
    "pilot",
    "section",
    "shadow",
    "source",
}

PROTECTED_MUTATIONS = (
    "answer_serving",
    "candidate_mode",
    "credential_rotation",
    "deployment",
    "graph_neural_retrieval",
    "live_traffic",
    "permanent_ledger",
    "production_pointer",
    "production_query_mirroring",
    "promotion",
    "public_graph_explorer",
    "qdrant_delete",
    "qdrant_read",
    "qdrant_write",
    "r2_mutation",
    "source_mutation",
    "source_pr_19_merge",
    "user_sampling",
    "worker_queue_mutation",
)


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
        raise IntegrityError(f"M23.7-R1-{code} {message}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), 101, f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    valid = not isinstance(value, (str, bytes)) and isinstance(value, Sequence)
    _require(valid, 102, f"{label} must be a list")
    return tuple(value)


def canonical_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R1",
        "implementation_issue": 460,
        "workstream": "live_probe_semantic_alignment",
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "m23_7_8_decision": "repair",
            "m23_7_8_decision_packet_sha256": DECISION_PACKET_SHA256,
            "m23_7_8_report_sha256": DECISION_REPORT_SHA256,
            "m23_7_8_repair_handoff_sha256": REPAIR_HANDOFF_SHA256,
            "m23_7_1_contract_sha256": QUALITY_CONTRACT_SHA256,
            "m23_7_2_evaluation_sha256": OFFLINE_EVALUATION_SHA256,
            "qdrant_release_id": QDRANT_RELEASE,
            "qdrant_release_manifest_sha256": QDRANT_MANIFEST,
            "source_pr_19": {
                "state": "open",
                "draft": True,
                "merged": False,
                "head_sha": SOURCE_PR_HEAD,
            },
        },
        "probe_contract": {
            "probe_count": SAMPLE_CAP,
            "sample_order": "point_id_ascending",
            "source": "bounded_public_nonproduction_pilot_samples",
            "query_text_source": (
                "deterministic_payload_identifier_humanisation"
            ),
            "field_priority": list(FIELD_PRIORITY),
            "raw_section_id_as_query_forbidden": True,
            "user_queries_allowed": False,
            "arbitrary_free_text_allowed": False,
            "minimum_semantic_tokens": MINIMUM_SEMANTIC_TOKENS,
            "maximum_query_characters": MAXIMUM_QUERY_CHARACTERS,
            "expected_relevance_rule": "exact_bound_target_section_id",
            "compiled_raw_query_persisted": False,
            "raw_answer_persisted": False,
        },
        "templates": dict(TEMPLATES),
        "slots": [
            {
                "probe_id": probe_id,
                "offline_case_id": case_id,
                "query_class": query_class,
                "offline_placeholder_relevant_id": placeholder,
                "acl_allowed": True,
                "no_answer_expected": False,
            }
            for probe_id, case_id, query_class, placeholder in SLOTS
        ],
        "exit_semantics": {
            "r1_complete_when": (
                "manifest_compiler_and_redacted_mapping_replay_pass"
            ),
            "retrieval_quality_blocker_cleared": False,
            "latency_blocker_cleared": False,
            "r2_required": True,
            "r3_required": True,
            "promotion_eligibility_granted": False,
        },
        "carry_forward_blockers": list(BLOCKERS),
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "semantic_output_served": False,
            "production_authority": False,
        },
        "protected_mutations": {
            key: False for key in PROTECTED_MUTATIONS
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def validate_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    root = dict(_mapping(payload, "manifest"))
    digest = root.pop("manifest_sha256", None)
    _require(digest == canonical_sha256(root), 103, "manifest digest mismatch")
    expected = canonical_manifest()
    expected_digest = expected.pop("manifest_sha256")
    _require(root == expected, 104, "manifest drifted")
    _require(digest == expected_digest, 105, "manifest identity drifted")
    return {**root, "manifest_sha256": digest}


def _identifier_tokens(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    leaf = value.rsplit("/", 1)[-1]
    leaf = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", leaf)
    leaf = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", leaf)
    output: list[str] = []
    for raw in raw_tokens:
        token = raw.lower()
        if token in GENERIC_TOKENS:
            continue
        if re.fullmatch(r"[a-f0-9]{8,}", token):
            continue
        numeric_suffix = re.fullmatch(r"([a-z]+)\d+", token)
        if numeric_suffix:
            prefix = numeric_suffix.group(1)
            if prefix not in GENERIC_TOKENS and len(prefix) >= 3:
                output.append(prefix)
            continue
        if len(token) >= 3:
            output.append(token)
    return output


def _semantic_topic(payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    tokens: list[str] = []
    for key in FIELD_PRIORITY:
        for token in _identifier_tokens(payload.get(key)):
            if token not in tokens:
                tokens.append(token)
    _require(
        len(tokens) >= MINIMUM_SEMANTIC_TOKENS,
        106,
        "sample identifiers do not contain enough semantic tokens",
    )
    selected = tokens[:8]
    return " ".join(selected), selected


def _validate_sample(raw: Mapping[str, Any]) -> dict[str, Any]:
    point_id = raw.get("point_id", raw.get("id"))
    _require(isinstance(point_id, str) and bool(point_id), 107, "point id missing")
    payload = dict(_mapping(raw.get("payload"), "sample payload"))
    expected = {
        "audience": "public",
        "source_membership": "evaluation-only-pending-proposal",
        "release_id": QDRANT_RELEASE,
        "release_manifest_sha256": QDRANT_MANIFEST,
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    for key, value in expected.items():
        _require(payload.get(key) == value, 108, f"sample identity drifted: {key}")
    section_id = payload.get("section_id")
    _require(
        isinstance(section_id, str) and bool(section_id),
        109,
        "section id missing",
    )
    topic, tokens = _semantic_topic(payload)
    return {
        "point_id": point_id,
        "section_id": section_id,
        "payload": payload,
        "topic": topic,
        "tokens": tokens,
    }


def compile_probe_plan(
    manifest_payload: Mapping[str, Any],
    samples_payload: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    manifest = validate_manifest(manifest_payload)
    raw_samples = _sequence(samples_payload, "samples")
    _require(len(raw_samples) == SAMPLE_CAP, 110, "exactly eight samples are required")
    samples = [_validate_sample(_mapping(item, "sample")) for item in raw_samples]
    samples.sort(key=lambda item: item["point_id"])
    target_ids = [item["section_id"] for item in samples]
    _require(len(set(target_ids)) == SAMPLE_CAP, 111, "target sections are duplicated")

    probes: list[dict[str, Any]] = []
    for slot, sample in zip(manifest["slots"], samples, strict=True):
        query_class = slot["query_class"]
        query_text = TEMPLATES[query_class].format(topic=sample["topic"])
        _require(query_text != sample["section_id"], 112, "raw section id reused as query")
        _require(
            len(query_text) <= MAXIMUM_QUERY_CHARACTERS,
            113,
            "compiled query exceeds character limit",
        )
        _require(
            len(sample["tokens"]) >= MINIMUM_SEMANTIC_TOKENS,
            114,
            "compiled query is semantically weak",
        )
        probes.append(
            {
                "probe_id": slot["probe_id"],
                "offline_case_id": slot["offline_case_id"],
                "query_class": query_class,
                "point_id": sample["point_id"],
                "target_section_id": sample["section_id"],
                "expected_relevant_ids": [sample["section_id"]],
                "query_text": query_text,
                "query_digest": canonical_sha256(
                    ["m23-7-r1", slot["probe_id"], query_text]
                ),
                "semantic_token_count": len(sample["tokens"]),
                "query_character_count": len(query_text),
            }
        )
    return probes


def canonical_fixture_samples() -> list[dict[str, Any]]:
    identifiers = (
        (
            "canonical-run-authority",
            "architecture/harness#canonical-run-authority",
            "harness-architecture",
            "harness-runtime",
            "docs/architecture/harness-runtime.md",
        ),
        (
            "request-boundary-admission-control",
            "architecture/harness#request-boundary",
            "harness-architecture",
            "harness-security",
            "docs/architecture/request-boundary.md",
        ),
        (
            "agent-loop-stopping-policy",
            "architecture/harness#agent-loop-stopping-policy",
            "agent-harness",
            "runtime-loop",
            "docs/architecture/agent-loop.md",
        ),
        (
            "evidence-provenance-verification",
            "architecture/harness#evidence-provenance-verification",
            "verification-system",
            "evidence-chain",
            "docs/architecture/provenance.md",
        ),
        (
            "durable-thread-state",
            "architecture/runtime#durable-thread-state",
            "runtime-architecture",
            "thread-state",
            "docs/architecture/durable-state.md",
        ),
        (
            "tool-calling-proposal-boundary",
            "architecture/agents#tool-calling-proposal-boundary",
            "agent-runtime",
            "tool-interface",
            "docs/architecture/tool-calling.md",
        ),
        (
            "graph-explorer-read-only-boundary",
            "architecture/explorer#read-only-boundary",
            "graph-explorer",
            "explorer-security",
            "docs/architecture/graph-explorer.md",
        ),
        (
            "lexical-rollback-authority",
            "architecture/retrieval#lexical-rollback-authority",
            "retrieval-runtime",
            "rollback-policy",
            "docs/architecture/lexical-rollback.md",
        ),
    )
    output: list[dict[str, Any]] = []
    for index, values in enumerate(identifiers, start=1):
        concept_id, section_id, article_id, document_id, source_path = values
        output.append(
            {
                "point_id": f"00000000-0000-0000-0000-{index:012d}",
                "payload": {
                    "concept_id": concept_id,
                    "section_id": section_id,
                    "article_id": article_id,
                    "document_id": document_id,
                    "source_path": source_path,
                    "audience": "public",
                    "source_membership": "evaluation-only-pending-proposal",
                    "release_id": QDRANT_RELEASE,
                    "release_manifest_sha256": QDRANT_MANIFEST,
                    "canonical_knowledge": False,
                    "candidate_release_eligible": False,
                    "production_authority": False,
                },
            }
        )
    return output


def build_alignment_report(
    manifest_payload: Mapping[str, Any],
    compiled_probes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    manifest = validate_manifest(manifest_payload)
    probes = [dict(_mapping(item, "compiled probe")) for item in compiled_probes]
    _require(len(probes) == SAMPLE_CAP, 115, "compiled probe count drifted")
    expected_slots = manifest["slots"]
    mappings: list[dict[str, Any]] = []
    for slot, probe in zip(expected_slots, probes, strict=True):
        _require(probe["probe_id"] == slot["probe_id"], 116, "probe order drifted")
        _require(
            probe["offline_case_id"] == slot["offline_case_id"],
            117,
            "offline case mapping drifted",
        )
        _require(
            probe["query_class"] == slot["query_class"],
            118,
            "query class mapping drifted",
        )
        _require(
            probe["expected_relevant_ids"] == [probe["target_section_id"]],
            119,
            "expected relevance set drifted",
        )
        query_text = probe.get("query_text")
        _require(isinstance(query_text, str) and bool(query_text), 120, "query missing")
        _require(
            probe["query_digest"]
            == canonical_sha256(["m23-7-r1", probe["probe_id"], query_text]),
            121,
            "query digest drifted",
        )
        mappings.append(
            {
                "probe_id": probe["probe_id"],
                "offline_case_id": probe["offline_case_id"],
                "query_class": probe["query_class"],
                "point_id": probe["point_id"],
                "target_section_id": probe["target_section_id"],
                "expected_relevant_ids": probe["expected_relevant_ids"],
                "query_digest": probe["query_digest"],
                "semantic_token_count": probe["semantic_token_count"],
                "query_character_count": probe["query_character_count"],
                "raw_query_persisted": False,
                "raw_answer_persisted": False,
            }
        )

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "pass_ready_for_r3_binding",
        "milestone": "M23.7-R1",
        "workstream": "live_probe_semantic_alignment",
        "manifest_sha256": manifest["manifest_sha256"],
        "fixture_mapping_count": SAMPLE_CAP,
        "query_class_counts": {
            name: sum(1 for item in mappings if item["query_class"] == name)
            for name in TEMPLATES
        },
        "mappings": mappings,
        "alignment": {
            "raw_section_id_query_replaced": True,
            "offline_positive_case_slots_bound": True,
            "expected_relevance_exact_target": True,
            "deterministic_mapping": True,
            "compiled_raw_query_persisted": False,
            "user_queries_used": False,
        },
        "exit": {
            "r1_complete": True,
            "runtime_compiler_ready": True,
            "live_target_binding_pending_r3": True,
            "retrieval_quality_blocker_cleared": False,
            "latency_blocker_cleared": False,
            "promotion_eligibility_granted": False,
        },
        "carry_forward_blockers": list(BLOCKERS),
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "production_authority": False,
            "protected_mutations_dispatched": False,
        },
        "external_calls": {
            "network": 0,
            "provider": 0,
            "qdrant_read": 0,
            "qdrant_write": 0,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def canonical_alignment_report() -> dict[str, Any]:
    manifest = canonical_manifest()
    probes = compile_probe_plan(manifest, canonical_fixture_samples())
    return build_alignment_report(manifest, probes)
