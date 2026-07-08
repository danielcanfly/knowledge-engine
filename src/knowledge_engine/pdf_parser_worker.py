from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pypdf import PdfReader

PARSER_ID = "pypdf_text"
PARSER_VERSION = "6.14.2"


def _set_limits() -> None:
    try:
        import resource
    except ImportError:
        return

    memory_limit = int(os.environ.get("KNOWLEDGE_PDF_MAX_MEMORY_BYTES", str(512 * 1024 * 1024)))
    cpu_seconds = int(os.environ.get("KNOWLEDGE_PDF_MAX_CPU_SECONDS", "10"))
    output_limit = int(os.environ.get("KNOWLEDGE_PDF_MAX_OUTPUT_BYTES", str(16 * 1024 * 1024)))
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _page_markdown(page_number: int, text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return f"## Page {page_number}\n\n[No extractable text]\n"
    return f"## Page {page_number}\n\n{normalized}\n"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pdf_parser_worker INPUT_PDF OUTPUT_JSON", file=sys.stderr)
        return 2

    _set_limits()
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    try:
        reader = PdfReader(str(source), strict=True)
        if reader.is_encrypted:
            payload = {"ok": False, "code": "PDF_ENCRYPTED", "message": "PDF is encrypted"}
        else:
            pages = []
            total_chars = 0
            for index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                total_chars += len(text)
                pages.append(_page_markdown(index, text))
            markdown = ("# PDF Extraction\n\n" + "\n".join(pages)).encode("utf-8")
            payload = {
                "ok": True,
                "parser_id": PARSER_ID,
                "parser_version": PARSER_VERSION,
                "page_count": len(reader.pages),
                "extractable_character_count": total_chars,
                "markdown": markdown.decode("utf-8"),
            }
    except Exception as exc:
        payload = {
            "ok": False,
            "code": "PDF_PARSE_FAILED",
            "message": exc.__class__.__name__,
        }

    destination.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
