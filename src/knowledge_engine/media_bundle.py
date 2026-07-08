from __future__ import annotations

import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .intake_v1 import IntakeFailure, canonical_json_bytes
from .storage import sha256_bytes

MANIFEST_SCHEMA = "media-derived-markdown/v1"
MAX_MANIFEST_BYTES = 1024 * 1024
DEFAULT_MAX_MEDIA_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_SEGMENTS = 20_000
DEFAULT_MAX_DURATION_MS = 24 * 60 * 60 * 1000
HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.+/-]{1,128}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,4}$")
SPEAKER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
TIMECODE_RE = re.compile(
    r"^## \[(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]"
    r"(?: ([A-Za-z0-9_.-]{1,64}))?$"
)
SUPPORTED_MEDIA = {
    ".mp3": {"audio/mpeg"},
    ".mp4": {"video/mp4"},
    ".m4a": {"audio/mp4"},
    ".wav": {"audio/wav"},
    ".flac": {"audio/flac"},
    ".ogg": {"audio/ogg", "video/ogg"},
    ".webm": {"audio/webm", "video/webm"},
}


@dataclass(frozen=True)
class FileIdentity:
    path: Path
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class MediaSegment:
    start_ms: int
    end_ms: int
    text_sha256: str
    speaker: str | None
    text: str


@dataclass(frozen=True)
class MediaManifest:
    source_uri_sha256: str
    media_path: str
    media_sha256: str
    media_byte_size: int
    media_type: str
    duration_ms: int
    transcript_path: str
    transcript_sha256: str
    transcript_byte_size: int
    language: str
    acquisition_tool: str
    acquisition_version: str
    transcription_tool: str
    transcription_model: str
    transcription_version: str
    segments: tuple[MediaSegment, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class MediaBundle:
    bundle_root: Path
    bundle_identity: FileIdentity
    manifest_identity: FileIdentity
    media_identity: FileIdentity
    transcript_identity: FileIdentity
    manifest: MediaManifest
    media_bytes: bytes
    transcript_bytes: bytes


def canonical_relative_path(value: str) -> str:
    if not value or value.strip() != value or "\\" in value or "\x00" in value:
        raise IntakeFailure("INVALID_BUNDLE_PATH", "request", "bundle path is not canonical")
    if any(ord(char) < 32 for char in value):
        raise IntakeFailure("INVALID_BUNDLE_PATH", "request", "bundle path has control bytes")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IntakeFailure("INVALID_BUNDLE_PATH", "request", "bundle path is not canonical")
    if path.as_posix() != value or value.endswith("/"):
        raise IntakeFailure("INVALID_BUNDLE_PATH", "request", "bundle path is not canonical")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} fields are invalid",
        )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} must be an object",
        )
    return value


def _required_string(value: Any, field: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} is invalid",
        )
    if pattern is not None and pattern.fullmatch(value) is None:
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} has invalid syntax",
        )
    return value


def _required_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            f"manifest {field} is outside policy",
        )
    return value


def _canonical_segment_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = normalized.strip("\n")
    if not normalized.strip():
        raise IntakeFailure("MEDIA_SEGMENT_EMPTY", "normalize", "media segment text is empty")
    return normalized + "\n"


