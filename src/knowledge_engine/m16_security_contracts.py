from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

M16_SECURITY_CONTRACT_SCHEMA = "knowledge-engine-m16-security-contracts/v1"


class Audience(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"


class AssetKind(StrEnum):
    CANONICAL_SOURCE = "canonical_source"
    ENGINE_CODE = "engine_code"
    PRODUCTION_RELEASE = "production_release"
    PRODUCTION_POINTER = "production_pointer"
    R2_OBJECT = "r2_object"
    RUNTIME_CACHE = "runtime_cache"
    APPROVAL_EVIDENCE = "approval_evidence"
    PERMANENT_LEDGER = "permanent_ledger"
    CREDENTIAL = "credential"
    CONTROL_PLANE = "control_plane"


class ThreatActor(StrEnum):
    EXTERNAL_ATTACKER = "external_attacker"
    MALICIOUS_INSIDER = "malicious_insider"
    COMPROMISED_OPERATOR = "compromised_operator"
    COMPROMISED_DEPENDENCY = "compromised_dependency"
    ACCIDENTAL_OPERATOR = "accidental_operator"
    REPLAY_CLIENT = "replay_client"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class TrustBoundary(StrEnum):
    SOURCE_CONTROL = "source_control"
    CI_CD = "ci_cd"
    CONTROL_PLANE = "control_plane"
    OBJECT_STORAGE = "object_storage"
    RUNTIME = "runtime"
    OPERATOR_INTERFACE = "operator_interface"
    EVIDENCE_STORE = "evidence_store"


class IncidentKind(StrEnum):
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SECRET_EXPOSURE = "secret_exposure"
    AUDIENCE_BREACH = "audience_breach"
    INTEGRITY_VIOLATION = "integrity_violation"
    AVAILABILITY_LOSS = "availability_loss"
    REPLAY_ATTACK = "replay_attack"
    CONTROL_PLANE_LOSS = "control_plane_loss"
    SOURCE_CORRUPTION = "source_corruption"
    BAD_PROMOTION = "bad_promotion"
    OBJECT_LOSS = "object_loss"


class IncidentState(StrEnum):
    DETECTED = "detected"
    TRIAGED = "triaged"
    CONTAINED = "contained"
    RECOVERY_PLANNED = "recovery_planned"
    RECOVERY_AUTHORIZED = "recovery_authorized"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    BLOCKED = "blocked"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityControl(StrEnum):
    LEAST_PRIVILEGE = "least_privilege"
    EXACT_IDENTITY_PRECONDITION = "exact_identity_precondition"
    IMMUTABLE_ARTIFACTS = "immutable_artifacts"
    CHECKSUM_VERIFICATION = "checksum_verification"
    AUDIENCE_NON_BROADENING = "audience_non_broadening"
    EXPLICIT_APPROVAL = "explicit_approval"
    IDEMPOTENCY_KEY = "idempotency_key"
    FAIL_CLOSED = "fail_closed"
    DUAL_CONTROL = "dual_control"
    APPEND_ONLY_EVIDENCE = "append_only_evidence"
    REDACTION = "redaction"
    RESTORE_VERIFICATION = "restore_verification"


class DrillMode(StrEnum):
    SIMULATION_ONLY = "simulation_only"
    ISOLATED_ENVIRONMENT = "isolated_environment"
    GOVERNED_PRODUCTION = "governed_production"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RecoveryAction(StrEnum):
    ASSESS = "assess"
    CONTAIN = "contain"
    PLAN = "plan"
    VERIFY = "verify"
    RESTORE_R2_OBJECT = "restore_r2_object"
    REBUILD_RUNTIME_CACHE = "rebuild_runtime_cache"
    ROLLBACK_RELEASE = "rollback_release"
    RESTORE_SOURCE_FROM_TRUSTED_GIT = "restore_source_from_trusted_git"
    RECONSTRUCT_CONTROL_PLANE = "reconstruct_control_plane"
    ROTATE_CREDENTIAL = "rotate_credential"


_FORBIDDEN_FRAGMENTS = (
    "bearer ",
    "authorization:",
    "cookie:",
    "jwt",
    "raw_query",
    "raw_answer",
    "private excerpt",
    "client_ip",
    "ip_address",
    "hostname",
    "traceback",
    "exception_text",
    "secret_value",
    "access_key",
    "s3://",
    "r2://",
    "file://",
    "http://",
    "https://",
)

_AUDIENCE_RANK = {
    Audience.PUBLIC: 0,
    Audience.INTERNAL: 1,
    Audience.PRIVATE: 2,
}

_MODE_RANK = {
    DrillMode.SIMULATION_ONLY: 0,
    DrillMode.ISOLATED_ENVIRONMENT: 1,
    DrillMode.GOVERNED_PRODUCTION: 2,
}

_SIMULATION_ACTIONS = {
    RecoveryAction.ASSESS,
    RecoveryAction.CONTAIN,
    RecoveryAction.PLAN,
    RecoveryAction.VERIFY,
}


class M16Identity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str = Field(min_length=8, max_length=128)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ThreatScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9._:-]+$")
    actor: ThreatActor
    asset: AssetKind
    boundary: TrustBoundary
    incident_kind: IncidentKind
    likelihood: RiskLevel
    impact: RiskLevel
    source_audience: Audience
    evidence_audience: Audience
    controls: list[SecurityControl] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        if len(set(self.controls)) != len(self.controls):
            raise ValueError("threat scenario controls must be unique")
        if _AUDIENCE_RANK[self.evidence_audience] < _AUDIENCE_RANK[self.source_audience]:
            raise ValueError("security evidence audience must not broaden source audience")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class DrillPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_kind: IncidentKind
    maximum_mode: DrillMode
    required_controls: list[SecurityControl] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if len(set(self.required_controls)) != len(self.required_controls):
            raise ValueError("drill policy controls must be unique")
        return self


