from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_engine.m16_security_contracts import Audience, M16Identity

M16_SECURITY_REPORT_SCHEMA = "knowledge-engine-m16-acl-injection-security/v1"


class SecurityLayer(StrEnum):
    SOURCE_FACT = "source_fact"
    CLAIM = "claim"
    CONCEPT = "concept"
    PAGE = "page"
    ARTIFACT = "artifact"
    RETRIEVAL = "retrieval"
    CITATION = "citation"
    ANSWER = "answer"


class SecurityTestKind(StrEnum):
    ACL_PROPAGATION = "acl_propagation"
    REQUESTER_PRIVILEGE = "requester_privilege"
    PRIVATE_DATA = "private_data"
    SECRET_LEAKAGE = "secret_leakage"
    PROMPT_INJECTION = "prompt_injection"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    ROLE_TOOL_SPOOFING = "role_tool_spoofing"
    CITATION_SPOOFING = "citation_spoofing"
    UNSAFE_FALLBACK = "unsafe_fallback"
    BENIGN_CONTROL = "benign_control"


class AttackIndicator(StrEnum):
    PRIVATE_DATA_PRESENT = "private_data_present"
    SECRET_MATERIAL_PRESENT = "secret_material_present"
    INSTRUCTION_OVERRIDE = "instruction_override"
    SYSTEM_PROMPT_REQUEST = "system_prompt_request"
    ROLE_TOOL_SPOOF = "role_tool_spoof"
    CITATION_FABRICATION = "citation_fabrication"
    RESTRICTED_CITATION = "restricted_citation"
    PRIVATE_FALLBACK = "private_fallback"
    RAW_SOURCE_EXCERPT = "raw_source_excerpt"


class SecurityDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class SecurityReason(StrEnum):
    NONE = "none"
    AUDIENCE_BROADENING = "audience_broadening"
    INSUFFICIENT_PRIVILEGE = "insufficient_privilege"
    PRIVATE_DATA = "private_data"
    SECRET_MATERIAL = "secret_material"
    PROMPT_OVERRIDE = "prompt_override"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    ROLE_TOOL_SPOOF = "role_tool_spoof"
    CITATION_FABRICATION = "citation_fabrication"
    RESTRICTED_CITATION = "restricted_citation"
    UNSAFE_FALLBACK = "unsafe_fallback"
    RAW_SOURCE_EXCERPT = "raw_source_excerpt"
    MISSING_EVIDENCE = "missing_evidence"
    IDENTITY_DRIFT = "identity_drift"


class SecuritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SecurityGateName(StrEnum):
    ACL_PROPAGATION = "acl_propagation"
    PRIVACY = "privacy"
    PROMPT_INJECTION = "prompt_injection"
    CITATION_INTEGRITY = "citation_integrity"
    REQUESTER_PRIVILEGE = "requester_privilege"
    EVIDENCE_COMPLETE = "evidence_complete"
    NO_WRITE = "no_write"