def _timestamp_ms(groups: tuple[str, str, str, str]) -> int:
    hours, minutes, seconds, milliseconds = (int(value) for value in groups)
    if minutes > 59 or seconds > 59:
        raise IntakeFailure("MEDIA_TIMECODE_INVALID", "normalize", "timecode is invalid")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def parse_transcript_markdown(data: bytes, *, max_segments: int) -> tuple[MediaSegment, ...]:
    if b"\x00" in data:
        raise IntakeFailure("MEDIA_TRANSCRIPT_BINARY", "safety_gate", "transcript has NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeFailure(
            "MEDIA_TRANSCRIPT_INVALID_UTF8",
            "safety_gate",
            "transcript must be UTF-8",
        ) from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntakeFailure("EMPTY_SOURCE", "normalize", "transcript is empty")
    lines = text.split("\n")
    headings: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = TIMECODE_RE.fullmatch(line)
        if match is not None:
            headings.append((index, match))
    if not headings or headings[0][0] != 0:
        raise IntakeFailure(
            "MEDIA_TRANSCRIPT_FORMAT_INVALID",
            "normalize",
            "transcript must begin with a timecode heading",
        )
    if len(headings) > max_segments:
        raise IntakeFailure(
            "MEDIA_SEGMENT_LIMIT",
            "normalize",
            "transcript exceeds segment policy",
        )
    segments: list[MediaSegment] = []
    for offset, (line_index, match) in enumerate(headings):
        next_index = headings[offset + 1][0] if offset + 1 < len(headings) else len(lines)
        content_lines = lines[line_index + 1 : next_index]
        while content_lines and content_lines[0] == "":
            content_lines.pop(0)
        while content_lines and content_lines[-1] == "":
            content_lines.pop()
        canonical_text = _canonical_segment_text("\n".join(content_lines))
        start_ms = _timestamp_ms(match.groups()[0:4])
        end_ms = _timestamp_ms(match.groups()[4:8])
        speaker = match.group(9)
        segments.append(
            MediaSegment(
                start_ms=start_ms,
                end_ms=end_ms,
                text_sha256=sha256_bytes(canonical_text.encode("utf-8")),
                speaker=speaker,
                text=canonical_text,
            )
        )
    return tuple(segments)


def _parse_manifest_segment(value: Any, index: int) -> tuple[int, int, str, str | None]:
    item = _mapping(value, f"transcript.segments[{index}]")
    allowed = {"start_ms", "end_ms", "text_sha256", "speaker"}
    required = {"start_ms", "end_ms", "text_sha256"}
    if not required.issubset(item) or not set(item).issubset(allowed):
        raise IntakeFailure(
            "MEDIA_MANIFEST_SCHEMA_INVALID",
            "safety_gate",
            "manifest segment fields are invalid",
        )
    start_ms = _required_int(item["start_ms"], "segment.start_ms", minimum=0, maximum=DEFAULT_MAX_DURATION_MS)
    end_ms = _required_int(item["end_ms"], "segment.end_ms", minimum=1, maximum=DEFAULT_MAX_DURATION_MS)
    text_hash = _required_string(item["text_sha256"], "segment.text_sha256", pattern=HEX64_RE)
    speaker_value = item.get("speaker")
    speaker = None
    if speaker_value is not None:
        speaker = _required_string(speaker_value, "segment.speaker", pattern=SPEAKER_RE)
    return start_ms, end_ms, text_hash, speaker


