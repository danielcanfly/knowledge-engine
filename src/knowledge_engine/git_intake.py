from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
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

CONNECTOR_TYPE = "git_repository_path"
CONNECTOR_VERSION = "git-path/1.0.0"
MARKDOWN_NORMALIZER_ID = "git_markdown"
TEXT_NORMALIZER_ID = "git_text_to_markdown"
NORMALIZER_VERSION = "1.0.0"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_COMMAND_STDOUT = 64 * 1024
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
ALLOWED_MODES = {"100644", "100755"}
LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".ini": "ini",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "jsx",
    ".kt": "kotlin",
    ".md": "markdown",
    ".markdown": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass(frozen=True)
class GitPathRequest:
    repository_locator: str
    tree_path: str
    commit_sha: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    git_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def validate(self) -> None:
        if not self.repository_locator.strip():
            raise IntakeFailure("INVALID_LOCATOR", "request", "repository locator is required")
        canonical_tree_path(self.tree_path)
        if not (SHA1_RE.fullmatch(self.commit_sha) or SHA256_RE.fullmatch(self.commit_sha)):
            raise IntakeFailure(
                "GIT_IMMUTABLE_COMMIT_REQUIRED",
                "request",
                "commit_sha must be a full lowercase SHA-1 or SHA-256 object ID",
            )
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
        if self.max_bytes < 1 or self.max_bytes > 100 * 1024 * 1024:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_bytes must be between 1 and 104857600",
            )
        if not 0 < self.git_timeout_seconds <= 60:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "git_timeout_seconds must be between 0 and 60",
            )

    def attempt_id(self) -> str:
        seed = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "repository_locator": self.repository_locator,
            "tree_path": self.tree_path,
            "commit_sha": self.commit_sha,
            "retrieved_at": self.retrieved_at,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "source_id": self.source_id,
            "parent_snapshot": self.parent_snapshot,
            "max_bytes": self.max_bytes,
            "git_timeout_seconds": self.git_timeout_seconds,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(seed))[:32]


@dataclass(frozen=True)
class GitRepository:
    root: Path
    git_dir: Path
    object_format: str
    git_version: str
    identity: tuple[int, int]
    git_dir_identity: tuple[int, int]


@dataclass(frozen=True)
class GitTreeEntry:
    mode: str
    object_type: str
    object_id: str
    tree_path: str
    byte_size: int


@dataclass(frozen=True)
class GitAcquisition:
    canonical_locator: str
    original_uri: str
    source_version: str
    commit_sha: str
    repository: GitRepository
    entry: GitTreeEntry
    data: bytes


@dataclass(frozen=True)
class GitCommandPolicy:
    hooks_enabled: bool = False
    credential_helpers_enabled: bool = False
    external_protocols_enabled: bool = False
    lazy_fetch_enabled: bool = False
    replace_objects_enabled: bool = False
    stdin_enabled: bool = False
    working_tree_read: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


AfterBlobHook = Callable[[], None]


