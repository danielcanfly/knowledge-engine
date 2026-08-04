from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

RECOVERY_KEY = "universal_answerability_recovery"
EXPECTED_ENTRYPOINT = (
    "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
)


@pytest.fixture(autouse=True)
def restore_ask_api_runtime_binding() -> Any:
    import knowledge_engine.m26_ask_api as ask_api

    original_run_owner_arbitrary_query = ask_api.run_owner_arbitrary_query
    original_runtime_entrypoint = ask_api.RUNTIME_ENTRYPOINT
    yield
    ask_api.run_owner_arbitrary_query = original_run_owner_arbitrary_query
    ask_api.RUNTIME_ENTRYPOINT = original_runtime_entrypoint


def _headers() -> dict[str, str]:
    return {
        "authorization": "Bearer local-test-token",
        "x-m26-owner-subject-hash": "local-owner-hash",
    }


def _base_runtime_response(
    *,
    status: str,
    terminal_status: str,
    answer_source: str,
    answer_text: str,
    safe_abstention: bool,
    telemetry: Mapping[str, Any],
) -> dict[str, Any]:
    citations = [] if safe_abstention else [
        {
            "citation_id": "c1",
            "claim_id": "claim_1",
            "claim_role": "direct",
            "evidence_id": "ev1",
            "evidence_type": "passage",
            "locator_id": "loc-ev1",
            "source_id": "source-a",
            "source_identity": "source-a",
            "section_id": "section-a",
            "concept_id": "concept-a",
            "release_id": "release-test",
            "source_locator": "source-a#section-a",
            "source_artifact_sha256": "a" * 64,
            "support_text_sha256": "b" * 64,
            "exact_quote_sha256": "c" * 64,
            "provenance_record_sha256": "d" * 64,
            "runtime_owned_locator": True,
        }
    ]
    claims = [] if safe_abstention else [
        {
            "claim_id": "claim_1",
            "claim_role": "direct",
            "surface_text": answer_text,
            "facet_ids": ["direct_answer"],
        }
    ]
    return {
        "schema_version": "knowledge-engine-m26-pa7-arbitrary-query-result/v1",
        "status": status,
        "terminal_status": terminal_status,
        "trace_id": "trace-route-test",
        "question_sha256": "q" * 64,
        "answer_text": answer_text,
        "safe_abstention": safe_abstention,
        "reason_codes": [],
        "answer_source": answer_source,
        "citations": citations,
        "answer_claims": claims,
        "relationship_summary": {"intent_class": "direct_grounded_knowledge"},
        "multi_evidence_verification": {RECOVERY_KEY: dict(telemetry)},
        "semantic_closure": {RECOVERY_KEY: dict(telemetry)},
        "selected_evidence": [],
        "evidence_utilization_trace": {
            "selected_evidence_count": 1,
            "used_evidence_count": 0 if safe_abstention else 1,
        },
        "graph_observability": {},
        "retrieval_mode_summary": {},
        "retrieval_backend_identity": {},
        "candidate_count_by_channel": {},
        "selected_evidence_count": 1,
        "distinct_source_count": 1,
        "distinct_source_identities": ["source-a"],
        "provider_invoked": True,
        "provider_call_count": 2,
        "payg_equivalent_cost_usd": "0.00",
        "latency_ms": 1,
        "unsupported_accepted_claims": 0,
        "material_claim_support_verified": True,
        "citation_locator_valid": True,
        "privacy": {},
        "mutations": {
            "canonical_writes": 0,
            "production_pointer_mutations": 0,
            "qdrant_write_operations": 0,
        },
    }


def test_production_import_uses_canonical_runtime_without_final_patch_binding() -> None:
    import knowledge_engine.m26_aq_final_universal_recovery_patch as final_patch
    import knowledge_engine.m26_aq_semantic_runtime_patch_v3 as v3_patch
    import knowledge_engine.m26_ask_api as ask_api
    import knowledge_engine.m26_pa7_arbitrary_query_runtime as legacy
    import knowledge_engine.m26_pa7_semantic_closure_runtime as semantic_runtime
    import knowledge_engine.m26_production_api  # noqa: F401

    assert ask_api.RUNTIME_ENTRYPOINT == EXPECTED_ENTRYPOINT
    assert ask_api.run_owner_arbitrary_query is semantic_runtime.run_owner_arbitrary_query
    assert not getattr(legacy._intent_class, final_patch._FINAL_MARKER, False)
    assert not getattr(legacy._direct_question_facets, final_patch._FINAL_MARKER, False)
    assert not getattr(v3_patch._generalized_provider_synthesize, final_patch._FINAL_MARKER, False)


