from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.intake import IntakeRequest, intake_markdown
from knowledge_engine.resolution import ResolveRequest, resolve_synthesis
from knowledge_engine.storage import FileObjectStore
from knowledge_engine.synthesis import (
    SynthesisRequest,
    prepare_synthesis,
    validate_synthesis,
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _concept(
    title: str,
    body: str,
    *,
    audience: str = "internal",
    aliases: tuple[str, ...] = (),
) -> str:
    alias_lines = ""
    if aliases:
        alias_lines = "aliases:\n" + "".join(f"  - {item}\n" for item in aliases)
    return (
        "---\n"
        "type: Concept\n"
        f"title: {json.dumps(title)}\n"
        f"description: {json.dumps(body[:120])}\n"
        "timestamp: 2026-07-03T00:00:00Z\n"
        "x-kos-id: ko_01JTEST0000000000000000000\n"
        "x-kos-status: published\n"
        f"x-kos-audience: {audience}\n"
        "x-kos-confidence: 0.9\n"
        "x-kos-provenance: provenance/test.json\n"
        "x-kos-review:\n"
        "  review_id: review_test\n"
        "  status: approved\n"
        f"{alias_lines}"
        "---\n"
        f"# {title}\n\n"
        f"{body}\n"
    )


def _source_repo(tmp_path: Path, concepts: dict[str, str]) -> tuple[Path, str]:
    root = tmp_path / "source"
    (root / "bundle/concepts").mkdir(parents=True)
    (root / "bundle/index.md").write_text("# Knowledge Source\n", encoding="utf-8")
    for name, content in concepts.items():
        (root / f"bundle/concepts/{name}.md").write_text(content, encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "source fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _synthesis(
    tmp_path: Path,
    store: FileObjectStore,
    *,
    title: str,
    claim: str,
    source_text: str | None = None,
    audience: str = "internal",
) -> str:
    source_text = source_text or f"# Evidence\n\n{claim}\n"
    source = tmp_path / f"evidence-{len(list(tmp_path.glob('evidence-*')))}.md"
    source.write_text(source_text, encoding="utf-8")
    intake = intake_markdown(
        store=store,
        request=IntakeRequest(
            source_id=f"source_resolution_{len(list(tmp_path.glob('intake-*'))):03d}",
            source_uri=f"urn:resolution:{len(list(tmp_path.glob('intake-*')))}",
            title=title,
            kind="markdown",
            audience=audience,
            retrieved_at="2026-07-03T10:10:00Z",
            owner="test-owner",
            license="test-only",
        ),
        input_path=source,
        output_dir=tmp_path / f"intake-{len(list(tmp_path.glob('intake-*')))}",
    )
    prepared = prepare_synthesis(
        store=store,
        request=SynthesisRequest(
            capture_id=intake.capture_id,
            provider="fixture-provider",
            model="fixture-model",
            model_version="fixture-v1",
            prompt_version="m5-prompt-v1",
            harness_version="m5-harness-v1",
            seed=23,
            temperature=0.0,
            requested_at="2026-07-03T10:11:00Z",
            actor="test-reviewer",
        ),
        output_dir=tmp_path / f"prepared-{intake.capture_id}",
    )
    start = source_text.index(claim)
    model_output = tmp_path / f"model-{intake.capture_id}.json"
    model_output.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "title": title,
                "summary": claim,
                "claims": [
                    {
                        "claim_id": "claim_resolution_test",
                        "text": claim,
                        "evidence": [
                            {
                                "start_char": start,
                                "end_char": start + len(claim),
                                "quote": claim,
                            }
                        ],
                    }
                ],
                "unsupported_claims": [],
            }
        ),
        encoding="utf-8",
    )
    validated = validate_synthesis(
        store=store,
        request_id=prepared.request_id,
        model_output_path=model_output,
        output_dir=tmp_path / f"validated-{intake.capture_id}",
    )
    return validated.synthesis_id


def _resolve(
    tmp_path: Path,
    store: FileObjectStore,
    synthesis_id: str,
    source_root: Path,
    source_sha: str,
    *,
    requested_audience: str = "internal",
    output_name: str = "resolution",
):
    return resolve_synthesis(
        store=store,
        request=ResolveRequest(
            synthesis_id=synthesis_id,
            source_repository="danielcanfly/knowledge-source",
            source_commit_sha=source_sha,
            requested_audience=requested_audience,
            resolver_version="resolver-v1",
            actor="test-reviewer",
            resolved_at="2026-07-03T10:12:00Z",
        ),
        source_root=source_root,
        output_dir=tmp_path / output_name,
    )


def test_create_when_source_has_no_concept_candidate(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="Completely new concept",
        claim="A novel governed intake rule exists.",
    )
    source_root, source_sha = _source_repo(tmp_path, {})

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)

    assert result.action == "create"
    assert result.target_concept_ids == ()
    assert result.status == "pending_human_review"
    assert result.canonical_write_permitted is False


