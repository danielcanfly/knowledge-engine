# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ReleaseConflictError
from .qa_answer_quality import (
    QA_EXPORT_RECORD_SCHEMA,
    QA_EXPORT_SCHEMA,
    QA_MAX_CLUSTER_VARIANTS,
    QA_MAX_EVENTS,
    QA_MAX_SAMPLE_TRACES,
    QA_RETENTION_DAYS,
    _build_failure_trace,
    _dedupe_identity,
    _event_id,
    _index_identity,
    _iso_now,
    _json_bytes,
    _latency_series,
    _normalize_country,
    _normalize_country_filter,
    _parse_ts,
    _percentile,
    _release_identity,
    _resolve_range,
)
from .qa_answer_quality_evaluator import (
    ANSWER_QUALITY_CRITERION_MAX,
    ANSWER_QUALITY_PASS_THRESHOLD,
    ANSWER_QUALITY_RUBRIC_VERSION,
    AnswerQualityEvaluation,
    AnswerQualityEvaluationError,
    AnswerQualityEvaluatorUnavailable,
    AnswerQualitySemanticEvaluator,
    canonical_failure_provenance,
    validate_answer_quality_evaluation,
)
from .qa_failure_clustering import FailureClusterIdentity, build_failure_cluster_identity
from .storage import FileObjectStore, ObjectStore, sha256_bytes

QA_SQLITE_SCHEMA = "knowledge-engine-answer-quality-sqlite/v3"
QA_DB_PATH_ENV = "M26_QA_DB_PATH"
QA_DEFAULT_PRODUCTION_DB = Path("/var/lib/knowledge-engine/public-api/qa-inbox.sqlite3")
EVALUATION_PENDING = "PENDING"
EVALUATION_ANSWERED = "ANSWERED"
EVALUATION_NOT_EVALUATED = "NOT_EVALUATED"
_EVALUATION_STATUSES = {EVALUATION_PENDING, EVALUATION_ANSWERED, EVALUATION_NOT_EVALUATED}


