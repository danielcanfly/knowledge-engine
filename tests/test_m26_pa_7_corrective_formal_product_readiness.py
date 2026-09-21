from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import knowledge_engine.m26_aq_semantic_contract as semantic_runtime
import knowledge_engine.m26_pa7_arbitrary_query_runtime as runtime_module
from knowledge_engine.m26_pa7_arbitrary_query_runtime import LocalDenseProjectionChannel
from knowledge_engine.m26_production_promotion_closure import (
    CORRECTIVE_FORMAL_TEST_CONTRACT_SELF_SHA256,
    CORRECTIVE_OWNER_AUTHORITY_SELF_SHA256,
    CORRECTIVE_REOPEN_SELF_SHA256,
    build_corrective_formal_test_manifest,
    corrective_formal_query_specs,
    load_json,
    run_corrective_formal_product_readiness,
    validate_corrective_formal_test_manifest,
    validate_promotion_trigger,
    validate_resolved_gate,
    verify_self_digest,
)
from knowledge_engine.m26_verified_answer_citation_gate import canonical_sha256
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle
from tests.test_m26_pa_7_arbitrary_query_runtime import (
    ExactSpanProvider as CanonicalExactSpanProvider,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-7-production-promotion-closure.yml"

OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
FORMAL_MANIFEST_SELF_SHA256 = (
    "2d0fbd3a837aab9f09996ba75000bf577e14db4dc01e483cc2aba3ad8ac07396"
)
CORRECTED_GATE_SELF_SHA256 = (
    "0921a5e31971bc754b3dfc0fbc78fb17321cb6f8ee4da485f3f1b3854fe7de9a"
)
CORRECTED_TRIGGER_SELF_SHA256 = (
    "5ee5b70f7a445e2c24cf64c6ba778688fbdfb5ccd7300336e6f5d02cdae75167"
)
FORMAL_CLASSES = {
    "conflict_temporal_freshness": 1,
    "cross_document_comparison": 1,
    "direct_grounded_knowledge": 2,
    "graph_relationship_navigation": 1,
    "no_answer": 1,
    "prompt_injection_privacy": 1,
    "provenance_source_trace": 1,
}


@pytest.fixture(autouse=True)
def _full_production_answer_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    def bundle_loader(store=None):
        del store
        return synthetic_full_production_answer_bundle()

    monkeypatch.setattr(runtime_module, "load_production_answer_bundle", bundle_loader)
    monkeypatch.setattr(semantic_runtime, "load_production_answer_bundle", bundle_loader)


def _schema_errors(schema_name: str, value: dict[str, Any]) -> list[str]:
    schema = load_json(SCHEMAS / schema_name)
    Draft202012Validator.check_schema(schema)
    return [
        error.message
        for error in sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.absolute_path),
        )
    ]


def test_corrective_artifacts_validate_and_bind_authority_chain() -> None:
    owner_decision = load_json(PILOT / "m26-pa-7-owner-final-decision.json")
    owner_authority = load_json(PILOT / "m26-pa-7-corrective-owner-authority.json")
    contract = load_json(PILOT / "m26-pa-7-corrective-formal-test-contract.json")
    manifest = load_json(PILOT / "m26-pa-7-corrective-formal-test-manifest.json")
    gate = load_json(PILOT / "m26-pa-7-corrected-resolved-production-gate.json")
    trigger = load_json(PILOT / "m26-pa-7-corrected-promotion-trigger.json")

    assert (
        _schema_errors("m26-pa-7-corrective-owner-authority-v1.schema.json", owner_authority)
        == []
    )
    assert (
        _schema_errors(
            "m26-pa-7-corrective-formal-test-contract-v1.schema.json",
            contract,
        )
        == []
    )
    assert (
        _schema_errors("m26-pa-7-corrective-formal-test-manifest-v1.schema.json", manifest)
        == []
    )
    assert (
        _schema_errors("m26-pa-7-corrective-resolved-production-gate-v1.schema.json", gate)
        == []
    )
    assert (
        _schema_errors("m26-pa-7-corrective-promotion-trigger-v1.schema.json", trigger)
        == []
    )

    verify_self_digest(owner_authority, "corrective owner authority")
    verify_self_digest(contract, "corrective formal test contract")
    verify_self_digest(manifest, "corrective formal test manifest")
    verify_self_digest(gate, "corrected resolved gate")
    verify_self_digest(trigger, "corrected promotion trigger")

    assert owner_authority["self_sha256"] == CORRECTIVE_OWNER_AUTHORITY_SELF_SHA256
    assert contract["self_sha256"] == CORRECTIVE_FORMAL_TEST_CONTRACT_SELF_SHA256
    assert manifest["self_sha256"] == FORMAL_MANIFEST_SELF_SHA256
    assert gate["self_sha256"] == CORRECTED_GATE_SELF_SHA256
    assert trigger["self_sha256"] == CORRECTED_TRIGGER_SELF_SHA256
    assert gate["corrective_reopen_self_sha256"] == CORRECTIVE_REOPEN_SELF_SHA256
    assert gate["formal_test_manifest_self_sha256"] == manifest["self_sha256"]
    assert trigger["formal_test_manifest_self_sha256"] == manifest["self_sha256"]
    assert validate_corrective_formal_test_manifest(manifest)["self_sha256"] == manifest[
        "self_sha256"
    ]
    assert validate_resolved_gate(gate, owner_decision)["self_sha256"] == gate["self_sha256"]
    assert validate_promotion_trigger(trigger, gate, owner_decision)["self_sha256"] == trigger[
        "self_sha256"
    ]