def test_no_op_when_title_and_claim_are_already_covered(tmp_path: Path) -> None:
    claim = "Raw evidence remains immutable."
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(tmp_path, store, title="Evidence policy", claim=claim)
    source_root, source_sha = _source_repo(
        tmp_path,
        {"evidence-policy": _concept("Evidence policy", claim)},
    )

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)

    assert result.action == "no-op"
    assert result.target_concept_ids == ("concepts/evidence-policy",)


def test_update_when_title_matches_but_claim_is_new(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="Evidence policy",
        claim="Every accepted claim requires an exact source span.",
    )
    source_root, source_sha = _source_repo(
        tmp_path,
        {
            "evidence-policy": _concept(
                "Evidence policy",
                "Raw evidence remains immutable.",
            )
        },
    )

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)
    proposal = json.loads(
        store.get(f"{result.resolution_prefix}/proposed-action.json")
    )

    assert result.action == "update"
    assert proposal["findings"][0]["code"] == "UNCOVERED_CLAIMS"


def test_alias_when_content_exists_under_another_title(tmp_path: Path) -> None:
    claim = "Raw evidence remains immutable."
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(tmp_path, store, title="Immutable capture", claim=claim)
    source_root, source_sha = _source_repo(
        tmp_path,
        {"evidence-policy": _concept("Evidence policy", claim)},
    )

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)

    assert result.action == "alias"
    assert result.target_concept_ids == ("concepts/evidence-policy",)


def test_merge_when_one_similar_candidate_needs_synthesis(tmp_path: Path) -> None:
    claim = "Immutable raw evidence uses content hashes for storage identity."
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="Immutable evidence identity",
        claim=claim,
    )
    source_root, source_sha = _source_repo(
        tmp_path,
        {
            "evidence-storage": _concept(
                "Evidence storage identity",
                "Immutable evidence storage uses content hash identity and review records.",
            )
        },
    )

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)

    assert result.action == "merge"
    assert result.target_concept_ids == ("concepts/evidence-storage",)


def test_negation_conflict_is_explicit_and_source_attributed(tmp_path: Path) -> None:
    claim = "Raw evidence must remain immutable during review."
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(tmp_path, store, title="Review storage rule", claim=claim)
    source_root, source_sha = _source_repo(
        tmp_path,
        {
            "mutable-review": _concept(
                "Mutable review storage",
                "Raw evidence must not remain immutable during review.",
            )
        },
    )

    result = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)
    conflicts = json.loads(store.get(f"{result.resolution_prefix}/conflicts.json"))

    assert result.action == "conflict"
    assert result.status == "pending_conflict_review"
    assert conflicts["findings"][0]["code"] == "POSSIBLE_NEGATION_CONFLICT"
    assert conflicts["findings"][0]["draft_claim_id"] == "claim_resolution_test"
    assert conflicts["findings"][0]["existing_path"].endswith("mutable-review.md")


def test_acl_downgrade_is_blocked_by_most_restrictive_evidence(tmp_path: Path) -> None:
    claim = "Restricted evidence requires restricted review."
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="Restricted review",
        claim=claim,
        audience="restricted",
    )
    source_root, source_sha = _source_repo(tmp_path, {})

    result = _resolve(
        tmp_path,
        store,
        synthesis_id,
        source_root,
        source_sha,
        requested_audience="public",
    )
    proposal = json.loads(
        store.get(f"{result.resolution_prefix}/proposed-action.json")
    )

    assert result.acl_downgrade_blocked is True
    assert result.effective_audience == "restricted"
    assert result.status == "pending_security_review"
    assert proposal["findings"][-1]["code"] == "ACL_DOWNGRADE_BLOCKED"


def test_resolution_replay_is_idempotent_and_review_only(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    store = FileObjectStore(store_root)
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="New review concept",
        claim="A review proposal remains non-canonical.",
    )
    source_root, source_sha = _source_repo(tmp_path, {})
    before = {
        path.relative_to(store_root).as_posix()
        for path in store_root.rglob("*")
        if path.is_file() and ".metadata" not in path.parts
    }

    first = _resolve(tmp_path, store, synthesis_id, source_root, source_sha)
    second = _resolve(
        tmp_path,
        store,
        synthesis_id,
        source_root,
        source_sha,
        output_name="resolution-replay",
    )
    after = {
        path.relative_to(store_root).as_posix()
        for path in store_root.rglob("*")
        if path.is_file() and ".metadata" not in path.parts
    }

    assert first.resolution_id == second.resolution_id
    assert first.idempotent is False
    assert second.idempotent is True
    added = after - before
    assert added
    assert all(path.startswith("review/resolutions/") for path in added)
    assert not any(path.startswith("channels/") for path in added)
    assert not any(path.startswith("releases/") for path in added)


def test_wrong_source_sha_and_dirty_checkout_are_rejected(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path / "store")
    synthesis_id = _synthesis(
        tmp_path,
        store,
        title="Source boundary",
        claim="Resolution requires an exact clean Source snapshot.",
    )
    source_root, source_sha = _source_repo(tmp_path, {})

    with pytest.raises(IntegrityError, match="source SHA mismatch"):
        _resolve(tmp_path, store, synthesis_id, source_root, "0" * 40)

    (source_root / "bundle/index.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="source checkout is dirty"):
        _resolve(tmp_path, store, synthesis_id, source_root, source_sha)
