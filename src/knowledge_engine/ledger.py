from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LedgerError(ValueError):
    """Raised when evidence is incomplete or unsafe to record."""


def _load(evidence_dir: Path, name: str) -> dict[str, Any]:
    path = evidence_dir / name
    if not path.is_file():
        raise LedgerError(f"missing evidence file: {name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"invalid JSON evidence file: {name}") from exc
    if not isinstance(payload, dict):
        raise LedgerError(f"evidence file must be a JSON object: {name}")
    return payload


def _required(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LedgerError(f"{label} is missing required string field {key!r}")
    return value


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise LedgerError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _false(value: Any, label: str) -> None:
    if value is not False:
        raise LedgerError(f"{label} must be false, got {value!r}")


def _bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _citations(payload: dict[str, Any]) -> list[str]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise LedgerError("public query results must be a list")
    return [
        uri
        for result in results
        if isinstance(result, dict)
        for citation in result.get("citations", [])
        if isinstance(citation, dict)
        for uri in [citation.get("uri")]
        if isinstance(uri, str)
    ]


def build_production_ledger_comment(
    *,
    evidence_dir: Path,
    run_id: str,
    run_url: str,
    workflow_name: str,
    event_name: str,
    head_sha: str,
) -> str:
    request = _load(evidence_dir, "request.json")
    normalized = _load(evidence_dir, "request.normalized.json")
    validation = _load(evidence_dir, "request-validation.json")
    precondition = _load(evidence_dir, "precondition.json")
    candidate = _load(evidence_dir, "candidate_identity.json")
    promotion = _load(evidence_dir, "promotion_result.json")
    post_refresh = _load(evidence_dir, "post_refresh.json")
    public_query = _load(evidence_dir, "post-promote-public-query.json")
    acceptance = _load(evidence_dir, "post_query_acceptance.json")
    idempotency = _load(evidence_dir, "idempotency_observation.json")

    _equal(validation.get("status"), "valid", "request validation status")

    release_id = _required(normalized, "release_id", "request")
    manifest_sha = _required(normalized, "manifest_sha256", "request")
    previous_release_id = _required(
        normalized, "expected_previous_release_id", "request"
    )
    previous_manifest_sha = _required(
        normalized, "expected_previous_manifest_sha256", "request"
    )
    source_sha = _required(normalized, "source_sha", "request")
    builder_sha = _required(normalized, "builder_sha", "request")
    foundation_sha = _required(normalized, "foundation_sha", "request")
    control_plane_sha = _required(normalized, "control_plane_sha", "request")
    operation_id = _required(normalized, "operation_id", "request")
    candidate_channel = _required(normalized, "candidate_channel", "request")
    expected_citation_url = _required(
        normalized, "expected_citation_url", "request"
    )
    expected_public_status = _required(
        normalized, "expected_public_status", "request"
    )

    state = _required(idempotency, "state", "idempotency")
    if state == "ready_to_promote":
        precondition_release = previous_release_id
        precondition_manifest = previous_manifest_sha
    elif state == "already_target":
        precondition_release = release_id
        precondition_manifest = manifest_sha
    else:
        raise LedgerError(f"unexpected idempotency state: {state!r}")

    _equal(request.get("release_id"), release_id, "raw request release_id")
    _equal(
        precondition.get("release_id"),
        precondition_release,
        "precondition release",
    )
    _equal(
        precondition.get("manifest_sha256"),
        precondition_manifest,
        "precondition manifest",
    )
    _equal(post_refresh.get("release_id"), release_id, "post refresh release")
    _equal(
        post_refresh.get("manifest_sha256"), manifest_sha, "post refresh manifest"
    )

    _equal(candidate.get("status"), "candidate_verified", "candidate status")
    for key, expected in {
        "candidate_channel": candidate_channel,
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "source_sha": source_sha,
        "builder_sha": builder_sha,
        "foundation_sha": foundation_sha,
        "control_plane_sha": control_plane_sha,
    }.items():
        _equal(candidate.get(key), expected, f"candidate {key}")

    promotion_status = _required(promotion, "status", "promotion")
    if promotion_status not in {"promoted", "already_promoted"}:
        raise LedgerError(f"unexpected promotion status: {promotion_status!r}")
    for key, expected in {
        "release_id": release_id,
        "manifest_sha256": manifest_sha,
        "source_sha": source_sha,
        "builder_sha": builder_sha,
        "foundation_sha": foundation_sha,
        "control_plane_sha": control_plane_sha,
    }.items():
        _equal(promotion.get(key), expected, f"promotion {key}")
    pointer_sha = _required(
        promotion, "production_pointer_sha256", "promotion"
    )

    _equal(public_query.get("status"), expected_public_status, "public status")
    _false(
        public_query.get("retrieval", {}).get("raw_fallback_used"),
        "public raw_fallback_used",
    )
    if expected_citation_url not in _citations(public_query):
        raise LedgerError("expected citation URL was not returned")

    public_acceptance = acceptance.get("public_query")
    if not isinstance(public_acceptance, dict):
        raise LedgerError("post_query_acceptance missing public_query object")
    _equal(
        public_acceptance.get("status"),
        expected_public_status,
        "public acceptance status",
    )
    _false(
        public_acceptance.get("raw_fallback_used"),
        "public acceptance raw_fallback_used",
    )

    expected_acl_status = normalized.get("expected_acl_status")
    acl_status = acl_raw_fallback = acl_filtered_count = "not configured"
    if isinstance(expected_acl_status, str) and expected_acl_status:
        acl_query = _load(evidence_dir, "post-promote-acl-query.json")
        _equal(acl_query.get("status"), expected_acl_status, "ACL status")
        _false(
            acl_query.get("retrieval", {}).get("raw_fallback_used"),
            "ACL raw_fallback_used",
        )
        acl_acceptance = acceptance.get("acl_query")
        if not isinstance(acl_acceptance, dict):
            raise LedgerError("post_query_acceptance missing acl_query object")
        _equal(
            acl_acceptance.get("status"),
            expected_acl_status,
            "ACL acceptance status",
        )
        _false(
            acl_acceptance.get("raw_fallback_used"),
            "ACL acceptance raw_fallback_used",
        )
        acl_status = str(acl_acceptance.get("status"))
        acl_raw_fallback = _bool(acl_acceptance.get("raw_fallback_used"))
        acl_filtered_count = str(acl_acceptance.get("acl_filtered_count"))

    lines = [
        "## Automated M5 production ledger entry",
        "",
        "Status: **production promotion verified**",
        "",
        "### Workflow identity",
        "",
        f"- Workflow: `{workflow_name}`",
        f"- Workflow event: `{event_name}`",
        f"- Actions run ID: `{run_id}`",
        f"- Actions run: {run_url}",
        f"- Engine / control-plane SHA: `{head_sha}`",
        "",
        "### Request identity",
        "",
        f"- Operation ID: `{operation_id}`",
        f"- Candidate channel: `{candidate_channel}`",
        f"- Release ID: `{release_id}`",
        f"- Manifest SHA-256: `{manifest_sha}`",
        f"- Source repository: `{normalized['source_repository']}`",
        f"- Source SHA: `{source_sha}`",
        f"- Builder SHA: `{builder_sha}`",
        f"- Foundation SHA: `{foundation_sha}`",
        f"- Control-plane SHA: `{control_plane_sha}`",
        "",
        "### Promotion / replay evidence",
        "",
        f"- Production precondition state: `{state}`",
        f"- Candidate verification status: `{candidate['status']}`",
        f"- Promotion status: `{promotion_status}`",
        f"- Idempotent: `{_bool(promotion.get('idempotent'))}`",
        f"- Intent key: `{promotion.get('intent_key')}`",
        f"- Receipt key: `{promotion.get('receipt_key')}`",
        f"- Production pointer SHA-256: `{pointer_sha}`",
        "",
        "### Runtime acceptance",
        "",
        f"- Public query: `{normalized['post_promote_public_query']}`",
        f"- Public expected status: `{expected_public_status}`",
        f"- Public actual status: `{public_query.get('status')}`",
        f"- Public raw fallback used: `{_bool(public_acceptance.get('raw_fallback_used'))}`",
        f"- Expected citation URL returned: `{expected_citation_url}`",
        f"- Citation count: `{public_acceptance.get('citation_count')}`",
        f"- ACL query: `{normalized.get('post_promote_acl_query', '')}`",
        f"- ACL expected status: `{expected_acl_status}`",
        f"- ACL actual status: `{acl_status}`",
        f"- ACL raw fallback used: `{acl_raw_fallback}`",
        f"- ACL filtered count: `{acl_filtered_count}`",
        "",
        "This ledger entry is automated evidence only. It is not a human approval decision and does not authorize a Source package or production release.",
        "",
    ]
    return "\n".join(lines)
