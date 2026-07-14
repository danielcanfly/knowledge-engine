from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import IntegrityError

ENGINE_ENTRY_SHA = "14a7f9bcf375925458e17272418d6db9aa308caf"
SOURCE_SHA = "a6ba738d910d01d2ae99b1968f0831989934c549"
FOUNDATION_SHA = "e5ef644053d34e89c70d2ceb37521e1c59234832"

REQUIRED_QUERY_CLASSES = {
    "exact_title",
    "paraphrase",
    "zh_for_english_concept",
    "en_for_chinese_concept",
    "comparison",
    "dependency",
    "not_found",
    "acl_negative",
}
UNRESOLVED_REPOSITORY_FIELDS = (
    "repository",
    "repository_commit",
    "repository_path",
    "blob_sha",
    "canonical_url",
)
PROTECTED_MUTATION_KEYS = (
    "article_byte_ingestion",
    "source_write",
    "r2_write",
    "production_pointer_update",
    "provider_call",
    "embedding_generation",
    "extraction",
    "traffic_change",
    "multi_hop_activation",
    "graph_neural_retrieval",
)


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrityError(f"M23-BASELINE-101 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise IntegrityError(f"M23-BASELINE-102 {label} must be a list")
    return tuple(value)


def _payload_digest(value: Mapping[str, Any], digest_key: str) -> str:
    payload = {key: item for key, item in value.items() if key != digest_key}
    return _sha(payload)


def _validate_entry_baseline(value: Any) -> dict[str, str]:
    baseline = _mapping(value, "entry_baseline")
    expected = {
        "engine_sha": ENGINE_ENTRY_SHA,
        "source_sha": SOURCE_SHA,
        "foundation_sha": FOUNDATION_SHA,
    }
    if dict(baseline) != expected:
        raise IntegrityError("M23-BASELINE-103 entry baseline identity mismatch")
    return expected


def _validate_document(value: Any) -> dict[str, Any]:
    document = _mapping(value, "document")
    required = {
        "document_id",
        "logical_article_id",
        "upload_id",
        "original_filename",
        "sha256",
        "byte_length",
        "line_count",
        "title",
        "series",
        "part",
        "language",
        "source_status",
        "audience",
        "ownership_basis",
        "pilot_role",
        "counterpart_document_id",
        "repository",
        "repository_commit",
        "repository_path",
        "blob_sha",
        "canonical_url",
        "unresolved_identity_fields",
        "image_references",
        "image_assets_supplied",
    }
    if set(document) != required:
        raise IntegrityError("M23-BASELINE-104 document shape is invalid")
    for key in ("document_id", "logical_article_id", "upload_id", "original_filename", "title"):
        if not isinstance(document[key], str) or not document[key].strip():
            raise IntegrityError(f"M23-BASELINE-105 invalid document field: {key}")
    digest = document["sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise IntegrityError("M23-BASELINE-106 invalid content SHA-256")
    if document["language"] not in {"zh-TW", "en"}:
        raise IntegrityError("M23-BASELINE-107 unsupported pilot language")
    if document["part"] not in {1, 2, 3}:
        raise IntegrityError("M23-BASELINE-108 unexpected Harness Theory part")
    if document["byte_length"] <= 0 or document["line_count"] <= 0:
        raise IntegrityError("M23-BASELINE-109 invalid byte or line count")
    if document["audience"] != "public" or document["ownership_basis"] != "user_supplied":
        raise IntegrityError("M23-BASELINE-110 audience or ownership basis mismatch")
    if document["image_assets_supplied"] is not False:
        raise IntegrityError("M23-BASELINE-111 missing image assets cannot be marked supplied")
    unresolved = _sequence(document["unresolved_identity_fields"], "unresolved fields")
    if tuple(unresolved) != UNRESOLVED_REPOSITORY_FIELDS:
        raise IntegrityError("M23-BASELINE-112 unresolved repository fields are incomplete")
    if any(document[key] is not None for key in UNRESOLVED_REPOSITORY_FIELDS):
        raise IntegrityError("M23-BASELINE-113 repository or URL identity was fabricated")
    _sequence(document["pilot_role"], "pilot_role")
    _sequence(document["image_references"], "image_references")
    return dict(document)


def validate_corpus_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _mapping(value, "corpus_manifest")
    required = {
        "schema_version",
        "entry_baseline",
        "authority",
        "documents",
        "protected_state",
        "manifest_digest",
    }
    if set(manifest) != required:
        raise IntegrityError("M23-BASELINE-114 corpus manifest shape is invalid")
    if manifest["schema_version"] != "knowledge-engine-m23-pilot-corpus/v1":
        raise IntegrityError("M23-BASELINE-115 unsupported corpus manifest schema")
    if manifest["manifest_digest"] != _payload_digest(manifest, "manifest_digest"):
        raise IntegrityError("M23-BASELINE-116 corpus manifest digest mismatch")

    baseline = _validate_entry_baseline(manifest["entry_baseline"])
    authority = _mapping(manifest["authority"], "authority")
    expected_authority = {
        "source_kind": "conversation_upload",
        "repository_discovery": "no_connected_authoritative_blog_repository",
        "repository_identity_fabricated": False,
        "article_bytes_committed": False,
        "intake_deferred_to": "M23.2",
    }
    if dict(authority) != expected_authority:
        raise IntegrityError("M23-BASELINE-117 source authority boundary mismatch")

    documents = [_validate_document(item) for item in _sequence(manifest["documents"], "documents")]
    if len(documents) != 6:
        raise IntegrityError("M23-BASELINE-118 exactly six pilot documents are required")
    if len({item["document_id"] for item in documents}) != 6:
        raise IntegrityError("M23-BASELINE-119 duplicate document identity")
    if len({item["upload_id"] for item in documents}) != 6:
        raise IntegrityError("M23-BASELINE-120 duplicate upload identity")
    if len({item["sha256"] for item in documents}) != 6:
        raise IntegrityError("M23-BASELINE-121 duplicate content digest")

    by_id = {item["document_id"]: item for item in documents}
    pairs: set[tuple[str, str]] = set()
    for item in documents:
        counterpart = by_id.get(item["counterpart_document_id"])
        if counterpart is None:
            raise IntegrityError("M23-BASELINE-122 missing bilingual counterpart")
        if counterpart["counterpart_document_id"] != item["document_id"]:
            raise IntegrityError("M23-BASELINE-123 counterpart mapping is not reciprocal")
        if counterpart["logical_article_id"] != item["logical_article_id"]:
            raise IntegrityError("M23-BASELINE-124 counterpart logical article mismatch")
        if counterpart["part"] != item["part"] or counterpart["language"] == item["language"]:
            raise IntegrityError("M23-BASELINE-125 counterpart part or language mismatch")
        pairs.add(tuple(sorted((item["document_id"], counterpart["document_id"]))))
    if len(pairs) != 3:
        raise IntegrityError("M23-BASELINE-126 exactly three bilingual pairs are required")

    protected = _mapping(manifest["protected_state"], "protected_state")
    if set(protected) != set(PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23-BASELINE-127 protected state is incomplete")
    if any(protected[key] is not False for key in PROTECTED_MUTATION_KEYS):
        raise IntegrityError("M23-BASELINE-128 protected mutation was dispatched")

    return {
        "schema_version": manifest["schema_version"],
        "entry_baseline": baseline,
        "authority": dict(authority),
        "documents": documents,
        "protected_state": dict(protected),
        "manifest_digest": manifest["manifest_digest"],
    }


def validate_golden_queries(value: Mapping[str, Any], *, manifest_digest: str) -> dict[str, Any]:
    golden = _mapping(value, "golden_queries")
    required = {
        "schema_version",
        "frozen_before_model_selection",
        "corpus_manifest_digest",
        "queries",
        "golden_query_digest",
    }
    if set(golden) != required:
        raise IntegrityError("M23-BASELINE-129 golden query shape is invalid")
    if golden["schema_version"] != "knowledge-engine-m23-golden-queries/v1":
        raise IntegrityError("M23-BASELINE-130 unsupported golden query schema")
    if golden["frozen_before_model_selection"] is not True:
        raise IntegrityError("M23-BASELINE-131 golden queries are not frozen")
    if golden["corpus_manifest_digest"] != manifest_digest:
        raise IntegrityError("M23-BASELINE-132 corpus/golden query binding mismatch")
    if golden["golden_query_digest"] != _payload_digest(golden, "golden_query_digest"):
        raise IntegrityError("M23-BASELINE-133 golden query digest mismatch")

    queries = []
    for value_item in _sequence(golden["queries"], "queries"):
        item = _mapping(value_item, "query")
        required_query = {
            "query_id",
            "class",
            "language",
            "text",
            "expected_logical_articles",
            "should_match",
            "expected_policy",
        }
        if set(item) != required_query:
            raise IntegrityError("M23-BASELINE-134 golden query item shape is invalid")
        if item["class"] not in REQUIRED_QUERY_CLASSES:
            raise IntegrityError("M23-BASELINE-135 unknown golden query class")
        if item["language"] not in {"zh-TW", "en"}:
            raise IntegrityError("M23-BASELINE-136 invalid golden query language")
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise IntegrityError("M23-BASELINE-137 empty golden query")
        expected = _sequence(item["expected_logical_articles"], "expected logical articles")
        if item["should_match"] is True and not expected:
            raise IntegrityError("M23-BASELINE-138 positive query has no expected article")
        if item["should_match"] is False and expected:
            raise IntegrityError("M23-BASELINE-139 negative query declares expected articles")
        queries.append({**dict(item), "expected_logical_articles": list(expected)})

    if len(queries) < 12:
        raise IntegrityError("M23-BASELINE-140 at least twelve golden queries are required")
    if len({item["query_id"] for item in queries}) != len(queries):
        raise IntegrityError("M23-BASELINE-141 duplicate golden query identity")
    if not REQUIRED_QUERY_CLASSES.issubset({item["class"] for item in queries}):
        raise IntegrityError("M23-BASELINE-142 required golden query coverage is incomplete")
    acl_queries = [item for item in queries if item["class"] == "acl_negative"]
    if any(item["expected_policy"] != "deny" for item in acl_queries):
        raise IntegrityError("M23-BASELINE-143 ACL-negative query must require denial")

    return {
        "schema_version": golden["schema_version"],
        "frozen_before_model_selection": True,
        "corpus_manifest_digest": manifest_digest,
        "queries": queries,
        "golden_query_digest": golden["golden_query_digest"],
    }


def validate_real_data_baseline(
    corpus_manifest: Mapping[str, Any],
    golden_queries: Mapping[str, Any],
) -> dict[str, Any]:
    corpus = validate_corpus_manifest(corpus_manifest)
    queries = validate_golden_queries(
        golden_queries,
        manifest_digest=corpus["manifest_digest"],
    )
    result = {
        "schema_version": "knowledge-engine-m23-real-data-baseline/v1",
        "corpus": corpus,
        "golden_queries": queries,
        "accepted": True,
    }
    return {**result, "baseline_digest": _sha(result)}
