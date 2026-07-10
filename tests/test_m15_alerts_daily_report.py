from datetime import UTC, datetime, timedelta

import pytest

from knowledge_engine.m15_alerts_daily_report import (
    AlertReason,
    ClosureDecision,
    EvidenceState,
    GateName,
    GateState,
    M15ClosureAuthority,
    M15DailyReport,
    M15EvidenceArtifact,
    M15Identity,
    ReportSection,
    evaluate_m15_daily_report,
    finalize_m15_daily_report,
)

ENGINE = "e8d85717797cb23fc6bcf6d6a014d2f2e005b1d5"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
DIGEST = "a" * 64
NOW = datetime(2026, 7, 10, 5, 30, tzinfo=UTC)


def identity(**overrides: object) -> M15Identity:
    values: dict[str, object] = {
        "engine_sha": ENGINE,
        "source_sha": SOURCE,
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
        "pointer_sha256": POINTER,
    }
    values.update(overrides)
    return M15Identity(**values)


def evidence(section: ReportSection, **overrides: object) -> M15EvidenceArtifact:
    values: dict[str, object] = {
        "section": section,
        "artifact_sha256": DIGEST,
        "state": EvidenceState.SUCCESS,
        "generated_at": NOW,
        "identity": identity(),
        "summary_code": f"{section.value.replace('_', '-')}.ok",
    }
    values.update(overrides)
    return M15EvidenceArtifact(**values)


def full_evidence() -> list[M15EvidenceArtifact]:
    return [evidence(section) for section in ReportSection]


def test_all_gates_pass_and_report_is_deterministic() -> None:
    first = evaluate_m15_daily_report(full_evidence(), generated_at=NOW, identity=identity())
    second = evaluate_m15_daily_report(full_evidence(), generated_at=NOW, identity=identity())
    assert first.artifact_sha256 == second.artifact_sha256
    assert first.closure_decision == ClosureDecision.READY_TO_CLOSE
    assert first.alerts == []
    assert {gate.state for gate in first.gates} == {GateState.PASSED}


def test_missing_required_evidence_blocks_closure() -> None:
    partial = [item for item in full_evidence() if item.section != ReportSection.FEEDBACK_TRIAGE]
    report = evaluate_m15_daily_report(partial, generated_at=NOW, identity=identity())
    assert report.closure_decision == ClosureDecision.BLOCKED
    assert any(alert.reason == AlertReason.MISSING_EVIDENCE for alert in report.alerts)
    assert any(
        gate.name == GateName.EVIDENCE_COMPLETE and gate.state == GateState.BLOCKED
        for gate in report.gates
    )


def test_unhealthy_and_unknown_evidence_fail_closed() -> None:
    items = full_evidence()
    items[0] = evidence(ReportSection.OBSERVABILITY_CONTRACTS, state=EvidenceState.UNHEALTHY)
    items[1] = evidence(ReportSection.RUNTIME_TELEMETRY, state=EvidenceState.UNKNOWN)
    report = evaluate_m15_daily_report(items, generated_at=NOW, identity=identity())
    assert report.closure_decision == ClosureDecision.BLOCKED
    reasons = {alert.reason for alert in report.alerts}
    assert AlertReason.UNHEALTHY_EVIDENCE in reasons
    assert AlertReason.UNKNOWN_EVIDENCE in reasons


def test_stale_evidence_blocks_freshness_gate() -> None:
    stale = evidence(
        ReportSection.RELEASE_HEALTH,
        generated_at=NOW - timedelta(days=2),
    )
    items = [stale if item.section == stale.section else item for item in full_evidence()]
    report = evaluate_m15_daily_report(items, generated_at=NOW, identity=identity())
    assert any(alert.reason == AlertReason.STALE_EVIDENCE for alert in report.alerts)
    assert any(
        gate.name == GateName.FRESHNESS and gate.state == GateState.BLOCKED
        for gate in report.gates
    )


def test_identity_drift_blocks_identity_gate() -> None:
    drift = evidence(
        ReportSection.GOVERNANCE_HEALTH,
        identity=identity(engine_sha="0" * 40),
    )
    items = [drift if item.section == drift.section else item for item in full_evidence()]
    report = evaluate_m15_daily_report(items, generated_at=NOW, identity=identity())
    assert report.closure_decision == ClosureDecision.BLOCKED
    assert any(alert.reason == AlertReason.IDENTITY_DRIFT for alert in report.alerts)


def test_rejects_private_or_secret_material_and_extra_fields() -> None:
    with pytest.raises(ValueError):
        M15EvidenceArtifact(
            section=ReportSection.FEEDBACK_TRIAGE,
            artifact_sha256=DIGEST,
            state=EvidenceState.SUCCESS,
            generated_at=NOW,
            identity=identity(),
            summary_code="raw_query",
        )
    with pytest.raises(ValueError):
        M15EvidenceArtifact(
            section=ReportSection.FEEDBACK_TRIAGE,
            artifact_sha256=DIGEST,
            state=EvidenceState.SUCCESS,
            generated_at=NOW,
            identity=identity(),
            summary_code="feedback.ok",
            raw_answer="private answer",
        )


def test_rejects_non_utc_timestamps() -> None:
    with pytest.raises(ValueError):
        evidence(ReportSection.RELEASE_HEALTH, generated_at=datetime(2026, 7, 10, 5, 0))
    with pytest.raises(ValueError):
        evaluate_m15_daily_report(
            full_evidence(),
            generated_at=datetime(2026, 7, 10, 5, 0),
            identity=identity(),
        )


def test_no_write_authority_is_enforced() -> None:
    with pytest.raises(ValueError):
        M15ClosureAuthority(source_write_allowed=True)
    with pytest.raises(ValueError):
        M15ClosureAuthority(production_write_allowed=True)
    with pytest.raises(ValueError):
        M15ClosureAuthority(permanent_ledger_append_allowed=True)


def test_report_is_tamper_evident() -> None:
    report = evaluate_m15_daily_report(full_evidence(), generated_at=NOW, identity=identity())
    tampered = report.model_copy(update={"closure_decision": ClosureDecision.BLOCKED})
    with pytest.raises(ValueError):
        finalize_m15_daily_report(tampered)


def test_digest_mismatch_is_rejected() -> None:
    report = evaluate_m15_daily_report(full_evidence(), generated_at=NOW, identity=identity())
    poisoned = M15DailyReport(
        generated_at=report.generated_at,
        identity=report.identity,
        evidence=report.evidence,
        alerts=report.alerts,
        gates=report.gates,
        closure_decision=report.closure_decision,
        artifact_sha256="0" * 64,
    )
    with pytest.raises(ValueError):
        finalize_m15_daily_report(poisoned)
