from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .intake_v1 import (
    AUDIENCES,
    SNAPSHOT_ID_RE,
    SOURCE_ID_RE,
    AccessPolicy,
    EvidenceValue,
    IntakeFailure,
    IntakeResult,
    _event,
    _event_keys,
    _pretty_json_bytes,
    _prompt_findings,
    _put_immutable,
    _reject,
    _secret_matches,
    _storage_location,
    _validate_utc,
    _write_event,
    _write_output,
    canonical_json_bytes,
    derivative_id_for,
    snapshot_id_for,
    stable_source_id,
)
from .storage import ObjectStore, sha256_bytes

CONNECTOR_TYPE = "local_pdf"
CONNECTOR_VERSION = "local-pdf/1.0.0"
PARSER_ID = "pypdf_text"
PARSER_VERSION = "6.14.2"
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_OBJECTS = 100_000
DEFAULT_MAX_STREAMS = 50_000
DEFAULT_MAX_DERIVATIVE_BYTES = 16 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
DEFAULT_CPU_SECONDS = 10

PDF_HEADER_RE = re.compile(rb"\A%PDF-(?P<version>1\.[0-7]|2\.0)\b")
PDF_OBJECT_RE = re.compile(rb"(?m)^[ \t]*\d+[ \t]+\d+[ \t]+obj\b")
PDF_STREAM_RE = re.compile(rb"(?m)^[ \t]*stream[ \t]*\r?$")
PDF_EOF_RE = re.compile(rb"%%EOF[ \t\r\n]*\Z")
ACTIVE_FEATURE_PATTERNS = {
    "javascript": re.compile(rb"/(?:JavaScript|JS)\b"),
    "open_action": re.compile(rb"/OpenAction\b"),
    "additional_actions": re.compile(rb"/AA\b"),
    "launch_action": re.compile(rb"/Launch\b"),
    "embedded_file": re.compile(rb"/(?:EmbeddedFile|EmbeddedFiles)\b"),
    "rich_media": re.compile(rb"/RichMedia\b"),
    "xfa": re.compile(rb"/XFA\b"),
    "external_file_spec": re.compile(rb"/(?:Filespec|GoToR)\b"),
}
ENCRYPTION_PATTERN = re.compile(rb"/Encrypt\b")


@dataclass(frozen=True)
class PDFRequest:
    locator: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    max_pages: int = DEFAULT_MAX_PAGES
    max_objects: int = DEFAULT_MAX_OBJECTS
    max_streams: int = DEFAULT_MAX_STREAMS
    max_derivative_bytes: int = DEFAULT_MAX_DERIVATIVE_BYTES
    parser_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    parser_memory_bytes: int = DEFAULT_MEMORY_BYTES
    parser_cpu_seconds: int = DEFAULT_CPU_SECONDS

    def validate(self) -> None:
        if not self.locator.strip():
            raise IntakeFailure("INVALID_LOCATOR", "request", "locator is required")
        _validate_utc(self.retrieved_at)
        self.owner.validate("owner")
        self.license.validate("license")
        if self.audience not in AUDIENCES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid audience")
        self.access_policy.validate(audience=self.audience)
        if self.source_id is not None and not SOURCE_ID_RE.fullmatch(self.source_id):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid source_id")
        if self.parent_snapshot is not None and not SNAPSHOT_ID_RE.fullmatch(
            self.parent_snapshot
        ):
            raise IntakeFailure("INVALID_METADATA", "request", "invalid parent_snapshot")
        numeric_limits = {
            "max_bytes": self.max_bytes,
            "max_pages": self.max_pages,
            "max_objects": self.max_objects,
            "max_streams": self.max_streams,
            "max_derivative_bytes": self.max_derivative_bytes,
            "parser_memory_bytes": self.parser_memory_bytes,
            "parser_cpu_seconds": self.parser_cpu_seconds,
        }
        if any(value < 1 for value in numeric_limits.values()):
            raise IntakeFailure("INVALID_METADATA", "request", "PDF limits must be positive")
        if not 0 < self.parser_timeout_seconds <= 120:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "parser_timeout_seconds must be between 0 and 120",
            )
        if self.max_pages > 10_000 or self.max_objects > 1_000_000:
            raise IntakeFailure("INVALID_METADATA", "request", "PDF limits exceed hard policy")
        if self.parser_memory_bytes > 4 * 1024 * 1024 * 1024:
            raise IntakeFailure("INVALID_METADATA", "request", "parser memory exceeds hard policy")

    def attempt_id(self) -> str:
        seed = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "locator": self.locator,
            "retrieved_at": self.retrieved_at,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "source_id": self.source_id,
            "parent_snapshot": self.parent_snapshot,
            "max_bytes": self.max_bytes,
            "max_pages": self.max_pages,
            "max_objects": self.max_objects,
            "max_streams": self.max_streams,
            "max_derivative_bytes": self.max_derivative_bytes,
            "parser_timeout_seconds": self.parser_timeout_seconds,
            "parser_memory_bytes": self.parser_memory_bytes,
            "parser_cpu_seconds": self.parser_cpu_seconds,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(seed))[:32]


