from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from .errors import ReleaseConflictError
from .qa_answer_quality import (
    LIFECYCLE_STATES,
    QA_EXPORT_RECORD_SCHEMA,
    QA_EXPORT_SCHEMA,
    QA_MAX_SAMPLE_TRACES,
    _iso_now,
    _normalize_country_filter,
    _resolve_range,
)
from .qa_answer_quality_sqlite import (
    EVALUATION_ANSWERED,
    EVALUATION_NOT_EVALUATED,
    EVALUATION_PENDING,
    SqliteQaRepository,
    _bounded_export_ids,
    _decode_cursor,
    _dump,
    _like_contains,
    _load,
    _normalize_search,
)
from .storage import sha256_bytes

_EVALUATION_STATUSES = {
    EVALUATION_PENDING,
    EVALUATION_ANSWERED,
    EVALUATION_NOT_EVALUATED,
}


class QualifiedQaRepositoryV2(SqliteQaRepository):
    """Production QA Inbox v2 query/export contract over the canonical SQLite store.

    Persistence, evaluation, clustering and lifecycle remain owned by
    ``SqliteQaRepository``. This class narrows the P0-B change to the owner-facing
    query and export contract so existing capture/storage foundations are not rebuilt.
    """

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
        failure_type: str | None = None,
        score_min: int | None = None,
        score_max: int | None = None,
        latency_min_ms: int | None = None,
        latency_max_ms: int | None = None,
        release: str | None = None,
        index_revision: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        start, end = _resolve_range(range_name, from_ts, to_ts)
        clauses, params = _event_filter_clauses(
            alias="",
            start=start.isoformat().replace("+00:00", "Z"),
            end=end.isoformat().replace("+00:00", "Z"),
            search=search,
            result=result,
            evaluation_status=evaluation_status,
            country=country,
            lifecycle=lifecycle,
            failure_type=failure_type,
            score_min=score_min,
            score_max=score_max,
            latency_min_ms=latency_min_ms,
            latency_max_ms=latency_max_ms,
            release=release,
            index_revision=index_revision,
            provider=provider,
            model=model,
        )
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
                return {"created": False, "reason": "NO_NEW_FAILURES", "mode": "new"}
            return self._materialize_v2_export(
                connection,
                clusters,
                mode="new",
                filters={
                    "lifecycle": ["NEW", "REOPENED"],
                    "already_exported": False,
                },
                transition_primary=True,
            )

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
            return self._materialize_v2_export(
                connection,
                clusters,
                mode="selected",
                filters={
                    "selected_event_count": len(selected_events),
                    "selected_cluster_count": len(selected_clusters),
                },
                transition_primary=False,
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
        failure_type: str | None = None,
        score_min: int | None = None,
        score_max: int | None = None,
        latency_min_ms: int | None = None,
        latency_max_ms: int | None = None,
        release: str | None = None,
        index_revision: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        start, end = _resolve_range(range_name, from_ts, to_ts)
        clauses, params = _event_filter_clauses(
            alias="e",
            start=start.isoformat().replace("+00:00", "Z"),
            end=end.isoformat().replace("+00:00", "Z"),
            search=search,
            result=result,
            evaluation_status=evaluation_status,
            country=country,
            lifecycle=lifecycle,
            failure_type=failure_type,
            score_min=score_min,
            score_max=score_max,
            latency_min_ms=latency_min_ms,
            latency_max_ms=latency_max_ms,
            release=release,
            index_revision=index_revision,
            provider=provider,
            model=model,
        )
        clauses.extend(
            [
                "e.cluster_id IS NOT NULL",
                "c.failure_class NOT LIKE 'legacy_heuristic:%'",
            ]
        )
        filters = _filter_snapshot(
            range_name=range_name,
            from_ts=from_ts,
            to_ts=to_ts,
            search=search,
            result=result,
            evaluation_status=evaluation_status,
            country=country,
            lifecycle=lifecycle,
            failure_type=failure_type,
            score_min=score_min,
            score_max=score_max,
            latency_min_ms=latency_min_ms,
            latency_max_ms=latency_max_ms,
            release=release,
            index_revision=index_revision,
            provider=provider,
            model=model,
        )
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
            return self._materialize_v2_export(
                connection,
                clusters,
                mode="current_filter",
                filters=filters,
                transition_primary=False,
            )

    def _materialize_v2_export(
        self,
        connection: sqlite3.Connection,
        clusters: list[dict[str, Any]],
        *,
        mode: str,
        filters: Mapping[str, Any],
        transition_primary: bool,
    ) -> dict[str, Any]:
        if not clusters:
            connection.rollback()
            return {"created": False, "reason": "NO_MATCHING_FAILURES", "mode": mode}

        membership = [f"{item['cluster_id']}:{item['version']}" for item in clusters]
        normalized_filters = json.loads(
            json.dumps(dict(filters), ensure_ascii=False, sort_keys=True, default=str)
        )
        record_payloads: list[dict[str, Any]] = []
        for cluster in clusters:
            stats = _cluster_export_stats(connection, str(cluster["cluster_id"]))
            record_payloads.append(
                {
                    "schema_version": QA_EXPORT_RECORD_SCHEMA,
                    "cluster_id": cluster["cluster_id"],
                    "cluster_version": cluster["version"],
                    "representative_question": cluster["representative_question"],
                    "variants": cluster["variants"],
                    "count": cluster["count"],
                    "event_count": stats["event_count"],
                    "first_seen": cluster["first_seen"],
                    "last_seen": cluster["last_seen"],
                    "release_range": stats["release_range"],
                    "filters": normalized_filters,
                    "failure_stage": cluster["failure_stage"],
                    "failure_class": cluster["failure_class"],
                    "failure_signature": cluster["failure_signature"],
                    "intent_family": cluster["intent_family"],
                    "cluster_match_method": cluster["cluster_match_method"],
                    "cluster_identity_version": cluster["cluster_identity_version"],
                    "sample_trace_ids": cluster["sample_trace_ids"][:QA_MAX_SAMPLE_TRACES],
                    "sample_traces": self._sample_traces_for_cluster(connection, cluster),
                    "resolved_by_release": cluster.get("resolved_by_release"),
                }
            )

        snapshot_digest = hashlib.sha256(
            json.dumps(
                {"mode": mode, "filters": normalized_filters, "records": record_payloads},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:20]
        batch_id = f"aqx_{snapshot_digest}"
        key = f"{self.prefix}/exports/{batch_id}.jsonl"
        existing = connection.execute(
            "SELECT * FROM qa_exports WHERE batch_id=?", (batch_id,)
        ).fetchone()
        exported_at = str(existing["created_at"]) if existing is not None else _iso_now()
        records = [
            {
                "batch_id": batch_id,
                "export_mode": mode,
                "exported_at": exported_at,
                **record,
            }
            for record in record_payloads
        ]
        body = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        ).encode()
        body_sha256 = sha256_bytes(body)

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
                "created_at": exported_at,
                "cluster_count": len(clusters),
                "event_count": sum(int(record["event_count"]) for record in record_payloads),
                "membership": membership,
                "filters": normalized_filters,
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

        for cluster in clusters:
            history = list(cluster["export_history"])
            history.append(
                {
                    "batch_id": batch_id,
                    "cluster_version": cluster["version"],
                    "exported_at": exported_at,
                    "export_mode": mode,
                    "filters": normalized_filters,
                }
            )
            if transition_primary:
                connection.execute(
                    "UPDATE qa_clusters SET lifecycle='EXPORTED',export_history_json=? WHERE cluster_id=?",
                    (_dump(history[-20:]), cluster["cluster_id"]),
                )
            else:
                connection.execute(
                    "UPDATE qa_clusters SET export_history_json=? WHERE cluster_id=?",
                    (_dump(history[-20:]), cluster["cluster_id"]),
                )
        connection.execute(
            "INSERT INTO qa_exports(batch_id,created_at,cluster_count,membership_json,object_key,sha256) VALUES(?,?,?,?,?,?)",
            (
                batch_id,
                exported_at,
                len(clusters),
                _dump(membership),
                key,
                body_sha256,
            ),
        )
        connection.commit()
        return {
            "created": True,
            "reused": False,
            "mode": mode,
            "schema_version": QA_EXPORT_SCHEMA,
            "batch_id": batch_id,
            "created_at": exported_at,
            "cluster_count": len(clusters),
            "event_count": sum(int(record["event_count"]) for record in record_payloads),
            "membership": membership,
            "filters": normalized_filters,
            "object_key": key,
            "sha256": body_sha256,
            "jsonl": body.decode(),
        }


def _event_filter_clauses(
    *,
    alias: str,
    start: str,
    end: str,
    search: str | None,
    result: str | None,
    evaluation_status: str | None,
    country: str | None,
    lifecycle: str | None,
    failure_type: str | None,
    score_min: int | None,
    score_max: int | None,
    latency_min_ms: int | None,
    latency_max_ms: int | None,
    release: str | None,
    index_revision: str | None,
    provider: str | None,
    model: str | None,
) -> tuple[list[str], list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses = [f"{prefix}timestamp >= ?", f"{prefix}timestamp <= ?"]
    params: list[Any] = [start, end]

    normalized_search = _normalize_search(search)
    if normalized_search:
        clauses.append(f"{prefix}question LIKE ? ESCAPE '!' COLLATE NOCASE")
        params.append(_like_contains(normalized_search))
    if result:
        normalized_result = str(result).casefold()
        if normalized_result not in {"pass", "fail"}:
            raise ValueError("invalid result")
        clauses.append(f"{prefix}result=?")
        params.append(normalized_result)
    if evaluation_status:
        normalized_status = str(evaluation_status).upper()
        if normalized_status not in _EVALUATION_STATUSES:
            raise ValueError("invalid evaluation_status")
        clauses.append(f"{prefix}evaluation_status=?")
        params.append(normalized_status)
    if country is not None:
        clauses.append(f"{prefix}country=?")
        params.append(_normalize_country_filter(country))
    if lifecycle:
        normalized_lifecycle = str(lifecycle).upper()
        if normalized_lifecycle not in LIFECYCLE_STATES:
            raise ValueError("invalid lifecycle")
        clauses.append(
            f"{prefix}cluster_id IN (SELECT cluster_id FROM qa_clusters WHERE lifecycle=?)"
        )
        params.append(normalized_lifecycle)

    failure_type = _bounded_text(failure_type, label="failure_type")
    if failure_type:
        clauses.append(f"LOWER(COALESCE({prefix}failure_class,''))=LOWER(?)")
        params.append(failure_type)

    score_min, score_max = _bounded_numeric_range(
        score_min, score_max, label="score", minimum=0, maximum=100
    )
    if score_min is not None:
        clauses.append(f"{prefix}score IS NOT NULL AND {prefix}score>=?")
        params.append(score_min)
    if score_max is not None:
        clauses.append(f"{prefix}score IS NOT NULL AND {prefix}score<=?")
        params.append(score_max)

    latency_min_ms, latency_max_ms = _bounded_numeric_range(
        latency_min_ms,
        latency_max_ms,
        label="latency",
        minimum=0,
        maximum=86_400_000,
    )
    if latency_min_ms is not None:
        clauses.append(f"{prefix}latency_ms>=?")
        params.append(latency_min_ms)
    if latency_max_ms is not None:
        clauses.append(f"{prefix}latency_ms<=?")
        params.append(latency_max_ms)

    release = _bounded_text(release, label="release")
    if release:
        clauses.append(
            "(COALESCE(json_extract("
            + prefix
            + "release_identity_json,'$.release_id'),'')=? OR "
            "COALESCE(json_extract("
            + prefix
            + "release_identity_json,'$.build_sha'),'')=?)"
        )
        params.extend([release, release])

    index_revision = _bounded_text(index_revision, label="index_revision")
    if index_revision:
        clauses.append(
            "(COALESCE(json_extract("
            + prefix
            + "index_identity_json,'$.manifest_sha256'),'')=? OR "
            "COALESCE(json_extract("
            + prefix
            + "index_identity_json,'$.pointer_digest'),'')=? OR "
            "COALESCE(json_extract("
            + prefix
            + "index_identity_json,'$.resolved_gate_sha256'),'')=?)"
        )
        params.extend([index_revision, index_revision, index_revision])

    provider = _bounded_text(provider, label="provider")
    if provider:
        clauses.append(
            f"LOWER(COALESCE(json_extract({prefix}evaluator_json,'$.evaluator_provider'),''))=LOWER(?)"
        )
        params.append(provider)
    model = _bounded_text(model, label="model")
    if model:
        clauses.append(
            f"LOWER(COALESCE(json_extract({prefix}evaluator_json,'$.evaluator_model'),''))=LOWER(?)"
        )
        params.append(model)
    return clauses, params


def _filter_snapshot(**values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if value is None or value == "":
            continue
        result[key] = value
    return result


def _cluster_export_stats(
    connection: sqlite3.Connection, cluster_id: str
) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT timestamp,release_identity_json FROM qa_events "
        "WHERE cluster_id=? ORDER BY timestamp ASC",
        (cluster_id,),
    ).fetchall()
    releases: list[str] = []
    for row in rows:
        identity = _load(row["release_identity_json"], {})
        candidate = str(identity.get("release_id") or identity.get("build_sha") or "").strip()
        if candidate and (not releases or releases[-1] != candidate):
            releases.append(candidate)
    return {
        "event_count": len(rows),
        "release_range": {
            "first_seen_at": str(rows[0]["timestamp"]) if rows else None,
            "last_seen_at": str(rows[-1]["timestamp"]) if rows else None,
            "first_release": releases[0] if releases else None,
            "last_release": releases[-1] if releases else None,
        },
    }


def _bounded_text(value: str | None, *, label: str) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split())
    if len(normalized) > 256:
        raise ValueError(f"{label} must be at most 256 characters")
    return normalized


def _bounded_numeric_range(
    lower: int | None,
    upper: int | None,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> tuple[int | None, int | None]:
    for value in (lower, upper):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{label} bounds must be integers")
        if value is not None and not minimum <= value <= maximum:
            raise ValueError(f"{label} bounds must be between {minimum} and {maximum}")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(f"{label} minimum must not exceed maximum")
    return lower, upper


__all__ = ["QualifiedQaRepositoryV2"]
