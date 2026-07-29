from __future__ import annotations

import copy
from pathlib import Path

import pytest

from knowledge_engine.m26_pa5_v8_runtime import (
    PA5V8Error,
    POPULATION_SHA256,
    STRATA,
    compile_grounding_plans,
    deterministic_calibration_sample,
    manifest,
    non_live_full_population_gate,
    provider_selection_contract,
    render_and_verify_selection,
)

ROOT = Path(__file__).resolve().parents[1]


def _plans():
    return compile_grounding_plans(ROOT)


def _selection(plan):
    return {
        "status": "select",
        "selected_span_ids": [e["span_id"] for e in plan["candidate_evidence"]],
        "selected_evidence_ids": [e["evidence_id"] for e in plan["candidate_evidence"]],
        "relation": "contrasts_with" if plan["stratum"] == "cross_document_comparison" else None,
        "abstention_reason": None,
    }


def test_full_population_compiles_and_reuses_pa4_kernel() -> None:
    result = non_live_full_population_gate(ROOT)
    assert result["status"] == "m26_pa_5_v8_non_live_full_population_gate_passed"
    assert result["population_count"] == 200
    assert result["population_sha256"] == POPULATION_SHA256
    assert result["pa4_kernel_reused"] is True
    assert result["provider_calls"] == 0
    assert result["raw_evidence_persisted"] is False


def test_every_answerable_plan_has_evidence_and_every_abstention_has_policy() -> None:
    plans = _plans()
    assert len(plans) == 200
    assert {plan["stratum"] for plan in plans} == set(STRATA)
    for plan in plans:
        if plan["abstention_policy"]:
            assert not plan["candidate_evidence"]
        else:
            assert plan["candidate_evidence"]
            for evidence in plan["candidate_evidence"]:
                assert evidence["span_id"].startswith("span_")
                assert evidence["span_text"]
                assert evidence["locator"]["locator_id"].startswith("loc_")


def test_manifest_persists_no_raw_evidence() -> None:
    value = manifest(_plans())
    assert value["population_count"] == 200
    assert value["raw_evidence_persisted"] is False
    assert "span_text" not in str(value)


def test_calibration_sample_is_fixed_stratified_and_deterministic() -> None:
    plans = _plans()
    first = deterministic_calibration_sample(plans)
    assert first == deterministic_calibration_sample(plans)
    assert first["count"] == 35
    by_id = {plan["question_id"]: plan for plan in plans}
    counts = {stratum: 0 for stratum in STRATA}
    for question_id in first["question_ids"]:
        counts[by_id[question_id]["stratum"]] += 1
    assert set(counts.values()) == {5}


def test_model_contract_has_no_authoritative_citation_fields() -> None:
    plan = next(p for p in _plans() if not p["abstention_policy"])
    contract = provider_selection_contract(plan)
    assert "locator_id" not in contract["required_keys"]
    assert "claim_text" not in contract["required_keys"]
    assert "locator_id" in contract["authoritative_fields_forbidden"]
    assert "claim_text" in contract["authoritative_fields_forbidden"]


def test_golden_runtime_selection_passes_pa4_verifier_for_200_of_200() -> None:
    for plan in _plans():
        if plan["abstention_policy"]:
            result = render_and_verify_selection(
                plan,
                {
                    "status": "abstain",
                    "selected_span_ids": [],
                    "selected_evidence_ids": [],
                    "relation": None,
                    "abstention_reason": plan["abstention_policy"],
                },
            )
            assert result["terminal_status"] == "safe_abstention"
        else:
            result = render_and_verify_selection(plan, _selection(plan))
            assert result["terminal_status"] == "verified_answer_ready_candidate"
            assert result["runtime_owned_citations"] is True


def test_mutated_span_id_fails_closed() -> None:
    plan = next(p for p in _plans() if not p["abstention_policy"])
    selection = _selection(plan)
    selection["selected_span_ids"] = ["span_mutated"]
    selection["selected_evidence_ids"] = []
    with pytest.raises(PA5V8Error, match="span ID"):
        render_and_verify_selection(plan, selection)


def test_model_authored_locator_fails_closed() -> None:
    plan = next(p for p in _plans() if not p["abstention_policy"])
    selection = _selection(plan)
    selection["locator_id"] = "spoofed"
    with pytest.raises(PA5V8Error, match="authoritative citation"):
        render_and_verify_selection(plan, selection)


def test_mutated_locator_fails_closed_before_pa4_kernel() -> None:
    plan = next(p for p in _plans() if not p["abstention_policy"])
    mutated = copy.deepcopy(plan)
    mutated["candidate_evidence"][0]["locator"]["locator_id"] = "loc_mutated"
    with pytest.raises(PA5V8Error, match="locator ID mismatch"):
        render_and_verify_selection(mutated, _selection(mutated))


def test_missing_evidence_fails_before_live_execution() -> None:
    plan = next(p for p in _plans() if not p["abstention_policy"])
    broken = copy.deepcopy(plan)
    broken["candidate_evidence"] = []
    with pytest.raises(PA5V8Error, match="has no evidence"):
        render_and_verify_selection(
            broken,
            {
                "status": "select",
                "selected_span_ids": [],
                "selected_evidence_ids": [],
                "relation": None,
                "abstention_reason": None,
            },
        )


def test_all_seven_strata_have_positive_and_negative_contract_coverage() -> None:
    for stratum in STRATA:
        plan = next(p for p in _plans() if p["stratum"] == stratum)
        if plan["abstention_policy"]:
            with pytest.raises(PA5V8Error, match="mandatory abstention"):
                render_and_verify_selection(
                    plan,
                    {
                        "status": "select",
                        "selected_span_ids": [],
                        "selected_evidence_ids": [],
                        "relation": None,
                        "abstention_reason": None,
                    },
                )
        else:
            selection = _selection(plan)
            selection["selected_span_ids"] = ["span_not_runtime_provided"]
            selection["selected_evidence_ids"] = []
            with pytest.raises(PA5V8Error):
                render_and_verify_selection(plan, selection)