@dataclass(frozen=True)
class PDFAcquisition:
    canonical_locator: str
    original_uri: str
    source_version: str
    data: bytes


@dataclass(frozen=True)
class PDFPreflight:
    pdf_version: str
    object_count: int
    stream_count: int
    active_content_findings: tuple[str, ...]
    encrypted_marker_present: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PDFParseResult:
    parser_id: str
    parser_version: str
    library_version: str
    page_count: int
    extractable_character_count: int
    markdown: bytes


ParserRunner = Callable[[bytes, PDFRequest], PDFParseResult]


class LocalPDFConnector:
    def __init__(self, allowed_root: Path) -> None:
        self.allowed_root = allowed_root.resolve(strict=True)
        if not self.allowed_root.is_dir():
            raise ValueError("allowed_root must be a directory")

    def canonicalize(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure("SOURCE_NOT_FOUND", "discover", "source does not exist") from exc
        try:
            resolved.relative_to(self.allowed_root)
        except ValueError as exc:
            raise IntakeFailure("PATH_ESCAPE", "discover", "source escapes the allowed root") from exc
        if resolved.suffix.lower() != ".pdf":
            raise IntakeFailure("UNSUPPORTED_MIME_TYPE", "discover", "source must use .pdf suffix")
        return resolved

    def acquire(self, path: Path, *, max_bytes: int) -> PDFAcquisition:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise IntakeFailure("UNSUPPORTED_BINARY", "acquire", "source is not a regular file")
        if before.st_size < 1:
            raise IntakeFailure("EMPTY_SOURCE", "acquire", "source is empty")
        if before.st_size > max_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "acquire",
                "PDF exceeds maximum bytes",
                safe_context={"observed_bytes": before.st_size, "max_bytes": max_bytes},
            )

        chunks: list[bytes] = []
        observed = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(min(64 * 1024, max_bytes + 1 - observed))
                if not chunk:
                    break
                chunks.append(chunk)
                observed += len(chunk)
                if observed > max_bytes:
                    raise IntakeFailure(
                        "SOURCE_TOO_LARGE",
                        "acquire",
                        "PDF exceeds maximum bytes during read",
                        safe_context={"observed_bytes": observed, "max_bytes": max_bytes},
                    )

        after = path.stat()
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity:
            raise IntakeFailure(
                "SOURCE_CHANGED_DURING_READ",
                "acquire",
                "source changed during acquisition",
            )

        source_version = (
            f"local:{before.st_dev}:{before.st_ino}:{before.st_size}:{before.st_mtime_ns}"
        )
        return PDFAcquisition(
            canonical_locator=path.as_uri(),
            original_uri=path.as_uri(),
            source_version=source_version,
            data=b"".join(chunks),
        )


def inspect_pdf(data: bytes, request: PDFRequest) -> PDFPreflight:
    header = PDF_HEADER_RE.search(data[:16])
    if header is None:
        raise IntakeFailure("PDF_INVALID_HEADER", "safety_gate", "invalid PDF header")
    if PDF_EOF_RE.search(data[-4096:]) is None:
        raise IntakeFailure("PDF_MISSING_EOF", "safety_gate", "PDF EOF marker is missing")
    if b"startxref" not in data[-8192:]:
        raise IntakeFailure("PDF_MISSING_XREF", "safety_gate", "PDF startxref marker is missing")

    object_count = len(PDF_OBJECT_RE.findall(data))
    stream_count = len(PDF_STREAM_RE.findall(data))
    if object_count < 1:
        raise IntakeFailure("PDF_NO_OBJECTS", "safety_gate", "PDF has no indirect objects")
    if object_count > request.max_objects:
        raise IntakeFailure(
            "PDF_OBJECT_LIMIT",
            "safety_gate",
            "PDF object count exceeds policy",
            safe_context={"object_count": object_count, "max_objects": request.max_objects},
        )
    if stream_count > request.max_streams:
        raise IntakeFailure(
            "PDF_STREAM_LIMIT",
            "safety_gate",
            "PDF stream count exceeds policy",
            safe_context={"stream_count": stream_count, "max_streams": request.max_streams},
        )

    encrypted = bool(ENCRYPTION_PATTERN.search(data))
    active_findings = tuple(
        sorted(name for name, pattern in ACTIVE_FEATURE_PATTERNS.items() if pattern.search(data))
    )
    if encrypted:
        raise IntakeFailure("PDF_ENCRYPTED", "safety_gate", "encrypted PDFs are forbidden")
    if active_findings:
        raise IntakeFailure(
            "PDF_ACTIVE_CONTENT",
            "safety_gate",
            "PDF contains forbidden active content",
            safe_context={"findings": list(active_findings)},
        )

    return PDFPreflight(
        pdf_version=header.group("version").decode("ascii"),
        object_count=object_count,
        stream_count=stream_count,
        active_content_findings=active_findings,
        encrypted_marker_present=encrypted,
    )


