from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import ADMIN_PREFIX, AuditEvent, redact
from .m26_admin_control_plane import request_id_from

AUDIT_READ_CAPABILITY = "audit.read"
_ALLOWED_FRESHNESS = frozenset(
    {"live", "near_live", "delayed", "snapshot", "stale", "unknown"}
)
_REQUIRED_EVENT_FIELDS = (
    "event_id",
    "observed_at",
    "actor_id",
    "actor_type",
    "action",
    "object_type",
    "request_id",
    "outcome",
    "reason_code",
)


@dataclass(frozen=True)
class AuditHistorySnapshot:
    events: Sequence[AuditEvent | Mapping[str, Any]]
    source: str
    observed_at: str | None
    freshness: str = "unknown"
    resource_identity: Mapping[str, Any] | None = None
    evidence_digest: str | None = None
    complete: bool = True


class AuditHistoryReader(Protocol):
    def read(self, request: Request) -> AuditHistorySnapshot | None: ...


class UnavailableAuditHistoryReader:
    def read(self, request: Request) -> AuditHistorySnapshot | None:
        del request
        return None


@dataclass
class StaticAuditHistoryReader:
    snapshot: AuditHistorySnapshot | None

    def read(self, request: Request) -> AuditHistorySnapshot | None:
        del request
        return self.snapshot


def _availability(
    status: str, reason_code: str | None, detail: str
) -> dict[str, Any]:
    return {"status": status, "reason_code": reason_code, "detail": detail}


def _provenance(
    source: str,
    *,
    observed_at: str | None,
    resource_identity: Mapping[str, Any] | None = None,
    evidence_digest: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "resource_identity": redact(resource_identity),
        "evidence_digest": evidence_digest,
        "source_observed_at": observed_at,
    }


def _clean_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _iso_datetime(value: Any) -> str | None:
    candidate = _clean_string(value)
    if candidate is None:
        return None
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return candidate


def _freshness(value: Any) -> str:
    return value if isinstance(value, str) and value in _ALLOWED_FRESHNESS else "unknown"


def _normalize_event(raw: object) -> dict[str, Any] | None:
    if isinstance(raw, AuditEvent):
        value: Mapping[str, Any] = raw.to_payload()
    elif isinstance(raw, Mapping):
        value = raw
    else:
        return None

    normalized: dict[str, Any] = {}
    for key in _REQUIRED_EVENT_FIELDS:
        item = _clean_string(value.get(key))
        if item is None:
            return None
        normalized[key] = item

    if _iso_datetime(normalized["observed_at"]) is None:
        return None

    normalized["object_id"] = _clean_string(value.get("object_id"))
    normalized["operation_id"] = _clean_string(value.get("operation_id"))
    metadata = value.get("metadata")
    normalized["metadata"] = redact(metadata if isinstance(metadata, Mapping) else {})

    before_ref = value.get("before_ref")
    after_ref = value.get("after_ref")
    if before_ref is None and isinstance(metadata, Mapping):
        before_ref = metadata.get("before_ref")
    if after_ref is None and isinstance(metadata, Mapping):
        after_ref = metadata.get("after_ref")
    normalized["before_ref"] = redact(before_ref)
    normalized["after_ref"] = redact(after_ref)
    return normalized


def _unavailable_payload(
    request: Request,
    *,
    reason_code: str,
    detail: str,
    source: str = "audit_history_unavailable",
) -> dict[str, Any]:
    return {
        "request_id": request_id_from(request),
        "availability": _availability("unavailable", reason_code, detail),
        "provenance": _provenance(source, observed_at=None),
        "observed_at": None,
        "freshness": "unknown",
        "data": {
            "events": None,
            "append_only": True,
            "mutable": False,
            "coverage": None,
        },
    }


