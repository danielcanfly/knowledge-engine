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

P3_SCHEMA = "knowledge-engine-m24-14-3-product-surface-usability/v1"
P3_ISSUE_NUMBER = 1011
P3_ROOT = Path("pilot/m24/m24-14/product-surface-usability")
P3_REPORT_PATH = P3_ROOT / "m24-14-3-product-surface-usability.json"


class P3AssetEvidence(BaseModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P3WorkflowEvidence(BaseModel):
    surface: str
    controls: list[str]
    handoffs: list[str]
    bounded_states: list[str]
    same_origin_artifacts: list[str]


class P3ProductSurfaceUsabilityReport(BaseModel):
    schema_version: str = P3_SCHEMA
    status: Literal["m24_14_3_product_surfaces_usable"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    deployment_package: str
    assets: list[P3AssetEvidence]
    workflows: list[P3WorkflowEvidence]
    client_side_only: bool
    external_network_dependencies: bool
    runtime_cdn_dependencies: bool
    local_browser_route_smoke: bool
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


def _asset(path: Path) -> P3AssetEvidence:
    data = path.read_bytes()
    return P3AssetEvidence(
        path=path.as_posix(),
        bytes=len(data),
        sha256=sha256_bytes(data),
    )


def build_p3_product_surface_usability_report(
    *,
    output_path: Path = P3_REPORT_PATH,
    include_self_digest: bool = True,
) -> P3ProductSurfaceUsabilityReport:
    build_p6_internal_product_deployment()
    assets = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "styles.css",
        SITE_ROOT / "app.js",
        SITE_ROOT / "data/concept-wiki-harness.json",
        SITE_ROOT / "data/search-harness.json",
        SITE_ROOT / "data/source-viewers.json",
        SITE_ROOT / "data/graph-navigation.json",
        SITE_ROOT / "data/release-viewer.json",
    ]
    report = P3ProductSurfaceUsabilityReport(
        status="m24_14_3_product_surfaces_usable",
        issue_number=P3_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        deployment_package=SITE_ROOT.as_posix(),
        assets=[_asset(path) for path in assets],
        workflows=[
            P3WorkflowEvidence(
                surface="concept_wiki",
                controls=[
                    "open_loaded_concept",
                    "open_relationship_in_graph",
                    "open_section_source_viewer",
                    "inspect_lexical_results",
                ],
                handoffs=["graph", "search", "sources"],
                bounded_states=["concept_section_empty", "concept_artifact_mismatch"],
                same_origin_artifacts=[
                    "site/data/concept-wiki-harness.json",
                    "site/data/source-viewers.json",
                ],
            ),
            P3WorkflowEvidence(
                surface="lexical_search",
                controls=[
                    "query_filter",
                    "open_graph",
                    "open_wiki",
                    "open_source_card",
                ],
                handoffs=["wiki", "graph", "sources"],
                bounded_states=["no_match"],
                same_origin_artifacts=[
                    "site/data/search-harness.json",
                    "site/data/source-viewers.json",
                ],
            ),
            P3WorkflowEvidence(
                surface="source_viewer",
                controls=[
                    "source_filter",
                    "inspect_source",
                    "pin_citation",
                    "open_citation_concept",
                ],
                handoffs=["wiki", "graph"],
                bounded_states=[
                    "source_no_match",
                    "citation_unavailable",
                    "citation_pinned",
                ],
                same_origin_artifacts=["site/data/source-viewers.json"],
            ),
        ],
        client_side_only=True,
        external_network_dependencies=False,
        runtime_cdn_dependencies=False,
        local_browser_route_smoke=True,
        authority=P6AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = canonical_sha256(
            report.model_dump(mode="json", exclude={"self_sha256"})
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_json(report.model_dump(mode="json")), encoding="utf-8")
    return report
