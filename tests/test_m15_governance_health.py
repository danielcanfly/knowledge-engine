from datetime import UTC, datetime, timedelta

import pytest

from knowledge_engine.m15_governance_health import (
    GovernanceAuthority,
    GovernanceHealthState,
    GovernanceIssueCode,
    GovernanceWorkItem,
    LifecyclePhase,
    evaluate_governance_health,
    finalize_governance_report,
)

ENGINE = "fb7459d90b10fc865239c7cca3077699ca6ac07c"
NOW = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)


def item(**overrides: object) -> GovernanceWorkItem:
    values: dict[str, object] = {
        "work_id": "batch-001",
        "phase": LifecyclePhase.RUNNING,
        "owner_id": "operator-a",
        "engine_sha": ENGINE,
        "expected_engine_sha": ENGINE,
        "created_at": NOW - timedelta(hours=1),
        "updated_at": NOW - timedelta(minutes=5),
        "heartbeat_at": NOW - timedelta(minutes=5),
        "lease_expires_at": NOW + timedelta(minutes=20),
    }
    values.update(overrides)
    return GovernanceWorkItem(**values)


def test_healthy_running_item() -> None:
    report = evaluate_governance_health([item()], generated_at=NOW)
    assert report.overall_state == GovernanceHealthState.HEALTHY
    assert report.issues == []
    assert report.artifact_sha256


def test_detects_stalled_and_expired_work() -> None:
    report = evaluate_governance_health(
        [item(heartbeat_at=NOW - timedelta(hours=2), lease_expires_at=NOW - timedelta(minutes=1))],
        generated_at=NOW,
    )
    assert {issue.code for issue in report.issues} == {
        GovernanceIssueCode.HEARTBEAT_STALE,
        GovernanceIssueCode.LEASE_EXPIRED,
    }
    assert report.overall_state == GovernanceHealthState.DEGRADED


def test_identity_drift_is_unhealthy() -> None:
    report = evaluate_governance_health(
        [item(engine_sha="0" * 40)],
        generated_at=NOW,
    )
    assert report.overall_state == GovernanceHealthState.UNHEALTHY
    assert report.issues[0].code == GovernanceIssueCode.IDENTITY_DRIFT


def test_duplicate_work_id_is_unhealthy_and_stably_sorted() -> None:
    report = evaluate_governance_health([item(), item()], generated_at=NOW)
    assert report.overall_state == GovernanceHealthState.UNHEALTHY
    assert any(issue.code == GovernanceIssueCode.DUPLICATE_WORK_ID for issue in report.issues)
    assert report.issues == sorted(
        report.issues,
        key=lambda issue: (issue.code.value, issue.work_id, issue.state.value),
    )


def test_missing_approval_and_evidence() -> None:
    report = evaluate_governance_health(
        [
            item(
                phase=LifecyclePhase.AWAITING_APPROVAL,
                approval_required=True,
                evidence_required=True,
            )
        ],
        generated_at=NOW,
    )
    assert {issue.code for issue in report.issues} == {
        GovernanceIssueCode.APPROVAL_MISSING,
        GovernanceIssueCode.EVIDENCE_MISSING,
    }


def test_future_heartbeat_fails_closed_as_unknown() -> None:
    report = evaluate_governance_health(
        [item(heartbeat_at=NOW + timedelta(minutes=1))],
        generated_at=NOW,
    )
    assert report.overall_state == GovernanceHealthState.UNKNOWN


def test_terminal_state_requires_terminal_result() -> None:
    report = evaluate_governance_health(
        [item(phase=LifecyclePhase.COMPLETED, terminal_result_recorded=False)],
        generated_at=NOW,
    )
    assert report.overall_state == GovernanceHealthState.UNHEALTHY


def test_retry_exhaustion_is_unhealthy() -> None:
    report = evaluate_governance_health(
        [item(phase=LifecyclePhase.FAILED, retry_count=3, retry_limit=3, terminal_result_recorded=True)],
        generated_at=NOW,
    )
    assert any(issue.code == GovernanceIssueCode.RETRY_EXHAUSTED for issue in report.issues)


def test_rejects_non_utc_timestamps() -> None:
    with pytest.raises(ValueError):
        item(created_at=datetime(2026, 7, 10, 4, 0))


def test_rejects_any_automatic_authority() -> None:
    with pytest.raises(ValueError):
        GovernanceAuthority(automatic_retry_allowed=True)
    with pytest.raises(ValueError):
        GovernanceAuthority(automatic_close_allowed=True)
    with pytest.raises(ValueError):
        GovernanceAuthority(promotion_allowed=True)


def test_report_digest_is_deterministic_and_tamper_evident() -> None:
    first = evaluate_governance_health([item()], generated_at=NOW)
    second = evaluate_governance_health([item()], generated_at=NOW)
    assert first.artifact_sha256 == second.artifact_sha256
    tampered = first.model_copy(update={"work_count": 2})
    with pytest.raises(ValueError):
        finalize_governance_report(tampered)
