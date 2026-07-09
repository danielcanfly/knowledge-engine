from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .errors import IntegrityError, ReleaseConflictError
from .m14_feedback_contracts import PublicFeedbackReceipt, PublicFeedbackRequest
from .m14_feedback_edge import register_feedback_edge_path
from .m14_source_cards import safe_public_uri
from .storage import ObjectStore, sha256_bytes

register_feedback_edge_path()

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
SECRET_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*\S+"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sanitize_feedback_text(value: str | None) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    normalized = unicodedata.normalize("NFKC", value)
    redactions: list[str] = []
    normalized, count = EMAIL_RE.subn("[redacted-email]", normalized)
    if count:
        redactions.append("email")
    normalized, count = BEARER_RE.subn("[redacted-token]", normalized)
    if count:
        redactions.append("bearer_token")
    normalized, count = SECRET_RE.subn("[redacted-secret]", normalized)
    if count:
        redactions.append("secret")
    normalized, count = CONTROL_RE.subn(" ", normalized)
    if count:
        redactions.append("control_character")
    compact = " ".join(normalized.split())[:2000]
    return compact or None, sorted(set(redactions))


def _submitter_scope(client_key: str) -> str:
    return hashlib.sha256(
        f"knowledge-engine-feedback/v1:{client_key}".encode()
    ).hexdigest()


def _identity_payload(
    request: PublicFeedbackRequest,
    *,
    submitter_scope_sha256: str,
    message: str | None,
    reference_uri: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": "knowledge-engine-feedback-identity/v1",
        "submitter_scope_sha256": submitter_scope_sha256,
        "feedback_type": request.feedback_type,
        "request_id": request.request_id,
        "release_id": request.release_id,
        "audience": request.audience,
        "message": message,
        "citation_id": request.citation_id,
        "source_card_id": request.source_card_id,
        "concept_id": request.concept_id,
        "section_id": request.section_id,
        "reference_uri": reference_uri,
        "locale": request.locale,
    }


def feedback_object_keys(feedback_id: str) -> tuple[str, str]:
    return (
        f"feedback/intake/v1/{feedback_id}.json",
        f"feedback/curation-queue/v1/{feedback_id}.json",
    )


class FeedbackIntake:
    def __init__(
        self,
        store: ObjectStore,
        *,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.store = store
        self.now = now

    def submit(
        self,
        request: PublicFeedbackRequest,
        *,
        client_key: str,
        authenticated: bool,
    ) -> PublicFeedbackReceipt:
        message, redactions = sanitize_feedback_text(request.message)
        reference_uri = None
        if request.reference_uri is not None:
            reference_uri = safe_public_uri(request.reference_uri)
            if reference_uri is None:
                raise ValueError("reference_uri is not a safe public HTTP(S) URI")
        submitter_scope_sha256 = _submitter_scope(client_key)
        identity = _identity_payload(
            request,
            submitter_scope_sha256=submitter_scope_sha256,
            message=message,
            reference_uri=reference_uri,
        )
        identity_sha256 = sha256_bytes(_canonical_bytes(identity))
        feedback_id = f"fb_{identity_sha256[:32]}"
        intake_key, queue_key = feedback_object_keys(feedback_id)
        received_at = self.now()
        record = {
            "schema_version": "knowledge-engine-feedback-intake/v1",
            "feedback_id": feedback_id,
            "identity_sha256": identity_sha256,
            "received_at": received_at,
            "submitter_scope_sha256": submitter_scope_sha256,
            "submitter_class": "authenticated" if authenticated else "anonymous",
            "feedback_type": request.feedback_type,
            "request_id": request.request_id,
            "release_id": request.release_id,
            "audience": request.audience,
            "message": message,
            "citation_id": request.citation_id,
            "source_card_id": request.source_card_id,
            "concept_id": request.concept_id,
            "section_id": request.section_id,
            "reference_uri": reference_uri,
            "locale": request.locale,
            "privacy_redactions": redactions,
            "governance": {
                "review_state": "pending_review",
                "source_write_allowed": False,
                "candidate_dispatch_allowed": False,
                "production_write_allowed": False,
                "ledger_append_allowed": False,
            },
        }
        record_bytes = _canonical_bytes(record)
        duplicate = False
        try:
            self.store.put(
                intake_key,
                record_bytes,
                content_type="application/json",
                sha256=sha256_bytes(record_bytes),
                only_if_absent=True,
            )
        except ReleaseConflictError as exc:
            duplicate = True
            stored = self._load_json(intake_key, "feedback intake")
            if stored.get("identity_sha256") != identity_sha256:
                raise IntegrityError("feedback identity collision") from exc
            stored_received_at = stored.get("received_at")
            if not isinstance(stored_received_at, str) or not stored_received_at:
                raise IntegrityError("feedback intake is missing received_at") from exc
            received_at = stored_received_at
            record_bytes = _canonical_bytes(stored)

        intake_sha256 = sha256_bytes(record_bytes)
        queue = {
            "schema_version": "knowledge-engine-feedback-curation-queue/v1",
            "feedback_id": feedback_id,
            "intake_sha256": intake_sha256,
            "created_at": received_at,
            "state": "pending_review",
            "proposed_action": "review_feedback",
            "source_write_allowed": False,
            "candidate_dispatch_allowed": False,
            "production_write_allowed": False,
            "ledger_append_allowed": False,
        }
        queue_bytes = _canonical_bytes(queue)
        try:
            self.store.put(
                queue_key,
                queue_bytes,
                content_type="application/json",
                sha256=sha256_bytes(queue_bytes),
                only_if_absent=True,
            )
        except ReleaseConflictError as exc:
            stored_queue = self._load_json(queue_key, "feedback queue envelope")
            if (
                stored_queue.get("feedback_id") != feedback_id
                or stored_queue.get("intake_sha256") != intake_sha256
            ):
                raise IntegrityError("feedback queue identity collision") from exc

        return PublicFeedbackReceipt(
            feedback_id=feedback_id,
            status="duplicate" if duplicate else "accepted",
            feedback_type=request.feedback_type,
            request_id=request.request_id,
            release_id=request.release_id,
            audience=request.audience,
            received_at=received_at,
            privacy_redactions_applied=bool(redactions),
        )

    def _load_json(self, key: str, label: str) -> dict[str, Any]:
        try:
            value = json.loads(self.store.get(key))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise IntegrityError(f"{label} is unavailable or invalid") from exc
        if not isinstance(value, dict):
            raise IntegrityError(f"{label} must be a JSON object")
        return value
