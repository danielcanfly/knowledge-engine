from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import IntegrityError, ReleaseConflictError
from .storage import ObjectStore, sha256_bytes

AUDIENCES = {"public", "internal", "confidential", "restricted"}
SOURCE_KINDS = {"markdown", "media2md_markdown", "transcript"}
SOURCE_ID_RE = re.compile(r"^source_[a-z0-9][a-z0-9_-]{2,79}$")
SAFE_SCHEMES = {"https", "file", "urn"}
MAX_SOURCE_BYTES = 10 * 1024 * 1024
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "generic_secret_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret[_-]?access[_-]?key|access[_-]?token)\b"
        r"\s*[:=]\s*[A-Za-z0-9_+/=-]{20,}"
    ),
}
PROMPT_INJECTION_PATTERNS = {
    "ignore_previous_instructions": re.compile(
        r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"
    ),
    "system_prompt_request": re.compile(r"(?i)\b(?:reveal|print|show)\s+the\s+system\s+prompt\b"),
    "role_override": re.compile(r"(?i)\byou\s+are\s+now\b"),
}


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_timestamp(value: str) -> None:
    if not value.endswith("Z"):
        raise IntegrityError("retrieved_at must be an exact UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntegrityError("retrieved_at must be a valid ISO-8601 timestamp") from exc


def _stable_kos_id(seed: bytes) -> str:
    value = int.from_bytes(hashlib.sha256(seed).digest()[:17], "big") >> 6
    encoded = []
    for _ in range(26):
        encoded.append(CROCKFORD[value & 31])
        value >>= 5
    return "ko_" + "".join(reversed(encoded))


def _slugify(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or fallback.removeprefix("source_").replace("_", "-"))[:80]


def _normalize_markdown(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntegrityError("Markdown intake must be valid UTF-8") from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntegrityError("Markdown intake cannot be empty")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _scan_secrets(text: str) -> None:
    matched = [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    if matched:
        raise IntegrityError(f"source contains secret-like content: {', '.join(sorted(matched))}")


def _prompt_injection_findings(text: str) -> list[dict[str, str]]:
    findings = []
    for name, pattern in PROMPT_INJECTION_PATTERNS.items():
        if pattern.search(text):
            findings.append(
                {
                    "code": "PROMPT_INJECTION_LIKE_CONTENT",
                    "pattern": name,
                    "severity": "warning",
                    "action": "treat_as_untrusted_data_and_require_security_review",
                }
            )
    return findings


def _put_immutable(
    store: ObjectStore,
    key: str,
    data: bytes,
    *,
    content_type: str,
) -> bool:
    current = store.head(key)
    if current is not None:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}")
        return True
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            sha256=sha256_bytes(data),
            only_if_absent=True,
        )
        return False
    except ReleaseConflictError:
        if store.get(key) != data:
            raise IntegrityError(f"immutable object collision: {key}") from None
        return True


@dataclass(frozen=True)
class IntakeRequest:
    source_id: str
    source_uri: str
    title: str
    kind: str
    audience: str
    retrieved_at: str
    owner: str
    license: str
    content_type: str = "text/markdown"

    def validate(self) -> None:
        if not SOURCE_ID_RE.fullmatch(self.source_id):
            raise IntegrityError("source_id must match source_[a-z0-9][a-z0-9_-]{2,79}")
        if not self.title.strip() or len(self.title) > 200:
            raise IntegrityError("title must contain 1-200 characters")
        parsed = urlsplit(self.source_uri)
        if parsed.scheme not in SAFE_SCHEMES:
            raise IntegrityError("source_uri must use https, file, or urn")
        if parsed.username or parsed.password:
            raise IntegrityError("source_uri cannot contain credentials")
        if self.kind not in SOURCE_KINDS:
            raise IntegrityError(f"unsupported source kind: {self.kind}")
        if self.audience not in AUDIENCES:
            raise IntegrityError(f"unsupported source audience: {self.audience}")
        _validate_timestamp(self.retrieved_at)
        if not self.owner.strip():
            raise IntegrityError("source owner is required")
        if not self.license.strip():
            raise IntegrityError("source license is required")
        if not self.content_type.startswith("text/"):
            raise IntegrityError("M5.1 intake only accepts text content types")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class IntakeResult:
    capture_id: str
    status: str
    idempotent: bool
    raw_blob_reused: bool
    raw_blob_key: str
    capture_metadata_key: str
    normalized_key: str
    review_packet_prefix: str
    raw_sha256: str
    normalized_sha256: str
    review_packet_sha256: str
    machine_finding_count: int
    canonical_write_permitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _draft_markdown(
    request: IntakeRequest,
    *,
    capture_id: str,
    concept_id: str,
    kos_id: str,
    review_id: str,
) -> bytes:
    quoted_title = json.dumps(request.title, ensure_ascii=False)
    quoted_description = json.dumps(
        "Review-required draft generated from an immutable evidence capture.",
        ensure_ascii=False,
    )
    return (
        "---\n"
        "type: Concept\n"
        f"title: {quoted_title}\n"
        f"description: {quoted_description}\n"
        f"timestamp: {request.retrieved_at}\n"
        f"x-kos-id: {kos_id}\n"
        "x-kos-status: draft\n"
        f"x-kos-audience: {request.audience}\n"
        "x-kos-confidence: 0.0\n"
        f"x-kos-provenance: provenance/{concept_id.removeprefix('concepts/')}.json\n"
        "x-kos-review:\n"
        f"  review_id: {review_id}\n"
        "  status: pending\n"
        "---\n"
        f"# {request.title}\n\n"
        "> This file is a review packet draft, not canonical knowledge.\n"
        "> It must not be copied into `knowledge-source/bundle` before approval.\n\n"
        "## Proposed synthesis\n\n"
        "TODO: synthesize supported claims from the normalized evidence.\n\n"
        "## Evidence identity\n\n"
        f"- Capture: `{capture_id}`\n"
        f"- Source: `{request.source_id}`\n"
        f"- URI: {request.source_uri}\n"
    ).encode("utf-8")


def _build_review_packet(
    request: IntakeRequest,
    *,
    capture_id: str,
    raw_blob_key: str,
    capture_metadata_key: str,
    normalized_key: str,
    raw_sha256: str,
    normalized_sha256: str,
    findings: list[dict[str, str]],
) -> dict[str, bytes]:
    slug = _slugify(request.title, request.source_id)
    concept_id = f"concepts/{slug}"
    kos_id = _stable_kos_id(f"{capture_id}:{concept_id}".encode())
    review_id = f"review_{capture_id.removeprefix('capture_')}"
    packet_status = "pending_security_review" if findings else "pending_human_review"

    source_record = {
        "source_id": request.source_id,
        "title": request.title,
        "uri": request.source_uri,
        "kind": request.kind,
        "trust": "unreviewed",
        "status": "pending_review",
        "audience": request.audience,
        "owner": request.owner,
        "license": request.license,
        "capture_id": capture_id,
        "raw_blob_key": raw_blob_key,
        "raw_sha256": raw_sha256,
        "normalized_sha256": normalized_sha256,
        "retrieved_at": request.retrieved_at,
    }
    provenance = {
        "schema_version": "1.0",
        "subject": {"concept_id": concept_id, "x_kos_id": kos_id},
        "sources": [
            {
                "source_id": request.source_id,
                "uri": request.source_uri,
                "retrieved_at": request.retrieved_at,
                "capture_id": capture_id,
                "raw_blob_key": raw_blob_key,
                "raw_sha256": raw_sha256,
                "normalized_key": normalized_key,
                "normalized_sha256": normalized_sha256,
            }
        ],
        "method": "pending_synthesis",
        "confidence": 0.0,
    }
    review = {
        "schema_version": "1.0",
        "review_id": review_id,
        "capture_id": capture_id,
        "concept_id": concept_id,
        "status": packet_status,
        "canonical_write_permitted": False,
        "machine_findings": findings,
        "required_checks": [
            "verify_source_ownership_and_license",
            "review_prompt_injection_findings",
            "verify_each_claim_against_evidence",
            "resolve_duplicate_or_existing_concept",
            "verify_audience_does_not_downgrade_source_acl",
            "record_human_reviewer_and_decision",
        ],
    }
    packet = {
        "draft/concept.md": _draft_markdown(
            request,
            capture_id=capture_id,
            concept_id=concept_id,
            kos_id=kos_id,
            review_id=review_id,
        ),
        "draft/provenance.json": _canonical_json(provenance),
        "draft/source-record.json": _canonical_json(source_record),
        "review-checklist.json": _canonical_json(review),
    }
    manifest = {
        "schema_version": "1.0",
        "capture_id": capture_id,
        "status": packet_status,
        "canonical_write_permitted": False,
        "capture_metadata_key": capture_metadata_key,
        "files": [
            {
                "path": path,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
            for path, data in sorted(packet.items())
        ],
    }
    packet["review-packet.json"] = _canonical_json(manifest)
    return packet


def intake_markdown(
    *,
    store: ObjectStore,
    request: IntakeRequest,
    input_path: Path,
    output_dir: Path,
) -> IntakeResult:
    request.validate()
    try:
        raw = input_path.read_bytes()
    except OSError as exc:
        raise IntegrityError(f"cannot read intake source: {input_path}") from exc
    if not raw:
        raise IntegrityError("Markdown intake cannot be empty")
    if len(raw) > MAX_SOURCE_BYTES:
        raise IntegrityError(f"Markdown intake exceeds {MAX_SOURCE_BYTES} bytes")

    normalized = _normalize_markdown(raw)
    normalized_text = normalized.decode("utf-8")
    _scan_secrets(normalized_text)
    findings = _prompt_injection_findings(normalized_text)

    raw_sha256 = sha256_bytes(raw)
    normalized_sha256 = sha256_bytes(normalized)
    capture_identity = {
        "schema_version": "1.0",
        "request": request.to_dict(),
        "raw_sha256": raw_sha256,
        "normalized_sha256": normalized_sha256,
    }
    capture_id = "capture_" + sha256_bytes(_canonical_json(capture_identity))[:32]
    raw_blob_key = f"raw/blobs/sha256/{raw_sha256[:2]}/{raw_sha256}"
    capture_metadata_key = f"raw/captures/{capture_id}.json"
    normalized_key = f"normalized/captures/{capture_id}/document.md"
    review_packet_prefix = f"review/packets/{capture_id}"

    capture_metadata = {
        **capture_identity,
        "capture_id": capture_id,
        "status": "captured",
        "raw_blob_key": raw_blob_key,
        "raw_bytes": len(raw),
        "normalized_key": normalized_key,
        "normalized_bytes": len(normalized),
        "machine_findings": findings,
        "downstream_synthesis_permitted": not findings,
        "canonical_write_permitted": False,
    }
    capture_metadata_bytes = _canonical_json(capture_metadata)
    packet = _build_review_packet(
        request,
        capture_id=capture_id,
        raw_blob_key=raw_blob_key,
        capture_metadata_key=capture_metadata_key,
        normalized_key=normalized_key,
        raw_sha256=raw_sha256,
        normalized_sha256=normalized_sha256,
        findings=findings,
    )

    object_states = []
    raw_blob_reused = _put_immutable(
        store,
        raw_blob_key,
        raw,
        content_type=request.content_type,
    )
    object_states.append(raw_blob_reused)
    object_states.append(
        _put_immutable(
            store,
            capture_metadata_key,
            capture_metadata_bytes,
            content_type="application/json",
        )
    )
    object_states.append(
        _put_immutable(
            store,
            normalized_key,
            normalized,
            content_type="text/markdown",
        )
    )
    for relative, data in sorted(packet.items()):
        content_type = "text/markdown" if relative.endswith(".md") else "application/json"
        object_states.append(
            _put_immutable(
                store,
                f"{review_packet_prefix}/{relative}",
                data,
                content_type=content_type,
            )
        )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw-capture.json").write_bytes(capture_metadata_bytes)
    (output_dir / "normalized.md").write_bytes(normalized)
    for relative, data in packet.items():
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    review_packet_sha256 = sha256_bytes(packet["review-packet.json"])
    result = IntakeResult(
        capture_id=capture_id,
        status="review_required",
        idempotent=all(object_states),
        raw_blob_reused=raw_blob_reused,
        raw_blob_key=raw_blob_key,
        capture_metadata_key=capture_metadata_key,
        normalized_key=normalized_key,
        review_packet_prefix=review_packet_prefix,
        raw_sha256=raw_sha256,
        normalized_sha256=normalized_sha256,
        review_packet_sha256=review_packet_sha256,
        machine_finding_count=len(findings),
    )
    (output_dir / "intake-result.json").write_bytes(_canonical_json(result.to_dict()))
    return result
