import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .m26_admin_audit import AuditHistorySnapshot
from .m26_admin_contract import (
    AdminConfigurationError,
    AuditEvent,
    CapabilityGate,
    IdempotencyRecord,
)
from .m26_admin_qa import (
    QA_CAPABILITY_DETAIL,
    QA_CAPABILITY_EVENTS,
    QA_CAPABILITY_EXPORT,
)

ADMIN_CONTROL_DB_ENV = "M26_ADMIN_CONTROL_DB_PATH"
L3B_ADMIN_QUALIFIED_ENV = "M26_L3B_ADMIN_QUALIFIED"
QA_CAPABILITY_EXPORT_JSONL = "qa.export_jsonl"
QA_CAPABILITY_LIFECYCLE = "qa.lifecycle"
SUGGESTED_QUESTIONS_REVIEW_CAPABILITY = "suggested_questions.review"
SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY = "suggested_questions.publish"
AUDIT_READ_CAPABILITY = "audit.read"
GOLDEN_READ_CAPABILITY = "evaluation.golden.read"
RUNS_READ_CAPABILITY = "evaluation.runs.read"
PLAYGROUND_RETRIEVE_CAPABILITY = "playground.retrieve"
PLAYGROUND_ASK_CAPABILITY = "playground.ask"

L3B_MUTATION_CAPABILITY_IDS = frozenset(
    {
        QA_CAPABILITY_EXPORT_JSONL,
        QA_CAPABILITY_LIFECYCLE,
        SUGGESTED_QUESTIONS_REVIEW_CAPABILITY,
    }
)
PRODUCT_READ_CAPABILITY_IDS = (
    AUDIT_READ_CAPABILITY,
    GOLDEN_READ_CAPABILITY,
    PLAYGROUND_ASK_CAPABILITY,
    PLAYGROUND_RETRIEVE_CAPABILITY,
    QA_CAPABILITY_DETAIL,
    QA_CAPABILITY_EVENTS,
    QA_CAPABILITY_EXPORT,
    RUNS_READ_CAPABILITY,
)
L3B_CAPABILITY_IDS = (
    *PRODUCT_READ_CAPABILITY_IDS,
    QA_CAPABILITY_EXPORT_JSONL,
    QA_CAPABILITY_LIFECYCLE,
    SUGGESTED_QUESTIONS_REVIEW_CAPABILITY,
    SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY,
)
L3B_QUALIFICATION_DIGEST = hashlib.sha256(
    json.dumps(L3B_CAPABILITY_IDS, separators=(",", ":")).encode()
).hexdigest()
L3B_SUGGESTED_QUESTIONS_PUBLISH_BLOCKED_REASON = (
    "L3B_SUGGESTED_QUESTIONS_PUBLISH_NOT_AUTHORIZED"
)


@dataclass(frozen=True)
class _CanonicalL3BCapabilityGate(CapabilityGate):
    """Production-owned capability evidence with an explicit canonical view."""

    qualification_status: str = "qualified"
    effective_state: str = "read_only"
    mutation_authorized: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "qualification_status": self.qualification_status,
                "effective_state": self.effective_state,
                "mutation_authorized": self.mutation_authorized,
            }
        )
        return payload


class QualifiedL3BCapabilityProvider:
    """Canonical production capability registry.

    The class name is kept for import compatibility with the earlier L3-B lane,
    but read capabilities are now product-scoped. Mutation authority remains
    exactly the previously-qualified set.
    """

    def __init__(self) -> None:
        self._gates = {
            capability_id: _CanonicalL3BCapabilityGate(
                capability_id=capability_id,
                state=(
                    "disabled"
                    if capability_id
                    in {
                        SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY,
                        PLAYGROUND_ASK_CAPABILITY,
                    }
                    else "enabled"
                    if capability_id in L3B_MUTATION_CAPABILITY_IDS
                    else "read_only"
                ),
                reason_code=(
                    L3B_SUGGESTED_QUESTIONS_PUBLISH_BLOCKED_REASON
                    if capability_id == SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY
                    else "PLAYGROUND_FULL_ASK_EXPLICIT_COST_AUTHORITY_REQUIRED"
                    if capability_id == PLAYGROUND_ASK_CAPABILITY
                    else "PRODUCT_MUTATION_AUTHORITY_QUALIFIED"
                    if capability_id in L3B_MUTATION_CAPABILITY_IDS
                    else "PRODUCT_READ_CAPABILITY_QUALIFIED"
                ),
                source="production_admin_capability_registry",
                resource_identity={
                    "binding": "qualified-production-runtime/v3",
                    "scope": "daniel-console",
                },
                evidence_digest=L3B_QUALIFICATION_DIGEST,
                qualification_status=(
                    "blocked_authority"
                    if capability_id
                    in {
                        SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY,
                        PLAYGROUND_ASK_CAPABILITY,
                    }
                    else "qualified"
                ),
                effective_state=(
                    "unavailable"
                    if capability_id
                    in {
                        SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY,
                        PLAYGROUND_ASK_CAPABILITY,
                    }
                    else "enabled"
                    if capability_id in L3B_MUTATION_CAPABILITY_IDS
                    else "read_only"
                ),
                mutation_authorized=capability_id in L3B_MUTATION_CAPABILITY_IDS,
            )
            for capability_id in L3B_CAPABILITY_IDS
        }

    def list_capabilities(self) -> list[CapabilityGate]:
        return [self._gates[key] for key in sorted(self._gates)]

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return self._gates.get(capability_id)


