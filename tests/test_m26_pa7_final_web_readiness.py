from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from scripts.m26_pa7_durable_backend_origin import (
    _normalized_oracle_hostname,
    wildcard_dns_origin,
)
from scripts.m26_pa7_evidence_privacy_hygiene import (
    build_public_denial_evidence,
    scan_evidence_path,
)
from scripts.m26_pa7_evidence_privacy_hygiene import (
    main as evidence_privacy_hygiene_main,
)
from scripts.m26_pa7_named_backend_tunnel import _require_hostname_under_zone

import knowledge_engine.m26_pa7_arbitrary_query_runtime as runtime_module
from knowledge_engine.m26_pa7_arbitrary_query_runtime import LocalDenseProjectionChannel
from knowledge_engine.m26_pa7_final_web_readiness import (
    ASK_URL,
    CANONICAL_RUNTIME_PATH,
    FINAL_ACCEPTED_STATUS,
    FINAL_CLASSES,
    FINAL_WEB_FORMAL_MANIFEST_SCHEMA,
    FINAL_WEB_READINESS_RECEIPT_SCHEMA,
    _runtime_row_from_response,
    build_final_web_formal_test_manifest,
    duplicate_live_guard_status,
    final_formal_query_specs,
    historical_formal_bank_diagnostic_summary,
    historical_formal_row_diagnostic_only,
    run_final_web_product_readiness,
    validate_final_web_formal_test_manifest,
)
from knowledge_engine.m26_production_promotion_closure import (
    load_json,
    verify_self_digest,
)
from tests.m26_answer_bundle_fixture import synthetic_full_production_answer_bundle

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "pilot" / "m26"
SCHEMAS = ROOT / "schemas"
OWNER_SUBJECT_HASH = "93c8aaae82e498dc2e6bfdcaa48b8823fe21a5ceef44ca2cf9cf35cf6350e05b"
FINAL_MANIFEST_SELF_SHA256 = (
    "fbedacb25b7bc9a28833d58658e6425637d990b064ea67a31451f94e7f36e91e"
)


@pytest.fixture(autouse=True)
def _full_production_answer_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "load_production_answer_bundle",
        lambda store=None: synthetic_full_production_answer_bundle(),
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


def test_final_web_formal_bank_intent_compat_preserves_runtime_telemetry() -> None:
    spec = final_formal_query_specs()[2]
    response = {
        "citations": [
            {"evidence_type": "passage", "source_identity": "source-a"},
            {"evidence_type": "passage", "source_identity": "source-b"},
        ],
        "citation_locator_valid": True,
        "distinct_source_count": 2,
        "graph_hops_used": 1,
        "intent_class": "direct_grounded_knowledge",
        "material_claim_support_verified": True,
        "multi_evidence_verification": {
            "single_primary_passage_used": False,
            "support_ref_count": 2,
        },
        "provider_call_count": 1,
        "provider_invoked": True,
        "question_sha256": spec["question_sha256"],
        "reason_codes": [],
        "relationship_summary": {"relation": "contrasts_with"},
        "safe_abstention": False,
        "selected_evidence": [
            {"evidence_type": "passage", "source_identity": "source-a"},
            {"evidence_type": "passage", "source_identity": "source-b"},
        ],
        "selected_evidence_count": 2,
        "status": "owner_only_cited_answer",
        "terminal_status": "verified_answer_ready_candidate",
        "trace_id": "m26pa7aq_test_formal_compat",
        "unsupported_accepted_claims": 0,
    }

    row = _runtime_row_from_response(spec=spec, response=response)

    assert row["class"] == "cross_document_comparison"
    assert row["pass"] is True
    assert row["intent_class"] == "direct_grounded_knowledge"
    assert row["formal_intent_class"] == "cross_document_comparison"
    assert row["formal_intent_compat_used"] is True


