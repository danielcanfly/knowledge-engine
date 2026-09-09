"""SQLite-backed durable authority for BP5-R0 ingestion orchestration.

The ledger owns mutable coordination only. Immutable candidate artifacts and
Qdrant writes remain delegated to already-qualified injected primitives.
"""

# Contract records intentionally use compact SQL/evidence literals.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .m26_active_production_release import resolve_active_production_release
from .m26_admin_contract import (
    AdminAPIError,
    IdempotencyRecord,
    StatefulIdempotencyLease,
    StatefulIdempotencyRecord,
    canonical_json_bytes,
    utc_now,
)
from .m26_admin_ingestion_core import ReadObservation
from .m26_admin_ingestion_sync import build_sync_plan
from .m26_ingestion_candidate_writer import (
    build_candidate_release_plan,
    stage_candidate_release,
)
from .m26_jobs_rollback_api import EvidenceObservation

SCHEMA_VERSION = "knowledge-engine-m26-sqlite-ingestion/v1"
DEFAULT_INGESTION_STATE_DB = "/var/lib/knowledge-engine/ingestion/ingestion.sqlite3"
LEASE_SECONDS = 300


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode()


def _decode(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise AdminAPIError(
            status_code=503,
            code="ADMIN_INGESTION_STATE_CORRUPT",
            message="Durable ingestion state is malformed",
            retryable=True,
        ) from exc


def _error(code: str, message: str, status: int = 503) -> AdminAPIError:
    return AdminAPIError(status_code=status, code=code, message=message, retryable=True)


def _request_payload(request: Any) -> dict[str, Any]:
    """Persist only the small, canonical operator intent needed for replay."""

    if hasattr(request, "model_dump"):
        payload = request.model_dump(exclude_none=True)
    elif isinstance(request, Mapping):
        payload = dict(request)
    else:
        payload = {
            key: getattr(request, key)
            for key in ("confirmation", "expected_plan_digest")
            if hasattr(request, key) and getattr(request, key) is not None
        }
    return {str(key): value for key, value in payload.items()}


def _error_payload(exc: Exception) -> dict[str, str]:
    return {
        "code": str(getattr(exc, "code", "ADMIN_INGESTION_EXECUTION_FAILED")),
        "detail": "Ingestion observation or planning failed before candidate work",
    }


class SQLiteIngestionLedger:
    """Single transactional authority for mutable ingestion state."""

    def __init__(self, path: str | Path, *, lease_seconds: int = LEASE_SECONDS) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = lease_seconds
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_idempotency (
                    scope TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('IN_PROGRESS','SUCCEEDED','FAILED')),
                    attempt INTEGER NOT NULL CHECK(attempt >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope, fingerprint),
                    UNIQUE(operation_id)
                );
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL UNIQUE,
                    actor_scope TEXT NOT NULL,
                    idempotency_fingerprint TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')),
                    phase TEXT NOT NULL DEFAULT 'scan',
                    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
                    attempt INTEGER NOT NULL CHECK(attempt >= 1),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    source_revision TEXT,
                    source_identity_digest TEXT,
                    active_manifest_key TEXT,
                    active_manifest_sha256 TEXT,
                    plan_id TEXT,
                    plan_digest TEXT,
                    manifest_diff_json TEXT,
                    candidate_release_id TEXT,
                    candidate_manifest_key TEXT,
                    candidate_manifest_sha256 TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    error_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(actor_scope, idempotency_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS ingestion_jobs_updated_idx
                    ON ingestion_jobs(updated_at DESC);
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(ingestion_jobs)").fetchall()
            }
            if "request_payload_json" not in columns:
                db.execute(
                    "ALTER TABLE ingestion_jobs ADD COLUMN request_payload_json TEXT NOT NULL DEFAULT '{}'"
                )

    @staticmethod
    def _legacy(row: sqlite3.Row) -> IdempotencyRecord:
        return IdempotencyRecord(
            scope=row["scope"],
            key_fingerprint=row["fingerprint"],
            request_hash=row["request_hash"],
            operation_id=row["operation_id"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _stateful(row: sqlite3.Row) -> StatefulIdempotencyRecord:
        return StatefulIdempotencyRecord(
            scope=row["scope"],
            key_fingerprint=row["fingerprint"],
            request_hash=row["request_hash"],
            operation_id=row["operation_id"],
            state=row["state"],
            attempt=int(row["attempt"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, scope: str, fingerprint: str) -> IdempotencyRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (scope, fingerprint),
            ).fetchone()
        return None if row is None else self._legacy(row)

    def put_if_absent(self, record: IdempotencyRecord) -> IdempotencyRecord:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (record.scope, record.key_fingerprint),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO ingestion_idempotency VALUES (?,?,?,?,?,?,?,?)",
                    (
                        record.scope,
                        record.key_fingerprint,
                        record.request_hash,
                        record.operation_id,
                        "IN_PROGRESS",
                        1,
                        record.created_at,
                        record.created_at,
                    ),
                )
                return record
            return self._legacy(existing)

    def get_stateful(self, scope: str, fingerprint: str) -> StatefulIdempotencyRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (scope, fingerprint),
            ).fetchone()
        return None if row is None else self._stateful(row)

    def put_stateful_if_absent(
        self, record: StatefulIdempotencyRecord
    ) -> StatefulIdempotencyRecord:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (record.scope, record.key_fingerprint),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO ingestion_idempotency VALUES (?,?,?,?,?,?,?,?)",
                    (
                        record.scope,
                        record.key_fingerprint,
                        record.request_hash,
                        record.operation_id,
                        record.state,
                        record.attempt,
                        record.created_at,
                        record.updated_at,
                    ),
                )
                return record
            return self._stateful(existing)

    def restart_stateful_failed(
        self, *, scope: str, fingerprint: str, request_hash: str
    ) -> tuple[StatefulIdempotencyRecord, bool]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (scope, fingerprint),
            ).fetchone()
            if row is None:
                raise _error(
                    "ADMIN_IDEMPOTENCY_STATE_CONFLICT", "Idempotency record is unavailable", 409
                )
            if row["request_hash"] != request_hash or row["state"] != "FAILED":
                return self._stateful(row), False
            now = utc_now()
            db.execute(
                "UPDATE ingestion_idempotency SET state='IN_PROGRESS', attempt=attempt+1, updated_at=? WHERE scope=? AND fingerprint=? AND state='FAILED' AND request_hash=?",
                (now, scope, fingerprint, request_hash),
            )
            updated = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (scope, fingerprint),
            ).fetchone()
            return self._stateful(updated), True

    def transition_stateful(
        self, lease: StatefulIdempotencyLease, *, target_state: str
    ) -> StatefulIdempotencyRecord:
        if target_state not in {"SUCCEEDED", "FAILED"}:
            raise ValueError(target_state)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (lease.scope, lease.key_fingerprint),
            ).fetchone()
            if (
                row is None
                or row["operation_id"] != lease.operation_id
                or row["attempt"] != lease.attempt
                or row["request_hash"] != lease.request_hash
                or row["state"] != "IN_PROGRESS"
            ):
                raise _error("ADMIN_IDEMPOTENCY_STATE_CONFLICT", "Idempotency lease is stale", 409)
            now = utc_now()
            db.execute(
                "UPDATE ingestion_idempotency SET state=?, updated_at=? WHERE scope=? AND fingerprint=?",
                (target_state, now, lease.scope, lease.key_fingerprint),
            )
            return self._stateful(
                db.execute(
                    "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                    (lease.scope, lease.key_fingerprint),
                ).fetchone()
            )

    def create_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        now = str(job.get("created_at") or utc_now())
        values = {
            "job_id": str(job["job_id"]),
            "operation_id": str(job["operation_id"]),
            "actor_scope": str(job.get("actor_scope", "")),
            "idempotency_fingerprint": str(job.get("idempotency_fingerprint", "")),
            "request_hash": str(job.get("request_hash", "")),
            "request_payload_json": _json(job.get("request_payload", {})),
            "status": str(job.get("status", "PENDING")),
            "phase": str(job.get("phase", "scan")),
            "progress": int(job.get("progress", 0)),
            "attempt": int(job.get("attempt", 1)),
            "version": int(job.get("version", 1)),
            "source_revision": job.get("source_revision"),
            "source_identity_digest": job.get("source_identity_digest"),
            "active_manifest_key": job.get("active_manifest_key"),
            "active_manifest_sha256": job.get("active_manifest_sha256"),
            "plan_id": job.get("plan_id"),
            "plan_digest": job.get("plan_digest"),
            "manifest_diff_json": _json(job.get("manifest_diff", {})),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if values["actor_scope"] and values["idempotency_fingerprint"]:
                identity = db.execute(
                    "SELECT operation_id, request_hash, attempt FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                    (values["actor_scope"], values["idempotency_fingerprint"]),
                ).fetchone()
                if (
                    identity is None
                    or identity["operation_id"] != values["operation_id"]
                    or identity["request_hash"] != values["request_hash"]
                    or identity["attempt"] != values["attempt"]
                ):
                    raise _error(
                        "ADMIN_INGESTION_IDENTITY_UNCOHERENT",
                        "Job and idempotency identity are not coherent",
                        409,
                    )
            existing = db.execute(
                "SELECT * FROM ingestion_jobs WHERE job_id=?", (values["job_id"],)
            ).fetchone()
            if existing is None:
                columns = ",".join(values)
                marks = ",".join("?" for _ in values)
                db.execute(
                    f"INSERT INTO ingestion_jobs ({columns}) VALUES ({marks})",
                    tuple(values.values()),
                )
                return self._job(
                    db.execute(
                        "SELECT * FROM ingestion_jobs WHERE job_id=?", (values["job_id"],)
                    ).fetchone()
                )
            return self._job(existing)

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "operation_id": row["operation_id"],
            "actor_scope": row["actor_scope"],
            "idempotency_fingerprint": row["idempotency_fingerprint"],
            "request_hash": row["request_hash"],
            "request_payload": _decode(row["request_payload_json"], {}),
            "status": row["status"],
            "phase": row["phase"],
            "progress": row["progress"],
            "attempt": row["attempt"],
            "version": row["version"],
            "lease_owner": row["lease_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "source_revision": row["source_revision"],
            "source_identity_digest": row["source_identity_digest"],
            "active_manifest_key": row["active_manifest_key"],
            "active_manifest_sha256": row["active_manifest_sha256"],
            "plan_id": row["plan_id"],
            "plan_digest": row["plan_digest"],
            "manifest_diff": _decode(row["manifest_diff_json"], {}),
            "candidate_release_id": row["candidate_release_id"],
            "candidate_manifest_key": row["candidate_manifest_key"],
            "candidate_manifest_sha256": row["candidate_manifest_sha256"],
            "result": _decode(row["result_json"]),
            "error_code": row["error_code"],
            "error_detail": row["error_detail"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else self._job(row)

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM ingestion_jobs ORDER BY updated_at DESC LIMIT ?",
                (min(max(limit, 1), 500),),
            ).fetchall()
        return [self._job(row) for row in rows]

    def update_job(
        self, job_id: str, *, expected_version: int, patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise _error(
                    "ADMIN_INGESTION_JOB_NOT_FOUND", "No durable ingestion job exists", 404
                )
            if row["version"] != expected_version:
                raise _error("ADMIN_INGESTION_JOB_STALE", "Durable job version changed", 409)
            allowed = {
                "PENDING": {"PENDING", "RUNNING", "FAILED"},
                "RUNNING": {"RUNNING", "SUCCEEDED", "FAILED"},
                "FAILED": {"FAILED", "RUNNING"},
                "SUCCEEDED": {"SUCCEEDED"},
            }
            target = str(patch.get("status", row["status"]))
            if target not in allowed.get(row["status"], set()):
                raise _error(
                    "ADMIN_INGESTION_JOB_TRANSITION_INVALID", "Invalid durable job transition", 409
                )
            fields: dict[str, Any] = {}
            for key, value in patch.items():
                column = {"manifest_diff": "manifest_diff_json", "result": "result_json"}.get(
                    key, key
                )
                if column in {
                    "status",
                    "phase",
                    "progress",
                    "attempt",
                    "lease_owner",
                    "lease_expires_at",
                    "source_revision",
                    "source_identity_digest",
                    "active_manifest_key",
                    "active_manifest_sha256",
                    "plan_id",
                    "plan_digest",
                    "candidate_release_id",
                    "candidate_manifest_key",
                    "candidate_manifest_sha256",
                    "error_code",
                    "error_detail",
                    "completed_at",
                    "manifest_diff_json",
                    "result_json",
                    "request_payload_json",
                }:
                    fields[column] = (
                        _json(value)
                        if column in {"manifest_diff_json", "result_json", "request_payload_json"}
                        else value
                    )
            fields["version"] = expected_version + 1
            fields["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in fields)
            db.execute(
                f"UPDATE ingestion_jobs SET {assignments} WHERE job_id=? AND version=?",
                (*fields.values(), job_id, expected_version),
            )
            return self._job(
                db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            )

    def claim_job(
        self,
        job_id: str,
        *,
        owner: str,
        now: float,
        expected_version: int | None = None,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise _error(
                    "ADMIN_INGESTION_JOB_NOT_FOUND", "No durable ingestion job exists", 404
                )
            if (
                row["status"] == "RUNNING"
                and row["lease_expires_at"] is not None
                and float(row["lease_expires_at"]) > now
                and row["lease_owner"] != owner
            ):
                raise _error(
                    "ADMIN_INGESTION_JOB_LEASE_HELD", "The ingestion job is already leased", 409
                )
            if expected_version is not None and row["version"] != expected_version:
                raise _error("ADMIN_INGESTION_JOB_STALE", "Durable job version changed", 409)
            next_attempt = int(attempt or row["attempt"])
            if next_attempt < int(row["attempt"]):
                raise _error("ADMIN_INGESTION_JOB_STALE", "Retry attempt moved backwards", 409)
            db.execute(
                "UPDATE ingestion_jobs SET status='RUNNING', phase='scan', progress=0, attempt=?, lease_owner=?, lease_expires_at=?, version=version+1, updated_at=? WHERE job_id=? AND version=?",
                (next_attempt, owner, now + self.lease_seconds, utc_now(), job_id, row["version"]),
            )
            return self._job(
                db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            )

    def recover_expired(self, *, now: float) -> int:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT operation_id, actor_scope, idempotency_fingerprint FROM ingestion_jobs WHERE status='RUNNING' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            result = db.execute(
                "UPDATE ingestion_jobs SET status='FAILED', lease_owner=NULL, lease_expires_at=NULL, error_code='ADMIN_INGESTION_LEASE_EXPIRED', error_detail='Execution lease expired; retry is required', version=version+1, updated_at=? WHERE status='RUNNING' AND lease_expires_at IS NOT NULL AND lease_expires_at<=?",
                (utc_now(), now),
            )
            for row in rows:
                db.execute(
                    "UPDATE ingestion_idempotency SET state='FAILED', updated_at=? WHERE scope=? AND fingerprint=? AND state='IN_PROGRESS'",
                    (utc_now(), row["actor_scope"], row["idempotency_fingerprint"]),
                )
            return result.rowcount

    def retry_failed_job(self, job_id: str, *, owner: str, now: float) -> dict[str, Any]:
        """Atomically increment the logical attempt and claim a FAILED job."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                raise _error(
                    "ADMIN_INGESTION_JOB_NOT_FOUND", "No durable ingestion job exists", 404
                )
            if job["status"] != "FAILED":
                raise _error(
                    "ADMIN_INGESTION_RETRY_INVALID", "Only FAILED jobs can be retried", 409
                )
            idem = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (job["actor_scope"], job["idempotency_fingerprint"]),
            ).fetchone()
            if idem is None or idem["state"] != "FAILED" or idem["attempt"] != job["attempt"]:
                raise _error(
                    "ADMIN_INGESTION_IDENTITY_UNCOHERENT",
                    "Job and idempotency retry state are not coherent",
                    409,
                )
            next_attempt = int(job["attempt"]) + 1
            now_text = utc_now()
            db.execute(
                "UPDATE ingestion_idempotency SET state='IN_PROGRESS', attempt=?, updated_at=? WHERE scope=? AND fingerprint=? AND state='FAILED' AND attempt=?",
                (
                    next_attempt,
                    now_text,
                    job["actor_scope"],
                    job["idempotency_fingerprint"],
                    job["attempt"],
                ),
            )
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise _error(
                    "ADMIN_INGESTION_RETRY_CONFLICT", "Retry was concurrently claimed", 409
                )
            db.execute(
                "UPDATE ingestion_jobs SET status='RUNNING', phase='scan', progress=0, attempt=?, lease_owner=?, lease_expires_at=?, version=version+1, error_code=NULL, error_detail=NULL, completed_at=NULL, updated_at=? WHERE job_id=? AND status='FAILED' AND version=?",
                (next_attempt, owner, now + self.lease_seconds, now_text, job_id, job["version"]),
            )
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise _error(
                    "ADMIN_INGESTION_RETRY_CONFLICT", "Retry was concurrently claimed", 409
                )
            return self._job(
                db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            )

    def complete_terminal(
        self,
        lease: StatefulIdempotencyLease,
        *,
        job_id: str,
        success: bool,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
        expected_lease_owner: str | None = None,
    ) -> dict[str, Any]:
        target_job = "SUCCEEDED" if success else "FAILED"
        target_idem = "SUCCEEDED" if success else "FAILED"
        candidate_release_id = None
        candidate_manifest_key = None
        candidate_manifest_sha256 = None
        if success and result is not None:
            candidate_release_id = result.get("release_id") or result.get("candidate_release_id")
            candidate_manifest_key = result.get("manifest_key") or result.get(
                "candidate_manifest_key"
            )
            candidate_manifest_sha256 = result.get("manifest_sha256") or result.get(
                "candidate_manifest_sha256"
            )
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            idem = db.execute(
                "SELECT * FROM ingestion_idempotency WHERE scope=? AND fingerprint=?",
                (lease.scope, lease.key_fingerprint),
            ).fetchone()
            job = db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            if (
                idem is None
                or job is None
                or idem["operation_id"] != lease.operation_id
                or idem["attempt"] != lease.attempt
                or idem["state"] != "IN_PROGRESS"
                or job["operation_id"] != lease.operation_id
                or job["attempt"] != lease.attempt
                or job["lease_owner"] != (expected_lease_owner or lease.operation_id)
                or (expected_version is not None and job["version"] != expected_version)
            ):
                raise _error(
                    "ADMIN_INGESTION_TERMINAL_STALE",
                    "Job and idempotency lease are not coherent",
                    409,
                )
            now = utc_now()
            db.execute(
                "UPDATE ingestion_idempotency SET state=?, updated_at=? WHERE scope=? AND fingerprint=?",
                (target_idem, now, lease.scope, lease.key_fingerprint),
            )
            db.execute(
                "UPDATE ingestion_jobs SET status=?, phase=?, progress=?, result_json=?, candidate_release_id=?, candidate_manifest_key=?, candidate_manifest_sha256=?, error_code=?, error_detail=?, lease_owner=NULL, lease_expires_at=NULL, completed_at=?, version=version+1, updated_at=? WHERE job_id=?",
                (
                    target_job,
                    "finalize" if success else "failed",
                    100 if success else int(job["progress"]),
                    _json(result) if result is not None else None,
                    candidate_release_id,
                    candidate_manifest_key,
                    candidate_manifest_sha256,
                    (error or {}).get("code"),
                    (error or {}).get("detail"),
                    now,
                    now,
                    job_id,
                ),
            )
            return self._job(
                db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
            )

    def fail_lease(self, lease: StatefulIdempotencyLease, *, detail: str) -> None:
        """Fail an unclaimed/pre-execution lease without overwriting a winner."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now = utc_now()
            db.execute(
                "UPDATE ingestion_idempotency SET state='FAILED', updated_at=? WHERE scope=? AND fingerprint=? AND operation_id=? AND attempt=? AND state='IN_PROGRESS'",
                (now, lease.scope, lease.key_fingerprint, lease.operation_id, lease.attempt),
            )
            if db.execute("SELECT changes()").fetchone()[0] == 1:
                db.execute(
                    "UPDATE ingestion_jobs SET status='FAILED', error_code='ADMIN_INGESTION_EXECUTION_FAILED', error_detail=?, lease_owner=NULL, lease_expires_at=NULL, completed_at=?, version=version+1, updated_at=? WHERE operation_id=? AND attempt=? AND lease_owner=? AND status IN ('PENDING','RUNNING')",
                    (detail, now, now, lease.operation_id, lease.attempt, lease.operation_id),
                )


class SQLiteIngestionAdapter:
    """Durable orchestration adapter around dynamic observers and candidate executor."""

    def __init__(
        self,
        ledger: SQLiteIngestionLedger,
        *,
        source_observer: Callable[[], Mapping[str, Any]] | None = None,
        active_manifest_observer: Callable[[], Mapping[str, Any]] | None = None,
        candidate_executor: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.ledger = ledger
        self.source_observer = source_observer
        self.active_manifest_observer = active_manifest_observer
        self.candidate_executor = candidate_executor

    def _unavailable(self, reason: str) -> ReadObservation:
        return ReadObservation(
            availability="unavailable",
            data=None,
            source="sqlite_ingestion_ledger",
            reason_code=reason,
            detail="Durable ingestion evidence is unavailable or unqualified.",
        )

    def list_jobs(self) -> ReadObservation:
        return ReadObservation(
            availability="available",
            data={"jobs": self.ledger.list_jobs()},
            source="sqlite_ingestion_ledger",
            freshness="live",
            observed_at=utc_now(),
            resource_identity={"path": str(self.ledger.path)},
        )

    def get_job(self, job_id: str) -> ReadObservation:
        job = self.ledger.get_job(job_id)
        if job is None:
            return self._unavailable("ADMIN_INGESTION_JOB_NOT_FOUND")
        return ReadObservation(
            availability="available",
            data=job,
            source="sqlite_ingestion_ledger",
            freshness="live",
            observed_at=utc_now(),
            resource_identity={"path": str(self.ledger.path)},
        )

    def current_index(self) -> ReadObservation:
        return self._unavailable("ADMIN_INGESTION_INDEX_OBSERVER_UNQUALIFIED")

    def list_audits(self) -> ReadObservation:
        return self._unavailable("ADMIN_INGESTION_AUDIT_OBSERVER_UNQUALIFIED")

    def _observe(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.source_observer is None or self.active_manifest_observer is None:
            raise _error(
                "ADMIN_INGESTION_OBSERVER_UNQUALIFIED",
                "Dynamic source and active-manifest observers are required",
            )
        source = dict(self.source_observer())
        active = dict(self.active_manifest_observer())
        if not isinstance(source.get("documents"), list) or not isinstance(
            active.get("document_digests"), Mapping
        ):
            raise _error(
                "ADMIN_INGESTION_OBSERVER_INVALID", "Dynamic observer returned invalid identity"
            )
        source.setdefault("source_identity_digest", _hash(source["documents"]))
        active.setdefault("manifest_sha256", _hash(active))
        return source, active

    def _invoke_executor(
        self,
        operation_id: str,
        request: Any,
        progress: Callable[[str, int], Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self.candidate_executor is None:
            raise _error(
                "ADMIN_INGESTION_EXECUTOR_UNQUALIFIED", "No governed candidate executor is bound"
            )
        signature = inspect.signature(self.candidate_executor)
        count = len(
            [
                p
                for p in signature.parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
        )
        args = (
            (operation_id, request, progress, context)
            if count >= 4
            else (operation_id, request, progress)
            if count >= 3
            else (operation_id, request)
        )
        return self.candidate_executor(*args)

    def sync_blog(
        self,
        operation_id: str,
        request: Any,
        lease: StatefulIdempotencyLease | None = None,
        *,
        execution_owner: str | None = None,
    ) -> dict[str, Any]:
        if lease is None:
            raise _error(
                "ADMIN_INGESTION_LEASE_REQUIRED", "A stateful idempotency lease is required"
            )
        job_id = "syncjob_" + operation_id.removeprefix("admop_")
        existing = self.ledger.get_job(job_id)
        if existing and existing["status"] == "SUCCEEDED":
            return existing
        if existing is None:
            self.ledger.create_job(
                {
                    "job_id": job_id,
                    "operation_id": operation_id,
                    "actor_scope": lease.scope,
                    "idempotency_fingerprint": lease.key_fingerprint,
                    "request_hash": lease.request_hash,
                    "request_payload": _request_payload(request),
                    "status": "PENDING",
                    "attempt": lease.attempt,
                    "version": 1,
                }
            )
        owner = execution_owner or operation_id
        claimed = self.ledger.claim_job(
            job_id,
            owner=owner,
            now=time.time(),
            attempt=lease.attempt,
        )
        try:
            source, active = self._observe()
            plan = build_sync_plan(
                source_revision=str(source["source_revision"]),
                documents=source["documents"],
                active_document_digests=active["document_digests"],
            )
            claimed = self.ledger.update_job(
                job_id,
                expected_version=claimed["version"],
                patch={
                    "source_revision": source["source_revision"],
                    "source_identity_digest": source["source_identity_digest"],
                    "active_manifest_key": active.get("manifest_key"),
                    "active_manifest_sha256": active["manifest_sha256"],
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                    "manifest_diff": plan["plan"]["manifest_diff"],
                },
            )
        except Exception as exc:
            current = self.ledger.get_job(job_id)
            if current and current["status"] == "RUNNING":
                self.ledger.complete_terminal(
                    lease,
                    job_id=job_id,
                    success=False,
                    error=_error_payload(exc),
                    expected_version=current["version"],
                    expected_lease_owner=owner,
                )
            raise
        if bool(plan["plan"]["requires_confirmation"]) and not getattr(
            request, "confirmation", False
        ):
            self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=False,
                error={
                    "code": "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED",
                    "detail": "Confirmation is required",
                },
                expected_version=claimed["version"],
                expected_lease_owner=owner,
            )
            raise _error(
                "ADMIN_INGESTION_DESTRUCTIVE_CONFIRMATION_REQUIRED",
                "Removed or unpublished documents require explicit confirmation",
                409,
            )
        if (
            bool(plan["plan"]["requires_confirmation"])
            and getattr(request, "expected_plan_digest", None) != plan["plan_digest"]
        ):
            self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=False,
                error={
                    "code": "ADMIN_INGESTION_STALE_PLAN",
                    "detail": "The reviewed plan digest is stale or missing",
                },
                expected_version=claimed["version"],
                expected_lease_owner=owner,
            )
            raise _error(
                "ADMIN_INGESTION_STALE_PLAN", "The reviewed plan digest is stale or missing", 409
            )
        fresh_source, fresh_active = self._observe()
        if _hash(fresh_source) != _hash(source) or _hash(fresh_active) != _hash(active):
            self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=False,
                error={
                    "code": "ADMIN_INGESTION_STALE_PLAN",
                    "detail": "Source or active manifest changed before candidate writes",
                },
                expected_version=claimed["version"],
                expected_lease_owner=owner,
            )
            raise _error(
                "ADMIN_INGESTION_STALE_PLAN",
                "Source or active manifest changed before candidate writes",
                409,
            )

        if not plan["plan"]["actions"]:
            return self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=True,
                result={
                    "status": "noop",
                    "plan_id": plan["plan_id"],
                    "plan_digest": plan["plan_digest"],
                },
                expected_version=claimed["version"],
                expected_lease_owner=owner,
            )

        def progress(phase: str, value: int) -> dict[str, Any]:
            current = self.ledger.get_job(job_id)
            if current is None or not 0 <= value <= 100 or value < int(current.get("progress", 0)):
                raise _error("ADMIN_INGESTION_PROGRESS_STALE", "Progress is not monotonic", 409)
            if current.get("status") != "RUNNING" or current.get("lease_owner") != owner:
                raise _error(
                    "ADMIN_INGESTION_JOB_LEASE_STALE", "Execution lease is no longer owned", 409
                )
            return self.ledger.update_job(
                job_id,
                expected_version=int(current["version"]),
                patch={"phase": phase, "progress": value},
            )

        try:
            result = dict(
                self._invoke_executor(
                    operation_id,
                    request,
                    progress,
                    {"source": fresh_source, "active": fresh_active, "plan": plan},
                )
            )
            current = self.ledger.get_job(job_id)
            return self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=True,
                result=result,
                expected_version=current["version"] if current else None,
                expected_lease_owner=owner,
            )
        except Exception as exc:
            current = self.ledger.get_job(job_id)
            if current and current["status"] == "RUNNING":
                self.ledger.complete_terminal(
                    lease,
                    job_id=job_id,
                    success=False,
                    error={
                        "code": getattr(exc, "code", "ADMIN_INGESTION_EXECUTION_FAILED"),
                        "detail": "Ingestion execution failed",
                    },
                    expected_version=current["version"],
                    expected_lease_owner=owner,
                )
            raise

    def sync_blog_with_lease(
        self,
        operation_id: str,
        request: Any,
        lease: StatefulIdempotencyLease,
    ) -> dict[str, Any]:
        return self.sync_blog(operation_id, request, lease)

    def retry_job(self, job_id: str, *, owner: str) -> dict[str, Any]:
        job = self.ledger.get_job(job_id)
        if job is None:
            raise _error("ADMIN_INGESTION_JOB_NOT_FOUND", "No durable ingestion job exists", 404)
        claimed = self.ledger.retry_failed_job(job_id, owner=owner, now=time.time())
        lease = StatefulIdempotencyLease(
            scope=claimed["actor_scope"],
            key_fingerprint=claimed["idempotency_fingerprint"],
            request_hash=claimed["request_hash"],
            operation_id=claimed["operation_id"],
            attempt=claimed["attempt"],
            replayed=False,
        )
        from .m26_admin_ingestion_sync import SyncBlogRequest

        payload = claimed.get("request_payload") or {}
        try:
            replay_request = SyncBlogRequest.model_validate(payload)
        except Exception as exc:
            self.ledger.complete_terminal(
                lease,
                job_id=job_id,
                success=False,
                error={
                    "code": "ADMIN_INGESTION_REQUEST_PAYLOAD_INVALID",
                    "detail": "Persisted ingestion request payload is invalid",
                },
                expected_version=claimed["version"],
                expected_lease_owner=owner,
            )
            raise _error(
                "ADMIN_INGESTION_REQUEST_PAYLOAD_INVALID",
                "Persisted ingestion request payload is invalid",
                409,
            ) from exc
        return self.sync_blog(claimed["operation_id"], replay_request, lease, execution_owner=owner)

    def as_p09_provider(self) -> SQLiteJobsEvidenceProvider:
        return SQLiteJobsEvidenceProvider(self)


class SQLiteJobsEvidenceProvider:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    @staticmethod
    def _convert(observation: ReadObservation) -> EvidenceObservation:
        return EvidenceObservation(
            availability_status=observation.availability,
            reason_code=observation.reason_code,
            detail=observation.detail,
            source=observation.source,
            data=observation.data,
            observed_at=observation.observed_at,
            freshness=observation.freshness,
            resource_identity=observation.resource_identity,
            evidence_digest=observation.evidence_digest,
            source_observed_at=observation.observed_at,
        )

    def list_jobs(self) -> EvidenceObservation:
        return self._convert(self.adapter.list_jobs())

    def get_job(self, job_id: str) -> EvidenceObservation:
        return self._convert(self.adapter.get_job(job_id))

    def list_versions(self) -> EvidenceObservation:
        return EvidenceObservation(
            availability_status="unavailable",
            reason_code="P09_PRODUCTION_POINTER_AUTHORITY_UNQUALIFIED",
            detail="Version evidence remains fail-closed in BP5-R0",
            source="sqlite_ingestion_ledger",
            data=None,
        )


class SQLiteIngestionReadAuthority:
    """Durable job reads with an explicit fail-closed mutation boundary."""

    def __init__(self, ledger: SQLiteIngestionLedger, missing_seams: list[str]) -> None:
        self.ledger = ledger
        self.missing_seams = tuple(sorted(missing_seams))
        self.reason_code = "ADMIN_INGESTION_RUNTIME_SEAMS_UNQUALIFIED"

    def _unavailable(self) -> ReadObservation:
        return ReadObservation(
            availability="unavailable",
            data=None,
            source="sqlite_ingestion_ledger",
            reason_code=self.reason_code,
            detail="Candidate execution is disabled because required runtime seams are unavailable.",
            resource_identity={"missing_seams": list(self.missing_seams)},
        )

    def current_index(self) -> ReadObservation:
        return self._unavailable()

    def list_audits(self) -> ReadObservation:
        return self._unavailable()

    def list_jobs(self) -> ReadObservation:
        return ReadObservation(
            availability="available",
            data={"jobs": self.ledger.list_jobs()},
            source="sqlite_ingestion_ledger",
            freshness="live",
            observed_at=utc_now(),
            resource_identity={"path": str(self.ledger.path)},
        )

    def get_job(self, job_id: str) -> ReadObservation:
        job = self.ledger.get_job(job_id)
        if job is None:
            return ReadObservation(
                availability="unavailable",
                data=None,
                source="sqlite_ingestion_ledger",
                reason_code="ADMIN_INGESTION_JOB_NOT_FOUND",
                detail="No durable ingestion job exists",
            )
        return ReadObservation(
            availability="available",
            data=job,
            source="sqlite_ingestion_ledger",
            freshness="live",
            observed_at=utc_now(),
            resource_identity={"path": str(self.ledger.path)},
        )

    def as_p09_provider(self) -> SQLiteJobsEvidenceProvider:
        return SQLiteJobsEvidenceProvider(self)


def build_sqlite_ingestion_adapter(
    *,
    source_observer: Callable[[], Mapping[str, Any]] | None = None,
    active_manifest_observer: Callable[[], Mapping[str, Any]] | None = None,
    candidate_executor: Callable[..., Mapping[str, Any]] | None = None,
) -> SQLiteIngestionAdapter | SQLiteIngestionReadAuthority | None:
    enabled = os.getenv("M26_INGESTION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return None
    path = os.getenv("M26_INGESTION_STATE_DB", DEFAULT_INGESTION_STATE_DB)
    if source_observer is None:
        source_root = os.getenv("M26_SOURCE_ROOT", "").strip()
        source_observer = (
            dynamic_source_observer_from_path(Path(source_root)) if source_root else None
        )
    active_observer = active_manifest_observer
    if active_observer is None:
        try:
            from .config import Settings
            from .storage import create_object_store

            active_observer = active_manifest_observer_from_store(
                create_object_store(Settings.from_env())
            )
        except Exception:
            # The controller remains truthful and fails closed until an active
            # authority is configured; the durable job/read authority still works.
            active_observer = None
    ledger = SQLiteIngestionLedger(path)
    missing = [
        name
        for name, seam in (
            ("dynamic_source_observer", source_observer),
            ("active_manifest_observer", active_observer),
            ("candidate_executor", candidate_executor),
        )
        if seam is None
    ]
    if missing:
        return SQLiteIngestionReadAuthority(ledger, missing)
    return SQLiteIngestionAdapter(
        ledger,
        source_observer=source_observer,
        active_manifest_observer=active_observer,
        candidate_executor=candidate_executor,
    )


def dynamic_source_observer_from_path(source_root: str | Path) -> Callable[[], Mapping[str, Any]]:
    """Observe a current markdown checkout without frozen corpus assumptions.

    The observer is deliberately read-only: it scans tracked markdown files,
    hashes their exact bytes, and derives revision from the checkout's current
    Git commit (or the deterministic tree digest for a non-Git fixture).
    """

    root = Path(source_root).expanduser().resolve()

    def observe() -> Mapping[str, Any]:
        if not root.is_dir():
            raise _error("ADMIN_INGESTION_SOURCE_UNAVAILABLE", "Source root is unavailable")
        content_root = root / "src/content/blog"
        if not content_root.is_dir():
            content_root = root
        files = sorted(content_root.glob("*/en.md"))
        if not files:
            raise _error(
                "ADMIN_INGESTION_SOURCE_EMPTY",
                "Source root contains no published English blog documents",
            )
        documents: list[dict[str, Any]] = []
        for path in files:
            slug = path.parent.name
            data = path.read_bytes()
            documents.append(
                {
                    "document_id": f"daniel_blog_en__{slug}",
                    "digest": hashlib.sha256(data).hexdigest(),
                    "origin_path": path.relative_to(root).as_posix(),
                    "bytes": len(data),
                }
            )
        identity = {"documents": documents}
        identity_digest = _hash(identity)
        revision = f"tree:{identity_digest}"
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit = completed.stdout.strip().lower()
            if completed.returncode == 0 and commit:
                revision = f"git:{commit}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        return {
            "source_revision": revision,
            "source_identity_digest": identity_digest,
            "documents": documents,
        }

    return observe


def candidate_executor_from_primitives(
    *,
    store: Any,
    vector_materializer: Any,
    artifact_builder: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> Callable[..., Mapping[str, Any]]:
    """Compose the existing immutable writer and Qdrant materializer.

    Artifact construction stays behind the qualified canonical builder seam;
    this function does not scan, compile, tokenize, or index independently.
    """

    def execute(
        _operation_id: str,
        _request: Any,
        progress: Callable[[str, int], Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        inputs = dict(artifact_builder(context))
        progress("artifact_build", 20)
        plan = build_candidate_release_plan(
            release_id=str(inputs["release_id"]),
            source_commit_sha=str(inputs["source_commit_sha"]),
            source_repository_head_sha=str(inputs["source_repository_head_sha"]),
            admission_sha256=str(inputs["admission_sha256"]),
            source_count=int(inputs["source_count"]),
            artifact_bytes=inputs["artifact_bytes"],
            created_at=str(inputs["created_at"]),
        )
        progress("candidate_materialization", 50)
        receipt = stage_candidate_release(
            store=store,
            vector_materializer=vector_materializer,
            plan=plan,
        )
        progress("candidate_verify", 95)
        return receipt

    return execute


def active_manifest_observer_from_store(store: Any) -> Callable[[], Mapping[str, Any]]:
    """Build a read-only observer from the existing active-release resolver."""

    def observe() -> Mapping[str, Any]:
        try:
            active = resolve_active_production_release(store)
            lexical = next(
                item
                for item in active.candidate_manifest.get("artifacts", [])
                if item.get("kind") == "lexical_index"
            )
            payload = json.loads(store.get(str(lexical["key"])))
            documents = payload.get("documents", [])
            digest_map = {
                str(item["document_id"]): str(
                    item.get("digest") or item.get("content_sha256") or item.get("source_digest")
                )
                for item in documents
                if isinstance(item, Mapping) and item.get("document_id")
            }
            if len(digest_map) != len(documents):
                raise ValueError("active lexical artifact has incomplete document identity")
            return {
                "manifest_key": active.candidate_manifest_key,
                "manifest_sha256": active.candidate_manifest_sha256,
                "document_digests": digest_map,
            }
        except Exception as exc:
            raise _error(
                "ADMIN_INGESTION_ACTIVE_MANIFEST_UNAVAILABLE",
                "Active production manifest could not be resolved",
            ) from exc

    return observe


__all__ = [
    "DEFAULT_INGESTION_STATE_DB",
    "SQLiteIngestionAdapter",
    "SQLiteIngestionLedger",
    "SQLiteIngestionReadAuthority",
    "SQLiteJobsEvidenceProvider",
    "active_manifest_observer_from_store",
    "build_sqlite_ingestion_adapter",
    "candidate_executor_from_primitives",
    "dynamic_source_observer_from_path",
]
