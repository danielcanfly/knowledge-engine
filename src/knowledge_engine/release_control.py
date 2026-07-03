from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
PROMOTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{7,127}$")


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_object(store: ObjectStore, key: str) -> tuple[bytes, dict[str, Any]]:
    data = store.get(key)
    try:
        value = json.loads(data)
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"invalid JSON object: {key}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"object root must be a JSON object: {key}")
    return data, value


def _require_release_id(value: str, field: str) -> None:
    if not RELEASE_ID_RE.fullmatch(value):
        raise IntegrityError(f"{field} is not a valid release ID")


def _require_sha256(value: str, field: str) -> None:
    if not SHA256_RE.fullmatch(value):
        raise IntegrityError(f"{field} is not a lowercase SHA-256")


@dataclass(frozen=True)
class PromotionRequest:
    promotion_id: str
    candidate_channel: str
    candidate_release_id: str
    candidate_manifest_sha256: str
    expected_previous_release_id: str
    expected_previous_manifest_sha256: str
    source_sha: str
    builder_sha: str
    foundation_sha: str
    actor: str
    reason: str

    def validate(self) -> None:
        if not PROMOTION_ID_RE.fullmatch(self.promotion_id):
            raise IntegrityError("promotion_id has an invalid format")
        if self.candidate_channel == "production" or not self.candidate_channel.startswith(
            "candidate-source-"
        ):
            raise IntegrityError("candidate_channel must start with candidate-source-")
        _require_release_id(self.candidate_release_id, "candidate_release_id")
        _require_release_id(
            self.expected_previous_release_id,
            "expected_previous_release_id",
        )
        _require_sha256(
            self.candidate_manifest_sha256,
            "candidate_manifest_sha256",
        )
        _require_sha256(
            self.expected_previous_manifest_sha256,
            "expected_previous_manifest_sha256",
        )
        for field_name, value in (
            ("source_sha", self.source_sha),
            ("builder_sha", self.builder_sha),
            ("foundation_sha", self.foundation_sha),
        ):
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise IntegrityError(f"{field_name} must be an exact commit SHA")
        if not self.actor.strip():
            raise IntegrityError("actor is required")
        if len(self.reason.strip()) < 8:
            raise IntegrityError("reason must contain at least 8 characters")


@dataclass(frozen=True)
class PromotionReceipt:
    schema_version: str
    promotion_id: str
    status: str
    actor: str
    reason: str
    source_sha: str
    builder_sha: str
    foundation_sha: str
    candidate_channel: str
    candidate_release_id: str
    candidate_manifest_sha256: str
    previous_release_id: str
    previous_manifest_sha256: str
    previous_pointer_sha256: str
    promoted_pointer_sha256: str
    promoted_at: str
    journal_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RollbackReceipt:
    schema_version: str
    promotion_id: str
    status: str
    restored_release_id: str
    restored_manifest_sha256: str
    restored_pointer_sha256: str
    rolled_back_at: str
    rollback_journal_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _journal_key(promotion_id: str) -> str:
    return f"release-control/promotions/{promotion_id}.json"


def _rollback_journal_key(promotion_id: str) -> str:
    return f"release-control/rollbacks/{promotion_id}.json"


