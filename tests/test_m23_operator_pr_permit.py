from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import m23_operator_pr_permit as subject


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return _git(repo, "rev-parse", "HEAD")


def _authorization(nonce: str) -> dict:
    value = {
        "schema_version": "knowledge-engine-m23-operator-command-authorization/v1",
        "authorization_id": "m23-r3-8-post-delete-recovery-29521901629-v5",
        "command_type": "r3_8_post_delete_recovery",
        "nonce": nonce,
        "bus_issue_number": 565,
        "actor_login": "huaihsuanbusiness",
        "source_run_id": "29521901629",
        "source_engine_sha": "542907fa0cfae47addd6d777c1708ae62155aea4",
        "worker_name": "knowledge-engine-r3-8-29506217284",
        "previous_deletion_authorization_path": (
            "deletion_authorizations/m23-7/r3-8/"
            "knowledge-engine-r3-8-29506217284.json"
        ),
        "authority": {
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
        },
    }
    value["authorization_sha256"] = subject.canonical_sha256(value)
    return value


def _build_repo(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    nonce = "a" * 64
    auth_relative = (
        "operator_authorizations/m23/r3-8/"
        "post-delete-recovery-29521901629-v5.json"
    )
    auth_path = repo / auth_relative
    auth_path.parent.mkdir(parents=True)
    authorization = _authorization(nonce)
    auth_path.write_text(
        subject.canonical_json(authorization) + "\n",
        encoding="utf-8",
    )
    (repo / "baseline.txt").write_text("base\n", encoding="utf-8")
    base = _commit(repo, "base")

    request_id = "r3-8-post-delete-recovery-29521901629-v5"
    request_relative = f"operator_requests/m23/r3-8/{request_id}.json"
    request = {
        "schema_version": "knowledge-engine-m23-operator-request/v1",
        "request_id": request_id,
        "command_type": "r3_8_post_delete_recovery",
        "authorization_path": auth_relative,
        "nonce": nonce,
        "expected_base_sha": base,
        "status_issue_number": 565,
    }
    request["request_sha256"] = subject.canonical_sha256(request)
    request_path = repo / request_relative
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        subject.canonical_json(request) + "\n",
        encoding="utf-8",
    )
    request_head = _commit(repo, "request")

    permit_id = request_id
    permit_relative = f"operator_permits/m23/r3-8/{permit_id}.json"
    permit = {
        "schema_version": subject.PERMIT_SCHEMA,
        "permit_id": permit_id,
        "command_type": "r3_8_post_delete_recovery",
        "request_path": request_relative,
        "request_sha256": request["request_sha256"],
        "validated_request_head_sha": request_head,
        "expected_base_sha": base,
        "authorization_sha256": authorization["authorization_sha256"],
        "permit_nonce": "b" * 64,
        "validation_runs": {
            "request_validation": 101,
            "ci": 102,
            "m18": 103,
        },
        "authority": dict(subject._RECOVERY_PERMIT_AUTHORITY),
    }
    permit["permit_sha256"] = subject.canonical_sha256(permit)
    permit_path = repo / permit_relative
    permit_path.parent.mkdir(parents=True)
    permit_path.write_text(
        subject.canonical_json(permit) + "\n",
        encoding="utf-8",
    )
    permit_head = _commit(repo, "permit")
    return repo, base, request_head, permit_head, permit_relative


def test_request_and_permit_stages_validate(tmp_path: Path) -> None:
    repo, base, request_head, permit_head, permit_relative = _build_repo(tmp_path)
    subprocess.run(
        ["git", "checkout", "-q", "--detach", request_head],
        cwd=repo,
        check=True,
    )
    stage, request_result = subject.validate_pr_stage(
        repo_root=repo,
        base=base,
        head=request_head,
    )
    assert stage == "request_validated"
    assert request_result["permit_path"] == ""

    subprocess.run(
        ["git", "checkout", "-q", "--detach", permit_head],
        cwd=repo,
        check=True,
    )
    stage, permit_result = subject.validate_pr_stage(
        repo_root=repo,
        base=base,
        head=permit_head,
    )
    assert stage == "execution_permitted"
    assert permit_result["permit_path"] == permit_relative
    assert permit_result["permit_sha256"]


def test_permit_commit_rejects_extra_file(tmp_path: Path) -> None:
    repo, base, _, permit_head, _ = _build_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", permit_head], cwd=repo, check=True)
    (repo / "extra.txt").write_text("not allowed\n", encoding="utf-8")
    bad_head = _commit(repo, "extra")
    subprocess.run(
        ["git", "checkout", "-q", "--detach", bad_head],
        cwd=repo,
        check=True,
    )
    with pytest.raises(subject.OperatorPermitError, match="pr_contains_non_operator_changes"):
        subject.validate_pr_stage(repo_root=repo, base=base, head=bad_head)


