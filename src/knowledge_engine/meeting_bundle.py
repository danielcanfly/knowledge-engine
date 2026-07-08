from __future__ import annotations

import json
import re
import stat
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .intake_v1 import IntakeFailure, canonical_json_bytes
from .media_bundle import (
    FileIdentity,
    _read_regular_file,
    _verify_identity,
    canonical_relative_path,
    format_timestamp,
)
from .storage import sha256_bytes

MANIFEST_SCHEMA = "meeting-transcript/v1"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_SEGMENTS = 20_000
DEFAULT_MAX_PARTICIPANTS = 500
DEFAULT_MAX_ANNOTATIONS = 2_000
DEFAULT_MAX_DURATION_MS = 24 * 60 * 60 * 1000
HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.+/-]{1,128}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SEGMENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,4}$")
TIMECODE_RE = re.compile(
    r"^## \[(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\] "
    r"([A-Za-z0-9_.-]{1,64}) #([A-Za-z0-9_.-]{1,64})$"
)
PLATFORMS = {"zoom", "google_meet", "microsoft_teams", "slack_huddle", "generic"}
PARTICIPANT_ROLES = {"host", "organizer", "attendee", "guest", "bot", "unknown"}
ATTENDANCE_STATES = {"present", "partial", "silent", "unknown"}
IDENTITY_STATES = {"verified", "unverified"}
POLICY_TYPES = {"public", "authenticated", "principal_set", "restricted", "unresolved"}
OBSERVATION_SOURCES = {"observed", "operator_asserted", "inherited", "unresolved"}
DECISION_STATES = {"proposed", "confirmed", "rejected", "unresolved"}
ACTION_STATES = {"open", "in_progress", "done", "cancelled", "unresolved"}
TRANSCRIPT_ORIGINS = {"platform_generated", "human_authored", "external_transcription"}


@dataclass(frozen=True)
class MeetingSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    speaker_label: str
    text_sha256: str
    text: str


@dataclass(frozen=True)
class MeetingParticipant:
    speaker_label: str
    role: str
    attendance: str
    identity_status: str
    principal_sha256: str | None


@dataclass(frozen=True)
class MeetingAnnotation:
    annotation_id: str
    text: str
    evidence_segment_ids: tuple[str, ...]
    status: str | None = None
    owner_speaker_label: str | None = None
    due_date: str | None = None


@dataclass(frozen=True)
class MeetingAccess:
    policy_type: str
    principal_hashes: tuple[str, ...]
    observation_source: str
    native_evidence_sha256: str | None

    @property
    def minimum_audience(self) -> str:
        return {
            "public": "public",
            "authenticated": "internal",
            "principal_set": "confidential",
            "restricted": "restricted",
            "unresolved": "restricted",
        }[self.policy_type]

    @property
    def digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "policy_type": self.policy_type,
                    "principal_hashes": list(self.principal_hashes),
                    "observation_source": self.observation_source,
                    "native_evidence_sha256": self.native_evidence_sha256,
                }
            )
        )


