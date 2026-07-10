from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.m16_acl_injection_security import (
    AttackIndicator,
    M16SecurityAuthority,
    SecurityDecision,
    SecurityGateState,
    SecurityLayer,
    SecurityReason,
    SecurityReportDecision,
    SecurityTestCase,
    SecurityTestKind,
    default_adversarial_cases,
    evaluate_security_case,
    evaluate_security_report,
    finalize_security_report,
)
from knowledge_engine.m16_security_contracts import Audience, M16Identity

ENGINE = "02a8cf56099156cdf660544cd9d386569c048958"
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


def benign_case(**overrides: object) -> SecurityTestCase:
    values: dict[str, object] = {
        "test_id": "benign-control",
        "kind": SecurityTestKind.BENIGN_CONTROL,
        "layer": SecurityLayer.ANSWER,
        "identity": identity(),
        "generated_at": NOW,
        "source_audience": Audience.PUBLIC,
        "output_audience": Audience.PUBLIC,
        "requester_privilege": Audience.PUBLIC,
        "indicators": [],
        "evidence_codes": ["m16.2.benign"],
        "expected_decision": SecurityDecision.ALLOW,
        "expected_reason": SecurityReason.NONE,
    }
    values.update(overrides)
    return SecurityTestCase(**values)


def test_default_corpus_passes_and_is_deterministic() -> None:
    cases = default_adversarial_cases(generated_at=NOW, identity=identity())
    first = evaluate_security_report(cases, generated_at=NOW, identity=identity())
    second = evaluate_security_report(
        list(reversed(cases)),
        generated_at=NOW,
        identity=identity(),
    )
    assert first.decision == SecurityReportDecision.PASSED
    assert first.artifact_sha256 == second.artifact_sha256
    assert all(gate.state == SecurityGateState.PASSED for gate in first.gates)


def test_default_attack_cases_block_and_benign_control_allows() -> None:
    report = evaluate_security_report(
        default_adversarial_cases(generated_at=NOW, identity=identity()),
        generated_at=NOW,
        identity=identity(),
    )
    by_id = {result.test_id: result for result in report.results}
    assert by_id["benign-public-control"].observed_decision == SecurityDecision.ALLOW
    blocked = [
        result
        for result in report.results
        if result.test_id != "benign-public-control"
    ]
    assert blocked
    assert all(result.observed_decision == SecurityDecision.BLOCK for result in blocked)


def test_acl_audience_broadening_is_blocked() -> None:
    case = benign_case(
        test_id="private-to-public",
        kind=SecurityTestKind.ACL_PROPAGATION,
        source_audience=Audience.PRIVATE,
        output_audience=Audience.PUBLIC,
        expected_decision=SecurityDecision.BLOCK,
        expected_reason=SecurityReason.AUDIENCE_BROADENING,
    )
    result = evaluate_security_case(case, expected_identity=identity())
    assert result.observed_reason == SecurityReason.AUDIENCE_BROADENING
    assert result.matched_expectation


