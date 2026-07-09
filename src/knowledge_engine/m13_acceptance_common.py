from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .compiler_contract_v1 import put_immutable
from .m13_contracts import stable_json_bytes
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectMetadata, ObjectStore, sha256_bytes

ACCEPTANCE_SCHEMA = "knowledge-engine-m13-acceptance/v1"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,100}$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,180}$")
SHA40_RE = re.compile(r"^[a-f0-9]{40}$")

SOURCE_REPOSITORY = "acceptance/knowledge-source"
BUILDER_ID = "m13-acceptance-builder-v1"
FOUNDATION_SHA256 = "f" * 64

P0_ID = "20260710T000000Z-000000000000"
P1_ID = "20260710T010000Z-111111111111"
P2_ID = "20260710T020000Z-222222222222"
P3_ID = "20260710T030000Z-333333333333"
BR_ID = "20260710T001000Z-bbbbbbbbbbbb"
CS_ID = "20260710T002000Z-cccccccccccc"

S_ALPHA = "1" * 40
S_BETA = "b" * 40
S_C = "c" * 40
S_D = "2" * 40
S_E = "3" * 40


class M13AcceptanceError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


class IsolatedObjectStore:
    """Prefix every object key and forbid deletion.

    The wrapped store may be the real R2 bucket. M13 sees a complete isolated
    object store rooted at ``prefix`` and cannot address the real production
    pointer or any object outside that root.
    """

    def __init__(self, store: ObjectStore, prefix: str) -> None:
        normalized = prefix.strip("/")
        if not PREFIX_RE.fullmatch(normalized) or ".." in normalized.split("/"):
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_PREFIX_INVALID",
                "acceptance prefix is invalid",
                prefix=prefix,
            )
        self.store = store
        self.prefix = normalized

    def physical_key(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise M13AcceptanceError(
                "M13_ACCEPTANCE_KEY_INVALID", "logical object key is invalid", key=key
            )
        return f"{self.prefix}/{key}"

    def _logical_metadata(self, key: str, value: ObjectMetadata) -> ObjectMetadata:
        return ObjectMetadata(
            key=key,
            bytes=value.bytes,
            etag=value.etag,
            sha256=value.sha256,
            content_type=value.content_type,
        )

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str | None = None,
        expected_etag: str | None = None,
        only_if_absent: bool = False,
    ) -> ObjectMetadata:
        value = self.store.put(
            self.physical_key(key),
            data,
            content_type=content_type,
            sha256=sha256,
            expected_etag=expected_etag,
            only_if_absent=only_if_absent,
        )
        return self._logical_metadata(key, value)

    def get(self, key: str) -> bytes:
        return self.store.get(self.physical_key(key))

    def head(self, key: str) -> ObjectMetadata | None:
        value = self.store.head(self.physical_key(key))
        return None if value is None else self._logical_metadata(key, value)

    def delete(self, key: str) -> None:
        raise M13AcceptanceError(
            "M13_ACCEPTANCE_DELETE_FORBIDDEN",
            "acceptance objects are retained and cannot be deleted",
            key=key,
        )


@dataclass(frozen=True)
class AcceptanceRuntimeReceipt:
    run_id: str
    isolation_prefix: str
    acceptance_id: str
    report_key: str
    report_sha256: str
    real_production_pointer_sha256_before: str
    real_production_pointer_sha256_after: str
    real_production_pointer_unchanged: bool
    engine_sha: str
    canonical_source_sha: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": f"{ACCEPTANCE_SCHEMA}/runtime-receipt",
            "run_id": self.run_id,
            "isolation_prefix": self.isolation_prefix,
            "acceptance_id": self.acceptance_id,
            "report_key": self.report_key,
            "report_sha256": self.report_sha256,
            "real_production_pointer_sha256_before": self.real_production_pointer_sha256_before,
            "real_production_pointer_sha256_after": self.real_production_pointer_sha256_after,
            "real_production_pointer_unchanged": self.real_production_pointer_unchanged,
            "engine_sha": self.engine_sha,
            "canonical_source_sha": self.canonical_source_sha,
            "governance": {
                **GOVERNANCE_NO_WRITE,
                "isolated_acceptance_write_permitted": True,
            },
        }


class _Clock:
    def __init__(self) -> None:
        self.base = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)
        self.index = 0

    def next(self, seconds: int = 1) -> str:
        self.index += seconds
        value = self.base + timedelta(seconds=self.index)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def future(self, seconds: int) -> str:
        value = self.base + timedelta(seconds=self.index + seconds)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Tracker:
    def __init__(self, store: ObjectStore) -> None:
        self.store = store
        self.hashes: dict[str, str] = {}

    def record(self, *keys: str | None) -> None:
        for key in keys:
            if key is None:
                continue
            data = self.store.get(key)
            digest = sha256_bytes(data)
            previous = self.hashes.get(key)
            if previous is not None and previous != digest:
                raise M13AcceptanceError(
                    "M13_ACCEPTANCE_EVIDENCE_OVERWRITTEN",
                    "immutable evidence changed bytes",
                    key=key,
                    expected=previous,
                    observed=digest,
                )
            self.hashes[key] = digest

    def verify(self) -> None:
        for key, expected in sorted(self.hashes.items()):
            observed = sha256_bytes(self.store.get(key))
            if observed != expected:
                raise M13AcceptanceError(
                    "M13_ACCEPTANCE_EVIDENCE_OVERWRITTEN",
                    "tracked evidence changed bytes",
                    key=key,
                    expected=expected,
                    observed=observed,
                )


def _hash_identity(value: dict[str, Any], prefix: str) -> str:
    digest = hashlib.sha256(stable_json_bytes(value)).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _put_json(store: ObjectStore, key: str, value: dict[str, Any]) -> str:
    data = stable_json_bytes(value)
    replay = put_immutable(store, key, data)
    return "replay" if replay else "created"
