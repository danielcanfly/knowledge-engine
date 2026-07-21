from __future__ import annotations

import json
from pathlib import Path

from scripts.m23_7_r3_8_remote_operator import canonical_sha256

from knowledge_engine.m24_14_sigma_graph_explorer import (
    P2_REPORT_PATH,
    build_p2_sigma_graph_explorer_report,
)
from knowledge_engine.m24_internal_product_deployment import SITE_ROOT
from knowledge_engine.storage import sha256_bytes


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m24_14_2_report_is_digest_bound() -> None:
    report = _json(P2_REPORT_PATH)
    unsigned = dict(report)
    digest = unsigned.pop("self_sha256")

    assert canonical_sha256(unsigned) == digest


def test_m24_14_2_report_matches_generated_sigma_explorer_evidence() -> None:
    report = build_p2_sigma_graph_explorer_report()

    assert report.model_dump(mode="json") == _json(P2_REPORT_PATH)
    assert report.status == "m24_14_2_sigma_graph_explorer_integrated"
    assert report.runtime.renderer_runtime == "sigma_js_canvas"
    assert report.runtime.runtime_cdn_dependencies is False
    assert report.runtime.local_vendor_assets_only is True


def test_m24_14_2_site_loads_local_sigma_assets_before_app_shell() -> None:
    build_p2_sigma_graph_explorer_report()
    index = SITE_ROOT.joinpath("index.html").read_text(encoding="utf-8")

    assert '<script src="vendor/graphology.umd.min.js"></script>' in index
    assert '<script src="vendor/sigma.min.js"></script>' in index
    assert '<script src="graph-explorer.js"></script>' in index
    assert index.index("vendor/graphology.umd.min.js") < index.index("vendor/sigma.min.js")
    assert index.index("vendor/sigma.min.js") < index.index("graph-explorer.js")
    assert index.index("graph-explorer.js") < index.index("app.js")
    assert "<script src=\"http" not in index
    assert "<script src=\"https" not in index


def test_m24_14_2_graph_route_uses_real_sigma_canvas_runtime() -> None:
    build_p2_sigma_graph_explorer_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")
    explorer_js = SITE_ROOT.joinpath("graph-explorer.js").read_text(encoding="utf-8")

    assert "data-sigma-stage" in app_js
    assert "initializeGraphExplorer" in app_js
    assert "createM24GraphExplorer" in explorer_js
    assert "new Sigma(graph, stage" in explorer_js
    assert "new Graphology(" in explorer_js
    assert "renderer.getCamera().animatedReset" in explorer_js
    assert "clickNode" in explorer_js
    assert "clickStage" in explorer_js
    assert "relation_filter" in _json(P2_REPORT_PATH)["interaction"]["controls"]


def test_m24_14_2_graph_controls_and_error_states_are_present() -> None:
    build_p2_sigma_graph_explorer_report()
    app_js = SITE_ROOT.joinpath("app.js").read_text(encoding="utf-8")
    explorer_js = SITE_ROOT.joinpath("graph-explorer.js").read_text(encoding="utf-8")

    for marker in [
        "data-graph-search",
        "data-graph-relation",
        "data-graph-neighbor=\"1\"",
        "data-graph-neighbor=\"2\"",
        "data-graph-reset",
        "data-graph-clear",
        "data-graph-orphans",
        "data-graph-details",
        "data-graph-results",
    ]:
        assert marker in app_js
    for marker in [
        "No graph nodes match the current filters.",
        "Sigma.js browser runtime unavailable",
        "Graph explorer initialization failed.",
        "No matching graph nodes.",
    ]:
        assert marker in app_js or marker in explorer_js


def test_m24_14_2_assets_match_committed_site_bytes() -> None:
    report = build_p2_sigma_graph_explorer_report()
    paths = {asset.path for asset in report.assets}

    assert SITE_ROOT.joinpath("vendor/graphology.umd.min.js").as_posix() in paths
    assert SITE_ROOT.joinpath("vendor/sigma.min.js").as_posix() in paths
    assert SITE_ROOT.joinpath("graph-explorer.js").as_posix() in paths
    for asset in report.assets:
        data = Path(asset.path).read_bytes()
        assert len(data) == asset.bytes
        assert sha256_bytes(data) == asset.sha256


def test_m24_14_2_preserves_non_production_authority_boundary() -> None:
    report = build_p2_sigma_graph_explorer_report()

    assert report.authority.product_audience == "authenticated_internal"
    assert report.authority.browser_authority == "read_only"
    assert report.authority.production_retrieval == "lexical"
    assert report.authority.semantic_promotion_enabled is False
    assert report.authority.semantic_serving_enabled is False
    assert report.authority.hybrid_retrieval_enabled is False
    assert report.authority.production_pointer_mutation is False
    assert report.authority.production_r2_mutation is False
    assert report.authority.qdrant_mutation is False
    assert report.authority.credential_mutation is False
    assert report.authority.traffic_mutation is False
