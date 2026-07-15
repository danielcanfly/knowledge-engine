from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.compiler import compile_release
from knowledge_engine.publisher import publish_release
from knowledge_engine.storage import FileObjectStore

ROOT = Path(__file__).resolve().parents[1]
_M23_INGESTION_TEST_MODULE = "test_m23_6_2_qdrant_ingestion_manifest"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@pytest.fixture(autouse=True)
def freeze_synthetic_m23_ingestion_zip_headers(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the M23.6.2 synthetic evidence digest independent of wall-clock time.

    The production ingestion contract hashes immutable evidence bytes. Its synthetic
    test fixture created ZIP entries from bare names, which lets ``zipfile`` inject
    the current timestamp into each member header. Two otherwise identical fixture
    builds could therefore differ when they crossed ZIP's two-second time boundary.
    This patch is restricted to that test module and does not alter runtime code.
    """

    module = request.node.module
    if module is None or module.__name__.rsplit(".", 1)[-1] != _M23_INGESTION_TEST_MODULE:
        return

    original = zipfile.ZipFile.writestr

    def deterministic_writestr(
        archive: zipfile.ZipFile,
        zinfo_or_arcname: str | zipfile.ZipInfo,
        data: str | bytes,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> Any:
        if isinstance(zinfo_or_arcname, str):
            info = zipfile.ZipInfo(zinfo_or_arcname, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = archive.compression if compress_type is None else compress_type
            zinfo_or_arcname = info
        return original(
            archive,
            zinfo_or_arcname,
            data,
            compress_type=compress_type,
            compresslevel=compresslevel,
        )

    monkeypatch.setattr(zipfile.ZipFile, "writestr", deterministic_writestr)


@pytest.fixture
def built_store(tmp_path: Path):
    store = FileObjectStore(tmp_path / "store")
    compiled = compile_release(
        bundle_root=ROOT / "examples/okf-bundle",
        work_root=tmp_path / "builds",
        release_time=datetime(2026, 7, 2, 12, tzinfo=UTC),
        source_repository="danielcanfly/knowledge-source",
        source_commit_sha="a" * 40,
        foundation_commit_sha="d" * 40,
    )
    result = publish_release(
        store=store,
        compiled=compiled,
        channel="staging",
        promoted_at="2026-07-02T12:00:00Z",
    )
    return store, compiled, result
