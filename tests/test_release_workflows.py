from pathlib import Path

PROMOTE = Path(".github/workflows/promote-knowledge-release.yml")
ROLLBACK = Path(".github/workflows/rollback-knowledge-release.yml")
RECORDER = Path(".github/workflows/record-production-release.yml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_promotion_workflow_is_approval_gated_and_knowledge_only() -> None:
    workflow = _read(PROMOTE)

    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "group: knowledge-production-control-plane" in workflow
    assert "knowledge-engine promote-release" in workflow
    assert "knowledge-engine rollback-release" in workflow
    assert "bash scripts/oracle_refresh_smoke.sh" in workflow
    assert "bash scripts/oracle_restart_verify.sh" in workflow
    assert "docker compose build" not in workflow
    assert "deploy/deploy.sh" not in workflow


def test_emergency_rollback_uses_same_production_lock() -> None:
    workflow = _read(ROLLBACK)

    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "group: knowledge-production-control-plane" in workflow
    assert "knowledge-engine rollback-release" in workflow
    assert "bash scripts/oracle_restart_verify.sh" in workflow
    assert "docker compose build" not in workflow
    assert "deploy/deploy.sh" not in workflow


def test_ledger_recorder_has_no_production_secrets() -> None:
    workflow = _read(RECORDER)

    assert "workflow_run:" in workflow
    assert "Promote Knowledge Release" in workflow
    assert "Roll Back Knowledge Release" in workflow
    assert "actions: read" in workflow
    assert "issues: write" in workflow
    assert "issue_number: 18" in workflow
    assert "R2_SECRET_ACCESS_KEY" not in workflow
    assert "ORACLE_VM_SSH_PRIVATE_KEY" not in workflow
    assert "environment: production" not in workflow