def test_corrective_formal_manifest_is_eight_query_novel_hash_only_denominator() -> None:
    manifest = load_json(PILOT / "m26-pa-7-corrective-formal-test-manifest.json")
    specs = corrective_formal_query_specs()
    rows = manifest["queries"]
    query_hashes = [row["question_sha256"] for row in rows]
    pa5_packet = load_json(PILOT / "m26-pa-5-v8-owner-oversight-packet.json")
    pa5_identities = {
        str(item.get(key))
        for item in pa5_packet["items"]
        for key in ("question_id", "review_digest", "selection_digest")
    }

    assert manifest["count"] == 8
    assert manifest["classes"] == FORMAL_CLASSES
    assert Counter(row["class"] for row in rows) == Counter(FORMAL_CLASSES)
    assert [row["ordinal"] for row in rows] == list(range(1, 9))
    assert len(set(query_hashes)) == 8
    assert set(query_hashes).isdisjoint(pa5_identities)
    assert sum("question_text" in row for row in rows) == 1
    assert manifest["privacy"] == {
        "hash_only_rows": 7,
        "non_sensitive_operator_demo_rows": 1,
        "private_owner_queries_persisted": 0,
    }
    assert all(row["expected_runtime_path"].endswith("run_owner_arbitrary_query") for row in rows)
    assert any(
        spec["answerable"]
        and all(
            token not in spec["question_text"].casefold()
            for token in ("m26", "pa7", "production", "authority", "closure")
        )
        for spec in specs
    )
    rebuilt = build_corrective_formal_test_manifest(
        implementation_merge_sha=manifest["implementation_merge_sha"],
        trigger_issue=manifest["trigger_issue"],
    )
    assert rebuilt == manifest