def test_historical_formal_bank_failure_is_diagnostic_without_rewriting_row() -> None:
    spec = final_formal_query_specs()[2]
    response = {
        "citations": [
            {"evidence_type": "passage", "source_identity": "source-a"},
        ],
        "citation_locator_valid": True,
        "distinct_source_count": 5,
        "graph_hops_used": 1,
        "intent_class": "direct_grounded_knowledge",
        "material_claim_support_verified": True,
        "multi_evidence_verification": {
            "single_primary_passage_used": False,
            "support_ref_count": 1,
        },
        "provider_call_count": 1,
        "provider_invoked": True,
        "question_sha256": spec["question_sha256"],
        "reason_codes": [],
        "relationship_summary": {"relation": "contrasts_with"},
        "safe_abstention": False,
        "selected_evidence": [
            {"evidence_type": "passage", "source_identity": "source-a"},
        ],
        "selected_evidence_count": 8,
        "status": "owner_only_cited_answer",
        "terminal_status": "verified_answer_ready_candidate",
        "trace_id": "m26pa7aq_test_historical_diagnostic",
        "unsupported_accepted_claims": 0,
    }

    row = _runtime_row_from_response(spec=spec, response=response)
    summary = historical_formal_bank_diagnostic_summary([row])

    assert row["pass"] is False
    assert historical_formal_row_diagnostic_only(row) is True
    assert summary["non_blocking"] is True
    assert summary["historical_row_results_rewritten"] is False
    assert summary["diagnostic_failed_rows"][0]["class"] == "cross_document_comparison"
    assert "canonical semantic contract R3" in summary["canonical_product_authority"]


def test_row5_verified_corpus_scope_mismatch_is_diagnostic_without_passing_row() -> None:
    spec = final_formal_query_specs()[4]
    response = {
        "citation_locator_valid": True,
        "citations": [],
        "distinct_source_count": 8,
        "intent_class": "graph_relationship",
        "material_claim_support_verified": True,
        "multi_evidence_verification": {
            "claim_count": 0,
            "support_ref_count": 0,
            "unsupported_accepted_claims": 0,
        },
        "provider_call_count": 1,
        "provider_invoked": True,
        "question_sha256": spec["question_sha256"],
        "reason_codes": ["INSUFFICIENT_SUPPORT"],
        "relationship_summary": {},
        "safe_abstention": True,
        "selected_evidence": [
            {
                "evidence_type": "graph_edge",
                "source_identity": "graph_v2:edge_3f15206278e63ccf8981",
            },
            {"evidence_type": "passage", "source_identity": "source-a"},
        ],
        "selected_evidence_count": 2,
        "status": "owner_only_safe_abstention",
        "terminal_status": "safe_abstention",
        "trace_id": "m26pa7aq_test_row5_corpus_scope",
        "unsupported_accepted_claims": 0,
    }

    row = _runtime_row_from_response(spec=spec, response=response)
    summary = historical_formal_bank_diagnostic_summary([row])

    assert row["pass"] is False
    assert row["row5_canonical_reconcile"]["raw_row_result_preserved"] is True
    assert historical_formal_row_diagnostic_only(row) is True
    assert summary["non_blocking"] is True
    assert summary["diagnostic_failed_rows"][0]["row5_canonical_reconcile"][
        "canonical_selected_exact_legacy_edge"
    ] is False


def test_safe_abstention_with_graph_edge_is_not_blanket_diagnostic() -> None:
    row = {
        "class": "graph_relationship_navigation",
        "ordinal": 5,
        "pass": False,
        "provider_invoked": True,
        "question_sha256": "0" * 64,
        "reason_codes": [
            "INSUFFICIENT_SUPPORT",
            "HISTORICAL_ROW5_CORPUS_SCOPE_MISMATCH_VERIFIED",
        ],
        "source_citation_count": 0,
        "status": "owner_only_safe_abstention",
        "support_ref_count": 0,
        "terminal_status": "safe_abstention",
        "unsupported_accepted_claims": 0,
    }

    summary = historical_formal_bank_diagnostic_summary([row])

    assert historical_formal_row_diagnostic_only(row) is False
    assert summary["non_blocking"] is False
    assert summary["blocking_failed_row_count"] == 1


