from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LedgerError(ValueError):
    """Raised when evidence is incomplete or unsafe to record."""


def _load_json(evidence_dir: Path, name: str) -> dict[str, Any]:
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


def _required_str(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LedgerError(f"{label} is missing required string field {key!r}")
    return value


def _expect_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise LedgerError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _expect_false(value: Any, label: str) -> None:
    if value is not False:
        raise LedgerError(f"{label} must be false, got {value!r}")


def _bool_text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _collect_citation_urls(public_query: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    results = public_query.get("results", [])
    if not isinstance(results, list):
        raise LedgerError("public query results must be a list")
    for result in results:
        if not isinstance(result, dict):
            continue
        citations = result.get("citations", [])
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            uri = citation.get("uri")
            if isinstance(uri, str):
                urls.append(uri)
    return urls


def build_production_ledger_comment(
    *,
    evidence_dir: Path,
    run_id: str,
    run_url: str,
    workflow_name: str,
    event_name: str,
    head_sha: str,
) -> str:
    request = _load_json(evidence_dir, "request.json")
    normalized = _load_json(evidence_dir, "request.normalized.json")
    validation = _load_json(evidence_dir, "request-validation.json")
    precondition = _load_json(evidence_dir, "precondition.json")
    candidate = _load_json(evidence_dir, "candidate_identity.json")
    promotion = _load_json(evidence_dir, "promotion_result.json")
    post_refresh = _load_json(evidence_dir, "post_refresh.json")
    public_query = _load_json(evidence_dir, "post-promote-public-query.json")
    acceptance = _load_json(evidence_dir, "post_query_acceptance.json")
    idempotency = _load_json(evidence_dir, "idempotency_observation.json")

    _expect_equal(validation.get("status"), "valid", "request validation status")

    release_id = _required_str(normalized, "release_id", "request")
    manifest_sha = _required_str(normalized, "manifest_sha256", "request")
    source_sha = _required_str(normalized, "source_sha", "request")
    builder_sha = _required_str(normalized, "builder_sha", "request")
    foundation_sha = _required_str(normalized, "foundation_sha", "request")
    control_plane_sha = _required_str(
        normalized,
        "control_plane_sha",
        "request",
    )
    operation_id = _required_str(normalized, "operation_id", "request")
    candidate_channel = _required_str(
        normalized,
        "candidate_channel",
        "request",
    )
    expected_citation_url = _required_str(
        normalized,
        "expected_citation_url",
        "request",
    )
    expected_public_status = _required_str(
        normalized,
        "expected_public_status",
        "request",
    )

    _expect_equal(request.get("release_id"), release_id, "raw request release_id")
    _expect_equal(precondition.get("release_id"), release_id, "precondition release")
    _expect_equal(
        precondition.get("manifest_sha256"),
        manifest_sha,
        "precondition manifest",
    )
    _expect_equal(post_refresh.get("release_id"), release_id, "post refresh release")
    _expect_equal(
        post_refresh.get("manifest_sha256"),
        manifest_sha,
        "post refresh manifest",
    )

    _expect_equal(candidate.get("status"), "candidate_verified", "candidate status")
    _expect_equal(
        candidate.get("candidate_channel"),
        candidate_channel,
        "candidate channel",
    )
    _expect_equal(candidate.get("release_id"), release_id, "candidate release")
    _expect_equal(
        candidate.get("manifest_sha256"),
        manifest_sha,
        "candidate manifest",
    )
    _expect_equal(candidate.get("source_sha"), source_sha, "candidate source SHA")
    _expect_equal(candidate.get("builder_sha"), builder_sha, "candidate builder SHA")
    _expect_equal(
        candidate.get("foundation_sha"),
        foundation_sha,
        "candidate foundation SHA",
    )
    _expect_equal(
        candidate.get("control_plane_sha"),
        control_plane_sha,
        "candidate control-plane SHA",
    )

    promotion_status = _required_str(promotion, "status", "promotion")
    if promotion_status not in {"promoted", "already_promoted"}:
        raise LedgerError(f"unexpected promotion status: {promotion_status!r}")
    _expect_equal(promotion.get("release_id"), release_id, "promotion release")
    _expect_equal(
        promotion.get("manifest_sha256"),
        manifest_sha,
        "promotion manifest",
    )
    _expect_equal(promotion.get("source_sha"), source_sha, "promotion source SHA")
    _expect_equal(promotion.get("builder_sha"), builder_sha, "promotion builder SHA")
    _expect_equal(
        promotion.get("foundation_sha"),
        foundation_sha,
        "promotion foundation SHA",
    )
    _expect_equal(
        promotion.get("control_plane_sha"),
        control_plane_sha,
        "promotion control-plane SHA",
    )
    production_pointer_sha = _required_str(
        promotion,
        "production_pointer_sha256",
        "promotion",
    )

    _expect_equal(public_query.get("status"), expected_public_status, "public status")
    _expect_false(
        public_query.get("retrieval", {}).get("raw_fallback_used"),
        "public raw_fallback_used",
    )
    citation_urls = _collect_citation_urls(public_query)
    if expected_citation_url not in citation_urls:
        raise LedgerError("expected citation URL was not returned")

    public_acceptance = acceptance.get("public_query")
    if not isinstance(public_acceptance, dict):
        raise LedgerError("post_query_acceptance missing public_query object")
    _expect_equal(
        public_acceptance.get("status"),
        expected_public_status,
        "public acceptance status",
    )
    _expect_false(
        public_acceptance.get("raw_fallback_used"),
        "public acceptance raw_fallback_used",
    )

    acl_status = "not configured"
    acl_raw_fallback = "not configured"
    acl_filtered_count = "not configured"
    expected_acl_status = normalized.get("expected_acl_status")
    if isinstance(expected_acl_status, str) and expected_acl_status:
        acl_query = _load_json(evidence_dir, "post-promote-acl-query.json")
        _expect_equal(acl_query.get("status"), expected_acl_status, "ACL status")
        _expect_false(
            acl_query.get("retrieval", {}).get("raw_fallback_used"),
            "ACL raw_fallback_used",
        )
        acl_acceptance = acceptance.get("acl_query")
        if not isinstance(acl_acceptance, dict):
            raise LedgerError("post_query_acceptance missing acl_query object")
        _expect_equal(
            acl_acceptance.get("status"),
            expected_acl_status,
            "ACL acceptance status",
        )
        _expect_false(
            acl_acceptance.get("raw_fallback_used"),
            "ACL acceptance raw_fallback_used",
        )
        acl_status = str(acl_acceptance.get("status"))
        acl_raw_fallback = _bool_text(acl_acceptance.get("raw_fallback_used"))
        acl_filtered_count = str(acl_acceptance.get("acl_filtered_count"))

    state = _required_str(idempotency, "state", "idempotency")
    if state not in {"ready_to_promote", "already_target"}:
        raise LedgerError(f"unexpected idempotency state: {state!r}")

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
        f"- Idempotent: `{_bool_text(promotion.get('idempotent'))}`",
        f"- Intent key: `{promotion.get('intent_key')}`",
        f"- Receipt key: `{promotion.get('receipt_key')}`",
        f"- Production pointer SHA-256: `{production_pointer_sha}`",
        "",
        "### Runtime acceptance",
        "",
        f"- Public query: `{normalized['post_promote_public_query']}`",
        f"- Public expected status: `{expected_public_status}`",
        f"- Public actual status: `{public_query.get('status')}`",
        f"- Public raw fallback used: "
        f"`{_bool_text(public_acceptance.get('raw_fallback_used'))}`",
        f"- Expected citation URL returned: `{expected_citation_url}`",
        f"- Citation count: `{public_acceptance.get('citation_count')}`",
        f"- ACL query: `{normalized.get('post_promote_acl_query', '')}`",
        f"- ACL expected status: `{expected_acl_status}`",
        f"- ACL actual status: `{acl_status}`",
        f"- ACL raw fallback used: `{acl_raw_fallback}`",
        f"- ACL filtered count: `{acl_filtered_count}`",
        "",
        "This ledger entry is automated evidence only. It is not a human "
        "approval decision and does not authorize a Source package or "
        "production release.",
        "",
    ]
    return "\n".join(lines)
