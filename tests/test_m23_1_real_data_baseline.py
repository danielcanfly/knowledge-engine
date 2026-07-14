from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.knowledge_engine.errors import IntegrityError
from src.knowledge_engine.m23_real_data_baseline import validate_real_data_baseline

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "pilot" / "m23" / "m23-1-corpus-manifest.json"
QUERIES_PATH = ROOT / "pilot" / "m23" / "m23-1-golden-queries.json"


def _digest(value: dict, key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load() -> tuple[dict, dict]:
    return (
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
        json.loads(QUERIES_PATH.read_text(encoding="utf-8")),
    )


def test_m23_1_accepts_exact_upload_baseline() -> None:
    manifest, queries = _load()
    result = validate_real_data_baseline(manifest, queries)

    assert result["accepted"] is True
    assert len(result["corpus"]["documents"]) == 6
    assert len(result["golden_queries"]["queries"]) >= 12
    assert len(result["baseline_digest"]) == 64


def test_m23_1_rejects_duplicate_content_digest() -> None:
    manifest, queries = _load()
    tampered = copy.deepcopy(manifest)
    tampered["documents"][1]["sha256"] = tampered["documents"][0]["sha256"]
    tampered["manifest_digest"] = _digest(tampered, "manifest_digest")

    with pytest.raises(IntegrityError, match="duplicate content digest"):
        validate_real_data_baseline(tampered, queries)


def test_m23_1_rejects_nonreciprocal_counterpart() -> None:
    manifest, queries = _load()
    tampered = copy.deepcopy(manifest)
    tampered["documents"][0]["counterpart_document_id"] = "harness-theory-part-02-en"
    tampered["manifest_digest"] = _digest(tampered, "manifest_digest")

    with pytest.raises(IntegrityError, match="counterpart"):
        validate_real_data_baseline(tampered, queries)


def test_m23_1_rejects_fabricated_repository_identity() -> None:
    manifest, queries = _load()
    tampered = copy.deepcopy(manifest)
    tampered["documents"][0]["repository"] = "danielcanfly/unverified-blog"
    tampered["manifest_digest"] = _digest(tampered, "manifest_digest")

    with pytest.raises(IntegrityError, match="fabricated"):
        validate_real_data_baseline(tampered, queries)


def test_m23_1_rejects_missing_query_class() -> None:
    manifest, queries = _load()
    tampered = copy.deepcopy(queries)
    tampered["queries"] = [item for item in tampered["queries"] if item["class"] != "dependency"]
    tampered["golden_query_digest"] = _digest(tampered, "golden_query_digest")

    with pytest.raises(IntegrityError, match="coverage"):
        validate_real_data_baseline(manifest, tampered)


def test_m23_1_rejects_manifest_query_binding_drift() -> None:
    manifest, queries = _load()
    tampered = copy.deepcopy(queries)
    tampered["corpus_manifest_digest"] = "0" * 64

    with pytest.raises(IntegrityError, match="binding mismatch"):
        validate_real_data_baseline(manifest, tampered)
