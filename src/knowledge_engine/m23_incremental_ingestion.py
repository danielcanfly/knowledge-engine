from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .errors import IntegrityError

MESSAGE_SCHEMA = "knowledge-engine-m23-incremental-ingestion-message/v1"
RECEIPT_SCHEMA = "knowledge-engine-m23-incremental-ingestion-receipt/v1"
COLLECTION = "llm_wiki_m23_pilot_bge_m3_1024"
SOURCE_MEMBERSHIP = "evaluation-only-pending-proposal"
MAX_BATCH_MESSAGES = 4
MAX_SECTIONS_PER_MESSAGE = 25
MAX_SECTIONS_PER_RUN = 500
MAX_SECTIONS_PER_DAY = 2000
MAX_USD_PER_RUN = 0.5
MAX_USD_PER_DAY = 2.0

AUTHORITY_FALSE = {
    "deployment_dispatched": False,
    "queue_creation_dispatched": False,
    "cloudflare_inference_dispatched": False,
    "qdrant_write_dispatched": False,
    "source_mutation_dispatched": False,
    "r2_mutation_dispatched": False,
    "pointer_mutation_dispatched": False,
    "production_mutation_dispatched": False,
    "permanent_ledger_mutation_dispatched": False,
    "delete_dispatched": False,
}


@dataclass(frozen=True)
class ExistingPoint:
    point_id: str
    section_id: str
    text_sha256: str


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _required_string(value: Any, field: str, max_length: int = 50000) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise IntegrityError(f"M23-INCREMENTAL invalid {field}")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _required_string(value, field, 64)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise IntegrityError(f"M23-INCREMENTAL invalid {field}")
    return text


