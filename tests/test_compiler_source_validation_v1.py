from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knowledge_engine.compiler_contract_v1 import CompilerFailure
from knowledge_engine.compiler_source_v1 import SOURCE_REPOSITORY, verify_source_checkout


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        list(args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _concept(*, audience: str = "public", frontmatter: bool = True) -> str:
    body = (
        "type: Concept\n"
        "title: Source Validation Fixture\n"
        "description: Exercises Source validation.\n"
        "x-kos-id: ko_source_validation_fixture\n"
        f"x-kos-audience: {audience}\n"
    )
    if frontmatter:
        return f"---\n{body}---\n# Source Validation Fixture\n"
    return f"{body}# Source Validation Fixture\n"


def _repository(tmp_path: Path, concept: str) -> tuple[Path, str]:
    root = tmp_path / "source"
    concepts = root / "bundle/concepts"
    concepts.mkdir(parents=True)
    (concepts / "fixture.md").write_text(concept, encoding="utf-8")
    _run(root, "git", "init")
    _run(root, "git", "config", "user.email", "fixture@example.com")
    _run(root, "git", "config", "user.name", "Fixture")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-m", "fixture")
    return root, _run(root, "git", "rev-parse", "HEAD")


def test_source_symlink_fails_closed(tmp_path: Path) -> None:
    root, _ = _repository(tmp_path, _concept())
    target = root / "outside.md"
    target.write_text("outside\n", encoding="utf-8")
    link = root / "bundle/concepts/symlink.md"
    link.symlink_to(target)
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-m", "add symlink")
    source_sha = _run(root, "git", "rev-parse", "HEAD")

    with pytest.raises(CompilerFailure) as raised:
        verify_source_checkout(root, SOURCE_REPOSITORY, source_sha)
    assert raised.value.code == "SOURCE_SYMLINK"


@pytest.mark.parametrize(
    ("concept", "expected"),
    [
        (_concept(frontmatter=False), "SOURCE_FRONTMATTER_REQUIRED"),
        (_concept(audience="world"), "SOURCE_AUDIENCE_INVALID"),
    ],
)
def test_malformed_source_metadata_fails_closed(
    tmp_path: Path,
    concept: str,
    expected: str,
) -> None:
    root, source_sha = _repository(tmp_path, concept)

    with pytest.raises(CompilerFailure) as raised:
        verify_source_checkout(root, SOURCE_REPOSITORY, source_sha)
    assert raised.value.code == expected
