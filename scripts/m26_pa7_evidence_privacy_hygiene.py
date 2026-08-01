#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from email.parser import Parser
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_PUBLIC_DENIAL = "knowledge-engine-m26-pa7-public-denial-sanitized/v1"
SCHEMA_SCAN = "knowledge-engine-m26-pa7-evidence-privacy-scan/v1"

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("set_cookie_header", re.compile(r"(?im)^set-cookie\s*:")),
    ("authorization_header", re.compile(r"(?im)^authorization\s*:")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "jwt_like_value",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    (
        "cloudflare_access_login_metadata",
        re.compile(r"(?i)/cdn-cgi/access/login[^\s\"'<>]*[?&](?:kid|meta|redirect_url)="),
    ),
    (
        "raw_secret_true_field",
        re.compile(
            r'(?i)"raw_[^"]*(?:token|cookie|jwt|authorization|auth_header)[^"]*"\s*:\s*true'
        ),
    ),
    (
        "known_api_key_form",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,})\b"),
    ),
)

_TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".headers",
    ".html",
    ".js",
    ".json",
    ".log",
    ".md",
    ".status",
    ".stderr",
    ".txt",
    ".xml",
    ".yml",
    ".yaml",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _header_message(headers_text: str):
    normalized = headers_text.replace("\r\n", "\n")
    blocks = [block for block in normalized.split("\n\n") if block.strip()]
    header_lines: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            if ":" in line:
                header_lines.append(line)
    return Parser().parsestr("\n".join(header_lines) + "\n")


def build_public_denial_evidence(
    *,
    http_status: int,
    headers_text: str,
    body_text: str = "",
) -> dict[str, object]:
    message = _header_message(headers_text)
    location = message.get("Location") or message.get("location") or ""
    parsed_location = urlparse(location) if location else None
    location_path = parsed_location.path if parsed_location else ""
    location_host = (parsed_location.hostname or "").lower() if parsed_location else ""
    marker_text = f"{headers_text}\n{body_text}".lower()
    access_marker_present = any(
        marker in marker_text
        for marker in ("cloudflare", "access", "login", "forbidden", "denied")
    )
    redirect_class = "none"
    if http_status in {301, 302, 303, 307, 308}:
        if location_path.startswith("/cdn-cgi/access/login"):
            redirect_class = "cloudflare_access_login"
        elif "cloudflare" in marker_text or "access" in marker_text:
            redirect_class = "cloudflare_access_redirect"
        else:
            redirect_class = "http_redirect"
    elif http_status in {401, 403}:
        redirect_class = "forbidden_or_unauthorized"
    elif http_status != 200:
        redirect_class = "non_200_denial"

    return {
        "schema_version": SCHEMA_PUBLIC_DENIAL,
        "http_status": http_status,
        "access_denied": http_status != 200 and access_marker_present,
        "redirect_class": redirect_class,
        "redirect_host_sha256": sha256_text(location_host) if location_host else None,
        "location_header_present": bool(location),
        "www_authenticate_present": bool(message.get("WWW-Authenticate")),
        "set_cookie_present": bool(message.get("Set-Cookie")),
        "access_marker_present": access_marker_present,
        "raw_header_values_recorded": False,
        "raw_location_recorded": False,
        "raw_cookie_recorded": False,
        "raw_jwt_recorded": False,
        "raw_token_recorded": False,
        "raw_response_body_recorded": False,
    }


def scan_text(text: str) -> list[str]:
    return [name for name, pattern in _SECRET_PATTERNS if pattern.search(text)]


def _iter_scannable_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*") if path.is_file())


def _read_text_for_scan(path: Path) -> str | None:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def scan_evidence_path(path: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    files_scanned = 0
    bytes_scanned = 0
    for file_path in _iter_scannable_files(path):
        text = _read_text_for_scan(file_path)
        if text is None:
            continue
        files_scanned += 1
        bytes_scanned += len(text.encode("utf-8", "replace"))
        classes = scan_text(text)
        if classes:
            findings.append(
                {
                    "path_sha256": sha256_text(file_path.as_posix()),
                    "relative_path": (
                        file_path.relative_to(path).as_posix()
                        if path.is_dir()
                        else file_path.name
                    ),
                    "violation_classes": classes,
                }
            )
    return {
        "schema_version": SCHEMA_SCAN,
        "status": "pass" if not findings else "fail",
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "violations": len(findings),
        "findings": findings,
        "raw_secret_values_recorded": False,
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_optional_text(path: str | None) -> str:
    if not path:
        return ""
    optional_path = Path(path)
    if not optional_path.exists():
        return ""
    return optional_path.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    denial = subparsers.add_parser("public-denial")
    denial.add_argument("--status", required=True, type=int)
    denial.add_argument("--headers", required=True)
    denial.add_argument("--body")
    denial.add_argument("--output", required=True)
    denial.add_argument("--status-output")
    scan = subparsers.add_parser("scan")
    scan.add_argument("--path", required=True)
    scan.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    if args.command == "public-denial":
        headers_text = Path(args.headers).read_text(encoding="utf-8", errors="replace")
        body_text = _read_optional_text(args.body)
        evidence = build_public_denial_evidence(
            http_status=args.status,
            headers_text=headers_text,
            body_text=body_text,
        )
        _write_json(Path(args.output), evidence)
        if args.status_output:
            Path(args.status_output).write_text(f"{args.status}\n", encoding="utf-8")
        if not evidence["access_denied"]:
            raise SystemExit("public_denial_not_proven")
        return 0

    result = scan_evidence_path(Path(args.path))
    _write_json(Path(args.output), result)
    if result["status"] != "pass":
        raise SystemExit("evidence_privacy_scan_failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
