#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import UTC, datetime
from typing import Any, Mapping

EXPECTED_STATUS = "M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS"
EXPECTED_RELEASE_ID = "m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440"
EXPECTED_SOURCE_HEAD_SHA = "a738f20b16f10925c8adfe4d625be8db30fb269c"
EXPECTED_SOURCE_COMMIT_SHA = "f5e20062c1400d7320fe2dbecf6409a0a8c910a7"
EXPECTED_ADMISSION_SHA256 = "ec79a3cad1d84a936a6420b64c3ec43859ebd296eee992b2654dd8537d62da2d"
EXPECTED_QDRANT_COLLECTION = "m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440"
EXPECTED_SEMANTIC_POINT_COUNT = 4424
EXPECTED_NODE_COUNT = 4457
EXPECTED_EDGE_COUNT = 8995
FORBIDDEN_PRODUCTION_PORT = 18087
REQUIRED_ZERO_AUTHORITY = {
    "production_pointer_writes",
    "canonical_route_mutations",
    "r2_writes",
    "qdrant_writes",
    "embedding_provider_requests",
    "provider_answer_requests",
    "source_repo_mutations",
    "e5_consumed_attempts",
}
ALLOWED_AUTH_BOOTSTRAP_SOURCES = {"base_env", "isolated_synthetic_localhost_only"}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_receipt_from_log(path: pathlib.Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = EXPECTED_STATUS
    pos = text.rfind(marker)
    if pos < 0:
        raise SystemExit(f"missing terminal marker {EXPECTED_STATUS}")
    start = text.find("{", pos)
    if start < 0:
        raise SystemExit("receipt JSON missing after terminal marker")
    decoder = json.JSONDecoder()
    value, end = decoder.raw_decode(text[start:])
    if not isinstance(value, dict):
        raise SystemExit("receipt JSON is not an object")
    return value


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label} mismatch: observed={actual!r} expected={expected!r}")


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SystemExit(f"{label} must be object")
    return value


