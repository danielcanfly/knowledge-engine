from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request

from .m26_admin_contract import ADMIN_PREFIX, DEFAULT_CONSOLE_ORIGIN, redact, utc_now
from .m26_admin_control_plane import request_id_from

CANONICAL_ADMIN_API_VERSION = "1.1.0-gate-a-repair-a"
CANONICAL_ADMIN_OPENAPI_SHA256 = (
    "2e28c734404d4428450e0b8232d44314365cfb775a44b45803e9bf11be90743f"
)

_QUALIFICATION_STATUSES = frozenset(
    {
        "qualified",
        "read_only",
        "disabled",
        "qualification_candidate",
        "blocked_authority",
        "unavailable",
        "unsupported",
    }
)
_EFFECTIVE_STATES = frozenset(
    {"enabled", "read_only", "disabled", "unavailable", "not_eligible"}
)


def _configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _safe_string(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _mapping_from_capability(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    to_payload = getattr(raw, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def canonicalize_capability(raw: Any) -> dict[str, Any]:
    """Project capability evidence into the Gate-A canonical shape.

    Pre-convergence B01 gates only expose a single ``state`` field. Those gates
    are never allowed to silently become mutation-authorized in Settings. A
    legacy ``enabled`` value is therefore demoted to a qualification candidate
    until B03-style qualification evidence supplies the canonical fields.
    """

    payload = _mapping_from_capability(raw)
    capability_id = _safe_string(
        payload.get("capability_id"), fallback="unknown.capability"
    )
    source = _safe_string(payload.get("source"), fallback="unknown")
    reason_code = _safe_string(
        payload.get("reason_code"), fallback="ADMIN_CAPABILITY_EVIDENCE_REQUIRED"
    )

    qualification = payload.get("qualification_status")
    effective = payload.get("effective_state")

    if qualification in _QUALIFICATION_STATUSES and effective in _EFFECTIVE_STATES:
        if qualification == "blocked_authority":
            effective = "unavailable"
        elif qualification == "qualification_candidate":
            effective = "disabled"
        elif qualification == "read_only":
            effective = "read_only"
        elif qualification == "unavailable":
            effective = "unavailable"

        mutation_authorized = bool(payload.get("mutation_authorized"))
        mutation_authorized = bool(
            mutation_authorized
            and qualification == "qualified"
            and effective == "enabled"
        )
    else:
        legacy_state = payload.get("state")
        if legacy_state == "read_only":
            qualification = "read_only"
            effective = "read_only"
        elif legacy_state == "disabled":
            qualification = "disabled"
            effective = "disabled"
        elif legacy_state == "not_eligible":
            qualification = "unsupported"
            effective = "not_eligible"
        elif legacy_state == "enabled":
            qualification = "qualification_candidate"
            effective = "disabled"
            reason_code = "ADMIN_CAPABILITY_REQUALIFICATION_REQUIRED"
        else:
            qualification = "unavailable"
            effective = "unavailable"
        mutation_authorized = False

    return redact(
        {
            "capability_id": capability_id,
            "qualification_status": qualification,
            "effective_state": effective,
            "mutation_authorized": mutation_authorized,
            "reason_code": reason_code,
            "source": source,
            "observed_at": payload.get("observed_at"),
            "resource_identity": payload.get("resource_identity"),
            "evidence_digest": payload.get("evidence_digest"),
        }
    )


def _settings_data(request: Request) -> dict[str, Any]:
    provider = getattr(request.app.state, "admin_capability_provider", None)
    raw_capabilities = provider.list_capabilities() if provider else []
    capabilities = [canonicalize_capability(item) for item in raw_capabilities]

    owner_allowlist_configured = _configured("M26_CONSOLE_OWNER_EMAILS") or _configured(
        "M26_CONSOLE_OWNER_SUBJECTS"
    )

    return {
        "environment": {
            "service": "knowledge-engine",
            "admin_api_namespace": ADMIN_PREFIX,
            "console_origin": DEFAULT_CONSOLE_ORIGIN,
        },
        "contract": {
            "name": "M26 LLM-Wiki Admin API",
            "version": CANONICAL_ADMIN_API_VERSION,
            "openapi_sha256": CANONICAL_ADMIN_OPENAPI_SHA256,
        },
        "configuration": [
            {
                "key": "cloudflare_access_team_domain",
                "configured": _configured("M26_CONSOLE_ACCESS_TEAM_DOMAIN"),
            },
            {
                "key": "cloudflare_access_audience",
                "configured": _configured("M26_CONSOLE_ACCESS_AUD"),
            },
            {
                "key": "owner_allowlist",
                "configured": owner_allowlist_configured,
            },
        ],
        "capabilities": capabilities,
        "capability_policy": {
            "default_when_missing": {
                "qualification_status": "unavailable",
                "effective_state": "unavailable",
                "mutation_authorized": False,
                "reason_code": "ADMIN_CAPABILITY_EVIDENCE_REQUIRED",
            }
        },
        "preferences": {
            "supported": False,
            "mutation_authorized": False,
            "reason_code": "SETTINGS_PHASE1_READ_ONLY",
        },
    }


def _router() -> APIRouter:
    router = APIRouter(prefix=ADMIN_PREFIX, tags=["Settings"])

    @router.get("/settings", operation_id="getAdminSettings")
    async def settings(request: Request) -> dict[str, Any]:
        observed_at = utc_now()
        return {
            "request_id": request_id_from(request),
            "availability": {
                "status": "available",
                "reason_code": None,
                "detail": None,
            },
            "provenance": {
                "source": "admin_settings_adapter",
                "resource_identity": {
                    "contract_version": CANONICAL_ADMIN_API_VERSION,
                    "contract_sha256": CANONICAL_ADMIN_OPENAPI_SHA256,
                },
                "evidence_digest": CANONICAL_ADMIN_OPENAPI_SHA256,
                "source_observed_at": observed_at,
            },
            "observed_at": observed_at,
            "freshness": "live",
            "data": _settings_data(request),
        }

    return router


def install_admin_settings(app: FastAPI) -> FastAPI:
    if getattr(app.state, "admin_settings_installed", False):
        return app
    app.include_router(_router())
    app.state.admin_settings_installed = True
    return app


__all__ = [
    "CANONICAL_ADMIN_API_VERSION",
    "CANONICAL_ADMIN_OPENAPI_SHA256",
    "canonicalize_capability",
    "install_admin_settings",
]
