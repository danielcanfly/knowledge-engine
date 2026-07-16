from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

BUS_ISSUE_NUMBER = 565
OWNER_LOGIN = "huaihsuanbusiness"
COMMAND_PREFIX = "M23_OPERATOR_COMMAND "
AUTH_SCHEMA = "knowledge-engine-m23-operator-command-authorization/v1"
RECOVERY_COMMAND = "r3_8_post_delete_recovery"
R3_LIVE_COMMAND = "r3_live_reobservation"
ALLOWED_COMMAND_TYPES = {RECOVERY_COMMAND, R3_LIVE_COMMAND}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_AUTH_PATH = re.compile(
    r"^operator_authorizations/m23/[a-z0-9][a-z0-9/_-]{0,180}\.json$"
)
_RECOVERY_AUTH_KEYS = {
    "schema_version",
    "authorization_id",
    "command_type",
    "nonce",
    "bus_issue_number",
    "actor_login",
    "source_run_id",
    "source_engine_sha",
    "worker_name",
    "previous_deletion_authorization_path",
    "authority",
    "authorization_sha256",
}
_R3_LIVE_AUTH_KEYS = {
    "schema_version",
    "authorization_id",
    "command_type",
    "nonce",
    "bus_issue_number",
    "actor_login",
    "source_issue_number",
    "source_engine_sha",
    "worker_name_prefix",
    "authority",
    "authorization_sha256",
}
_COMMAND_KEYS = {"authorization_path", "expected_head", "nonce"}
_RECOVERY_AUTHORITY = {
    "control_plane_read_authorized": True,
    "worker_delete_authorized": False,
    "worker_deploy_authorized": False,
    "worker_secret_mutation_authorized": False,
    "worker_route_invocation_authorized": False,
    "qdrant_read_authorized": False,
    "qdrant_mutation_authorized": False,
    "r2_read_authorized": False,
    "r2_mutation_authorized": False,
    "pointer_mutation_authorized": False,
    "source_mutation_authorized": False,
    "blocker_clearance_authorized": False,
    "parent_closure_authorized": False,
    "m23_7_closure_authorized": False,
}
_R3_LIVE_AUTHORITY = {
    "control_plane_read_authorized": True,
    "worker_delete_authorized": True,
    "worker_deploy_authorized": True,
    "worker_secret_mutation_authorized": True,
    "worker_route_invocation_authorized": True,
    "qdrant_read_authorized": True,
    "qdrant_mutation_authorized": False,
    "r2_read_authorized": False,
    "r2_mutation_authorized": False,
    "pointer_mutation_authorized": False,
    "source_mutation_authorized": False,
    "blocker_clearance_authorized": False,
    "parent_closure_authorized": False,
    "m23_7_closure_authorized": False,
}


class OperatorCommandError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_command_body(body: str) -> dict[str, str]:
    if not body.startswith(COMMAND_PREFIX):
        raise OperatorCommandError("command_prefix_mismatch")
    raw = body[len(COMMAND_PREFIX) :]
    if not raw or "\n" in raw or "\r" in raw or len(raw) > 1000:
        raise OperatorCommandError("command_body_not_single_line")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OperatorCommandError("command_body_not_json") from exc
    if not isinstance(value, dict) or set(value) != _COMMAND_KEYS:
        raise OperatorCommandError("command_body_keys")
    if canonical_json(value) != raw:
        raise OperatorCommandError("command_body_not_canonical")
    expected_head = value.get("expected_head")
    nonce = value.get("nonce")
    auth_path = value.get("authorization_path")
    if not isinstance(expected_head, str) or not _HEX_40.fullmatch(expected_head):
        raise OperatorCommandError("command_expected_head")
    if not isinstance(nonce, str) or not _HEX_64.fullmatch(nonce):
        raise OperatorCommandError("command_nonce")
    if not isinstance(auth_path, str) or not _AUTH_PATH.fullmatch(auth_path):
        raise OperatorCommandError("command_authorization_path")
    return {
        "authorization_path": auth_path,
        "expected_head": expected_head,
        "nonce": nonce,
    }


