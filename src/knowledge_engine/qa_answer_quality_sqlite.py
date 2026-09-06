from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ReleaseConflictError
from .qa_answer_quality import (
    ANSWER_QUALITY_PASS_THRESHOLD,
    ANSWER_QUALITY_RUBRIC_VERSION,
    QA_EXPORT_RECORD_SCHEMA,
    QA_EXPORT_SCHEMA,
    QA_MAX_CLUSTER_VARIANTS,
    QA_MAX_EVENTS,
    QA_MAX_SAMPLE_TRACES,
    QA_RETENTION_DAYS,
    _build_failure_trace,
    _cluster_id,
    _dedupe_identity,
    _event_id,
    _index_identity,
    _iso_now,
    _json_bytes,
    _latency_series,
    _normalize_country,
    _parse_ts,
    _percentile,
    _quality_series,
    _release_identity,
    _resolve_range,
    evaluate_answer_quality,
)
from .storage import FileObjectStore, ObjectStore, sha256_bytes

QA_SQLITE_SCHEMA = "knowledge-engine-answer-quality-sqlite/v1"
QA_DB_PATH_ENV = "M26_QA_DB_PATH"
QA_DEFAULT_PRODUCTION_DB = Path("/var/lib/knowledge-engine/public-api/qa-inbox.sqlite3")


