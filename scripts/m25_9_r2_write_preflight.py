from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from knowledge_engine.config import Settings
from knowledge_engine.errors import ReleaseConflictError
from knowledge_engine.storage import ObjectStore, create_object_store, sha256_bytes

SCHEMA_VERSION = "knowledge-engine-m25-9-r2-write-preflight/v1"


def _error_details(exc: Exception) -> tuple[str, int | None, str]:
    if isinstance(exc, ClientError):
        response = exc.response if isinstance(exc.response, dict) else {}
        error = response.get("Error", {})
        metadata = response.get("ResponseMetadata", {})
        code = str(error.get("Code") or type(exc).__name__)
        status_raw = metadata.get("HTTPStatusCode")
        status = int(status_raw) if isinstance(status_raw, int) else None
        if code == "AccessDenied" or status == 403:
            category = "r2_put_object_access_denied"
        elif code in {"Unauthorized", "InvalidAccessKeyId"} or status == 401:
            category = "r2_authentication_failed"
        elif code == "SignatureDoesNotMatch":
            category = "r2_signature_mismatch"
        else:
            category = "r2_client_error"
        return category, status, code
    if isinstance(exc, ReleaseConflictError):
        return "r2_canary_key_conflict", None, type(exc).__name__
    return "r2_unexpected_error", None, type(exc).__name__


def run_preflight(
    *,
    store: ObjectStore,
    key: str,
    payload: bytes,
    identity: dict[str, Any],
) -> dict[str, Any]:
    digest = sha256_bytes(payload)
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "payload_bytes": len(payload),
        "payload_sha256": digest,
        "identity": identity,
        "put_succeeded": False,
        "read_verified": False,
        "delete_succeeded": False,
        "residual_object_present": None,
        "bounded_mutation_count": 0,
        "secret_values_recorded": False,
    }
    created = False
    failure: Exception | None = None
    try:
        if store.head(key) is not None:
            raise ReleaseConflictError("R2 write-preflight canary key already exists")
        store.put(
            key,
            payload,
            content_type="application/json",
            sha256=digest,
            only_if_absent=True,
        )
        created = True
        evidence["put_succeeded"] = True
        evidence["bounded_mutation_count"] = 1
        remote = store.get(key)
        if len(remote) != len(payload) or sha256_bytes(remote) != digest:
            raise RuntimeError("R2 write-preflight read-back digest mismatch")
        evidence["read_verified"] = True
    except Exception as exc:
        failure = exc
    finally:
        if created:
            try:
                store.delete(key)
                evidence["delete_succeeded"] = True
                evidence["bounded_mutation_count"] = 2
            except Exception as exc:
                if failure is None:
                    failure = exc
        try:
            evidence["residual_object_present"] = store.head(key) is not None
        except Exception as exc:
            evidence["residual_object_present"] = None
            if failure is None:
                failure = exc

    if failure is None and evidence["residual_object_present"] is False:
        evidence["status"] = "pass"
        evidence["root_cause_classification"] = "r2_object_read_write_capability_pass"
    else:
        category, http_status, error_code = _error_details(
            failure or RuntimeError("R2 write-preflight residual object detected")
        )
        if evidence["residual_object_present"] is True:
            category = "r2_canary_cleanup_failed_residual_present"
        evidence["status"] = "fail"
        evidence["root_cause_classification"] = category
        evidence["http_status"] = http_status
        evidence["error_code"] = error_code
    evidence["zero_residual_objects"] = (
        evidence["residual_object_present"] is False
    )
    evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return evidence


def _identity(settings: Settings) -> dict[str, str | bool]:
    endpoint = settings.r2_endpoint_url or ""
    bucket = settings.r2_bucket or ""
    access_key = settings.r2_access_key_id or ""
    return {
        "backend_is_r2": settings.object_store_backend == "r2",
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
        "bucket_sha256": hashlib.sha256(bucket.encode()).hexdigest(),
        "access_key_id_sha256": hashlib.sha256(access_key.encode()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)

    try:
        settings = Settings.from_env()
        if settings.object_store_backend != "r2":
            raise RuntimeError("R2 write-preflight requires OBJECT_STORE_BACKEND=r2")
        payload = (
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "engine_sha": args.engine_sha,
                    "run_id": args.run_id,
                    "purpose": "bounded-r2-object-write-capability-check",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        evidence = run_preflight(
            store=create_object_store(settings),
            key=args.key,
            payload=payload,
            identity=_identity(settings),
        )
    except Exception as exc:
        category, http_status, error_code = _error_details(exc)
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "root_cause_classification": category,
            "http_status": http_status,
            "error_code": error_code,
            "bounded_mutation_count": 0,
            "residual_object_present": None,
            "zero_residual_objects": False,
            "secret_values_recorded": False,
        }
        evidence["evidence_sha256"] = hashlib.sha256(
            json.dumps(
                evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    args.evidence_output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
