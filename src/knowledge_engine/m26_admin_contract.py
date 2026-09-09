from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

ADMIN_PREFIX = "/v1/admin"
DEFAULT_CONSOLE_ORIGIN = "https://console.danielcanfly.com"
ACCESS_ASSERTION_HEADER = "cf-access-jwt-assertion"
DEFAULT_STATE_CHANGING_ROUTES = (
    ("POST", "/v1/admin/index/audits"),
    ("POST", "/v1/admin/ingestion/scan"),
    ("POST", "/v1/admin/ingestion/dry-runs"),
    ("POST", "/v1/admin/ingestion/jobs"),
    ("POST", "/v1/admin/index/versions/{version_id}/rollback-preflight"),
    ("POST", "/v1/admin/index/versions/{version_id}/activate"),
    ("PUT", "/v1/admin/suggested-questions"),
    ("POST", "/v1/admin/evaluations/runs"),
)
ADMIN_CAPABILITY_STATES = frozenset(
    {"enabled", "read_only", "disabled", "unavailable", "not_eligible"}
)
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:\-/]{16,128}$")
CREDENTIAL_KEY_RE = re.compile(
    r"^(?:authorization|cookie|set-cookie|cf-access-jwt-assertion|x-api-key)$|"
    r"(?:^|[_-])(?:api[_-]?key|token|secret|password|credential|assertion|cookie)$",
    re.I,
)
JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,})\b"
)


class AdminConfigurationError(RuntimeError):
    pass


class AdminAPIError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})


@dataclass(frozen=True)
class AdminActor:
    actor_id: str
    subject: str
    email: str | None
    actor_type: str
    issuer: str
    audience: tuple[str, ...]

    def safe_payload(self) -> dict[str, Any]:
        return {"actor_id": self.actor_id, "actor_type": self.actor_type, "email": self.email}


@dataclass(frozen=True)
class CapabilityGate:
    capability_id: str
    state: str
    reason_code: str
    source: str
    observed_at: str | None = None
    resource_identity: Mapping[str, Any] | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if self.state not in ADMIN_CAPABILITY_STATES:
            raise ValueError(f"invalid capability state: {self.state}")

    def to_payload(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "state": self.state,
            "reason_code": self.reason_code,
            "source": self.source,
            "observed_at": self.observed_at,
            "resource_identity": redact(self.resource_identity),
            "evidence_digest": self.evidence_digest,
        }


class DefaultCapabilityProvider:
    def list_capabilities(self) -> list[CapabilityGate]:
        return []

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return None


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    observed_at: str
    actor_id: str
    actor_type: str
    action: str
    object_type: str
    object_id: str | None
    request_id: str
    operation_id: str | None
    outcome: str
    reason_code: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        value = dict(self.__dict__)
        value["metadata"] = redact(value["metadata"])
        return value


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self.events.append(event)


class UnavailableAuditSink:
    def append(self, event: AuditEvent) -> None:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_AUDIT_SINK_UNAVAILABLE",
            message="A durable admin audit sink is not configured",
        )


@dataclass(frozen=True)
class IdempotencyRecord:
    scope: str
    key_fingerprint: str
    request_hash: str
    operation_id: str
    created_at: str


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def get(self, scope: str, fingerprint: str) -> IdempotencyRecord | None:
        with self._lock:
            return self.records.get((scope, fingerprint))

    def put_if_absent(self, record: IdempotencyRecord) -> IdempotencyRecord:
        with self._lock:
            return self.records.setdefault((record.scope, record.key_fingerprint), record)


class UnavailableIdempotencyStore:
    def get(self, scope: str, fingerprint: str) -> IdempotencyRecord | None:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_IDEMPOTENCY_STORE_UNAVAILABLE",
            message="A durable admin idempotency store is not configured",
        )

    def put_if_absent(self, record: IdempotencyRecord) -> IdempotencyRecord:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_IDEMPOTENCY_STORE_UNAVAILABLE",
            message="A durable admin idempotency store is not configured",
        )


class IdempotencyCoordinator:
    def __init__(self, store: Any) -> None:
        self.store = store

    def begin(
        self,
        *,
        actor_id: str,
        method: str,
        path: str,
        idempotency_key: str,
        request_payload: Any,
    ) -> tuple[str, bool]:
        validate_idempotency_key(idempotency_key)
        scope = f"{actor_id}|{method.upper()}|{path}"
        fingerprint = hashlib.sha256(idempotency_key.encode()).hexdigest()
        request_hash = hashlib.sha256(canonical_json_bytes(request_payload)).hexdigest()
        existing = self.store.get(scope, fingerprint)
        if existing:
            if existing.request_hash != request_hash:
                raise AdminAPIError(
                    status_code=409,
                    code="ADMIN_IDEMPOTENCY_CONFLICT",
                    message="Idempotency key was already used with a different request",
                )
            return existing.operation_id, True
        record = IdempotencyRecord(
            scope, fingerprint, request_hash, new_operation_id(), utc_now()
        )
        winner = self.store.put_if_absent(record)
        if winner.request_hash != request_hash:
            raise AdminAPIError(
                status_code=409,
                code="ADMIN_IDEMPOTENCY_CONFLICT",
                message="Idempotency key was concurrently reused",
            )
        return winner.operation_id, winner.operation_id != record.operation_id


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_request_id() -> str:
    return "admreq_" + uuid.uuid4().hex


def new_operation_id() -> str:
    return "admop_" + uuid.uuid4().hex


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def validate_idempotency_key(value: str | None) -> str:
    if value is None or not IDEMPOTENCY_RE.fullmatch(value):
        raise AdminAPIError(
            status_code=400,
            code="ADMIN_IDEMPOTENCY_KEY_INVALID",
            message="A 16-128 character Idempotency-Key is required",
        )
    return value


def redact(value: Any, *, _depth: int = 0) -> Any:
    if _depth > 8:
        return "[REDACTED_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        value = BEARER_RE.sub("Bearer [REDACTED]", value)
        value = JWT_RE.sub("[REDACTED_JWT]", value)
        return SECRET_RE.sub("[REDACTED_SECRET]", value)
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if CREDENTIAL_KEY_RE.search(str(key))
                else redact(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item, _depth=_depth + 1) for item in value]
    return redact(str(value), _depth=_depth + 1)


def build_audit_event(
    *,
    actor: AdminActor,
    action: str,
    object_type: str,
    object_id: str | None,
    request_id: str,
    operation_id: str | None,
    outcome: str,
    reason_code: str,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        "admevt_" + uuid.uuid4().hex,
        utc_now(),
        actor.actor_id,
        actor.actor_type,
        action,
        object_type,
        object_id,
        request_id,
        operation_id,
        outcome,
        reason_code,
        redact(metadata or {}),
    )
