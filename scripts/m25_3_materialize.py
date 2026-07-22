from __future__ import annotations

import hashlib
import io
import tarfile
import zlib
from pathlib import Path

ARCHIVE_SHA256 = "e66422869497f17721992d740f904f024f7dbb24a88409d464786575ab188773"
ROOT = Path(__file__).resolve().parents[1]


def _extract() -> None:
    parts = sorted((ROOT / "scripts").glob("m25_3_payload_*.hex"))
    payload = "".join(path.read_text(encoding="utf-8").strip() for path in parts)
    raw = zlib.decompress(bytes.fromhex(payload))
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit("M25.3 materialization payload digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            target = (ROOT / member.name).resolve()
            target.relative_to(ROOT.resolve())
            if not member.isfile():
                raise SystemExit(f"unsupported payload member: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"missing payload bytes: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
    for path in parts:
        path.unlink()


def _patch_pyproject() -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    entry = 'knowledge-m25-extraction = "knowledge_engine.m25_extraction_cli:main"'
    if entry not in text:
        anchor = 'knowledge-m25-admission = "knowledge_engine.m25_intake_orchestrator_cli:main"'
        if anchor not in text:
            raise SystemExit("M25.2 CLI anchor missing from pyproject.toml")
        text = text.replace(anchor, anchor + "\n" + entry)
    ignore = '"tests/test_m25_3_extraction_worker.py" = ["E501"]'
    if ignore not in text:
        anchor = '"tests/test_m23_6_3_first_pilot_upsert.py" = ["E501", "I001"]'
        if anchor not in text:
            raise SystemExit("ruff ignore anchor missing from pyproject.toml")
        text = text.replace(anchor, anchor + "\n" + ignore)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    _extract()
    _patch_pyproject()
    (ROOT / ".github" / "workflows" / "m25-3-bootstrap.yml").unlink()
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
