from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_internal_product_deployment import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CSP,
    P6_ISSUE_NUMBER,
    build_p6_internal_product_deployment,
)
from knowledge_engine.storage import sha256_bytes

P6_ROOT = Path("pilot/m24/internal-product-deployment")
REPORT_PATH = P6_ROOT / "m24-p6-internal-product-deployment.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_p6_deployment_report_is_digest_bound() -> None:
    report = _json(REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_p6_report_matches_generated_internal_product_package() -> None:
    report = build_p6_internal_product_deployment()

    assert report.model_dump(mode="json") == _json(REPORT_PATH)
    assert report.issue_number == P6_ISSUE_NUMBER
    assert report.release_id == CANONICAL_RELEASE_ID
    assert report.manifest_sha256 == CANONICAL_MANIFEST_SHA256
    assert report.status == "internal_product_deployment_package_complete"


def test_m24_p6_contains_all_required_internal_product_surfaces() -> None:
    report = build_p6_internal_product_deployment()

    assert {surface.surface for surface in report.surfaces} == {
        "concept_wiki",
        "lexical_search",
        "sigma_graph_explorer",
        "provenance_source_viewer",
        "citation_grounded_internal_answers",
        "release_viewer",
        "obsidian_export",
    }
    assert len(report.surfaces) == 7
    assert all(surface.ready for surface in report.surfaces)
    assert all(surface.release_id == CANONICAL_RELEASE_ID for surface in report.surfaces)
    assert all(surface.fallback for surface in report.surfaces)


def test_m24_p6_artifact_manifest_matches_committed_site_bytes() -> None:
    report = build_p6_internal_product_deployment()
    artifact_paths = {artifact.path for artifact in report.artifacts}

    assert "pilot/m24/internal-product-deployment/site/index.html" in artifact_paths
    assert "pilot/m24/internal-product-deployment/site/styles.css" in artifact_paths
    assert "pilot/m24/internal-product-deployment/site/data/source-index.json" in artifact_paths
    assert "pilot/m24/internal-product-deployment/site/data/source-documents.json" in artifact_paths
    for artifact in report.artifacts:
        path = Path(artifact.path)
        data = path.read_bytes()
        assert len(data) == artifact.bytes
        assert sha256_bytes(data) == artifact.sha256


def test_m24_p6_source_document_package_covers_canonical_registry() -> None:
    build_p6_internal_product_deployment()
    source_index = _json(Path("pilot/m24/internal-product-deployment/site/data/source-index.json"))
    source_documents = _json(
        Path("pilot/m24/internal-product-deployment/site/data/source-documents.json")
    )
    source_viewers = _json(
        Path("pilot/m24/internal-product-deployment/site/data/source-viewers.json")
    )

    assert source_index["source_commit_sha"] == "acf78596ace8a7366688ccef72b507204d09d9f9"
    assert source_index["source_count"] == 7
    assert source_documents["source_count"] == 7
    assert source_viewers["viewer_count"] == 7

    paths = {row["document_path"] for row in source_index["coverage_matrix"]}
    assert len(paths) == 7
    for path in paths:
        assert Path("pilot/m24/internal-product-deployment/site", path).exists()

    blog_rows = [
        row for row in source_index["coverage_matrix"]
        if row["source_id"].startswith("source_blog_")
    ]
    assert len(blog_rows) == 3
    assert all(row["coverage_status"] == "full_snapshot" for row in blog_rows)
    assert all(
        row["origin_commit"] == "27e2fe996f878f2129bf510d6a326c02f7d87be5"
        for row in blog_rows
    )
    assert all(row["content_bytes"] > 20000 for row in blog_rows)

    assert (
        "Multi-agent is an organisational choice, not a maturity level"
        in source_documents["documents"]["source_blog_agent_architecture_6d"]["document"]["body"]
    )
    assert (
        "Simple requests pay the latency and error surface of planning"
        in source_documents["documents"]["source_blog_agent_execution_paths"]["document"]["body"]
    )
    assert (
        "The production objective is not maximum planning freedom"
        in source_documents["documents"]["source_blog_agent_planning_strategies"][
            "document"
        ]["body"]
    )

    m3 = source_documents["documents"]["source_m3_contract"]
    assert m3["coverage_status"] == "metadata_only_with_reason"
    assert m3["metadata_only_reason"]

    for row in source_index["coverage_matrix"]:
        document = source_documents["documents"][row["source_id"]]
        comparable = json.loads(json.dumps(document))
        comparable["integrity"]["browser_payload_sha256"] = None
        assert (
            canonical_sha256(comparable)
            == document["integrity"]["browser_payload_sha256"]
        )
        assert document["origin"]["repo"] == row["origin_repo"]
        assert document["origin"]["commit"] == row["origin_commit"]
        assert document["origin"]["path"] == row["origin_path"]
        assert document["origin"]["blob_sha"] == row["origin_blob_sha"]
        assert document["integrity"]["truncated"] is False
        assert document["integrity"]["executable_scripts_detected"] is False


def test_m24_p6_security_auth_and_rollback_gates_are_explicit() -> None:
    report = build_p6_internal_product_deployment()

    assert report.auth.required is True
    assert report.auth.anonymous_access is False
    assert report.auth.unauthenticated_behavior == "403"
    assert report.auth.live_url_status == "pending_cloudflare_access_binding"
    assert report.auth.manual_daniel_acceptance == "pending_authenticated_url"
    assert report.security.csp == CSP
    assert report.security.csp_inline_script_allowed is False
    assert report.security.csp_remote_network_allowed is False
    assert report.security.secret_scan_passed is True
    assert report.security.mutation_routes == []
    assert report.security.read_only_browser_authority is True
    assert "403_unauthenticated" in report.security.error_states
    assert "restore previous deployment package" in report.security.rollback_plan


def test_m24_p6_preserves_non_production_authority_boundary() -> None:
    report = build_p6_internal_product_deployment()

    assert report.authority.product_audience == "authenticated_internal"
    assert report.authority.browser_authority == "read_only"
    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_answer_serving_enabled is False
    assert report.authority.source_mutation is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False
    assert report.authority.permanent_ledger_mutation is False
    assert report.authority.raw_evidence_exposed is False
