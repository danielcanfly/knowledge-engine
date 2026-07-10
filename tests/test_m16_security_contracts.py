from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_security_contracts import (
    ApprovalState,
    AssetKind,
    Audience,
    DrillMode,
    IncidentKind,
    IncidentRecord,
    IncidentState,
    M16Identity,
    RecoveryAction,
    RecoveryAuthority,
    RecoveryPlan,
    RecoveryStep,
    RiskLevel,
    SecurityControl,
    ThreatActor,
    ThreatScenario,
    TrustBoundary,
    build_security_contract_bundle,
    default_drill_policies,
    default_threat_scenarios,
    finalize_incident_record,
    finalize_recovery_plan,
    finalize_security_contract_bundle,
    policy_allows_mode,
)

ENGINE = "16dfe909b22d9fbe04fbbb5ddfad49e4341ac3b8"
SOURCE = "2126db2ed4d372d3d61464fe31a86fc0243a1f24"
RELEASE = "20260708T040116Z-69a9f445699a"
MANIFEST = "2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb"
POINTER = "38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5"
NOW = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)


def identity(**overrides: object) -> M16Identity:
    values: dict[str, object] = {
        "engine_sha": ENGINE,
        "source_sha": SOURCE,
        "release_id": RELEASE,
        "manifest_sha256": MANIFEST,
        "pointer_sha256": POINTER,
    }
    values.update(overrides)
    return M16Identity(**values)


def scenario(**overrides: object) -> ThreatScenario:
    values: dict[str, object] = {
        "scenario_id": "scenario-alpha",
        "actor": ThreatActor.EXTERNAL_ATTACKER,
        "asset": AssetKind.PRODUCTION_RELEASE,
        "boundary": TrustBoundary.RUNTIME,
        "incident_kind": IncidentKind.INTEGRITY_VIOLATION,
        "likelihood": RiskLevel.MEDIUM,
        "impact": RiskLevel.HIGH,
        "source_audience": Audience.INTERNAL,
        "evidence_audience": Audience.INTERNAL,
        "controls": [
            SecurityControl.FAIL_CLOSED,
            SecurityControl.EXACT_IDENTITY_PRECONDITION,
        ],
    }
    values.update(overrides)
    return ThreatScenario(**values)


def simulation_authority() -> RecoveryAuthority:
    return RecoveryAuthority(mode=DrillMode.SIMULATION_ONLY)


def isolated_authority() -> RecoveryAuthority:
    return RecoveryAuthority(mode=DrillMode.ISOLATED_ENVIRONMENT)


def governed_authority(**overrides: object) -> RecoveryAuthority:
    values: dict[str, object] = {
        "mode": DrillMode.GOVERNED_PRODUCTION,
        "production_scope": True,
        "approval_state": ApprovalState.APPROVED,
        "approval_id": "approval-m16-001",
        "operation_id": "operation-m16-001",
        "expected_previous_pointer_sha256": POINTER,
        "expected_source_sha": SOURCE,
        "rollback_evidence_code": "rollback.ready",
    }
    values.update(overrides)
    return RecoveryAuthority(**values)


def plan(
    *,
    authority: RecoveryAuthority | None = None,
    steps: list[RecoveryStep] | None = None,
    **overrides: object,
) -> RecoveryPlan:
    values: dict[str, object] = {
        "plan_id": "plan-m16-001",
        "incident_id": "incident-m16-001",
        "generated_at": NOW,
        "incident_kind": IncidentKind.OBJECT_LOSS,
        "identity": identity(),
        "authority": authority or simulation_authority(),
        "steps": steps
        or [
            RecoveryStep(
                step_id="01-assess",
                action=RecoveryAction.ASSESS,
                target=AssetKind.R2_OBJECT,
                expected_evidence_code="assessment.complete",
            ),
            RecoveryStep(
                step_id="02-verify",
                action=RecoveryAction.VERIFY,
                target=AssetKind.R2_OBJECT,
                expected_evidence_code="verification.complete",
            ),
        ],
    }
    values.update(overrides)
    return RecoveryPlan(**values)


