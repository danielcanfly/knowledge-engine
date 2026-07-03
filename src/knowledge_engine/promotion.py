from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,119}$")


def _json_bytes(value: Any) -> bytes:
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


def _read_json(store: ObjectStore, key: str) -> tuple[bytes, dict[str, Any]]:
    data = store.get(key)
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise IntegrityError(f"invalid JSON object: {key}") from exc
    if not isinstance(payload, dict):
        raise IntegrityError(f"JSON object must be a mapping: {key}")
    return data, payload


def _decode_pointer(intent: dict[str, Any], field: str) -> bytes:
    encoded = intent.get(field)
    if not isinstance(encoded, str):
        raise IntegrityError(f"promotion intent is missing {field}")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise IntegrityError(f"promotion intent contains invalid {field}") from exc


def _validate_sha(value: str, label: str) -> None:
    if not SHA_RE.fullmatch(value):
        raise IntegrityError(f"{label} must be an exact lowercase 40-character SHA")


def _validate_fields(
    payload: dict[str, Any],
    expected: dict[str, Any],
    *,
    label: str,
) -> None:
    for key, value in expected.items():
        if payload.get(key) != value:
            if key == "request_sha256":
                raise ReleaseConflictError(
                    "operation ID already belongs to a different request"
                )
            raise ReleaseConflictError(
                f"{label} {key} mismatch: expected {value!r}, got {payload.get(key)!r}"
            )


def _write_or_load_record(
    *,
    store: ObjectStore,
    key: str,
    payload: dict[str, Any],
    identity: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    if store.head(key) is None:
        data = _json_bytes(payload)
        try:
            store.put(
                key,
                data,
                content_type="application/json",
                sha256=sha256_bytes(data),
                only_if_absent=True,
            )
            return payload, False
        except ReleaseConflictError:
            pass
    _, existing = _read_json(store, key)
    _validate_fields(existing, identity, label=key)
    return existing, True


@dataclass(frozen=True)
class PromotionRequest:
    operation_id: str
    candidate_channel: str
    expected_release_id: str
    expected_manifest_sha256: str
    expected_source_repository: str
    expected_source_sha: str
    expected_foundation_sha: str
    control_plane_sha: str
    reason: str
    actor: str

    def validate(self) -> None:
        if not OPERATION_RE.fullmatch(self.operation_id):
            raise IntegrityError("operation_id must be 8-120 safe characters")
        if not self.candidate_channel.startswith("candidate-source-"):
            raise IntegrityError("candidate channel must start with candidate-source-")
        if self.candidate_channel == "production":
            raise IntegrityError("candidate channel cannot be production")
        if not self.expected_release_id:
            raise IntegrityError("expected_release_id is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.expected_manifest_sha256):
            raise IntegrityError("expected_manifest_sha256 must be lowercase SHA-256")
        if self.expected_source_repository != "danielcanfly/knowledge-source":
            raise IntegrityError("unexpected source repository")
        _validate_sha(self.expected_source_sha, "expected_source_sha")
        _validate_sha(self.expected_foundation_sha, "expected_foundation_sha")
        _validate_sha(self.control_plane_sha, "control_plane_sha")
        if not self.reason.strip():
            raise IntegrityError("promotion reason is required")
        if not self.actor.strip():
            raise IntegrityError("promotion actor is required")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionResult:
    operation_id: str
    status: str
    idempotent: bool
    previous_release_id: str
    release_id: str
    manifest_sha256: str
    source_sha: str
    foundation_sha: str
    control_plane_sha: str
    production_pointer_sha256: str
    intent_key: str
    receipt_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RollbackResult:
    operation_id: str
    status: str
    idempotent: bool
    restored_release_id: str
    replaced_release_id: str
    production_pointer_sha256: str
    receipt_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _operation_prefix(operation_id: str) -> str:
    return f"operations/promotions/{operation_id}"


def _validate_candidate(
    store: ObjectStore,
    request: PromotionRequest,
) -> dict[str, Any]:
    candidate_key = f"channels/{request.candidate_channel}.json"
    _, candidate = _read_json(store, candidate_key)
    expected_pointer = {
        "channel": request.candidate_channel,
        "release_id": request.expected_release_id,
        "manifest_sha256": request.expected_manifest_sha256,
    }
    for key, expected in expected_pointer.items():
        if candidate.get(key) != expected:
            raise IntegrityError(
                f"candidate pointer {key} mismatch: "
                f"expected {expected!r}, got {candidate.get(key)!r}"
            )
    manifest_key = candidate.get("manifest_key")
    if not isinstance(manifest_key, str) or not manifest_key:
        raise IntegrityError("candidate pointer is missing manifest_key")
    manifest_bytes, manifest = _read_json(store, manifest_key)
    if sha256_bytes(manifest_bytes) != request.expected_manifest_sha256:
        raise IntegrityError("candidate manifest bytes do not match expected SHA-256")
    if manifest.get("release_id") != request.expected_release_id:
        raise IntegrityError("candidate manifest release ID mismatch")
    if manifest.get("release_ready") is not True:
        raise IntegrityError("candidate manifest is not release-ready")
    quality = manifest.get("quality")
    if not isinstance(quality, dict) or quality.get("overall") != "passed":
        raise IntegrityError("candidate manifest quality did not pass")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise IntegrityError("candidate manifest source metadata is missing")
    expectations = {
        "repository": request.expected_source_repository,
        "commit_sha": request.expected_source_sha,
        "foundation_commit_sha": request.expected_foundation_sha,
        "dirty": False,
    }
    for key, expected in expectations.items():
        if source.get(key) != expected:
            raise IntegrityError(
                f"candidate source {key} mismatch: "
                f"expected {expected!r}, got {source.get(key)!r}"
            )
    return candidate


def _load_or_create_intent(
    *,
    store: ObjectStore,
    request: PromotionRequest,
    production_bytes: bytes,
    production: dict[str, Any],
    candidate: dict[str, Any],
    promoted_at: str,
) -> tuple[str, dict[str, Any], bool]:
    prefix = _operation_prefix(request.operation_id)
    key = f"{prefix}/intent.json"
    request_payload = request.to_dict()
    request_hash = sha256_bytes(_json_bytes(request_payload))
    target = {
        "schema_version": "1.0",
        "channel": "production",
        "release_id": candidate["release_id"],
        "manifest_key": candidate["manifest_key"],
        "manifest_sha256": candidate["manifest_sha256"],
        "promoted_at": promoted_at,
        "promotion_id": request.operation_id,
    }
    target_bytes = _json_bytes(target)
    proposed = {
        "schema_version": "1.0",
        "operation_id": request.operation_id,
        "request": request_payload,
        "request_sha256": request_hash,
        "created_at": promoted_at,
        "previous_pointer_b64": base64.b64encode(production_bytes).decode("ascii"),
        "previous_pointer_sha256": sha256_bytes(production_bytes),
        "previous_release_id": production.get("release_id"),
        "target_pointer_b64": base64.b64encode(target_bytes).decode("ascii"),
        "target_pointer_sha256": sha256_bytes(target_bytes),
        "target_release_id": target["release_id"],
    }
    intent, reused = _write_or_load_record(
        store=store,
        key=key,
        payload=proposed,
        identity={
            "operation_id": request.operation_id,
            "request_sha256": request_hash,
        },
    )
    return key, intent, reused


def promote_release(
    *,
    store: ObjectStore,
    request: PromotionRequest,
    promoted_at: str | None = None,
) -> PromotionResult:
    request.validate()
    candidate = _validate_candidate(store, request)
    production_key = "channels/production.json"
    production_head = store.head(production_key)
    if production_head is None:
        raise IntegrityError("production pointer does not exist")
    production_bytes, production = _read_json(store, production_key)

    intent_key, intent, reused_intent = _load_or_create_intent(
        store=store,
        request=request,
        production_bytes=production_bytes,
        production=production,
        candidate=candidate,
        promoted_at=promoted_at or _utc_now(),
    )
    previous_bytes = _decode_pointer(intent, "previous_pointer_b64")
    target_bytes = _decode_pointer(intent, "target_pointer_b64")
    if sha256_bytes(previous_bytes) != intent.get("previous_pointer_sha256"):
        raise IntegrityError("promotion intent previous pointer hash mismatch")
    if sha256_bytes(target_bytes) != intent.get("target_pointer_sha256"):
        raise IntegrityError("promotion intent target pointer hash mismatch")

    current_head = store.head(production_key)
    if current_head is None:
        raise IntegrityError("production pointer disappeared")
    current_bytes = store.get(production_key)
    idempotent = reused_intent
    if current_bytes == target_bytes:
        idempotent = True
    elif current_bytes == previous_bytes:
        store.put(
            production_key,
            target_bytes,
            content_type="application/json",
            sha256=sha256_bytes(target_bytes),
            expected_etag=current_head.etag,
        )
    else:
        raise ReleaseConflictError(
            "production pointer changed after promotion intent was created"
        )
    if store.get(production_key) != target_bytes:
        raise IntegrityError("production pointer verification failed after promotion")

    receipt_key = f"{_operation_prefix(request.operation_id)}/promotion-receipt.json"
    receipt, reused_receipt = _write_or_load_record(
        store=store,
        key=receipt_key,
        payload={
            "schema_version": "1.0",
            "operation_id": request.operation_id,
            "status": "promoted",
            "intent_key": intent_key,
            "previous_release_id": intent["previous_release_id"],
            "release_id": intent["target_release_id"],
            "manifest_sha256": request.expected_manifest_sha256,
            "source_sha": request.expected_source_sha,
            "foundation_sha": request.expected_foundation_sha,
            "control_plane_sha": request.control_plane_sha,
            "production_pointer_sha256": sha256_bytes(target_bytes),
            "completed_at": _utc_now(),
        },
        identity={
            "operation_id": request.operation_id,
            "status": "promoted",
            "release_id": intent["target_release_id"],
            "production_pointer_sha256": sha256_bytes(target_bytes),
        },
    )
    return PromotionResult(
        operation_id=request.operation_id,
        status="promoted",
        idempotent=idempotent or reused_receipt,
        previous_release_id=str(receipt["previous_release_id"]),
        release_id=str(receipt["release_id"]),
        manifest_sha256=str(receipt["manifest_sha256"]),
        source_sha=str(receipt["source_sha"]),
        foundation_sha=str(receipt["foundation_sha"]),
        control_plane_sha=str(receipt["control_plane_sha"]),
        production_pointer_sha256=str(receipt["production_pointer_sha256"]),
        intent_key=intent_key,
        receipt_key=receipt_key,
    )


def rollback_release(
    *,
    store: ObjectStore,
    operation_id: str,
    reason: str,
    actor: str,
) -> RollbackResult:
    if not OPERATION_RE.fullmatch(operation_id):
        raise IntegrityError("operation_id must be 8-120 safe characters")
    if not reason.strip() or not actor.strip():
        raise IntegrityError("rollback reason and actor are required")
    prefix = _operation_prefix(operation_id)
    _, intent = _read_json(store, f"{prefix}/intent.json")
    previous_bytes = _decode_pointer(intent, "previous_pointer_b64")
    target_bytes = _decode_pointer(intent, "target_pointer_b64")
    if sha256_bytes(previous_bytes) != intent.get("previous_pointer_sha256"):
        raise IntegrityError("promotion intent previous pointer hash mismatch")
    if sha256_bytes(target_bytes) != intent.get("target_pointer_sha256"):
        raise IntegrityError("promotion intent target pointer hash mismatch")

    key = "channels/production.json"
    current_head = store.head(key)
    if current_head is None:
        raise IntegrityError("production pointer does not exist")
    current_bytes = store.get(key)
    idempotent = False
    if current_bytes == previous_bytes:
        idempotent = True
    elif current_bytes == target_bytes:
        store.put(
            key,
            previous_bytes,
            content_type="application/json",
            sha256=sha256_bytes(previous_bytes),
            expected_etag=current_head.etag,
        )
    else:
        raise ReleaseConflictError(
            "production pointer no longer matches this promotion operation"
        )
    if store.get(key) != previous_bytes:
        raise IntegrityError("production pointer verification failed after rollback")

    receipt_key = f"{prefix}/rollback-receipt.json"
    receipt, reused_receipt = _write_or_load_record(
        store=store,
        key=receipt_key,
        payload={
            "schema_version": "1.0",
            "operation_id": operation_id,
            "status": "rolled_back",
            "reason": reason,
            "actor": actor,
            "restored_release_id": intent["previous_release_id"],
            "replaced_release_id": intent["target_release_id"],
            "production_pointer_sha256": sha256_bytes(previous_bytes),
            "completed_at": _utc_now(),
        },
        identity={
            "operation_id": operation_id,
            "status": "rolled_back",
            "restored_release_id": intent["previous_release_id"],
            "replaced_release_id": intent["target_release_id"],
            "production_pointer_sha256": sha256_bytes(previous_bytes),
        },
    )
    return RollbackResult(
        operation_id=operation_id,
        status="rolled_back",
        idempotent=idempotent or reused_receipt,
        restored_release_id=str(receipt["restored_release_id"]),
        replaced_release_id=str(receipt["replaced_release_id"]),
        production_pointer_sha256=str(receipt["production_pointer_sha256"]),
        receipt_key=receipt_key,
    )
