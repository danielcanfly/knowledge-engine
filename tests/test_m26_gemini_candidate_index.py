from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "m26_gemini_candidate_index.py"
spec = importlib.util.spec_from_file_location("m26_gemini_candidate_index", SCRIPT)
assert spec is not None and spec.loader is not None
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_input_loader_understands_candidate_jsonl_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    semantic = tmp_path / "semantic-inputs.jsonl"
    lexical = tmp_path / "lexical-documents.jsonl"
    source = tmp_path / "source-index.json"
    semantic_rows = [
        {"section_id": "s1", "text": "alpha", "payload": {"title": "A"}},
        {"section_id": "s2", "text": "beta", "payload": {"title": "B"}},
    ]
    lexical_rows = [
        {"section_id": "s1", "text": "alpha"},
        {"section_id": "s2", "text": "beta"},
    ]
    _write_jsonl(semantic, semantic_rows)
    _write_jsonl(lexical, lexical_rows)
    source.write_text(
        json.dumps(
            {
                "article_source_count": 2,
                "sources": [{"path": "a.md"}, {"path": "b.md"}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "M26_GEMINI_CANDIDATE_POINT_COUNT", 2)
    monkeypatch.setattr(subject, "M26_GEMINI_CANDIDATE_SOURCE_COUNT", 2)
    monkeypatch.setattr(subject, "M26_GEMINI_SEMANTIC_INPUTS_SHA256", _sha(semantic))
    monkeypatch.setattr(subject, "M26_GEMINI_LEXICAL_DOCUMENTS_SHA256", _sha(lexical))
    monkeypatch.setattr(subject, "M26_GEMINI_SOURCE_INDEX_SHA256", _sha(source))

    sections, loaded_lexical, loaded_sources, digests = subject._validate_exact_inputs(
        semantic, lexical, source
    )

    assert [item.section_id for item in sections] == ["s1", "s2"]
    assert [item["section_id"] for item in loaded_lexical] == ["s1", "s2"]
    assert len(loaded_sources) == 2
    assert digests["semantic_inputs_sha256"] == _sha(semantic)


def test_exact_input_loader_rejects_canonical_id_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    semantic = tmp_path / "semantic-inputs.jsonl"
    lexical = tmp_path / "lexical-documents.jsonl"
    source = tmp_path / "source-index.json"
    _write_jsonl(semantic, [{"section_id": "s1", "text": "alpha", "payload": {}}])
    _write_jsonl(lexical, [{"section_id": "other", "text": "alpha"}])
    source.write_text(
        json.dumps({"article_source_count": 1, "sources": [{"path": "a.md"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "M26_GEMINI_CANDIDATE_POINT_COUNT", 1)
    monkeypatch.setattr(subject, "M26_GEMINI_CANDIDATE_SOURCE_COUNT", 1)
    monkeypatch.setattr(subject, "M26_GEMINI_SEMANTIC_INPUTS_SHA256", _sha(semantic))
    monkeypatch.setattr(subject, "M26_GEMINI_LEXICAL_DOCUMENTS_SHA256", _sha(lexical))
    monkeypatch.setattr(subject, "M26_GEMINI_SOURCE_INDEX_SHA256", _sha(source))

    with pytest.raises(SystemExit, match="canonical section ID parity failed"):
        subject._validate_exact_inputs(semantic, lexical, source)


def test_exact_input_loader_rejects_wrong_bytes_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    semantic = tmp_path / "semantic-inputs.jsonl"
    lexical = tmp_path / "lexical-documents.jsonl"
    source = tmp_path / "source-index.json"
    semantic.write_text("not-json\n", encoding="utf-8")
    lexical.write_text("{}\n", encoding="utf-8")
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(subject, "M26_GEMINI_SEMANTIC_INPUTS_SHA256", "0" * 64)

    with pytest.raises(SystemExit, match="semantic-inputs SHA256 mismatch"):
        subject._validate_exact_inputs(semantic, lexical, source)