@dataclass(frozen=True)
class MeetingManifest:
    source_uri_sha256: str
    meeting_id_sha256: str
    title_sha256: str
    platform: str
    scheduled_start: str
    scheduled_end: str
    actual_start: str
    actual_end: str
    duration_ms: int
    transcript_path: str
    transcript_sha256: str
    transcript_byte_size: int
    language: str
    participants: tuple[MeetingParticipant, ...]
    access: MeetingAccess
    agenda: tuple[MeetingAnnotation, ...]
    decisions: tuple[MeetingAnnotation, ...]
    action_items: tuple[MeetingAnnotation, ...]
    extraction_tool: str
    extraction_version: str
    transcript_origin: str
    segments: tuple[MeetingSegment, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class MeetingBundle:
    bundle_root: Path
    bundle_identity: FileIdentity
    manifest_identity: FileIdentity
    transcript_identity: FileIdentity
    manifest_bytes: bytes
    transcript_bytes: bytes
    manifest: MeetingManifest


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise IntakeFailure(
            "MEETING_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} fields are invalid",
        )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntakeFailure(
            "MEETING_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} must be an object",
        )
    return value


def _string(
    value: Any,
    field: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 4096,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise IntakeFailure(
            "MEETING_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} is invalid",
        )
    if pattern is not None and pattern.fullmatch(value) is None:
        raise IntakeFailure(
            "MEETING_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} has invalid syntax",
        )
    return value


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise IntakeFailure(
            "MEETING_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} is outside policy",
        )
    return value


def _utc(value: Any, field: str) -> tuple[str, datetime]:
    text = _string(value, field, maximum=128)
    if not text.endswith("Z"):
        raise IntakeFailure("MEETING_TIME_INVALID", "safety_gate", f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise IntakeFailure("MEETING_TIME_INVALID", "safety_gate", f"{field} is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise IntakeFailure("MEETING_TIME_INVALID", "safety_gate", f"{field} must be UTC")
    return text, parsed


def _timestamp_ms(groups: tuple[str, str, str, str]) -> int:
    hours, minutes, seconds, milliseconds = (int(value) for value in groups)
    if minutes > 59 or seconds > 59:
        raise IntakeFailure("MEETING_TIMECODE_INVALID", "normalize", "timecode is invalid")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _canonical_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = normalized.strip("\n")
    if not normalized.strip():
        raise IntakeFailure("MEETING_SEGMENT_EMPTY", "normalize", "meeting segment text is empty")
    return normalized + "\n"


def parse_transcript(data: bytes, *, max_segments: int) -> tuple[MeetingSegment, ...]:
    if b"\x00" in data:
        raise IntakeFailure("MEETING_TRANSCRIPT_BINARY", "safety_gate", "transcript has NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeFailure(
            "MEETING_TRANSCRIPT_INVALID_UTF8",
            "safety_gate",
            "transcript must be UTF-8",
        ) from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntakeFailure("EMPTY_SOURCE", "normalize", "meeting transcript is empty")
    lines = text.split("\n")
    headings: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = TIMECODE_RE.fullmatch(line)
        if match is not None:
            headings.append((index, match))
    if not headings or headings[0][0] != 0:
        raise IntakeFailure(
            "MEETING_TRANSCRIPT_FORMAT_INVALID",
            "normalize",
            "transcript must begin with a segment heading",
        )
    if len(headings) > max_segments:
        raise IntakeFailure("MEETING_SEGMENT_LIMIT", "normalize", "segment count exceeds policy")
    segments: list[MeetingSegment] = []
    seen_ids: set[str] = set()
    previous_end = 0
    for offset, (line_index, match) in enumerate(headings):
        next_index = headings[offset + 1][0] if offset + 1 < len(headings) else len(lines)
        content = lines[line_index + 1 : next_index]
        while content and content[0] == "":
            content.pop(0)
        while content and content[-1] == "":
            content.pop()
        canonical = _canonical_text("\n".join(content))
        start_ms = _timestamp_ms(match.groups()[0:4])
        end_ms = _timestamp_ms(match.groups()[4:8])
        speaker = match.group(9)
        segment_id = match.group(10)
        if segment_id in seen_ids:
            raise IntakeFailure("MEETING_SEGMENT_DUPLICATE", "normalize", "segment ID is duplicated")
        if end_ms <= start_ms or start_ms < previous_end:
            raise IntakeFailure(
                "MEETING_SEGMENT_OVERLAP",
                "normalize",
                "segments overlap, reverse, or are out of order",
            )
        seen_ids.add(segment_id)
        previous_end = end_ms
        segments.append(
            MeetingSegment(
                segment_id=segment_id,
                start_ms=start_ms,
                end_ms=end_ms,
                speaker_label=speaker,
                text_sha256=sha256_bytes(canonical.encode("utf-8")),
                text=canonical,
            )
        )
    return tuple(segments)


def _parse_participants(
    value: Any,
    *,
    max_participants: int,
) -> tuple[MeetingParticipant, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= max_participants:
        raise IntakeFailure(
            "MEETING_PARTICIPANT_LIMIT",
            "safety_gate",
            "participant count is outside policy",
        )
    participants: list[MeetingParticipant] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _mapping(raw, f"participants[{index}]")
        _exact_keys(
            item,
            {"speaker_label", "role", "attendance", "identity_status", "principal_sha256"},
            f"participants[{index}]",
        )
        speaker = _string(item["speaker_label"], "participant.speaker_label", pattern=ALIAS_RE)
        role = _string(item["role"], "participant.role", maximum=64)
        attendance = _string(item["attendance"], "participant.attendance", maximum=64)
        identity_status = _string(item["identity_status"], "participant.identity_status", maximum=64)
        principal = item["principal_sha256"]
        if role not in PARTICIPANT_ROLES or attendance not in ATTENDANCE_STATES:
            raise IntakeFailure(
                "MEETING_PARTICIPANT_INVALID",
                "safety_gate",
                "participant role or attendance is invalid",
            )
        if identity_status not in IDENTITY_STATES:
            raise IntakeFailure(
                "MEETING_IDENTITY_INVALID",
                "safety_gate",
                "participant identity status is invalid",
            )
        if identity_status == "verified":
            principal = _string(principal, "participant.principal_sha256", pattern=HEX64_RE)
        elif principal is not None:
            raise IntakeFailure(
                "MEETING_IDENTITY_INVALID",
                "safety_gate",
                "unverified participant cannot carry a principal hash",
            )
        if speaker in seen:
            raise IntakeFailure(
                "MEETING_PARTICIPANT_DUPLICATE",
                "safety_gate",
                "speaker alias is duplicated",
            )
        seen.add(speaker)
        participants.append(
            MeetingParticipant(speaker, role, attendance, identity_status, principal)
        )
    return tuple(participants)


def _parse_access(value: Any) -> MeetingAccess:
    item = _mapping(value, "access")
    _exact_keys(
        item,
        {"policy_type", "principal_hashes", "observation_source", "native_evidence_sha256"},
        "access",
    )
    policy_type = _string(item["policy_type"], "access.policy_type", maximum=64)
    observation = _string(item["observation_source"], "access.observation_source", maximum=64)
    principals_value = item["principal_hashes"]
    if policy_type not in POLICY_TYPES or observation not in OBSERVATION_SOURCES:
        raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "meeting ACL is invalid")
    if not isinstance(principals_value, list) or len(principals_value) > 10_000:
        raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "meeting ACL principals invalid")
    principals = tuple(
        sorted(
            _string(value, "access.principal_hash", pattern=HEX64_RE)
            for value in principals_value
        )
    )
    if len(set(principals)) != len(principals):
        raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "meeting ACL principals duplicate")
    native_value = item["native_evidence_sha256"]
    if policy_type == "unresolved" or observation == "unresolved":
        if policy_type != "unresolved" or observation != "unresolved" or principals or native_value is not None:
            raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "unresolved ACL is malformed")
        native_hash = None
    else:
        native_hash = _string(native_value, "access.native_evidence_sha256", pattern=HEX64_RE)
        if policy_type == "public" and principals:
            raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "public ACL cannot list principals")
        if policy_type in {"authenticated", "principal_set"} and not principals:
            raise IntakeFailure("MEETING_ACL_INVALID", "safety_gate", "meeting ACL needs principals")
    return MeetingAccess(policy_type, principals, observation, native_hash)