def test_default_security_bundle_is_complete_deterministic_and_sorted() -> None:
    first = build_security_contract_bundle(generated_at=NOW, identity=identity())
    second = build_security_contract_bundle(generated_at=NOW, identity=identity())

    assert first.artifact_sha256 == second.artifact_sha256
    assert first.artifact_sha256 is not None
    assert [item.scenario_id for item in first.scenarios] == sorted(
        item.scenario_id for item in first.scenarios
    )
    assert {policy.incident_kind for policy in first.drill_policies} == set(IncidentKind)
    assert len(first.drill_policies) == len(IncidentKind)
    assert all(
        policy.maximum_mode != DrillMode.GOVERNED_PRODUCTION
        for policy in first.drill_policies
    )


def test_default_scenarios_cover_high_value_assets_and_controls() -> None:
    scenarios = default_threat_scenarios()
    assets = {item.asset for item in scenarios}
    controls = {control for item in scenarios for control in item.controls}

    assert AssetKind.CANONICAL_SOURCE in assets
    assert AssetKind.PRODUCTION_POINTER in assets
    assert AssetKind.R2_OBJECT in assets
    assert AssetKind.CREDENTIAL in assets
    assert SecurityControl.EXACT_IDENTITY_PRECONDITION in controls
    assert SecurityControl.AUDIENCE_NON_BROADENING in controls
    assert SecurityControl.IDEMPOTENCY_KEY in controls
    assert SecurityControl.RESTORE_VERIFICATION in controls


def test_duplicate_scenario_ids_are_rejected() -> None:
    duplicate = scenario()
    with pytest.raises(ValueError, match="scenario IDs must be unique"):
        build_security_contract_bundle(
            generated_at=NOW,
            identity=identity(),
            scenarios=[duplicate, duplicate],
        )


def test_policy_coverage_must_be_exact() -> None:
    policies = default_drill_policies()[:-1]
    with pytest.raises(ValueError, match="cover each incident kind exactly once"):
        build_security_contract_bundle(
            generated_at=NOW,
            identity=identity(),
            scenarios=[scenario()],
            drill_policies=policies,
        )


def test_audience_broadening_and_duplicate_controls_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not broaden"):
        scenario(
            source_audience=Audience.PRIVATE,
            evidence_audience=Audience.PUBLIC,
        )
    with pytest.raises(ValueError, match="controls must be unique"):
        scenario(
            controls=[SecurityControl.FAIL_CLOSED, SecurityControl.FAIL_CLOSED],
        )


def test_private_secret_and_arbitrary_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden private or secret material"):
        IncidentRecord(
            incident_id="incident-private",
            detected_at=NOW,
            state=IncidentState.DETECTED,
            incident_kind=IncidentKind.AUDIENCE_BREACH,
            identity=identity(),
            affected_assets=[AssetKind.PRODUCTION_RELEASE],
            evidence_codes=["raw_query"],
            audience=Audience.PRIVATE,
        )
    with pytest.raises(ValidationError):
        IncidentRecord(
            incident_id="incident-extra",
            detected_at=NOW,
            state=IncidentState.DETECTED,
            incident_kind=IncidentKind.AUDIENCE_BREACH,
            identity=identity(),
            affected_assets=[AssetKind.PRODUCTION_RELEASE],
            evidence_codes=["evidence.safe"],
            audience=Audience.PRIVATE,
            raw_answer="private material",
        )


def test_utc_timestamps_and_identity_formats_are_required() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        build_security_contract_bundle(
            generated_at=datetime(2026, 7, 10, 6, 0),
            identity=identity(),
        )
    with pytest.raises(ValidationError):
        identity(engine_sha="not-a-sha")


def test_incident_record_is_deterministic_and_tamper_evident() -> None:
    record = IncidentRecord(
        incident_id="incident-m16-001",
        detected_at=NOW,
        state=IncidentState.DETECTED,
        incident_kind=IncidentKind.OBJECT_LOSS,
        identity=identity(),
        affected_assets=[AssetKind.R2_OBJECT],
        evidence_codes=["object.missing", "probe.complete"],
        audience=Audience.INTERNAL,
    )
    first = finalize_incident_record(record)
    second = finalize_incident_record(record)
    assert first.artifact_sha256 == second.artifact_sha256

    tampered = first.model_copy(update={"state": IncidentState.RESOLVED})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_incident_record(tampered)


