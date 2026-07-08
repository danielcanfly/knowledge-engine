from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from knowledge_engine.compiler_resolution_contract_v1 import RESOLUTION_OUTCOMES
from knowledge_engine.compiler_resolution_v1 import (
    SourceResolutionRequest,
    resolve_compiler_run,
    verify_resolution_event,
)
from knowledge_engine.compiler_v1 import (
    compile_local_markdown,
    request_from_intake_result,
)
from knowledge_engine.errors import IntegrityError
from knowledge_engine.intake_v1 import (
    AccessPolicy,
    EvidenceValue,
    LocalMarkdownRequest,
    intake_local_markdown,
)
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = "danielcanfly/knowledge-source"
RESOLUTION_MODULES = (
    ROOT / "src/knowledge_engine/compiler_resolution_contract_v1.py",
    ROOT / "src/knowledge_engine/compiler_evidence_v1.py",
    ROOT / "src/knowledge_engine/compiler_source_v1.py",
    ROOT / "src/knowledge_engine/compiler_resolution_v1.py",
)
MARKDOWN = """# Novel Topic

# Existing Topic

# Old Alias

Existing evidence is canonical.

Agents must not retry forever.

Supersedes: Legacy Topic — Replaced by current evidence.

Published: 2026-07-08

Unsupported assertion.
"""


