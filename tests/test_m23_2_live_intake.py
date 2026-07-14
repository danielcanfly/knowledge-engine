from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_live_intake import (
    M23_1_MANIFEST_DIGEST,
    execute_live_intake,
    validate_execution_receipt,
    validate_https_capture,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(source_root: Path) -> dict:
    documents = []
    for part in range(1, 4):
        for language in ("zh-TW", "en"):
            document_id = f"part-{part}-{language.lower()}"
            filename = f"{document_id}.md"
            data = f"# Part {part} {language}\n\nBody {part} {language}.\n".encode()
            (source_root / filename).write_bytes(data)
            documents.append(
                {
                    "document_id": document_id,
                    "upload_id": f"upload-{document_id}",
                    "original_filename": filename,
                    "sha256": _sha(data),
                    "byte_length": len(data),
                    "language": language,
                    "title": f"Part {part} {language}",
                    "audience": "public",
                }
            )
    return {"manifest_digest": M23_1_MANIFEST_DIGEST, "documents": documents}


def _allow_synthetic_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "knowledge_engine.m23_live_intake.validate_corpus_manifest",
        lambda value: value,
    )


def test_executes_six_items_and_replays_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_synthetic_manifest(monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    manifest = _manifest(source_root)
    evidence_root = tmp_path / "evidence"

    first = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
    )
    replay = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
    )

    assert first == replay
    assert first["status"] == "completed"
    assert first["completed_count"] == 6
    assert len({item["capture_id"] for item in first["results"]}) == 6
    assert all(item["canonical_write_permitted"] is False for item in first["results"])


def test_failed_item_requires_explicit_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_synthetic_manifest(monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    manifest = _manifest(source_root)
    first_document = manifest["documents"][0]
    first_path = source_root / first_document["original_filename"]
    original = first_path.read_bytes()
    first_path.write_text("tampered\n", encoding="utf-8")
    evidence_root = tmp_path / "evidence"

    partial = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
    )
    first_path.write_bytes(original)
    no_retry = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
    )
    completed = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
        retry_failed=True,
    )

    assert partial["status"] == "partial"
    assert partial["failed_count"] == 1
    assert no_retry == partial
    assert completed["status"] == "completed"
    assert completed["completed_count"] == 6


def test_rejects_checkpoint_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_synthetic_manifest(monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    manifest = _manifest(source_root)
    evidence_root = tmp_path / "evidence"
    receipt = execute_live_intake(
        corpus_manifest=manifest,
        source_root=source_root,
        evidence_root=evidence_root,
        retrieved_at="2026-07-14T09:15:00Z",
        owner="Daniel Huang",
        license_name="owner-provided",
    )
    checkpoint_path = (
        evidence_root / "batches" / receipt["batch_id"] / "checkpoint.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["revision"] += 1
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises(IntegrityError, match="checkpoint digest mismatch"):
        execute_live_intake(
            corpus_manifest=manifest,
            source_root=source_root,
            evidence_root=evidence_root,
            retrieved_at="2026-07-14T09:15:00Z",
            owner="Daniel Huang",
            license_name="owner-provided",
        )


def test_validates_committed_real_execution_receipt() -> None:
    root = Path(__file__).resolve().parents[1]
    receipt = json.loads(
        (root / "pilot" / "m23" / "m23-2-live-intake-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    validated = validate_execution_receipt(receipt)
    assert validated["status"] == "completed"
    assert validated["completed_count"] == 6
    assert validated["filesystem_evidence_written"] is True


def test_https_capture_accepts_bounded_allowlisted_markdown() -> None:
    result = validate_https_capture(
        initial_url="https://docs.example.com/article.md",
        final_url="https://docs.example.com/article.md",
        redirect_chain=[],
        allowed_hosts={"docs.example.com"},
        content_type="text/markdown; charset=utf-8",
        body=b"# Article\n",
    )
    assert result["credentials_sent"] is False
    assert result["content_type"] == "text/markdown"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "initial_url": "http://docs.example.com/article.md",
                "final_url": "http://docs.example.com/article.md",
                "redirect_chain": [],
            },
            "HTTPS source is invalid",
        ),
        (
            {
                "initial_url": "https://127.0.0.1/article.md",
                "final_url": "https://127.0.0.1/article.md",
                "redirect_chain": [],
                "allowed_hosts": {"127.0.0.1"},
            },
            "private or reserved IP literal",
        ),
        (
            {
                "initial_url": "https://docs.example.com/a",
                "final_url": "https://docs.example.com/e",
                "redirect_chain": [
                    "https://docs.example.com/b",
                    "https://docs.example.com/c",
                    "https://docs.example.com/d",
                    "https://docs.example.com/e",
                ],
            },
            "redirect limit exceeded",
        ),
    ],
)
def test_https_capture_rejects_unsafe_routes(kwargs: dict, message: str) -> None:
    base = {
        "allowed_hosts": {"docs.example.com"},
        "content_type": "text/markdown",
        "body": b"# Article\n",
    }
    base.update(kwargs)
    with pytest.raises(IntegrityError, match=message):
        validate_https_capture(**base)


def test_https_capture_rejects_media_and_byte_violations() -> None:
    common = {
        "initial_url": "https://docs.example.com/article.md",
        "final_url": "https://docs.example.com/article.md",
        "redirect_chain": [],
        "allowed_hosts": {"docs.example.com"},
    }
    with pytest.raises(IntegrityError, match="media type"):
        validate_https_capture(
            **common,
            content_type="application/octet-stream",
            body=b"payload",
        )
    with pytest.raises(IntegrityError, match="exceeds bounds"):
        validate_https_capture(
            **common,
            content_type="text/plain",
            body=b"12345",
            max_bytes=4,
        )


def test_receipt_rejects_authority_drift() -> None:
    root = Path(__file__).resolve().parents[1]
    receipt = json.loads(
        (root / "pilot" / "m23" / "m23-2-live-intake-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    tampered = copy.deepcopy(receipt)
    tampered["production_authority"] = True
    unsigned = {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    encoded = (
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    tampered["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    with pytest.raises(IntegrityError, match="authority drift"):
        validate_execution_receipt(tampered)
