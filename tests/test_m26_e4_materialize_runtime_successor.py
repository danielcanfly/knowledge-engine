from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from scripts.m26_e4_build_runtime_bundle import section_identity_evidence

from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "m26_e4_materialize_runtime_successor",
    SCRIPTS / "m26_e4_materialize_runtime_successor.py",
)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    bundle = tmp_path / "bundle"
    release = "candidate-test-release"
    artifact = bundle / "releases" / release / "artifacts" / "lexical.json"
    manifest = bundle / "releases" / release / "manifest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"documents":[]}\n')
    manifest.write_bytes(b'{"status":"candidate"}\n')
    return bundle, manifest.relative_to(bundle).as_posix()


def test_manifest_is_deferred_until_explicit_finalization(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")

    artifacts = subject.stage_bundle_artifacts_to_r2(
        store,
        bundle,
        manifest_key,
    )

    assert artifacts["manifest_deferred"] is True
    assert store.head(manifest_key) is None
    assert len(artifacts["uploaded"]) == 1

    finalized = subject.finalize_candidate_manifest(store, bundle, manifest_key)
    assert finalized["created"] is True
    assert finalized["verified_exact"] is True
    assert store.head(manifest_key) is not None


def test_exact_replay_reuses_artifacts_and_manifest(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)
    subject.finalize_candidate_manifest(store, bundle, manifest_key)

    artifacts = subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)
    finalized = subject.finalize_candidate_manifest(store, bundle, manifest_key)

    assert artifacts["uploaded"] == []
    assert len(artifacts["skipped_exact"]) == 1
    assert finalized["created"] is False


def test_manifest_collision_fails_before_artifact_write(tmp_path: Path) -> None:
    bundle, manifest_key = _bundle(tmp_path)
    store = FileObjectStore(tmp_path / "store")
    store.put(
        manifest_key,
        b'{"status":"foreign"}\n',
        content_type="application/json",
        only_if_absent=True,
    )

    with pytest.raises(SystemExit, match="different digest"):
        subject.stage_bundle_artifacts_to_r2(store, bundle, manifest_key)

    artifact_key = manifest_key.replace("manifest.json", "artifacts/lexical.json")
    assert store.head(artifact_key) is None


def test_source_digest_parser_rejects_duplicates_and_missing_digest() -> None:
    assert subject._source_digests(
        {
            "entries": [
                {"source_id": "a", "content_sha256": "a" * 64},
                {"source_id": "b", "content_sha256": "b" * 64},
            ]
        }
    ) == {"a": "a" * 64, "b": "b" * 64}

    with pytest.raises(SystemExit, match="duplicate"):
        subject._source_digests(
            {
                "entries": [
                    {"source_id": "a", "content_sha256": "a" * 64},
                    {"source_id": "a", "content_sha256": "a" * 64},
                ]
            }
        )
    with pytest.raises(SystemExit, match="digest missing"):
        subject._source_digests({"entries": [{"source_id": "a"}]})


def test_section_identity_evidence_requires_exact_unique_parity() -> None:
    evidence = section_identity_evidence(
        [{"section_id": "b"}, {"section_id": "a"}],
        [{"section_id": "a"}, {"section_id": "b"}],
    )
    assert evidence["lexical_semantic_exact_set_equal"] is True
    assert evidence["lexical_duplicate_count"] == 0
    assert evidence["semantic_missing_count"] == 0

    with pytest.raises(SystemExit, match="duplicated"):
        section_identity_evidence(
            [{"section_id": "a"}, {"section_id": "a"}],
            [{"section_id": "a"}, {"section_id": "b"}],
        )
    with pytest.raises(SystemExit, match="sets differ"):
        section_identity_evidence(
            [{"section_id": "a"}],
            [{"section_id": "b"}],
        )
