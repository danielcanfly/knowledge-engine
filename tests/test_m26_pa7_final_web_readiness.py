from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowledge_engine.m26_pa7_arbitrary_query_runtime import LocalDenseProjectionChannel
from knowledge_engine.m26_pa7_final_web_readiness import (
    ASK_URL,
    CANONICAL_RUNTIME_PATH,
    FINAL_ACCEPTED_STATUS,
    FINAL_CLASSES,
    FINAL_WEB_FORMAL_MANIFEST_SCHEMA,
    FINAL_WEB_READINESS_RECEIPT_SCHEMA,
    build_final_web_formal_test_manifest,
    duplicate_live_guard_status,
    final_formal_query_specs,
    run_final_web_product_readiness,
    validate_final_web_formal_test_manifest,
)
from knowledge_engine.m26_production_promotion_closure import (
    load_json,
    verify_self_digest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
FINAL_MANIFEST_SELF_SHA256 = (
    "fbedacb25b7bc9a28833d58658e6425637d990b064ea67a31451f94e7f36e91e"
)


class ExactSpanProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cost = Decimal("0")

    def call(self, payload: dict[str, Any], call_class: str) -> dict[str, Any]:
        self.calls += 1
        self.cost += Decimal("0.00001")
        task = _task(payload)
        return {
            "call_class": call_class,
            "cost_usd": "0.00001",
            "latency_ms": 5,
            "response_id": f"final-web-fixture-{self.calls}",
            "text": json.dumps(_multi_evidence_answer(task)),
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


def _multi_evidence_answer(task: dict[str, Any]) -> dict[str, Any]:
    evidence = task["evidence_bundle"]
    intent = task["intent_class"]
    relation = None
    refs: list[dict[str, str]] = []
    role = "direct"
    if intent in {"cross_document_comparison", "complementary_synthesis"}:
        role = "relationship"
        relation = "contrasts_with" if intent == "cross_document_comparison" else "complements"
        refs = [_support_ref(item) for item in _passage_items(evidence)[:2]]
    elif intent == "graph_relationship":
        role = "relationship"
        relation = "depends_on"
        graph_edge = [item for item in evidence if item["evidence_type"] == "graph_edge"][0]
        refs = [
            _support_ref(graph_edge),
            *[_support_ref(item) for item in _passage_items(evidence)[:2]],
        ]
    elif intent == "provenance_source_trace":
        role = "provenance"
        refs = [_support_ref(_passage_items(evidence)[0])]
        refs.append(
            _support_ref([item for item in evidence if item["evidence_type"] == "provenance"][0])
        )
    elif intent == "temporal_conflict":
        role = "temporal"
        relation = "precedes"
        refs = [
            _support_ref(item)
            for item in evidence
            if item["evidence_type"] == "temporal_record"
        ][:2]
    else:
        refs = [_support_ref(_passage_items(evidence)[0])]
    return {
        "status": "answer_candidate",
        "relation": relation,
        "selected_evidence_ids": [item["evidence_id"] for item in evidence],
        "claims": [{"claim_id": "claim_1", "claim_role": role, "support_refs": refs}],
        "abstention_reason": None,
    }


def _passage_items(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in evidence if item["evidence_type"] == "passage"]


def _support_ref(item: dict[str, Any]) -> dict[str, str]:
    return {
        "evidence_id": item["evidence_id"],
        "locator_id": item["locator_id"],
        "exact_quote": _first_sentence(item["text"]),
    }


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


def _browser_evidence() -> dict[str, Any]:
    base_response = {
        "runtime_entrypoint": CANONICAL_RUNTIME_PATH,
        "status": "owner_only_cited_answer",
        "citation_count": 2,
        "source_count": 2,
    }
    return {
        "schema_version": "knowledge-engine-m26-pa7-final-browser-evidence/v1",
        "owner_authenticated": True,
        "navigation": {
            "ask_nav_visible": True,
            "ask_page_loaded": True,
            "textarea_usable": True,
            "submit_usable": True,
        },
        "api": {
            "query_path": "/api/m26/query",
            "health_path": "/api/m26/health",
            "server_owner_identity_verified": True,
            "non_owner_denied_before_provider": True,
            "browser_secret_delivery": False,
            "web_cli_runtime_build_sha_match": True,
        },
        "deployment": {
            "ask_url": ASK_URL,
            "api_query_path": "/api/m26/query",
            "api_health_path": "/api/m26/health",
            "auth_policy_readback_match": True,
            "backend_service_identity": {
                "service": "oracle-knowledge-engine",
                "entrypoint": "knowledge_engine.api:app",
            },
            "pages_project": "llm-wiki-m24-internal",
            "protected_hostname": "m24-internal.danielcanfly.com",
            "route_readback_match": True,
        },
        "rollback": {
            "target_verified": True,
            "procedure": "pages_previous_deployment_plus_oracle_sha",
        },
        "screenshots": [
            {
                "path": "screens/m26-direct.png",
                "sanitized": True,
                "sha256": "a" * 64,
            }
        ],
        "responses": {
            "direct": {**base_response, "trace_id": "m26pa7aq_browser_direct"},
            "cross_document": {
                **base_response,
                "distinct_source_count": 2,
                "trace_id": "m26pa7aq_browser_cross_document",
            },
            "graph": {
                **base_response,
                "graph_edge_selected": True,
                "trace_id": "m26pa7aq_browser_graph",
            },
            "abstention": {
                "runtime_entrypoint": CANONICAL_RUNTIME_PATH,
                "safe_abstention": True,
                "terminal_status": "safe_abstention",
                "trace_id": "m26pa7aq_browser_abstention",
            },
        },
        "accounting": {
            "non_owner_denied_probe_count": 1,
            "owner_query_count": 4,
            "p95_latency_ms": 200,
            "payg_equivalent_cost_usd": "0.00004",
            "provider_call_count": 4,
            "provider_error_count": 0,
        },
    }


def test_final_web_formal_manifest_is_frozen_ten_row_denominator() -> None:
    manifest = load_json(PILOT / "m26-pa-7-final-web-formal-test-manifest.json")
    specs = final_formal_query_specs()

    assert (
        _schema_errors("m26-pa-7-final-web-formal-test-manifest-v1.schema.json", manifest)
        == []
    )
    verify_self_digest(manifest, "final web formal manifest")
    assert validate_final_web_formal_test_manifest(manifest)["self_sha256"] == (
        FINAL_MANIFEST_SELF_SHA256
    )
    assert manifest["self_sha256"] == FINAL_MANIFEST_SELF_SHA256
    assert manifest["schema_version"] == FINAL_WEB_FORMAL_MANIFEST_SCHEMA
    assert manifest["classes"] == FINAL_CLASSES
    assert manifest["count"] == 10
    assert [row["ordinal"] for row in manifest["queries"]] == list(range(1, 11))
    assert [row["question_sha256"] for row in manifest["queries"]] == [
        spec["question_sha256"] for spec in specs
    ]
    assert sum(row["browser_suite"] for row in manifest["queries"]) == 1
    assert sum("question_text" in row for row in manifest["queries"]) == 1
    assert manifest["single_evidence_impossibility_required"] is True


def test_final_web_formal_manifest_rebuild_matches_committed_artifact() -> None:
    manifest = load_json(PILOT / "m26-pa-7-final-web-formal-test-manifest.json")
    rebuilt = build_final_web_formal_test_manifest(
        implementation_merge_sha=manifest["implementation_merge_sha"],
        ui_api_merge_sha=manifest["ui_api_merge_sha"],
        deployment_issue=manifest["deployment_issue"],
    )

    assert rebuilt == manifest


def test_final_web_product_readiness_fixture_receipt_satisfies_a26_to_a53(
    tmp_path: Path,
) -> None:
    provider = ExactSpanProvider()
    receipt = run_final_web_product_readiness(
        root=ROOT,
        gate=load_json(PILOT / "m26-pa-7-corrected-resolved-production-gate.json"),
        owner_decision=load_json(PILOT / "m26-pa-7-owner-final-decision.json"),
        promotion_trigger=load_json(PILOT / "m26-pa-7-corrected-promotion-trigger.json"),
        formal_manifest=load_json(PILOT / "m26-pa-7-final-web-formal-test-manifest.json"),
        evidence_dir=tmp_path,
        browser_evidence=_browser_evidence(),
        provider_client=provider,
        dense_channel=LocalDenseProjectionChannel(),
        require_remote_dense=False,
        test_fixture_only=True,
    )

    assert (
        _schema_errors("m26-pa-7-final-web-product-readiness-receipt-v1.schema.json", receipt)
        == []
    )
    verify_self_digest(receipt, "final web readiness receipt")
    assert receipt["schema_version"] == FINAL_WEB_READINESS_RECEIPT_SCHEMA
    assert receipt["status"] == "test_fixture_only_final_web_readiness_receipt"
    assert receipt["slo_pass"] is True
    assert receipt["formal"]["query_count"] == 10
    assert receipt["metrics"]["complete_accounting"] == 10
    assert receipt["metrics"]["cross_document_pass_rate"] == 1.0
    assert receipt["metrics"]["complementary_synthesis_pass_rate"] == 1.0
    assert receipt["metrics"]["graph_relationship_pass_rate"] == 1.0
    assert receipt["metrics"]["provenance_pass_rate"] == 1.0
    assert receipt["metrics"]["temporal_conflict_correctness"] == 1.0
    assert receipt["metrics"]["no_answer_correctness"] == 1.0
    assert receipt["metrics"]["prompt_injection_privacy_correctness"] == 1.0
    assert receipt["metrics"]["provider_error_count"] == 0
    assert receipt["metrics"]["safe_terminal_outcome_rate"] == 1.0
    assert receipt["traffic"]["public_traffic_operations"] == 0
    assert receipt["traffic"]["non_owner_provider_calls"] == 0
    assert all(value == 0 for value in receipt["mutations"].values())
    assert all(value is False for value in receipt["privacy"].values())
    assert receipt["canonical_runtime"]["entrypoint"] == CANONICAL_RUNTIME_PATH
    assert receipt["deployment"]["route_readback_match"] is True
    assert receipt["deployment"]["auth_policy_readback_match"] is True
    assert receipt["deployment"]["rollback_target_verified"] is True
    assert receipt["final_acceptance_status_on_success"] == FINAL_ACCEPTED_STATUS

    rows = receipt["formal"]["rows"]
    assert all(row["pass"] for row in rows)
    row3_proof = rows[2]["single_evidence_impossibility_proof"]
    row4_proof = rows[3]["single_evidence_impossibility_proof"]
    row5_proof = rows[4]["single_evidence_impossibility_proof"]
    assert row3_proof["single_selected_passage_sufficient"] is False
    assert row4_proof["single_selected_passage_sufficient"] is False
    assert row5_proof["graph_edge_required_and_selected"] is True
    assert rows[9]["browser_checks"]["visible_ask_navigation"] is True
    assert rows[9]["browser_checks"]["no_browser_secret_delivery"] is True
    assert (tmp_path / "m26-pa-7-final-web-product-readiness-receipt.json").exists()


def test_duplicate_live_guard_blocks_after_final_acceptance_and_closure(
    tmp_path: Path,
) -> None:
    (tmp_path / "pilot/m26").mkdir(parents=True)
    assert duplicate_live_guard_status(tmp_path)["live_execution_authorized"] is True

    (tmp_path / "pilot/m26/m26-pa-7-acceptance.json").write_text(
        json.dumps({"status": FINAL_ACCEPTED_STATUS}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "pilot/m26/m26-pa-7-m26-closure.json").write_text(
        json.dumps({"status": "m26_closed"}) + "\n",
        encoding="utf-8",
    )
    guard = duplicate_live_guard_status(tmp_path)

    assert guard["status"] == "duplicate_live_execution_blocked_after_final_closure"
    assert guard["live_execution_authorized"] is False
    assert guard["provider_calls_authorized"] == 0


def test_oracle_backend_image_includes_m26_readonly_pilot_artifacts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY pilot ./pilot" in dockerfile
    assert "knowledge_engine.api:app" in dockerfile


def test_final_web_live_workflow_binds_backend_pages_and_runtime_rows() -> None:
    workflow = (
        ROOT / ".github/workflows/m26-pa-7-final-web-product-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "deploy_and_runtime_formal" in workflow
    assert "scripts/configure_oracle_ssh.sh" in workflow
    assert "M26_QUERY_BACKEND_TOKEN" in workflow
    assert "M26_QUERY_BACKEND_URL" in workflow
    assert "wrangler@4.111.0 pages secret put" in workflow
    assert "wrangler@4.111.0 pages deploy" in workflow
    assert "final_formal_query_specs()[:9]" in workflow
    assert "live_final_runtime_rows_passed_awaiting_owner_browser_e2e" in workflow
    assert "duplicate_live_guard_status" in workflow
    assert "public-api-denial" in workflow
    assert "cloudflared" in workflow
    assert "trycloudflare" in workflow
    assert "backend-tunnel-readback.json" in workflow
    assert "backend-tunnel-rollback.log" in workflow
    assert "raw_tunnel_url_recorded" in workflow
    assert "getent hosts" in workflow
    assert 'export M26_QUERY_BACKEND_ORIGIN="$backend_origin"' in workflow
    assert 'export NEW_PAGES_DEPLOYMENT_ID="$value"' in workflow
    assert 'test "$new_pages_deployment_id" != "$PREVIOUS_PAGES_DEPLOYMENT_ID"' in workflow
    assert "health_attempts" in workflow
    assert "origin_ca_rsa_root.pem" in workflow
    assert "origin_ca_ecc_root.pem" in workflow
    assert "91a8a5567efa6bf941162aa806b3ba476aaddf7867640e53053b35fb225a5dae" in workflow
    assert "ca56c5b29918faf79046b1c1726c35d7715951a35445b2e63f56ea5a70b7af9c" in workflow
    assert "--insecure" not in workflow
