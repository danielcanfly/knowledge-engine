from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError
from .m23_7_r1_semantic_alignment import (
    MAXIMUM_QUERY_CHARACTERS,
    SAMPLE_CAP,
    SLOTS,
    TEMPLATES,
)
from .m23_cloudflare_qdrant import deterministic_point_id

SCHEMA_VERSION = "knowledge-engine-m23-7-r3-2-semantic-payload-repair/v1"
PAYLOAD_SCHEMA_V2 = "knowledge-engine-m23-qdrant-payload/v2"
INGESTION_PREVIEW_SCHEMA = "knowledge-engine-m23-7-r3-2-ingestion-preview/v1"
ENTRY_ENGINE_SHA = "011bcf8b019ba9b168c143c45604345b2f2e35e9"
IMPLEMENTATION_ISSUE = 484
R3_1_REPORT_SHA256 = "10a5bd0aa1b141cb508db8781269d2d47ed1cf9309a3065671f3356f7e1d5f7c"
R3_1_RECONCILIATION_SHA = "011bcf8b019ba9b168c143c45604345b2f2e35e9"
VECTOR_DIMENSION = 1024
EXPECTED_REBUILD_POINT_COUNT = 107
MAXIMUM_SEMANTIC_SURFACE_CHARACTERS = 170