def test_corrective_formal_fixture_receipt_satisfies_a01_to_a34_evidence(tmp_path: Path) -> None:
    owner_decision = load_json(PILOT / "m26-pa-7-owner-final-decision.json")
    manifest = load_json(PILOT / "m26-pa-7-corrective-formal-test-manifest.json")
    gate = load_json(PILOT / "m26-pa-7-corrected-resolved-production-gate.json")
    trigger = load_json(PILOT / "m26-pa-7-corrected-promotion-trigger.json")
    provider = CanonicalExactSpanProvider()

    receipt = run_corrective_formal_product_readiness(
        root=ROOT,
        gate=gate,
        owner_decision=owner_decision,
        promotion_trigger=trigger,
        formal_manifest=manifest,
        evidence_dir=tmp_path,
        provider_client=provider,
        dense_channel=LocalDenseProjectionChannel(),
        require_remote_dense=False,
        test_fixture_only=True,
    )

    assert _schema_errors("m26-pa-7-corrective-formal-receipt-v1.schema.json", receipt) == []
    verify_self_digest(receipt, "corrective formal receipt")
    assert (tmp_path / "m26-pa-7-corrective-formal-receipt.json").exists()
    assert (tmp_path / "m26-pa-7-corrective-formal-receipt.json.sha256").read_text(
        encoding="utf-8"
    ).startswith(receipt["self_sha256"])
    assert receipt["status"] == "test_fixture_only_corrective_formal_receipt"
    assert receipt["slo_pass"] is True
    assert receipt["calibration"]["query_count"] == 4
    assert receipt["calibration"]["slo_pass"] is True
    assert receipt["formal"]["query_count"] == 8
    assert receipt["metrics"]["complete_accounting"] == 8
    assert receipt["metrics"]["answerable_count"] == 6
    assert receipt["metrics"]["answerable_grounded_pass_rate"] >= 0.8
    assert receipt["metrics"]["mandatory_abstention_correctness"] == 1.0
    assert receipt["metrics"]["citation_locator_validity"] == 1.0
    assert receipt["metrics"]["material_claim_support_precision"] == 1.0
    assert receipt["metrics"]["unsupported_accepted_claims"] == 0
    assert receipt["metrics"]["provider_error_count"] == 0
    assert receipt["metrics"]["provider_calls"] <= 32
    assert Decimal(receipt["metrics"]["total_payg_equivalent_cost_usd"]) <= Decimal("0.75")
    assert provider.calls <= int(gate["budgets"]["attempt_provider_calls_maximum"])
    assert receipt["traffic"] == {
        "non_owner_denied_probes": 2,
        "non_owner_provider_calls": 0,
        "owner_requests": 8,
        "public_traffic_operations": 0,
    }
    assert all(value == 0 for value in receipt["mutations"].values())
    assert all(value is False for value in receipt["privacy"].values())

    rows = receipt["formal"]["rows"]
    assert {row["runtime_path"] for row in rows} == {
        "knowledge_engine.m26_aq_semantic_contract.run_owner_arbitrary_query"
    }
    assert all(row["safe_terminal"] for row in rows)
    assert all(row["unsupported_accepted_claims"] == 0 for row in rows)
    assert all(row["retrieval_channels"]["lexical"] for row in rows[:7])
    assert all(row["retrieval_channels"]["dense"] for row in rows[:7])
    assert any(row["retrieval_channels"]["graph"] for row in rows[:7])
    assert any(row["graph_hops_used"] > 0 for row in rows)
    assert all(row["selected_evidence_count"] > 0 for row in rows[:6])
    assert rows[2]["intent_class"] == "cross_document_comparison"
    assert rows[2]["distinct_source_count"] >= 2
    assert rows[2]["support_ref_count"] >= 2
    assert rows[2]["multi_evidence_verification"]["single_primary_passage_used"] is False
    assert rows[3]["intent_class"] == "graph_relationship"
    assert {"graph_edge", "passage"}.issubset(set(rows[3]["selected_evidence_types"]))
    assert rows[3]["support_ref_count"] >= 3
    assert rows[4]["intent_class"] == "provenance_source_trace"
    assert {"passage", "provenance"}.issubset(set(rows[4]["selected_evidence_types"]))
    assert rows[5]["intent_class"] == "temporal_conflict"
    assert "temporal_record" in rows[5]["selected_evidence_types"]
    assert rows[5]["distinct_source_count"] >= 2
    assert rows[6]["status"] == "owner_only_safe_abstention"
    assert rows[6]["provider_invoked"] is False
    assert rows[7]["status"] == "owner_only_safe_abstention"
    assert rows[7]["provider_invoked"] is False
    assert rows[7]["reason_codes"] == ["PROMPT_INJECTION_OR_PRIVACY_RISK"]
    assert sum("non_sensitive_operator_demo_payload" in row for row in rows) == 1
    assert rows[0]["non_sensitive_operator_demo_payload"]["question_text"] == (
        "What should a router define for permission-first controls?"
    )
    assert all("question_text" not in row for row in rows[1:])


def test_corrected_workflow_executes_formal_run_and_duplicate_guard_is_corrected_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "run_corrective_formal_product_readiness(" in workflow
    assert "run_owner_only_production_promotion" not in workflow
    assert "m26-pa-7-corrective-product-readiness-evidence" in workflow
    assert "m26-pa7-corrective-formal-evidence" in workflow
    assert "m26-pa-7-corrected-resolved-production-gate.json" in workflow
    assert "m26-pa-7-corrected-promotion-trigger.json" in workflow
    assert "m26-pa-7-corrective-formal-test-manifest.json" in workflow
    assert "m26_pa_7_arbitrary_owner_query_product_readiness_accepted" in workflow
    assert (
        "PA.7 acceptance already reconciled; no further promotion action authorized."
        not in workflow
    )
    assert "Corrected PA.7 acceptance already reconciled" in workflow
    assert "M26_PA7_DENSE_COLLECTION" in workflow
    assert "CLOUDFLARE_API_TOKEN" in workflow
    assert "CLOUDFLARE_AI_TOKEN" in workflow
    assert "QDRANT_API_KEY_READ" in workflow
    assert "QDRANT_READ_ONLY_API_KEY" in workflow
    assert "tests/test_m26_pa_7_corrective_formal_product_readiness.py" in workflow


def test_query_bank_hashes_match_manifest_without_fixed_answer_logic() -> None:
    runtime_source = (ROOT / "src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py").read_text(
        encoding="utf-8"
    )
    manifest = load_json(PILOT / "m26-pa-7-corrective-formal-test-manifest.json")
    specs = corrective_formal_query_specs()

    assert "What should a router define for permission-first controls?" not in runtime_source
    assert "What checksum proves the zxqv quasar asparagus ledger?" not in runtime_source
    assert [canonical_sha256(spec["question_text"]) for spec in specs] == [
        row["question_sha256"] for row in manifest["queries"]
    ]