def _capability_unavailable(request: Request) -> dict[str, Any] | None:
    provider = getattr(request.app.state, "admin_capability_provider", None)
    gate = provider.get_capability(AUDIT_READ_CAPABILITY) if provider else None
    if gate is None:
        return _unavailable_payload(
            request,
            reason_code="ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
            detail="Audit history read capability has not been qualified.",
            source="capability_gate",
        )
    if gate.state not in {"enabled", "read_only"}:
        return _unavailable_payload(
            request,
            reason_code=gate.reason_code or "ADMIN_CAPABILITY_DISABLED",
            detail="Audit history read capability is not currently available.",
            source=gate.source or "capability_gate",
        )
    return None


def build_audit_history_payload(request: Request) -> dict[str, Any]:
    capability_failure = _capability_unavailable(request)
    if capability_failure is not None:
        return capability_failure

    reader: AuditHistoryReader = getattr(
        request.app.state,
        "admin_audit_history_reader",
        UnavailableAuditHistoryReader(),
    )
    try:
        snapshot = reader.read(request)
    except Exception:
        return _unavailable_payload(
            request,
            reason_code="AUDIT_HISTORY_READ_FAILED",
            detail="The qualified durable audit history source could not be read.",
        )

    if snapshot is None:
        return _unavailable_payload(
            request,
            reason_code="AUDIT_HISTORY_UNAVAILABLE",
            detail="No qualified durable audit history reader is configured.",
        )
    if not isinstance(snapshot, AuditHistorySnapshot):
        return _unavailable_payload(
            request,
            reason_code="AUDIT_HISTORY_READER_CONTRACT_INVALID",
            detail="Audit history was withheld because the reader contract was invalid.",
        )

    source = _clean_string(snapshot.source)
    if source is None:
        return _unavailable_payload(
            request,
            reason_code="AUDIT_HISTORY_PROVENANCE_REQUIRED",
            detail="Audit history was withheld because source provenance is missing.",
        )

    observed_at = _iso_datetime(snapshot.observed_at)
    freshness = _freshness(snapshot.freshness)
    events: list[dict[str, Any]] = []
    rejected = 0
    for raw in snapshot.events:
        event = _normalize_event(raw)
        if event is None:
            rejected += 1
        else:
            events.append(event)

    partial = not snapshot.complete or rejected > 0 or observed_at is None
    status = "partial" if partial else "available"
    reason_code = "AUDIT_HISTORY_PARTIAL_EVIDENCE" if partial else None
    detail = (
        "Durable audit history is available, but coverage or event identity evidence is incomplete."
        if partial
        else "Qualified durable append-only audit history snapshot."
    )

    return {
        "request_id": request_id_from(request),
        "availability": _availability(status, reason_code, detail),
        "provenance": _provenance(
            source,
            observed_at=observed_at,
            resource_identity=snapshot.resource_identity,
            evidence_digest=_clean_string(snapshot.evidence_digest),
        ),
        "observed_at": observed_at,
        "freshness": freshness,
        "data": {
            "events": events,
            "append_only": True,
            "mutable": False,
            "coverage": {
                "complete": snapshot.complete and rejected == 0,
                "returned_count": len(events),
                "rejected_count": rejected,
            },
        },
    }


def audit_router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Audit"])

    @router.get("/audit-log", operation_id="listAuditLog")
    async def audit_log(request: Request) -> dict[str, Any]:
        return build_audit_history_payload(request)

    return router


def install_admin_audit(
    app: FastAPI, *, reader: AuditHistoryReader | None = None
) -> FastAPI:
    if getattr(app.state, "admin_audit_history_installed", False):
        return app
    app.state.admin_audit_history_reader = reader or UnavailableAuditHistoryReader()
    app.include_router(audit_router())
    app.state.admin_audit_history_installed = True
    return app


__all__ = [
    "AUDIT_READ_CAPABILITY",
    "AuditHistoryReader",
    "AuditHistorySnapshot",
    "StaticAuditHistoryReader",
    "UnavailableAuditHistoryReader",
    "build_audit_history_payload",
    "install_admin_audit",
]
