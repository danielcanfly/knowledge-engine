from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_engine import m23_7_r3_3_offline_rebuild_evaluation_real as compat


def _documents() -> list[dict[str, Any]]:
    return [
        {
            "row": row,
            "section_id": f"section-{row:03d}",
            "concept_id": f"concept-{row:03d}",
            "language": "en",
            "title": f"Title {row:03d}",
            "text": f"Text {row:03d}",
            "text_sha256": f"{row:064x}"[-64:],
            "source_path": f"docs/{row:03d}.md",
            "source_sha256": f"{row + 1:064x}"[-64:],
            "audience": "public",
        }
        for row in range(compat.EXPECTED_POINT_COUNT)
    ]


class _Archive:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.pilot = b"p" * compat.EXPECTED_VECTOR_BYTES
        self.semantic = b"s" * compat.EXPECTED_VECTOR_BYTES
        self.members = {
            "evidence/run-receipt.json": json.dumps({"files": {}}).encode(),
            "evidence/benchmark-suite.json": json.dumps(
                {
                    "identities": {
                        "source_commit_sha": "a" * 40,
                        "foundation_commit_sha": "b" * 40,
                    }
                }
            ).encode(),
            "evidence/pilot-document-vectors.f32": self.pilot,
            "evidence/semantic-artifact/semantic-metadata.json": b"semantic-metadata",
            "evidence/semantic-artifact/semantic-vectors.f32": self.semantic,
            "evidence/benchmark-results.json": b"benchmark-results",
        }

    def __enter__(self) -> _Archive:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def namelist(self) -> list[str]:
        return list(self.members)

    def read(self, name: str) -> bytes:
        return self.members[name]


def test_real_loader_accepts_distinct_provider_generations(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    documents = _documents()
    pilot_vectors = [(1.0,) + (0.0,) * (compat.VECTOR_DIMENSION - 1)] * len(documents)
    semantic_vectors = [(0.0, 1.0) + (0.0,) * (compat.VECTOR_DIMENSION - 2)] * len(
        documents
    )
    sidecar_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(compat, "file_sha256", lambda _path: compat.EXPECTED_EVIDENCE_SHA256)
    monkeypatch.setattr(compat.zipfile, "ZipFile", _Archive)
    monkeypatch.setattr(compat, "_archive_root", lambda _names: "evidence")
    monkeypatch.setattr(compat, "_validate_receipt", lambda _receipt: None)
    monkeypatch.setattr(compat, "_receipt_files", lambda *_args: {"validated": {}})
    monkeypatch.setattr(compat, "_validate_suite", lambda *_args: documents)

    def read_json(data: bytes, _label: str) -> dict[str, Any]:
        if data == b"semantic-metadata":
            return {"kind": "semantic"}
        if data == b"benchmark-results":
            return {"kind": "results"}
        return json.loads(data)

    monkeypatch.setattr(compat, "_read_json_bytes", read_json)

    def unpack(data: bytes, _count: int) -> list[tuple[float, ...]]:
        return pilot_vectors if data.startswith(b"p") else semantic_vectors

    monkeypatch.setattr(compat, "_unpack_vectors", unpack)

    def validate_sidecar(
        metadata: Any,
        semantic_bytes: bytes,
        suite: Any,
        benchmark_results: Any,
        observed_documents: Any,
        *,
        expected_artifact_id: str,
    ) -> None:
        sidecar_calls.append(
            {
                "metadata": metadata,
                "semantic_bytes": semantic_bytes,
                "suite": suite,
                "benchmark_results": benchmark_results,
                "documents": observed_documents,
                "artifact": expected_artifact_id,
            }
        )

    monkeypatch.setattr(compat, "_validate_semantic_sidecar", validate_sidecar)

    result = compat._load_inputs(tmp_path / "evidence.zip")

    assert result["vectors"] is pilot_vectors
    assert result["vector_sha256"] != result["semantic_vector_sha256"]
    assert len(sidecar_calls) == 1
    assert sidecar_calls[0]["semantic_bytes"].startswith(b"s")
    assert sidecar_calls[0]["benchmark_results"] == {"kind": "results"}
    assert sidecar_calls[0]["documents"] is documents


def test_operator_routes_through_real_evidence_module() -> None:
    source = Path("scripts/m23_7_r3_3_offline_rebuild_operator.py").read_text(
        encoding="utf-8"
    )
    assert "m23_7_r3_3_offline_rebuild_evaluation_real" in source
    assert "from knowledge_engine.m23_7_r3_3_offline_rebuild_evaluation import" not in source