class SqliteQaRepository:
    """Durable compact QA events; semantic evaluation is a separate lifecycle."""

    def __init__(
        self, store: ObjectStore, *, db_path: Path | None = None, prefix: str = "admin/qa"
    ) -> None:
        self.store = store
        self.prefix = prefix.strip("/")
        self.db_path = (db_path or qa_db_path_from_env(store)).resolve()
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
                CREATE TABLE IF NOT EXISTS qa_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qa_clusters (
                    cluster_id TEXT PRIMARY KEY, representative_question TEXT NOT NULL,
                    variants_json TEXT NOT NULL, event_count INTEGER NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    failure_stage TEXT NOT NULL, failure_signature TEXT NOT NULL,
                    failure_class TEXT NOT NULL, sample_trace_ids_json TEXT NOT NULL,
                    lifecycle TEXT NOT NULL, version INTEGER NOT NULL,
                    export_history_json TEXT NOT NULL, resolved_by_release TEXT,
                    last_seen_release_json TEXT NOT NULL, ignored_reason TEXT,
                    intent_family_json TEXT NOT NULL DEFAULT '{}',
                    cluster_match_method TEXT NOT NULL DEFAULT 'legacy',
                    cluster_identity_version TEXT NOT NULL DEFAULT 'legacy/v1'
                );
                CREATE INDEX IF NOT EXISTS qa_clusters_lifecycle_last_seen_idx
                    ON qa_clusters(lifecycle, last_seen DESC);
                CREATE TABLE IF NOT EXISTS qa_exports (
                    batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    cluster_count INTEGER NOT NULL, membership_json TEXT NOT NULL,
                    object_key TEXT NOT NULL, sha256 TEXT NOT NULL
                );
                """
            )
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qa_events'"
            ).fetchone()
            if exists is None:
                self._create_events_table(connection, "qa_events")
            else:
                columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(qa_events)")
                }
                if "evaluation_status" not in columns:
                    self._migrate_v1_events(connection)
                else:
                    self._ensure_event_indexes(connection)
            self._ensure_cluster_columns(connection)
            connection.execute(
                "INSERT OR REPLACE INTO qa_meta(key, value) VALUES('schema_version', ?)",
                (QA_SQLITE_SCHEMA,),
            )
            connection.commit()

    @staticmethod
    def _create_events_table(connection: sqlite3.Connection, name: str) -> None:
        connection.executescript(
            f"""
            CREATE TABLE {name} (
                event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, question TEXT NOT NULL,
                score INTEGER, result TEXT CHECK(result IS NULL OR result IN ('pass','fail')),
                evaluation_status TEXT NOT NULL CHECK(evaluation_status IN ('PENDING','ANSWERED','NOT_EVALUATED')),
                latency_ms INTEGER NOT NULL, country TEXT NOT NULL,
                release_identity_json TEXT NOT NULL, index_identity_json TEXT NOT NULL,
                evaluator_json TEXT NOT NULL, evaluation_error_code TEXT,
                evaluated_at TEXT, evaluation_latency_ms INTEGER, dedupe_identity TEXT NOT NULL,
                trace_id TEXT NOT NULL, failure_class TEXT, failure_signature TEXT,
                cluster_id TEXT, failure_trace_key TEXT, suggested_questions_json TEXT NOT NULL
            );
            """
        )
        SqliteQaRepository._ensure_event_indexes(connection)

    @staticmethod
    def _ensure_event_indexes(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS qa_events_timestamp_idx ON qa_events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS qa_events_status_timestamp_idx ON qa_events(evaluation_status, timestamp DESC);
            CREATE INDEX IF NOT EXISTS qa_events_result_timestamp_idx ON qa_events(result, timestamp DESC);
            CREATE INDEX IF NOT EXISTS qa_events_country_timestamp_idx ON qa_events(country, timestamp DESC);
            CREATE INDEX IF NOT EXISTS qa_events_cluster_idx ON qa_events(cluster_id);
            """
        )

    @staticmethod
    def _ensure_cluster_columns(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(qa_clusters)")
        }
        additions = {
            "intent_family_json": "TEXT NOT NULL DEFAULT '{}'",
            "cluster_match_method": "TEXT NOT NULL DEFAULT 'legacy'",
            "cluster_identity_version": "TEXT NOT NULL DEFAULT 'legacy/v1'",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE qa_clusters ADD COLUMN {name} {declaration}")

    def _migrate_v1_events(self, connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE qa_events RENAME TO qa_events_v1_legacy")
        self._create_events_table(connection, "qa_events")
        rows = connection.execute("SELECT * FROM qa_events_v1_legacy").fetchall()
        for row in rows:
            evaluator = _load(row["evaluator_json"], {})
            evaluator.update(
                {
                    "rubric_version": "ANSWER_QUALITY_HEURISTIC_LEGACY_v0",
                    "provenance": "legacy_heuristic_migrated",
                }
            )
            self._insert_event(
                connection,
                {
                    "event_id": row["event_id"],
                    "timestamp": row["timestamp"],
                    "question": row["question"],
                    "score": row["score"],
                    "result": row["result"],
                    "evaluation_status": EVALUATION_ANSWERED,
                    "latency_ms": row["latency_ms"],
                    "country": row["country"],
                    "release_identity": _load(row["release_identity_json"], {}),
                    "index_identity": _load(row["index_identity_json"], {}),
                    "evaluator": evaluator,
                    "evaluation_error_code": None,
                    "evaluated_at": row["timestamp"],
                    "evaluation_latency_ms": None,
                    "dedupe_identity": row["dedupe_identity"],
                    "trace_id": row["trace_id"],
                    "failure_class": row["failure_class"],
                    "failure_signature": row["failure_signature"],
                    "cluster_id": row["cluster_id"],
                    "failure_trace_key": row["failure_trace_key"],
                    "suggested_questions": _load(row["suggested_questions_json"], {}),
                },
            )
        # Existing v1 clusters were created by the heuristic scorer. Keep them
        # queryable for forensics, but never include them in canonical exports.
        connection.execute(
            "UPDATE qa_clusters SET failure_class='legacy_heuristic:' || failure_class"
        )
        connection.execute("DROP TABLE qa_events_v1_legacy")
        # v1 index names survive the table rename, so CREATE INDEX IF NOT EXISTS
        # above may have no-op'd. Recreate them after dropping the legacy table.
        self._ensure_event_indexes(connection)

    def record_answer(
        self,
        *,
        question: str,
        response: Mapping[str, Any],
        latency_ms: int,
        country: str = "ZZ",
        trace: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Capture one compact PENDING row; this method never invokes the legacy heuristic."""
        del trace
        now = timestamp or _iso_now()
        event_id = _durable_event_id(response, question, now)
        event = {
            "schema_version": "knowledge-engine-answer-quality-event/v2",
            "event_id": event_id,
            "timestamp": now,
            "question": " ".join(question.split()),
            "score": None,
            "result": None,
            "evaluation_status": EVALUATION_PENDING,
            "latency_ms": max(0, int(latency_ms)),
            "country": _normalize_country(country),
            "release_identity": _release_identity(response),
            "index_identity": _index_identity(response),
            "evaluator": {
                "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
                "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
                "status": EVALUATION_PENDING,
            },
            "evaluation_error_code": None,
            "evaluated_at": None,
            "evaluation_latency_ms": None,
            "dedupe_identity": _dedupe_identity(question, response),
            "trace_id": str(response.get("trace_id") or response.get("request_id") or event_id),
            "failure_class": None,
            "failure_signature": None,
            "cluster_id": None,
            "failure_trace_key": None,
            "suggested_questions": {
                "eligible": False,
                "evaluation_status": EVALUATION_PENDING,
                "rubric": "SUGGESTED_QUESTIONS_OWNER_RUBRIC",
                "threshold": 85,
                "production_published": False,
            },
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM qa_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return self._event_from_row(existing)
            self._insert_event(connection, event)
            self._trim(connection, now)
            connection.commit()
        return event

    def evaluate_event(
        self,
        event_id: str,
        *,
        evaluator: AnswerQualitySemanticEvaluator,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        event = self.get_event(event_id)
        if event["evaluation_status"] != EVALUATION_PENDING:
            return event
        try:
            evaluation = validate_answer_quality_evaluation(
                evaluator.evaluate(
                    question=event["question"],
                    answer_payload=answer_payload,
                    forensic_trace=forensic_trace,
                )
            )
        except AnswerQualityEvaluatorUnavailable:
            return self.mark_not_evaluated(
                event_id, reason_code="EVALUATOR_UNAVAILABLE", latency_ms=_elapsed_ms(started)
            )
        except TimeoutError:
            return self.mark_not_evaluated(
                event_id, reason_code="EVALUATOR_TIMEOUT", latency_ms=_elapsed_ms(started)
            )
        except (AnswerQualityEvaluationError, ValueError, TypeError, json.JSONDecodeError):
            return self.mark_not_evaluated(
                event_id, reason_code="EVALUATOR_OUTPUT_INVALID", latency_ms=_elapsed_ms(started)
            )
        except Exception:
            return self.mark_not_evaluated(
                event_id, reason_code="EVALUATOR_ERROR", latency_ms=_elapsed_ms(started)
            )
        return self._persist_evaluation(
            event_id, evaluation, answer_payload, forensic_trace, _elapsed_ms(started)
        )

    def mark_not_evaluated(
        self, event_id: str, *, reason_code: str, latency_ms: int = 0
    ) -> dict[str, Any]:
        reason_code = str(reason_code).strip().upper()[:64] or "EVALUATOR_ERROR"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM qa_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(event_id)
            if row["evaluation_status"] != EVALUATION_PENDING:
                connection.rollback()
                return self._event_from_row(row)
            evaluator = _load(row["evaluator_json"], {})
            evaluator.update(
                {
                    "status": EVALUATION_NOT_EVALUATED,
                    "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
                }
            )
            connection.execute(
                "UPDATE qa_events SET evaluation_status='NOT_EVALUATED',evaluator_json=?,evaluation_error_code=?,evaluated_at=?,evaluation_latency_ms=? WHERE event_id=?",
                (_dump(evaluator), reason_code, _iso_now(), max(0, int(latency_ms)), event_id),
            )
            connection.commit()
        return self.get_event(event_id)

    def _persist_evaluation(
        self,
        event_id: str,
        evaluation: AnswerQualityEvaluation,
        answer_payload: Mapping[str, Any],
        forensic_trace: Mapping[str, Any] | None,
        latency_ms: int,
    ) -> dict[str, Any]:
        event = self.get_event(event_id)
        if event["evaluation_status"] != EVALUATION_PENDING:
            return event
        failure_stage = None
        failure_class = None
        failure_signature = None
        cluster_identity = None
        if evaluation.result == "fail":
            failure_stage, failure_class, failure_signature = canonical_failure_provenance(
                hard_fail_codes=evaluation.hard_fail_codes,
                criterion_scores=evaluation.criterion_scores,
            )
            cluster_identity = build_failure_cluster_identity(
                question=event["question"],
                failure_stage=failure_stage,
                failure_signature=failure_signature,
                intent_family=evaluation.failure_intent,
            )
        evaluator_payload = evaluation.to_payload()
        if evaluation.result == "fail":
            evaluator_payload.update(
                {
                    "failure_stage": failure_stage,
                    "failure_class": failure_class,
                    "failure_signature": failure_signature,
                }
            )
        event.update(
            {
                "score": evaluation.score,
                "result": evaluation.result,
                "evaluation_status": EVALUATION_ANSWERED,
                "evaluated_at": _iso_now(),
                "evaluation_latency_ms": max(0, int(latency_ms)),
                "evaluator": evaluator_payload,
                "failure_class": failure_class,
                "failure_signature": failure_signature,
            }
        )
        if evaluation.result == "fail":
            assert cluster_identity is not None
            event["cluster_id"] = cluster_identity.cluster_id
            event["failure_trace_key"] = f"{self.prefix}/failures/{event_id}.json"
            trace_body = _json_bytes(
                _build_failure_trace(
                    event=event,
                    response=answer_payload,
                    trace=forensic_trace,
                    evaluation={
                        "score": evaluation.score,
                        "criteria": {
                            key: {"score": value, "max": ANSWER_QUALITY_CRITERION_MAX[key]}
                            for key, value in evaluation.criterion_scores.items()
                        },
                        "hard_fail_reasons": list(evaluation.hard_fail_codes),
                        "failure_stage": failure_stage,
                        "failure_class": failure_class,
                        "failure_signature": failure_signature,
                        "rubric_version": evaluation.rubric_version,
                        "evaluator_provider": evaluation.evaluator_provider,
                        "evaluator_model": evaluation.evaluator_model,
                        "evaluator_version": evaluation.evaluator_version,
                        "failure_intent": (
                            evaluation.failure_intent.to_payload()
                            if evaluation.failure_intent
                            else None
                        ),
                        "cluster_match_method": cluster_identity.match_method,
                        "cluster_identity_version": cluster_identity.identity_version,
                    },
                )
            )
            with suppress(ReleaseConflictError):
                self.store.put(
                    event["failure_trace_key"],
                    trace_body,
                    content_type="application/json",
                    sha256=sha256_bytes(trace_body),
                    only_if_absent=True,
                )
        event["suggested_questions"] = {
            **event["suggested_questions"],
            "eligible": evaluation.result == "pass",
            "evaluation_status": EVALUATION_ANSWERED,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT evaluation_status FROM qa_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if current is None:
                connection.rollback()
                raise KeyError(event_id)
            if current[0] != EVALUATION_PENDING:
                connection.rollback()
                return self.get_event(event_id)
            if event["cluster_id"]:
                assert cluster_identity is not None
                self._upsert_cluster(
                    connection,
                    event,
                    failure_stage=failure_stage or "answer_quality",
                    failure_signature=failure_signature or "unknown",
                    failure_class=failure_class or "quality_below_threshold",
                    cluster_identity=cluster_identity,
                )
            self._update_event(connection, event)
            connection.commit()
        return self.get_event(event_id)

    def _insert_event(self, connection: sqlite3.Connection, event: Mapping[str, Any]) -> None:
        columns = (
            "event_id",
            "timestamp",
            "question",
            "score",
            "result",
            "evaluation_status",
            "latency_ms",
            "country",
            "release_identity_json",
            "index_identity_json",
            "evaluator_json",
            "evaluation_error_code",
            "evaluated_at",
            "evaluation_latency_ms",
            "dedupe_identity",
            "trace_id",
            "failure_class",
            "failure_signature",
            "cluster_id",
            "failure_trace_key",
            "suggested_questions_json",
        )
        values = (
            event["event_id"],
            event["timestamp"],
            event["question"],
            event.get("score"),
            event.get("result"),
            event["evaluation_status"],
            event["latency_ms"],
            event["country"],
            _dump(event["release_identity"]),
            _dump(event["index_identity"]),
            _dump(event["evaluator"]),
            event.get("evaluation_error_code"),
            event.get("evaluated_at"),
            event.get("evaluation_latency_ms"),
            event["dedupe_identity"],
            event["trace_id"],
            event.get("failure_class"),
            event.get("failure_signature"),
            event.get("cluster_id"),
            event.get("failure_trace_key"),
            _dump(event["suggested_questions"]),
        )
        connection.execute(
            f"INSERT INTO qa_events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            values,
        )

    def _update_event(self, connection: sqlite3.Connection, event: Mapping[str, Any]) -> None:
        connection.execute(
            "UPDATE qa_events SET score=?,result=?,evaluation_status=?,evaluator_json=?,evaluation_error_code=?,evaluated_at=?,evaluation_latency_ms=?,failure_class=?,failure_signature=?,cluster_id=?,failure_trace_key=?,suggested_questions_json=? WHERE event_id=?",
            (
                event.get("score"),
                event.get("result"),
                event["evaluation_status"],
                _dump(event["evaluator"]),
                event.get("evaluation_error_code"),
                event.get("evaluated_at"),
                event.get("evaluation_latency_ms"),
                event.get("failure_class"),
                event.get("failure_signature"),
                event.get("cluster_id"),
                event.get("failure_trace_key"),
                _dump(event["suggested_questions"]),
                event["event_id"],
            ),
        )

    def _upsert_cluster(
        self,
        connection: sqlite3.Connection,
        event: Mapping[str, Any],
        *,
        failure_stage: str,
        failure_signature: str,
        failure_class: str,
        cluster_identity: FailureClusterIdentity,
    ) -> None:
        cluster_id = str(event["cluster_id"])
        row = connection.execute(
            "SELECT * FROM qa_clusters WHERE cluster_id=?", (cluster_id,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO qa_clusters(cluster_id,representative_question,variants_json,event_count,first_seen,last_seen,failure_stage,failure_signature,failure_class,sample_trace_ids_json,lifecycle,version,export_history_json,resolved_by_release,last_seen_release_json,ignored_reason,intent_family_json,cluster_match_method,cluster_identity_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cluster_id,
                    event["question"],
                    _dump([event["question"]]),
                    1,
                    event["timestamp"],
                    event["timestamp"],
                    failure_stage,
                    failure_signature,
                    failure_class,
                    _dump([event["trace_id"]]),
                    "NEW",
                    1,
                    _dump([]),
                    None,
                    _dump(event["release_identity"]),
                    None,
                    _dump(cluster_identity.intent_family),
                    cluster_identity.match_method,
                    cluster_identity.identity_version,
                ),
            )
            return
        cluster = self._cluster_from_row(row)
        reopened = cluster["lifecycle"] == "VERIFIED"
        lifecycle = "REOPENED" if reopened else cluster["lifecycle"]
        version = cluster["version"] + (1 if reopened else 0)
        variants = list(cluster["variants"])
        traces = list(cluster["sample_trace_ids"])
        if event["question"] not in variants:
            variants.append(event["question"])
        if event["trace_id"] not in traces:
            traces.append(event["trace_id"])
        connection.execute(
            "UPDATE qa_clusters SET variants_json=?,event_count=?,last_seen=?,sample_trace_ids_json=?,lifecycle=?,version=?,resolved_by_release=?,last_seen_release_json=? WHERE cluster_id=?",
            (
                _dump(variants[-QA_MAX_CLUSTER_VARIANTS:]),
                cluster["count"] + 1,
                event["timestamp"],
                _dump(traces[-QA_MAX_SAMPLE_TRACES:]),
                lifecycle,
                version,
                None if reopened else cluster.get("resolved_by_release"),
                _dump(event["release_identity"]),
                cluster_id,
            ),
        )

    def _trim(self, connection: sqlite3.Connection, now: str) -> None:
        cutoff = (
            datetime.fromtimestamp(_parse_ts(now).timestamp() - QA_RETENTION_DAYS * 86400, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        connection.execute("DELETE FROM qa_events WHERE timestamp < ?", (cutoff,))
        count = int(connection.execute("SELECT COUNT(*) FROM qa_events").fetchone()[0])
        if count > QA_MAX_EVENTS:
            connection.execute(
                "DELETE FROM qa_events WHERE event_id IN (SELECT event_id FROM qa_events ORDER BY timestamp ASC LIMIT ?)",
                (count - QA_MAX_EVENTS,),
            )

    def list_events(
        self,
        *,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
        search: str | None = None,
        result: str | None = None,
        evaluation_status: str | None = None,
        country: str | None = None,
        lifecycle: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        start, end = _resolve_range(range_name, from_ts, to_ts)
        clauses = ["timestamp >= ?", "timestamp <= ?"]
        params: list[Any] = [
            start.isoformat().replace("+00:00", "Z"),
            end.isoformat().replace("+00:00", "Z"),
        ]
        normalized_search = _normalize_search(search)
        if normalized_search:
            clauses.append("question LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(_like_contains(normalized_search))
        if result:
            normalized_result = result.casefold()
            if normalized_result not in {"pass", "fail"}:
                raise ValueError("invalid result")
            clauses.append("result=?")
            params.append(normalized_result)
        if evaluation_status:
            normalized = evaluation_status.upper()
            if normalized not in _EVALUATION_STATUSES:
                raise ValueError("invalid evaluation_status")
            clauses.append("evaluation_status=?")
            params.append(normalized)
        if country is not None:
            clauses.append("country=?")
            params.append(_normalize_country_filter(country))
        if lifecycle:
            from .qa_answer_quality import LIFECYCLE_STATES

            normalized_lifecycle = lifecycle.upper()
            if normalized_lifecycle not in LIFECYCLE_STATES:
                raise ValueError("invalid lifecycle")
            clauses.append(
                "cluster_id IN (SELECT cluster_id FROM qa_clusters WHERE lifecycle=?)"
            )
            params.append(normalized_lifecycle)
        where = " AND ".join(clauses)
        offset = _decode_cursor(cursor)
        page_limit = max(1, min(limit, 500))
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM qa_events WHERE {where}", params
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM qa_events WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                [*params, page_limit, offset],
            ).fetchall()
        items = [self._event_from_row(row) for row in rows]
        next_offset = offset + len(items)
        return {
            "items": items,
            "next_cursor": f"o{next_offset}" if next_offset < total else None,
            "total": total,
            "range": range_name,
        }

    def get_event(self, event_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qa_events WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        detail = self._event_from_row(row)
        trace_key = detail.get("failure_trace_key")
        if trace_key:
            try:
                detail["failure_trace"] = json.loads(self.store.get(str(trace_key)).decode("utf-8"))
            except FileNotFoundError:
                detail["failure_trace"] = {"unavailable": True, "trace_key": trace_key}
        return detail

    def record_suggested_questions_evaluation(
        self,
        event_id: str,
        *,
        status: str,
        score: int | None,
        result: str | None,
        rubric_version: str,
        promotion_id: str,
        production_published: bool = False,
        publication_revision: str | None = None,
    ) -> dict[str, Any]:
        allowed_statuses = {"not_evaluated", "ineligible", "eligible", "evaluated_rejected", "published"}
        normalized_status = str(status).strip().casefold()
        if normalized_status not in allowed_statuses:
            raise ValueError("invalid Suggested Questions evaluation status")
        if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100):
            raise ValueError("Suggested Questions score must be an integer from 0 to 100")
        if result is not None and result not in {"pass", "fail"}:
            raise ValueError("Suggested Questions result must be pass or fail")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT suggested_questions_json FROM qa_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(event_id)
            payload = _load(row["suggested_questions_json"], {})
            payload.update(
                {
                    "evaluation_status": normalized_status,
                    "score": score,
                    "result": result,
                    "rubric": rubric_version,
                    "promotion_id": promotion_id,
                    "production_published": bool(production_published),
                    "publication_revision": publication_revision,
                    "evaluated_at": _iso_now(),
                }
            )
            connection.execute(
                "UPDATE qa_events SET suggested_questions_json=? WHERE event_id=?",
                (_dump(payload), event_id),
            )
            connection.commit()
        return self.get_event(event_id)

    def summary(
        self, *, range_name: str = "24h", from_ts: str | None = None, to_ts: str | None = None
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = self.list_events(
                range_name=range_name, from_ts=from_ts, to_ts=to_ts, limit=500, cursor=cursor
            )
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        canonical = [
            item
            for item in items
            if item.get("evaluation_status") == EVALUATION_ANSWERED
            and item.get("evaluator", {}).get("rubric_version") == ANSWER_QUALITY_RUBRIC_VERSION
        ]
        scored = [item for item in canonical if isinstance(item.get("score"), int)]
        passed = [item for item in scored if item.get("result") == "pass"]
        failed = [item for item in scored if item.get("result") == "fail"]
        latencies = sorted(int(item.get("latency_ms", 0)) for item in items)
        return {
            "queries": len(items),
            "scored": len(scored),
            "pass_rate": round(len(passed) / len(scored) * 100, 1) if scored else 0.0,
            "avg_score": round(sum(item["score"] for item in scored) / len(scored), 1)
            if scored
            else 0.0,
            "failed": len(failed),
            "pending": sum(item.get("evaluation_status") == EVALUATION_PENDING for item in items),
            "not_evaluated": sum(
                item.get("evaluation_status") == EVALUATION_NOT_EVALUATED for item in items
            ),
            "median_latency_ms": _median(latencies),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "quality_series": _quality_series(canonical),
            "latency_series": _latency_series(items),
            "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
            "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
        }

    def list_clusters(self, *, lifecycle: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM qa_clusters"
        params: tuple[Any, ...] = ()
        if lifecycle:
            sql += " WHERE lifecycle=?"
            params = (lifecycle.upper(),)
        with self._connect() as connection:
            rows = connection.execute(sql + " ORDER BY last_seen DESC", params).fetchall()
        return [self._cluster_from_row(row) for row in rows]

    def transition_cluster(
        self,
        cluster_id: str,
        *,
        state: str,
        reason: str | None = None,
        resolved_by_release: str | None = None,
    ) -> dict[str, Any]:
        from .qa_answer_quality import _ALLOWED_TRANSITIONS, LIFECYCLE_STATES

        target = state.upper()
        if target not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {state}")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM qa_clusters WHERE cluster_id=?", (cluster_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(cluster_id)
            cluster = self._cluster_from_row(row)
            current = cluster["lifecycle"]
            if target != current and target not in _ALLOWED_TRANSITIONS.get(current, set()):
                connection.rollback()
                raise ValueError(f"invalid lifecycle transition: {current} -> {target}")
            if target == "IGNORED" and not reason:
                connection.rollback()
                raise ValueError("IGNORED requires a reason")
            final_release = resolved_by_release or cluster.get("resolved_by_release")
            if target == "VERIFIED" and not final_release:
                connection.rollback()
                raise ValueError("VERIFIED requires resolved_by_release")
            connection.execute(
                "UPDATE qa_clusters SET lifecycle=?,resolved_by_release=?,ignored_reason=? WHERE cluster_id=?",
                (
                    target,
                    final_release,
                    reason if target == "IGNORED" else cluster.get("ignored_reason"),
                    cluster_id,
                ),
            )
            connection.commit()
        return next(item for item in self.list_clusters() if item["cluster_id"] == cluster_id)

    def export_new_failures(self) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            clusters = [
                self._cluster_from_row(row)
                for row in connection.execute(
                    "SELECT * FROM qa_clusters WHERE lifecycle IN ('NEW','REOPENED') "
                    "AND failure_class NOT LIKE 'legacy_heuristic:%' ORDER BY cluster_id"
                ).fetchall()
            ]
            if not clusters:
                connection.rollback()
                return {"created": False, "reason": "NO_NEW_FAILURES"}
            membership = [f"{item['cluster_id']}:{item['version']}" for item in clusters]
            digest = hashlib.sha256("\n".join(membership).encode()).hexdigest()[:20]
            batch_id = f"aqx_{digest}"
            key = f"{self.prefix}/exports/{batch_id}.jsonl"
            records = [
                {
                    "schema_version": QA_EXPORT_RECORD_SCHEMA,
                    "batch_id": batch_id,
                    "cluster_id": c["cluster_id"],
                    "cluster_version": c["version"],
                    "representative_question": c["representative_question"],
                    "variants": c["variants"],
                    "count": c["count"],
                    "first_seen": c["first_seen"],
                    "last_seen": c["last_seen"],
                    "failure_stage": c["failure_stage"],
                    "failure_class": c["failure_class"],
                    "failure_signature": c["failure_signature"],
                    "intent_family": c["intent_family"],
                    "cluster_match_method": c["cluster_match_method"],
                    "cluster_identity_version": c["cluster_identity_version"],
                    "sample_trace_ids": c["sample_trace_ids"][:QA_MAX_SAMPLE_TRACES],
                    "sample_traces": self._sample_traces_for_cluster(connection, c),
                    "resolved_by_release": c.get("resolved_by_release"),
                }
                for c in clusters
            ]
            body = "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
            ).encode()
            try:
                self.store.put(
                    key,
                    body,
                    content_type="application/x-ndjson",
                    sha256=sha256_bytes(body),
                    only_if_absent=True,
                )
            except ReleaseConflictError:
                if self.store.get(key) != body:
                    connection.rollback()
                    raise
            created = _iso_now()
            for c in clusters:
                history = c["export_history"] + [
                    {"batch_id": batch_id, "cluster_version": c["version"], "exported_at": created}
                ]
                connection.execute(
                    "UPDATE qa_clusters SET lifecycle='EXPORTED',export_history_json=? WHERE cluster_id=?",
                    (_dump(history[-20:]), c["cluster_id"]),
                )
            meta = {
                "schema_version": QA_EXPORT_SCHEMA,
                "batch_id": batch_id,
                "created_at": created,
                "cluster_count": len(clusters),
                "membership": membership,
                "object_key": key,
                "sha256": sha256_bytes(body),
            }
            connection.execute(
                "INSERT OR IGNORE INTO qa_exports(batch_id,created_at,cluster_count,membership_json,object_key,sha256) VALUES(?,?,?,?,?,?)",
                (batch_id, created, len(clusters), _dump(membership), key, meta["sha256"]),
            )
            connection.commit()
        return {"created": True, **meta, "jsonl": body.decode()}

    def export_selected_failures(
        self,
        *,
        event_ids: list[str] | tuple[str, ...] = (),
        cluster_ids: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        selected_events = _bounded_export_ids(event_ids, label="event_ids")
        selected_clusters = _bounded_export_ids(cluster_ids, label="cluster_ids")
        if not selected_events and not selected_clusters:
            raise ValueError("selected export requires event_ids or cluster_ids")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cluster_id_set = set(selected_clusters)
            if selected_events:
                placeholders = ",".join("?" for _ in selected_events)
                rows = connection.execute(
                    f"SELECT event_id,cluster_id FROM qa_events WHERE event_id IN ({placeholders})",
                    selected_events,
                ).fetchall()
                found = {str(row["event_id"]): row["cluster_id"] for row in rows}
                missing = sorted(set(selected_events) - set(found))
                if missing:
                    connection.rollback()
                    raise ValueError("unknown selected event_ids: " + ",".join(missing[:10]))
                non_failures = sorted(
                    event_id for event_id, cluster_id in found.items() if not cluster_id
                )
                if non_failures:
                    connection.rollback()
                    raise ValueError(
                        "selected events must be clustered failures: "
                        + ",".join(non_failures[:10])
                    )
                cluster_id_set.update(str(cluster_id) for cluster_id in found.values())
            if len(cluster_id_set) > 500:
                connection.rollback()
                raise ValueError("selected export may resolve to at most 500 unique clusters")

            clusters = self._load_export_clusters(connection, sorted(cluster_id_set))
            requested_cluster_ids = set(cluster_id_set)
            found_cluster_ids = {str(cluster["cluster_id"]) for cluster in clusters}
            missing_clusters = sorted(requested_cluster_ids - found_cluster_ids)
            if missing_clusters:
                connection.rollback()
                raise ValueError(
                    "unknown or legacy selected cluster_ids: "
                    + ",".join(missing_clusters[:10])
                )
            return self._materialize_secondary_export(
                connection,
                clusters,
                mode="selected",
            )

    def export_filtered_failures(
        self,
        *,
        range_name: str = "24h",
        from_ts: str | None = None,
        to_ts: str | None = None,
        search: str | None = None,
        result: str | None = None,
        evaluation_status: str | None = None,
        country: str | None = None,
        lifecycle: str | None = None,
    ) -> dict[str, Any]:
        start, end = _resolve_range(range_name, from_ts, to_ts)
        clauses = [
            "e.timestamp >= ?",
            "e.timestamp <= ?",
            "e.cluster_id IS NOT NULL",
            "c.failure_class NOT LIKE 'legacy_heuristic:%'",
        ]
        params: list[Any] = [
            start.isoformat().replace("+00:00", "Z"),
            end.isoformat().replace("+00:00", "Z"),
        ]
        normalized_search = _normalize_search(search)
        if normalized_search:
            clauses.append("e.question LIKE ? ESCAPE '!' COLLATE NOCASE")
            params.append(_like_contains(normalized_search))
        if result:
            normalized_result = result.casefold()
            if normalized_result not in {"pass", "fail"}:
                raise ValueError("invalid result")
            clauses.append("e.result=?")
            params.append(normalized_result)
        if evaluation_status:
            normalized_status = evaluation_status.upper()
            if normalized_status not in _EVALUATION_STATUSES:
                raise ValueError("invalid evaluation_status")
            clauses.append("e.evaluation_status=?")
            params.append(normalized_status)
        if country is not None:
            clauses.append("e.country=?")
            params.append(_normalize_country_filter(country))
        if lifecycle:
            from .qa_answer_quality import LIFECYCLE_STATES

            normalized_lifecycle = lifecycle.upper()
            if normalized_lifecycle not in LIFECYCLE_STATES:
                raise ValueError("invalid lifecycle")
            clauses.append("c.lifecycle=?")
            params.append(normalized_lifecycle)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT DISTINCT c.* FROM qa_clusters c "
                "JOIN qa_events e ON e.cluster_id=c.cluster_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY c.cluster_id",
                params,
            ).fetchall()
            clusters = [self._cluster_from_row(row) for row in rows]
            return self._materialize_secondary_export(
                connection,
                clusters,
                mode="current_filter",
            )

    def _load_export_clusters(
        self,
        connection: sqlite3.Connection,
        cluster_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not cluster_ids:
            return []
        placeholders = ",".join("?" for _ in cluster_ids)
        rows = connection.execute(
            f"SELECT * FROM qa_clusters WHERE cluster_id IN ({placeholders}) "
            "AND failure_class NOT LIKE 'legacy_heuristic:%' ORDER BY cluster_id",
            cluster_ids,
        ).fetchall()
        return [self._cluster_from_row(row) for row in rows]

    def _sample_traces_for_cluster(
        self,
        connection: sqlite3.Connection,
        cluster: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        trace_ids = [
            str(trace_id)
            for trace_id in list(cluster.get("sample_trace_ids", []))[:QA_MAX_SAMPLE_TRACES]
            if str(trace_id)
        ]
        if not trace_ids:
            return []
        placeholders = ",".join("?" for _ in trace_ids)
        rows = connection.execute(
            f"SELECT trace_id,failure_trace_key FROM qa_events "
            f"WHERE cluster_id=? AND trace_id IN ({placeholders})",
            [cluster["cluster_id"], *trace_ids],
        ).fetchall()
        trace_keys = {
            str(row["trace_id"]): str(row["failure_trace_key"] or "") for row in rows
        }
        traces: list[dict[str, Any]] = []
        for trace_id in trace_ids:
            key = trace_keys.get(trace_id, "")
            if not key:
                traces.append({"trace_id": trace_id, "unavailable": True})
                continue
            try:
                payload = json.loads(self.store.get(key).decode("utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
                traces.append({"trace_id": trace_id, "unavailable": True})
                continue
            if not isinstance(payload, dict):
                traces.append({"trace_id": trace_id, "unavailable": True})
                continue
            traces.append(payload)
        return traces

    def _materialize_secondary_export(
        self,
        connection: sqlite3.Connection,
        clusters: list[dict[str, Any]],
        *,
        mode: str,
    ) -> dict[str, Any]:
        if not clusters:
            connection.rollback()
            return {"created": False, "reason": "NO_MATCHING_FAILURES", "mode": mode}

        membership = [f"{item['cluster_id']}:{item['version']}" for item in clusters]
        record_payloads = [
            {
                "schema_version": QA_EXPORT_RECORD_SCHEMA,
                "cluster_id": c["cluster_id"],
                "cluster_version": c["version"],
                "representative_question": c["representative_question"],
                "variants": c["variants"],
                "count": c["count"],
                "first_seen": c["first_seen"],
                "last_seen": c["last_seen"],
                "failure_stage": c["failure_stage"],
                "failure_class": c["failure_class"],
                "failure_signature": c["failure_signature"],
                "intent_family": c["intent_family"],
                "cluster_match_method": c["cluster_match_method"],
                "cluster_identity_version": c["cluster_identity_version"],
                "sample_trace_ids": c["sample_trace_ids"][:QA_MAX_SAMPLE_TRACES],
                "sample_traces": self._sample_traces_for_cluster(connection, c),
                "resolved_by_release": c.get("resolved_by_release"),
            }
            for c in clusters
        ]
        snapshot_digest = hashlib.sha256(
            _json_bytes({"mode": mode, "records": record_payloads})
        ).hexdigest()[:20]
        batch_id = f"aqx_{snapshot_digest}"
        key = f"{self.prefix}/exports/{batch_id}.jsonl"
        records = [{"batch_id": batch_id, **record} for record in record_payloads]
        body = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        ).encode()
        body_sha256 = sha256_bytes(body)

        existing = connection.execute(
            "SELECT * FROM qa_exports WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if existing is not None:
            if str(existing["sha256"]) != body_sha256:
                connection.rollback()
                raise ReleaseConflictError("QA export batch identity content mismatch")
            try:
                stored = self.store.get(key)
            except FileNotFoundError:
                stored = body
                self.store.put(
                    key,
                    body,
                    content_type="application/x-ndjson",
                    sha256=body_sha256,
                    only_if_absent=True,
                )
            if stored != body:
                connection.rollback()
                raise ReleaseConflictError("QA export object content mismatch")
            connection.rollback()
            return {
                "created": False,
                "reused": True,
                "mode": mode,
                "schema_version": QA_EXPORT_SCHEMA,
                "batch_id": batch_id,
                "created_at": str(existing["created_at"]),
                "cluster_count": len(clusters),
                "membership": membership,
                "object_key": key,
                "sha256": body_sha256,
                "jsonl": body.decode(),
            }

        try:
            self.store.put(
                key,
                body,
                content_type="application/x-ndjson",
                sha256=body_sha256,
                only_if_absent=True,
            )
        except ReleaseConflictError:
            if self.store.get(key) != body:
                connection.rollback()
                raise
        created = _iso_now()
        for cluster in clusters:
            history = list(cluster["export_history"])
            history.append(
                {
                    "batch_id": batch_id,
                    "cluster_version": cluster["version"],
                    "exported_at": created,
                    "export_mode": mode,
                }
            )
            connection.execute(
                "UPDATE qa_clusters SET export_history_json=? WHERE cluster_id=?",
                (_dump(history[-20:]), cluster["cluster_id"]),
            )
        connection.execute(
            "INSERT INTO qa_exports(batch_id,created_at,cluster_count,membership_json,object_key,sha256) VALUES(?,?,?,?,?,?)",
            (batch_id, created, len(clusters), _dump(membership), key, body_sha256),
        )
        connection.commit()
        return {
            "created": True,
            "reused": False,
            "mode": mode,
            "schema_version": QA_EXPORT_SCHEMA,
            "batch_id": batch_id,
            "created_at": created,
            "cluster_count": len(clusters),
            "membership": membership,
            "object_key": key,
            "sha256": body_sha256,
            "jsonl": body.decode(),
        }

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": "knowledge-engine-answer-quality-event/v2",
            "event_id": row["event_id"],
            "timestamp": row["timestamp"],
            "question": row["question"],
            "score": row["score"],
            "result": row["result"],
            "evaluation_status": row["evaluation_status"],
            "latency_ms": int(row["latency_ms"]),
            "country": row["country"],
            "release_identity": _load(row["release_identity_json"], {}),
            "index_identity": _load(row["index_identity_json"], {}),
            "evaluator": _load(row["evaluator_json"], {}),
            "evaluation_error_code": row["evaluation_error_code"],
            "evaluated_at": row["evaluated_at"],
            "evaluation_latency_ms": row["evaluation_latency_ms"],
            "dedupe_identity": row["dedupe_identity"],
            "trace_id": row["trace_id"],
            "failure_class": row["failure_class"],
            "failure_signature": row["failure_signature"],
            "cluster_id": row["cluster_id"],
            "failure_trace_key": row["failure_trace_key"],
            "suggested_questions": _load(row["suggested_questions_json"], {}),
        }

    def _cluster_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "cluster_id": row["cluster_id"],
            "representative_question": row["representative_question"],
            "variants": _load(row["variants_json"], []),
            "count": int(row["event_count"]),
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "failure_stage": row["failure_stage"],
            "failure_signature": row["failure_signature"],
            "failure_class": row["failure_class"],
            "sample_trace_ids": _load(row["sample_trace_ids_json"], []),
            "lifecycle": row["lifecycle"],
            "version": int(row["version"]),
            "export_history": _load(row["export_history_json"], []),
            "resolved_by_release": row["resolved_by_release"],
            "last_seen_release": _load(row["last_seen_release_json"], {}),
            "ignored_reason": row["ignored_reason"],
            "intent_family": _load(row["intent_family_json"], {}),
            "cluster_match_method": row["cluster_match_method"],
            "cluster_identity_version": row["cluster_identity_version"],
        }


def qa_db_path_from_env(store: ObjectStore) -> Path:
    configured = os.environ.get(QA_DB_PATH_ENV, "").strip()
    if configured:
        return Path(configured)
    if isinstance(store, FileObjectStore):
        return store.root / ".qa" / "qa-inbox.sqlite3"
    rate_limit_db = os.environ.get("M26_ASK_RATE_LIMIT_DB_PATH", "").strip()
    if rate_limit_db:
        return Path(rate_limit_db).parent / "qa-inbox.sqlite3"
    if os.environ.get("APP_ENV", "").strip().casefold() == "production":
        return QA_DEFAULT_PRODUCTION_DB
    return Path(tempfile.gettempdir()) / f"m26-qa-inbox-{os.getpid()}.sqlite3"


def _normalize_search(value: str | None) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split())
    if len(normalized) > 500:
        raise ValueError("search must be at most 500 characters")
    return normalized


def _like_contains(value: str) -> str:
    escaped = value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%"


def _bounded_export_ids(values: list[str] | tuple[str, ...], *, label: str) -> list[str]:
    if len(values) > 500:
        raise ValueError(f"{label} may contain at most 500 items")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item:
            continue
        if len(item) > 256:
            raise ValueError(f"{label} item is too long")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    if not cursor.startswith("o") or not cursor[1:].isdigit():
        raise ValueError("invalid cursor")
    return int(cursor[1:])


def _durable_event_id(response: Mapping[str, Any], question: str, timestamp: str) -> str:
    """Prefer the runtime request identity so capture retries cannot duplicate rows."""
    identity = str(response.get("trace_id") or response.get("request_id") or "").strip()
    if not identity:
        return _event_id(response, question, timestamp)
    material = f"{identity}\n{' '.join(question.split())}"
    return f"qa_{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _median(values: list[int]) -> int:
    if not values:
        return 0
    middle = len(values) // 2
    return (
        values[middle] if len(values) % 2 else int(round((values[middle - 1] + values[middle]) / 2))
    )


def _quality_series(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        buckets.setdefault(str(item.get("timestamp", ""))[:10], []).append(item)
    return [
        {
            "date": key,
            "avg_score": round(sum(float(item["score"]) for item in bucket) / len(bucket), 1),
            "pass_rate": round(
                sum(item.get("result") == "pass" for item in bucket) / len(bucket) * 100, 1
            ),
        }
        for key, bucket in sorted(buckets.items())
        if bucket
    ]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "EVALUATION_ANSWERED",
    "EVALUATION_NOT_EVALUATED",
    "EVALUATION_PENDING",
    "QA_DB_PATH_ENV",
    "QA_SQLITE_SCHEMA",
    "SqliteQaRepository",
    "qa_db_path_from_env",
]