def parse_manifest(
    data: bytes,
    transcript_segments: tuple[MediaSegment, ...],
    *,
    max_media_bytes: int,
    max_transcript_bytes: int,
    max_segments: int,
    max_duration_ms: int,
) -> MediaManifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise IntakeFailure("MEDIA_MANIFEST_TOO_LARGE", "safety_gate", "manifest exceeds policy")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntakeFailure("MEDIA_MANIFEST_INVALID", "safety_gate", "manifest JSON is invalid") from exc
    root = _mapping(payload, "root")
    _exact_keys(
        root,
        {"schema_version", "source_uri_sha256", "media", "transcript", "acquisition", "transcription"},
        "root",
    )
    if root["schema_version"] != MANIFEST_SCHEMA:
        raise IntakeFailure("MEDIA_MANIFEST_VERSION_UNSUPPORTED", "safety_gate", "manifest version unsupported")
    source_hash = _required_string(root["source_uri_sha256"], "source_uri_sha256", pattern=HEX64_RE)

    media = _mapping(root["media"], "media")
    _exact_keys(media, {"path", "sha256", "byte_size", "media_type", "duration_ms"}, "media")
    media_path = canonical_relative_path(_required_string(media["path"], "media.path"))
    media_hash = _required_string(media["sha256"], "media.sha256", pattern=HEX64_RE)
    media_size = _required_int(media["byte_size"], "media.byte_size", minimum=1, maximum=max_media_bytes)
    media_type = _required_string(media["media_type"], "media.media_type")
    duration_ms = _required_int(media["duration_ms"], "media.duration_ms", minimum=1, maximum=max_duration_ms)

    transcript = _mapping(root["transcript"], "transcript")
    _exact_keys(transcript, {"path", "sha256", "byte_size", "language", "segments"}, "transcript")
    transcript_path = canonical_relative_path(_required_string(transcript["path"], "transcript.path"))
    transcript_hash = _required_string(transcript["sha256"], "transcript.sha256", pattern=HEX64_RE)
    transcript_size = _required_int(
        transcript["byte_size"],
        "transcript.byte_size",
        minimum=1,
        maximum=max_transcript_bytes,
    )
    language = _required_string(transcript["language"], "transcript.language", pattern=LANGUAGE_RE)
    segment_values = transcript["segments"]
    if not isinstance(segment_values, list) or not 1 <= len(segment_values) <= max_segments:
        raise IntakeFailure("MEDIA_SEGMENT_LIMIT", "safety_gate", "manifest segment count invalid")
    if len(segment_values) != len(transcript_segments):
        raise IntakeFailure("MEDIA_SEGMENT_MISMATCH", "safety_gate", "segment counts differ")
    previous_end = 0
    bound_segments: list[MediaSegment] = []
    for index, (manifest_value, parsed) in enumerate(zip(segment_values, transcript_segments, strict=True)):
        start_ms, end_ms, text_hash, speaker = _parse_manifest_segment(manifest_value, index)
        if end_ms <= start_ms or start_ms < previous_end:
            raise IntakeFailure("MEDIA_SEGMENT_OVERLAP", "safety_gate", "segments overlap or reverse")
        if end_ms > duration_ms:
            raise IntakeFailure("MEDIA_SEGMENT_OUT_OF_RANGE", "safety_gate", "segment exceeds duration")
        if (start_ms, end_ms, text_hash, speaker) != (
            parsed.start_ms,
            parsed.end_ms,
            parsed.text_sha256,
            parsed.speaker,
        ):
            raise IntakeFailure("MEDIA_SEGMENT_MISMATCH", "safety_gate", "segment evidence differs")
        previous_end = end_ms
        bound_segments.append(parsed)

    acquisition = _mapping(root["acquisition"], "acquisition")
    _exact_keys(acquisition, {"tool", "version"}, "acquisition")
    acquisition_tool = _required_string(acquisition["tool"], "acquisition.tool", pattern=SAFE_ID_RE)
    acquisition_version = _required_string(acquisition["version"], "acquisition.version", pattern=SAFE_ID_RE)

    transcription = _mapping(root["transcription"], "transcription")
    _exact_keys(transcription, {"tool", "model", "version"}, "transcription")
    transcription_tool = _required_string(transcription["tool"], "transcription.tool", pattern=SAFE_ID_RE)
    transcription_model = _required_string(transcription["model"], "transcription.model", pattern=SAFE_ID_RE)
    transcription_version = _required_string(transcription["version"], "transcription.version", pattern=SAFE_ID_RE)

    return MediaManifest(
        source_uri_sha256=source_hash,
        media_path=media_path,
        media_sha256=media_hash,
        media_byte_size=media_size,
        media_type=media_type,
        duration_ms=duration_ms,
        transcript_path=transcript_path,
        transcript_sha256=transcript_hash,
        transcript_byte_size=transcript_size,
        language=language,
        acquisition_tool=acquisition_tool,
        acquisition_version=acquisition_version,
        transcription_tool=transcription_tool,
        transcription_model=transcription_model,
        transcription_version=transcription_version,
        segments=tuple(bound_segments),
        manifest_sha256=sha256_bytes(data),
    )