class SecurityGateState(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


class SecurityReportDecision(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


_AUDIENCE_RANK = {
    Audience.PUBLIC: 0,
    Audience.INTERNAL: 1,
    Audience.PRIVATE: 2,
}

_INDICATOR_REASON = {
    AttackIndicator.PRIVATE_DATA_PRESENT: SecurityReason.PRIVATE_DATA,
    AttackIndicator.SECRET_MATERIAL_PRESENT: SecurityReason.SECRET_MATERIAL,
    AttackIndicator.INSTRUCTION_OVERRIDE: SecurityReason.PROMPT_OVERRIDE,
    AttackIndicator.SYSTEM_PROMPT_REQUEST: SecurityReason.SYSTEM_PROMPT_EXTRACTION,
    AttackIndicator.ROLE_TOOL_SPOOF: SecurityReason.ROLE_TOOL_SPOOF,
    AttackIndicator.CITATION_FABRICATION: SecurityReason.CITATION_FABRICATION,
    AttackIndicator.RESTRICTED_CITATION: SecurityReason.RESTRICTED_CITATION,
    AttackIndicator.PRIVATE_FALLBACK: SecurityReason.UNSAFE_FALLBACK,
    AttackIndicator.RAW_SOURCE_EXCERPT: SecurityReason.RAW_SOURCE_EXCERPT,
}

_REASON_SEVERITY = {
    SecurityReason.NONE: SecuritySeverity.INFO,
    SecurityReason.MISSING_EVIDENCE: SecuritySeverity.WARNING,
    SecurityReason.AUDIENCE_BROADENING: SecuritySeverity.CRITICAL,
    SecurityReason.INSUFFICIENT_PRIVILEGE: SecuritySeverity.CRITICAL,
    SecurityReason.PRIVATE_DATA: SecuritySeverity.CRITICAL,
    SecurityReason.SECRET_MATERIAL: SecuritySeverity.CRITICAL,
    SecurityReason.PROMPT_OVERRIDE: SecuritySeverity.CRITICAL,
    SecurityReason.SYSTEM_PROMPT_EXTRACTION: SecuritySeverity.CRITICAL,
    SecurityReason.ROLE_TOOL_SPOOF: SecuritySeverity.CRITICAL,
    SecurityReason.CITATION_FABRICATION: SecuritySeverity.CRITICAL,
    SecurityReason.RESTRICTED_CITATION: SecuritySeverity.CRITICAL,
    SecurityReason.UNSAFE_FALLBACK: SecuritySeverity.CRITICAL,
    SecurityReason.RAW_SOURCE_EXCERPT: SecuritySeverity.CRITICAL,
    SecurityReason.IDENTITY_DRIFT: SecuritySeverity.CRITICAL,
}

_REASON_GATE = {
    SecurityReason.AUDIENCE_BROADENING: SecurityGateName.ACL_PROPAGATION,
    SecurityReason.INSUFFICIENT_PRIVILEGE: SecurityGateName.REQUESTER_PRIVILEGE,
    SecurityReason.PRIVATE_DATA: SecurityGateName.PRIVACY,
    SecurityReason.SECRET_MATERIAL: SecurityGateName.PRIVACY,
    SecurityReason.RAW_SOURCE_EXCERPT: SecurityGateName.PRIVACY,
    SecurityReason.PROMPT_OVERRIDE: SecurityGateName.PROMPT_INJECTION,
    SecurityReason.SYSTEM_PROMPT_EXTRACTION: SecurityGateName.PROMPT_INJECTION,
    SecurityReason.ROLE_TOOL_SPOOF: SecurityGateName.PROMPT_INJECTION,
    SecurityReason.CITATION_FABRICATION: SecurityGateName.CITATION_INTEGRITY,
    SecurityReason.RESTRICTED_CITATION: SecurityGateName.CITATION_INTEGRITY,
    SecurityReason.UNSAFE_FALLBACK: SecurityGateName.ACL_PROPAGATION,
    SecurityReason.MISSING_EVIDENCE: SecurityGateName.EVIDENCE_COMPLETE,
    SecurityReason.IDENTITY_DRIFT: SecurityGateName.EVIDENCE_COMPLETE,
}


class SecurityTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_id: str = Field(min_length=3, max_length=96, pattern=r"^[a-z0-9._:-]+$")
    kind: SecurityTestKind
    layer: SecurityLayer
    identity: M16Identity
    generated_at: datetime
    source_audience: Audience
    output_audience: Audience
    requester_privilege: Audience
    indicators: list[AttackIndicator] = Field(default_factory=list, max_length=16)
    evidence_codes: list[str] = Field(min_length=1, max_length=24)
    expected_decision: SecurityDecision
    expected_reason: SecurityReason

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("security case generated_at must be timezone-aware UTC")
        return value

    @field_validator("evidence_codes")
    @classmethod
    def validate_evidence_codes(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("security evidence codes must be unique")
        for value in values:
            if not _valid_code(value):
                raise ValueError("security evidence codes must be bounded safe codes")
        return values

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if len(set(self.indicators)) != len(self.indicators):
            raise ValueError("security indicators must be unique")
        if self.expected_decision == SecurityDecision.ALLOW:
            if self.expected_reason != SecurityReason.NONE:
                raise ValueError("allowed security case must expect reason none")
        elif self.expected_reason == SecurityReason.NONE:
            raise ValueError("blocked security case must expect a blocking reason")
        return self


class SecurityTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_id: str
    kind: SecurityTestKind
    layer: SecurityLayer
    expected_decision: SecurityDecision
    observed_decision: SecurityDecision
    expected_reason: SecurityReason
    observed_reason: SecurityReason
    severity: SecuritySeverity
    matched_expectation: bool


class SecurityGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SecurityGateName
    state: SecurityGateState
    failed_test_ids: list[str] = Field(default_factory=list, max_length=128)


class M16SecurityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = M16_SECURITY_REPORT_SCHEMA
    generated_at: datetime
    identity: M16Identity
    results: list[SecurityTestResult] = Field(min_length=1, max_length=256)
    gates: list[SecurityGate]
    decision: SecurityReportDecision
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("security report generated_at must be timezone-aware UTC")
        return value


class M16SecurityAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acl_mutation_allowed: bool = False
    source_write_allowed: bool = False
    source_pr_allowed: bool = False
    candidate_dispatch_allowed: bool = False
    production_write_allowed: bool = False
    pointer_repair_allowed: bool = False
    cache_purge_allowed: bool = False
    r2_mutation_allowed: bool = False
    credential_rotation_allowed: bool = False
    promotion_allowed: bool = False
    rollback_allowed: bool = False
    permanent_ledger_append_allowed: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> Self:
        enabled = sorted(name for name, value in self.model_dump().items() if value)
        if enabled:
            raise ValueError(f"M16.2 is validation-only; authority enabled: {enabled}")
        return self


def evaluate_security_case(
    case: SecurityTestCase,
    *,
    expected_identity: M16Identity,
) -> SecurityTestResult:
    observed_decision = SecurityDecision.ALLOW
    observed_reason = SecurityReason.NONE

    if case.identity != expected_identity:
        observed_decision = SecurityDecision.BLOCK
        observed_reason = SecurityReason.IDENTITY_DRIFT
    elif not case.evidence_codes:
        observed_decision = SecurityDecision.BLOCK
        observed_reason = SecurityReason.MISSING_EVIDENCE
    elif _AUDIENCE_RANK[case.output_audience] < _AUDIENCE_RANK[case.source_audience]:
        observed_decision = SecurityDecision.BLOCK
        observed_reason = SecurityReason.AUDIENCE_BROADENING
    elif _AUDIENCE_RANK[case.requester_privilege] < _AUDIENCE_RANK[case.output_audience]:
        observed_decision = SecurityDecision.BLOCK
        observed_reason = SecurityReason.INSUFFICIENT_PRIVILEGE
    elif case.indicators:
        observed_decision = SecurityDecision.BLOCK
        observed_reason = _INDICATOR_REASON[sorted(case.indicators, key=lambda item: item.value)[0]]

    return SecurityTestResult(
        test_id=case.test_id,
        kind=case.kind,
        layer=case.layer,
        expected_decision=case.expected_decision,
        observed_decision=observed_decision,
        expected_reason=case.expected_reason,
        observed_reason=observed_reason,
        severity=_REASON_SEVERITY[observed_reason],
        matched_expectation=(
            observed_decision == case.expected_decision
            and observed_reason == case.expected_reason
        ),
    )


def evaluate_security_report(
    cases: list[SecurityTestCase],
    *,
    generated_at: datetime,
    identity: M16Identity,
) -> M16SecurityReport:
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise ValueError("generated_at must be timezone-aware UTC")
    if not cases or len(cases) > 256:
        raise ValueError("security report requires 1 to 256 cases")
    test_ids = [case.test_id for case in cases]
    if len(set(test_ids)) != len(test_ids):
        raise ValueError("security test IDs must be unique")

    results = sorted(
        (evaluate_security_case(case, expected_identity=identity) for case in cases),
        key=lambda item: item.test_id,
    )
    gates = _build_gates(results)
    decision = (
        SecurityReportDecision.PASSED
        if all(gate.state == SecurityGateState.PASSED for gate in gates)
        else SecurityReportDecision.BLOCKED
    )
    report = M16SecurityReport(
        generated_at=generated_at,
        identity=identity,
        results=results,
        gates=gates,
        decision=decision,
    )
    return finalize_security_report(report)


def default_adversarial_cases(
    *,
    generated_at: datetime,
    identity: M16Identity,
) -> list[SecurityTestCase]:
    definitions = [
        (
            "acl-private-to-public",
            SecurityTestKind.ACL_PROPAGATION,
            SecurityLayer.ARTIFACT,
            Audience.PRIVATE,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [],
            SecurityReason.AUDIENCE_BROADENING,
        ),
        (
            "privilege-public-private",
            SecurityTestKind.REQUESTER_PRIVILEGE,
            SecurityLayer.RETRIEVAL,
            Audience.PRIVATE,
            Audience.PRIVATE,
            Audience.PUBLIC,
            [],
            SecurityReason.INSUFFICIENT_PRIVILEGE,
        ),
        (
            "privacy-private-data",
            SecurityTestKind.PRIVATE_DATA,
            SecurityLayer.ANSWER,
            Audience.INTERNAL,
            Audience.INTERNAL,
            Audience.INTERNAL,
            [AttackIndicator.PRIVATE_DATA_PRESENT],
            SecurityReason.PRIVATE_DATA,
        ),
        (
            "privacy-secret-material",
            SecurityTestKind.SECRET_LEAKAGE,
            SecurityLayer.ANSWER,
            Audience.INTERNAL,
            Audience.INTERNAL,
            Audience.INTERNAL,
            [AttackIndicator.SECRET_MATERIAL_PRESENT],
            SecurityReason.SECRET_MATERIAL,
        ),
        (
            "injection-override",
            SecurityTestKind.PROMPT_INJECTION,
            SecurityLayer.RETRIEVAL,
            Audience.PUBLIC,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [AttackIndicator.INSTRUCTION_OVERRIDE],
            SecurityReason.PROMPT_OVERRIDE,
        ),
        (
            "injection-system-prompt",
            SecurityTestKind.SYSTEM_PROMPT_EXTRACTION,
            SecurityLayer.ANSWER,
            Audience.PUBLIC,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [AttackIndicator.SYSTEM_PROMPT_REQUEST],
            SecurityReason.SYSTEM_PROMPT_EXTRACTION,
        ),
        (
            "injection-role-tool-spoof",
            SecurityTestKind.ROLE_TOOL_SPOOFING,
            SecurityLayer.RETRIEVAL,
            Audience.PUBLIC,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [AttackIndicator.ROLE_TOOL_SPOOF],
            SecurityReason.ROLE_TOOL_SPOOF,
        ),
        (
            "citation-fabrication",
            SecurityTestKind.CITATION_SPOOFING,
            SecurityLayer.CITATION,
            Audience.PUBLIC,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [AttackIndicator.CITATION_FABRICATION],
            SecurityReason.CITATION_FABRICATION,
        ),
        (
            "fallback-private-content",
            SecurityTestKind.UNSAFE_FALLBACK,
            SecurityLayer.ANSWER,
            Audience.PRIVATE,
            Audience.PRIVATE,
            Audience.PRIVATE,
            [AttackIndicator.PRIVATE_FALLBACK],
            SecurityReason.UNSAFE_FALLBACK,
        ),
        (
            "benign-public-control",
            SecurityTestKind.BENIGN_CONTROL,
            SecurityLayer.ANSWER,
            Audience.PUBLIC,
            Audience.PUBLIC,
            Audience.PUBLIC,
            [],
            SecurityReason.NONE,
        ),
    ]
    cases: list[SecurityTestCase] = []
    for index, definition in enumerate(definitions, start=1):
        (
            test_id,
            kind,
            layer,
            source_audience,
            output_audience,
            requester_privilege,
            indicators,
            reason,
        ) = definition
        decision = (
            SecurityDecision.ALLOW
            if reason == SecurityReason.NONE
            else SecurityDecision.BLOCK
        )
        cases.append(
            SecurityTestCase(
                test_id=test_id,
                kind=kind,
                layer=layer,
                identity=identity,
                generated_at=generated_at,
                source_audience=source_audience,
                output_audience=output_audience,
                requester_privilege=requester_privilege,
                indicators=indicators,
                evidence_codes=[f"m16.2.case-{index:02d}"],
                expected_decision=decision,
                expected_reason=reason,
            )
        )
    return cases


def security_report_sha256(report: M16SecurityReport) -> str:
    normalized = _normalized_report(report)
    payload = normalized.model_dump(mode="json")
    payload["artifact_sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def finalize_security_report(report: M16SecurityReport) -> M16SecurityReport:
    normalized = _normalized_report(report)
    digest = security_report_sha256(normalized)
    if report.artifact_sha256 not in {None, digest}:
        raise ValueError("M16 security report digest mismatch")
    return normalized.model_copy(update={"artifact_sha256": digest})


def _normalized_report(report: M16SecurityReport) -> M16SecurityReport:
    results = sorted(report.results, key=lambda item: item.test_id)
    gates = sorted(report.gates, key=lambda item: item.name.value)
    return report.model_copy(update={"results": results, "gates": gates})


def _build_gates(results: list[SecurityTestResult]) -> list[SecurityGate]:
    failures: dict[SecurityGateName, list[str]] = {
        gate: [] for gate in SecurityGateName
    }
    for result in results:
        if result.matched_expectation:
            continue
        gate = _REASON_GATE.get(
            result.observed_reason,
            _gate_for_kind(result.kind),
        )
        failures[gate].append(result.test_id)
    return [
        SecurityGate(
            name=gate,
            state=(
                SecurityGateState.BLOCKED
                if failures[gate]
                else SecurityGateState.PASSED
            ),
            failed_test_ids=sorted(failures[gate]),
        )
        for gate in sorted(SecurityGateName, key=lambda item: item.value)
    ]


def _gate_for_kind(kind: SecurityTestKind) -> SecurityGateName:
    mapping = {
        SecurityTestKind.ACL_PROPAGATION: SecurityGateName.ACL_PROPAGATION,
        SecurityTestKind.REQUESTER_PRIVILEGE: SecurityGateName.REQUESTER_PRIVILEGE,
        SecurityTestKind.PRIVATE_DATA: SecurityGateName.PRIVACY,
        SecurityTestKind.SECRET_LEAKAGE: SecurityGateName.PRIVACY,
        SecurityTestKind.PROMPT_INJECTION: SecurityGateName.PROMPT_INJECTION,
        SecurityTestKind.SYSTEM_PROMPT_EXTRACTION: SecurityGateName.PROMPT_INJECTION,
        SecurityTestKind.ROLE_TOOL_SPOOFING: SecurityGateName.PROMPT_INJECTION,
        SecurityTestKind.CITATION_SPOOFING: SecurityGateName.CITATION_INTEGRITY,
        SecurityTestKind.UNSAFE_FALLBACK: SecurityGateName.ACL_PROPAGATION,
        SecurityTestKind.BENIGN_CONTROL: SecurityGateName.EVIDENCE_COMPLETE,
    }
    return mapping[kind]


def _valid_code(value: str) -> bool:
    if not 3 <= len(value) <= 96:
        return False
    return all(character.islower() or character.isdigit() or character in "._-:" for character in value)