def promote_candidate(
    *,
    store: ObjectStore,
    request: PromotionRequest,
    promoted_at: str | None = None,
) -> PromotionReceipt:
    request.validate()
    production_key = "channels/production.json"
    candidate_key = f"channels/{request.candidate_channel}.json"
    journal_key = _journal_key(request.promotion_id)

    existing_journal = store.head(journal_key)
    if existing_journal is not None:
        _, existing = _load_object(store, journal_key)
        if existing.get("request") != asdict(request):
            raise ReleaseConflictError(
                "promotion_id already exists with a different request"
            )
        receipt = existing.get("receipt")
        if not isinstance(receipt, dict):
            raise IntegrityError("promotion journal receipt is missing")
        return PromotionReceipt(**receipt)

    candidate_bytes, candidate = _load_object(store, candidate_key)
    if candidate.get("release_id") != request.candidate_release_id:
        raise IntegrityError("candidate release ID does not match request")
    if candidate.get("manifest_sha256") != request.candidate_manifest_sha256:
        raise IntegrityError("candidate manifest hash does not match request")
    manifest_key = candidate.get("manifest_key")
    if not isinstance(manifest_key, str) or not manifest_key:
        raise IntegrityError("candidate pointer is missing manifest_key")
    manifest_bytes, manifest = _load_object(store, manifest_key)
    if sha256_bytes(manifest_bytes) != request.candidate_manifest_sha256:
        raise IntegrityError("candidate manifest bytes do not match requested hash")
    if manifest.get("release_id") != request.candidate_release_id:
        raise IntegrityError("candidate manifest release ID mismatch")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("commit_sha") != request.source_sha:
        raise IntegrityError("candidate source SHA mismatch")
    if manifest.get("foundation_commit_sha") != request.foundation_sha:
        raise IntegrityError("candidate foundation SHA mismatch")

    production_head = store.head(production_key)
    if production_head is None:
        raise IntegrityError("production pointer does not exist")
    production_bytes, production = _load_object(store, production_key)
    if production.get("release_id") != request.expected_previous_release_id:
        raise ReleaseConflictError("production release precondition failed")
    if production.get("manifest_sha256") != request.expected_previous_manifest_sha256:
        raise ReleaseConflictError("production manifest precondition failed")

    timestamp = promoted_at or _utc_now()
    promoted_pointer = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": request.candidate_release_id,
        "manifest_key": manifest_key,
        "manifest_sha256": request.candidate_manifest_sha256,
        "promoted_at": timestamp,
    }
    promoted_bytes = _canonical_json(promoted_pointer)
    store.put(
        production_key,
        promoted_bytes,
        content_type="application/json",
        sha256=sha256_bytes(promoted_bytes),
        expected_etag=production_head.etag,
    )
    if store.get(production_key) != promoted_bytes:
        raise IntegrityError("production pointer verification failed")

    receipt = PromotionReceipt(
        schema_version="1.0",
        promotion_id=request.promotion_id,
        status="promoted",
        actor=request.actor,
        reason=request.reason.strip(),
        source_sha=request.source_sha,
        builder_sha=request.builder_sha,
        foundation_sha=request.foundation_sha,
        candidate_channel=request.candidate_channel,
        candidate_release_id=request.candidate_release_id,
        candidate_manifest_sha256=request.candidate_manifest_sha256,
        previous_release_id=request.expected_previous_release_id,
        previous_manifest_sha256=request.expected_previous_manifest_sha256,
        previous_pointer_sha256=sha256_bytes(production_bytes),
        promoted_pointer_sha256=sha256_bytes(promoted_bytes),
        promoted_at=timestamp,
        journal_key=journal_key,
    )
    journal = {
        "schema_version": "1.0",
        "request": asdict(request),
        "candidate_pointer_sha256": sha256_bytes(candidate_bytes),
        "previous_pointer": production,
        "previous_pointer_bytes_sha256": sha256_bytes(production_bytes),
        "promoted_pointer": promoted_pointer,
        "receipt": receipt.to_dict(),
    }
    journal_bytes = _canonical_json(journal)
    store.put(
        journal_key,
        journal_bytes,
        content_type="application/json",
        sha256=sha256_bytes(journal_bytes),
        only_if_absent=True,
    )
    return receipt


def rollback_promotion(
    *,
    store: ObjectStore,
    promotion_id: str,
    rolled_back_at: str | None = None,
) -> RollbackReceipt:
    if not PROMOTION_ID_RE.fullmatch(promotion_id):
        raise IntegrityError("promotion_id has an invalid format")
    rollback_key = _rollback_journal_key(promotion_id)
    if store.head(rollback_key) is not None:
        _, existing = _load_object(store, rollback_key)
        receipt = existing.get("receipt")
        if not isinstance(receipt, dict):
            raise IntegrityError("rollback journal receipt is missing")
        return RollbackReceipt(**receipt)

    _, journal = _load_object(store, _journal_key(promotion_id))
    request = journal.get("request")
    previous_pointer = journal.get("previous_pointer")
    receipt_data = journal.get("receipt")
    if not isinstance(request, dict) or not isinstance(previous_pointer, dict):
        raise IntegrityError("promotion journal is incomplete")
    if not isinstance(receipt_data, dict):
        raise IntegrityError("promotion receipt is missing")

    production_key = "channels/production.json"
    production_head = store.head(production_key)
    if production_head is None:
        raise IntegrityError("production pointer does not exist")
    production_bytes, production = _load_object(store, production_key)
    if production.get("release_id") != request.get("candidate_release_id"):
        raise ReleaseConflictError(
            "production no longer points to the promoted release"
        )
    if production.get("manifest_sha256") != request.get(
        "candidate_manifest_sha256"
    ):
        raise ReleaseConflictError(
            "production manifest no longer matches the promoted release"
        )
    if sha256_bytes(production_bytes) != receipt_data.get(
        "promoted_pointer_sha256"
    ):
        raise ReleaseConflictError("production pointer bytes changed after promotion")

    previous_bytes = _canonical_json(previous_pointer)
    store.put(
        production_key,
        previous_bytes,
        content_type="application/json",
        sha256=sha256_bytes(previous_bytes),
        expected_etag=production_head.etag,
    )
    if store.get(production_key) != previous_bytes:
        raise IntegrityError("rollback pointer verification failed")

    timestamp = rolled_back_at or _utc_now()
    rollback_receipt = RollbackReceipt(
        schema_version="1.0",
        promotion_id=promotion_id,
        status="rolled_back",
        restored_release_id=str(previous_pointer["release_id"]),
        restored_manifest_sha256=str(previous_pointer["manifest_sha256"]),
        restored_pointer_sha256=sha256_bytes(previous_bytes),
        rolled_back_at=timestamp,
        rollback_journal_key=rollback_key,
    )
    rollback_journal = {
        "schema_version": "1.0",
        "promotion_id": promotion_id,
        "production_before_rollback_sha256": sha256_bytes(production_bytes),
        "restored_pointer": previous_pointer,
        "receipt": rollback_receipt.to_dict(),
    }
    rollback_bytes = _canonical_json(rollback_journal)
    store.put(
        rollback_key,
        rollback_bytes,
        content_type="application/json",
        sha256=sha256_bytes(rollback_bytes),
        only_if_absent=True,
    )
    return rollback_receipt