REQUIRED_PAYLOAD_FIELDS_V2 = (
    "payload_schema_version",
    "section_id",
    "article_id",
    "document_id",
    "concept_id",
    "section_title",
    "language",
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

GENERIC_TITLE_TOKENS = {
    "article",
    "chapter",
    "chunk",
    "document",
    "knowledge",
    "part",
    "section",
    "source",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require(condition: bool, code: int, message: str) -> None:
    if not condition:
        raise IntegrityError(f"M23.7-R3.2-{code} {message}")


def _required_string(value: Any, label: str, maximum: int) -> str:
    _require(isinstance(value, str), 101, f"{label} must be a string")
    text = value.strip()
    _require(bool(text) and len(text) <= maximum, 102, f"{label} is empty or too long")
    return text


def _sha256_string(value: Any, label: str) -> str:
    text = _required_string(value, label, 64)
    _require(
        len(text) == 64 and all(char in "0123456789abcdef" for char in text),
        103,
        f"{label} must be lowercase SHA-256",
    )
    return text


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _title_tokens(title: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[^\W_]+", title, flags=re.UNICODE):
        token = raw.casefold()
        if _contains_cjk(token):
            compact = "".join(char for char in token if "\u3400" <= char <= "\u9fff")
            grams = (
                [compact]
                if len(compact) <= 2
                else [compact[index : index + 2] for index in range(len(compact) - 1)]
            )
            for gram in grams:
                if gram not in tokens:
                    tokens.append(gram)
            continue
        if len(token) < 2 or token in GENERIC_TITLE_TOKENS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens[:12]


def _locator_tokens(section_id: str) -> list[str]:
    tokens: list[str] = []
    for prefix, number in re.findall(r"([A-Za-z]+)[-_]?(\d+)", section_id):
        token = f"{prefix.casefold()} {int(number)}"
        if token not in tokens:
            tokens.append(token)
    return tokens[-4:]


def _article_id(section_id: str) -> str:
    if "/chunk-" in section_id:
        return section_id.split("/chunk-", 1)[0]
    if "#" in section_id:
        return section_id.split("#", 1)[0]
    return section_id


def _normalised_vector(vector: Sequence[Any], row: int) -> list[float]:
    _require(len(vector) == VECTOR_DIMENSION, 104, f"vector row {row} dimension mismatch")
    values: list[float] = []
    for item in vector:
        _require(
            not isinstance(item, bool) and isinstance(item, (int, float)),
            105,
            f"vector row {row} contains a non-number",
        )
        number = float(item)
        _require(math.isfinite(number), 106, f"vector row {row} contains non-finite data")
        values.append(number)
    norm = math.sqrt(math.fsum(value * value for value in values))
    _require(abs(norm - 1.0) <= 1e-4, 107, f"vector row {row} is not L2-normalized")
    return values


def build_payload_v2(
    document: Mapping[str, Any],
    *,
    article_id: str,
    release: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a retrieval payload from the same document bound to its vector row.

    This pure builder authorises no Qdrant write and does not recompute or alter the
    vector. It restores semantic fields that the v1 ingestion path discarded.
    """

    section_title = _required_string(document.get("title"), "document.title", 2_000)
    language = _required_string(document.get("language"), "document.language", 40)
    payload = {
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "section_id": _required_string(document.get("section_id"), "document.section_id", 500),
        "article_id": _required_string(article_id, "article_id", 500),
        "document_id": _required_string(article_id, "document_id", 500),
        "concept_id": _required_string(document.get("concept_id"), "document.concept_id", 500),
        "section_title": section_title,
        "language": language,
        "source_path": _required_string(document.get("source_path"), "document.source_path", 2_000),
        "source_sha256": _sha256_string(document.get("source_sha256"), "document.source_sha256"),
        "text_sha256": _sha256_string(document.get("text_sha256"), "document.text_sha256"),
        "audience": _required_string(document.get("audience"), "document.audience", 80),
        "source_membership": "evaluation-only-pending-proposal",
        "release_id": _required_string(release.get("release_id"), "release.release_id", 128),
        "release_manifest_sha256": _sha256_string(
            release.get("release_manifest_sha256"),
            "release.release_manifest_sha256",
        ),
        "graph_node_id": _required_string(document.get("concept_id"), "graph_node_id", 500),
        "embedding_provider": "cloudflare-workers-ai",
        "embedding_model": "@cf/baai/bge-m3",
        "vector_dimension": VECTOR_DIMENSION,
        "vector_name": "default",
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
    }
    _require(tuple(payload) == REQUIRED_PAYLOAD_FIELDS_V2, 108, "payload v2 field ordering drifted")
    return payload


def build_repaired_ingestion_preview(
    documents: Sequence[Mapping[str, Any]],
    vectors: Sequence[Sequence[Any]],
    *,
    release: Mapping[str, Any],
    expected_point_count: int = EXPECTED_REBUILD_POINT_COUNT,
) -> dict[str, Any]:
    """Create deterministic candidate points without dispatching a write.

    The point ID, payload and vector are assembled in one zip operation so row
    ordering cannot silently remap a title or section identity onto another vector.
    """

    _require(expected_point_count > 0, 109, "expected point count must be positive")
    _require(len(documents) == expected_point_count, 110, "document count mismatch")
    _require(len(vectors) == expected_point_count, 111, "vector count mismatch")

    points: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    seen_point_ids: set[str] = set()
    seen_sections: set[str] = set()
    for row, (document, vector) in enumerate(zip(documents, vectors, strict=True)):
        section_id = _required_string(document.get("section_id"), f"documents[{row}].section_id", 500)
        _require(section_id not in seen_sections, 112, "duplicate section id")
        seen_sections.add(section_id)
        point_id = deterministic_point_id(section_id)
        _require(point_id not in seen_point_ids, 113, "duplicate deterministic point id")
        seen_point_ids.add(point_id)

        values = _normalised_vector(vector, row)
        payload = build_payload_v2(
            document,
            article_id=_article_id(section_id),
            release=release,
        )
        vector_sha256 = canonical_sha256(values)
        binding_sha256 = canonical_sha256(
            {
                "row": row,
                "point_id": point_id,
                "section_id": section_id,
                "text_sha256": payload["text_sha256"],
                "section_title": payload["section_title"],
                "language": payload["language"],
                "vector_sha256": vector_sha256,
            }
        )
        points.append(
            {
                "id": point_id,
                "vector": {"default": values},
                "payload": payload,
            }
        )
        bindings.append(
            {
                "row": row,
                "point_id": point_id,
                "section_id": section_id,
                "vector_sha256": vector_sha256,
                "binding_sha256": binding_sha256,
            }
        )

    preview: dict[str, Any] = {
        "schema_version": INGESTION_PREVIEW_SCHEMA,
        "milestone": "M23.7-R3.2",
        "mode": "offline-no-write-preview",
        "point_count": len(points),
        "payload_schema_version": PAYLOAD_SCHEMA_V2,
        "points": points,
        "bindings": bindings,
        "embedding_contract": {
            "provider": "cloudflare-workers-ai",
            "model": "@cf/baai/bge-m3",
            "dimension": VECTOR_DIMENSION,
            "normalised": True,
            "model_changed": False,
            "query_prefix_changed": False,
        },
        "authority": {
            "qdrant_write_dispatched": False,
            "qdrant_delete_dispatched": False,
            "r2_mutation_dispatched": False,
            "pointer_mutation_dispatched": False,
            "source_mutation_dispatched": False,
            "production_mutation_dispatched": False,
        },
    }
    preview["preview_sha256"] = canonical_sha256(preview)
    return preview


def _semantic_surface(payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    _require(payload.get("payload_schema_version") == PAYLOAD_SCHEMA_V2, 114, "payload v2 required")
    title = _required_string(payload.get("section_title"), "section_title", 2_000)
    language = _required_string(payload.get("language"), "language", 40)
    section_id = _required_string(payload.get("section_id"), "section_id", 500)
    concept_id = _required_string(payload.get("concept_id"), "concept_id", 500)

    title_tokens = _title_tokens(title)
    _require(len(title_tokens) >= 2, 115, "section title is not semantically discriminative")
    locators = _locator_tokens(section_id)
    concept_tokens = _title_tokens(concept_id.replace("-", " ").replace("_", " "))

    suffixes: list[str] = []
    if concept_tokens:
        suffixes.append("concept " + " ".join(concept_tokens[:4]))
    if locators:
        suffixes.append("location " + " ".join(locators))
    suffixes.append("language " + language)
    suffix = "; " + "; ".join(suffixes)
    title_budget = max(1, MAXIMUM_SEMANTIC_SURFACE_CHARACTERS - len(suffix))
    bounded_title = title[:title_budget].rstrip()
    surface = bounded_title + suffix
    tokens = title_tokens + concept_tokens[:4] + locators + [language.casefold()]
    return surface, tokens


def compile_repaired_probe_plan(samples_payload: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    _require(len(samples_payload) == SAMPLE_CAP, 116, "exactly eight samples are required")
    ordered = sorted(samples_payload, key=lambda item: item.get("point_id", item.get("id")))
    probes: list[dict[str, Any]] = []
    text_digests: set[str] = set()
    targets: set[str] = set()

    for slot, raw in zip(SLOTS, ordered, strict=True):
        point_id = _required_string(raw.get("point_id", raw.get("id")), "point_id", 128)
        payload = raw.get("payload")
        _require(isinstance(payload, Mapping), 117, "sample payload missing")
        target = _required_string(payload.get("section_id"), "target_section_id", 500)
        _require(target not in targets, 118, "target sections are duplicated")
        targets.add(target)

        surface, tokens = _semantic_surface(payload)
        query_class = slot[2]
        query_text = TEMPLATES[query_class].format(topic=surface)
        _require(query_text != target, 119, "raw section id reused as query")
        _require(len(query_text) <= MAXIMUM_QUERY_CHARACTERS, 120, "compiled query exceeds limit")
        text_digest = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        _require(text_digest not in text_digests, 121, "query text collision detected")
        text_digests.add(text_digest)

        probes.append(
            {
                "probe_id": slot[0],
                "offline_case_id": slot[1],
                "query_class": query_class,
                "point_id": point_id,
                "target_section_id": target,
                "expected_relevant_ids": [target],
                "query_text": query_text,
                "query_text_sha256": text_digest,
                "query_digest": canonical_sha256(["m23-7-r3-2", slot[0], text_digest]),
                "semantic_token_count": len(tokens),
                "query_character_count": len(query_text),
                "payload_schema_version": PAYLOAD_SCHEMA_V2,
            }
        )

    _require(len(text_digests) == SAMPLE_CAP, 122, "compiled query identities are not unique")
    return probes


def canonical_repair_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "milestone": "M23.7-R3.2",
        "implementation_issue": IMPLEMENTATION_ISSUE,
        "entry": {
            "engine_sha": ENTRY_ENGINE_SHA,
            "r3_1_report_sha256": R3_1_REPORT_SHA256,
            "r3_1_reconciliation_merge_sha": R3_1_RECONCILIATION_SHA,
        },
        "repair": {
            "primary_root_cause": "identifier_humanisation_query_collision",
            "compounding_factor": "corpus_hubness",
            "payload_schema": PAYLOAD_SCHEMA_V2,
            "payload_additions": ["section_title", "language"],
            "compiler_surface": "title-plus-concept-plus-structural-locator-plus-language",
            "text_only_query_identity_required": True,
            "collision_policy": "fail-closed",
            "full_reingestion_required": True,
            "expected_rebuild_point_count": EXPECTED_REBUILD_POINT_COUNT,
            "embedding_model_changed": False,
            "embedding_prefix_changed": False,
            "payload_vector_row_binding_changed": False,
            "payload_vector_row_binding_revalidated": True,
        },
        "authority": {
            "production_retrieval": "lexical",
            "candidate_mode_enabled": False,
            "promotion_eligibility_granted": False,
            "qdrant_write_authorized": False,
            "source_mutation_authorized": False,
            "r2_mutation_authorized": False,
            "production_pointer_mutation_authorized": False,
        },
        "next_gate": "offline_rebuild_and_retrieval_evaluation",
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract
