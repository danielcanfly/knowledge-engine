from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

AUDIENCES = {"public", "internal", "confidential", "restricted"}
OBSERVATION_SOURCES = {"observed", "operator_asserted", "inherited", "unresolved"}
POLICY_TYPES = {"public", "authenticated", "principal_set", "restricted", "unresolved"}
SOURCE_ID_RE = re.compile(r"^source_[a-z0-9][a-z0-9_-]{2,127}$")
SNAPSHOT_ID_RE = re.compile(r"^(?:snap_[a-f0-9]{64}|capture_[a-f0-9]{32})$")
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
CONNECTOR_TYPE = "local_file"
CONNECTOR_VERSION = "local-file/1.0.0"
NORMALIZER_ID = "markdown"
NORMALIZER_VERSION = "1.0.0"

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "generic_secret_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret[_-]?access[_-]?key|access[_-]?token)\b"
        r"\s*[:=]\s*[A-Za-z0-9_+/=-]{20,}"
    ),
}
PROMPT_INJECTION_PATTERNS = {
    "ignore_previous_instructions": re.compile(
        r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"
    ),
    "system_prompt_request": re.compile(
        r"(?i)\b(?:reveal|print|show)\s+the\s+system\s+prompt\b"
    ),
    "role_override": re.compile(r"(?i)\byou\s+are\s+now\b"),
}


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalized(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return M10 canonical JSON v1 bytes without a trailing newline."""

    return json.dumps(
        _normalized(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(_normalized(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_utc(value: str) -> None:
    if not value.endswith("Z"):
        raise IntakeFailure("INVALID_TIMESTAMP", "request", "timestamp must end in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntakeFailure("INVALID_TIMESTAMP", "request", "invalid ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise IntakeFailure("INVALID_TIMESTAMP", "request", "timestamp must be UTC")


def stable_source_id(connector_type: str, canonical_locator: str) -> str:
    digest = sha256_bytes(canonical_json_bytes([connector_type, canonical_locator]))
    return f"source_{digest[:32]}"


def snapshot_id_for(identity_payload: Mapping[str, Any]) -> str:
    return "snap_" + sha256_bytes(canonical_json_bytes(identity_payload))


def derivative_id_for(
    *,
    snapshot_id: str,
    normalizer_id: str,
    normalizer_version: str,
    normalized_content_hash: str,
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "normalizer_id": normalizer_id,
        "normalizer_version": normalizer_version,
        "normalized_content_hash": normalized_content_hash,
    }
    return "drv_" + sha256_bytes(canonical_json_bytes(payload))


def _attempt_id_for(request: LocalMarkdownRequest) -> str:
    seed = {
        "schema_version": "intake-attempt/v1",
        "locator": request.locator,
        "original_uri": request.original_uri,
        "source_id": request.source_id,
        "retrieved_at": request.retrieved_at,
        "owner": request.owner.to_dict(),
        "license": request.license.to_dict(),
        "audience": request.audience,
        "access_policy": request.access_policy.to_dict(),
        "parent_snapshot": request.parent_snapshot,
        "max_bytes": request.max_bytes,
    }
    return "attempt_" + sha256_bytes(canonical_json_bytes(seed))[:32]


@dataclass(frozen=True)
class EvidenceValue:
    status: str
    value: str | None
    observation_source: str

    def validate(self, field_name: str) -> None:
        if self.status not in {"resolved", "unresolved"}:
            raise IntakeFailure("INVALID_METADATA", "request", f"invalid {field_name} status")
        if self.observation_source not in OBSERVATION_SOURCES:
            raise IntakeFailure(
                "INVALID_METADATA", "request", f"invalid {field_name} observation source"
            )
        if self.status == "resolved":
            if not self.value or not self.value.strip():
                raise IntakeFailure(
                    "INVALID_METADATA", "request", f"resolved {field_name} requires value"
                )
            if self.observation_source == "unresolved":
                raise IntakeFailure(
                    "INVALID_METADATA",
                    "request",
                    f"resolved {field_name} cannot use unresolved observation source",
                )
        elif self.value is not None or self.observation_source != "unresolved":
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                f"unresolved {field_name} must have null value and unresolved source",
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccessPolicy:
    policy_type: str
    principals: tuple[str, ...] = ()
    observation_source: str = "unresolved"
    native_evidence_ref: str | None = None

    def validate(self, *, audience: str) -> None:
        if self.policy_type not in POLICY_TYPES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid access policy type")
        if self.observation_source not in OBSERVATION_SOURCES:
            raise IntakeFailure(
                "INVALID_METADATA", "request", "invalid access policy observation source"
            )
        if any(not principal.strip() for principal in self.principals):
            raise IntakeFailure("INVALID_METADATA", "request", "empty access principal")
        if len(set(self.principals)) != len(self.principals):
            raise IntakeFailure("INVALID_METADATA", "request", "duplicate access principal")
        if self.policy_type == "public":
            if audience != "public" or self.principals:
                raise IntakeFailure(
                    "INVALID_METADATA", "request", "public policy requires public audience"
                )
            if self.observation_source == "unresolved":
                raise IntakeFailure(
                    "ACL_UNRESOLVED", "request", "public policy requires resolved evidence"
                )
        if self.policy_type == "unresolved" or self.observation_source == "unresolved":
            if audience != "restricted":
                raise IntakeFailure(
                    "ACL_UNRESOLVED",
                    "request",
                    "unresolved ACL must use restricted audience",
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_type": self.policy_type,
            "principals": sorted(self.principals),
            "observation_source": self.observation_source,
            "native_evidence_ref": self.native_evidence_ref,
        }


@dataclass(frozen=True)
class LocalMarkdownRequest:
    locator: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    original_uri: str | None = None
    parent_snapshot: str | None = None
    max_bytes: int = DEFAULT_MAX_BYTES

    def validate(self) -> None:
        if not self.locator.strip():
            raise IntakeFailure("INVALID_LOCATOR", "request", "locator is required")
        _validate_utc(self.retrieved_at)
        self.owner.validate("owner")
        self.license.validate("license")
        if self.audience not in AUDIENCES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid audience")
        self.access_policy.validate(audience=self.audience)
        if self.source_id is not None and not SOURCE_ID_RE.fullmatch(self.source_id):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid source_id")
        if self.parent_snapshot is not None and not SNAPSHOT_ID_RE.fullmatch(
            self.parent_snapshot
        ):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid parent_snapshot")
        if self.max_bytes < 1:
            raise IntakeFailure("INVALID_METADATA", "request", "max_bytes must be positive")
        if self.original_uri:
            parsed = urlsplit(self.original_uri)
            if parsed.username or parsed.password:
                raise IntakeFailure(
                    "INVALID_METADATA", "request", "original_uri cannot contain credentials"
                )


@dataclass(frozen=True)
class Acquisition:
    canonical_locator: str
    original_uri: str
    source_version: str
    retrieved_at: str
    mime_type: str
    encoding: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class SnapshotRecord:
    source_id: str
    snapshot_id: str
    original_uri: str
    connector_type: str
    connector_version: str
    retrieved_at: str
    content_hash: str
    byte_size: int
    mime_type: str
    encoding: str | None
    license: dict[str, Any]
    owner: dict[str, Any]
    audience: str
    acl_status: str
    access_policy: dict[str, Any]
    source_version: str | None
    parent_snapshot: str | None
    storage_location: dict[str, Any]
    schema_version: str = "intake-snapshot/v1"

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "original_uri": self.original_uri,
            "connector_type": self.connector_type,
            "connector_version": self.connector_version,
            "retrieved_at": self.retrieved_at,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "mime_type": self.mime_type,
            "encoding": self.encoding,
            "license": self.license,
            "owner": self.owner,
            "audience": self.audience,
            "access_policy": self.access_policy,
            "source_version": self.source_version,
            "parent_snapshot": self.parent_snapshot,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DerivativeRecord:
    derivative_id: str
    snapshot_id: str
    normalizer_id: str
    normalizer_version: str
    normalized_content_hash: str
    normalized_key: str
    byte_size: int
    mime_type: str
    warnings: tuple[dict[str, str], ...]
    schema_version: str = "intake-derivative/v1"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["warnings"] = list(self.warnings)
        return value


@dataclass(frozen=True)
class IntakeResult:
    attempt_id: str
    status: str
    source_id: str | None
    snapshot_id: str | None
    derivative_id: str | None
    raw_blob_key: str | None
    snapshot_key: str | None
    normalized_key: str | None
    derivative_key: str | None
    result_key: str
    rejection_key: str | None
    idempotent: bool
    raw_blob_reused: bool
    event_keys: tuple[str, ...]
    failure_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["event_keys"] = list(self.event_keys)
        return value

    def evidence_dict(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("idempotent")
        value.pop("raw_blob_reused")
        return value


class IntakeFailure(IntegrityError):
    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        *,
        transient: bool = False,
        safe_context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stage = stage
        self.safe_message = message
        self.transient = transient
        self.safe_context = dict(safe_context or {})


class LocalFileConnector:
    def __init__(
        self,
        allowed_root: Path,
        *,
        after_read_hook: Callable[[], None] | None = None,
    ) -> None:
        self.allowed_root = allowed_root.resolve(strict=True)
        if not self.allowed_root.is_dir():
            raise ValueError("allowed_root must be a directory")
        self._after_read_hook = after_read_hook

    def canonicalize(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure("SOURCE_NOT_FOUND", "discover", "source does not exist") from exc
        try:
            resolved.relative_to(self.allowed_root)
        except ValueError as exc:
            raise IntakeFailure(
                "PATH_ESCAPE", "discover", "source escapes the allowed root"
            ) from exc
        return resolved

    def acquire(self, path: Path, *, retrieved_at: str, max_bytes: int) -> Acquisition:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise IntakeFailure("UNSUPPORTED_BINARY", "acquire", "source is not a regular file")
        if before.st_size < 1:
            raise IntakeFailure("EMPTY_SOURCE", "acquire", "source is empty")
        if before.st_size > max_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "acquire",
                "source exceeds maximum bytes",
                safe_context={"observed_bytes": before.st_size, "max_bytes": max_bytes},
            )

        chunks: list[bytes] = []
        observed = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(min(64 * 1024, max_bytes + 1 - observed))
                if not chunk:
                    break
                chunks.append(chunk)
                observed += len(chunk)
                if observed > max_bytes:
                    raise IntakeFailure(
                        "SOURCE_TOO_LARGE",
                        "acquire",
                        "source exceeds maximum bytes during read",
                        safe_context={"observed_bytes": observed, "max_bytes": max_bytes},
                    )

        if self._after_read_hook is not None:
            self._after_read_hook()
        after = path.stat()
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after:
            raise IntakeFailure(
                "SOURCE_CHANGED_DURING_READ",
                "acquire",
                "source changed during acquisition",
            )

        data = b"".join(chunks)
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IntakeFailure(
                "UNSUPPORTED_BINARY", "safety_gate", "Markdown source must be UTF-8"
            ) from exc

        suffix = path.suffix.lower()
        mime_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
        source_version = (
            f"local:{before.st_dev}:{before.st_ino}:{before.st_size}:{before.st_mtime_ns}"
        )
        return Acquisition(
            canonical_locator=path.as_uri(),
            original_uri=path.as_uri(),
            source_version=source_version,
            retrieved_at=retrieved_at,
            mime_type=mime_type,
            encoding="utf-8",
            data=data,
        )


def _normalize_markdown(data: bytes) -> bytes:
    text = data.decode("utf-8-sig")
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntakeFailure("EMPTY_SOURCE", "normalize", "Markdown source is empty")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _secret_matches(text: str) -> list[str]:
    return sorted(name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text))


def _prompt_findings(text: str) -> tuple[dict[str, str], ...]:
    findings = []
    for name, pattern in PROMPT_INJECTION_PATTERNS.items():
        if pattern.search(text):
            findings.append(
                {
                    "code": "PROMPT_INJECTION_LIKE_CONTENT",
                    "pattern": name,
                    "severity": "warning",
                    "action": "treat_as_untrusted_data",
                }
            )
    return tuple(findings)


def _put_immutable(
    store: ObjectStore,
    key: str,
    data: bytes,
    *,
    content_type: str,
) -> bool:
    current = store.head(key)
    if current is not None:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=sha256_bytes(data),
            only_if_absent=True,
        )
        return False
    except ReleaseConflictError:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}") from None
        return True


def _event(
    *,
    attempt_id: str,
    sequence: int,
    occurred_at: str,
    from_state: str | None,
    to_state: str,
    reason_code: str,
    evidence_refs: Sequence[str],
    previous_event_sha256: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "intake-event/v1",
        "attempt_id": attempt_id,
        "sequence": sequence,
        "occurred_at": occurred_at,
        "from_state": from_state,
        "to_state": to_state,
        "actor": "knowledge-engine",
        "reason_code": reason_code,
        "evidence_refs": list(evidence_refs),
        "previous_event_sha256": previous_event_sha256,
    }
    return {**payload, "event_sha256": sha256_bytes(canonical_json_bytes(payload))}


def verify_event(event: Mapping[str, Any]) -> bool:
    payload = dict(event)
    expected = payload.pop("event_sha256", None)
    return isinstance(expected, str) and expected == sha256_bytes(canonical_json_bytes(payload))


def _write_event(
    store: ObjectStore,
    event: Mapping[str, Any],
) -> tuple[str, bool]:
    key = (
        f"intake/v1/attempts/{event['attempt_id']}/events/"
        f"{int(event['sequence']):06d}-{event['event_sha256']}.json"
    )
    reused = _put_immutable(store, key, _pretty_json_bytes(event), content_type="application/json")
    return key, reused


def _write_output(output_dir: Path | None, relative: str, data: bytes) -> None:
    if output_dir is None:
        return
    destination = output_dir.resolve() / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _rejected_result(
    *,
    store: ObjectStore,
    request: LocalMarkdownRequest,
    attempt_id: str,
    failure: IntakeFailure,
    current_state: str | None,
    events: list[dict[str, Any]],
    object_states: list[bool],
    output_dir: Path | None,
    source_id: str | None,
) -> IntakeResult:
    previous_hash = events[-1]["event_sha256"] if events else None
    rejected_event = _event(
        attempt_id=attempt_id,
        sequence=len(events) + 1,
        occurred_at=request.retrieved_at,
        from_state=current_state,
        to_state="rejected",
        reason_code=failure.code,
        evidence_refs=[],
        previous_event_sha256=previous_hash,
    )
    event_key, reused = _write_event(store, rejected_event)
    events.append(rejected_event)
    object_states.append(reused)

    rejection = {
        "schema_version": "intake-rejection/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "stage": failure.stage,
        "reason_code": failure.code,
        "message": failure.safe_message,
        "transient": failure.transient,
        "safe_context": failure.safe_context,
        "rejected_at": request.retrieved_at,
        "raw_persisted": False,
        "canonical_write_permitted": False,
        "production_write_permitted": False,
    }
    rejection_key = f"intake/v1/rejections/{attempt_id}/evidence.json"
    rejection_bytes = _pretty_json_bytes(rejection)
    object_states.append(
        _put_immutable(store, rejection_key, rejection_bytes, content_type="application/json")
    )

    result_key = f"intake/v1/attempts/{attempt_id}/result.json"
    result = IntakeResult(
        attempt_id=attempt_id,
        status="rejected",
        source_id=source_id,
        snapshot_id=None,
        derivative_id=None,
        raw_blob_key=None,
        snapshot_key=None,
        normalized_key=None,
        derivative_key=None,
        result_key=result_key,
        rejection_key=rejection_key,
        idempotent=False,
        raw_blob_reused=False,
        event_keys=tuple(
            f"intake/v1/attempts/{attempt_id}/events/"
            f"{int(item['sequence']):06d}-{item['event_sha256']}.json"
            for item in events
        ),
        failure_code=failure.code,
    )
    result_bytes = _pretty_json_bytes(result.evidence_dict())
    object_states.append(
        _put_immutable(store, result_key, result_bytes, content_type="application/json")
    )
    result = IntakeResult(**{**result.to_dict(), "event_keys": result.event_keys, "idempotent": all(object_states)})
    _write_output(output_dir, "rejection.json", rejection_bytes)
    _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
    return result


def intake_local_markdown(
    *,
    store: ObjectStore,
    request: LocalMarkdownRequest,
    allowed_root: Path,
    output_dir: Path | None = None,
    after_read_hook: Callable[[], None] | None = None,
) -> IntakeResult:
    """Acquire one local Markdown source into the immutable M10 intake namespace."""

    attempt_id = _attempt_id_for(request)
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    current_state: str | None = None
    source_id = request.source_id

    try:
        request.validate()
        connector = LocalFileConnector(allowed_root, after_read_hook=after_read_hook)

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        path = connector.canonicalize(request.locator)
        acquisition = connector.acquire(
            path,
            retrieved_at=request.retrieved_at,
            max_bytes=request.max_bytes,
        )
        original_uri = request.original_uri or acquisition.original_uri
        canonical_locator = acquisition.canonical_locator
        source_id = source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)

        raw_hash = sha256_bytes(acquisition.data)
        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[f"sha256:{raw_hash}", f"bytes:{len(acquisition.data)}"],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        text = acquisition.data.decode("utf-8-sig")
        secret_matches = _secret_matches(text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "source contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "observed_sha256": raw_hash,
                    "observed_bytes": len(acquisition.data),
                },
            )

        normalized = _normalize_markdown(acquisition.data)
        normalized_hash = sha256_bytes(normalized)
        raw_blob_key = f"intake/v1/raw/sha256/{raw_hash[:2]}/{raw_hash}"
        raw_reused = _put_immutable(
            store,
            raw_blob_key,
            acquisition.data,
            content_type=acquisition.mime_type,
        )
        object_states.append(raw_reused)

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            else "resolved"
        )
        provisional = SnapshotRecord(
            source_id=source_id,
            snapshot_id="snap_" + "0" * 64,
            original_uri=original_uri,
            connector_type=CONNECTOR_TYPE,
            connector_version=CONNECTOR_VERSION,
            retrieved_at=request.retrieved_at,
            content_hash=raw_hash,
            byte_size=len(acquisition.data),
            mime_type=acquisition.mime_type,
            encoding=acquisition.encoding,
            license=request.license.to_dict(),
            owner=request.owner.to_dict(),
            audience=request.audience,
            acl_status=acl_status,
            access_policy=request.access_policy.to_dict(),
            source_version=acquisition.source_version,
            parent_snapshot=request.parent_snapshot,
            storage_location={
                "backend": "object_store",
                "bucket": None,
                "key": raw_blob_key,
                "sha256": raw_hash,
            },
        )
        snapshot_id = snapshot_id_for(provisional.identity_payload())
        snapshot = SnapshotRecord(**{**provisional.to_dict(), "snapshot_id": snapshot_id})
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot_bytes = _pretty_json_bytes(snapshot.to_dict())
        object_states.append(
            _put_immutable(store, snapshot_key, snapshot_bytes, content_type="application/json")
        )

        snapshotted = _event(
            attempt_id=attempt_id,
            sequence=3,
            occurred_at=request.retrieved_at,
            from_state="acquired",
            to_state="snapshotted",
            reason_code="SNAPSHOT_WRITTEN",
            evidence_refs=[raw_blob_key, snapshot_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=NORMALIZER_ID,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = DerivativeRecord(
            derivative_id=derivative_id,
            snapshot_id=snapshot_id,
            normalizer_id=NORMALIZER_ID,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content_hash=normalized_hash,
            normalized_key=normalized_key,
            byte_size=len(normalized),
            mime_type="text/markdown",
            warnings=_prompt_findings(normalized.decode("utf-8")),
        )
        derivative_bytes = _pretty_json_bytes(derivative.to_dict())
        object_states.append(
            _put_immutable(
                store,
                derivative_key,
                derivative_bytes,
                content_type="application/json",
            )
        )

        normalized_event = _event(
            attempt_id=attempt_id,
            sequence=4,
            occurred_at=request.retrieved_at,
            from_state="snapshotted",
            to_state="normalized",
            reason_code="DERIVATIVE_WRITTEN",
            evidence_refs=[normalized_key, derivative_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, normalized_event)
        events.append(normalized_event)
        object_states.append(reused)
        current_state = "normalized"

        if acl_status != "resolved" or request.owner.status != "resolved":
            raise IntakeFailure(
                "ACL_UNRESOLVED",
                "admission",
                "ACL or ownership is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )
        if request.license.status != "resolved":
            raise IntakeFailure(
                "LICENSE_UNRESOLVED",
                "admission",
                "license is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )

        accepted = _event(
            attempt_id=attempt_id,
            sequence=5,
            occurred_at=request.retrieved_at,
            from_state="normalized",
            to_state="accepted_for_compilation",
            reason_code="COMPILATION_ADMISSION_ACCEPTED",
            evidence_refs=[snapshot_key, derivative_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, accepted)
        events.append(accepted)
        object_states.append(reused)

        result_key = f"intake/v1/attempts/{attempt_id}/result.json"
        result = IntakeResult(
            attempt_id=attempt_id,
            status="accepted_for_compilation",
            source_id=source_id,
            snapshot_id=snapshot_id,
            derivative_id=derivative_id,
            raw_blob_key=raw_blob_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=raw_reused,
            event_keys=tuple(
                f"intake/v1/attempts/{attempt_id}/events/"
                f"{int(item['sequence']):06d}-{item['event_sha256']}.json"
                for item in events
            ),
        )
        result_bytes = _pretty_json_bytes(result.evidence_dict())
        object_states.append(
            _put_immutable(store, result_key, result_bytes, content_type="application/json")
        )
        result = IntakeResult(
            **{
                **result.to_dict(),
                "event_keys": result.event_keys,
                "idempotent": all(object_states),
            }
        )

        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        return _rejected_result(
            store=store,
            request=request,
            attempt_id=attempt_id,
            failure=failure,
            current_state=current_state,
            events=events,
            object_states=object_states,
            output_dir=output_dir,
            source_id=source_id,
        )