def require_zero_authority(authority: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for key in sorted(REQUIRED_ZERO_AUTHORITY):
        value = authority.get(key, 0)
        observed[key] = value
        if value != 0:
            raise SystemExit(f"{prefix}.{key} must be 0, observed {value!r}")
    return observed


def require_auth_bootstrap(receipt: Mapping[str, Any]) -> dict[str, Any]:
    auth_bootstrap = require_mapping(receipt.get("auth_bootstrap"), "receipt.auth_bootstrap")
    backend_source = auth_bootstrap.get("backend_token_source")
    owner_source = auth_bootstrap.get("owner_subject_hash_source")
    if backend_source not in ALLOWED_AUTH_BOOTSTRAP_SOURCES:
        raise SystemExit(f"unexpected backend token source: {backend_source!r}")
    if owner_source not in ALLOWED_AUTH_BOOTSTRAP_SOURCES:
        raise SystemExit(f"unexpected owner hash source: {owner_source!r}")
    require_equal(auth_bootstrap.get("secret_values_exposed"), False, "auth_bootstrap.secret_values_exposed")
    require_equal(auth_bootstrap.get("base_container_env_mutated"), False, "auth_bootstrap.base_container_env_mutated")
    require_equal(auth_bootstrap.get("candidate_env_only"), True, "auth_bootstrap.candidate_env_only")
    require_equal(auth_bootstrap.get("localhost_only"), True, "auth_bootstrap.localhost_only")
    return dict(auth_bootstrap)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt-log", required=True)
    parser.add_argument("--binding-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    receipt_log = pathlib.Path(args.receipt_log)
    binding_path = pathlib.Path(args.binding_json)
    output = pathlib.Path(args.output)
    receipt = load_receipt_from_log(receipt_log)
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if not isinstance(binding, dict):
        raise SystemExit("binding JSON must be object")

    require_equal(receipt.get("status"), EXPECTED_STATUS, "receipt.status")
    receipt_binding = require_mapping(receipt.get("binding"), "receipt.binding")
    require_equal(receipt_binding.get("release_id"), EXPECTED_RELEASE_ID, "binding.release_id")
    require_equal(receipt_binding.get("qdrant_collection"), EXPECTED_QDRANT_COLLECTION, "binding.qdrant_collection")
    require_equal(receipt_binding.get("source_head_sha"), EXPECTED_SOURCE_HEAD_SHA, "binding.source_head_sha")
    require_equal(receipt_binding.get("source_commit_sha"), EXPECTED_SOURCE_COMMIT_SHA, "binding.source_commit_sha")
    require_equal(receipt_binding.get("admission_sha256"), EXPECTED_ADMISSION_SHA256, "binding.admission_sha256")
    require_equal(receipt_binding.get("semantic_point_count"), EXPECTED_SEMANTIC_POINT_COUNT, "binding.semantic_point_count")
    require_equal(receipt_binding.get("node_count"), EXPECTED_NODE_COUNT, "binding.node_count")
    require_equal(receipt_binding.get("edge_count"), EXPECTED_EDGE_COUNT, "binding.edge_count")

    for key in ("release_id", "qdrant_collection", "source_head_sha", "source_commit_sha", "admission_sha256", "semantic_point_count", "node_count", "edge_count"):
        require_equal(binding.get(key), receipt_binding.get(key), f"binding_json.{key}")

    endpoint = require_mapping(receipt.get("endpoint"), "receipt.endpoint")
    require_equal(endpoint.get("host"), "127.0.0.1", "endpoint.host")
    if int(endpoint.get("host_port", 0)) == FORBIDDEN_PRODUCTION_PORT:
        raise SystemExit("isolated runtime bound forbidden production host_port 18087")
    if int(endpoint.get("host_port", 0)) <= 0:
        raise SystemExit("endpoint.host_port invalid")
    require_equal(endpoint.get("query_path"), "/api/m26/query", "endpoint.query_path")
    require_equal(endpoint.get("health_path"), "/api/m26/health", "endpoint.health_path")

    health = require_mapping(receipt.get("health"), "receipt.health")
    require_equal(health.get("status"), "ok", "health.status")
    health_mutations = require_mapping(health.get("mutations"), "health.mutations")
    for key in ("canonical_writes", "production_pointer_mutations", "qdrant_write_operations"):
        require_equal(health_mutations.get(key), 0, f"health.mutations.{key}")
    canonical_runtime = require_mapping(health.get("canonical_runtime"), "health.canonical_runtime")
    build_sha = str(canonical_runtime.get("build_sha") or "")
    if EXPECTED_RELEASE_ID not in build_sha or "m26-e4-v3-isolated" not in build_sha:
        raise SystemExit(f"health canonical build_sha not isolated M26 E4 V3: {build_sha!r}")

    auth_bootstrap = require_auth_bootstrap(receipt)
    authority = require_mapping(receipt.get("authority"), "receipt.authority")
    authority_zero = require_zero_authority(authority, "receipt.authority")

    verification = {
        "schema_version": "m26-e4-v3-oracle-isolated-runtime-verification/v1",
        "status": "M26_E4_V3_ORACLE_ISOLATED_RUNTIME_VERIFICATION_PASS",
        "verified_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "receipt_log_sha256": hashlib.sha256(receipt_log.read_bytes()).hexdigest(),
        "binding_json_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "receipt_sha256": sha256_value(receipt),
        "release_id": EXPECTED_RELEASE_ID,
        "source_head_sha": EXPECTED_SOURCE_HEAD_SHA,
        "qdrant_collection": EXPECTED_QDRANT_COLLECTION,
        "host_port": int(endpoint.get("host_port")),
        "candidate_container": receipt.get("candidate_container"),
        "base_container": receipt.get("base_container"),
        "health_status": health.get("status"),
        "health_mutations": dict(health_mutations),
        "auth_bootstrap": auth_bootstrap,
        "authority_zero": authority_zero,
        "gates": {
            "terminal_marker_present": True,
            "binding_identity": "PASS",
            "non_production_port": "PASS",
            "health_ok": "PASS",
            "health_no_mutations": "PASS",
            "isolated_auth_bootstrap": "PASS",
            "authority_no_mutations": "PASS",
            "e5_not_consumed": "PASS",
        },
    }
    verification["verification_sha256"] = sha256_value(verification)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("M26_E4_V3_ORACLE_ISOLATED_RUNTIME_VERIFICATION_PASS")
    print(json.dumps({
        "release_id": EXPECTED_RELEASE_ID,
        "host_port": verification["host_port"],
        "receipt_sha256": verification["receipt_sha256"],
        "verification_sha256": verification["verification_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
