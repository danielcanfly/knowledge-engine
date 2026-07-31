from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

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

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
WORKFLOW = ROOT / ".github" / "workflows" / "m26-pa-7-production-promotion-closure.yml"

OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
FORMAL_MANIFEST_SELF_SHA256 = (
    "b9474b5274f598670aa8f4146e2aacb82a8a408f3baf79a78a4c78df843572d7"
)
CORRECTED_GATE_SELF_SHA256 = (
    "993e33be92109f7e7d798dec0a2e710ad00b2cdac2d3c6e574956ebde81aa08d"
)
CORRECTED_TRIGGER_SELF_SHA256 = (
    "5ef19c74e8c59b88a61002ddee119e731021075871908efd3e11be049efb5bf4"
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


class ExactSpanProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        task = _task(payload)
        passage = task["passage"]["text"]
        locator_id = task["passage"]["locator_id"]
        claim = _first_sentence(passage)
        return {
            "call_class": call_class,
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": f"formal-fixture-{self.calls}",
            "text": json.dumps(
                {
                    "answer_text": "",
                    "claims": [
                        {
                            "citation": {"locator_id": locator_id},
                            "claim_id": "claim_1",
                            "claim_text": claim,
                        }
                    ],
                    "reason_codes": [],
                    "status": "draft_candidate",
                }
            ),
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }


def _task(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload["messages"][0]["content"]
    text = message[0]["text"] if isinstance(message, list) else message
    return json.loads(text)


def _first_sentence(passage: str) -> str:
    for delimiter in (". ", "\n"):
        if delimiter in passage:
            return passage.split(delimiter, 1)[0].strip() + delimiter.strip()
    return passage[:160].strip()


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
    provider = ExactSpanProvider()

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
    assert receipt["metrics"]["answerable_grounded_pass_rate"] == 1.0
    assert receipt["metrics"]["mandatory_abstention_correctness"] == 1.0
    assert receipt["metrics"]["citation_locator_validity"] == 1.0
    assert receipt["metrics"]["material_claim_support_precision"] == 1.0
    assert receipt["metrics"]["unsupported_accepted_claims"] == 0
    assert receipt["metrics"]["provider_error_count"] == 0
    assert receipt["metrics"]["provider_calls"] <= 32
    assert Decimal(receipt["metrics"]["total_payg_equivalent_cost_usd"]) <= Decimal("0.75")
    assert provider.calls == 10
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
        "knowledge_engine.m26_pa7_arbitrary_query_runtime.run_owner_arbitrary_query"
    }
    assert all(row["safe_terminal"] for row in rows)
    assert all(row["unsupported_accepted_claims"] == 0 for row in rows)
    assert all(row["retrieval_channels"]["lexical"] for row in rows[:7])
    assert all(row["retrieval_channels"]["dense"] for row in rows[:7])
    assert any(row["retrieval_channels"]["parent_expansion"] for row in rows[:7])
    assert any(row["graph_hops_used"] > 0 for row in rows)
    assert all(row["selected_evidence_count"] > 0 for row in rows[:6])
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