def test_simulation_mode_rejects_mutating_actions() -> None:
    steps = [
        RecoveryStep(
            step_id="01-restore",
            action=RecoveryAction.RESTORE_R2_OBJECT,
            target=AssetKind.R2_OBJECT,
            expected_evidence_code="restore.complete",
        )
    ]
    with pytest.raises(ValueError, match="simulation plan contains mutating actions"):
        plan(steps=steps)


def test_isolated_mode_cannot_claim_production_scope_or_tokens() -> None:
    with pytest.raises(ValueError, match="only governed-production"):
        RecoveryAuthority(
            mode=DrillMode.ISOLATED_ENVIRONMENT,
            production_scope=True,
        )
    with pytest.raises(ValueError, match="must not carry production tokens"):
        RecoveryAuthority(
            mode=DrillMode.ISOLATED_ENVIRONMENT,
            operation_id="operation-not-allowed",
        )


def test_governed_production_requires_explicit_complete_authority() -> None:
    with pytest.raises(ValueError, match="requires approval"):
        RecoveryAuthority(
            mode=DrillMode.GOVERNED_PRODUCTION,
            production_scope=True,
            approval_state=ApprovalState.PENDING,
        )

    authority = governed_authority()
    assert authority.production_scope is True
    assert authority.approval_state == ApprovalState.APPROVED
    assert authority.operation_id == "operation-m16-001"


def test_governed_plan_requires_exact_pointer_and_source_preconditions() -> None:
    with pytest.raises(ValueError, match="pointer precondition"):
        plan(authority=governed_authority(expected_previous_pointer_sha256="0" * 64))
    with pytest.raises(ValueError, match="Source precondition"):
        plan(authority=governed_authority(expected_source_sha="0" * 40))


def test_permanent_ledger_append_authority_is_never_granted() -> None:
    with pytest.raises(ValueError, match="never grants permanent-ledger"):
        RecoveryAuthority(
            mode=DrillMode.SIMULATION_ONLY,
            permanent_ledger_append_allowed=True,
        )
    with pytest.raises(ValueError, match="never grants permanent-ledger"):
        governed_authority(permanent_ledger_append_allowed=True)


def test_recovery_plan_is_deterministic_and_tamper_evident() -> None:
    first = finalize_recovery_plan(plan())
    second = finalize_recovery_plan(plan())
    assert first.artifact_sha256 == second.artifact_sha256
    assert first.artifact_sha256 is not None

    tampered = first.model_copy(update={"incident_kind": IncidentKind.BAD_PROMOTION})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_recovery_plan(tampered)


def test_duplicate_recovery_step_ids_are_rejected() -> None:
    duplicate = RecoveryStep(
        step_id="01-assess",
        action=RecoveryAction.ASSESS,
        target=AssetKind.R2_OBJECT,
        expected_evidence_code="assessment.complete",
    )
    with pytest.raises(ValueError, match="step IDs must be unique"):
        plan(steps=[duplicate, duplicate])


def test_default_policy_blocks_unapproved_production_drills() -> None:
    policies = {policy.incident_kind: policy for policy in default_drill_policies()}
    object_loss = policies[IncidentKind.OBJECT_LOSS]
    secret_exposure = policies[IncidentKind.SECRET_EXPOSURE]

    assert policy_allows_mode(object_loss, DrillMode.ISOLATED_ENVIRONMENT)
    assert not policy_allows_mode(object_loss, DrillMode.GOVERNED_PRODUCTION)
    assert policy_allows_mode(secret_exposure, DrillMode.SIMULATION_ONLY)
    assert not policy_allows_mode(secret_exposure, DrillMode.ISOLATED_ENVIRONMENT)


def test_contract_bundle_tampering_is_detected() -> None:
    bundle = build_security_contract_bundle(generated_at=NOW, identity=identity())
    tampered = bundle.model_copy(update={"identity": identity(engine_sha="0" * 40)})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_security_contract_bundle(tampered)
