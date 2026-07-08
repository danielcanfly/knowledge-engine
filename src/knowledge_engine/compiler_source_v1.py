from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .compiler_contract_v1 import CompilerFailure
from .intake_v1 import canonical_json_bytes
from .storage import sha256_bytes

SOURCE_REPOSITORY = "danielcanfly/knowledge-source"
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,119}$")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")
AUDIENCE_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
NEGATION_TERMS = {
    "not",
    "no",
    "never",
    "cannot",
    "can't",
    "without",
    "不",
    "無",
    "未",
    "非",
    "禁",
}
SUPERSESSION_RE = re.compile(
    r"^(?:supersedes|replaces)\s*:\s*([^|—\n]+?)\s*(?:\||—)\s*(.+)$",
    re.IGNORECASE,
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CompilerFailure("SOURCE_GIT_FAILURE", "source", detail)
    return completed.stdout


def normalize_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"`{1,3}.*?`{1,3}", " ", value, flags=re.DOTALL)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u3400-\u9fff]+", " ", value)
    return " ".join(value.split())


def tokens(value: str) -> set[str]:
    return {item.casefold() for item in TOKEN_RE.findall(value)}


def without_negation(value: set[str]) -> set[str]:
    return {item for item in value if item not in NEGATION_TERMS}


def has_negation(value: str) -> bool:
    return bool(tokens(value) & NEGATION_TERMS)


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def sentences(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n.!?。！？]+", value) if item.strip()]


def _frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise CompilerFailure(
            "SOURCE_FRONTMATTER_REQUIRED", "source", "concept front matter missing", path=str(path)
        )
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise CompilerFailure(
            "SOURCE_FRONTMATTER_INVALID", "source", "concept front matter unterminated", path=str(path)
        )
    try:
        value = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise CompilerFailure(
            "SOURCE_FRONTMATTER_INVALID", "source", "concept front matter invalid", path=str(path)
        ) from exc
    if not isinstance(value, dict):
        raise CompilerFailure(
            "SOURCE_FRONTMATTER_INVALID", "source", "concept front matter must be a mapping", path=str(path)
        )
    return value, text[marker + 5 :]


def verify_source_checkout(
    source_root: Path,
    source_repository: str,
    source_commit_sha: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if source_repository != SOURCE_REPOSITORY:
        raise CompilerFailure("SOURCE_REPOSITORY_INVALID", "source", "unexpected source repository")
    if not SHA_RE.fullmatch(source_commit_sha):
        raise CompilerFailure("SOURCE_SHA_INVALID", "source", "source SHA must be exact lowercase")
    root = source_root.resolve()
    if not root.is_dir():
        raise CompilerFailure("SOURCE_ROOT_MISSING", "source", "source root does not exist")
    actual = _git(root, "rev-parse", "HEAD").strip().lower()
    if actual != source_commit_sha:
        raise CompilerFailure(
            "SOURCE_SHA_MISMATCH", "source", "source checkout SHA mismatch", expected=source_commit_sha, actual=actual
        )
    if _git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise CompilerFailure("SOURCE_DIRTY", "source", "source checkout is dirty")

    tracked = [
        item
        for item in _git(root, "ls-files", "-z", "--", "bundle").split("\0")
        if item
    ]
    allowed = [
        item
        for item in tracked
        if Path(item).suffix.lower() in {".md", ".json", ".yaml", ".yml"}
    ]
    if not allowed:
        raise CompilerFailure("SOURCE_EMPTY", "source", "source bundle has no tracked records")

    files = []
    concept_paths = []
    for relative in sorted(allowed):
        path = root / relative
        if path.is_symlink():
            raise CompilerFailure(
                "SOURCE_SYMLINK", "source", "source symlink is not allowed", path=relative
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise CompilerFailure(
                "SOURCE_READ_FAILURE", "source", "cannot read source file", path=relative
            ) from exc
        files.append({"path": relative, "bytes": len(data), "sha256": sha256_bytes(data)})
        if relative.startswith("bundle/concepts/") and relative.endswith(".md"):
            concept_paths.append(path)
    if not concept_paths:
        raise CompilerFailure("SOURCE_CONCEPTS_MISSING", "source", "source concepts are required")

    concepts = []
    seen_ids: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for path in sorted(concept_paths):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CompilerFailure(
                "SOURCE_READ_FAILURE", "source", "cannot decode concept", path=relative
            ) from exc
        metadata, body = _frontmatter(text, path)
        concept_id = metadata.get("x-kos-id")
        title = metadata.get("title")
        aliases = metadata.get("aliases", [])
        audience = metadata.get("x-kos-audience", "internal")
        description = metadata.get("description", "")
        if not isinstance(concept_id, str) or not SAFE_ID_RE.fullmatch(concept_id):
            raise CompilerFailure("SOURCE_ID_INVALID", "source", "concept ID invalid", path=relative)
        if not isinstance(title, str) or not title.strip():
            raise CompilerFailure("SOURCE_TITLE_INVALID", "source", "concept title invalid", path=relative)
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) and item.strip() for item in aliases
        ):
            raise CompilerFailure("SOURCE_ALIAS_INVALID", "source", "concept aliases invalid", path=relative)
        if audience not in AUDIENCE_RANK:
            raise CompilerFailure("SOURCE_AUDIENCE_INVALID", "source", "concept audience invalid", path=relative)
        if not isinstance(description, str):
            raise CompilerFailure(
                "SOURCE_DESCRIPTION_INVALID", "source", "concept description invalid", path=relative
            )
        if concept_id in seen_ids:
            raise CompilerFailure(
                "SOURCE_DUPLICATE_ID", "source", "duplicate concept ID", concept_id=concept_id
            )
        seen_ids[concept_id] = relative
        names = [title.strip(), *(item.strip() for item in aliases)]
        for name in names:
            key = normalize_text(name)
            previous = seen_names.get(key)
            if previous is not None and previous != concept_id:
                raise CompilerFailure(
                    "SOURCE_DUPLICATE_NAME", "source", "duplicate title or alias", name=name
                )
            seen_names[key] = concept_id
        exact_values = {normalize_text(item) for item in names if normalize_text(item)}
        exact_values.update(
            normalize_text(item)
            for item in sentences("\n".join([description, body]))
            if normalize_text(item)
        )
        searchable = "\n".join([title, description, *aliases, body])
        concepts.append(
            {
                "concept_id": concept_id,
                "path": relative,
                "title": title.strip(),
                "title_normalized": normalize_text(title),
                "aliases": [item.strip() for item in aliases],
                "alias_normalized": [normalize_text(item) for item in aliases],
                "audience": audience,
                "description": description.strip(),
                "body": body,
                "sentences": sentences(body),
                "exact_values": sorted(exact_values),
                "tokens": sorted(tokens(searchable)),
            }
        )

    snapshot_identity = {
        "schema_version": "knowledge-source-snapshot/v1",
        "repository": source_repository,
        "commit_sha": source_commit_sha,
        "files": files,
    }
    source_snapshot_sha256 = sha256_bytes(canonical_json_bytes(snapshot_identity))
    snapshot = {
        **snapshot_identity,
        "source_snapshot_sha256": source_snapshot_sha256,
        "concept_count": len(concepts),
        "canonical_write_permitted": False,
    }
    return snapshot, concepts


def explicit_supersession(value: str) -> tuple[str, str] | None:
    match = SUPERSESSION_RE.match(value.strip())
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()
