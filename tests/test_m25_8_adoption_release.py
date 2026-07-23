from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knowledge_engine.errors import AuthorizationError, IntegrityError
from knowledge_engine.m25_adoption_release import (
    BLOCKED_STATUS,
    LIVE_COMPLETE_STATUS,
    TEST_COMPLETE_STATUS,
    build_adoption_receipt,
    evaluate_readiness,
    sign,
    validate_adoption_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot/m25"


def _load(name: str) -> dict:
    return json.loads((PILOT / name).read_text(encoding="utf-8"))


def test_actual_benchmark_closure_is_blocked_from_m25_8() -> None:
    closure = _load("m25-7-benchmark-closure.json")
    gate = evaluate_readiness(closure)
    assert gate == _load("m25-8-readiness-gate.json")
    assert gate["status"] == BLOCKED_STATUS
    assert gate["source_pr_merge_permitted"] is False
    assert gate["candidate_release_build_permitted"] is False
    assert gate["benchmark_fixtures_reusable_as_live_source"] is False


def test_synthetic_candidate_adoption_is_deterministic_and_non_production() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    receipt = build_adoption_receipt(evidence)
    assert receipt == _load("m25-8-adoption-receipt.synthetic.json")
    assert receipt["status"] == TEST_COMPLETE_STATUS
    assert receipt["surface_count"] == 5
    assert receipt["surfaces"] == ["graph", "search", "sources", "vault", "wiki"]
    assert receipt["rollback_passed"] is True
    assert receipt["production_pointer_unchanged"] is True
    assert receipt["production_mutation_permitted"] is False
    assert receipt["m25_9_authorized"] is False


def test_live_mode_requires_non_synthetic_knowledge_owner() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["mode"] = "live"
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(AuthorizationError, match="synthetic actor"):
        validate_adoption_evidence(evidence)


def test_exact_head_authority_is_mandatory() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    authority = copy.deepcopy(evidence["authority"])
    authority["exact_source_pr_head_sha"] = "9" * 40
    evidence["authority"] = sign(authority, "authority_sha256")
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(AuthorizationError, match="stale or over-broad"):
        validate_adoption_evidence(evidence)


def test_source_pr_must_be_ready_and_ci_green() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["source_pr"]["ci_conclusion"] = "failure"
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="not merge-ready"):
        validate_adoption_evidence(evidence)


def test_all_five_surfaces_are_required() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["surfaces"] = evidence["surfaces"][:-1]
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="exactly five"):
        validate_adoption_evidence(evidence)


def test_surface_release_identity_must_match_candidate() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["surfaces"][0]["release_id"] = "candidate-drift"
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="surface regression mismatch"):
        validate_adoption_evidence(evidence)


def test_rollback_must_preserve_production_pointer() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["rollback"]["production_pointer_after_sha256"] = "8" * 64
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(IntegrityError, match="rollback proof mismatch"):
        validate_adoption_evidence(evidence)


def test_production_mutation_flags_fail_closed() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["boundary"]["production_pointer_mutation"] = True
    evidence = sign(evidence, "evidence_sha256")
    with pytest.raises(AuthorizationError, match="boundary drift"):
        validate_adoption_evidence(evidence)


def test_live_complete_status_is_distinct_from_test_only() -> None:
    evidence = _load("m25-8-adoption-evidence.synthetic.json")
    evidence["mode"] = "live"
    evidence["authority"]["actor"] = "huaihsuanbusiness"
    evidence["authority"] = sign(evidence["authority"], "authority_sha256")
    evidence = sign(evidence, "evidence_sha256")
    receipt = build_adoption_receipt(evidence)
    assert receipt["status"] == LIVE_COMPLETE_STATUS
    assert receipt["status"] != TEST_COMPLETE_STATUS
