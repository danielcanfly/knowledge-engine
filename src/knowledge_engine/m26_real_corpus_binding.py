from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from .errors import IntegrityError
from .m26_production_authority import load_contract
from .storage import ObjectStore, sha256_bytes

RECEIPT_SCHEMA = "knowledge-engine-m26-12-real-corpus-receipt/v1"
PRODUCTION_MANIFEST_KEY = (
    "releases/m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043/"
    "promotion/m25-10-production-manifest.json"
)
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|password|authorization|bearer|access[_-]?token)"
)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityError(f"M26-REAL-001 {label} must be an object")
    return value


def _decode_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(data), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"M26-REAL-002 invalid JSON: {label}") from exc


def _qdrant_request(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    collection: str,
    operation: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    escaped = urllib.parse.quote(collection, safe="")
    response = client.post(
        f"{base_url.rstrip('/')}/collections/{escaped}/points/{operation}",
        headers={"api-key": api_key, "Accept": "application/json"},
        json=dict(body),
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise IntegrityError(f"M26-REAL-003 Qdrant {operation} returned non-ok")
    return value


def _qdrant_filter(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "must": [
            {"key": key, "match": {"value": value}}
            for key, value in sorted(values.items())
        ]
    }


def _validate_manifest(
    manifest: Mapping[str, Any], entry: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    identity = entry["production_identity"]
    if manifest.get("schema_version") != "knowledge-engine-release/v1":
        raise IntegrityError("M26-REAL-004 manifest schema drift")
    if manifest.get("release_id") != identity["release_id"]:
        raise IntegrityError("M26-REAL-005 release identity drift")
    if manifest.get("status") != "production":
        raise IntegrityError("M26-REAL-006 release is not production")

    authority = _object(manifest.get("authority"), "manifest authority")
    if authority.get("production_pointer_authorized") is not True:
        raise IntegrityError("M26-REAL-007 production pointer authority missing")
    if authority.get("public_production_traffic_authorized") is not False:
        raise IntegrityError("M26-REAL-008 public traffic authority drift")

    identities = _object(manifest.get("identities"), "manifest identities")
    expected = {
        "engine_commit_sha": identity["engine_sha"],
        "source_commit_sha": identity["source_sha"],
        "foundation_commit_sha": identity["foundation_sha"],
        "admission_sha256": identity["admission_sha256"],
    }
    for key, value in expected.items():
        if identities.get(key) != value:
            raise IntegrityError(f"M26-REAL-009 manifest identity drift: {key}")

    counts = _object(manifest.get("counts"), "manifest counts")
    for key, value in policy["expected_counts"].items():
        if counts.get(key) != value:
            raise IntegrityError(f"M26-REAL-010 population drift: {key}")


def _bounded_payload(
    payload: Mapping[str, Any], policy: Mapping[str, Any], expected: Mapping[str, Any]
) -> dict[str, Any]:
    for key, value in expected.items():
        if payload.get(key) != value:
            raise IntegrityError(f"M26-REAL-011 Qdrant payload drift: {key}")
    if any(SECRET_PATTERN.search(str(key)) for key in payload):
        raise IntegrityError("M26-REAL-012 secret-like payload key")
    if "text" in payload or "body" in payload or "content" in payload:
        raise IntegrityError("M26-REAL-013 raw corpus text present in Qdrant payload")
    allowlist = set(policy["evidence"]["payload_allowlist"])
    bounded = {key: payload[key] for key in sorted(payload) if key in allowlist}
    return bounded


def bind_real_corpus(
    *,
    root: Path,
    store: ObjectStore,
    qdrant_url: str,
    qdrant_api_key: str,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    pilot = root / "pilot" / "m26"
    entry = load_contract(pilot / "m26-12-entry-contract.json")
    policy = load_contract(pilot / "m26-12-retrieval-policy.json")
    identity = entry["production_identity"]

    pointer_bytes = store.get(identity["pointer_key"])
    pointer = _decode_json(pointer_bytes, "production pointer")
    if pointer.get("channel") != "production":
        raise IntegrityError("M26-REAL-014 production channel drift")
    if pointer.get("release_id") != identity["release_id"]:
        raise IntegrityError("M26-REAL-015 production pointer release drift")
    if pointer.get("manifest_key") != PRODUCTION_MANIFEST_KEY:
        raise IntegrityError("M26-REAL-016 production manifest key drift")

    manifest_bytes = store.get(pointer["manifest_key"])
    manifest_sha = sha256_bytes(manifest_bytes)
    if pointer.get("manifest_sha256") != manifest_sha:
        raise IntegrityError("M26-REAL-017 production manifest digest drift")
    manifest = _decode_json(manifest_bytes, "production manifest")
    _validate_manifest(manifest, entry, policy)

    qdrant = policy["qdrant"]
    authority_filter = _qdrant_filter(qdrant["filter"])
    with httpx.Client(timeout=timeout_seconds) as client:
        count_response = _qdrant_request(
            client=client,
            base_url=qdrant_url,
            api_key=qdrant_api_key,
            collection=identity["qdrant_collection"],
            operation="count",
            body={"exact": True, "filter": authority_filter},
        )
        count = _object(count_response.get("result"), "Qdrant count").get("count")
        if count != qdrant["expected_point_count"]:
            raise IntegrityError("M26-REAL-018 Qdrant point count drift")

        scroll_response = _qdrant_request(
            client=client,
            base_url=qdrant_url,
            api_key=qdrant_api_key,
            collection=identity["qdrant_collection"],
            operation="scroll",
            body={
                "filter": authority_filter,
                "limit": qdrant["sample_limit"],
                "with_payload": True,
                "with_vector": False,
            },
        )
    rows = _object(scroll_response.get("result"), "Qdrant scroll").get("points")
    if not isinstance(rows, list) or len(rows) != qdrant["sample_limit"]:
        raise IntegrityError("M26-REAL-019 Qdrant sample population drift")

    samples = []
    expected_payload = qdrant["filter"]
    for row in rows:
        if not isinstance(row, Mapping) or "vector" in row:
            raise IntegrityError("M26-REAL-020 vector or malformed row returned")
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            raise IntegrityError("M26-REAL-021 missing Qdrant payload")
        bounded = _bounded_payload(payload, policy, expected_payload)
        samples.append(
            {
                "point_id_sha256": hashlib.sha256(
                    str(row.get("id")).encode("utf-8")
                ).hexdigest(),
                "payload": bounded,
            }
        )

    samples.sort(key=lambda item: item["point_id_sha256"])
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "real_corpus_retrieval_binding_verified",
        "release": {
            "pointer_key": identity["pointer_key"],
            "pointer_sha256": sha256_bytes(pointer_bytes),
            "release_id": identity["release_id"],
            "manifest_key": pointer["manifest_key"],
            "manifest_sha256": manifest_sha,
            "engine_sha": identity["engine_sha"],
            "source_sha": identity["source_sha"],
            "foundation_sha": identity["foundation_sha"],
            "admission_sha256": identity["admission_sha256"],
            "counts": manifest["counts"],
        },
        "qdrant": {
            "collection": identity["qdrant_collection"],
            "filtered_point_count": count,
            "sample_count": len(samples),
            "samples": samples,
            "vectors_returned": False,
            "writes_performed": False,
        },
        "authority": {
            "r2_reads_performed": True,
            "qdrant_reads_performed": True,
            "live_provider_calls": False,
            "network_model_execution": False,
            "production_pointer_mutation": False,
            "qdrant_write": False,
            "public_traffic": False,
            "verified_final_answers": False,
            "raw_corpus_text_persisted": False,
            "secret_values_persisted": False,
        },
    }