class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_SECURITY_CONTRACT_SCHEMA
    incident_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    detected_at: datetime
    state: IncidentState
    incident_kind: IncidentKind
    identity: M16Identity
    affected_assets: list[AssetKind] = Field(min_length=1, max_length=16)
    evidence_codes: list[str] = Field(min_length=1, max_length=32)
    audience: Audience
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("detected_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "incident detected_at")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        for value in values:
            _validate_code(value, "evidence code")
        return values

    @model_validator(mode="after")
    def validate_incident(self) -> Self:
        if len(set(self.affected_assets)) != len(self.affected_assets):
            raise ValueError("incident affected assets must be unique")
        if len(set(self.evidence_codes)) != len(self.evidence_codes):
            raise ValueError("incident evidence codes must be unique")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class RecoveryStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9._:-]+$")
    action: RecoveryAction
    target: AssetKind
    expected_evidence_code: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[a-z0-9._:-]+$",
    )


class RecoveryAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: DrillMode
    production_scope: bool = False
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    approval_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._:-]{3,96}$")
    operation_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._:-]{3,96}$")
    expected_previous_pointer_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_source_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    rollback_evidence_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9._:-]{3,96}$",
    )
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if self.permanent_ledger_append_allowed:
            raise ValueError("M16.1 never grants permanent-ledger append authority")
        if self.production_scope and self.mode != DrillMode.GOVERNED_PRODUCTION:
            raise ValueError("only governed-production plans may claim production scope")
        if self.mode != DrillMode.GOVERNED_PRODUCTION and self.production_scope:
            raise ValueError("non-production drills must remain outside production scope")
        if self.mode == DrillMode.GOVERNED_PRODUCTION:
            required = (
                self.production_scope,
                self.approval_state == ApprovalState.APPROVED,
                self.approval_id is not None,
                self.operation_id is not None,
                self.expected_previous_pointer_sha256 is not None,
                self.expected_source_sha is not None,
                self.rollback_evidence_code is not None,
            )
            if not all(required):
                raise ValueError(
                    "governed-production authority requires approval, operation identity, "
                    "exact preconditions, and rollback evidence"
                )
        elif any(
            value is not None
            for value in (
                self.approval_id,
                self.operation_id,
                self.expected_previous_pointer_sha256,
                self.expected_source_sha,
                self.rollback_evidence_code,
            )
        ):
            raise ValueError("simulation and isolated authority must not carry production tokens")
        return self


class RecoveryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_SECURITY_CONTRACT_SCHEMA
    plan_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    incident_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-zA-Z0-9._:-]+$")
    generated_at: datetime
    incident_kind: IncidentKind
    identity: M16Identity
    authority: RecoveryAuthority
    steps: list[RecoveryStep] = Field(min_length=1, max_length=32)
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "recovery plan generated_at")
        return value

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("recovery step IDs must be unique")
        if self.authority.mode == DrillMode.SIMULATION_ONLY:
            disallowed = sorted(
                step.action.value
                for step in self.steps
                if step.action not in _SIMULATION_ACTIONS
            )
            if disallowed:
                raise ValueError(f"simulation plan contains mutating actions: {disallowed}")
        if self.authority.mode == DrillMode.GOVERNED_PRODUCTION:
            if self.authority.expected_previous_pointer_sha256 != self.identity.pointer_sha256:
                raise ValueError("governed plan pointer precondition does not match exact identity")
            if self.authority.expected_source_sha != self.identity.source_sha:
                raise ValueError("governed plan Source precondition does not match exact identity")
        _reject_forbidden(self.model_dump(mode="json"))
        return self


class SecurityContractBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_SECURITY_CONTRACT_SCHEMA
    generated_at: datetime
    identity: M16Identity
    scenarios: list[ThreatScenario]
    drill_policies: list[DrillPolicy]
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        _require_utc(value, "security contract generated_at")
        return value


_DEFAULT_CONTROLS = [
    SecurityControl.EXACT_IDENTITY_PRECONDITION,
    SecurityControl.FAIL_CLOSED,
    SecurityControl.REDACTION,
    SecurityControl.APPEND_ONLY_EVIDENCE,
]


