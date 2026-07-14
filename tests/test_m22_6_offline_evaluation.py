from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m22_offline_evaluation import evaluate_controlled_variants
from knowledge_engine.m22_reasoning_modes import PROTECTED_MUTATION_KEYS


def _package(
    *,
    package_sha: str,
    disposition: str = "answered",
    claims: list[str] | None = None,
    citations: int = 1,
    fallback_reason: str | None = None,
) -> dict:
    claim_hashes = claims or []
    return {
        "schema_version": "knowledge-engine-m22-grounded-answer-package/v1",
        "trace_sha256": "a" * 64,
        "package_sha256": package_sha,
        "disposition": disposition,
        "audience": "public",
        "answer_sha256": "b" * 64 if disposition == "answered" else None,
        "claim_order": [
            f"claim-{index:02d}" for index in range(1, len(claim_hashes) + 1)
        ],
        "claims": [
            {
                "claim_id": f"claim-{index:02d}",
                "claim_sha256": claim_sha,
                "evidence_refs": [f"output:step-{index:02d}"],
                "citation_ids": [f"citation-{index:02d}"],
                "acl_passed": True,
                "provenance_complete": True,
                "supported": True,
            }
            for index, claim_sha in enumerate(claim_hashes, start=1)
        ],
        "citations": [
            {
                "citation_id": f"citation-{index:02d}",
                "source_ref": f"source:{index}",
                "evidence_refs": [f"output:step-{index:02d}"],
                "audience": "public",
                "acl_passed": True,
                "provenance_complete": True,
            }
            for index in range(1, citations + 1)
        ],
        "fallback_reason": fallback_reason,
        "answer_evidence_validated": True,
        "answer_content_generated_by_validator": False,
        "provider_call_performed": False,
        "production_authority": False,
    }


def _variant(
    package: dict,
    *,
    tokens: int = 100,
    calls: int = 1,
    elapsed: int = 100,
) -> dict:
    evidence = {
        "execution_trace": {
            "usage": {
                "total_tokens": tokens,
                "model_calls": calls,
                "elapsed_ms": elapsed,
            }
        }
    }
    return {
        "answer_evidence": evidence,
        "grounded_package": package,
    }


def _rubric(*, required: list[str] | None = None) -> dict:
    return {
        "expected_disposition": "answered",
        "expected_fallback_reason": None,
        "required_claim_sha256s": required or [],
        "forbidden_claim_sha256s": [],
        "min_citations": 1,
        "max_total_tokens": 1000,
        "max_model_calls": 4,
        "max_elapsed_ms": 1000,
    }


def _case(
    *,
    baseline: dict,
    candidate: dict,
    rubric: dict | None = None,
    case_id: str = "case-01",
    case_key: str = "quality:one",
) -> dict:
    return {
        "case_id": case_id,
        "case_key": case_key,
        "rubric": rubric or _rubric(),
        "baseline": baseline,
        "candidate": candidate,
    }


def _payload(case: dict, *, minimum_gain: int = 1) -> dict:
    return {
        "schema_version": "knowledge-engine-m22-evaluation-evidence/v1",
        "suite_id": "suite:m22-6-test",
        "minimum_quality_gain": minimum_gain,
        "cases": [case],
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }


def _validate_from_supplied(evidence: dict) -> dict:
    return copy.deepcopy(evidence["__package"])


def _bind_variant(variant: dict) -> dict:
    bound = copy.deepcopy(variant)
    bound["answer_evidence"]["__package"] = copy.deepcopy(
        bound["grounded_package"]
    )
    return bound


def _run(payload: dict) -> dict:
    with patch(
        "knowledge_engine.m22_offline_evaluation.validate_grounded_answer_package",
        side_effect=_validate_from_supplied,
    ):
        return evaluate_controlled_variants(payload)


def test_promote_candidate_when_quality_gain_reaches_threshold() -> None:
    required = ["1" * 64]
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64, claims=[])))
    candidate = _bind_variant(
        _variant(_package(package_sha="b" * 64, claims=required))
    )
    result = _run(
        _payload(
            _case(
                baseline=baseline,
                candidate=candidate,
                rubric=_rubric(required=required),
            ),
            minimum_gain=20,
        )
    )
    assert result["recommendation"] == "promote_candidate"
    assert result["aggregate"]["candidate_all_passed"] is True
    assert result["rollout_performed"] is False
    assert result["traffic_changed"] is False
    assert result["production_authority"] is False


def test_hold_when_safe_but_gain_is_below_threshold() -> None:
    claims = ["1" * 64]
    baseline = _bind_variant(
        _variant(_package(package_sha="a" * 64, claims=claims))
    )
    candidate = _bind_variant(
        _variant(_package(package_sha="b" * 64, claims=claims))
    )
    result = _run(
        _payload(
            _case(
                baseline=baseline,
                candidate=candidate,
                rubric=_rubric(required=claims),
            ),
            minimum_gain=1,
        )
    )
    assert result["recommendation"] == "hold"
    assert result["reason_codes"] == ["quality_gain_below_threshold"]


def test_reject_on_candidate_regression() -> None:
    required = ["1" * 64]
    baseline = _bind_variant(
        _variant(_package(package_sha="a" * 64, claims=required))
    )
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64, claims=[])))
    result = _run(
        _payload(
            _case(
                baseline=baseline,
                candidate=candidate,
                rubric=_rubric(required=required),
            )
        )
    )
    assert result["recommendation"] == "reject"
    assert "candidate_case_failed" in result["reason_codes"]
    assert "baseline_regression" in result["reason_codes"]


