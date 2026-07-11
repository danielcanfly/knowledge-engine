from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from knowledge_engine.m17_ga_acceptance import (
    assess_ga_acceptance,
    build_drill_transcript,
    canonical_json,
    sha256_hex,
    validate_contract,
    verify_report,
    verify_transcript,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/ga/m17/independent-ga-contract.json"


def _transcript() -> dict:
    return build_drill_transcript(
        ROOT,
        CONTRACT,
        engine_sha="1" * 40,
        source_sha="2" * 40,
        release_id="release-test",
        manifest_sha256="3" * 64,
        pointer_sha256="4" * 64,
        operator_id="operator-independent",
    )


def _resign(transcript: dict) -> dict:
    unsigned = deepcopy(transcript)
    unsigned.pop("transcript_sha256", None)
    unsigned["transcript_sha256"] = sha256_hex(canonical_json(unsigned))
    return unsigned


def test_real_contract_and_independent_drill_are_ga_accepted() -> None:
    contract_report = validate_contract(ROOT, CONTRACT)
    assert contract_report["status"] == "passed"
    transcript = _transcript()
    assert verify_transcript(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    assert report["status"] == "ga_accepted"
    assert report["ga_accepted"] is True
    assert report["stage_count"] == 18
    assert report["capability_count"] == 20
    assert report["safe_stop_count"] == 4
    assert verify_report(report)

    tampered = deepcopy(report)
    tampered["ga_accepted"] = False
    assert not verify_report(tampered)


def test_self_evaluation_is_blocked() -> None:
    transcript = _transcript()
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id=transcript["operator_id"],
    )
    assert report["status"] == "blocked"
    assert "independence" in {item["code"] for item in report["issues"]}


def test_missing_stage_is_blocked() -> None:
    transcript = _transcript()
    transcript["stages"].pop()
    transcript["final_reconciliation"]["stage_count"] = 17
    transcript = _resign(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    codes = {item["code"] for item in report["issues"]}
    assert report["ga_accepted"] is False
    assert "stage_set" in codes


def test_real_mutation_claim_is_blocked() -> None:
    transcript = _transcript()
    transcript["mutation_dispatched"] = True
    transcript["stages"][7]["mutation_dispatched"] = True
    transcript = _resign(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    assert "mutation_claim" in {item["code"] for item in report["issues"]}


def test_undocumented_hint_source_is_blocked() -> None:
    transcript = _transcript()
    transcript["hint_sources"].append("private-notes.md")
    transcript = _resign(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    assert "undocumented_hint" in {item["code"] for item in report["issues"]}


def test_missing_capability_is_blocked() -> None:
    transcript = _transcript()
    transcript["capabilities"].pop(0)
    transcript["final_reconciliation"]["capability_count"] = 19
    transcript = _resign(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    assert "capability_set" in {item["code"] for item in report["issues"]}


def test_failed_safe_stop_and_transcript_tamper_are_blocked() -> None:
    transcript = _transcript()
    transcript["safe_stops"][0]["status"] = "continued"
    transcript = _resign(transcript)
    report = assess_ga_acceptance(
        ROOT,
        CONTRACT,
        transcript,
        evaluator_id="evaluator-independent",
    )
    assert "safe_stop_status" in {item["code"] for item in report["issues"]}

    tampered = deepcopy(_transcript())
    tampered["operator_context"] = "chat_history"
    assert not verify_transcript(tampered)
