import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY = "suggested_questions.publish"
L3B_CAPABILITY_IDS = (
    QA_CAPABILITY_DETAIL,
    QA_CAPABILITY_EVENTS,
    QA_CAPABILITY_EXPORT,
    SUGGESTED_QUESTIONS_PUBLISH_CAPABILITY,
)
L3B_QUALIFICATION_DIGEST = hashlib.sha256(
    json.dumps(L3B_CAPABILITY_IDS, separators=(",", ":")).encode()
).hexdigest()


class QualifiedL3BCapabilityProvider:
    """Expose only the QA/SQ capabilities qualified by the L3-B production lane."""

    def __init__(self) -> None:
        self._gates = {
            capability_id: CapabilityGate(
                capability_id=capability_id,
                state="enabled",
                reason_code="L3B_QA_PRODUCTION_QUALIFIED",
                source="l3b_production_qualification",
                resource_identity={
                    "lane": "L3B_QA_P0",
                    "binding": "qualified-production-runtime/v1",
                },
                evidence_digest=L3B_QUALIFICATION_DIGEST,
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
    "ProductionAdminRuntime",
    "QualifiedL3BCapabilityProvider",
    "SqliteAdminControlStore",
    "production_admin_runtime_from_env",
]
