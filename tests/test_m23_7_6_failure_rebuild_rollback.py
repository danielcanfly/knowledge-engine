from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m23_7_6_failure_rebuild_rollback import (
    EXPECTED_BLOCKERS,
    FAILURE_CLASSES,
    build_m23_7_6_report,
    canonical_m23_7_6_payload,
    canonical_rebuild_descriptor,
    validate_m23_7_6_payload,
)


def _payload() -> dict:
    return copy.deepcopy(canonical_m23_7_6_payload())


def test_canonical_failure_rebuild_rollback_report_passes():
    payload = _payload()
    report = build_m23_7_6_report(payload)

    assert report["status"] == "pass"
    assert report["fault_scenario_count"] == 10
    assert report["failure_classes"] == list(FAILURE_CLASSES)
    assert report["rebuild_byte_identical"] is True
    assert report["lexical_rollback_passed"] is True
    assert report["candidate_dependency_required_for_rollback"] is False
    assert report["carry_forward_blockers"] == list(EXPECTED_BLOCKERS)
    assert report["promotion_eligibility_granted"] is False
    assert report["production_authority"] is False
    assert report["protected_mutations_dispatched"] is False
    assert len(report["m23_7_6_sha256"]) == 64


def test_canonical_report_is_byte_stable():
    first = build_m23_7_6_report(_payload())
    second = build_m23_7_6_report(_payload())
    assert first == second


def test_rebuild_descriptor_pins_frozen_pilot_identity():
    descriptor = canonical_rebuild_descriptor()
    assert descriptor["collection"] == {
        "name": "llm_wiki_m23_pilot_bge_m3_1024",
        "points": 107,
        "vector_name": "default",
        "vector_dimension": 1024,
        "distance": "Cosine",
        "point_id_strategy": "uuid5(section_id,embedding_model)",
        "payload_schema_version": "knowledge-engine-m23-qdrant-payload/v1",
        "source_membership": "evaluation-only-pending-proposal",
    }
    assert descriptor["authority"]["canonical_knowledge"] is False
    assert descriptor["authority"]["candidate_release_eligible"] is False
    assert descriptor["authority"]["production_authority"] is False
    assert all(value is False for value in descriptor["execution"].values())


@pytest.mark.parametrize("index", range(10))
def test_each_fault_preserves_lexical_authority(index: int):
    payload = _payload()
    scenario = payload["failure_scenarios"][index]
    assert scenario["expected_failure_class"] == FAILURE_CLASSES[index]
    assert scenario["observed_failure_class"] == FAILURE_CLASSES[index]
    assert scenario["lexical_before_ids"] == scenario["lexical_after_ids"]
    assert scenario["candidate_result_ids"] == []
    assert scenario["lexical_primary_continued"] is True
    assert scenario["candidate_output_discarded"] is True
    assert scenario["output_influenced"] is False
    assert scenario["rollback"] == {
        "mode": "lexical-only",
        "immediate": True,
        "candidate_dependency_required": False,
        "completed": True,
    }


def test_rejects_incomplete_fault_matrix():
    payload = _payload()
    payload["failure_scenarios"].pop()
    with pytest.raises(IntegrityError, match="fault matrix is incomplete"):
        validate_m23_7_6_payload(payload)


def test_rejects_failure_class_drift():
    payload = _payload()
    payload["failure_scenarios"][0]["observed_failure_class"] = "qdrant-timeout"
    with pytest.raises(IntegrityError, match="failure classification drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_lexical_output_drift():
    payload = _payload()
    payload["failure_scenarios"][1]["lexical_after_ids"] = ["drifted"]
    with pytest.raises(IntegrityError, match="lexical output drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_candidate_output_survival():
    payload = _payload()
    payload["failure_scenarios"][2]["candidate_result_ids"] = ["candidate#leak"]
    with pytest.raises(IntegrityError, match="candidate output survived"):
        validate_m23_7_6_payload(payload)


def test_rejects_raw_exception_persistence():
    payload = _payload()
    payload["failure_scenarios"][3]["raw_exception_persisted"] = True
    with pytest.raises(IntegrityError, match="raw_exception_persisted"):
        validate_m23_7_6_payload(payload)


def test_rejects_scenario_rollback_dependency():
    payload = _payload()
    payload["failure_scenarios"][4]["rollback"][
        "candidate_dependency_required"
    ] = True
    with pytest.raises(IntegrityError, match="scenario rollback drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_rebuild_digest_drift():
    payload = _payload()
    payload["rebuild"]["second_calculation_sha256"] = "0" * 64
    with pytest.raises(IntegrityError, match="second rebuild digest drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_external_rebuild_write():
    payload = _payload()
    payload["rebuild"]["external_write_performed"] = True
    with pytest.raises(IntegrityError, match="external rebuild write"):
        validate_m23_7_6_payload(payload)


def test_rejects_blocker_removal():
    payload = _payload()
    payload["carry_forward_blockers"] = ["blocked_pending_latency"]
    with pytest.raises(IntegrityError, match="carry-forward blockers drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_source_pr_merge():
    payload = _payload()
    payload["entry"]["source_pr_19"]["merged"] = True
    with pytest.raises(IntegrityError, match="entry identity drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_premature_m23_7_7_entry():
    payload = _payload()
    payload["phase_gate"]["m23_7_7_may_begin"] = True
    with pytest.raises(IntegrityError, match="phase gate drifted"):
        validate_m23_7_6_payload(payload)


def test_rejects_protected_mutation():
    payload = _payload()
    payload["protected_mutations"]["qdrant_write"] = True
    with pytest.raises(IntegrityError, match="protected mutation dispatched"):
        validate_m23_7_6_payload(payload)