def test_permit_rejects_parent_binding_drift(tmp_path: Path) -> None:
    repo, base, request_head, permit_head, permit_relative = _build_repo(tmp_path)
    raw = _git(repo, "show", f"{permit_head}:{permit_relative}")
    value = json.loads(raw)
    value["validated_request_head_sha"] = "c" * 40
    unsigned = dict(value)
    unsigned.pop("permit_sha256")
    value["permit_sha256"] = subject.canonical_sha256(unsigned)

    subprocess.run(
        ["git", "checkout", "-q", "-B", "drift", request_head],
        cwd=repo,
        check=True,
    )
    path = repo / permit_relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(subject.canonical_json(value) + "\n", encoding="utf-8")
    drift_head = _commit(repo, "drift")
    subprocess.run(
        ["git", "checkout", "-q", "--detach", drift_head],
        cwd=repo,
        check=True,
    )
    with pytest.raises(subject.OperatorPermitError, match="permit_parent_head_mismatch"):
        subject.validate_pr_stage(repo_root=repo, base=base, head=drift_head)


def test_source_forbids_arbitrary_execution_surfaces() -> None:
    text = Path(subject.__file__).read_text(encoding="utf-8")
    assert 'R3_LIVE_COMMAND = "r3_live_reobservation"' in text
    assert 'PERMIT_ROOT = "operator_permits/m23/"' in text
    for forbidden in (
        "workflow_name",
        "shell_command",
        "client.post(",
        "QDRANT_URL",
        "R2_ACCESS_KEY_ID",
    ):
        assert forbidden not in text


def test_live_permit_authorizes_only_transient_observation_scope(tmp_path: Path) -> None:
    repo, base, _, _, _ = _build_repo(tmp_path)
    subprocess.run(
        ["git", "checkout", "-q", "--detach", base],
        cwd=repo,
        check=True,
    )
    request_id = "r3-live-reobservation-001"
    auth_relative = "operator_authorizations/m23/r3-live/r3-live-001.json"
    nonce = "e" * 64
    authorization = {
        "schema_version": "knowledge-engine-m23-operator-command-authorization/v1",
        "authorization_id": "m23-r3-live-001",
        "command_type": subject.R3_LIVE_COMMAND,
        "nonce": nonce,
        "bus_issue_number": 565,
        "actor_login": "huaihsuanbusiness",
        "source_issue_number": 595,
        "source_engine_sha": "ddac861f648a130db6af5a293c6d5af291226382",
        "worker_name_prefix": "knowledge-engine-m23-7-r3-live",
        "authority": {
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
        },
    }
    authorization["authorization_sha256"] = subject.canonical_sha256(authorization)
    auth_path = repo / auth_relative
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(subject.canonical_json(authorization) + "\n", encoding="utf-8")
    base = _commit(repo, "live authorization base")
    request_relative = f"operator_requests/m23/r3-live/{request_id}.json"
    request = {
        "schema_version": "knowledge-engine-m23-operator-request/v1",
        "request_id": request_id,
        "command_type": subject.R3_LIVE_COMMAND,
        "authorization_path": auth_relative,
        "nonce": nonce,
        "expected_base_sha": base,
        "status_issue_number": 565,
    }
    request["request_sha256"] = subject.canonical_sha256(request)
    request_path = repo / request_relative
    request_path.parent.mkdir(parents=True)
    request_path.write_text(subject.canonical_json(request) + "\n", encoding="utf-8")
    live_request_head = _commit(repo, "live request")

    permit_relative = f"operator_permits/m23/r3-live/{request_id}.json"
    permit = {
        "schema_version": subject.PERMIT_SCHEMA,
        "permit_id": request_id,
        "command_type": subject.R3_LIVE_COMMAND,
        "request_path": request_relative,
        "request_sha256": request["request_sha256"],
        "validated_request_head_sha": live_request_head,
        "expected_base_sha": base,
        "authorization_sha256": authorization["authorization_sha256"],
        "permit_nonce": "f" * 64,
        "validation_runs": {"request_validation": 201, "ci": 202, "m18": 203},
        "authority": dict(subject._R3_LIVE_PERMIT_AUTHORITY),
    }
    permit["permit_sha256"] = subject.canonical_sha256(permit)
    permit_path = repo / permit_relative
    permit_path.parent.mkdir(parents=True)
    permit_path.write_text(subject.canonical_json(permit) + "\n", encoding="utf-8")
    live_permit_head = _commit(repo, "live permit")
    subprocess.run(
        ["git", "checkout", "-q", "--detach", live_permit_head],
        cwd=repo,
        check=True,
    )
    stage, result = subject.validate_pr_stage(
        repo_root=repo,
        base=base,
        head=live_permit_head,
    )
    assert stage == "execution_permitted"
    assert result["command_type"] == subject.R3_LIVE_COMMAND