def run_pdf_parser(data: bytes, request: PDFRequest) -> PDFParseResult:
    output_file_limit = max(request.max_derivative_bytes + 1024 * 1024, 2 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix="knowledge-pdf-") as temporary:
        root = Path(temporary)
        source = root / "source.pdf"
        destination = root / "result.json"
        source.write_bytes(data)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PYTHONNOUSERSITE": "1",
            "KNOWLEDGE_PDF_MAX_MEMORY_BYTES": str(request.parser_memory_bytes),
            "KNOWLEDGE_PDF_MAX_CPU_SECONDS": str(request.parser_cpu_seconds),
            "KNOWLEDGE_PDF_MAX_OUTPUT_BYTES": str(output_file_limit),
            "KNOWLEDGE_PDF_MAX_DERIVATIVE_BYTES": str(request.max_derivative_bytes),
            "KNOWLEDGE_PDF_MAX_PAGES": str(request.max_pages),
        }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "knowledge_engine.pdf_parser_worker",
                    str(source),
                    str(destination),
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=request.parser_timeout_seconds,
                check=False,
                close_fds=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise IntakeFailure(
                "PDF_PARSE_TIMEOUT",
                "parse",
                "PDF parser exceeded wall-clock policy",
                transient=True,
            ) from exc

        if completed.returncode != 0 or not destination.is_file():
            raise IntakeFailure("PDF_PARSER_CRASH", "parse", "PDF parser terminated unexpectedly")
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntakeFailure(
                "PDF_PARSER_PROTOCOL_ERROR",
                "parse",
                "PDF parser returned invalid evidence",
            ) from exc

    if payload.get("ok") is not True:
        code = str(payload.get("code") or "PDF_PARSE_FAILED")
        allowed_codes = {
            "PDF_DERIVATIVE_TOO_LARGE",
            "PDF_EMPTY",
            "PDF_ENCRYPTED",
            "PDF_PAGE_LIMIT",
            "PDF_PARSE_FAILED",
            "PDF_PARSER_MEMORY_LIMIT",
        }
        if code not in allowed_codes:
            code = "PDF_PARSE_FAILED"
        raise IntakeFailure(code, "parse", "PDF parser rejected the document")

    parser_id = payload.get("parser_id")
    parser_version = payload.get("parser_version")
    library_version = payload.get("library_version")
    if (
        parser_id != PARSER_ID
        or parser_version != PARSER_VERSION
        or library_version != PARSER_VERSION
    ):
        raise IntakeFailure(
            "PDF_PARSER_VERSION_MISMATCH",
            "parse",
            "PDF parser identity does not match the pinned contract",
        )
    markdown_value = payload.get("markdown")
    page_count = payload.get("page_count")
    character_count = payload.get("extractable_character_count")
    if not isinstance(markdown_value, str) or not isinstance(page_count, int):
        raise IntakeFailure(
            "PDF_PARSER_PROTOCOL_ERROR",
            "parse",
            "PDF parser result has invalid types",
        )
    if not isinstance(character_count, int) or page_count < 1 or page_count > request.max_pages:
        raise IntakeFailure(
            "PDF_PARSER_PROTOCOL_ERROR",
            "parse",
            "PDF parser result violates page or character invariants",
        )
    markdown = markdown_value.encode("utf-8")
    if len(markdown) > request.max_derivative_bytes:
        raise IntakeFailure(
            "PDF_DERIVATIVE_TOO_LARGE",
            "parse",
            "PDF derivative exceeds maximum bytes",
        )
    return PDFParseResult(
        parser_id=parser_id,
        parser_version=parser_version,
        library_version=library_version,
        page_count=page_count,
        extractable_character_count=character_count,
        markdown=markdown,
    )