def test_production_query_route_surfaces_recovery_telemetry(monkeypatch: Any) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "local-test-token")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "local-owner-hash")
    import knowledge_engine.m26_ask_api as ask_api
    import knowledge_engine.m26_production_api as production_api

    telemetry = {
        "schema_version": "m26-aq-final-universal-recovery-telemetry/v1",
        "case_specific": False,
        "universal_recovery_attempted": True,
        "universal_recovery_should_attempt": True,
        "universal_recovery_trigger_codes": ["SEMANTIC_CLOSURE_FAILED"],
        "universal_recovery_hard_stop_codes": [],
        "recovery_input_evidence_count": 10,
        "recovery_items_count": 8,
        "recovery_text_available_count": 8,
        "candidate_built": True,
        "candidate_claim_count": 1,
        "candidate_verify_result": "verified",
        "candidate_verify_failure_codes": [],
        "candidate_missing_facets": [],
        "candidate_exception_class": "",
        "first_broken_stage": "none",
        "published_verified_answer": True,
    }

    def fake_run_owner_arbitrary_query(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["root"] == Path(".").resolve()
        return _base_runtime_response(
            status="owner_only_cited_answer",
            terminal_status="verified_answer",
            answer_source="deterministic_verified_evidence_recovery",
            answer_text="The cited evidence supports the answer.",
            safe_abstention=False,
            telemetry=telemetry,
        )

    monkeypatch.setattr(ask_api, "run_owner_arbitrary_query", fake_run_owner_arbitrary_query)
    client = TestClient(production_api.app)
    response = client.post(
        "/api/m26/query",
        headers=_headers(),
        json={"question": "Why does demand not prove a viable business?"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_source"] == "deterministic_verified_evidence_recovery"
    assert payload["integrity"]["unsupported_accepted_claims"] == 0
    assert payload["multi_evidence_verification"][RECOVERY_KEY]["candidate_built"] is True
    assert payload["semantic_closure"][RECOVERY_KEY]["published_verified_answer"] is True


def test_production_query_route_keeps_ood_recovery_hard_stop(monkeypatch: Any) -> None:
    monkeypatch.setenv("M26_QUERY_BACKEND_TOKEN", "local-test-token")
    monkeypatch.setenv("KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH", "local-owner-hash")
    import knowledge_engine.m26_ask_api as ask_api
    import knowledge_engine.m26_production_api as production_api

    telemetry = {
        "schema_version": "m26-aq-final-universal-recovery-telemetry/v1",
        "case_specific": False,
        "universal_recovery_attempted": False,
        "universal_recovery_should_attempt": False,
        "universal_recovery_trigger_codes": ["LOW_RETRIEVAL_SUPPORT"],
        "universal_recovery_hard_stop_codes": ["LOW_RETRIEVAL_SUPPORT"],
        "recovery_input_evidence_count": 0,
        "recovery_items_count": 0,
        "recovery_text_available_count": 0,
        "candidate_built": False,
        "candidate_claim_count": 0,
        "candidate_verify_result": "not_attempted",
        "candidate_verify_failure_codes": [],
        "candidate_missing_facets": [],
        "candidate_exception_class": "",
        "first_broken_stage": "not_recoverable",
        "published_verified_answer": False,
    }

    def fake_run_owner_arbitrary_query(**_kwargs: Any) -> dict[str, Any]:
        return _base_runtime_response(
            status="owner_only_safe_abstention",
            terminal_status="safe_abstention",
            answer_source="safe_abstention",
            answer_text="I cannot answer from the authorized knowledge base.",
            safe_abstention=True,
            telemetry=telemetry,
        )

    monkeypatch.setattr(ask_api, "run_owner_arbitrary_query", fake_run_owner_arbitrary_query)
    client = TestClient(production_api.app)
    response = client.post(
        "/api/m26/query",
        headers=_headers(),
        json={"question": "Give Toyota 2025 audited quarterly revenue."},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["safe_abstention"] is True
    assert payload["citations"] == []
    assert payload["answer_source"] == "safe_abstention"
    assert payload["semantic_closure"][RECOVERY_KEY]["universal_recovery_hard_stop_codes"]