def test_output_is_deterministic_and_input_is_not_mutated() -> None:
    claims = ["1" * 64]
    baseline = _bind_variant(
        _variant(_package(package_sha="a" * 64, claims=claims))
    )
    candidate = _bind_variant(
        _variant(_package(package_sha="b" * 64, claims=claims))
    )
    payload = _payload(
        _case(
            baseline=baseline,
            candidate=candidate,
            rubric=_rubric(required=claims),
        )
    )
    before = copy.deepcopy(payload)
    first = _run(payload)
    second = _run(payload)
    assert first == second
    assert payload == before
    assert len(first["evaluation_sha256"]) == 64


def test_tampered_package_is_rejected() -> None:
    package = _package(package_sha="a" * 64)
    baseline = _bind_variant(_variant(package))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    baseline["grounded_package"]["package_sha256"] = "f" * 64
    with pytest.raises(IntegrityError, match="package does not match evidence"):
        _run(_payload(_case(baseline=baseline, candidate=candidate)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer_evidence_validated", False),
        ("answer_content_generated_by_validator", True),
        ("provider_call_performed", True),
        ("production_authority", True),
    ],
)
def test_invalid_package_authority_is_rejected(field: str, value: object) -> None:
    package = _package(package_sha="a" * 64)
    package[field] = value
    baseline = _bind_variant(_variant(package))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    with pytest.raises(IntegrityError, match="package authority is invalid"):
        _run(_payload(_case(baseline=baseline, candidate=candidate)))


def test_cost_ceiling_failure_rejects_candidate() -> None:
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(
        _variant(_package(package_sha="b" * 64), tokens=2000)
    )
    result = _run(_payload(_case(baseline=baseline, candidate=candidate)))
    assert result["recommendation"] == "reject"
    assert result["cases"][0]["candidate"]["cost_compliant"] is False


def test_fallback_rubric_is_supported() -> None:
    package_a = _package(
        package_sha="a" * 64,
        disposition="fallback",
        citations=0,
        fallback_reason="not_found",
    )
    package_b = _package(
        package_sha="b" * 64,
        disposition="fallback",
        citations=0,
        fallback_reason="not_found",
    )
    rubric = _rubric()
    rubric.update(
        {
            "expected_disposition": "fallback",
            "expected_fallback_reason": "not_found",
            "min_citations": 0,
        }
    )
    result = _run(
        _payload(
            _case(
                baseline=_bind_variant(_variant(package_a)),
                candidate=_bind_variant(_variant(package_b)),
                rubric=rubric,
            )
        )
    )
    assert result["recommendation"] == "hold"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("case_id", "case-02", "case IDs must be sequential"),
        ("case_key", "../unsafe", "case key is invalid"),
    ],
)
def test_case_identity_is_strict(
    field: str,
    value: object,
    message: str,
) -> None:
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    case = _case(baseline=baseline, candidate=candidate)
    case[field] = value
    with pytest.raises(IntegrityError, match=message):
        _run(_payload(case))


def test_duplicate_case_keys_are_rejected() -> None:
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    first = _case(baseline=baseline, candidate=candidate)
    second = _case(
        baseline=copy.deepcopy(baseline),
        candidate=copy.deepcopy(candidate),
        case_id="case-02",
    )
    payload = _payload(first)
    payload["cases"].append(second)
    with pytest.raises(IntegrityError, match="case keys must be unique"):
        _run(payload)


def test_required_and_forbidden_claims_cannot_overlap() -> None:
    claim = "1" * 64
    rubric = _rubric(required=[claim])
    rubric["forbidden_claim_sha256s"] = [claim]
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    with pytest.raises(IntegrityError, match="claims overlap"):
        _run(
            _payload(
                _case(
                    baseline=baseline,
                    candidate=candidate,
                    rubric=rubric,
                )
            )
        )


def test_fallback_rubric_cannot_require_citations() -> None:
    rubric = _rubric()
    rubric.update(
        {
            "expected_disposition": "fallback",
            "expected_fallback_reason": "not_found",
            "min_citations": 1,
        }
    )
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    with pytest.raises(IntegrityError, match="cannot require citations"):
        _run(
            _payload(
                _case(
                    baseline=baseline,
                    candidate=candidate,
                    rubric=rubric,
                )
            )
        )


def test_empty_suite_is_rejected() -> None:
    payload = {
        "schema_version": "knowledge-engine-m22-evaluation-evidence/v1",
        "suite_id": "suite:empty",
        "minimum_quality_gain": 1,
        "cases": [],
        "protected_state": {name: False for name in PROTECTED_MUTATION_KEYS},
    }
    with pytest.raises(IntegrityError, match="cannot be empty"):
        _run(payload)


def test_unknown_fields_and_schema_drift_fail_closed() -> None:
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    payload = _payload(_case(baseline=baseline, candidate=candidate))
    payload["raw_query"] = "forbidden"
    with pytest.raises(IntegrityError, match="shape is invalid"):
        _run(payload)

    payload = _payload(_case(baseline=baseline, candidate=candidate))
    payload["schema_version"] = "knowledge-engine-m22-evaluation-evidence/v2"
    with pytest.raises(IntegrityError, match="unsupported evaluation evidence"):
        _run(payload)


def test_any_protected_mutation_fails_closed() -> None:
    baseline = _bind_variant(_variant(_package(package_sha="a" * 64)))
    candidate = _bind_variant(_variant(_package(package_sha="b" * 64)))
    for name in PROTECTED_MUTATION_KEYS:
        payload = _payload(_case(baseline=baseline, candidate=candidate))
        payload["protected_state"][name] = True
        with pytest.raises(IntegrityError, match="protected mutation was dispatched"):
            _run(payload)