def _observed_media_type(path: str, data: bytes) -> set[str]:
    suffix = PurePosixPath(path).suffix.lower()
    allowed = SUPPORTED_MEDIA.get(suffix)
    if allowed is None:
        raise IntakeFailure("MEDIA_TYPE_UNSUPPORTED", "safety_gate", "media extension unsupported")
    signature_ok = False
    if suffix == ".mp3":
        signature_ok = data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    elif suffix in {".mp4", ".m4a"}:
        signature_ok = len(data) >= 12 and data[4:8] == b"ftyp"
    elif suffix == ".wav":
        signature_ok = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    elif suffix == ".flac":
        signature_ok = data.startswith(b"fLaC")
    elif suffix == ".ogg":
        signature_ok = data.startswith(b"OggS")
    elif suffix == ".webm":
        signature_ok = data.startswith(b"\x1aE\xdf\xa3")
    if not signature_ok:
        raise IntakeFailure("MEDIA_SIGNATURE_MISMATCH", "safety_gate", "media signature invalid")
    return allowed


def validate_media(manifest: MediaManifest, media_bytes: bytes, transcript_bytes: bytes) -> None:
    if len(media_bytes) != manifest.media_byte_size or sha256_bytes(media_bytes) != manifest.media_sha256:
        raise IntakeFailure("MEDIA_HASH_MISMATCH", "safety_gate", "media bytes differ from manifest")
    if len(transcript_bytes) != manifest.transcript_byte_size or sha256_bytes(
        transcript_bytes
    ) != manifest.transcript_sha256:
        raise IntakeFailure(
            "MEDIA_TRANSCRIPT_HASH_MISMATCH",
            "safety_gate",
            "transcript bytes differ from manifest",
        )
    allowed_types = _observed_media_type(manifest.media_path, media_bytes)
    if manifest.media_type not in allowed_types:
        raise IntakeFailure("MEDIA_TYPE_MISMATCH", "safety_gate", "declared media type is invalid")


