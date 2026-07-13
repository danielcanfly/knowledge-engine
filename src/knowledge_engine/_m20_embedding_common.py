from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

EMBEDDING_CONTRACT_SCHEMA = "knowledge-os-embedding-provider-contract/v1"
MAX_VECTOR_DIMENSION = 65_536
MAX_INPUT_LENGTH = 131_072
MAX_BATCH_SIZE = 4_096
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_POOLING = {"cls", "mean", "last-token", "weighted-mean", "provider-native"}
_ALLOWED_NORMALIZATION = {"l2", "none"}
_ALLOWED_TRUNCATION = {"error", "head", "tail", "head-tail"}


class ContractError(ValueError):
    """Raised when a governed M20.1 contract is invalid."""


def _required_string(value: Any, label: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        raise ContractError(f"{label} must contain 1 to {maximum} characters")
    return candidate


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be a boolean")
    return value


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ContractError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _sha256(value: Any, label: str) -> str:
    candidate = _required_string(value, label, 64)
    if _SHA256.fullmatch(candidate) is None:
        raise ContractError(f"{label} must be a lowercase SHA-256 digest")
    return candidate


def _git_sha(value: Any, label: str) -> str:
    candidate = _required_string(value, label, 40)
    if _GIT_SHA.fullmatch(candidate) is None:
        raise ContractError(f"{label} must be a lowercase 40-character git SHA")
    return candidate


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str, maximum: int) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    if len(value) > maximum:
        raise ContractError(f"{label} must contain at most {maximum} items")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_provider_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    schema = _required_string(raw.get("schema_version"), "schema_version")
    if schema != EMBEDDING_CONTRACT_SCHEMA:
        raise ContractError(f"unsupported embedding contract schema: {schema}")

    provider = _mapping(raw.get("provider"), "provider")
    model = _mapping(raw.get("model"), "model")
    tokenizer = _mapping(raw.get("tokenizer"), "tokenizer")
    preprocessing = _mapping(raw.get("preprocessing"), "preprocessing")
    batching = _mapping(raw.get("batching"), "batching")
    identities = _mapping(raw.get("identities"), "identities")
    authority = _mapping(raw.get("authority"), "authority")

    revision = model.get("revision")
    digest = model.get("digest_sha256")
    if revision is None and digest is None:
        raise ContractError("model must pin revision or digest_sha256")
    if revision is not None:
        revision = _required_string(revision, "model.revision", 300)
    if digest is not None:
        digest = _sha256(digest, "model.digest_sha256")

    tokenizer_revision = tokenizer.get("revision")
    tokenizer_digest = tokenizer.get("digest_sha256")
    if tokenizer_revision is None and tokenizer_digest is None:
        raise ContractError("tokenizer must pin revision or digest_sha256")
    if tokenizer_revision is not None:
        tokenizer_revision = _required_string(tokenizer_revision, "tokenizer.revision", 300)
    if tokenizer_digest is not None:
        tokenizer_digest = _sha256(tokenizer_digest, "tokenizer.digest_sha256")

    pooling = _required_string(preprocessing.get("pooling"), "preprocessing.pooling")
    if pooling not in _ALLOWED_POOLING:
        raise ContractError(f"unsupported pooling: {pooling}")
    normalization = _required_string(
        preprocessing.get("normalization"), "preprocessing.normalization"
    )
    if normalization not in _ALLOWED_NORMALIZATION:
        raise ContractError(f"unsupported normalization: {normalization}")
    truncation = _required_string(preprocessing.get("truncation"), "preprocessing.truncation")
    if truncation not in _ALLOWED_TRUNCATION:
        raise ContractError(f"unsupported truncation: {truncation}")

    result = {
        "schema_version": EMBEDDING_CONTRACT_SCHEMA,
        "provider": {
            "name": _required_string(provider.get("name"), "provider.name", 200),
            "implementation": _required_string(
                provider.get("implementation"), "provider.implementation", 300
            ),
            "execution": _required_string(provider.get("execution"), "provider.execution", 100),
        },
        "model": {
            "id": _required_string(model.get("id"), "model.id", 300),
            **({"revision": revision} if revision is not None else {}),
            **({"digest_sha256": digest} if digest is not None else {}),
            "vector_dimension": _bounded_int(
                model.get("vector_dimension"), "model.vector_dimension", 1, MAX_VECTOR_DIMENSION
            ),
        },
        "tokenizer": {
            "id": _required_string(tokenizer.get("id"), "tokenizer.id", 300),
            **({"revision": tokenizer_revision} if tokenizer_revision is not None else {}),
            **(
                {"digest_sha256": tokenizer_digest}
                if tokenizer_digest is not None
                else {}
            ),
        },
        "preprocessing": {
            "pooling": pooling,
            "normalization": normalization,
            "input_template": _required_string(
                preprocessing.get("input_template"), "preprocessing.input_template", 2_000
            ),
            "query_template": _required_string(
                preprocessing.get("query_template"), "preprocessing.query_template", 2_000
            ),
            "maximum_input_length": _bounded_int(
                preprocessing.get("maximum_input_length"),
                "preprocessing.maximum_input_length",
                1,
                MAX_INPUT_LENGTH,
            ),
            "truncation": truncation,
            "unicode_normalization": _required_string(
                preprocessing.get("unicode_normalization"),
                "preprocessing.unicode_normalization",
                20,
            ),
        },
        "batching": {
            "batch_size": _bounded_int(
                batching.get("batch_size"), "batching.batch_size", 1, MAX_BATCH_SIZE
            ),
            "preserve_input_order": _required_bool(
                batching.get("preserve_input_order"), "batching.preserve_input_order"
            ),
            "deterministic": _required_bool(
                batching.get("deterministic"), "batching.deterministic"
            ),
        },
        "identities": {
            "engine_commit_sha": _git_sha(
                identities.get("engine_commit_sha"), "identities.engine_commit_sha"
            ),
            "source_commit_sha": _git_sha(
                identities.get("source_commit_sha"), "identities.source_commit_sha"
            ),
            "foundation_commit_sha": _git_sha(
                identities.get("foundation_commit_sha"), "identities.foundation_commit_sha"
            ),
        },
        "authority": {
            "canonical_source": _required_string(
                authority.get("canonical_source"), "authority.canonical_source", 100
            ),
            "vectors_are_derived": _required_bool(
                authority.get("vectors_are_derived"), "authority.vectors_are_derived"
            ),
            "runtime_network_required": _required_bool(
                authority.get("runtime_network_required"),
                "authority.runtime_network_required",
            ),
            "write_back": _required_bool(authority.get("write_back"), "authority.write_back"),
            "production_authority": _required_bool(
                authority.get("production_authority"), "authority.production_authority"
            ),
        },
    }
    if result["preprocessing"]["unicode_normalization"] != "NFKC":
        raise ContractError("unicode_normalization must be NFKC")
    if result["batching"]["preserve_input_order"] is not True:
        raise ContractError("batching must preserve input order")
    if result["batching"]["deterministic"] is not True:
        raise ContractError("batching must be deterministic")
    if result["authority"] != {
        "canonical_source": "markdown",
        "vectors_are_derived": True,
        "runtime_network_required": False,
        "write_back": False,
        "production_authority": False,
    }:
        raise ContractError("embedding provider authority must remain local, derived, and read-only")
    return result