def default_threat_scenarios() -> list[ThreatScenario]:
    return [
        ThreatScenario(
            scenario_id="audience-boundary-bypass",
            actor=ThreatActor.COMPROMISED_DEPENDENCY,
            asset=AssetKind.PRODUCTION_RELEASE,
            boundary=TrustBoundary.RUNTIME,
            incident_kind=IncidentKind.AUDIENCE_BREACH,
            likelihood=RiskLevel.MEDIUM,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.PRIVATE,
            evidence_audience=Audience.PRIVATE,
            controls=[
                SecurityControl.AUDIENCE_NON_BROADENING,
                SecurityControl.FAIL_CLOSED,
                SecurityControl.REDACTION,
            ],
        ),
        ThreatScenario(
            scenario_id="bad-release-promotion",
            actor=ThreatActor.ACCIDENTAL_OPERATOR,
            asset=AssetKind.PRODUCTION_POINTER,
            boundary=TrustBoundary.CI_CD,
            incident_kind=IncidentKind.BAD_PROMOTION,
            likelihood=RiskLevel.MEDIUM,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.INTERNAL,
            evidence_audience=Audience.INTERNAL,
            controls=[
                SecurityControl.EXACT_IDENTITY_PRECONDITION,
                SecurityControl.EXPLICIT_APPROVAL,
                SecurityControl.RESTORE_VERIFICATION,
            ],
        ),
        ThreatScenario(
            scenario_id="control-plane-loss",
            actor=ThreatActor.INFRASTRUCTURE_FAILURE,
            asset=AssetKind.CONTROL_PLANE,
            boundary=TrustBoundary.CONTROL_PLANE,
            incident_kind=IncidentKind.CONTROL_PLANE_LOSS,
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.HIGH,
            source_audience=Audience.INTERNAL,
            evidence_audience=Audience.INTERNAL,
            controls=[
                SecurityControl.IMMUTABLE_ARTIFACTS,
                SecurityControl.APPEND_ONLY_EVIDENCE,
                SecurityControl.RESTORE_VERIFICATION,
            ],
        ),
        ThreatScenario(
            scenario_id="credential-exposure",
            actor=ThreatActor.EXTERNAL_ATTACKER,
            asset=AssetKind.CREDENTIAL,
            boundary=TrustBoundary.OPERATOR_INTERFACE,
            incident_kind=IncidentKind.SECRET_EXPOSURE,
            likelihood=RiskLevel.MEDIUM,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.PRIVATE,
            evidence_audience=Audience.PRIVATE,
            controls=[
                SecurityControl.LEAST_PRIVILEGE,
                SecurityControl.REDACTION,
                SecurityControl.DUAL_CONTROL,
            ],
        ),
        ThreatScenario(
            scenario_id="production-operation-replay",
            actor=ThreatActor.REPLAY_CLIENT,
            asset=AssetKind.PRODUCTION_POINTER,
            boundary=TrustBoundary.CONTROL_PLANE,
            incident_kind=IncidentKind.REPLAY_ATTACK,
            likelihood=RiskLevel.MEDIUM,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.INTERNAL,
            evidence_audience=Audience.INTERNAL,
            controls=[
                SecurityControl.IDEMPOTENCY_KEY,
                SecurityControl.EXACT_IDENTITY_PRECONDITION,
                SecurityControl.FAIL_CLOSED,
            ],
        ),
        ThreatScenario(
            scenario_id="r2-object-loss",
            actor=ThreatActor.INFRASTRUCTURE_FAILURE,
            asset=AssetKind.R2_OBJECT,
            boundary=TrustBoundary.OBJECT_STORAGE,
            incident_kind=IncidentKind.OBJECT_LOSS,
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.HIGH,
            source_audience=Audience.INTERNAL,
            evidence_audience=Audience.INTERNAL,
            controls=[
                SecurityControl.CHECKSUM_VERIFICATION,
                SecurityControl.IMMUTABLE_ARTIFACTS,
                SecurityControl.RESTORE_VERIFICATION,
            ],
        ),
        ThreatScenario(
            scenario_id="source-history-corruption",
            actor=ThreatActor.COMPROMISED_OPERATOR,
            asset=AssetKind.CANONICAL_SOURCE,
            boundary=TrustBoundary.SOURCE_CONTROL,
            incident_kind=IncidentKind.SOURCE_CORRUPTION,
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.PRIVATE,
            evidence_audience=Audience.PRIVATE,
            controls=[
                SecurityControl.EXPLICIT_APPROVAL,
                SecurityControl.IMMUTABLE_ARTIFACTS,
                SecurityControl.RESTORE_VERIFICATION,
            ],
        ),
        ThreatScenario(
            scenario_id="unauthorized-pointer-change",
            actor=ThreatActor.MALICIOUS_INSIDER,
            asset=AssetKind.PRODUCTION_POINTER,
            boundary=TrustBoundary.CONTROL_PLANE,
            incident_kind=IncidentKind.UNAUTHORIZED_ACCESS,
            likelihood=RiskLevel.LOW,
            impact=RiskLevel.CRITICAL,
            source_audience=Audience.INTERNAL,
            evidence_audience=Audience.INTERNAL,
            controls=[
                SecurityControl.LEAST_PRIVILEGE,
                SecurityControl.DUAL_CONTROL,
                SecurityControl.EXACT_IDENTITY_PRECONDITION,
            ],
        ),
    ]


