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
from scripts.m23_operator_request_bus import validate_request

REQUEST_ROOT = "operator_requests/m23/"
PERMIT_ROOT = "operator_permits/m23/"
PERMIT_SCHEMA = "knowledge-engine-m23-operator-permit/v1"
ALLOWED_COMMAND_TYPES = {"r3_8_post_delete_recovery"}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_PATH = re.compile(
    r"^operator_requests/m23/[a-z0-9][a-z0-9/_-]{0,180}\.json$"
)
_PERMIT_PATH = re.compile(
    r"^operator_permits/m23/[a-z0-9][a-z0-9/_-]{0,180}\.json$"
)
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")
_PERMIT_KEYS = {
    "schema_version",
    "permit_id",
    "command_type",
    "request_path",
    "request_sha256",
    "validated_request_head_sha",
    "expected_base_sha",
    "authorization_sha256",
    "permit_nonce",
    "validation_runs",
    "authority",
    "permit_sha256",
}
_RUN_KEYS = {"request_validation", "ci", "m18"}
_EXPECTED_PERMIT_AUTHORITY = {
    "read_only_recovery_execute_authorized": True,
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


class OperatorPermitError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise OperatorPermitError("git_command_failure")
    return result.stdout.strip()


def _safe(repo: Path, relative: str, pattern: re.Pattern[str]) -> Path:
    if not pattern.fullmatch(relative):
        raise OperatorPermitError("bounded_path_invalid")
    root = repo.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OperatorPermitError("bounded_path_escape") from exc
    if not path.is_file() or path.stat().st_size > 50_000:
        raise OperatorPermitError("bounded_file_missing_or_oversized")
    return path


def _operator_rows(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = _git(
        repo,
        [
            "diff",
            "--name-status",
            "--find-renames=0",
            base,
            head,
            "--",
            REQUEST_ROOT,
            PERMIT_ROOT,
        ],
    )
    rows: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise OperatorPermitError("operator_diff_shape")
        rows.append((parts[0], parts[1]))
    return rows


def _changed_paths(repo: Path, base: str, head: str) -> list[str]:
    raw = _git(repo, ["diff", "--name-only", base, head])
    return sorted(line for line in raw.splitlines() if line.strip())


def _single_parent(repo: Path, head: str) -> str:
    parts = _git(repo, ["rev-list", "--parents", "-n", "1", head]).split()
    if len(parts) != 2 or parts[0] != head or not _HEX_40.fullmatch(parts[1]):
        raise OperatorPermitError("permit_head_not_single_parent")
    return parts[1]


def _validate_runs(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _RUN_KEYS:
        raise OperatorPermitError("permit_validation_runs")
    run_ids = list(value.values())
    if any(not isinstance(run_id, int) or run_id <= 0 for run_id in run_ids):
        raise OperatorPermitError("permit_validation_run_ids")
    if len(set(run_ids)) != len(run_ids):
        raise OperatorPermitError("permit_validation_run_ids")


def validate_permit(
    path: Path,
    *,
    expected_base_sha: str,
    request_path: str,
    request: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorPermitError("permit_not_json") from exc
    if not isinstance(value, dict) or set(value) != _PERMIT_KEYS:
        raise OperatorPermitError("permit_keys")
    if text != canonical_json(value) + "\n":
        raise OperatorPermitError("permit_not_canonical")
    if value.get("schema_version") != PERMIT_SCHEMA:
        raise OperatorPermitError("permit_schema")
    permit_id = value.get("permit_id")
    if not isinstance(permit_id, str) or not _ID.fullmatch(permit_id):
        raise OperatorPermitError("permit_id")
    if path.stem != permit_id:
        raise OperatorPermitError("permit_id_path_mismatch")
    if value.get("command_type") not in ALLOWED_COMMAND_TYPES:
        raise OperatorPermitError("permit_command_type")
    if value.get("command_type") != request.get("command_type"):
        raise OperatorPermitError("permit_request_command_mismatch")
    if value.get("request_path") != request_path:
        raise OperatorPermitError("permit_request_path")
    if value.get("request_sha256") != request.get("request_sha256"):
        raise OperatorPermitError("permit_request_digest")
    if value.get("expected_base_sha") != expected_base_sha:
        raise OperatorPermitError("permit_base_sha")
    if value.get("authorization_sha256") != authorization.get(
        "authorization_sha256"
    ):
        raise OperatorPermitError("permit_authorization_digest")
    request_head = value.get("validated_request_head_sha")
    if not isinstance(request_head, str) or not _HEX_40.fullmatch(request_head):
        raise OperatorPermitError("permit_request_head")
    permit_nonce = value.get("permit_nonce")
    if not isinstance(permit_nonce, str) or not _HEX_64.fullmatch(permit_nonce):
        raise OperatorPermitError("permit_nonce")
    _validate_runs(value.get("validation_runs"))
    if value.get("authority") != _EXPECTED_PERMIT_AUTHORITY:
        raise OperatorPermitError("permit_authority")
    stored = value.get("permit_sha256")
    unsigned = dict(value)
    unsigned.pop("permit_sha256", None)
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise OperatorPermitError("permit_digest")
    return value


def _validate_identities(repo: Path, base: str, head: str) -> None:
    if not _HEX_40.fullmatch(base) or not _HEX_40.fullmatch(head) or base == head:
        raise OperatorPermitError("pr_identity")
    if _git(repo, ["rev-parse", "HEAD"]) != head:
        raise OperatorPermitError("pr_exact_head_mismatch")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        cwd=repo,
        check=False,
    )
    if result.returncode != 0:
        raise OperatorPermitError("pr_base_not_ancestor")


def validate_pr_stage(
    *,
    repo_root: Path,
    base: str,
    head: str,
) -> tuple[str, dict[str, Any]]:
    _validate_identities(repo_root, base, head)
    rows = _operator_rows(repo_root, base, head)
    if any(status != "A" for status, _ in rows):
        raise OperatorPermitError("operator_files_not_additions")
    requests = [path for _, path in rows if _REQUEST_PATH.fullmatch(path)]
    permits = [path for _, path in rows if _PERMIT_PATH.fullmatch(path)]
    if len(requests) != 1 or len(permits) not in {0, 1}:
        raise OperatorPermitError("operator_file_counts")
    if _changed_paths(repo_root, base, head) != sorted(requests + permits):
        raise OperatorPermitError("pr_contains_non_operator_changes")

    request_path = requests[0]
    request = validate_request(
        _safe(repo_root, request_path, _REQUEST_PATH),
        expected_base_sha=base,
    )
    auth_relative = request.get("authorization_path")
    if not isinstance(auth_relative, str):
        raise OperatorPermitError("request_authorization_path")
    auth_path = (repo_root.resolve() / auth_relative).resolve()
    try:
        auth_path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise OperatorPermitError("authorization_path_escape") from exc
    try:
        authorization = validate_authorization(
            auth_path,
            expected_nonce=request["nonce"],
        )
    except OperatorCommandError as exc:
        raise OperatorPermitError("authorization_" + exc.code) from exc
    if authorization.get("command_type") != request.get("command_type"):
        raise OperatorPermitError("authorization_command_mismatch")

    result: dict[str, Any] = {
        "stage": "request_validated",
        "request_path": request_path,
        "request_sha256": request["request_sha256"],
        "authorization_path": auth_relative,
        "authorization_sha256": authorization["authorization_sha256"],
        "nonce": request["nonce"],
        "command_type": request["command_type"],
        "expected_head": head,
        "permit_path": "",
        "permit_sha256": "",
    }
    if not permits:
        return "request_validated", result

    permit_path = permits[0]
    permit = validate_permit(
        _safe(repo_root, permit_path, _PERMIT_PATH),
        expected_base_sha=base,
        request_path=request_path,
        request=request,
        authorization=authorization,
    )
    parent = _single_parent(repo_root, head)
    if parent != permit["validated_request_head_sha"]:
        raise OperatorPermitError("permit_parent_head_mismatch")
    if _operator_rows(repo_root, parent, head) != [("A", permit_path)]:
        raise OperatorPermitError("permit_commit_scope")
    if _operator_rows(repo_root, base, parent) != [("A", request_path)]:
        raise OperatorPermitError("validated_request_head_scope")
    result.update(
        stage="execution_permitted",
        permit_path=permit_path,
        permit_sha256=permit["permit_sha256"],
    )
    return "execution_permitted", result


def _write_output(path: Path, key: str, value: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate two-stage M23 PR permit")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _, result = validate_pr_stage(
            repo_root=Path(args.repo_root),
            base=args.base,
            head=args.head,
        )
    except (OperatorPermitError, OperatorCommandError, OSError, json.JSONDecodeError):
        return 23
    output = Path(args.github_output)
    for key in (
        "stage",
        "request_path",
        "request_sha256",
        "authorization_path",
        "authorization_sha256",
        "nonce",
        "command_type",
        "expected_head",
        "permit_path",
        "permit_sha256",
    ):
        _write_output(output, key, str(result[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