class SqliteQaRepository:
    """Queryable QA metadata in SQLite; full failure traces remain in object storage."""

    def __init__(
        self,
        store: ObjectStore,
        *,
        db_path: Path | None = None,
        prefix: str = "admin/qa",
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
                CREATE TABLE IF NOT EXISTS qa_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qa_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    question TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    result TEXT NOT NULL CHECK(result IN ('pass','fail')),
                    latency_ms INTEGER NOT NULL,
                    country TEXT NOT NULL,
                    release_identity_json TEXT NOT NULL,
                    index_identity_json TEXT NOT NULL,
                    evaluator_json TEXT NOT NULL,
                    dedupe_identity TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    failure_class TEXT,
                    failure_signature TEXT,
                    cluster_id TEXT,
                    failure_trace_key TEXT,
                    suggested_questions_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS qa_events_timestamp_idx ON qa_events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS qa_events_result_timestamp_idx ON qa_events(result, timestamp DESC);
                CREATE INDEX IF NOT EXISTS qa_events_country_timestamp_idx ON qa_events(country, timestamp DESC);
                CREATE INDEX IF NOT EXISTS qa_events_cluster_idx ON qa_events(cluster_id);
                CREATE TABLE IF NOT EXISTS qa_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    representative_question TEXT NOT NULL,
                    variants_json TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    failure_stage TEXT NOT NULL,
                    failure_signature TEXT NOT NULL,
                    failure_class TEXT NOT NULL,
                    sample_trace_ids_json TEXT NOT NULL,
                    lifecycle TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    export_history_json TEXT NOT NULL,
                    resolved_by_release TEXT,
                    last_seen_release_json TEXT NOT NULL,
                    ignored_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS qa_clusters_lifecycle_last_seen_idx
                    ON qa_clusters(lifecycle, last_seen DESC);
                CREATE TABLE IF NOT EXISTS qa_exports (
                    batch_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    cluster_count INTEGER NOT NULL,
                    membership_json TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    sha256 TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO qa_meta(key, value) VALUES('schema_version', ?)",
                (QA_SQLITE_SCHEMA,),
            )
            connection.commit()

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
        now = timestamp or _iso_now()
        evaluation = evaluate_answer_quality(question=question, response=response)
        event_id = _event_id(response, question, now)
        release_identity = _release_identity(response)
        index_identity = _index_identity(response)
        event = {
            "schema_version": "knowledge-engine-answer-quality-event/v1",
            "event_id": event_id,
            "timestamp": now,
            "question": " ".join(question.split()),
            "score": evaluation["score"],
            "result": evaluation["result"],
            "latency_ms": max(0, int(latency_ms)),
            "country": _normalize_country(country),
            "release_identity": release_identity,
            "index_identity": index_identity,
            "evaluator": {
                "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
                "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
                "criteria": evaluation["criteria"],
                "hard_fail_reasons": evaluation["hard_fail_reasons"],
            },
            "dedupe_identity": _dedupe_identity(question, response),
            "trace_id": str(response.get("trace_id") or response.get("request_id") or event_id),
            "failure_class": evaluation.get("failure_class"),
            "failure_signature": evaluation.get("failure_signature"),
            "cluster_id": None,
            "failure_trace_key": None,
            "suggested_questions": {
                "eligible": evaluation["result"] == "pass",
                "evaluation_status": "not_evaluated",
                "rubric": "SUGGESTED_QUESTIONS_OWNER_RUBRIC",
                "threshold": 85,
                "production_published": False,
            },
        }
        if evaluation["result"] == "fail":
            event["cluster_id"] = _cluster_id(question, evaluation)
            trace_key = f"{self.prefix}/failures/{event_id}.json"
            event["failure_trace_key"] = trace_key
            body = _json_bytes(
                _build_failure_trace(
                    event=event,
                    response=response,
                    trace=trace,
                    evaluation=evaluation,
                )
            )
            try:
                self.store.put(
                    trace_key,
                    body,
                    content_type="application/json",
                    sha256=sha256_bytes(body),
                    only_if_absent=True,
                )
            except ReleaseConflictError:
                pass

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM qa_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return self._event_from_row(existing)

            if event["cluster_id"]:
                self._upsert_cluster(
                    connection,
                    cluster_id=str(event["cluster_id"]),
                    question=event["question"],
                    trace_id=event["trace_id"],
                    now=now,
                    release_identity=release_identity,
                    evaluation=evaluation,
                )
            self._insert_event(connection, event)
            cutoff = _parse_ts(now).timestamp() - QA_RETENTION_DAYS * 86400
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            connection.execute("DELETE FROM qa_events WHERE timestamp < ?", (cutoff_iso,))
            count = int(connection.execute("SELECT COUNT(*) FROM qa_events").fetchone()[0])
            if count > QA_MAX_EVENTS:
                connection.execute(
                    """
                    DELETE FROM qa_events WHERE event_id IN (
                        SELECT event_id FROM qa_events ORDER BY timestamp ASC LIMIT ?
                    )
                    """,
                    (count - QA_MAX_EVENTS,),
                )
            connection.commit()
        return event

    def _insert_event(self, connection: sqlite3.Connection, event: Mapping[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO qa_events(
                event_id,timestamp,question,score,result,latency_ms,country,
                release_identity_json,index_identity_json,evaluator_json,dedupe_identity,
                trace_id,failure_class,failure_signature,cluster_id,failure_trace_key,
                suggested_questions_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event["event_id"], event["timestamp"], event["question"], event["score"],
                event["result"], event["latency_ms"], event["country"],
                _dump(event["release_identity"]), _dump(event["index_identity"]),
                _dump(event["evaluator"]), event["dedupe_identity"], event["trace_id"],
                event.get("failure_class"), event.get("failure_signature"), event.get("cluster_id"),
                event.get("failure_trace_key"), _dump(event["suggested_questions"]),
            ),
        )

    def _upsert_cluster(
        self,
        connection: sqlite3.Connection,
        *,
        cluster_id: str,
        question: str,
        trace_id: str,
        now: str,
        release_identity: Mapping[str, Any],
        evaluation: Mapping[str, Any],
    ) -> None:
        row = connection.execute("SELECT * FROM qa_clusters WHERE cluster_id = ?", (cluster_id,)).fetchone()
        if row is None:
            connection.execute(
                """INSERT INTO qa_clusters(
                    cluster_id,representative_question,variants_json,event_count,first_seen,last_seen,
                    failure_stage,failure_signature,failure_class,sample_trace_ids_json,lifecycle,
                    version,export_history_json,resolved_by_release,last_seen_release_json,ignored_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    cluster_id, question, _dump([question]), 1, now, now,
                    str(evaluation.get("failure_stage") or "answer_quality"),
                    str(evaluation.get("failure_signature") or "unknown"),
                    str(evaluation.get("failure_class") or "quality_below_threshold"),
                    _dump([trace_id]), "NEW", 1, _dump([]), None, _dump(release_identity), None,
                ),
            )
            return
        cluster = self._cluster_from_row(row)
        lifecycle = cluster["lifecycle"]
        version = cluster["version"]
        resolved_by_release = cluster.get("resolved_by_release")
        if lifecycle == "VERIFIED":
            lifecycle = "REOPENED"
            version += 1
            resolved_by_release = None
        variants = list(cluster["variants"])
        if question not in variants:
            variants.append(question)
        traces = list(cluster["sample_trace_ids"])
        if trace_id not in traces:
            traces.append(trace_id)
        connection.execute(
            """UPDATE qa_clusters SET variants_json=?,event_count=?,last_seen=?,sample_trace_ids_json=?,
                lifecycle=?,version=?,resolved_by_release=?,last_seen_release_json=? WHERE cluster_id=?""",
            (
                _dump(variants[-QA_MAX_CLUSTER_VARIANTS:]), int(cluster["count"]) + 1, now,
                _dump(traces[-QA_MAX_SAMPLE_TRACES:]), lifecycle, version, resolved_by_release,
                _dump(release_identity), cluster_id,
            ),
        )

    def list_events(self, *, range_name: str = "24h", from_ts: str | None = None,
                    to_ts: str | None = None, result: str | None = None,
                    country: str | None = None, limit: int = 100,
                    cursor: str | None = None) -> dict[str, Any]:
        start, end = _resolve_range(range_name, from_ts, to_ts)
        clauses = ["timestamp >= ?", "timestamp <= ?"]
        params: list[Any] = [start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")]
        if result:
            clauses.append("result = ?")
            params.append(result)
        if country:
            clauses.append("country = ?")
            params.append(_normalize_country(country))
        offset = _decode_cursor(cursor)
        where = " AND ".join(clauses)
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM qa_events WHERE {where}", params).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM qa_events WHERE {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(limit, 500)), offset],
            ).fetchall()
        page = [self._event_from_row(row) for row in rows]
        next_offset = offset + len(page)
        return {"items": page, "next_cursor": f"o{next_offset}" if next_offset < total else None,
                "total": total, "range": range_name}

    def get_event(self, event_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM qa_events WHERE event_id = ?", (event_id,)).fetchone()
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

    def summary(self, *, range_name: str = "24h", from_ts: str | None = None,
                to_ts: str | None = None) -> dict[str, Any]:
        page = self.list_events(range_name=range_name, from_ts=from_ts, to_ts=to_ts, limit=500)
        items = list(page["items"])
        cursor = page["next_cursor"]
        while cursor:
            page = self.list_events(range_name=range_name, from_ts=from_ts, to_ts=to_ts,
                                    limit=500, cursor=cursor)
            items.extend(page["items"])
            cursor = page["next_cursor"]
        scored = [item for item in items if isinstance(item.get("score"), (int, float))]
        passed = [item for item in scored if item.get("result") == "pass"]
        failed = [item for item in scored if item.get("result") == "fail"]
        latencies = sorted(int(item.get("latency_ms", 0)) for item in items)
        return {
            "queries": len(items), "pass_rate": round(len(passed) / len(scored) * 100, 1) if scored else 0.0,
            "avg_score": round(sum(float(item["score"]) for item in scored) / len(scored), 1) if scored else 0.0,
            "failed": len(failed), "median_latency_ms": _median(latencies),
            "p95_latency_ms": _percentile(latencies, 0.95), "quality_series": _quality_series(items),
            "latency_series": _latency_series(items), "rubric_version": ANSWER_QUALITY_RUBRIC_VERSION,
            "threshold": ANSWER_QUALITY_PASS_THRESHOLD,
        }

    def list_clusters(self, *, lifecycle: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM qa_clusters"
        params: tuple[Any, ...] = ()
        if lifecycle:
            sql += " WHERE lifecycle = ?"
            params = (lifecycle.upper(),)
        sql += " ORDER BY last_seen DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._cluster_from_row(row) for row in rows]

    def transition_cluster(self, cluster_id: str, *, state: str, reason: str | None = None,
                           resolved_by_release: str | None = None) -> dict[str, Any]:
        from .qa_answer_quality import LIFECYCLE_STATES, _ALLOWED_TRANSITIONS
        target = state.upper()
        if target not in LIFECYCLE_STATES:
            raise ValueError(f"invalid lifecycle state: {state}")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM qa_clusters WHERE cluster_id = ?", (cluster_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(cluster_id)
            cluster = self._cluster_from_row(row)
            current = str(cluster["lifecycle"])
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
            ignored_reason = reason if target == "IGNORED" else cluster.get("ignored_reason")
            connection.execute("UPDATE qa_clusters SET lifecycle=?,resolved_by_release=?,ignored_reason=? WHERE cluster_id=?",
                               (target, final_release, ignored_reason, cluster_id))
            connection.commit()
        return next(item for item in self.list_clusters() if item["cluster_id"] == cluster_id)

    def export_new_failures(self) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT * FROM qa_clusters WHERE lifecycle IN ('NEW','REOPENED') ORDER BY cluster_id ASC").fetchall()
            clusters = [self._cluster_from_row(row) for row in rows]
            if not clusters:
                connection.rollback()
                return {"created": False, "reason": "NO_NEW_FAILURES"}
            membership = [f"{item['cluster_id']}:{item['version']}" for item in clusters]
            digest = hashlib.sha256("\n".join(membership).encode("utf-8")).hexdigest()[:20]
            batch_id = f"aqx_{digest}"
            export_key = f"{self.prefix}/exports/{batch_id}.jsonl"
            records = [{
                "schema_version": QA_EXPORT_RECORD_SCHEMA, "batch_id": batch_id,
                "cluster_id": c["cluster_id"], "cluster_version": c["version"],
                "representative_question": c["representative_question"], "variants": c["variants"],
                "count": c["count"], "first_seen": c["first_seen"], "last_seen": c["last_seen"],
                "failure_stage": c["failure_stage"], "failure_class": c["failure_class"],
                "failure_signature": c["failure_signature"],
                "sample_trace_ids": c["sample_trace_ids"][:QA_MAX_SAMPLE_TRACES],
                "resolved_by_release": c.get("resolved_by_release"),
            } for c in clusters]
            jsonl = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
            body = jsonl.encode("utf-8")
            try:
                self.store.put(export_key, body, content_type="application/x-ndjson",
                               sha256=sha256_bytes(body), only_if_absent=True)
            except ReleaseConflictError:
                if self.store.get(export_key) != body:
                    connection.rollback()
                    raise
            created_at = _iso_now()
            for cluster in clusters:
                history = list(cluster["export_history"])
                history.append({"batch_id": batch_id, "cluster_version": cluster["version"],
                                "exported_at": created_at})
                connection.execute("UPDATE qa_clusters SET lifecycle='EXPORTED',export_history_json=? WHERE cluster_id=?",
                                   (_dump(history[-20:]), cluster["cluster_id"]))
            export_meta = {"schema_version": QA_EXPORT_SCHEMA, "batch_id": batch_id,
                           "created_at": created_at, "cluster_count": len(clusters),
                           "membership": membership, "object_key": export_key, "sha256": sha256_bytes(body)}
            connection.execute("INSERT OR IGNORE INTO qa_exports(batch_id,created_at,cluster_count,membership_json,object_key,sha256) VALUES(?,?,?,?,?,?)",
                               (batch_id, created_at, len(clusters), _dump(membership), export_key, export_meta["sha256"]))
            connection.commit()
        return {"created": True, **export_meta, "jsonl": jsonl}

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"schema_version": "knowledge-engine-answer-quality-event/v1", "event_id": row["event_id"],
                "timestamp": row["timestamp"], "question": row["question"], "score": int(row["score"]),
                "result": row["result"], "latency_ms": int(row["latency_ms"]), "country": row["country"],
                "release_identity": _load(row["release_identity_json"], {}),
                "index_identity": _load(row["index_identity_json"], {}), "evaluator": _load(row["evaluator_json"], {}),
                "dedupe_identity": row["dedupe_identity"], "trace_id": row["trace_id"],
                "failure_class": row["failure_class"], "failure_signature": row["failure_signature"],
                "cluster_id": row["cluster_id"], "failure_trace_key": row["failure_trace_key"],
                "suggested_questions": _load(row["suggested_questions_json"], {})}

    def _cluster_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"cluster_id": row["cluster_id"], "representative_question": row["representative_question"],
                "variants": _load(row["variants_json"], []), "count": int(row["event_count"]),
                "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                "failure_stage": row["failure_stage"], "failure_signature": row["failure_signature"],
                "failure_class": row["failure_class"], "sample_trace_ids": _load(row["sample_trace_ids_json"], []),
                "lifecycle": row["lifecycle"], "version": int(row["version"]),
                "export_history": _load(row["export_history_json"], []), "resolved_by_release": row["resolved_by_release"],
                "last_seen_release": _load(row["last_seen_release_json"], {}), "ignored_reason": row["ignored_reason"]}


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


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    if not cursor.startswith("o") or not cursor[1:].isdigit():
        raise ValueError("invalid cursor")
    return int(cursor[1:])


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _median(values: list[int]) -> int:
    if not values:
        return 0
    size = len(values)
    middle = size // 2
    return values[middle] if size % 2 else int(round((values[middle - 1] + values[middle]) / 2))


__all__ = ["QA_DB_PATH_ENV", "QA_SQLITE_SCHEMA", "SqliteQaRepository", "qa_db_path_from_env"]