def _annotation_text(value: Any, field: str) -> str:
    text = _string(value, field, maximum=4000)
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise IntakeFailure("MEETING_ANNOTATION_INVALID", "safety_gate", "annotation has controls")
    if not text.strip():
        raise IntakeFailure("MEETING_ANNOTATION_INVALID", "safety_gate", "annotation is empty")
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _evidence_ids(value: Any, known_segments: set[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > 500:
        raise IntakeFailure(
            "MEETING_ANNOTATION_EVIDENCE_INVALID",
            "safety_gate",
            "annotation evidence is invalid",
        )
    ids = tuple(_string(item, "annotation.evidence_segment_id", pattern=SEGMENT_ID_RE) for item in value)
    if len(set(ids)) != len(ids) or any(item not in known_segments for item in ids):
        raise IntakeFailure(
            "MEETING_ANNOTATION_EVIDENCE_INVALID",
            "safety_gate",
            "annotation evidence does not resolve",
        )
    return ids


def _parse_annotations(
    value: Any,
    *,
    known_segments: set[str],
    participants: set[str],
    max_annotations: int,
) -> tuple[
    tuple[MeetingAnnotation, ...],
    tuple[MeetingAnnotation, ...],
    tuple[MeetingAnnotation, ...],
]:
    root = _mapping(value, "annotations")
    _exact_keys(root, {"agenda", "decisions", "action_items"}, "annotations")
    total = sum(len(root[key]) if isinstance(root[key], list) else max_annotations + 1 for key in root)
    if total > max_annotations:
        raise IntakeFailure(
            "MEETING_ANNOTATION_LIMIT",
            "safety_gate",
            "annotation count exceeds policy",
        )
    seen_ids: set[str] = set()

    def common(raw: Any, index: int, field: str, expected: set[str]) -> tuple[dict[str, Any], str, str, tuple[str, ...]]:
        item = _mapping(raw, f"annotations.{field}[{index}]")
        _exact_keys(item, expected, f"annotations.{field}[{index}]")
        annotation_id = _string(item["id"], "annotation.id", pattern=SAFE_ID_RE)
        if annotation_id in seen_ids:
            raise IntakeFailure(
                "MEETING_ANNOTATION_DUPLICATE",
                "safety_gate",
                "annotation ID is duplicated",
            )
        seen_ids.add(annotation_id)
        text = _annotation_text(item["text"], "annotation.text")
        evidence = _evidence_ids(item["evidence_segment_ids"], known_segments)
        return item, annotation_id, text, evidence

    agenda: list[MeetingAnnotation] = []
    if not isinstance(root["agenda"], list):
        raise IntakeFailure("MEETING_MANIFEST_SCHEMA_INVALID", "safety_gate", "agenda must be a list")
    for index, raw in enumerate(root["agenda"]):
        _item, annotation_id, text, evidence = common(
            raw,
            index,
            "agenda",
            {"id", "text", "evidence_segment_ids"},
        )
        agenda.append(MeetingAnnotation(annotation_id, text, evidence))

    decisions: list[MeetingAnnotation] = []
    if not isinstance(root["decisions"], list):
        raise IntakeFailure("MEETING_MANIFEST_SCHEMA_INVALID", "safety_gate", "decisions must be a list")
    for index, raw in enumerate(root["decisions"]):
        item, annotation_id, text, evidence = common(
            raw,
            index,
            "decisions",
            {"id", "text", "status", "evidence_segment_ids"},
        )
        status = _string(item["status"], "decision.status", maximum=64)
        if status not in DECISION_STATES:
            raise IntakeFailure("MEETING_ANNOTATION_INVALID", "safety_gate", "decision status invalid")
        decisions.append(MeetingAnnotation(annotation_id, text, evidence, status=status))

    actions: list[MeetingAnnotation] = []
    if not isinstance(root["action_items"], list):
        raise IntakeFailure("MEETING_MANIFEST_SCHEMA_INVALID", "safety_gate", "action_items must be a list")
    for index, raw in enumerate(root["action_items"]):
        item, annotation_id, text, evidence = common(
            raw,
            index,
            "action_items",
            {"id", "text", "status", "owner_speaker_label", "due_date", "evidence_segment_ids"},
        )
        status = _string(item["status"], "action.status", maximum=64)
        if status not in ACTION_STATES:
            raise IntakeFailure("MEETING_ANNOTATION_INVALID", "safety_gate", "action status invalid")
        owner_value = item["owner_speaker_label"]
        owner = None
        if owner_value is not None:
            owner = _string(owner_value, "action.owner_speaker_label", pattern=ALIAS_RE)
            if owner not in participants:
                raise IntakeFailure(
                    "MEETING_ACTION_OWNER_INVALID",
                    "safety_gate",
                    "action owner does not resolve to a participant alias",
                )
        due_value = item["due_date"]
        due = None
        if due_value is not None:
            due = _string(due_value, "action.due_date", maximum=10)
            try:
                date.fromisoformat(due)
            except ValueError as exc:
                raise IntakeFailure(
                    "MEETING_ACTION_DUE_DATE_INVALID",
                    "safety_gate",
                    "action due date is invalid",
                ) from exc
        actions.append(
            MeetingAnnotation(
                annotation_id,
                text,
                evidence,
                status=status,
                owner_speaker_label=owner,
                due_date=due,
            )
        )
    return tuple(agenda), tuple(decisions), tuple(actions)


def parse_manifest(
    data: bytes,
    transcript_segments: tuple[MeetingSegment, ...],
    *,
    max_transcript_bytes: int,
    max_participants: int,
    max_annotations: int,
    max_duration_ms: int,
) -> MeetingManifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise IntakeFailure("MEETING_MANIFEST_TOO_LARGE", "safety_gate", "manifest exceeds policy")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntakeFailure("MEETING_MANIFEST_INVALID", "safety_gate", "manifest JSON is invalid") from exc
    root = _mapping(payload, "root")
    _exact_keys(
        root,
        {
            "schema_version",
            "source_uri_sha256",
            "meeting",
            "transcript",
            "participants",
            "access",
            "annotations",
            "extraction",
        },
        "root",
    )
    if root["schema_version"] != MANIFEST_SCHEMA:
        raise IntakeFailure(
            "MEETING_MANIFEST_VERSION_UNSUPPORTED",
            "safety_gate",
            "manifest version unsupported",
        )
    source_hash = _string(root["source_uri_sha256"], "source_uri_sha256", pattern=HEX64_RE)

    meeting = _mapping(root["meeting"], "meeting")
    _exact_keys(
        meeting,
        {
            "meeting_id_sha256",
            "title_sha256",
            "platform",
            "scheduled_start",
            "scheduled_end",
            "actual_start",
            "actual_end",
        },
        "meeting",
    )
    meeting_hash = _string(meeting["meeting_id_sha256"], "meeting.meeting_id_sha256", pattern=HEX64_RE)
    title_hash = _string(meeting["title_sha256"], "meeting.title_sha256", pattern=HEX64_RE)
    platform = _string(meeting["platform"], "meeting.platform", maximum=64)
    if platform not in PLATFORMS:
        raise IntakeFailure("MEETING_PLATFORM_UNSUPPORTED", "safety_gate", "meeting platform unsupported")
    scheduled_start, scheduled_start_dt = _utc(meeting["scheduled_start"], "meeting.scheduled_start")
    scheduled_end, scheduled_end_dt = _utc(meeting["scheduled_end"], "meeting.scheduled_end")
    actual_start, actual_start_dt = _utc(meeting["actual_start"], "meeting.actual_start")
    actual_end, actual_end_dt = _utc(meeting["actual_end"], "meeting.actual_end")
    if scheduled_end_dt <= scheduled_start_dt or actual_end_dt <= actual_start_dt:
        raise IntakeFailure("MEETING_TIME_WINDOW_INVALID", "safety_gate", "meeting time window is invalid")
    duration_ms = int((actual_end_dt - actual_start_dt).total_seconds() * 1000)
    if duration_ms > max_duration_ms:
        raise IntakeFailure("MEETING_DURATION_LIMIT", "safety_gate", "meeting duration exceeds policy")

    transcript = _mapping(root["transcript"], "transcript")
    _exact_keys(transcript, {"path", "sha256", "byte_size", "language", "segments"}, "transcript")
    transcript_path = canonical_relative_path(_string(transcript["path"], "transcript.path"))
    transcript_hash = _string(transcript["sha256"], "transcript.sha256", pattern=HEX64_RE)
    transcript_size = _integer(
        transcript["byte_size"],
        "transcript.byte_size",
        minimum=1,
        maximum=max_transcript_bytes,
    )
    language = _string(transcript["language"], "transcript.language", pattern=LANGUAGE_RE)
    manifest_segments = transcript["segments"]
    if not isinstance(manifest_segments, list) or len(manifest_segments) != len(transcript_segments):
        raise IntakeFailure("MEETING_SEGMENT_MISMATCH", "safety_gate", "segment count differs")
    for index, (raw, parsed) in enumerate(zip(manifest_segments, transcript_segments, strict=True)):
        item = _mapping(raw, f"transcript.segments[{index}]")
        _exact_keys(
            item,
            {"id", "start_ms", "end_ms", "speaker_label", "text_sha256"},
            f"transcript.segments[{index}]",
        )
        observed = (
            _string(item["id"], "segment.id", pattern=SEGMENT_ID_RE),
            _integer(item["start_ms"], "segment.start_ms", minimum=0, maximum=max_duration_ms),
            _integer(item["end_ms"], "segment.end_ms", minimum=1, maximum=max_duration_ms),
            _string(item["speaker_label"], "segment.speaker_label", pattern=ALIAS_RE),
            _string(item["text_sha256"], "segment.text_sha256", pattern=HEX64_RE),
        )
        expected = (
            parsed.segment_id,
            parsed.start_ms,
            parsed.end_ms,
            parsed.speaker_label,
            parsed.text_sha256,
        )
        if observed != expected:
            raise IntakeFailure("MEETING_SEGMENT_MISMATCH", "safety_gate", "segment evidence differs")
        if parsed.end_ms > duration_ms:
            raise IntakeFailure(
                "MEETING_SEGMENT_OUT_OF_RANGE",
                "safety_gate",
                "segment exceeds actual meeting duration",
            )

    participants = _parse_participants(root["participants"], max_participants=max_participants)
    participant_labels = {item.speaker_label for item in participants}
    if any(segment.speaker_label not in participant_labels for segment in transcript_segments):
        raise IntakeFailure(
            "MEETING_SPEAKER_UNKNOWN",
            "safety_gate",
            "transcript speaker alias is not declared",
        )
    access = _parse_access(root["access"])
    verified_principals = {
        item.principal_sha256
        for item in participants
        if item.identity_status == "verified" and item.principal_sha256 is not None
    }
    if access.principal_hashes and not verified_principals.issubset(set(access.principal_hashes)):
        raise IntakeFailure(
            "MEETING_IDENTITY_ACL_MISMATCH",
            "safety_gate",
            "verified participant proof is outside meeting ACL evidence",
        )
    agenda, decisions, action_items = _parse_annotations(
        root["annotations"],
        known_segments={item.segment_id for item in transcript_segments},
        participants=participant_labels,
        max_annotations=max_annotations,
    )

    extraction = _mapping(root["extraction"], "extraction")
    _exact_keys(extraction, {"tool", "version", "transcript_origin"}, "extraction")
    extraction_tool = _string(extraction["tool"], "extraction.tool", pattern=SAFE_ID_RE)
    extraction_version = _string(extraction["version"], "extraction.version", pattern=SAFE_ID_RE)
    transcript_origin = _string(extraction["transcript_origin"], "extraction.transcript_origin", maximum=64)
    if transcript_origin not in TRANSCRIPT_ORIGINS:
        raise IntakeFailure(
            "MEETING_TRANSCRIPT_ORIGIN_INVALID",
            "safety_gate",
            "transcript origin is invalid",
        )

    return MeetingManifest(
        source_uri_sha256=source_hash,
        meeting_id_sha256=meeting_hash,
        title_sha256=title_hash,
        platform=platform,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        actual_start=actual_start,
        actual_end=actual_end,
        duration_ms=duration_ms,
        transcript_path=transcript_path,
        transcript_sha256=transcript_hash,
        transcript_byte_size=transcript_size,
        language=language,
        participants=participants,
        access=access,
        agenda=agenda,
        decisions=decisions,
        action_items=action_items,
        extraction_tool=extraction_tool,
        extraction_version=extraction_version,
        transcript_origin=transcript_origin,
        segments=transcript_segments,
        manifest_sha256=sha256_bytes(data),
    )


def _reject_symlink_components(allowed_root: Path, candidate: Path) -> None:
    absolute = candidate if candidate.is_absolute() else allowed_root / candidate
    try:
        relative = absolute.relative_to(allowed_root)
    except ValueError as exc:
        raise IntakeFailure("PATH_ESCAPE", "discover", "bundle escapes allowed root") from exc
    current = allowed_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise IntakeFailure("SYMLINK_ESCAPE", "discover", "bundle path contains symlink")


class LocalMeetingBundleReader:
    def __init__(self, allowed_root: Path) -> None:
        try:
            self.allowed_root = allowed_root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure("ALLOWED_ROOT_NOT_FOUND", "request", "allowed root not found") from exc
        if not self.allowed_root.is_dir():
            raise IntakeFailure("INVALID_ALLOWED_ROOT", "request", "allowed root must be a directory")

    def _root(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        _reject_symlink_components(self.allowed_root, candidate)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.allowed_root)
        except FileNotFoundError as exc:
            raise IntakeFailure("MEETING_BUNDLE_NOT_FOUND", "discover", "bundle not found") from exc
        except ValueError as exc:
            raise IntakeFailure("PATH_ESCAPE", "discover", "bundle escapes allowed root") from exc
        info = resolved.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise IntakeFailure("MEETING_BUNDLE_INVALID", "discover", "bundle must be a directory")
        return resolved

    def read(
        self,
        locator: str,
        *,
        max_transcript_bytes: int,
        max_segments: int,
        max_participants: int,
        max_annotations: int,
        max_duration_ms: int,
    ) -> MeetingBundle:
        root = self._root(locator)
        root_identity = FileIdentity(root, *self._identity_values(root))
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise IntakeFailure("SYMLINK_ESCAPE", "discover", "manifest must not be a symlink")
        manifest_bytes, manifest_identity = _read_regular_file(
            manifest_path,
            max_bytes=MAX_MANIFEST_BYTES,
        )
        try:
            preview = json.loads(manifest_bytes.decode("utf-8"))
            transcript_value = preview["transcript"]["path"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise IntakeFailure("MEETING_MANIFEST_INVALID", "safety_gate", "manifest JSON is invalid") from exc
        transcript_relative = canonical_relative_path(_string(transcript_value, "transcript.path"))
        transcript_path = root.joinpath(*PurePosixPath(transcript_relative).parts)
        if transcript_path == manifest_path:
            raise IntakeFailure("MEETING_BUNDLE_PATH_COLLISION", "safety_gate", "bundle paths collide")
        _reject_symlink_components(self.allowed_root, transcript_path)
        transcript_bytes, transcript_identity = _read_regular_file(
            transcript_path,
            max_bytes=max_transcript_bytes,
        )
        segments = parse_transcript(transcript_bytes, max_segments=max_segments)
        manifest = parse_manifest(
            manifest_bytes,
            segments,
            max_transcript_bytes=max_transcript_bytes,
            max_participants=max_participants,
            max_annotations=max_annotations,
            max_duration_ms=max_duration_ms,
        )
        if len(transcript_bytes) != manifest.transcript_byte_size or sha256_bytes(
            transcript_bytes
        ) != manifest.transcript_sha256:
            raise IntakeFailure(
                "MEETING_TRANSCRIPT_HASH_MISMATCH",
                "safety_gate",
                "transcript bytes differ from manifest",
            )
        for identity in (root_identity, manifest_identity, transcript_identity):
            _verify_identity(identity)
        return MeetingBundle(
            root,
            root_identity,
            manifest_identity,
            transcript_identity,
            manifest_bytes,
            transcript_bytes,
            manifest,
        )

    @staticmethod
    def _identity_values(path: Path) -> tuple[int, int, int, int]:
        info = path.stat(follow_symlinks=False)
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _quoted_lines(text: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in text.rstrip("\n").split("\n")]


def render_derivative(manifest: MeetingManifest) -> bytes:
    verified = sum(item.identity_status == "verified" for item in manifest.participants)
    unverified = len(manifest.participants) - verified
    lines = [
        "# Meeting Transcript",
        "",
        "## Meeting Evidence",
        "",
        f"- Platform: `{manifest.platform}`",
        f"- Scheduled: `{manifest.scheduled_start}` to `{manifest.scheduled_end}`",
        f"- Actual: `{manifest.actual_start}` to `{manifest.actual_end}`",
        f"- Duration: `{format_timestamp(manifest.duration_ms)}`",
        f"- Language: `{manifest.language}`",
        f"- Transcript origin: `{manifest.transcript_origin}`",
        f"- Extraction: `{manifest.extraction_tool}/{manifest.extraction_version}`",
        f"- Participant aliases: `{len(manifest.participants)}`",
        f"- Verified alias proofs: `{verified}`",
        f"- Unverified aliases: `{unverified}`",
        "",
        "Identity note: speaker aliases are evidence labels, not human names. An unverified alias must not be treated as a real-person identity.",
        "",
        "## Participant Alias Evidence",
        "",
    ]
    for participant in manifest.participants:
        lines.append(
            f"- `{participant.speaker_label}`: role `{participant.role}`, attendance `{participant.attendance}`, identity `{participant.identity_status}`"
        )
    lines.extend(["", "## Declared Agenda", ""])
    if not manifest.agenda:
        lines.append("No declared agenda items.")
    for item in manifest.agenda:
        lines.extend(
            [
                f"### {item.annotation_id}",
                "",
                f"Evidence segments: `{', '.join(item.evidence_segment_ids)}`",
                "",
                *_quoted_lines(item.text),
                "",
            ]
        )
    lines.extend(["", "## Declared Decisions", ""])
    if not manifest.decisions:
        lines.append("No declared decisions.")
    for item in manifest.decisions:
        lines.extend(
            [
                f"### {item.annotation_id} [{item.status}]",
                "",
                f"Evidence segments: `{', '.join(item.evidence_segment_ids)}`",
                "",
                *_quoted_lines(item.text),
                "",
            ]
        )
    lines.extend(["", "## Declared Action Items", ""])
    if not manifest.action_items:
        lines.append("No declared action items.")
    for item in manifest.action_items:
        owner = item.owner_speaker_label or "unassigned"
        due = item.due_date or "unspecified"
        lines.extend(
            [
                f"### {item.annotation_id} [{item.status}]",
                "",
                f"Owner alias: `{owner}`",
                f"Due date: `{due}`",
                f"Evidence segments: `{', '.join(item.evidence_segment_ids)}`",
                "",
                *_quoted_lines(item.text),
                "",
            ]
        )
    lines.extend(["", "## Transcript", ""])
    for segment in manifest.segments:
        lines.extend(
            [
                f"### [{format_timestamp(segment.start_ms)} --> {format_timestamp(segment.end_ms)}] {segment.speaker_label} #{segment.segment_id}",
                "",
                segment.text.rstrip("\n"),
                "",
            ]
        )
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