def _timestamp(value: Any, field: str) -> str:
    text = _required_string(value, field, 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError(f"M23-INCREMENTAL invalid {field}") from exc
    if parsed.tzinfo is None:
        raise IntegrityError(f"M23-INCREMENTAL {field} must be timezone-aware")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def deterministic_message_id(message_without_id: Mapping[str, Any]) -> str:
    return f"m23inc-{canonical_sha256(message_without_id)[:24]}"


def validate_message(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != MESSAGE_SCHEMA:
        raise IntegrityError("M23-INCREMENTAL unsupported message schema")
    if raw.get("collection") != COLLECTION:
        raise IntegrityError("M23-INCREMENTAL wrong collection")

    message_id = _required_string(raw.get("message_id"), "message_id", 31)
    if not message_id.startswith("m23inc-") or len(message_id) != 31:
        raise IntegrityError("M23-INCREMENTAL invalid message_id")
    _sha256(message_id.removeprefix("m23inc-").ljust(64, "0"), "message_id digest")

    release_id = _required_string(raw.get("release_id"), "release_id", 128)
    source_commit_sha = _required_string(raw.get("source_commit_sha"), "source_commit_sha", 40)
    if len(source_commit_sha) != 40 or any(
        ch not in "0123456789abcdef" for ch in source_commit_sha
    ):
        raise IntegrityError("M23-INCREMENTAL invalid source_commit_sha")
    emitted_at = _timestamp(raw.get("emitted_at"), "emitted_at")

    estimated_usd = raw.get("estimated_usd")
    if (
        not isinstance(estimated_usd, int | float)
        or isinstance(estimated_usd, bool)
        or estimated_usd < 0
        or estimated_usd > MAX_USD_PER_RUN
    ):
        raise IntegrityError("M23-INCREMENTAL message budget exceeds run cap")

    authority = raw.get("authority")
    expected_authority = {
        "canonical_knowledge": False,
        "candidate_release_eligible": False,
        "production_authority": False,
        "delete_authorized": False,
    }
    if authority != expected_authority:
        raise IntegrityError("M23-INCREMENTAL authority flags must all be false")

    sections = raw.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS_PER_MESSAGE:
        raise IntegrityError("M23-INCREMENTAL invalid section count")

    normalized_sections: list[dict[str, Any]] = []
    seen_section_ids: set[str] = set()
    seen_point_ids: set[str] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, Mapping):
            raise IntegrityError(f"M23-INCREMENTAL section {index} must be an object")
        section_id = _required_string(section.get("section_id"), "section_id", 500)
        point_id = _required_string(section.get("point_id"), "point_id", 64)
        try:
            UUID(point_id)
        except ValueError as exc:
            raise IntegrityError("M23-INCREMENTAL invalid point_id") from exc
        if section_id in seen_section_ids or point_id in seen_point_ids:
            raise IntegrityError("M23-INCREMENTAL duplicate section or point identity")
        seen_section_ids.add(section_id)
        seen_point_ids.add(point_id)

        previous = section.get("expected_previous_text_sha256")
        if previous is not None:
            previous = _sha256(previous, "expected_previous_text_sha256")
        text = _required_string(section.get("text"), "text", 50000)
        text_sha = _sha256(section.get("text_sha256"), "text_sha256")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha:
            raise IntegrityError("M23-INCREMENTAL text digest mismatch")

        payload = section.get("payload")
        if not isinstance(payload, Mapping):
            raise IntegrityError("M23-INCREMENTAL payload must be an object")
        if payload.get("section_id") != section_id or payload.get("text_sha256") != text_sha:
            raise IntegrityError("M23-INCREMENTAL payload identity mismatch")
        if payload.get("source_membership") != SOURCE_MEMBERSHIP:
            raise IntegrityError("M23-INCREMENTAL source membership mismatch")
        for flag in (
            "canonical_knowledge",
            "candidate_release_eligible",
            "production_authority",
        ):
            if payload.get(flag) is not False:
                raise IntegrityError(f"M23-INCREMENTAL payload {flag} must be false")
        _sha256(payload.get("source_sha256"), "payload.source_sha256")

        normalized_sections.append(
            {
                "section_id": section_id,
                "point_id": point_id,
                "expected_previous_text_sha256": previous,
                "text": text,
                "text_sha256": text_sha,
                "payload": dict(payload),
            }
        )

    normalized = {
        "schema_version": MESSAGE_SCHEMA,
        "message_id": message_id,
        "collection": COLLECTION,
        "release_id": release_id,
        "source_commit_sha": source_commit_sha,
        "emitted_at": emitted_at,
        "estimated_usd": float(estimated_usd),
        "sections": normalized_sections,
        "authority": expected_authority,
    }
    without_id = dict(normalized)
    without_id.pop("message_id")
    expected_id = deterministic_message_id(without_id)
    if message_id != expected_id:
        raise IntegrityError("M23-INCREMENTAL deterministic message_id mismatch")
    return normalized


def build_message(
    *,
    release_id: str,
    source_commit_sha: str,
    emitted_at: str,
    estimated_usd: float,
    sections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": MESSAGE_SCHEMA,
        "collection": COLLECTION,
        "release_id": release_id,
        "source_commit_sha": source_commit_sha,
        "emitted_at": emitted_at,
        "estimated_usd": estimated_usd,
        "sections": [dict(section) for section in sections],
        "authority": {
            "canonical_knowledge": False,
            "candidate_release_eligible": False,
            "production_authority": False,
            "delete_authorized": False,
        },
    }
    body["message_id"] = deterministic_message_id(body)
    return validate_message(body)


def plan_batch(
    messages: Sequence[Mapping[str, Any]],
    existing_points: Mapping[str, ExistingPoint],
    *,
    daily_sections_before: int = 0,
    daily_estimated_usd_before: float = 0.0,
) -> dict[str, Any]:
    if not 1 <= len(messages) <= MAX_BATCH_MESSAGES:
        raise IntegrityError("M23-INCREMENTAL batch message cap exceeded")
    normalized = [validate_message(message) for message in messages]
    message_ids = [message["message_id"] for message in normalized]
    if len(message_ids) != len(set(message_ids)):
        raise IntegrityError("M23-INCREMENTAL duplicate message_id in batch")

    section_count = sum(len(message["sections"]) for message in normalized)
    estimated_usd = sum(message["estimated_usd"] for message in normalized)
    if section_count > MAX_SECTIONS_PER_RUN:
        raise IntegrityError("M23-INCREMENTAL run section cap exceeded")
    if daily_sections_before + section_count > MAX_SECTIONS_PER_DAY:
        raise IntegrityError("M23-INCREMENTAL daily section cap exceeded")
    if estimated_usd > MAX_USD_PER_RUN + 1e-12:
        raise IntegrityError("M23-INCREMENTAL run budget exceeded")
    if daily_estimated_usd_before + estimated_usd > MAX_USD_PER_DAY + 1e-12:
        raise IntegrityError("M23-INCREMENTAL daily budget exceeded")

    outcomes: list[dict[str, str]] = []
    for message in normalized:
        for section in message["sections"]:
            existing = existing_points.get(section["point_id"])
            if existing is None:
                action = "insert"
                reason = "point-missing"
            elif existing.section_id != section["section_id"]:
                action = "reject-stale"
                reason = "point-id-section-id-conflict"
            elif existing.text_sha256 == section["text_sha256"]:
                action = "skip-duplicate"
                reason = "text-sha-already-current"
            elif (
                section["expected_previous_text_sha256"] is not None
                and existing.text_sha256 == section["expected_previous_text_sha256"]
            ):
                action = "replace"
                reason = "optimistic-precondition-matched"
            else:
                action = "reject-stale"
                reason = "optimistic-precondition-mismatch"
            outcomes.append(
                {
                    "message_id": message["message_id"],
                    "section_id": section["section_id"],
                    "point_id": section["point_id"],
                    "action": action,
                    "reason": reason,
                }
            )

    status = "pass"
    if any(outcome["action"] == "reject-stale" for outcome in outcomes):
        status = "rejected"
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "milestone": "M23.6.4",
        "status": status,
        "collection": COLLECTION,
        "message_count": len(normalized),
        "section_count": section_count,
        "outcomes": outcomes,
        "estimated_usd": round(estimated_usd, 12),
        "authority": dict(AUTHORITY_FALSE),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt
