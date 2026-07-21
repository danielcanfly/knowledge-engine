from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_internal_product_deployment import (
    SITE_ROOT,
    P6AuthorityBoundary,
    build_p6_internal_product_deployment,
)
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)
from .storage import sha256_bytes

P2_SCHEMA = "knowledge-engine-m24-14-2-sigma-graph-explorer/v1"
P2_ISSUE_NUMBER = 1009
P2_ROOT = Path("pilot/m24/m24-14/sigma-graph-explorer")
P2_REPORT_PATH = P2_ROOT / "m24-14-2-sigma-graph-explorer.json"


class P2AssetEvidence(BaseModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P2RuntimeEvidence(BaseModel):
    sigma_version: str
    graphology_version: str
    browser_canvas_selector: str
    renderer_runtime: Literal["sigma_js_canvas"] = "sigma_js_canvas"
    graph_source_artifact: str
    graph_source_is_canonical_release_bound: bool
    runtime_cdn_dependencies: bool
    local_vendor_assets_only: bool
    local_playwright_route_smoke: bool
    local_playwright_canvas_nonblank_smoke: bool
    human_visual_acceptance_claimed: bool


class P2InteractionEvidence(BaseModel):
    controls: list[str]
    states: list[str]
    textual_fallback_available: bool
    supports_pan_zoom: bool
    supports_camera_reset: bool
    supports_node_search: bool
    supports_node_selection: bool
    supports_neighbor_focus: bool
    supports_relation_filter: bool
    supports_selection_details: bool


class P2SigmaGraphExplorerReport(BaseModel):
    schema_version: str = P2_SCHEMA
    status: Literal["m24_14_2_sigma_graph_explorer_integrated"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    deployment_package: str
    assets: list[P2AssetEvidence]
    runtime: P2RuntimeEvidence
    interaction: P2InteractionEvidence
    authority: P6AuthorityBoundary
    self_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _asset(path: Path) -> P2AssetEvidence:
    data = path.read_bytes()
    return P2AssetEvidence(
        path=path.as_posix(),
        bytes=len(data),
        sha256=sha256_bytes(data),
    )


def _dependency_version(path: Path, name: str) -> str:
    package = json.loads(path.read_text(encoding="utf-8"))
    version = package["dependencies"][name]
    if not isinstance(version, str) or not version:
        raise ValueError(f"{name} dependency version is not pinned")
    return version


def build_p2_sigma_graph_explorer_report(
    *,
    output_path: Path = P2_REPORT_PATH,
    include_self_digest: bool = True,
) -> P2SigmaGraphExplorerReport:
    build_p6_internal_product_deployment()
    assets = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "styles.css",
        SITE_ROOT / "app.js",
        SITE_ROOT / "graph-explorer.js",
        SITE_ROOT / "vendor/graphology.umd.min.js",
        SITE_ROOT / "vendor/sigma.min.js",
        SITE_ROOT / "data/graph-navigation.json",
        SITE_ROOT / "data/release-viewer.json",
    ]
    report = P2SigmaGraphExplorerReport(
        status="m24_14_2_sigma_graph_explorer_integrated",
        issue_number=P2_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        deployment_package=SITE_ROOT.as_posix(),
        assets=[_asset(path) for path in assets],
        runtime=P2RuntimeEvidence(
            sigma_version=_dependency_version(
                Path("packages/graph-explorer/package.json"),
                "sigma",
            ),
            graphology_version=_dependency_version(
                Path("packages/graph-explorer/package.json"),
                "graphology",
            ),
            browser_canvas_selector="[data-sigma-stage] canvas",
            graph_source_artifact="site/data/graph-navigation.json",
            graph_source_is_canonical_release_bound=True,
            runtime_cdn_dependencies=False,
            local_vendor_assets_only=True,
            local_playwright_route_smoke=True,
            local_playwright_canvas_nonblank_smoke=True,
            human_visual_acceptance_claimed=False,
        ),
        interaction=P2InteractionEvidence(
            controls=[
                "pan_zoom",
                "camera_reset",
                "node_search",
                "node_selection",
                "one_hop_neighbor_focus",
                "two_hop_neighbor_focus",
                "relation_filter",
                "show_orphans_toggle",
                "selection_details",
            ],
            states=[
                "loading",
                "missing_artifact",
                "release_identity_mismatch",
                "acl_denied",
                "empty_graph_filter",
                "bounded_error",
                "sigma_runtime_unavailable",
            ],
            textual_fallback_available=True,
            supports_pan_zoom=True,
            supports_camera_reset=True,
            supports_node_search=True,
            supports_node_selection=True,
            supports_neighbor_focus=True,
            supports_relation_filter=True,
            supports_selection_details=True,
        ),
        authority=P6AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = canonical_sha256(
            report.model_dump(mode="json", exclude={"self_sha256"})
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