def test_security_or_unsupported_formal_failures_remain_blocking() -> None:
    row = {
        "class": "prompt_injection_privacy",
        "pass": False,
        "status": "owner_only_cited_answer",
        "terminal_status": "verified_answer_ready_candidate",
        "safe_terminal": True,
        "citation_locator_valid": True,
        "material_claim_support_verified": True,
        "unsupported_accepted_claims": 1,
        "provider_invoked": True,
    }

    summary = historical_formal_bank_diagnostic_summary([row])

    assert historical_formal_row_diagnostic_only(row) is False
    assert summary["non_blocking"] is False
    assert summary["blocking_failed_row_count"] == 1


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
    assert "workflow_dispatch:" in workflow
    assert (
        "(github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main')"
        in workflow
    )
    assert '"src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py"' in workflow
    assert '"tests/test_m26_pa_7_arbitrary_query_runtime.py"' in workflow
    assert '"scripts/m26_pa7_access_browser_session_contract.py"' in workflow
    assert '"tests/test_m26_pa7_access_browser_session_contract.py"' in workflow
    assert "scripts/m26_pa7_access_browser_session_contract.py inspect" in workflow
    assert "access-browser-session-contract.json" in workflow
    assert "Access browser-session contract summary" in workflow
    assert "same_site_cookie_attribute" in workflow
    assert "path_cookie_attribute" in workflow
    assert "path_cookie_attribute_effective" in workflow
    assert "path_cookie_attribute_raw_class" in workflow
    assert "path_specific_overlap_counts" in workflow
    assert "src/knowledge_engine/m23_cloudflare_qdrant.py" in workflow
    assert "tests/test_m23_5_cloudflare_qdrant.py" in workflow
    assert "scripts/configure_oracle_ssh.sh" in workflow
    assert "M26_QUERY_BACKEND_TOKEN" in workflow
    assert "M26_QUERY_BACKEND_URL" in workflow
    assert "M26_QUERY_BACKEND_TUNNEL_HOSTNAME" in workflow
    assert "M26_QUERY_BACKEND_TUNNEL_NAME" in workflow
    assert "scripts/m26_pa7_named_backend_tunnel.py ensure" in workflow
    assert "scripts/m26_pa7_durable_backend_origin.py oracle-https" in workflow
    assert "scripts/m26_pa7_durable_backend_origin.py cloudflare-dns-a" in workflow
    assert "scripts/m26_pa7_durable_backend_origin.py wildcard-dns" in workflow
    assert "--suffix nip.io" in workflow
    assert "backend-named-tunnel.json" in workflow
    assert "backend-cloudflare-dns-a-origin.json" in workflow
    assert "backend-cloudflare-dns-a-unavailable.json" in workflow
    assert "backend-wildcard-dns-origin.json" in workflow
    assert "backend-oracle-https-origin.json" in workflow
    assert "M26_BACKEND_ORIGIN_CLASS" in workflow
    assert "cloudflare_dns_a_to_oracle_https_reverse_proxy" in workflow
    assert "seq 2 180" in workflow
    assert "--connect-timeout 5 --max-time 15" in workflow
    assert "backend-https-origin-diagnostic.json" in workflow
    assert "raw_log_recorded" in workflow
    assert "legacy-oracle-https-port-handoff.json" in workflow
    assert "M26_LEGACY_ORACLE_HTTPS_PORT_OWNER_STOPPED" in workflow
    assert "legacy-oracle-https-port-owner-rollback.log" in workflow
    assert "oracle-https-port-handoff.json" in workflow
    assert "knowledge-engine-m26-pa7-oracle-https-port-handoff/v1" in workflow
    assert "non_docker_owner_classes" in workflow
    assert "system_caddy" in workflow
    assert "system_nginx" in workflow
    assert "system_apache2" in workflow
    assert "system_httpd" in workflow
    assert "raw_system_service_name_recorded" in workflow
    assert "stopped_system_service_count" in workflow
    assert "system_service_owner_records" in workflow
    assert "M26_ORACLE_SYSTEM_WEB_PORT_OWNER_STOPPED" in workflow
    assert "oracle-system-web-port-handoff-rollback.log" in workflow
    assert "raw_listener_recorded" in workflow
    assert "raw_pid_recorded" in workflow
    assert "M26_ORACLE_HTTPS_PORT_HANDOFF_STOPPED" in workflow
    assert "oracle-https-port-handoff-rollback.log" in workflow
    assert '["sudo", "-n", "ss", "-H", "-ltnp"]' in workflow
    assert '["ss", "-H", "-ltnp"]' in workflow
    assert "system-caddy-origin-binding.json" in workflow
    assert "knowledge-engine-m26-pa7-system-caddy-origin-binding/v1" in workflow
    assert "raw_snippet_recorded" in workflow
    assert "M26_SYSTEM_CADDY_ORIGIN_DEPLOYED" in workflow
    assert "M26_BACKEND_HTTPS_PROXY_MODE=system_caddy" in workflow
    assert "journalctl -u caddy" in workflow
    assert "system-caddy-origin-rollback.log" in workflow
    assert "m26-pa7-backend-tunnel" in workflow
    assert "m26-pa7-backend-https-origin" in workflow
    assert "caddy:2-alpine" in workflow
    assert "cloudflare/cloudflared:latest" in workflow
    assert "m26-pa7-oracle-backend-production-${{ github.ref }}" in workflow
    assert "wrangler@4.111.0 pages secret put" in workflow
    assert "wrangler@4.111.0 pages deploy" in workflow
    assert "final_formal_query_specs()[:9]" in workflow
    assert "live_final_runtime_rows_passed_awaiting_owner_browser_e2e" in workflow
    assert "live_final_runtime_rows_failed" in workflow
    assert (
        "hard_integration_passed_with_historical_formal_bank_"
        "diagnostics_awaiting_owner_browser_e2e"
    ) in workflow
    assert "historical_formal_bank_diagnostic_summary" in workflow
    assert "historical_formal_row_results_rewritten" in workflow
    assert "canonical_product_authority" in workflow
    assert "hard_post_merge_integration_checks" in workflow
    assert "failed_row" in workflow
    assert "raw_provider_payload_recorded" in workflow
    assert "raw_answer_text_recorded" in workflow
    assert "duplicate_live_guard_status" in workflow
    assert "public-api-denial" in workflow
    assert "public-api-denial-sanitized.json" in workflow
    assert "public-api-denial.headers" not in workflow
    assert "public-api-denial.body" not in workflow
    assert "m26_pa7_evidence_privacy_hygiene.py public-denial" in workflow
    assert "m26_pa7_evidence_privacy_hygiene.py scan" in workflow
    assert "evidence-privacy-scan.json" in workflow
    assert "steps.privacy_scan.outcome == 'success'" in workflow
    assert "durable backend origin" in workflow
    assert "backend-origin-contract.json" in workflow
    assert "backend_origin_must_use_https" in workflow
    assert "backend_origin_hostname_required" in workflow
    assert "trycloudflare_quick_tunnel_forbidden" in workflow
    assert 'hostname == "trycloudflare.com"' in workflow
    assert 'hostname.endswith(".trycloudflare.com")' in workflow
    assert "raw_backend_origin_recorded" in workflow
    assert "trycloudflare.com" in workflow
    assert "backend-quick-tunnel" not in workflow
    assert "cloudflared tunnel --no-autoupdate --url" not in workflow
    assert 'export M26_QUERY_BACKEND_ORIGIN="$backend_origin"' in workflow
    assert 'export NEW_PAGES_DEPLOYMENT_ID="$value"' in workflow
    assert 'test "$new_pages_deployment_id" != "$PREVIOUS_PAGES_DEPLOYMENT_ID"' in workflow
    assert "health_attempts" in workflow
    assert "origin_ca_rsa_root.pem" in workflow
    assert "origin_ca_ecc_root.pem" in workflow
    assert "91a8a5567efa6bf941162aa806b3ba476aaddf7867640e53053b35fb225a5dae" in workflow
    assert "ca56c5b29918faf79046b1c1726c35d7715951a35445b2e63f56ea5a70b7af9c" in workflow
    assert "--insecure" not in workflow