def _run(root: Path, *args: str) -> str:
    completed = subprocess.run(
        list(args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _resolved(value: str) -> EvidenceValue:
    return EvidenceValue("resolved", value, "operator_asserted")


def _json(store: FileObjectStore, key: str) -> dict[str, Any]:
    value = json.loads(store.get(key))
    assert isinstance(value, dict)
    return value


def _rewrite_json(store: FileObjectStore, key: str, value: dict[str, Any]) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    store.put(key, data, content_type="application/json")


def _compile(
    tmp_path: Path,
    *,
    markdown: str = MARKDOWN,
    audience: str = "public",
) -> tuple[FileObjectStore, Any]:
    intake_root = tmp_path / "intake"
    intake_root.mkdir(parents=True)
    (intake_root / "document.md").write_text(markdown, encoding="utf-8")
    store = FileObjectStore(tmp_path / "store")
    intake = intake_local_markdown(
        store=store,
        request=LocalMarkdownRequest(
            locator="document.md",
            retrieved_at="2026-07-08T08:00:00Z",
            owner=_resolved("Daniel"),
            license=_resolved("owner-provided"),
            audience=audience,
            access_policy=AccessPolicy(
                "public" if audience == "public" else "restricted",
                (),
                "observed",
            ),
        ),
        allowed_root=intake_root,
    )
    assert intake.status == "accepted_for_compilation"
    compiled = compile_local_markdown(store, request_from_intake_result(store, intake))
    assert compiled.status == "review_only_complete"
    return store, compiled


def _concept(
    concept_id: str,
    title: str,
    body: str,
    *,
    audience: str = "public",
    aliases: tuple[str, ...] = (),
    description: str = "Fixture concept.",
) -> str:
    alias_lines = ""
    if aliases:
        alias_lines = "aliases:\n" + "".join(f"  - {item}\n" for item in aliases)
    return (
        "---\n"
        "type: Concept\n"
        f"title: {title}\n"
        f"description: {description}\n"
        f"{alias_lines}"
        f"x-kos-id: {concept_id}\n"
        f"x-kos-audience: {audience}\n"
        "---\n"
        f"# {title}\n\n"
        f"{body.strip()}\n"
    )


def _source(
    tmp_path: Path,
    *,
    extra: dict[str, str] | None = None,
) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    _run(root, "git", "init")
    _run(root, "git", "config", "user.email", "fixture@example.com")
    _run(root, "git", "config", "user.name", "Fixture")
    concepts = root / "bundle/concepts"
    concepts.mkdir(parents=True)
    (concepts / "existing.md").write_text(
        _concept(
            "ko_existing",
            "Existing Topic",
            "Existing evidence is canonical.\nAgents must retry forever.",
            audience="internal",
            aliases=("Old Alias",),
            description="Existing adaptive evidence.",
        ),
        encoding="utf-8",
    )
    (concepts / "legacy.md").write_text(
        _concept(
            "ko_legacy",
            "Legacy Topic",
            "Legacy evidence remains.",
        ),
        encoding="utf-8",
    )
    for name, content in (extra or {}).items():
        (concepts / name).write_text(content, encoding="utf-8")
    (root / "bundle/README.md").write_text("# Fixture Source\n", encoding="utf-8")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-m", "fixture")
    return root, _run(root, "git", "rev-parse", "HEAD")


def _request(run_id: str, source_sha: str, **overrides: Any) -> SourceResolutionRequest:
    values = {
        "compiler_run_id": run_id,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit_sha": source_sha,
        "resolved_at": "2026-07-08T09:00:00Z",
    }
    values.update(overrides)
    return SourceResolutionRequest(**values)


def _mark_unsupported(store: FileObjectStore, candidates_key: str) -> None:
    candidate_set = _json(store, candidates_key)
    target = next(
        item
        for item in candidate_set["candidates"]
        if item["candidate_type"] == "claim" and item["value"] == "Unsupported assertion."
    )
    target["status"] = "rejected_unsupported"
    target["rejection_reason"] = "fixture unsupported claim"
    target["synthesis_eligible"] = False
    _rewrite_json(store, candidates_key, candidate_set)


def test_source_aware_resolution_emits_all_outcomes_and_review_only_evidence(
    tmp_path: Path,
) -> None:
    store, compiled = _compile(tmp_path)
    _mark_unsupported(store, compiled.candidates_key)
    source_root, source_sha = _source(tmp_path)
    before_status = _run(source_root, "git", "status", "--porcelain", "--untracked-files=all")

    result = resolve_compiler_run(
        store,
        _request(compiled.compiler_run_id, source_sha),
        source_root,
        tmp_path / "output",
    )

    assert result.status == "review_only_complete"
    assert result.idempotent is False
    assert result.resolution_prefix
    assert result.canonical_write_permitted is False
    assert result.github_write_permitted is False
    assert result.production_write_permitted is False
    assert set(result.outcome_counts or {}) == RESOLUTION_OUTCOMES
    assert all((result.outcome_counts or {})[outcome] >= 1 for outcome in RESOLUTION_OUTCOMES)

    prefix = result.resolution_prefix
    resolutions = _json(store, f"{prefix}/resolutions.json")["resolutions"]
    assert {item["outcome"] for item in resolutions} == RESOLUTION_OUTCOMES
    assert all(item["canonical_write_permitted"] is False for item in resolutions)
    assert all(item["resolution_id"].startswith("cres_") for item in resolutions)
    assert all(item["evidence_refs"] for item in resolutions)
    existing = next(
        item
        for item in resolutions
        if item["outcome"] == "existing_concept_update" and item["target_ids"] == ["ko_existing"]
    )
    assert existing["effective_audience"] == "internal"
    supersession = next(item for item in resolutions if item["outcome"] == "supersession")
    assert supersession["supersession_basis"]["superseded_target_id"] == "ko_legacy"
    assert supersession["review_status"] == "pending_conflict_review"
    unsupported = next(
        item for item in resolutions if item["outcome"] == "rejected_unsupported_claim"
    )
    assert unsupported["review_status"] == "rejected"
    assert unsupported["synthesis_eligible"] is False

    validation = _json(store, f"{prefix}/validation-report.json")
    assert validation["all_candidates_evidence_valid"] is True
    assert validation["source_checkout_clean"] is True
    assert validation["source_identity_exact"] is True
    assert validation["audience_broadening_detected"] is False
    assert validation["canonical_write_permitted"] is False
    source_snapshot = _json(store, f"{prefix}/source-snapshot.json")
    assert source_snapshot["repository"] == SOURCE_REPOSITORY
    assert source_snapshot["commit_sha"] == source_sha
    assert source_snapshot["source_snapshot_sha256"] == result.source_snapshot_sha256

    previous = None
    states = []
    for key in result.event_keys:
        assert key.startswith(f"{prefix}/events/")
        event = _json(store, key)
        assert verify_resolution_event(event)
        assert event["previous_event_hash"] == previous
        assert event["mutations_performed"] == ["compiler_review_object_write"]
        previous = event["event_sha256"]
        states.append(event["to_state"])
    assert states == [
        "validated_input",
        "source_indexed",
        "resolved",
        "review_only_complete",
    ]
    assert (tmp_path / "output/resolutions.json").is_file()
    assert (tmp_path / "output/validation-report.json").is_file()
    assert _run(source_root, "git", "rev-parse", "HEAD") == source_sha
    assert (
        _run(source_root, "git", "status", "--porcelain", "--untracked-files=all") == before_status
    )


def test_exact_resolution_replay_is_byte_identical(tmp_path: Path) -> None:
    store, compiled = _compile(tmp_path)
    source_root, source_sha = _source(tmp_path)
    request = _request(compiled.compiler_run_id, source_sha)
    first = resolve_compiler_run(store, request, source_root)
    prefix = first.resolution_prefix or ""
    keys = [
        f"{prefix}/resolution-record.json",
        f"{prefix}/source-snapshot.json",
        f"{prefix}/candidate-index.json",
        f"{prefix}/resolutions.json",
        f"{prefix}/validation-report.json",
        f"{prefix}/result.json",
        *first.event_keys,
    ]
    before = {key: store.get(key) for key in keys}
    second = resolve_compiler_run(store, request, source_root)
    assert second.resolution_batch_id == first.resolution_batch_id
    assert first.idempotent is False
    assert second.idempotent is True
    assert all(store.get(key) == value for key, value in before.items())


@pytest.mark.parametrize(
    ("artifact", "expected"),
    [
        ("candidate", "RESOLUTION_CANDIDATE_INVALID"),
        ("block", "RESOLUTION_BLOCK_INVALID"),
        ("source_map", "RESOLUTION_SOURCE_MAP_INVALID"),
        ("event", "RESOLUTION_EVENT_CHAIN_INVALID"),
        ("normalized", "RESOLUTION_HASH_MISMATCH"),
    ],
)
def test_tampered_compiler_evidence_is_rejected(
    tmp_path: Path,
    artifact: str,
    expected: str,
) -> None:
    store, compiled = _compile(tmp_path)
    source_root, source_sha = _source(tmp_path)
    if artifact == "candidate":
        value = _json(store, compiled.candidates_key)
        value["candidates"][0]["value"] += " tampered"
        _rewrite_json(store, compiled.candidates_key, value)
    elif artifact == "block":
        value = _json(store, compiled.blocks_key)
        value["blocks"][0]["text"] += " tampered"
        _rewrite_json(store, compiled.blocks_key, value)
    elif artifact == "source_map":
        value = _json(store, compiled.source_map_key)
        value["source_maps"][0]["segments"][0]["quote"] += " tampered"
        _rewrite_json(store, compiled.source_map_key, value)
    elif artifact == "event":
        value = _json(store, compiled.event_keys[0])
        value["to_state"] = "review_only_complete"
        _rewrite_json(store, compiled.event_keys[0], value)
    else:
        compiler_input = _json(store, compiled.input_key)
        normalized_key = compiler_input["derivative_ref"]["normalized_key"]
        store.put(normalized_key, b"tampered\n", content_type="text/markdown")

    result = resolve_compiler_run(
        store,
        _request(compiled.compiler_run_id, source_sha),
        source_root,
    )
    assert result.status == "rejected"
    assert result.failure_code == expected
    rejection = _json(store, result.rejection_key or "")
    assert rejection["canonical_write_permitted"] is False
    assert rejection["github_write_permitted"] is False
    assert rejection["production_write_permitted"] is False


def test_source_sha_dirty_and_duplicate_name_fail_closed(tmp_path: Path) -> None:
    store, compiled = _compile(tmp_path)
    source_root, _ = _source(tmp_path)
    wrong = resolve_compiler_run(
        store,
        _request(compiled.compiler_run_id, "0" * 40),
        source_root,
    )
    assert wrong.failure_code == "SOURCE_SHA_MISMATCH"

    store2, compiled2 = _compile(tmp_path / "dirty")
    source_root2, source_sha2 = _source(tmp_path / "dirty")
    (source_root2 / "untracked.txt").write_text("dirty", encoding="utf-8")
    dirty = resolve_compiler_run(
        store2,
        _request(compiled2.compiler_run_id, source_sha2),
        source_root2,
    )
    assert dirty.failure_code == "SOURCE_DIRTY"

    duplicate = {
        "duplicate.md": _concept(
            "ko_duplicate",
            "Duplicate Topic",
            "Other content.",
            aliases=("Old Alias",),
        )
    }
    store3, compiled3 = _compile(tmp_path / "duplicate")
    source_root3, source_sha3 = _source(tmp_path / "duplicate", extra=duplicate)
    duplicate_result = resolve_compiler_run(
        store3,
        _request(compiled3.compiler_run_id, source_sha3),
        source_root3,
    )
    assert duplicate_result.failure_code == "SOURCE_DUPLICATE_NAME"


def test_ambiguous_similarity_never_silently_merges(tmp_path: Path) -> None:
    store, compiled = _compile(
        tmp_path,
        markdown="Shared adaptive planning model.\n",
    )
    extra = {
        "shared-one.md": _concept(
            "ko_shared_one",
            "Shared Planning One",
            "Shared adaptive planning model with governed execution.",
        ),
        "shared-two.md": _concept(
            "ko_shared_two",
            "Shared Planning Two",
            "Shared adaptive planning model with bounded execution.",
        ),
    }
    source_root, source_sha = _source(tmp_path, extra=extra)
    result = resolve_compiler_run(
        store,
        _request(
            compiled.compiler_run_id,
            source_sha,
            strong_match_threshold=0.25,
        ),
        source_root,
    )
    resolutions = _json(store, f"{result.resolution_prefix}/resolutions.json")["resolutions"]
    claim = next(item for item in resolutions if item["candidate_id"])
    assert claim["outcome"] == "unresolved_conflict"
    assert claim["reason_codes"] == ["MULTIPLE_VIABLE_SOURCE_TARGETS"]
    assert claim["review_status"] == "pending_conflict_review"
    assert claim["synthesis_eligible"] is False


def test_resolution_immutable_collision_fails_hard(tmp_path: Path) -> None:
    store, compiled = _compile(tmp_path)
    source_root, source_sha = _source(tmp_path)
    request = _request(compiled.compiler_run_id, source_sha)
    first = resolve_compiler_run(store, request, source_root)
    key = f"{first.resolution_prefix}/resolutions.json"
    store.put(key, b"corrupt", content_type="application/json")
    with pytest.raises(IntegrityError, match="immutable object collision"):
        resolve_compiler_run(store, request, source_root)


def test_resolution_taxonomy_and_mutation_surface_are_closed() -> None:
    assert {
        "new_concept",
        "existing_concept_update",
        "alias",
        "duplicate",
        "contradiction",
        "supersession",
        "unresolved_conflict",
        "rejected_unsupported_claim",
    } == RESOLUTION_OUTCOMES
    imports = set()
    combined = ""
    for path in RESOLUTION_MODULES:
        source = path.read_text(encoding="utf-8")
        combined += source
        tree = ast.parse(source)
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imports.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
    forbidden = {
        "socket",
        "http.client",
        "requests",
        "urllib.request",
        "sqlite3",
        "psycopg",
        "pymysql",
        "pyodbc",
        "sqlalchemy",
        "knowledge_engine.review",
        "knowledge_engine.synthesis",
        "knowledge_engine.promotion",
        "knowledge_engine.release",
    }
    assert not imports & forbidden
    assert "channels/production.json" not in combined
    assert "publish_release" not in combined
    assert 'github_write_permitted": True' not in combined
    assert 'production_write_permitted": True' not in combined
