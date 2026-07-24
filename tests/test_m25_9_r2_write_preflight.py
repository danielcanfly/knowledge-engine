from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError
from scripts.m25_9_r2_write_preflight import run_preflight

from knowledge_engine.storage import FileObjectStore


def _identity() -> dict[str, Any]:
    return {
        "backend_is_r2": True,
        "endpoint_sha256": "e" * 64,
        "bucket_sha256": "b" * 64,
        "access_key_id_sha256": "a" * 64,
    }


def test_r2_write_preflight_passes_and_leaves_no_residual(tmp_path):
    store = FileObjectStore(tmp_path / "store")
    evidence = run_preflight(
        store=store,
        key="diagnostics/m25-9/run-1.json",
        payload=b'{"ok":true}\n',
        identity=_identity(),
    )
    assert evidence["status"] == "pass"
    assert evidence["root_cause_classification"] == (
        "r2_object_read_write_capability_pass"
    )
    assert evidence["put_succeeded"] is True
    assert evidence["read_verified"] is True
    assert evidence["delete_succeeded"] is True
    assert evidence["bounded_mutation_count"] == 2
    assert evidence["zero_residual_objects"] is True
    assert store.head("diagnostics/m25-9/run-1.json") is None


class AccessDeniedStore:
    def head(self, key):
        del key
        return None

    def put(self, key, data, **kwargs):
        del key, data, kwargs
        raise ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "denied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )

    def get(self, key):
        raise AssertionError(key)

    def delete(self, key):
        raise AssertionError(key)


def test_r2_write_preflight_classifies_access_denied_without_mutation():
    evidence = run_preflight(
        store=AccessDeniedStore(),
        key="diagnostics/m25-9/run-2.json",
        payload=b"{}\n",
        identity=_identity(),
    )
    assert evidence["status"] == "fail"
    assert evidence["root_cause_classification"] == (
        "r2_put_object_access_denied"
    )
    assert evidence["http_status"] == 403
    assert evidence["error_code"] == "AccessDenied"
    assert evidence["bounded_mutation_count"] == 0
    assert evidence["residual_object_present"] is False


class DigestMismatchStore(FileObjectStore):
    def get(self, key):
        del key
        return b"wrong"


def test_r2_write_preflight_cleans_up_after_readback_mismatch(tmp_path):
    store = DigestMismatchStore(tmp_path / "store")
    key = "diagnostics/m25-9/run-3.json"
    evidence = run_preflight(
        store=store,
        key=key,
        payload=b"expected\n",
        identity=_identity(),
    )
    assert evidence["status"] == "fail"
    assert evidence["delete_succeeded"] is True
    assert evidence["bounded_mutation_count"] == 2
    assert evidence["zero_residual_objects"] is True
    assert store.head(key) is None


def test_r2_write_preflight_does_not_delete_preexisting_key(tmp_path):
    store = FileObjectStore(tmp_path / "store")
    key = "diagnostics/m25-9/preexisting.json"
    store.put(
        key,
        b"existing",
        content_type="application/json",
    )
    evidence = run_preflight(
        store=store,
        key=key,
        payload=b"new",
        identity=_identity(),
    )
    assert evidence["status"] == "fail"
    assert evidence["root_cause_classification"] == (
        "r2_canary_cleanup_failed_residual_present"
    )
    assert evidence["bounded_mutation_count"] == 0
    assert store.get(key) == b"existing"
