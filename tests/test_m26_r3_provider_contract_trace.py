from __future__ import annotations

import json

from knowledge_engine import m26_pa7_arbitrary_query_runtime as legacy
from knowledge_engine.m26_provider_contract_trace import (
    TRACE_SCHEMA_VERSION,
    _attach_trace_to_response,
    diagnose_fast_provider_result,
)


def _raw(status: str, answer_text: str, citation_ids: list[str], reason=None):
    return {
        "text": json.dumps(
            {
                "status": status,
                "answer_text": answer_text,
                "citation_ids": citation_ids,
                "abstention_reason": reason,
            }
        )
    }


def test_installer_preserves_fast_normalizer_return_semantics() -> None:
    cases = [
        _raw("answer", "Grounded answer.", ["ev1"]),
        _raw("answer", "Grounded answer.", []),
        _raw("abstain", "", [], "INSUFFICIENT_EVIDENCE"),
        {"text": '{"status":"answer",', "stop_reason": "max_tokens"},
        {},
    ]
    assert legacy._m26_r3_provider_trace_installed is True
    for raw in cases:
        before = legacy._m26_r3_original_normalize_fast_provider_result(raw)
        after = legacy._normalize_fast_provider_result(raw)
        assert after == before


def test_parser_validator_and_retry_acceptance_functions_are_untouched() -> None:
    assert not hasattr(legacy, "_m26_r3_original_parse_multi_provider_json")
    assert not hasattr(legacy, "_m26_r3_original_validate_fast_provider_candidate")
    assert not hasattr(legacy, "_m26_r3_original_verify_multi_evidence_provider_output")
    assert legacy._parse_multi_provider_json.__module__ == legacy.__name__
    assert legacy._validate_fast_provider_candidate.__module__ == legacy.__name__
    assert legacy._verify_multi_evidence_provider_output.__module__ == legacy.__name__


def test_precise_reason_is_additive_and_coarse_terminal_is_preserved() -> None:
    raw = _raw("answer", "Grounded answer.", [])
    diagnostic = diagnose_fast_provider_result(raw, selected_evidence_ids=["ev1"])
    assert diagnostic["validator"]["failure_code"] == "FAST_VALIDATOR_CITATIONS_EMPTY"
    normalized = legacy._normalize_fast_provider_result(raw)
    response = {
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "safe_abstention": True,
        "reason_codes": ["PROVIDER_OUTPUT_INVALID"],
        "multi_evidence_verification": {},
    }
    traced = _attach_trace_to_response(
        response,
        provider_result=normalized,
        provider_identity={"provider": "synthetic", "model": "synthetic"},
        selected_evidence=[{"evidence_id": "ev1", "locator_id": "loc1", "source_id": "src1"}],
    )
    assert traced["reason_codes"] == ["PROVIDER_OUTPUT_INVALID"]
    trace = traced["multi_evidence_verification"]["provider_contract_trace"]
    assert trace["schema_version"] == TRACE_SCHEMA_VERSION
    assert trace["terminal"]["reason_code"] == "PROVIDER_OUTPUT_INVALID"
    assert trace["terminal"]["precise_reason_code"] == "FAST_VALIDATOR_CITATIONS_EMPTY"
    assert trace["fallback"]["blind_retry_performed"] is False
    assert trace["fallback"]["provider_attempt_count"] == 1
    assert trace["terminal"]["clean_bounded_terminal"] is True


def test_true_abstain_remains_true_abstain_shape() -> None:
    raw = _raw("abstain", "", [], "INSUFFICIENT_EVIDENCE")
    diagnostic = diagnose_fast_provider_result(raw, selected_evidence_ids=["ev1"])
    assert diagnostic["parser"]["outcome"] == "valid"
    assert diagnostic["validator"]["outcome"] == "valid_abstain"
    assert diagnostic["validator"]["failure_code"] == ""


def test_trace_never_persists_provider_text_or_secret_named_fields() -> None:
    secret = "SUPERSECRET-PROVIDER-VALUE"
    raw = {
        **_raw("answer", secret, []),
        "authorization": "Bearer SUPERSECRET-HEADER",
        "api_key": "sk-SUPERSECRET-KEY",
    }
    normalized = legacy._normalize_fast_provider_result(raw)
    traced = _attach_trace_to_response(
        {
            "status": "owner_only_safe_abstention",
            "terminal_status": "safe_abstention",
            "safe_abstention": True,
            "reason_codes": ["PROVIDER_OUTPUT_INVALID"],
            "multi_evidence_verification": {},
        },
        provider_result=normalized,
        provider_identity={"provider": "synthetic", "model": "synthetic"},
        selected_evidence=[{"evidence_id": "ev1", "locator_id": "loc1", "source_id": "src1"}],
    )
    rendered = json.dumps(
        traced["multi_evidence_verification"]["provider_contract_trace"], sort_keys=True
    )
    for forbidden in (
        secret,
        "SUPERSECRET-HEADER",
        "SUPERSECRET-KEY",
        "authorization",
        "api_key",
    ):
        assert forbidden not in rendered