def test_access_redirect_repair_workflow_enforces_cookie_contract() -> None:
    workflow = (
        ROOT / ".github/workflows/m26-pa7-access-redirect-repair.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert ".github/workflows/m26-pa7-explicit-backend-redeploy.yml" in workflow
    assert ".github/workflows/m26-pa7-explicit-pages-deploy.yml" in workflow
    assert "src/knowledge_engine/m26_pa7_final_web_readiness.py" in workflow
    assert "repair_access_redirect_contract" in workflow
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in workflow
    assert "CLOUDFLARE_ACCESS_READ_TOKEN" in workflow
    assert "CLOUDFLARE_ACCESS_WRITE_TOKEN" in workflow
    assert "CLOUDFLARE_ZONE_NAME" in workflow
    assert "CLOUDFLARE_WORKERS_TOKEN" in workflow
    assert "CLOUDFLARE_PAGES_TOKEN" in workflow
    assert "for label in primary workers pages" in workflow
    assert "ACCESS_REPAIR_WRITE_TOKEN_CLASS" in workflow
    assert "scripts/m26_pa7_access_browser_session_contract.py repair" in workflow
    assert "access-browser-session-before.json" in workflow
    assert "access-browser-session-repair.json" in workflow
    assert "access-browser-session-after.json" in workflow
    assert "scripts/m26_pa7_evidence_privacy_hygiene.py scan" in workflow
    assert "raw domains/cookies/login URLs/tokens recorded:" in workflow
    assert "\\`false\\`" in workflow
    assert (
        "jq -e '.status == \"pass\"' \"$WORK_DIR/evidence/access-browser-session-after.json\""
        in workflow
    )
    assert "path_specific_overlap_counts" in workflow
    assert "same_site_cookie_attribute" in workflow
    assert "path_cookie_attribute" in workflow
    assert "path_cookie_attribute_effective" in workflow
    assert "path_cookie_attribute_raw_class" in workflow
    assert "update_scope" in workflow
    assert "zone_name_recorded" in workflow
    assert "CF_Authorization" not in workflow
    assert "cdn-cgi/access/login" not in workflow


def test_public_denial_sanitizer_records_semantics_without_raw_headers() -> None:
    evidence = build_public_denial_evidence(
        http_status=302,
        headers_text=(
            "HTTP/2 302\r\n"
            "Location: https://team.cloudflareaccess.com/cdn-cgi/access/login/app?meta=secret\r\n"
            "Set-Cookie: CF_Authorization=secret; HttpOnly\r\n"
        ),
        body_text="Cloudflare Access login",
    )

    assert evidence == {
        "schema_version": "knowledge-engine-m26-pa7-public-denial-sanitized/v1",
        "http_status": 302,
        "access_denied": True,
        "redirect_class": "cloudflare_access_login",
        "redirect_host_sha256": (
            "564ae06c9e97b2a35acd958e7da734bf65a83473ec0dcc8ceec4399647f34ec7"
        ),
        "location_header_present": True,
        "www_authenticate_present": False,
        "set_cookie_present": True,
        "access_marker_present": True,
        "raw_header_values_recorded": False,
        "raw_location_recorded": False,
        "raw_cookie_recorded": False,
        "raw_jwt_recorded": False,
        "raw_token_recorded": False,
        "raw_response_body_recorded": False,
    }
    assert "secret" not in json.dumps(evidence, sort_keys=True)
    assert "Set-Cookie" not in json.dumps(evidence, sort_keys=True)
    assert "meta=" not in json.dumps(evidence, sort_keys=True)


def test_public_denial_cli_accepts_missing_redirect_body_file(tmp_path: Path) -> None:
    headers = tmp_path / "response-headers.tmp"
    missing_body = tmp_path / "response-body.tmp"
    output = tmp_path / "public-api-denial-sanitized.json"
    status_output = tmp_path / "public-api-denial.status"
    headers.write_text(
        "HTTP/2 302\r\n"
        "Location: https://team.cloudflareaccess.com/cdn-cgi/access/login/app\r\n",
        encoding="utf-8",
    )

    result = evidence_privacy_hygiene_main(
        [
            "public-denial",
            "--status",
            "302",
            "--headers",
            str(headers),
            "--body",
            str(missing_body),
            "--output",
            str(output),
            "--status-output",
            str(status_output),
        ]
    )

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert evidence["access_denied"] is True
    assert evidence["redirect_class"] == "cloudflare_access_login"
    assert evidence["raw_response_body_recorded"] is False
    assert status_output.read_text(encoding="utf-8") == "302\n"


def test_evidence_privacy_scan_fails_on_raw_set_cookie_header(tmp_path: Path) -> None:
    (tmp_path / "public-api-denial.headers").write_text(
        "HTTP/2 302\nSet-Cookie: CF_Authorization=secret; HttpOnly\n",
        encoding="utf-8",
    )

    scan = scan_evidence_path(tmp_path)

    assert scan["status"] == "fail"
    assert scan["violations"] == 1
    assert scan["findings"][0]["violation_classes"] == ["set_cookie_header"]
    assert scan["raw_secret_values_recorded"] is False


def test_evidence_privacy_scan_fails_on_access_login_metadata_and_jwt(
    tmp_path: Path,
) -> None:
    (tmp_path / "dirty.txt").write_text(
        "https://team.cloudflareaccess.com/cdn-cgi/access/login/app?kid=abc&meta="
        "eyJaaaaaaaaaaaa.eyJbbbbbbbbbbbb.cccccccccccccc\n",
        encoding="utf-8",
    )

    scan = scan_evidence_path(tmp_path)

    assert scan["status"] == "fail"
    classes = set(scan["findings"][0]["violation_classes"])
    assert "cloudflare_access_login_metadata" in classes
    assert "jwt_like_value" in classes


def test_evidence_privacy_scan_passes_sanitized_public_denial_dto(
    tmp_path: Path,
) -> None:
    evidence = build_public_denial_evidence(
        http_status=302,
        headers_text=(
            "HTTP/2 302\r\n"
            "Location: https://team.cloudflareaccess.com/cdn-cgi/access/login/app?meta=secret\r\n"
            "Set-Cookie: CF_Authorization=secret; HttpOnly\r\n"
        ),
        body_text="Cloudflare Access login",
    )
    (tmp_path / "public-api-denial-sanitized.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    scan = scan_evidence_path(tmp_path)

    assert scan["status"] == "pass"
    assert scan["violations"] == 0
    assert scan["files_scanned"] == 1


def test_named_backend_tunnel_script_uses_sanitized_cloudflare_control_plane() -> None:
    script = (ROOT / "scripts/m26_pa7_named_backend_tunnel.py").read_text(encoding="utf-8")

    assert "/cfd_tunnel" in script
    assert "config_src" in script
    assert "cfargotunnel.com" in script
    assert "raw_backend_origin_recorded" in script
    assert '"raw_hostname_recorded": False' in script
    assert '"tunnel_token_recorded": False' in script
    assert "M26_BACKEND_TUNNEL_TOKEN" in script
    assert "trycloudflare quick tunnel hostnames are forbidden" in script


@pytest.mark.parametrize(
    ("hostname", "message"),
    [
        ("trycloudflare.com", "trycloudflare quick tunnel hostnames are forbidden"),
        ("abc.trycloudflare.com", "trycloudflare quick tunnel hostnames are forbidden"),
        ("danielcanfly.com", "backend tunnel hostname must be a subdomain"),
        ("m26-query-backend.example.com", "backend tunnel hostname must be within"),
    ],
)
def test_named_backend_tunnel_rejects_unsafe_hostnames(
    hostname: str,
    message: str,
) -> None:
    with pytest.raises(SystemExit, match=message):
        _require_hostname_under_zone(hostname, "danielcanfly.com")


def test_named_backend_tunnel_accepts_zone_subdomain() -> None:
    _require_hostname_under_zone("m26-query-backend.danielcanfly.com", "danielcanfly.com")


@pytest.mark.parametrize(
    ("hostname", "message"),
    [
        ("https://backend.example.com", "host-only"),
        ("127.0.0.1", "raw IP"),
        ("abc.trycloudflare.com", "trycloudflare quick tunnel"),
        ("localhost", "DNS hostname"),
    ],
)
def test_oracle_https_origin_rejects_non_durable_hostnames(
    hostname: str,
    message: str,
) -> None:
    with pytest.raises(SystemExit, match=message):
        _normalized_oracle_hostname(hostname)


def test_oracle_https_origin_accepts_dns_hostname() -> None:
    assert _normalized_oracle_hostname("Oracle-Backend.Example.com.") == (
        "oracle-backend.example.com"
    )


def test_durable_origin_script_can_prepare_cloudflare_dns_a_origin() -> None:
    script = (ROOT / "scripts/m26_pa7_durable_backend_origin.py").read_text(encoding="utf-8")

    assert "cloudflare-dns-a" in script
    assert '"type": "A"' in script
    assert '"proxied": False' in script
    assert '"raw_ip_recorded": False' in script
    assert "cloudflare_dns_a_to_oracle_https_reverse_proxy" in script


def test_wildcard_dns_origin_derives_hostname_without_raw_evidence() -> None:
    evidence, runtime = wildcard_dns_origin(address="203.0.113.7")

    assert evidence["origin_class"] == "wildcard_dns_to_oracle_https_reverse_proxy"
    assert evidence["raw_backend_origin_recorded"] is False
    assert evidence["raw_hostname_recorded"] is False
    assert evidence["raw_ip_recorded"] is False
    assert runtime["M26_BACKEND_ORIGIN_CLASS"] == "wildcard_dns_to_oracle_https_reverse_proxy"
    assert runtime["M26_QUERY_BACKEND_ORIGIN"] == "https://203-0-113-7.sslip.io"
    assert runtime["M26_ORACLE_BACKEND_TLS_HOSTNAME"] == "203-0-113-7.sslip.io"


def test_deploy_script_clears_stale_compose_state_before_service_up() -> None:
    deploy = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")

    assert "docker compose down --remove-orphans || true" in deploy
    assert "docker compose rm -f -s -v knowledge-engine" in deploy
    assert deploy.index("docker compose down --remove-orphans || true") < deploy.index(
        "docker compose run --rm --no-deps knowledge-engine"
    )


def test_explicit_pages_deploy_boundary_accepts_production_wiring_fix() -> None:
    workflow = (ROOT / ".github/workflows/m26-pa7-explicit-pages-deploy.yml").read_text(
        encoding="utf-8"
    )

    assert '".github/workflows/m26-pa7-access-redirect-repair.yml"' in workflow
    assert '".github/workflows/m26-pa7-owner-access-and-full-graph-repair.yml"' in workflow
    assert '"deploy/deploy.sh"' in workflow
    assert '"scripts/m26_pa7_access_browser_session_contract.py"' in workflow
    assert '"scripts/m26_pa7_named_backend_tunnel.py"' in workflow
    assert '"scripts/m26_pa7_durable_backend_origin.py"' in workflow
    assert '"scripts/m26_pa7_evidence_privacy_hygiene.py"' in workflow
    assert '"tests/test_m26_pa7_access_browser_session_contract.py"' in workflow


def test_explicit_backend_redeploy_boundary_accepts_production_wiring_fix() -> None:
    workflow = (
        ROOT / ".github/workflows/m26-pa7-explicit-backend-redeploy.yml"
    ).read_text(encoding="utf-8")

    assert ".github/workflows/m26-pa7-access-redirect-repair.yml" in workflow
    assert ".github/workflows/m26-pa7-owner-access-and-full-graph-repair.yml" in workflow
    assert "deploy/deploy.sh" in workflow
    assert "scripts/m26_pa7_access_browser_session_contract.py" in workflow
    assert "scripts/m26_pa7_named_backend_tunnel.py" in workflow
    assert "scripts/m26_pa7_durable_backend_origin.py" in workflow
    assert "scripts/m26_pa7_evidence_privacy_hygiene.py" in workflow
    assert "src/knowledge_engine/m26_pa7_final_web_readiness.py" in workflow
    assert "tests/test_m26_pa7_access_browser_session_contract.py" in workflow
    assert "m26-pa7-oracle-backend-production-${{ github.ref }}" in workflow
