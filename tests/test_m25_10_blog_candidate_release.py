from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine import m25_blog_candidate_release as subject
from knowledge_engine.errors import IntegrityError


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_stable_kos_is_deterministic_and_valid() -> None:
    first = subject._stable_kos("article_example")
    assert first == subject._stable_kos("article_example")
    assert first.startswith("ko_")
    assert len(first) == 29


def test_body_lines_enforces_exact_locator() -> None:
    raw = b"one\ntwo\nthree\n"
    assert subject._body_lines(raw, 2, 3) == "two\nthree"
    with pytest.raises(IntegrityError, match="locator"):
        subject._body_lines(raw, 0, 2)


def test_validate_pack_rejects_authority_digest_drift(tmp_path: Path) -> None:
    admission = {
        "schema_version": subject.PACK_SCHEMA,
        "production_pointer_authorized": False,
        "source_write_authorized": True,
        "candidate_release_authorized": True,
    }
    unsigned = json.dumps(
        admission,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    admission["admission_sha256"] = hashlib.sha256(unsigned).hexdigest()
    _write_json(tmp_path / "admission.json", admission)
    with pytest.raises(IntegrityError, match="authority digest"):
        subject.validate_pack(tmp_path)


def test_candidate_channel_must_be_isolated(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="candidate channel"):
        subject.deploy_candidate(
            source_url="file:///tmp/source",
            source_sha="a" * 40,
            foundation_sha="b" * 40,
            channel="production",
            work_dir=tmp_path,
            release_time=subject.datetime(2026, 7, 24, tzinfo=subject.UTC),
            allow_live=False,
        )


def test_semantic_population_contract_is_article_plus_section() -> None:
    assert subject.COUNTS["semantic_documents"] == (
        subject.COUNTS["articles"] + subject.COUNTS["sections"]
    )
    assert subject.COUNTS["nodes"] == (
        subject.COUNTS["series"]
        + subject.COUNTS["articles"]
        + subject.COUNTS["sections"]
    )