def _identity(path: Path) -> FileIdentity:
    info = path.stat(follow_symlinks=False)
    return FileIdentity(path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _verify_identity(identity: FileIdentity) -> None:
    try:
        current = identity.path.stat(follow_symlinks=False)
    except OSError as exc:
        raise IntakeFailure("MEDIA_BUNDLE_MUTATED", "acquire", "bundle file disappeared") from exc
    if (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
    ) != (identity.device, identity.inode, identity.size, identity.modified_ns):
        raise IntakeFailure("MEDIA_BUNDLE_MUTATED", "acquire", "bundle file changed during read")


def _read_regular_file(path: Path, *, max_bytes: int) -> tuple[bytes, FileIdentity]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise IntakeFailure("MEDIA_BUNDLE_FILE_INVALID", "acquire", "bundle file cannot be opened") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise IntakeFailure(
                "MEDIA_BUNDLE_FILE_INVALID",
                "acquire",
                "bundle file must be one regular non-hardlinked file",
            )
        if before.st_size < 1 or before.st_size > max_bytes:
            raise IntakeFailure("MEDIA_BUNDLE_FILE_SIZE", "acquire", "bundle file size outside policy")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise IntakeFailure("MEDIA_BUNDLE_FILE_SIZE", "acquire", "bundle file exceeds policy")
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise IntakeFailure("MEDIA_BUNDLE_MUTATED", "acquire", "bundle file changed during read")
        data = b"".join(chunks)
        if len(data) != before.st_size:
            raise IntakeFailure("MEDIA_BUNDLE_TRUNCATED", "acquire", "bundle file read was truncated")
        return data, FileIdentity(path, before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    finally:
        os.close(descriptor)


class LocalMediaBundleReader:
    def __init__(self, allowed_root: Path) -> None:
        try:
            self.allowed_root = allowed_root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure("ALLOWED_ROOT_NOT_FOUND", "request", "allowed root not found") from exc
        if not self.allowed_root.is_dir():
            raise IntakeFailure("INVALID_ALLOWED_ROOT", "request", "allowed root must be a directory")

    def _reject_symlink_components(self, candidate: Path) -> None:
        absolute = candidate if candidate.is_absolute() else self.allowed_root / candidate
        try:
            relative = absolute.relative_to(self.allowed_root)
        except ValueError as exc:
            raise IntakeFailure("PATH_ESCAPE", "discover", "bundle escapes allowed root") from exc
        current = self.allowed_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise IntakeFailure("SYMLINK_ESCAPE", "discover", "bundle path contains symlink")

    def bundle_root(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        self._reject_symlink_components(candidate)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.allowed_root)
        except FileNotFoundError as exc:
            raise IntakeFailure("MEDIA_BUNDLE_NOT_FOUND", "discover", "bundle not found") from exc
        except ValueError as exc:
            raise IntakeFailure("PATH_ESCAPE", "discover", "bundle escapes allowed root") from exc
        info = resolved.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 1:
            raise IntakeFailure("MEDIA_BUNDLE_INVALID", "discover", "bundle must be a directory")
        return resolved

    def read(
        self,
        locator: str,
        *,
        max_media_bytes: int,
        max_transcript_bytes: int,
        max_segments: int,
        max_duration_ms: int,
    ) -> MediaBundle:
        root = self.bundle_root(locator)
        root_identity = _identity(root)
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise IntakeFailure("SYMLINK_ESCAPE", "discover", "manifest must not be a symlink")
        manifest_bytes, manifest_identity = _read_regular_file(
            manifest_path,
            max_bytes=MAX_MANIFEST_BYTES,
        )
        try:
            preview = json.loads(manifest_bytes.decode("utf-8"))
            transcript_path_value = preview["transcript"]["path"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise IntakeFailure("MEDIA_MANIFEST_INVALID", "safety_gate", "manifest JSON is invalid") from exc
        transcript_relative = canonical_relative_path(
            _required_string(transcript_path_value, "transcript.path")
        )
        transcript_path = root.joinpath(*PurePosixPath(transcript_relative).parts)
        self._reject_symlink_components(transcript_path)
        transcript_bytes, transcript_identity = _read_regular_file(
            transcript_path,
            max_bytes=max_transcript_bytes,
        )
        transcript_segments = parse_transcript_markdown(
            transcript_bytes,
            max_segments=max_segments,
        )
        manifest = parse_manifest(
            manifest_bytes,
            transcript_segments,
            max_media_bytes=max_media_bytes,
            max_transcript_bytes=max_transcript_bytes,
            max_segments=max_segments,
            max_duration_ms=max_duration_ms,
        )
        media_path = root.joinpath(*PurePosixPath(manifest.media_path).parts)
        if media_path == transcript_path or media_path == manifest_path or transcript_path == manifest_path:
            raise IntakeFailure("MEDIA_BUNDLE_PATH_COLLISION", "safety_gate", "bundle paths collide")
        self._reject_symlink_components(media_path)
        media_bytes, media_identity = _read_regular_file(media_path, max_bytes=max_media_bytes)
        validate_media(manifest, media_bytes, transcript_bytes)
        for identity in (root_identity, manifest_identity, media_identity, transcript_identity):
            _verify_identity(identity)
        return MediaBundle(
            bundle_root=root,
            bundle_identity=root_identity,
            manifest_identity=manifest_identity,
            media_identity=media_identity,
            transcript_identity=transcript_identity,
            manifest=manifest,
            media_bytes=media_bytes,
            transcript_bytes=transcript_bytes,
        )


def format_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def render_derivative(manifest: MediaManifest) -> bytes:
    lines = [
        "# Media-Derived Transcript",
        "",
        f"- Media type: `{manifest.media_type}`",
        f"- Duration: `{format_timestamp(manifest.duration_ms)}`",
        f"- Language: `{manifest.language}`",
        f"- Acquisition: `{manifest.acquisition_tool}/{manifest.acquisition_version}`",
        (
            "- Transcription: "
            f"`{manifest.transcription_tool}/{manifest.transcription_model}/"
            f"{manifest.transcription_version}`"
        ),
        "",
    ]
    for segment in manifest.segments:
        heading = (
            f"## [{format_timestamp(segment.start_ms)} --> "
            f"{format_timestamp(segment.end_ms)}]"
        )
        if segment.speaker is not None:
            heading += f" {segment.speaker}"
        lines.extend([heading, "", segment.text.rstrip("\n"), ""])
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
