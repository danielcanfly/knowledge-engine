from __future__ import annotations

import json
import re
from typing import Any

from . import m13_registry as registry
from .m13_contracts import (
    BATCH_ID_RE,
    CANDIDATE_CHANNEL_RE,
    OPERATION_ID_RE,
    RELEASE_ID_RE,
    ProductionIdentity,
)
from .m13_coordination_common import (
    AUTHORIZATION_ID_RE,
    CANDIDATE_HEAD_KEY,
    COORDINATOR_SCHEMA,
    LEASE_ID_RE,
    PERMIT_ID_RE,
    PRODUCTION_LEASE_KEY,
    SLOT_ID_RE,
    load_production_lease,
    parse_utc,
)
from .release_quality_gate import GOVERNANCE_NO_WRITE
from .storage import ObjectStore, sha256_bytes

OPERATOR_SCHEMA = "knowledge-engine-m13-operator/v1"
COMPARISON_ID_RE = re.compile(r"^mcompare_[a-f0-9]{32}$")
COMPLETION_ID_RE = re.compile(r"^mcomplete_[a-f0-9]{32}$")
CLOSEOUT_ID_RE = re.compile(r"^mclose_[a-f0-9]{32}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class M13OperatorError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.context = context


def _load_object(
    store: ObjectStore,
    key: str,
    label: str,
) -> tuple[bytes, dict[str, Any]]:
    try:
        data = store.get(key)
    except FileNotFoundError as exc:
        raise M13OperatorError(
            "M13_OPERATOR_OBJECT_MISSING",
            f"{label} is missing",
            key=key,
        ) from exc
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M13OperatorError(
            "M13_OPERATOR_OBJECT_INVALID",
            f"{label} is invalid JSON",
            key=key,
        ) from exc
    if not isinstance(value, dict):
        raise M13OperatorError(
            "M13_OPERATOR_OBJECT_INVALID",
            f"{label} must be an object",
            key=key,
        )
    return data, value


def load_production_identity(
    store: ObjectStore,
) -> tuple[ProductionIdentity, dict[str, Any]]:
    pointer_key = "channels/production.json"
    pointer_bytes, pointer = _load_object(
        store,
        pointer_key,
        "production pointer",
    )
    release_id = pointer.get("release_id")
    manifest_sha256 = pointer.get("manifest_sha256")
    manifest_key = pointer.get("manifest_key")
    if not isinstance(release_id, str) or not RELEASE_ID_RE.fullmatch(release_id):
        raise M13OperatorError(
            "M13_OPERATOR_PRODUCTION_INVALID",
            "production release_id is invalid",
        )
    if not isinstance(manifest_sha256, str) or not SHA256_RE.fullmatch(
        manifest_sha256
    ):
        raise M13OperatorError(
            "M13_OPERATOR_PRODUCTION_INVALID",
            "production manifest hash is invalid",
        )
    if not isinstance(manifest_key, str) or not manifest_key:
        raise M13OperatorError(
            "M13_OPERATOR_PRODUCTION_INVALID",
            "production manifest key is invalid",
        )
    manifest_bytes, manifest = _load_object(
        store,
        manifest_key,
        "production manifest",
    )
    observed_manifest_sha256 = sha256_bytes(manifest_bytes)
    if observed_manifest_sha256 != manifest_sha256:
        raise M13OperatorError(
            "M13_OPERATOR_PRODUCTION_MANIFEST_MISMATCH",
            "production manifest bytes do not match pointer",
            expected=manifest_sha256,
            observed=observed_manifest_sha256,
        )
    if manifest.get("release_id") != release_id:
        raise M13OperatorError(
            "M13_OPERATOR_PRODUCTION_RELEASE_MISMATCH",
            "production manifest release_id does not match pointer",
        )
    identity = ProductionIdentity(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        pointer_sha256=sha256_bytes(pointer_bytes),
    )
    evidence = {
        "pointer_key": pointer_key,
        "pointer_sha256": identity.pointer_sha256,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha256,
        "release_id": release_id,
    }
    return identity, evidence


def _candidate_head(
    store: ObjectStore,
    *,
    default_capacity: int = 2,
) -> dict[str, Any]:
    metadata = store.head(CANDIDATE_HEAD_KEY)
    if metadata is None:
        return {
            "schema_version": f"{COORDINATOR_SCHEMA}/candidate-head",
            "head_version": 0,
            "capacity": default_capacity,
            "updated_at": None,
            "active": {},
        }
    _, head = _load_object(
        store,
        CANDIDATE_HEAD_KEY,
        "candidate concurrency head",
    )
    if head.get("schema_version") != f"{COORDINATOR_SCHEMA}/candidate-head":
        raise M13OperatorError(
            "M13_OPERATOR_CANDIDATE_HEAD_INVALID",
            "candidate head schema is invalid",
        )
    valid_numbers = isinstance(head.get("head_version"), int) and isinstance(
        head.get("capacity"),
        int,
    )
    if not valid_numbers:
        raise M13OperatorError(
            "M13_OPERATOR_CANDIDATE_HEAD_INVALID",
            "candidate head version or capacity is invalid",
        )
    if not isinstance(head.get("active"), dict):
        raise M13OperatorError(
            "M13_OPERATOR_CANDIDATE_HEAD_INVALID",
            "candidate active slots are invalid",
        )
    return head


def _batch_views(
    store: ObjectStore,
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]:
    head, _ = registry._load_head(store)
    values: list[tuple[dict[str, Any], Any]] = []
    for batch_id in sorted(head["batches"]):
        snapshot, record = registry._load_batch_snapshot(
            store,
            head,
            batch_id,
        )
        values.append((snapshot, record))
    return head, values


def _active_slots(head: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(
        head["active"].items(),
        key=lambda item: int(item[0]),
    )
    return [
        {"slot_number": int(number), **summary}
        for number, summary in ordered
        if isinstance(summary, dict)
    ]


def operator_status(
    store: ObjectStore,
    *,
    observed_at: str,
    candidate_capacity: int = 2,
) -> dict[str, Any]:
    parse_utc(observed_at, "observed_at")
    production, production_evidence = load_production_identity(store)
    head, batch_values = _batch_views(store)
    candidate_head = _candidate_head(
        store,
        default_capacity=candidate_capacity,
    )
    lease, _ = load_production_lease(store)
    batches: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for snapshot, record in batch_values:
        counts[record.state] = counts.get(record.state, 0) + 1
        plan = registry.plan_batch_lifecycle(
            snapshot=snapshot,
            observed_production=production,
            actor="m13-operator",
            planned_at=observed_at,
        )
        batches.append(
            {
                "batch_id": record.batch_id,
                "batch_version": snapshot["batch_version"],
                "state": record.state,
                "candidate_channel": record.candidate_channel,
                "source_repository": record.seed.source_repository,
                "source_commit_sha": record.seed.source_commit_sha,
                "expected_previous_production": (
                    record.seed.production.to_identity()
                ),
                "expected_previous_is_current": (
                    record.seed.production == production
                ),
                "operation_count": len(snapshot["operation_summaries"]),
                "event_count": len(snapshot["event_keys"]),
                "next_action": plan.next_action,
                "blockers": list(plan.blockers),
                "terminal": plan.terminal,
                "snapshot_key": head["batches"][record.batch_id][
                    "snapshot_key"
                ],
            }
        )
    active_slots = _active_slots(candidate_head)
    return {
        "schema_version": f"{OPERATOR_SCHEMA}/status",
        "observed_at": observed_at,
        "registry_version": head["registry_version"],
        "registry_updated_at": head["updated_at"],
        "production": production.to_identity(),
        "production_evidence": production_evidence,
        "batch_count": len(batches),
        "state_counts": dict(sorted(counts.items())),
        "batches": batches,
        "candidate_concurrency": {
            "head_version": candidate_head["head_version"],
            "capacity": candidate_head["capacity"],
            "active_count": len(active_slots),
            "active_slots": active_slots,
        },
        "production_lease": lease.to_dict() if lease is not None else None,
        "governance": dict(GOVERNANCE_NO_WRITE),
    }


def stale_report(
    store: ObjectStore,
    *,
    observed_at: str,
    candidate_capacity: int = 2,
) -> dict[str, Any]:
    now = parse_utc(observed_at, "observed_at")
    production, _ = load_production_identity(store)
    _, batch_values = _batch_views(store)
    candidate_head = _candidate_head(
        store,
        default_capacity=candidate_capacity,
    )
    lease, _ = load_production_lease(store)
    findings: list[dict[str, Any]] = []
    for snapshot, record in batch_values:
        terminal = bool(snapshot["record"]["terminal"])
        if not terminal and record.seed.production != production:
            findings.append(
                {
                    "code": "expected_previous_production_stale",
                    "severity": "blocker",
                    "batch_id": record.batch_id,
                    "expected": record.seed.production.to_identity(),
                    "observed": production.to_identity(),
                }
            )
        closeout_complete = any(
            item.get("kind") == "closeout"
            and item.get("state") == "completed"
            for item in snapshot["operation_summaries"]
        )
        if record.state == "promoting":
            if lease is None or lease.batch_id != record.batch_id:
                findings.append(
                    {
                        "code": "promoting_batch_without_current_lease",
                        "severity": "blocker",
                        "batch_id": record.batch_id,
                    }
                )
            elif lease.state == "released" and lease.completion_key is None:
                findings.append(
                    {
                        "code": "released_lease_missing_completion",
                        "severity": "blocker",
                        "batch_id": record.batch_id,
                        "lease_id": lease.lease_id,
                    }
                )
            elif lease.state == "released" and not closeout_complete:
                findings.append(
                    {
                        "code": "promotion_ready_for_closeout",
                        "severity": "action_required",
                        "batch_id": record.batch_id,
                        "lease_id": lease.lease_id,
                        "completion_key": lease.completion_key,
                    }
                )
        if closeout_complete and record.state != "closed":
            findings.append(
                {
                    "code": "closeout_operation_without_closed_batch",
                    "severity": "blocker",
                    "batch_id": record.batch_id,
                    "state": record.state,
                }
            )
    candidate_items = sorted(
        candidate_head["active"].items(),
        key=lambda item: int(item[0]),
    )
    for number, summary in candidate_items:
        valid_summary = isinstance(summary, dict) and isinstance(
            summary.get("expires_at"),
            str,
        )
        if not valid_summary:
            findings.append(
                {
                    "code": "candidate_slot_invalid",
                    "severity": "blocker",
                    "slot_number": int(number),
                }
            )
            continue
        if parse_utc(summary["expires_at"], "expires_at") < now:
            findings.append(
                {
                    "code": "candidate_slot_expired",
                    "severity": "action_required",
                    "slot_number": int(number),
                    "slot_id": summary.get("slot_id"),
                    "batch_id": summary.get("batch_id"),
                    "expires_at": summary["expires_at"],
                }
            )
    if lease is not None:
        live_states = {"active", "permit_issued", "commit_authorized"}
        if lease.state in live_states and parse_utc(
            lease.expires_at,
            "expires_at",
        ) < now:
            findings.append(
                {
                    "code": "production_lease_expired",
                    "severity": "blocker",
                    "lease_id": lease.lease_id,
                    "batch_id": lease.batch_id,
                    "state": lease.state,
                    "expires_at": lease.expires_at,
                }
            )
        matching = [
            record
            for _, record in batch_values
            if record.batch_id == lease.batch_id
        ]
        if not matching:
            findings.append(
                {
                    "code": "production_lease_batch_missing",
                    "severity": "blocker",
                    "lease_id": lease.lease_id,
                    "batch_id": lease.batch_id,
                }
            )
    findings.sort(
        key=lambda item: (
            item["severity"],
            item["code"],
            str(item.get("batch_id", "")),
        )
    )
    return {
        "schema_version": f"{OPERATOR_SCHEMA}/stale-report",
        "observed_at": observed_at,
        "production": production.to_identity(),
        "finding_count": len(findings),
        "blocker_count": sum(
            item["severity"] == "blocker" for item in findings
        ),
        "findings": findings,
        "governance": dict(GOVERNANCE_NO_WRITE),
    }


def _append_issue(
    issues: list[dict[str, Any]],
    code: str,
    **context: Any,
) -> None:
    issues.append({"code": code, **context})


def _audit_operations(
    store: ObjectStore,
    *,
    batch_id: str,
    snapshot: dict[str, Any],
    checked_objects: set[str],
    issues: list[dict[str, Any]],
) -> None:
    for summary in snapshot["operation_summaries"]:
        key = summary.get("operation_key")
        if not isinstance(key, str) or store.head(key) is None:
            _append_issue(
                issues,
                "operation_object_missing",
                batch_id=batch_id,
                operation_id=summary.get("operation_id"),
                key=key,
            )
            continue
        checked_objects.add(key)
        _, value = _load_object(store, key, "operation object")
        if value.get("operation_id") not in {
            None,
            summary.get("operation_id"),
        }:
            _append_issue(
                issues,
                "operation_identity_mismatch",
                batch_id=batch_id,
                operation_id=summary.get("operation_id"),
                key=key,
            )


def _audit_candidate_slots(
    store: ObjectStore,
    *,
    head: dict[str, Any],
    checked_objects: set[str],
    issues: list[dict[str, Any]],
) -> None:
    for number, summary in head["active"].items():
        if not isinstance(summary, dict):
            _append_issue(
                issues,
                "candidate_slot_invalid",
                slot_number=number,
            )
            continue
        key = summary.get("artifact_key")
        if not isinstance(key, str) or store.head(key) is None:
            _append_issue(
                issues,
                "candidate_slot_artifact_missing",
                slot_number=number,
                key=key,
            )
            continue
        checked_objects.add(key)
        _, artifact = _load_object(store, key, "candidate slot artifact")
        if artifact.get("slot_id") != summary.get("slot_id"):
            _append_issue(
                issues,
                "candidate_slot_identity_mismatch",
                slot_number=number,
                key=key,
            )


def integrity_audit(
    store: ObjectStore,
    *,
    observed_at: str,
    candidate_capacity: int = 2,
) -> dict[str, Any]:
    parse_utc(observed_at, "observed_at")
    issues: list[dict[str, Any]] = []
    checked_objects: set[str] = set()
    try:
        production, evidence = load_production_identity(store)
        checked_objects.update(
            {evidence["pointer_key"], evidence["manifest_key"]}
        )
    except (M13OperatorError, ValueError) as exc:
        production = None
        _append_issue(
            issues,
            getattr(exc, "code", "production_invalid"),
            message=str(exc),
        )
    try:
        head, _ = registry._load_head(store)
        checked_objects.add(registry.REGISTRY_HEAD_KEY)
        for batch_id in sorted(head["batches"]):
            try:
                snapshot, _ = registry._load_batch_snapshot(
                    store,
                    head,
                    batch_id,
                )
                snapshot_key = head["batches"][batch_id]["snapshot_key"]
                checked_objects.add(snapshot_key)
                checked_objects.update(snapshot["event_keys"])
                _audit_operations(
                    store,
                    batch_id=batch_id,
                    snapshot=snapshot,
                    checked_objects=checked_objects,
                    issues=issues,
                )
            except Exception as exc:  # fail-closed audit aggregation
                _append_issue(
                    issues,
                    "batch_integrity_failure",
                    batch_id=batch_id,
                    message=str(exc),
                )
    except Exception as exc:  # fail-closed audit aggregation
        _append_issue(
            issues,
            "registry_integrity_failure",
            message=str(exc),
        )
    try:
        candidate_head = _candidate_head(
            store,
            default_capacity=candidate_capacity,
        )
        if store.head(CANDIDATE_HEAD_KEY) is not None:
            checked_objects.add(CANDIDATE_HEAD_KEY)
        _audit_candidate_slots(
            store,
            head=candidate_head,
            checked_objects=checked_objects,
            issues=issues,
        )
    except Exception as exc:  # fail-closed audit aggregation
        _append_issue(
            issues,
            "candidate_head_integrity_failure",
            message=str(exc),
        )
    try:
        lease, _ = load_production_lease(store)
        if lease is not None:
            checked_objects.add(PRODUCTION_LEASE_KEY)
            lease_keys = (
                ("acquisition", lease.acquisition_key),
                ("permit", lease.permit_key),
                ("authorization", lease.authorization_key),
                ("completion", lease.completion_key),
                ("release", lease.release_key),
                ("recovery", lease.recovery_key),
            )
            for label, key in lease_keys:
                if key is None:
                    continue
                if store.head(key) is None:
                    _append_issue(
                        issues,
                        "lease_evidence_missing",
                        label=label,
                        key=key,
                    )
                else:
                    checked_objects.add(key)
            if lease.state == "released" and lease.completion_key is None:
                _append_issue(
                    issues,
                    "released_lease_missing_completion",
                    lease_id=lease.lease_id,
                )
    except Exception as exc:  # fail-closed audit aggregation
        _append_issue(
            issues,
            "production_lease_integrity_failure",
            message=str(exc),
        )
    issues.sort(
        key=lambda item: (
            item["code"],
            str(item.get("batch_id", "")),
            str(item.get("key", "")),
        )
    )
    return {
        "schema_version": f"{OPERATOR_SCHEMA}/audit",
        "observed_at": observed_at,
        "passed": not issues,
        "production": (
            production.to_identity() if production is not None else None
        ),
        "checked_object_count": len(checked_objects),
        "checked_objects": sorted(checked_objects),
        "issue_count": len(issues),
        "issues": issues,
        "governance": dict(GOVERNANCE_NO_WRITE),
    }


def _operation_matches(
    store: ObjectStore,
    identity: str,
) -> list[dict[str, Any]]:
    head, batch_values = _batch_views(store)
    matches: list[dict[str, Any]] = []
    for snapshot, record in batch_values:
        for summary in snapshot["operation_summaries"]:
            if summary.get("operation_id") != identity:
                continue
            key = summary.get("operation_key")
            value = None
            if isinstance(key, str) and store.head(key) is not None:
                _, value = _load_object(store, key, "operation object")
            matches.append(
                {
                    "kind": "operation",
                    "batch_id": record.batch_id,
                    "summary": summary,
                    "operation_key": key,
                    "value": value,
                    "snapshot_key": head["batches"][record.batch_id][
                        "snapshot_key"
                    ],
                }
            )
    return matches


def _direct_lookup(
    store: ObjectStore,
    *,
    identity: str,
    pattern: re.Pattern[str],
    key_template: str,
    label: str,
    kind: str,
) -> list[dict[str, Any]] | None:
    if not pattern.fullmatch(identity):
        return None
    key = key_template.format(identity=identity)
    _, value = _load_object(store, key, label)
    return [{"kind": kind, "key": key, "value": value}]


def _release_matches(
    store: ObjectStore,
    *,
    identity: str,
    batch_values: list[tuple[dict[str, Any], Any]],
    head: dict[str, Any],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    production, evidence = load_production_identity(store)
    if production.release_id == identity:
        matches.append(
            {
                "kind": "production_release",
                "production": production.to_identity(),
                "evidence": evidence,
            }
        )
    for snapshot, record in batch_values:
        if record.seed.production.release_id == identity:
            matches.append(
                {
                    "kind": "batch_expected_previous_release",
                    "batch_id": record.batch_id,
                    "state": record.state,
                    "production": record.seed.production.to_identity(),
                    "snapshot_key": head["batches"][record.batch_id][
                        "snapshot_key"
                    ],
                }
            )
        for summary in snapshot["operation_summaries"]:
            key = summary.get("operation_key")
            if not isinstance(key, str) or store.head(key) is None:
                continue
            _, operation = _load_object(store, key, "operation object")
            evidence_refs = operation.get("evidence_refs")
            if not isinstance(evidence_refs, list):
                continue
            for evidence_key in evidence_refs:
                if (
                    not isinstance(evidence_key, str)
                    or store.head(evidence_key) is None
                ):
                    continue
                _, value = _load_object(
                    store,
                    evidence_key,
                    "operation evidence",
                )
                target = value.get("target_release")
                if isinstance(target, dict) and target.get("release_id") == identity:
                    matches.append(
                        {
                            "kind": "comparison_target_release",
                            "batch_id": record.batch_id,
                            "operation_id": summary.get("operation_id"),
                            "evidence_key": evidence_key,
                            "target_release": target,
                        }
                    )
    return matches


def operator_lookup(
    store: ObjectStore,
    *,
    identity: str,
) -> dict[str, Any]:
    if not identity or len(identity) > 220:
        raise M13OperatorError(
            "M13_OPERATOR_LOOKUP_INVALID",
            "identity is invalid",
        )
    matches: list[dict[str, Any]] = []
    head, batch_values = _batch_views(store)
    if BATCH_ID_RE.fullmatch(identity):
        snapshot, record = registry._load_batch_snapshot(
            store,
            head,
            identity,
        )
        matches.append(
            {
                "kind": "batch",
                "batch_id": identity,
                "record": record.to_identity(),
                "snapshot": snapshot,
                "snapshot_key": head["batches"][identity]["snapshot_key"],
            }
        )
    elif OPERATION_ID_RE.fullmatch(identity):
        matches.extend(_operation_matches(store, identity))
    elif CANDIDATE_CHANNEL_RE.fullmatch(identity):
        for snapshot, record in batch_values:
            if record.candidate_channel != identity:
                continue
            matches.append(
                {
                    "kind": "candidate_channel",
                    "candidate_channel": identity,
                    "batch_id": record.batch_id,
                    "state": record.state,
                    "snapshot_key": head["batches"][record.batch_id][
                        "snapshot_key"
                    ],
                    "operation_summaries": snapshot[
                        "operation_summaries"
                    ],
                }
            )
    elif COMPARISON_ID_RE.fullmatch(identity):
        key = f"m13/v1/release-comparisons/{identity}/result.json"
        _, value = _load_object(store, key, "release comparison")
        matches.append(
            {
                "kind": "release_comparison",
                "comparison_id": identity,
                "key": key,
                "value": value,
            }
        )
    elif LEASE_ID_RE.fullmatch(identity):
        lease, _ = load_production_lease(store)
        if lease is not None and lease.lease_id == identity:
            matches.append(
                {
                    "kind": "production_lease",
                    "value": lease.to_dict(),
                    "key": PRODUCTION_LEASE_KEY,
                }
            )
    else:
        direct_specs = (
            (
                PERMIT_ID_RE,
                "m13/v2/concurrency/production/permits/{identity}.json",
                "production permit",
                "production_permit",
            ),
            (
                AUTHORIZATION_ID_RE,
                "m13/v2/concurrency/production/authorizations/{identity}.json",
                "commit authorization",
                "commit_authorization",
            ),
            (
                COMPLETION_ID_RE,
                "m13/v2/concurrency/production/completions/{identity}.json",
                "production completion",
                "production_completion",
            ),
            (
                SLOT_ID_RE,
                "m13/v2/concurrency/candidate/leases/{identity}.json",
                "candidate slot",
                "candidate_slot",
            ),
            (
                CLOSEOUT_ID_RE,
                "m13/v2/closeouts/{identity}.json",
                "batch closeout",
                "closeout",
            ),
        )
        for pattern, template, label, kind in direct_specs:
            direct = _direct_lookup(
                store,
                identity=identity,
                pattern=pattern,
                key_template=template,
                label=label,
                kind=kind,
            )
            if direct is not None:
                matches.extend(direct)
                break
        else:
            if RELEASE_ID_RE.fullmatch(identity):
                matches.extend(
                    _release_matches(
                        store,
                        identity=identity,
                        batch_values=batch_values,
                        head=head,
                    )
                )
            else:
                raise M13OperatorError(
                    "M13_OPERATOR_LOOKUP_TYPE_UNKNOWN",
                    "identity type is not supported",
                )
    if not matches:
        raise M13OperatorError(
            "M13_OPERATOR_LOOKUP_NOT_FOUND",
            "identity was not found",
            identity=identity,
        )
    matches.sort(
        key=lambda item: (
            item["kind"],
            str(item.get("batch_id", "")),
            str(item.get("key", "")),
        )
    )
    return {
        "schema_version": f"{OPERATOR_SCHEMA}/lookup",
        "identity": identity,
        "match_count": len(matches),
        "matches": matches,
        "governance": dict(GOVERNANCE_NO_WRITE),
    }


def ledger_summary(
    store: ObjectStore,
    *,
    observed_at: str,
) -> dict[str, Any]:
    parse_utc(observed_at, "observed_at")
    production, _ = load_production_identity(store)
    _, batch_values = _batch_views(store)
    operation_counts: dict[str, dict[str, int]] = {}
    batches: list[dict[str, Any]] = []
    missing_ledger: list[str] = []
    for snapshot, record in batch_values:
        promotion = None
        closeout = None
        ledger_references: list[str] = []
        for summary in snapshot["operation_summaries"]:
            kind = str(summary["kind"])
            state = str(summary["state"])
            states = operation_counts.setdefault(kind, {})
            states[state] = states.get(state, 0) + 1
            if kind == "production_promotion":
                promotion = summary
            if kind != "closeout":
                continue
            closeout = summary
            key = summary.get("operation_key")
            if not isinstance(key, str) or store.head(key) is None:
                continue
            _, result = _load_object(store, key, "closeout operation")
            refs = result.get("evidence_refs", [])
            if not isinstance(refs, list):
                continue
            for ref in refs:
                is_ledger_ref = isinstance(ref, str) and (
                    ref.startswith("issue-") or ref.startswith("ledger")
                )
                if is_ledger_ref:
                    ledger_references.append(ref)
        if record.state == "closed" and not ledger_references:
            missing_ledger.append(record.batch_id)
        batches.append(
            {
                "batch_id": record.batch_id,
                "state": record.state,
                "candidate_channel": record.candidate_channel,
                "expected_previous_release_id": (
                    record.seed.production.release_id
                ),
                "production_promotion": promotion,
                "closeout": closeout,
                "ledger_references": sorted(set(ledger_references)),
            }
        )
    normalized_counts = {
        kind: dict(sorted(states.items()))
        for kind, states in sorted(operation_counts.items())
    }
    return {
        "schema_version": f"{OPERATOR_SCHEMA}/ledger-summary",
        "observed_at": observed_at,
        "production": production.to_identity(),
        "batch_count": len(batches),
        "closed_batch_count": sum(
            item["state"] == "closed" for item in batches
        ),
        "operation_counts": normalized_counts,
        "batches": batches,
        "closed_batches_missing_ledger_references": sorted(
            missing_ledger
        ),
        "ledger_append_performed": False,
        "governance": dict(GOVERNANCE_NO_WRITE),
    }
