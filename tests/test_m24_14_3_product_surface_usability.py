from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_14_product_surface_usability import (
    P3_REPORT_PATH,
    build_p3_product_surface_usability_report,
)
from knowledge_engine.m24_internal_product_deployment import SITE_ROOT
from knowledge_engine.storage import sha256_bytes


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_14_3_report_is_digest_bound() -> None:
    report = _json(P3_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_14_3_report_matches_generated_surface_usability_evidence() -> None:
    report = build_p3_product_surface_usability_report()

    assert report.model_dump(mode="json") == _json(P3_REPORT_PATH)
    assert report.status == "m24_14_3_product_surfaces_usable"
    assert report.client_side_only is True
    assert report.external_network_dependencies is False
    assert report.runtime_cdn_dependencies is False


def test_m24_14_3_concept_wiki_has_navigation_and_mismatch_state() -> None:
    build_p3_product_surface_usability_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "concept-artifact-mismatch" in app_js
    assert "data-open-source-viewer" in app_js
    assert "data-focus-concept" in app_js
    assert "data-route=\"search\"" in app_js
    assert "concept-section-empty" in app_js


def test_m24_14_3_lexical_search_has_client_side_filter_and_handoffs() -> None:
    build_p3_product_surface_usability_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "filteredSearchResults" in app_js
    assert "data-search-form" in app_js
    assert "Release-pinned lexical results" in app_js
    assert "data-open-source-card" in app_js
    assert "data-open-concept" in app_js
    assert "No lexical matches" in app_js


def test_m24_14_3_source_viewer_has_filter_citation_drill_in_and_states() -> None:
    build_p3_product_surface_usability_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")

    assert "data-source-form" in app_js
    assert "Source detail" in app_js
    assert "data-open-citation" in app_js
    assert "citation-unavailable" in app_js
    assert "citation-pinned" in app_js
    assert "source-no-match" in app_js


def test_m24_14_3_assets_match_committed_site_bytes() -> None:
    report = build_p3_product_surface_usability_report()

    for asset in report.assets:
        data = Path(asset.path).read_bytes()
        assert len(data) == asset.bytes
        assert sha256_bytes(data) == asset.sha256


def test_m24_14_3_preserves_non_production_authority_boundary() -> None:
    report = build_p3_product_surface_usability_report()

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