def default_drill_policies() -> list[DrillPolicy]:
    isolated = {
        IncidentKind.AUDIENCE_BREACH,
        IncidentKind.INTEGRITY_VIOLATION,
        IncidentKind.AVAILABILITY_LOSS,
        IncidentKind.REPLAY_ATTACK,
        IncidentKind.CONTROL_PLANE_LOSS,
        IncidentKind.SOURCE_CORRUPTION,
        IncidentKind.BAD_PROMOTION,
        IncidentKind.OBJECT_LOSS,
    }
    policies: list[DrillPolicy] = []
    for incident_kind in IncidentKind:
        maximum_mode = (
            DrillMode.ISOLATED_ENVIRONMENT
            if incident_kind in isolated
            else DrillMode.SIMULATION_ONLY
        )
        policies.append(
            DrillPolicy(
                incident_kind=incident_kind,
                maximum_mode=maximum_mode,
                required_controls=list(_DEFAULT_CONTROLS),
            )
        )
    return policies


def build_security_contract_bundle(
    *,
    generated_at: datetime,
    identity: M16Identity,
    scenarios: list[ThreatScenario] | None = None,
    drill_policies: list[DrillPolicy] | None = None,
) -> SecurityContractBundle:
    selected_scenarios = list(scenarios or default_threat_scenarios())
    selected_policies = list(drill_policies or default_drill_policies())
    if not selected_scenarios or len(selected_scenarios) > 128:
        raise ValueError("security contract requires 1 to 128 threat scenarios")
    scenario_ids = [scenario.scenario_id for scenario in selected_scenarios]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("threat scenario IDs must be unique")
    policy_kinds = [policy.incident_kind for policy in selected_policies]
    if set(policy_kinds) != set(IncidentKind) or len(policy_kinds) != len(IncidentKind):
        raise ValueError("drill policies must cover each incident kind exactly once")
    bundle = SecurityContractBundle(
        generated_at=generated_at,
        identity=identity,
        scenarios=sorted(selected_scenarios, key=lambda item: item.scenario_id),
        drill_policies=sorted(selected_policies, key=lambda item: item.incident_kind.value),
    )
    return finalize_security_contract_bundle(bundle)


def security_contract_bundle_sha256(bundle: SecurityContractBundle) -> str:
    return _model_sha256(bundle)


def finalize_security_contract_bundle(bundle: SecurityContractBundle) -> SecurityContractBundle:
    digest = security_contract_bundle_sha256(bundle)
    if bundle.artifact_sha256 not in {None, digest}:
        raise ValueError("security contract bundle digest mismatch")
    return bundle.model_copy(update={"artifact_sha256": digest})


def incident_record_sha256(record: IncidentRecord) -> str:
    return _model_sha256(record)


def finalize_incident_record(record: IncidentRecord) -> IncidentRecord:
    digest = incident_record_sha256(record)
    if record.artifact_sha256 not in {None, digest}:
        raise ValueError("incident record digest mismatch")
    return record.model_copy(update={"artifact_sha256": digest})


def recovery_plan_sha256(plan: RecoveryPlan) -> str:
    return _model_sha256(plan)


def finalize_recovery_plan(plan: RecoveryPlan) -> RecoveryPlan:
    digest = recovery_plan_sha256(plan)
    if plan.artifact_sha256 not in {None, digest}:
        raise ValueError("recovery plan digest mismatch")
    return plan.model_copy(
        update={
            "steps": sorted(plan.steps, key=lambda item: item.step_id),
            "artifact_sha256": digest,
        }
    )


def policy_allows_mode(policy: DrillPolicy, requested_mode: DrillMode) -> bool:
    return _MODE_RANK[requested_mode] <= _MODE_RANK[policy.maximum_mode]


def _model_sha256(model: BaseModel) -> str:
    payload = model.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _validate_code(value: str, field_name: str) -> None:
    if len(value) < 3 or len(value) > 96:
        raise ValueError(f"{field_name} must contain 3 to 96 characters")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._:-")
    if any(character not in allowed for character in value):
        raise ValueError(f"{field_name} must be a bounded lowercase code")


def _reject_forbidden(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).lower()
    if any(fragment in encoded for fragment in _FORBIDDEN_FRAGMENTS):
        raise ValueError("M16 security evidence contains forbidden private or secret material")
