from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from typing import Any

from scripts.m23_operator_command_bus import canonical_json

REPOSITORY = "danielcanfly/knowledge-engine"
BUS_ISSUE_NUMBER = 565
STATUS_PREFIX = "M23_OPERATOR_STATUS "
COMMAND_PREFIX = "M23_OPERATOR_COMMAND "
_ALLOWED_PHASES = {"accepted", "final"}
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[0-9]{1,20}$")
_COMMAND_TYPE = re.compile(r"^[a-z0-9][a-z0-9_]{0,79}$")
_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class OperatorStatusError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise OperatorStatusError(f"missing_{name.lower()}")
    return value


def build_status(
    *,
    phase: str,
    run_id: str,
    command_type: str,
    expected_head: str,
    authorization_sha256: str,
    exit_code: str | None = None,
    artifact_name: str | None = None,
) -> str:
    if phase not in _ALLOWED_PHASES:
        raise OperatorStatusError("status_phase")
    if not _RUN_ID.fullmatch(run_id):
        raise OperatorStatusError("status_run_id")
    if not _COMMAND_TYPE.fullmatch(command_type):
        raise OperatorStatusError("status_command_type")
    if not _HEX_40.fullmatch(expected_head):
        raise OperatorStatusError("status_expected_head")
    if not _HEX_64.fullmatch(authorization_sha256):
        raise OperatorStatusError("status_authorization")
    value: dict[str, Any] = {
        "schema_version": "knowledge-engine-m23-operator-status/v1",
        "phase": phase,
        "run_id": run_id,
        "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}",
        "command_type": command_type,
        "expected_head": expected_head,
        "authorization_sha256": authorization_sha256,
        "bus_issue_number": BUS_ISSUE_NUMBER,
        "production_retrieval": "lexical",
        "blockers_cleared": False,
        "worker_delete_replayed": False,
        "qdrant_access_dispatched": False,
        "r2_access_dispatched": False,
    }
    if phase == "accepted":
        if exit_code is not None or artifact_name is not None:
            raise OperatorStatusError("accepted_status_extra_fields")
        value["status"] = "command_validated_and_routed"
    else:
        if exit_code not in {"0", "23", "30"}:
            raise OperatorStatusError("final_status_exit_code")
        if not isinstance(artifact_name, str) or not _ARTIFACT.fullmatch(artifact_name):
            raise OperatorStatusError("final_status_artifact")
        value["status"] = "route_completed"
        value["exit_code"] = int(exit_code)
        value["artifact_name"] = artifact_name
    body = STATUS_PREFIX + canonical_json(value)
    if body.startswith(COMMAND_PREFIX) or "\n" in body or "\r" in body:
        raise OperatorStatusError("status_body_boundary")
    return body


def post_status(body: str, token: str) -> None:
    if not body.startswith(STATUS_PREFIX) or body.startswith(COMMAND_PREFIX):
        raise OperatorStatusError("status_body_prefix")
    url = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/"
        f"{BUS_ISSUE_NUMBER}/comments"
    )
    encoded = json.dumps({"body": body}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 201:
            raise OperatorStatusError("status_comment_http")
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise OperatorStatusError("status_comment_response")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post bounded M23 operator status")
    parser.add_argument("--phase", choices=sorted(_ALLOWED_PHASES), required=True)
    parser.add_argument("--command-type", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--authorization-sha256", required=True)
    parser.add_argument("--exit-code")
    parser.add_argument("--artifact-name")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_id = required_env("GITHUB_RUN_ID")
        repository = required_env("GITHUB_REPOSITORY")
        if repository != REPOSITORY:
            raise OperatorStatusError("status_repository")
        body = build_status(
            phase=args.phase,
            run_id=run_id,
            command_type=args.command_type,
            expected_head=args.expected_head,
            authorization_sha256=args.authorization_sha256,
            exit_code=args.exit_code,
            artifact_name=args.artifact_name,
        )
        post_status(body, required_env("GH_TOKEN"))
    except (OperatorStatusError, OSError, json.JSONDecodeError):
        return 23
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