def canonical_tree_path(value: str) -> str:
    if not value or value.strip() != value:
        raise IntakeFailure("INVALID_GIT_PATH", "request", "tree path is required")
    if "\\" in value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise IntakeFailure(
            "INVALID_GIT_PATH",
            "request",
            "tree path contains forbidden characters",
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise IntakeFailure("INVALID_GIT_PATH", "request", "tree path must be canonical")
    canonical = path.as_posix()
    if canonical != value or canonical.endswith("/"):
        raise IntakeFailure("INVALID_GIT_PATH", "request", "tree path must be canonical")
    return canonical


def _normalise_text(data: bytes) -> str:
    if b"\x00" in data:
        raise IntakeFailure("GIT_BINARY_BLOB", "safety_gate", "Git blob contains NUL bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeFailure(
            "GIT_INVALID_UTF8",
            "safety_gate",
            "Git blob must be UTF-8 text",
        ) from exc
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        raise IntakeFailure("EMPTY_SOURCE", "normalize", "Git blob is empty")
    if not text.endswith("\n"):
        text += "\n"
    return text


def _fence_for(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _normalise_git_blob(tree_path: str, commit_sha: str, object_id: str, data: bytes) -> tuple[bytes, str]:
    text = _normalise_text(data)
    suffix = PurePosixPath(tree_path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return text.encode("utf-8"), MARKDOWN_NORMALIZER_ID
    language = LANGUAGE_BY_SUFFIX.get(suffix, "text")
    fence = _fence_for(text)
    rendered = (
        "# Git Repository Path\n\n"
        f"- Path: `{tree_path}`\n"
        f"- Commit: `{commit_sha}`\n"
        f"- Blob: `{object_id}`\n\n"
        f"{fence}{language}\n{text}{fence}\n"
    )
    return rendered.encode("utf-8"), TEXT_NORMALIZER_ID


class GitRunner:
    def __init__(self, *, timeout_seconds: float) -> None:
        executable = shutil.which("git")
        if executable is None:
            raise IntakeFailure("GIT_UNAVAILABLE", "discover", "Git executable is unavailable")
        self.executable = str(Path(executable).resolve())
        self.timeout_seconds = timeout_seconds

    def _environment(self, home: Path) -> dict[str, str]:
        return {
            "PATH": os.path.dirname(self.executable),
            "HOME": str(home),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": os.devnull,
            "SSH_ASKPASS": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }

    def run(
        self,
        repository: Path,
        arguments: Sequence[str],
        *,
        max_stdout: int = MAX_COMMAND_STDOUT,
        stage: str = "acquire",
    ) -> bytes:
        command = [
            self.executable,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.file.allow=never",
            "-C",
            str(repository),
            *arguments,
        ]
        with tempfile.TemporaryDirectory(prefix="knowledge-git-home-") as temporary:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self._environment(Path(temporary)),
                    close_fds=True,
                )
            except OSError as exc:
                raise IntakeFailure(
                    "GIT_COMMAND_FAILED",
                    stage,
                    "Git command could not start",
                ) from exc
            assert process.stdout is not None
            try:
                stdout = process.stdout.read(max_stdout + 1)
                if len(stdout) > max_stdout:
                    process.kill()
                    process.wait()
                    raise IntakeFailure(
                        "GIT_OUTPUT_LIMIT",
                        stage,
                        "Git command output exceeds policy",
                    )
                return_code = process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise IntakeFailure(
                    "GIT_TIMEOUT",
                    stage,
                    "Git command exceeded wall-clock policy",
                    transient=True,
                ) from exc
        if return_code != 0:
            raise IntakeFailure("GIT_COMMAND_FAILED", stage, "Git command failed")
        return stdout


class LocalGitPathConnector:
    def __init__(
        self,
        allowed_root: Path,
        *,
        runner: GitRunner,
        after_blob_hook: AfterBlobHook | None = None,
    ) -> None:
        self.allowed_root = allowed_root.resolve(strict=True)
        if not self.allowed_root.is_dir():
            raise ValueError("allowed_root must be a directory")
        self.runner = runner
        self.after_blob_hook = after_blob_hook

    def canonicalize_repository(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure(
                "GIT_REPOSITORY_NOT_FOUND",
                "discover",
                "Git repository does not exist",
            ) from exc
        try:
            resolved.relative_to(self.allowed_root)
        except ValueError as exc:
            raise IntakeFailure(
                "PATH_ESCAPE",
                "discover",
                "repository escapes the allowed root",
            ) from exc
        if not resolved.is_dir():
            raise IntakeFailure(
                "GIT_REPOSITORY_INVALID",
                "discover",
                "repository locator is not a directory",
            )
        return resolved

    def inspect_repository(self, root: Path) -> GitRepository:
        if self.runner.run(root, ["rev-parse", "--is-bare-repository"], stage="discover").strip() != b"false":
            raise IntakeFailure(
                "GIT_BARE_REPOSITORY_UNSUPPORTED",
                "discover",
                "bare repositories are not supported",
            )
        top_level = Path(
            self.runner.run(root, ["rev-parse", "--show-toplevel"], stage="discover")
            .decode("utf-8")
            .strip()
        ).resolve(strict=True)
        if top_level != root:
            raise IntakeFailure(
                "GIT_REPOSITORY_ROOT_REQUIRED",
                "discover",
                "repository locator must be the worktree root",
            )
        git_dir = Path(
            self.runner.run(root, ["rev-parse", "--absolute-git-dir"], stage="discover")
            .decode("utf-8")
            .strip()
        ).resolve(strict=True)
        try:
            git_dir.relative_to(root)
        except ValueError as exc:
            raise IntakeFailure(
                "GIT_EXTERNAL_DIRECTORY",
                "discover",
                "Git metadata directory must remain inside repository root",
            ) from exc
        alternates = git_dir / "objects" / "info" / "alternates"
        if alternates.exists() and alternates.read_bytes().strip():
            raise IntakeFailure(
                "GIT_EXTERNAL_OBJECT_STORE",
                "discover",
                "Git object alternates are forbidden",
            )
        object_format = (
            self.runner.run(root, ["rev-parse", "--show-object-format"], stage="discover")
            .decode("ascii")
            .strip()
        )
        if object_format not in {"sha1", "sha256"}:
            raise IntakeFailure(
                "GIT_OBJECT_FORMAT_UNSUPPORTED",
                "discover",
                "Git object format is unsupported",
            )
        git_version = (
            self.runner.run(root, ["--version"], stage="discover").decode("ascii").strip()
        )
        root_stat = root.stat()
        git_dir_stat = git_dir.stat()
        return GitRepository(
            root=root,
            git_dir=git_dir,
            object_format=object_format,
            git_version=git_version,
            identity=(root_stat.st_dev, root_stat.st_ino),
            git_dir_identity=(git_dir_stat.st_dev, git_dir_stat.st_ino),
        )

    def acquire(self, repository: GitRepository, request: GitPathRequest) -> GitAcquisition:
        expected_pattern = SHA1_RE if repository.object_format == "sha1" else SHA256_RE
        if expected_pattern.fullmatch(request.commit_sha) is None:
            raise IntakeFailure(
                "GIT_COMMIT_FORMAT_MISMATCH",
                "discover",
                "commit SHA does not match repository object format",
            )
        commit = request.commit_sha
        try:
            resolved_commit = (
                self.runner.run(
                    repository.root,
                    ["rev-parse", "--verify", f"{commit}^{{commit}}"],
                    stage="discover",
                )
                .decode("ascii")
                .strip()
            )
        except IntakeFailure as exc:
            raise IntakeFailure(
                "GIT_COMMIT_NOT_FOUND",
                "discover",
                "commit is unavailable in local repository",
            ) from exc
        if resolved_commit != commit:
            raise IntakeFailure(
                "GIT_COMMIT_MISMATCH",
                "discover",
                "resolved commit differs from requested immutable commit",
            )

        tree_path = canonical_tree_path(request.tree_path)
        raw_entry = self.runner.run(
            repository.root,
            ["ls-tree", "-z", "--full-tree", commit, "--", tree_path],
            stage="discover",
        )
        records = [item for item in raw_entry.split(b"\x00") if item]
        if len(records) != 1:
            code = "GIT_PATH_NOT_FOUND" if not records else "GIT_PATH_AMBIGUOUS"
            raise IntakeFailure(code, "discover", "Git tree path did not resolve to one object")
        try:
            metadata, encoded_path = records[0].split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            observed_path = encoded_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise IntakeFailure(
                "GIT_TREE_PROTOCOL_ERROR",
                "discover",
                "Git tree response is invalid",
            ) from exc
        if observed_path != tree_path:
            raise IntakeFailure(
                "GIT_PATH_MISMATCH",
                "discover",
                "Git returned a different tree path",
            )
        if mode == "040000" or object_type == "tree":
            raise IntakeFailure("GIT_PATH_IS_DIRECTORY", "discover", "Git path is a directory")
        if mode == "120000":
            raise IntakeFailure("GIT_SYMLINK_FORBIDDEN", "discover", "Git symlink is forbidden")
        if mode == "160000" or object_type == "commit":
            raise IntakeFailure("GIT_SUBMODULE_FORBIDDEN", "discover", "Git submodule is forbidden")
        if mode not in ALLOWED_MODES or object_type != "blob":
            raise IntakeFailure(
                "GIT_OBJECT_TYPE_UNSUPPORTED",
                "discover",
                "Git object mode or type is unsupported",
            )
        if expected_pattern.fullmatch(object_id) is None:
            raise IntakeFailure(
                "GIT_TREE_PROTOCOL_ERROR",
                "discover",
                "Git blob object ID has invalid format",
            )
        try:
            byte_size = int(
                self.runner.run(
                    repository.root,
                    ["cat-file", "-s", object_id],
                    stage="acquire",
                )
                .decode("ascii")
                .strip()
            )
        except ValueError as exc:
            raise IntakeFailure(
                "GIT_OBJECT_SIZE_INVALID",
                "acquire",
                "Git blob size is invalid",
            ) from exc
        if byte_size < 1:
            raise IntakeFailure("EMPTY_SOURCE", "acquire", "Git blob is empty")
        if byte_size > request.max_bytes:
            raise IntakeFailure(
                "SOURCE_TOO_LARGE",
                "acquire",
                "Git blob exceeds maximum bytes",
                safe_context={"observed_bytes": byte_size, "max_bytes": request.max_bytes},
            )
        data = self.runner.run(
            repository.root,
            ["cat-file", "blob", object_id],
            max_stdout=request.max_bytes,
            stage="acquire",
        )
        if len(data) != byte_size:
            raise IntakeFailure(
                "GIT_BLOB_TRUNCATED",
                "acquire",
                "Git blob size does not match object metadata",
            )
        if data.startswith(LFS_PREFIX):
            raise IntakeFailure(
                "GIT_LFS_POINTER",
                "safety_gate",
                "Git LFS pointer is not the underlying source content",
            )

        if self.after_blob_hook is not None:
            self.after_blob_hook()
        root_stat = repository.root.stat()
        git_dir_stat = repository.git_dir.stat()
        if (root_stat.st_dev, root_stat.st_ino) != repository.identity or (
            git_dir_stat.st_dev,
            git_dir_stat.st_ino,
        ) != repository.git_dir_identity:
            raise IntakeFailure(
                "GIT_REPOSITORY_CHANGED_DURING_READ",
                "acquire",
                "repository identity changed during acquisition",
            )
        repeated_entry = self.runner.run(
            repository.root,
            ["ls-tree", "-z", "--full-tree", commit, "--", tree_path],
            stage="acquire",
        )
        if repeated_entry != raw_entry:
            raise IntakeFailure(
                "GIT_REPOSITORY_CHANGED_DURING_READ",
                "acquire",
                "Git tree entry changed during acquisition",
            )

        entry = GitTreeEntry(
            mode=mode,
            object_type=object_type,
            object_id=object_id,
            tree_path=tree_path,
            byte_size=byte_size,
        )
        canonical_locator = f"{repository.root.as_uri()}#git-path={tree_path}"
        return GitAcquisition(
            canonical_locator=canonical_locator,
            original_uri=canonical_locator,
            source_version=f"git:{commit}:{object_id}:{mode}",
            commit_sha=commit,
            repository=repository,
            entry=entry,
            data=data,
        )


def _git_evidence(
    *,
    attempt_id: str,
    source_id: str,
    repository_locator_hash: str,
    request: GitPathRequest,
    acquisition: GitAcquisition | None,
    raw_hash: str | None,
    failure: IntakeFailure | None,
) -> dict[str, Any]:
    repository = acquisition.repository if acquisition is not None else None
    entry = acquisition.entry if acquisition is not None else None
    return {
        "schema_version": "git-acquisition-evidence/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "connector_type": CONNECTOR_TYPE,
        "connector_version": CONNECTOR_VERSION,
        "repository_locator_sha256": repository_locator_hash,
        "requested_commit_sha": request.commit_sha,
        "resolved_commit_sha": acquisition.commit_sha if acquisition is not None else None,
        "tree_path": entry.tree_path if entry is not None else request.tree_path,
        "object_format": repository.object_format if repository is not None else None,
        "file_mode": entry.mode if entry is not None else None,
        "object_type": entry.object_type if entry is not None else None,
        "blob_object_id": entry.object_id if entry is not None else None,
        "byte_size": entry.byte_size if entry is not None else None,
        "raw_sha256": raw_hash,
        "git_version": repository.git_version if repository is not None else None,
        "command_policy": GitCommandPolicy().to_dict(),
        "outcome": "accepted" if failure is None else "rejected",
        "failure_code": failure.code if failure is not None else None,
        "safe_context": failure.safe_context if failure is not None else {},
    }


def intake_local_git_path(
    *,
    store: ObjectStore,
    request: GitPathRequest,
    allowed_root: Path,
    output_dir: Path | None = None,
    runner: GitRunner | None = None,
    after_blob_hook: AfterBlobHook | None = None,
) -> IntakeResult:
    """Acquire one immutable committed Git blob into the M10 intake namespace."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None
    repository_locator_hash = sha256_bytes(request.repository_locator.encode("utf-8"))
    acquisition: GitAcquisition | None = None
    raw_hash: str | None = None
    evidence_key: str | None = None
    evidence_written = False

    try:
        request.validate()
        command_runner = runner or GitRunner(timeout_seconds=request.git_timeout_seconds)
        connector = LocalGitPathConnector(
            allowed_root,
            runner=command_runner,
            after_blob_hook=after_blob_hook,
        )
        repository_root = connector.canonicalize_repository(request.repository_locator)
        canonical_tree = canonical_tree_path(request.tree_path)
        canonical_locator = f"{repository_root.as_uri()}#git-path={canonical_tree}"
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)
        artifacts["source_id"] = source_id

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[
                f"repository_locator_sha256:{repository_locator_hash}",
                f"tree_path_sha256:{sha256_bytes(canonical_tree.encode('utf-8'))}",
                f"commit:{request.commit_sha}",
            ],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        repository = connector.inspect_repository(repository_root)
        acquisition = connector.acquire(repository, request)
        raw_hash = sha256_bytes(acquisition.data)
        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[
                f"commit:{acquisition.commit_sha}",
                f"blob:{acquisition.entry.object_id}",
                f"sha256:{raw_hash}",
                f"bytes:{len(acquisition.data)}",
            ],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        evidence_key = f"intake/v1/attempts/{attempt_id}/git-acquisition.json"
        artifacts["git_evidence_key"] = evidence_key
        normalized, normalizer_id = _normalise_git_blob(
            acquisition.entry.tree_path,
            acquisition.commit_sha,
            acquisition.entry.object_id,
            acquisition.data,
        )
        extracted_text = normalized.decode("utf-8")
        secret_matches = _secret_matches(extracted_text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "Git blob contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "observed_sha256": raw_hash,
                    "observed_bytes": len(acquisition.data),
                },
            )

        evidence = _git_evidence(
            attempt_id=attempt_id,
            source_id=source_id,
            repository_locator_hash=repository_locator_hash,
            request=request,
            acquisition=acquisition,
            raw_hash=raw_hash,
            failure=None,
        )
        evidence_bytes = _pretty_json_bytes(evidence)
        object_states.append(
            _put_immutable(
                store,
                evidence_key,
                evidence_bytes,
                content_type="application/json",
            )
        )
        evidence_written = True

        raw_blob_key = f"intake/v1/raw/sha256/{raw_hash[:2]}/{raw_hash}"
        raw_reused = _put_immutable(
            store,
            raw_blob_key,
            acquisition.data,
            content_type="text/plain",
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
            "mime_type": "text/plain",
            "encoding": "utf-8",
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
            evidence_refs=[raw_blob_key, snapshot_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        normalized_hash = sha256_bytes(normalized)
        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=normalizer_id,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{normalizer_id}/"
            f"{NORMALIZER_VERSION}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{normalizer_id}/"
            f"{NORMALIZER_VERSION}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = {
            "schema_version": "intake-derivative/v1",
            "derivative_id": derivative_id,
            "snapshot_id": snapshot_id,
            "normalizer_id": normalizer_id,
            "normalizer_version": NORMALIZER_VERSION,
            "normalized_content_hash": normalized_hash,
            "normalized_key": normalized_key,
            "byte_size": len(normalized),
            "mime_type": "text/markdown",
            "warnings": _prompt_findings(extracted_text),
            "git_evidence_key": evidence_key,
            "commit_sha": acquisition.commit_sha,
            "tree_path": acquisition.entry.tree_path,
            "blob_object_id": acquisition.entry.object_id,
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
            evidence_refs=[normalized_key, derivative_key, evidence_key],
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
            evidence_refs=[snapshot_key, derivative_key, evidence_key],
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
        _write_output(output_dir, "git-acquisition.json", evidence_bytes)
        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        if (
            not evidence_written
            and evidence_key is not None
            and artifacts.get("source_id") is not None
        ):
            evidence = _git_evidence(
                attempt_id=attempt_id,
                source_id=str(artifacts["source_id"]),
                repository_locator_hash=repository_locator_hash,
                request=request,
                acquisition=acquisition,
                raw_hash=raw_hash,
                failure=failure,
            )
            object_states.append(
                _put_immutable(
                    store,
                    evidence_key,
                    _pretty_json_bytes(evidence),
                    content_type="application/json",
                )
            )
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
