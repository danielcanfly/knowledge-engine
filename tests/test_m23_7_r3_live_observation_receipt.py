from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import m23_7_r3_live_observation_receipt as subject
from scripts.m23_operator_command_bus import canonical_json, canonical_sha256


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def test_live_observation_receipt_is_privacy_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    auth = {
        "schema_version": "knowledge-engine-m23-operator-command-authorization/v1",
        "authorization_id": "m23-r3-live-001",
        "command_type": subject.COMMAND_TYPE,
        "nonce": nonce,
        "bus_issue_number": 565,
        "actor_login": "huaihsuanbusiness",
        "source_issue_number": 595,
        "source_engine_sha": "ddac861f648a130db6af5a293c6d5af291226382",
        "worker_name_prefix": subject.WORKER_PREFIX,
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
    auth["authorization_sha256"] = canonical_sha256(auth)
    auth_rel = "operator_authorizations/m23/r3-live/r3-live-001.json"
    auth_path = repo / auth_rel
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(canonical_json(auth) + "\n", encoding="utf-8")
    head = _commit(repo, "base")
    report = {
        "status": "pass_bounded_live_reobservation",
        "metrics": {
            "recall_at_5": 1.0,
            "mrr_at_10": 0.75,
            "ndcg_at_10": 0.8,
            "worker_internal_shadow_ms": 800,
            "error_rate": 0.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
        },
        "gates": {"recall_at_5": True},
        "remaining_blockers": [],
    }
    report["report_sha256"] = canonical_sha256(report)
    report_path = tmp_path / "report.json"
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    monkeypatch.setenv(
        "M23_R3_TRANSIENT_WORKER_NAME",
        "knowledge-engine-m23-7-r3-live-29599999999",
    )
    args = subject.parse_args(
        [
            "--authorization-path",
            auth_rel,
            "--expected-head",
            head,
            "--nonce",
            nonce,
            "--repo-root",
            str(repo),
            "--report-path",
            str(report_path),
            "--deletion-completed",
            "true",
            "--output",
            str(tmp_path / "receipt.json"),
        ]
    )
    receipt = subject.build_receipt(args)
    assert receipt["status"] == "pass_live_observation_pending_reconciliation"
    assert receipt["blockers_cleared"] is False
    assert receipt["privacy"]["worker_url_persisted"] is False
    encoded = canonical_json(receipt)
    assert "workers.dev" not in encoded
    assert "QDRANT_API_KEY" not in encoded

    diagnostic_report = {
        "status": "rejected_diagnostic_worker_failure",
        "metrics": {
            "recall_at_5": 0.0,
            "mrr_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "worker_internal_shadow_ms": 1201,
            "error_rate": 1.0,
            "acl_violation_rate": 0.0,
            "output_influence_rate": 0.0,
        },
        "gates": {
            "recall_at_5": False,
            "mrr_at_10": False,
            "ndcg_at_10": False,
            "worker_internal_shadow": False,
            "error_rate": False,
            "acl_violation_rate": True,
            "output_influence_rate": True,
        },
        "remaining_blockers": ["blocked_pending_retrieval_quality"],
    }
    diagnostic_report["report_sha256"] = canonical_sha256(diagnostic_report)
    report_path.write_text(canonical_json(diagnostic_report) + "\n", encoding="utf-8")
    diagnostic_receipt = subject.build_receipt(args)
    assert diagnostic_receipt["status"] == (
        "rejected_live_observation_pending_reconciliation"
    )
    assert diagnostic_receipt["blockers_cleared"] is False
