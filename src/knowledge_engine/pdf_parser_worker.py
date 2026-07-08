from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PARSER_ID = "pypdf_text"
PARSER_VERSION = "6.14.2"


def _set_limits() -> None:
    try:
        import resource
    except ImportError:
        return

    memory_limit = int(os.environ["KNOWLEDGE_PDF_MAX_MEMORY_BYTES"])
    cpu_seconds = int(os.environ["KNOWLEDGE_PDF_MAX_CPU_SECONDS"])
    output_limit = int(os.environ["KNOWLEDGE_PDF_MAX_OUTPUT_BYTES"])
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _page_markdown(page_number: int, text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return f"## Page {page_number}\n\n[No extractable text]\n"
    return f"## Page {page_number}\n\n{normalized}\n"


def _failure(code: str, message: str) -> dict[str, object]:
    return {"ok": False, "code": code, "message": message}


def _write_payload(destination: Path, payload: dict[str, object]) -> None:
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pdf_parser_worker INPUT_PDF OUTPUT_JSON", file=sys.stderr)
        return 2

    _set_limits()
    from pypdf import PdfReader, __version__ as pypdf_version

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    max_pages = int(os.environ["KNOWLEDGE_PDF_MAX_PAGES"])
    max_output_bytes = int(os.environ["KNOWLEDGE_PDF_MAX_DERIVATIVE_BYTES"])

    try:
        reader = PdfReader(str(source), strict=True)
        if reader.is_encrypted:
            payload = _failure("PDF_ENCRYPTED", "PDF is encrypted")
        else:
            page_count = len(reader.pages)
            if page_count < 1:
                payload = _failure("PDF_EMPTY", "PDF has no pages")
            elif page_count > max_pages:
                payload = _failure("PDF_PAGE_LIMIT", "PDF page count exceeds policy")
            else:
                sections: list[str] = []
                total_chars = 0
                output_bytes = len("# PDF Extraction\n\n".encode("utf-8"))
                for index, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    total_chars += len(text)
                    section = _page_markdown(index, text)
                    output_bytes += len(section.encode("utf-8")) + 1
                    if output_bytes > max_output_bytes:
                        payload = _failure(
                            "PDF_DERIVATIVE_TOO_LARGE",
                            "PDF derivative exceeds maximum bytes",
                        )
                        break
                    sections.append(section)
                else:
                    markdown = "# PDF Extraction\n\n" + "\n".join(sections)
                    payload = {
                        "ok": True,
                        "parser_id": PARSER_ID,
                        "parser_version": PARSER_VERSION,
                        "library_version": pypdf_version,
                        "page_count": page_count,
                        "extractable_character_count": total_chars,
                        "markdown": markdown,
                    }
    except MemoryError:
        payload = _failure("PDF_PARSER_MEMORY_LIMIT", "PDF parser exceeded memory policy")
    except Exception as exc:
        payload = _failure("PDF_PARSE_FAILED", exc.__class__.__name__)

    try:
        _write_payload(destination, payload)
    except OSError:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