def validate_event(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("action") != "created":
        raise OperatorCommandError("event_action")
    issue = value.get("issue")
    comment = value.get("comment")
    if not isinstance(issue, dict) or issue.get("number") != BUS_ISSUE_NUMBER:
        raise OperatorCommandError("event_issue")
    if not isinstance(comment, dict):
        raise OperatorCommandError("event_comment")
    user = comment.get("user")
    if not isinstance(user, dict) or user.get("login") != OWNER_LOGIN:
        raise OperatorCommandError("event_actor")
    if comment.get("author_association") != "OWNER":
        raise OperatorCommandError("event_actor_association")
    body = comment.get("body")
    if not isinstance(body, str):
        raise OperatorCommandError("event_comment_body")
    return parse_command_body(body)


def _safe_authorization_path(repo_root: Path, relative: str) -> Path:
    if not _AUTH_PATH.fullmatch(relative):
        raise OperatorCommandError("authorization_path")
    root = repo_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OperatorCommandError("authorization_path_escape") from exc
    if not path.is_file() or path.stat().st_size > 50_000:
        raise OperatorCommandError("authorization_file_missing_or_oversized")
    return path


def validate_authorization(
    path: Path,
    *,
    expected_nonce: str,
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorCommandError("authorization_not_json") from exc
    if not isinstance(value, dict):
        raise OperatorCommandError("authorization_keys")
    if value.get("schema_version") != AUTH_SCHEMA:
        raise OperatorCommandError("authorization_schema")
    command_type = value.get("command_type")
    if command_type == RECOVERY_COMMAND:
        expected_keys = _RECOVERY_AUTH_KEYS
    elif command_type == R3_LIVE_COMMAND:
        expected_keys = _R3_LIVE_AUTH_KEYS
    else:
        raise OperatorCommandError("authorization_command_type")
    if set(value) != expected_keys:
        raise OperatorCommandError("authorization_keys")
    stored = value.get("authorization_sha256")
    unsigned = dict(value)
    unsigned.pop("authorization_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise OperatorCommandError("authorization_digest")
    if value.get("nonce") != expected_nonce or not _HEX_64.fullmatch(expected_nonce):
        raise OperatorCommandError("authorization_nonce")
    if value.get("bus_issue_number") != BUS_ISSUE_NUMBER:
        raise OperatorCommandError("authorization_issue")
    if value.get("actor_login") != OWNER_LOGIN:
        raise OperatorCommandError("authorization_actor")
    expected_authority = (
        _RECOVERY_AUTHORITY if command_type == RECOVERY_COMMAND else _R3_LIVE_AUTHORITY
    )
    if value.get("authority") != expected_authority:
        raise OperatorCommandError("authorization_boundary")
    if command_type == RECOVERY_COMMAND:
        if value.get("source_run_id") != "29521901629":
            raise OperatorCommandError("authorization_source_run")
        if value.get("source_engine_sha") != "542907fa0cfae47addd6d777c1708ae62155aea4":
            raise OperatorCommandError("authorization_source_engine")
        if value.get("worker_name") != "knowledge-engine-r3-8-29506217284":
            raise OperatorCommandError("authorization_worker")
        if value.get("previous_deletion_authorization_path") != (
            "deletion_authorizations/m23-7/r3-8/"
            "knowledge-engine-r3-8-29506217284.json"
        ):
            raise OperatorCommandError("authorization_lineage")
    else:
        source_pair = (
            value.get("source_issue_number"),
            value.get("source_engine_sha"),
        )
        if source_pair not in {
            (595, "ddac861f648a130db6af5a293c6d5af291226382"),
            (599, "8205c9fb2b3d58e91eec8b631b6d9caf46b047ca"),
            (602, "07118f15f6fc49f2fc80c38d090ac9a8ae44ddb1"),
            (607, "dee2a17adabb158fff20027e9a282c46a7f5c5d5"),
            (612, "e9d24cbbe742c19942086dcda53f7295ff0a1be2"),
        }:
            raise OperatorCommandError("authorization_source_lineage")
        if value.get("worker_name_prefix") != "knowledge-engine-m23-7-r3-live":
            raise OperatorCommandError("authorization_worker_prefix")
    return value


def validate_command(
    *,
    event_path: Path,
    repo_root: Path,
    actual_head: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    if not _HEX_40.fullmatch(actual_head):
        raise OperatorCommandError("actual_head")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    command = validate_event(event)
    if command["expected_head"] != actual_head:
        raise OperatorCommandError("command_exact_head_mismatch")
    auth_path = _safe_authorization_path(repo_root, command["authorization_path"])
    auth = validate_authorization(auth_path, expected_nonce=command["nonce"])
    return command, auth


def _write_output(path: Path, key: str, value: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate governed M23 operator command")
    parser.add_argument("--event-path", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--actual-head", required=True)
    parser.add_argument("--github-output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        command, auth = validate_command(
            event_path=Path(args.event_path),
            repo_root=Path(args.repo_root),
            actual_head=args.actual_head,
        )
    except (OperatorCommandError, OSError, json.JSONDecodeError):
        return 23
    output = Path(args.github_output)
    _write_output(output, "authorization_path", command["authorization_path"])
    _write_output(output, "expected_head", command["expected_head"])
    _write_output(output, "nonce", command["nonce"])
    _write_output(output, "command_type", auth["command_type"])
    _write_output(output, "authorization_sha256", auth["authorization_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