def test_requester_privilege_is_fail_closed() -> None:
    case = benign_case(
        test_id="public-requester-private-answer",
        kind=SecurityTestKind.REQUESTER_PRIVILEGE,
        source_audience=Audience.PRIVATE,
        output_audience=Audience.PRIVATE,
        requester_privilege=Audience.PUBLIC,
        expected_decision=SecurityDecision.BLOCK,
        expected_reason=SecurityReason.INSUFFICIENT_PRIVILEGE,
    )
    result = evaluate_security_case(case, expected_identity=identity())
    assert result.observed_reason == SecurityReason.INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    ("indicator", "reason"),
    [
        (AttackIndicator.PRIVATE_DATA_PRESENT, SecurityReason.PRIVATE_DATA),
        (AttackIndicator.SECRET_MATERIAL_PRESENT, SecurityReason.SECRET_MATERIAL),
        (AttackIndicator.INSTRUCTION_OVERRIDE, SecurityReason.PROMPT_OVERRIDE),
        (
            AttackIndicator.SYSTEM_PROMPT_REQUEST,
            SecurityReason.SYSTEM_PROMPT_EXTRACTION,
        ),
        (AttackIndicator.ROLE_TOOL_SPOOF, SecurityReason.ROLE_TOOL_SPOOF),
        (
            AttackIndicator.CITATION_FABRICATION,
            SecurityReason.CITATION_FABRICATION,
        ),
        (
            AttackIndicator.RESTRICTED_CITATION,
            SecurityReason.RESTRICTED_CITATION,
        ),
        (AttackIndicator.PRIVATE_FALLBACK, SecurityReason.UNSAFE_FALLBACK),
        (AttackIndicator.RAW_SOURCE_EXCERPT, SecurityReason.RAW_SOURCE_EXCERPT),
    ],
)
def test_closed_attack_indicators_are_blocked(
    indicator: AttackIndicator,
    reason: SecurityReason,
) -> None:
    case = benign_case(
        test_id=f"indicator-{indicator.value}",
        indicators=[indicator],
        expected_decision=SecurityDecision.BLOCK,
        expected_reason=reason,
    )
    result = evaluate_security_case(case, expected_identity=identity())
    assert result.observed_decision == SecurityDecision.BLOCK
    assert result.observed_reason == reason


def test_identity_drift_cannot_authorize_access() -> None:
    case = benign_case(identity=identity(engine_sha="0" * 40))
    result = evaluate_security_case(case, expected_identity=identity())
    assert result.observed_decision == SecurityDecision.BLOCK
    assert result.observed_reason == SecurityReason.IDENTITY_DRIFT
    assert not result.matched_expectation


def test_unexpected_allow_blocks_report_gate() -> None:
    case = benign_case(
        expected_decision=SecurityDecision.BLOCK,
        expected_reason=SecurityReason.PROMPT_OVERRIDE,
    )
    report = evaluate_security_report([case], generated_at=NOW, identity=identity())
    assert report.decision == SecurityReportDecision.BLOCKED
    assert any(gate.state == SecurityGateState.BLOCKED for gate in report.gates)


def test_duplicate_test_ids_are_rejected() -> None:
    case = benign_case()
    with pytest.raises(ValueError, match="unique"):
        evaluate_security_report([case, case], generated_at=NOW, identity=identity())


def test_non_utc_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        benign_case(generated_at=datetime(2026, 7, 10, 6, 0))
    with pytest.raises(ValueError, match="UTC"):
        evaluate_security_report(
            [benign_case()],
            generated_at=datetime(2026, 7, 10, 6, 0),
            identity=identity(),
        )


def test_evidence_codes_reject_urls_and_secret_shaped_payloads() -> None:
    with pytest.raises(ValidationError):
        benign_case(evidence_codes=["https://private.example"])
    with pytest.raises(ValidationError):
        benign_case(evidence_codes=["Bearer token-value"])


def test_raw_payload_fields_are_not_part_of_contract() -> None:
    payload = benign_case().model_dump()
    payload["raw_query"] = "private question"
    with pytest.raises(ValidationError):
        SecurityTestCase(**payload)


def test_no_write_authority_is_enforced() -> None:
    with pytest.raises(ValidationError):
        M16SecurityAuthority(acl_mutation_allowed=True)
    with pytest.raises(ValidationError):
        M16SecurityAuthority(production_write_allowed=True)
    with pytest.raises(ValidationError):
        M16SecurityAuthority(permanent_ledger_append_allowed=True)


def test_report_is_tamper_evident() -> None:
    report = evaluate_security_report(
        [benign_case()],
        generated_at=NOW,
        identity=identity(),
    )
    tampered = report.model_copy(update={"decision": SecurityReportDecision.BLOCKED})
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize_security_report(tampered)