def _pdf_evidence(
    *,
    attempt_id: str,
    source_id: str,
    raw_hash: str,
    byte_size: int,
    preflight: PDFPreflight | None,
    parse_result: PDFParseResult | None,
    failure: IntakeFailure | None,
) -> dict[str, Any]:
    return {
        "schema_version": "pdf-parse-evidence/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "connector_type": CONNECTOR_TYPE,
        "connector_version": CONNECTOR_VERSION,
        "raw_sha256": raw_hash,
        "byte_size": byte_size,
        "preflight": preflight.to_dict() if preflight is not None else None,
        "parser": (
            {
                "parser_id": parse_result.parser_id,
                "parser_version": parse_result.parser_version,
                "library_version": parse_result.library_version,
                "page_count": parse_result.page_count,
                "extractable_character_count": parse_result.extractable_character_count,
                "derivative_byte_size": len(parse_result.markdown),
            }
            if parse_result is not None
            else None
        ),
        "outcome": "accepted" if failure is None else "rejected",
        "failure_code": failure.code if failure is not None else None,
        "safe_context": failure.safe_context if failure is not None else {},
        "network_access_permitted": False,
        "javascript_execution_permitted": False,
        "attachment_extraction_permitted": False,
        "ocr_permitted": False,
    }


def intake_local_pdf(
    *,
    store: ObjectStore,
    request: PDFRequest,
    allowed_root: Path,
    output_dir: Path | None = None,
    parser_runner: ParserRunner = run_pdf_parser,
) -> IntakeResult:
    """Acquire one local PDF into the immutable M10 intake namespace."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None

    try:
        request.validate()
        connector = LocalPDFConnector(allowed_root)
        path = connector.canonicalize(request.locator)
        canonical_locator = path.as_uri()
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)
        artifacts["source_id"] = source_id

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[f"locator_sha256:{sha256_bytes(canonical_locator.encode('utf-8'))}"],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        acquisition = connector.acquire(path, max_bytes=request.max_bytes)
        raw_hash = sha256_bytes(acquisition.data)
        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[f"sha256:{raw_hash}", f"bytes:{len(acquisition.data)}"],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        parse_evidence_key = f"intake/v1/attempts/{attempt_id}/pdf-parse.json"
        artifacts["parse_evidence_key"] = parse_evidence_key
        preflight: PDFPreflight | None = None
        parse_result: PDFParseResult | None = None
        try:
            preflight = inspect_pdf(acquisition.data, request)
            parse_result = parser_runner(acquisition.data, request)
        except IntakeFailure as failure:
            evidence = _pdf_evidence(
                attempt_id=attempt_id,
                source_id=source_id,
                raw_hash=raw_hash,
                byte_size=len(acquisition.data),
                preflight=preflight,
                parse_result=None,
                failure=failure,
            )
            object_states.append(
                _put_immutable(
                    store,
                    parse_evidence_key,
                    _pretty_json_bytes(evidence),
                    content_type="application/json",
                )
            )
            raise

        evidence = _pdf_evidence(
            attempt_id=attempt_id,
            source_id=source_id,
            raw_hash=raw_hash,
            byte_size=len(acquisition.data),
            preflight=preflight,
            parse_result=parse_result,
            failure=None,
        )
        evidence_bytes = _pretty_json_bytes(evidence)
        object_states.append(
            _put_immutable(
                store,
                parse_evidence_key,
                evidence_bytes,
                content_type="application/json",
            )
        )

        extracted_text = parse_result.markdown.decode("utf-8")
        secret_matches = _secret_matches(extracted_text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "PDF extraction contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "observed_sha256": raw_hash,
                    "observed_bytes": len(acquisition.data),
                },
            )

        raw_blob_key = f"intake/v1/raw/sha256/{raw_hash[:2]}/{raw_hash}"
        raw_reused = _put_immutable(
            store,
            raw_blob_key,
            acquisition.data,
            content_type="application/pdf",
        )
        object_states.append(raw_reused)
        artifacts.update(raw_blob_key=raw_blob_key, raw_blob_reused=raw_reused)

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            else "resolved"
        )
        identity = {
            "schema_version": "intake-snapshot/v1",
            "source_id": source_id,
            "original_uri": acquisition.original_uri,
            "connector_type": CONNECTOR_TYPE,
            "connector_version": CONNECTOR_VERSION,
            "retrieved_at": request.retrieved_at,
            "content_hash": raw_hash,
            "byte_size": len(acquisition.data),
            "mime_type": "application/pdf",
            "encoding": "binary",
            "license": request.license.to_dict(),
            "owner": request.owner.to_dict(),
            "audience": request.audience,
            "access_policy": request.access_policy.to_dict(),
            "source_version": acquisition.source_version,
            "parent_snapshot": request.parent_snapshot,
        }
        snapshot_id = snapshot_id_for(identity)
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot = {
            **identity,
            "snapshot_id": snapshot_id,
            "acl_status": acl_status,
            "storage_location": _storage_location(store, raw_blob_key, raw_hash),
        }
        snapshot_bytes = _pretty_json_bytes(snapshot)
        object_states.append(
            _put_immutable(store, snapshot_key, snapshot_bytes, content_type="application/json")
        )
        artifacts.update(snapshot_id=snapshot_id, snapshot_key=snapshot_key)

        snapshotted = _event(
            attempt_id=attempt_id,
            sequence=3,
            occurred_at=request.retrieved_at,
            from_state="acquired",
            to_state="snapshotted",
            reason_code="SNAPSHOT_WRITTEN",
            evidence_refs=[raw_blob_key, snapshot_key, parse_evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        normalized = parse_result.markdown
        normalized_hash = sha256_bytes(normalized)
        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=parse_result.parser_id,
            normalizer_version=parse_result.parser_version,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{parse_result.parser_id}/"
            f"{parse_result.parser_version}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{parse_result.parser_id}/"
            f"{parse_result.parser_version}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = {
            "schema_version": "intake-derivative/v1",
            "derivative_id": derivative_id,
            "snapshot_id": snapshot_id,
            "normalizer_id": parse_result.parser_id,
            "normalizer_version": parse_result.parser_version,
            "normalized_content_hash": normalized_hash,
            "normalized_key": normalized_key,
            "byte_size": len(normalized),
            "mime_type": "text/markdown",
            "warnings": _prompt_findings(extracted_text),
            "parse_evidence_key": parse_evidence_key,
            "page_count": parse_result.page_count,
            "extractable_character_count": parse_result.extractable_character_count,
        }
        derivative_bytes = _pretty_json_bytes(derivative)
        object_states.append(
            _put_immutable(
                store,
                derivative_key,
                derivative_bytes,
                content_type="application/json",
            )
        )
        artifacts.update(
            derivative_id=derivative_id,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
        )

        normalized_event = _event(
            attempt_id=attempt_id,
            sequence=4,
            occurred_at=request.retrieved_at,
            from_state="snapshotted",
            to_state="normalized",
            reason_code="DERIVATIVE_WRITTEN",
            evidence_refs=[normalized_key, derivative_key, parse_evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, normalized_event)
        events.append(normalized_event)
        object_states.append(reused)
        current_state = "normalized"

        if acl_status != "resolved" or request.owner.status != "resolved":
            raise IntakeFailure(
                "ACL_UNRESOLVED",
                "admission",
                "ACL or ownership is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )
        if request.license.status != "resolved":
            raise IntakeFailure(
                "LICENSE_UNRESOLVED",
                "admission",
                "license is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )

        accepted = _event(
            attempt_id=attempt_id,
            sequence=5,
            occurred_at=request.retrieved_at,
            from_state="normalized",
            to_state="accepted_for_compilation",
            reason_code="COMPILATION_ADMISSION_ACCEPTED",
            evidence_refs=[snapshot_key, derivative_key, parse_evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, accepted)
        events.append(accepted)
        object_states.append(reused)

        result_key = f"intake/v1/attempts/{attempt_id}/result.json"
        result = IntakeResult(
            attempt_id=attempt_id,
            status="accepted_for_compilation",
            source_id=source_id,
            snapshot_id=snapshot_id,
            derivative_id=derivative_id,
            raw_blob_key=raw_blob_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=raw_reused,
            event_keys=_event_keys(attempt_id, events),
        )
        object_states.append(
            _put_immutable(
                store,
                result_key,
                _pretty_json_bytes(result.evidence_dict()),
                content_type="application/json",
            )
        )
        result = replace(result, idempotent=all(object_states))
        _write_output(output_dir, "pdf-parse.json", evidence_bytes)
        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        return _reject(
            store=store,
            request=request,
            attempt_id=attempt_id,
            failure=failure,
            current_state=current_state,
            events=events,
            object_states=object_states,
            artifacts=artifacts,
            output_dir=output_dir,
        )