class SqliteAdminControlStore:
    """Durable audit/idempotency store colocated with the owner-only QA runtime."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path.as_posix(), timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    event_id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS admin_audit_observed_idx
                    ON admin_audit_events(observed_at DESC);
                CREATE TABLE IF NOT EXISTS admin_idempotency (
                    scope TEXT NOT NULL,
                    key_fingerprint TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(scope, key_fingerprint)
                );
                """
            )
            connection.commit()

    def append(self, event: AuditEvent) -> None:
        payload = json.dumps(
            event.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO admin_audit_events(event_id, observed_at, payload_json) VALUES(?,?,?)",
                (event.event_id, event.observed_at, payload),
            )
            connection.commit()

    def get(self, scope: str, fingerprint: str) -> IdempotencyRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT scope, key_fingerprint, request_hash, operation_id, created_at "
                "FROM admin_idempotency WHERE scope=? AND key_fingerprint=?",
                (scope, fingerprint),
            ).fetchone()
        return _idempotency_record(row) if row is not None else None

    def put_if_absent(self, record: IdempotencyRecord) -> IdempotencyRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO admin_idempotency("
                "scope, key_fingerprint, request_hash, operation_id, created_at"
                ") VALUES(?,?,?,?,?)",
                (
                    record.scope,
                    record.key_fingerprint,
                    record.request_hash,
                    record.operation_id,
                    record.created_at,
                ),
            )
            row = connection.execute(
                "SELECT scope, key_fingerprint, request_hash, operation_id, created_at "
                "FROM admin_idempotency WHERE scope=? AND key_fingerprint=?",
                (record.scope, record.key_fingerprint),
            ).fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("durable idempotency write did not materialize")
        return _idempotency_record(row)

    def audit_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM admin_audit_events").fetchone()
        return int(row["count"] if row is not None else 0)

    def read_audit_events(self, *, limit: int = 500) -> tuple[list[dict[str, Any]], int]:
        """Read a bounded newest-first audit window without changing the ledger."""
        bounded_limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            total_row = connection.execute(
                "SELECT COUNT(*) AS count FROM admin_audit_events"
            ).fetchone()
            rows = connection.execute(
                "SELECT observed_at, payload_json FROM admin_audit_events "
                "ORDER BY observed_at DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                events.append(payload)
        total = int(total_row["count"] if total_row is not None else 0)
        return events, total


class SqliteAuditHistoryReader:
    """Bounded read adapter over the already-durable Admin audit ledger."""

    def __init__(self, store: SqliteAdminControlStore, *, limit: int = 500) -> None:
        self.store = store
        self.limit = max(1, min(int(limit), 1000))

    def read(self, request: Any) -> AuditHistorySnapshot:
        del request
        events, total = self.store.read_audit_events(limit=self.limit)
        observed_at = None
        for event in events:
            value = event.get("observed_at")
            if isinstance(value, str) and value:
                observed_at = value if observed_at is None else max(observed_at, value)
        digest = hashlib.sha256(
            json.dumps(
                events,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return AuditHistorySnapshot(
            events=events,
            source="durable_admin_audit_sqlite",
            observed_at=observed_at,
            freshness="near_live" if observed_at else "unknown",
            resource_identity={
                "kind": "sqlite_admin_audit",
                "window_limit": self.limit,
                "total_count": total,
            },
            evidence_digest=digest,
            complete=total <= self.limit,
        )


@dataclass(frozen=True)
class ProductionAdminRuntime:
    capability_provider: QualifiedL3BCapabilityProvider
    store: SqliteAdminControlStore


def production_admin_runtime_from_env() -> ProductionAdminRuntime | None:
    enabled = os.environ.get(L3B_ADMIN_QUALIFIED_ENV, "").strip().casefold()
    if enabled not in {"1", "true", "yes"}:
        return None
    raw_path = os.environ.get(ADMIN_CONTROL_DB_ENV, "").strip()
    if not raw_path:
        raise AdminConfigurationError(
            "L3-B production Admin binding requires a durable control DB path"
        )
    store = SqliteAdminControlStore(Path(raw_path))
    return ProductionAdminRuntime(QualifiedL3BCapabilityProvider(), store)


def _idempotency_record(row: Any) -> IdempotencyRecord:
    return IdempotencyRecord(
        scope=str(row["scope"]),
        key_fingerprint=str(row["key_fingerprint"]),
        request_hash=str(row["request_hash"]),
        operation_id=str(row["operation_id"]),
        created_at=str(row["created_at"]),
    )


__all__ = [
    "ADMIN_CONTROL_DB_ENV",
    "L3B_ADMIN_QUALIFIED_ENV",
    "L3B_CAPABILITY_IDS",
    "L3B_MUTATION_CAPABILITY_IDS",
    "QA_CAPABILITY_EXPORT_JSONL",
    "QA_CAPABILITY_LIFECYCLE",
    "SUGGESTED_QUESTIONS_REVIEW_CAPABILITY",
    "SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY",
    "ProductionAdminRuntime",
    "QualifiedL3BCapabilityProvider",
    "SqliteAdminControlStore",
    "SqliteAuditHistoryReader",
    "production_admin_runtime_from_env",
]
