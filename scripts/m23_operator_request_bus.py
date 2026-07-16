from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from scripts.m23_operator_command_bus import (
    OperatorCommandError,
    canonical_json,
    canonical_sha256,
    validate_authorization,
)

REQUEST_SCHEMA = "knowledge-engine-m23-operator-request/v1"
REQUEST_ROOT = "operator_requests/m23/"
ALLOWED_COMMAND_TYPES = {"r3_8_post_delete_recovery"}
BUS_ISSUE_NUMBER = 565
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_REQUEST_PATH = re.compile(
    r"^operator_requests/m23/[a-z0-9][a-z0-9/_-]{0,180}\.json$"
)
_REQUEST_KEYS = {
    "schema_version",
    "request_id",
    "command_type",
    "authorization_path",
    "nonce",
    "expected_base_sha",
    "status_issue_number",
    "request_sha256",
}


class OperatorRequestError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def find_single_added_request(repo_root: Path, before: str, after: str) -> str:
    if not _HEX_40.fullmatch(before) or not _HEX_40.fullmatch(after) or before == after:
        raise OperatorRequestError("request_diff_identity")
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--find-renames=0",
            before,
            after,
            "--",
            REQUEST_ROOT,
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise OperatorRequestError("request_diff_failure")
    rows = [line for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise OperatorRequestError("request_diff_count")
    parts = rows[0].split("\t")
    if len(parts) != 2 or parts[0] != "A":
        raise OperatorRequestError("request_not_single_addition")
    path = parts[1]
    if not _REQUEST_PATH.fullmatch(path):
        raise OperatorRequestError("request_path")
    return path


def _safe_file(repo_root: Path, relative: str) -> Path:
    if not _REQUEST_PATH.fullmatch(relative):
        raise OperatorRequestError("request_path")
    root = repo_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OperatorRequestError("request_path_escape") from exc
    if not path.is_file() or path.stat().st_size > 50_000:
        raise OperatorRequestError("request_file_missing_or_oversized")
    return path


def validate_request(
    path: Path,
    *,
    expected_base_sha: str,
) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorRequestError("request_not_json") from exc
    if not isinstance(value, dict) or set(value) != _REQUEST_KEYS:
        raise OperatorRequestError("request_keys")
    if text != canonical_json(value) + "\n":
        raise OperatorRequestError("request_not_canonical")
    if value.get("schema_version") != REQUEST_SCHEMA:
        raise OperatorRequestError("request_schema")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise OperatorRequestError("request_id")
    if path.stem != request_id:
        raise OperatorRequestError("request_id_path_mismatch")
    if value.get("command_type") not in ALLOWED_COMMAND_TYPES:
        raise OperatorRequestError("request_command_type")
    if value.get("expected_base_sha") != expected_base_sha:
        raise OperatorRequestError("request_base_sha")
    if value.get("status_issue_number") != BUS_ISSUE_NUMBER:
        raise OperatorRequestError("request_status_issue")
    nonce = value.get("nonce")
    if not isinstance(nonce, str) or not _HEX_64.fullmatch(nonce):
        raise OperatorRequestError("request_nonce")
    authorization_path = value.get("authorization_path")
    if not isinstance(authorization_path, str):
        raise OperatorRequestError("request_authorization_path")
    stored = value.get("request_sha256")
    unsigned = dict(value)
    unsigned.pop("request_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise OperatorRequestError("request_digest")
    return value


def validate_push_request(
    *,
    repo_root: Path,
    before: str,
    after: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    relative = find_single_added_request(repo_root, before, after)
    request_path = _safe_file(repo_root, relative)
    request = validate_request(request_path, expected_base_sha=before)
    auth_path = (repo_root.resolve() / request["authorization_path"]).resolve()
    try:
        auth_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise OperatorRequestError("request_authorization_escape") from exc
    try:
        auth = validate_authorization(auth_path, expected_nonce=request["nonce"])
    except OperatorCommandError as exc:
        raise OperatorRequestError("request_authorization_" + exc.code) from exc
    if auth.get("command_type") != request.get("command_type"):
        raise OperatorRequestError("request_authorization_command_mismatch")
    return relative, request, auth


def _write_output(path: Path, key: str, value: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate M23 merge-triggered request")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--github-output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        relative, request, auth = validate_push_request(
            repo_root=Path(args.repo_root),
            before=args.before,
            after=args.after,
        )
    except (OperatorRequestError, OSError, json.JSONDecodeError):
        return 23
    output = Path(args.github_output)
    _write_output(output, "request_path", relative)
    _write_output(output, "request_sha256", request["request_sha256"])
    _write_output(output, "authorization_path", request["authorization_path"])
    _write_output(output, "authorization_sha256", auth["authorization_sha256"])
    _write_output(output, "nonce", request["nonce"])
    _write_output(output, "command_type", request["command_type"])
    _write_output(output, "expected_head", args.after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
