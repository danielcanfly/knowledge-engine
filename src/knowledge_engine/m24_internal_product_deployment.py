from __future__ import annotations

import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .m24_14_6_authenticated_performance import (
    build_m24_14_6_pending_acceptance_report,
)
from .m24_product_surface_integration import (
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
    canonical_concept_wiki_page,
    canonical_graph_navigation_state,
    canonical_obsidian_export,
    canonical_runtime_search,
    load_canonical_release,
)
from .m24_query_answer_acceptance import build_p5_query_answer_acceptance_report
from .storage import sha256_bytes

P6_SCHEMA = "knowledge-engine-m24-p6-internal-product-deployment/v1"
P6_ISSUE_NUMBER = 997
DEPLOYMENT_ROOT = Path("pilot/m24/internal-product-deployment")
SITE_ROOT = DEPLOYMENT_ROOT / "site"
OBSIDIAN_VAULT_ZIP_RELATIVE = "downloads/llm-wiki-m24-obsidian-vault.zip"
SOURCE_DOCUMENT_PACKAGE_ROOT = Path("pilot/m24/source-document-package")
SOURCE_DOCUMENT_INDEX_PATH = SOURCE_DOCUMENT_PACKAGE_ROOT / "source-index.json"
SOURCE_DOCUMENT_AGGREGATE_PATH = SOURCE_DOCUMENT_PACKAGE_ROOT / "source-documents.json"
SOURCE_DOCUMENT_PAYLOAD_ROOT = SOURCE_DOCUMENT_PACKAGE_ROOT / "sources"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
GRAPH_VENDOR_ASSETS = (
    (
        Path("packages/graph-explorer/node_modules/graphology/dist/graphology.umd.min.js"),
        "vendor/graphology.umd.min.js",
    ),
    (
        Path("packages/graph-explorer/node_modules/sigma/dist/sigma.min.js"),
        "vendor/sigma.min.js",
    ),
)
FAVICON_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100ffff030000060005"
    "57bfab0000000049454e44ae426082"
)
SurfaceName = Literal[
    "concept_wiki",
    "lexical_search",
    "sigma_graph_explorer",
    "provenance_source_viewer",
    "citation_grounded_internal_answers",
    "release_viewer",
    "obsidian_export",
    "m24_14_6_acceptance",
]
CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "font-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)
CSP_META = CSP.replace("; frame-ancestors 'none'", "")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"CFPAT-[A-Za-z0-9_-]{20,}"),
)


class P6AuthorityBoundary(BaseModel):
    product_audience: Literal["authenticated_internal"] = "authenticated_internal"
    browser_authority: Literal["read_only"] = "read_only"
    production_retrieval: Literal["lexical"] = "lexical"
    semantic_promotion_enabled: bool = False
    semantic_serving_enabled: bool = False
    hybrid_retrieval_enabled: bool = False
    production_answer_serving_enabled: bool = False
    source_mutation: bool = False
    production_pointer_mutation: bool = False
    production_r2_mutation: bool = False
    qdrant_mutation: bool = False
    credential_mutation: bool = False
    traffic_mutation: bool = False
    permanent_ledger_mutation: bool = False
    raw_evidence_exposed: bool = False


class P6AuthContract(BaseModel):
    provider: Literal["cloudflare_access_or_equivalent"] = "cloudflare_access_or_equivalent"
    required: bool = True
    anonymous_access: bool = False
    unauthenticated_behavior: Literal["403"] = "403"
    identity_sources: list[str]
    live_url_status: Literal["pending_cloudflare_access_binding"] = (
        "pending_cloudflare_access_binding"
    )
    manual_daniel_acceptance: Literal["pending_authenticated_url"] = (
        "pending_authenticated_url"
    )


class P6SurfaceDescriptor(BaseModel):
    surface: SurfaceName
    path: str
    release_id: str
    ready: bool
    fallback: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class P6DeploymentArtifact(BaseModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P6SecurityChecks(BaseModel):
    csp: str
    csp_inline_script_allowed: bool = False
    csp_remote_network_allowed: bool = False
    secret_scan_passed: bool
    secret_scan_patterns: int = Field(ge=1)
    read_only_browser_authority: bool = True
    mutation_routes: list[str] = []
    observability_events: list[str]
    error_states: list[str]
    rollback_plan: list[str]


class P6InternalDeploymentReport(BaseModel):
    schema_version: str = P6_SCHEMA
    status: Literal["internal_product_deployment_package_complete"]
    issue_number: int
    release_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    deployment_package: str
    auth: P6AuthContract
    surfaces: list[P6SurfaceDescriptor]
    artifacts: list[P6DeploymentArtifact]
    security: P6SecurityChecks
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


def _digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        return canonical_sha256(value.model_dump(mode="json"))
    return canonical_sha256(value)


def _write_text(path: Path, text: str) -> P6DeploymentArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    data = path.read_bytes()
    return P6DeploymentArtifact(
        path=path.as_posix(),
        bytes=len(data),
        sha256=sha256_bytes(data),
    )


def _write_bytes(path: Path, data: bytes) -> P6DeploymentArtifact:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return P6DeploymentArtifact(
        path=path.as_posix(),
        bytes=len(data),
        sha256=sha256_bytes(data),
    )


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def _deterministic_obsidian_vault_zip(
    *,
    site_root: Path,
    export_files: list[Any],
) -> P6DeploymentArtifact:
    members: dict[str, bytes] = {
        file.path: file.content.encode("utf-8")
        for file in export_files
    }
    members[".obsidian/app.json"] = (
        json.dumps(
            {
                "alwaysUpdateLinks": True,
                "attachmentFolderPath": "attachments",
                "newFileLocation": "folder",
                "newFileFolderPath": "concepts",
                "readableLineLength": True,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(members):
            archive.writestr(_zip_info(path), members[path])
    return _write_bytes(site_root / OBSIDIAN_VAULT_ZIP_RELATIVE, buffer.getvalue())


def _surface(
    *,
    surface: SurfaceName,
    path: str,
    payload: Any,
    fallback: str,
) -> P6SurfaceDescriptor:
    return P6SurfaceDescriptor(
        surface=surface,
        path=path,
        release_id=CANONICAL_RELEASE_ID,
        ready=True,
        fallback=fallback,
        digest=_digest(payload),
    )


def _index_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP_META}">
  <link rel="icon" type="image/png" href="favicon.png">
  <title>LLM Wiki Internal Product</title>
  <link rel="stylesheet" href="styles.css">
  <script src="vendor/graphology.umd.min.js"></script>
  <script src="vendor/sigma.min.js"></script>
  <script src="graph-explorer.js"></script>
  <script type="module" src="app.js"></script>
</head>
<body>
  <a class="skip-link" href="#app-main">Skip to content</a>
  <div
    class="app-shell"
    data-release-id="{CANONICAL_RELEASE_ID}"
    data-manifest-sha="{CANONICAL_MANIFEST_SHA256}"
  >
    <aside class="sidebar" aria-label="Product navigation">
      <div class="brand-block">
        <p class="eyebrow">Authenticated internal</p>
        <h1>LLM Wiki</h1>
        <p class="release">Release {CANONICAL_RELEASE_ID}</p>
      </div>
      <nav class="primary-nav" aria-label="M24 surfaces">
        <a href="#/overview" data-route-link="overview">Overview</a>
        <a href="#/wiki?concept=concepts/harness" data-route-link="wiki">Concept Wiki</a>
        <a href="#/search" data-route-link="search">Lexical Search</a>
        <a href="#/graph" data-route-link="graph">Graph Explorer</a>
        <a href="#/sources" data-route-link="sources">Sources</a>
        <a href="#/release" data-route-link="release">Release</a>
        <a href="#/obsidian" data-route-link="obsidian">Obsidian</a>
        <a href="#/acceptance" data-route-link="acceptance">Acceptance</a>
      </nav>
      <section class="boundary-panel" aria-label="Authority boundary">
        <h2>Boundary</h2>
        <p>Read-only internal product. Production retrieval remains lexical.</p>
      </section>
    </aside>
    <main id="app-main" class="workspace" tabindex="-1">
      <header class="workspace-header">
        <div>
          <p class="eyebrow">M24 internal product candidate</p>
          <h2 id="route-title">Loading</h2>
        </div>
        <dl class="identity-strip" aria-label="Release identity">
          <div>
            <dt>Release</dt>
            <dd id="release-id">{CANONICAL_RELEASE_ID}</dd>
          </div>
          <div>
            <dt>Manifest</dt>
            <dd id="manifest-sha">{CANONICAL_MANIFEST_SHA256}</dd>
          </div>
          <div>
            <dt>Retrieval</dt>
            <dd>lexical</dd>
          </div>
        </dl>
      </header>
      <section id="app-status" class="status-banner" role="status" aria-live="polite">
        Loading canonical artifacts.
      </section>
      <section id="app" class="surface-region" aria-label="Selected product surface"></section>
    </main>
  </div>
  <noscript>
    <main class="noscript">
      <h1>LLM Wiki requires JavaScript</h1>
      <p>This internal product shell uses same-origin canonical JSON artifacts and
      does not load runtime CDN dependencies.</p>
    </main>
  </noscript>
</body>
</html>
"""


def _styles() -> str:
    return """html {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: #f6f7f9;
  color: #17202a;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

a {
  color: inherit;
}

.skip-link {
  background: #ffffff;
  border: 1px solid #1f6feb;
  left: 12px;
  padding: 8px 10px;
  position: fixed;
  top: -48px;
  z-index: 20;
}

.skip-link:focus {
  top: 12px;
}

.app-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  background: #111827;
  color: #f9fafb;
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-height: 100vh;
  padding: 24px;
}

.brand-block h1 {
  font-size: 30px;
  line-height: 1.1;
  margin: 4px 0 10px;
}

.eyebrow,
.release {
  color: #a7b0bf;
  margin: 0;
}

.primary-nav {
  display: grid;
  gap: 6px;
}

.primary-nav a {
  border-left: 3px solid transparent;
  color: #d1d5db;
  padding: 9px 10px;
  text-decoration: none;
}

.primary-nav a[aria-current="page"],
.primary-nav a:focus,
.primary-nav a:hover {
  background: #1f2937;
  border-left-color: #5eead4;
  color: #ffffff;
}

.boundary-panel {
  border-top: 1px solid #374151;
  color: #d1d5db;
  margin-top: auto;
  padding-top: 18px;
}

.boundary-panel h2 {
  color: #ffffff;
  font-size: 14px;
  margin: 0 0 8px;
}

.boundary-panel p {
  margin: 0;
  line-height: 1.5;
}

.workspace {
  min-width: 0;
  padding: 28px;
}

.workspace-header {
  align-items: start;
  display: grid;
  gap: 20px;
  grid-template-columns: minmax(220px, 1fr) minmax(320px, 620px);
  margin-bottom: 18px;
}

.workspace-header h2 {
  font-size: 28px;
  margin: 4px 0 0;
}

.identity-strip {
  background: #ffffff;
  border: 1px solid #d6dae1;
  display: grid;
  gap: 0;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.identity-strip div {
  border-right: 1px solid #e5e7eb;
  min-width: 0;
  padding: 10px 12px;
}

.identity-strip div:last-child {
  border-right: 0;
}

.identity-strip dt {
  color: #5b6472;
  font-size: 12px;
  margin-bottom: 4px;
}

.identity-strip dd {
  font-size: 13px;
  margin: 0;
  overflow-wrap: anywhere;
}

.status-banner {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #7c2d12;
  margin-bottom: 18px;
  padding: 10px 12px;
}

.status-banner[data-state="ready"] {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #064e3b;
}

.status-banner[data-state="blocked"] {
  background: #fef2f2;
  border-color: #fecaca;
  color: #7f1d1d;
}

.surface-region {
  display: grid;
  gap: 16px;
}

.toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.toolbar input,
.toolbar select {
  border: 1px solid #cbd5e1;
  font: inherit;
  min-height: 36px;
  padding: 7px 9px;
}

.toolbar button,
.download-link {
  background: #14532d;
  border: 1px solid #14532d;
  color: #ffffff;
  cursor: pointer;
  font: inherit;
  min-height: 36px;
  padding: 7px 10px;
  text-decoration: none;
}

.metric-grid,
.item-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.panel,
.item-card,
.state-panel {
  background: #ffffff;
  border: 1px solid #d6dae1;
  padding: 14px;
}

.panel h3,
.item-card h3,
.state-panel h3 {
  font-size: 16px;
  margin: 0 0 8px;
}

.panel p,
.item-card p,
.state-panel p {
  line-height: 1.5;
  margin: 0 0 8px;
}

.item-card button,
.inline-action {
  background: #ffffff;
  border: 1px solid #94a3b8;
  cursor: pointer;
  font: inherit;
  min-height: 34px;
  padding: 6px 8px;
}

.pill-list,
.relationship-list,
.source-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
}

.pill-list li,
.relationship-list li,
.source-list li {
  background: #eef2f7;
  border: 1px solid #d6dae1;
  padding: 5px 7px;
}

.table-like {
  border: 1px solid #d6dae1;
  display: grid;
}

.table-row {
  display: grid;
  gap: 8px;
  grid-template-columns: 80px minmax(0, 1fr) 120px;
  padding: 9px 10px;
}

.table-row + .table-row {
  border-top: 1px solid #e5e7eb;
}

.surface-split {
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(0, 1fr) 340px;
  min-width: 0;
}

.source-split {
  grid-template-columns: minmax(0, 1fr) minmax(360px, 460px);
}

.section-list,
.citation-list,
.result-list {
  display: grid;
  gap: 10px;
}

.section-list article,
.citation-list article,
.result-list article {
  border: 1px solid #d6dae1;
  padding: 10px;
}

.source-card[aria-current="true"] {
  border-color: #0f766e;
  box-shadow: inset 4px 0 0 #0f766e;
}

.source-detail-panel {
  align-self: start;
  container: source-detail / inline-size;
  max-height: calc(100vh - 56px);
  min-width: 0;
  overflow: auto;
}

.source-detail-panel h3:focus {
  outline: 2px solid #0f766e;
  outline-offset: 3px;
}

.reader-meta {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(0, 1fr);
  margin: 12px 0;
  min-width: 0;
}

.reader-meta section,
.source-toc {
  border: 1px solid #e5e7eb;
  min-width: 0;
  overflow-wrap: anywhere;
  padding: 10px;
  word-break: break-word;
}

.reader-meta h4,
.source-toc h4 {
  margin: 0 0 6px;
}

.compact-meta.vertical {
  display: grid;
  min-width: 0;
}

.compact-meta.vertical > li {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.source-toc ol {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding-left: 22px;
}

.source-toc li[data-level="2"] {
  margin-left: 12px;
}

.source-toc li[data-level="3"],
.source-toc li[data-level="4"],
.source-toc li[data-level="5"],
.source-toc li[data-level="6"] {
  margin-left: 24px;
}

.source-document-body {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
  margin: 12px 0 0;
  max-height: 65vh;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.source-reader {
  min-width: 0;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.muted {
  color: #64748b;
}

.compact-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
}

.compact-meta li {
  color: #475569;
  font-size: 13px;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.graph-placeholder {
  background:
    linear-gradient(90deg, rgba(20, 83, 45, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(20, 83, 45, 0.08) 1px, transparent 1px);
  background-size: 22px 22px;
  min-height: 260px;
  position: relative;
}

.graph-placeholder svg {
  display: block;
  height: 260px;
  width: 100%;
}

.node-dot {
  fill: #0f766e;
}

.edge-line {
  stroke: #64748b;
  stroke-width: 1.4;
}

.graph-workbench {
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(0, 1fr) 320px;
}

.graph-toolbar {
  align-items: end;
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(180px, 1fr) minmax(140px, 220px) repeat(3, max-content);
}

.graph-toolbar label {
  display: grid;
  gap: 5px;
}

.graph-toolbar input,
.graph-toolbar select {
  border: 1px solid #b8c0cc;
  font: inherit;
  min-height: 34px;
  padding: 6px 8px;
}

.graph-toolbar button,
.graph-result-button {
  background: #ffffff;
  border: 1px solid #94a3b8;
  cursor: pointer;
  font: inherit;
  min-height: 34px;
  padding: 6px 8px;
}

.graph-stage {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  min-height: 430px;
  overflow: hidden;
  position: relative;
}

.graph-stage canvas {
  display: block;
}

.graph-stage[data-state="empty"]::after,
.graph-stage[data-state="unavailable"]::after {
  align-items: center;
  color: #475569;
  content: attr(data-message);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 18px;
  position: absolute;
  text-align: center;
}

.graph-side-panel {
  display: grid;
  gap: 12px;
}

.graph-result-list {
  display: grid;
  gap: 6px;
  max-height: 230px;
  overflow: auto;
}

.graph-result-button {
  text-align: left;
}

.graph-result-button[aria-current="true"] {
  border-color: #0f766e;
  box-shadow: inset 3px 0 0 #0f766e;
}

.graph-details dl {
  display: grid;
  gap: 6px;
  margin: 0;
}

.graph-details div {
  border-top: 1px solid #e5e7eb;
  display: grid;
  gap: 4px;
  padding-top: 6px;
}

.graph-details dt {
  color: #64748b;
  font-size: 12px;
  text-transform: uppercase;
}

.graph-details dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.noscript {
  margin: 40px auto;
  max-width: 720px;
  padding: 0 20px;
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    min-height: auto;
  }

  .workspace-header {
    grid-template-columns: 1fr;
  }

  .graph-workbench {
    grid-template-columns: 1fr;
  }

  .surface-split {
    grid-template-columns: 1fr;
  }

  .source-detail-panel {
    max-height: none;
  }

  .reader-meta {
    grid-template-columns: 1fr;
  }

  .graph-toolbar {
    grid-template-columns: 1fr 1fr;
  }

  .identity-strip,
  .table-row {
    grid-template-columns: 1fr;
  }

  .identity-strip div {
    border-bottom: 1px solid #e5e7eb;
    border-right: 0;
  }
}
"""


def _graph_explorer_js() -> str:
    return """(function () {
  "use strict";

  const NODE_COLORS = {
    architecture: "#0f766e",
    component: "#1d4ed8",
    concept: "#0f766e",
    contract: "#7c3aed",
    decision: "#b45309",
    process: "#be123c",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function normalize(value) {
    return String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase("en-US");
  }

  function stableHash(value) {
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function positionFor(nodeId, index, count) {
    const phase = (stableHash(nodeId) / 0xffffffff) * Math.PI * 2;
    const angle = phase + (index / Math.max(count, 1)) * Math.PI * 2;
    const radius = 5 + (stableHash(`${nodeId}:radius`) % 1000) / 140;
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
  }

  function nodeIdOf(node) {
    return node.concept_id || node.id || node.node_id;
  }

  function nodeTitle(node) {
    return node.title || node.label || nodeIdOf(node);
  }

  function stringList(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
  }

  function buildGraphologyGraph(payload) {
    const Graphology = window.graphology;
    if (typeof Graphology !== "function") {
      throw new Error("graphology browser runtime unavailable");
    }
    const graph = new Graphology({ allowSelfLoops: false, multi: true, type: "mixed" });
    const nodes = [...(payload.nodes || [])].sort((left, right) =>
      nodeIdOf(left).localeCompare(nodeIdOf(right)),
    );
    nodes.forEach((node, index) => {
      const nodeId = nodeIdOf(node);
      const position = positionFor(nodeId, index, nodes.length);
      const semanticType = node.type || node.concept_type || "concept";
      const semanticTypeKey = normalize(semanticType || "concept");
      graph.addNode(nodeId, {
        ...node,
        color: NODE_COLORS[semanticTypeKey] || "#64748b",
        label: nodeTitle(node),
        semanticType,
        semanticTypeKey,
        size: node.focus_node ? 9 : 6,
        title: nodeTitle(node),
        type: "circle",
        x: position.x,
        y: position.y,
      });
    });
    for (const edge of [...(payload.edges || [])].sort((left, right) =>
      left.edge_id.localeCompare(right.edge_id),
    )) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const attrs = {
        ...edge,
        color: edge.focus_edge ? "#0f766e" : "#94a3b8",
        label: edge.relation_type || "related",
        relationType: edge.relation_type || "related",
        size: edge.focus_edge ? 2 : 1,
      };
      if (edge.directed === false) {
        graph.addUndirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attrs);
      } else {
        graph.addDirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, attrs);
      }
    }
    graph.setAttribute("readOnly", true);
    graph.setAttribute("releaseId", payload.release_id);
    return graph;
  }

  function selection(graph, nodeId, sourceCountsByConcept) {
    const attrs = graph.getNodeAttributes(nodeId);
    return {
      id: nodeId,
      title: attrs.title || nodeId,
      type: attrs.semanticType || "concept",
      description: attrs.description || attrs.summary || "",
      sourcePath: attrs.source_path || attrs.path || "",
      sourceCount: Number(sourceCountsByConcept?.[nodeId] || 0),
      tags: stringList(attrs.tags),
    };
  }

  function searchMatches(graph, query) {
    const normalizedQuery = normalize(query);
    if (!normalizedQuery) return [];
    return graph
      .nodes()
      .map((nodeId) => {
        const attrs = graph.getNodeAttributes(nodeId);
        const title = normalize(attrs.title || nodeId);
        const aliases = stringList(attrs.aliases).map(normalize);
        const tags = stringList(attrs.tags).map(normalize);
        const description = normalize(attrs.description || attrs.summary || "");
        let score = null;
        if (title === normalizedQuery) score = 0;
        else if (aliases.includes(normalizedQuery)) score = 1;
        else if (title.startsWith(normalizedQuery)) score = 2;
        else if (aliases.some((alias) => alias.startsWith(normalizedQuery))) score = 3;
        else if (title.includes(normalizedQuery)) score = 4;
        else if (aliases.some((alias) => alias.includes(normalizedQuery))) score = 5;
        else if (tags.some((tag) => tag.includes(normalizedQuery))) score = 6;
        else if (description.includes(normalizedQuery)) score = 7;
        else if (normalize(nodeId).includes(normalizedQuery)) score = 8;
        return score === null ? null : { id: nodeId, score, title: attrs.title || nodeId };
      })
      .filter(Boolean)
      .sort((left, right) => left.score - right.score || left.id.localeCompare(right.id))
      .slice(0, 20);
  }

  function relationTypes(payload) {
    return [
      ...new Set((payload.edges || []).map((edge) => edge.relation_type || "related")),
    ].sort();
  }

  window.createM24GraphExplorer = function createM24GraphExplorer(options) {
    const root = options.root;
    const stage = root.querySelector("[data-sigma-stage]");
    const details = root.querySelector("[data-graph-details]");
    const results = root.querySelector("[data-graph-results]");
    const search = root.querySelector("[data-graph-search]");
    const relation = root.querySelector("[data-graph-relation]");
    const reset = root.querySelector("[data-graph-reset]");
    const clear = root.querySelector("[data-graph-clear]");
    const oneHop = root.querySelector("[data-graph-neighbor='1']");
    const twoHop = root.querySelector("[data-graph-neighbor='2']");
    const showOrphans = root.querySelector("[data-graph-orphans]");
    const Sigma = window.Sigma;
    if (typeof Sigma !== "function") {
      throw new Error("Sigma.js browser runtime unavailable");
    }

    const graph = buildGraphologyGraph(options.payload);
    let selectedNodeId = graph.hasNode(options.selectedNodeId) ? options.selectedNodeId : null;
    let focusDepth = 0;
    let visibleNodes = new Set(graph.nodes());
    let visibleEdges = new Set(graph.edges());
    let searchResultIds = new Set();

    for (const type of relationTypes(options.payload)) {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type;
      relation.append(option);
    }

    function adjacentWithinDepth(nodeId, depth) {
      const seen = new Set([nodeId]);
      let frontier = [nodeId];
      for (let level = 0; level < depth; level += 1) {
        const next = [];
        for (const id of frontier) {
          for (const neighbor of graph.neighbors(id).sort()) {
            if (!seen.has(neighbor)) {
              seen.add(neighbor);
              next.push(neighbor);
            }
          }
        }
        frontier = next;
      }
      return seen;
    }

    function recompute() {
      const relationFilter = relation.value;
      let nodes = new Set(graph.nodes());
      let edges = graph.edges().filter((edgeId) => {
        if (!relationFilter) return true;
        return graph.getEdgeAttribute(edgeId, "relationType") === relationFilter;
      });
      if (selectedNodeId && focusDepth > 0) {
        nodes = adjacentWithinDepth(selectedNodeId, focusDepth);
        edges = edges.filter((edgeId) =>
          nodes.has(graph.source(edgeId)) && nodes.has(graph.target(edgeId)),
        );
      }
      if (!showOrphans.checked) {
        const connected = new Set();
        for (const edgeId of edges) {
          connected.add(graph.source(edgeId));
          connected.add(graph.target(edgeId));
        }
        if (selectedNodeId) connected.add(selectedNodeId);
        nodes = new Set([...nodes].filter((nodeId) => connected.has(nodeId)));
        edges = edges.filter((edgeId) =>
          nodes.has(graph.source(edgeId)) && nodes.has(graph.target(edgeId)),
        );
      }
      visibleNodes = nodes;
      visibleEdges = new Set(edges);
      const matches = searchMatches(graph, search.value).filter((match) => nodes.has(match.id));
      searchResultIds = new Set(matches.map((match) => match.id));
      renderResults(matches);
      renderDetails();
      stage.dataset.state = nodes.size === 0 ? "empty" : "ready";
      stage.dataset.message = nodes.size === 0 ? "No graph nodes match the current filters." : "";
      renderer.refresh();
      options.onStatus?.(
        `Sigma.js canvas ready: ${nodes.size} visible nodes, ${edges.length} visible edges.`,
      );
    }

    function renderResults(matches) {
      if (!search.value.trim()) {
        results.innerHTML = "<p>Search graph nodes by title, aliases, tags, or source path.</p>";
        return;
      }
      if (matches.length === 0) {
        results.innerHTML = '<p data-state="no-match">No matching graph nodes.</p>';
        return;
      }
      results.innerHTML = matches
        .map((match) => `
          <button
            class="graph-result-button"
            data-node-id="${escapeHtml(match.id)}"
            aria-current="${match.id === selectedNodeId ? "true" : "false"}"
          >${escapeHtml(match.title)}</button>
        `)
        .join("");
      for (const button of results.querySelectorAll("[data-node-id]")) {
        button.addEventListener("click", () => selectNode(button.dataset.nodeId));
      }
    }

    function renderDetails() {
      if (!selectedNodeId) {
        details.innerHTML = "<p>Select a node to inspect provenance and relationships.</p>";
        return;
      }
      const selected = selection(graph, selectedNodeId, options.sourceCountsByConcept || {});
      const neighbors = graph.neighbors(selectedNodeId).sort();
      details.innerHTML = `
        <div class="detail-actions graph-selection-actions">
          <button
            class="inline-action"
            type="button"
            data-graph-open-wiki="${escapeHtml(selected.id)}"
          >Open Wiki</button>
          ${selected.sourceCount > 0 ? `
            <button
              class="inline-action"
              type="button"
              data-graph-view-sources="${escapeHtml(selected.id)}"
            >View sources</button>
          ` : ""}
          <button
            class="inline-action"
            type="button"
            data-graph-copy-concept="${escapeHtml(selected.id)}"
          >Copy concept ID</button>
        </div>
        <dl>
          <div><dt>Title</dt><dd>${escapeHtml(selected.title)}</dd></div>
          <div><dt>Type</dt><dd>${escapeHtml(selected.type)}</dd></div>
          <div>
            <dt>Source</dt>
            <dd>${escapeHtml(selected.sourcePath || "release artifact")}</dd>
          </div>
          <div><dt>Tags</dt><dd>${escapeHtml(selected.tags.join(", ") || "none")}</dd></div>
          <div><dt>Neighbors</dt><dd>${escapeHtml(neighbors.length)}</dd></div>
          <div><dt>Source handoffs</dt><dd>${escapeHtml(selected.sourceCount)}</dd></div>
          <div>
            <dt>Description</dt>
            <dd>${escapeHtml(selected.description || "No description")}</dd>
          </div>
        </dl>
      `;
      const wikiButton = details.querySelector("[data-graph-open-wiki]");
      if (wikiButton) {
        wikiButton.addEventListener("click", () => options.onOpenWiki?.(selected));
      }
      const sourcesButton = details.querySelector("[data-graph-view-sources]");
      if (sourcesButton) {
        sourcesButton.addEventListener("click", () => options.onViewSources?.(selected));
      }
      const copyButton = details.querySelector("[data-graph-copy-concept]");
      if (copyButton) {
        copyButton.addEventListener("click", async () => {
          try {
            await navigator.clipboard?.writeText(selected.id);
            options.onStatus?.(`Copied ${selected.id}.`);
          } catch (_error) {
            options.onStatus?.(selected.id);
          }
        });
      }
      options.onSelection?.(selected);
    }

    function selectNode(nodeId) {
      if (!graph.hasNode(nodeId)) return;
      selectedNodeId = nodeId;
      focusDepth = Math.max(focusDepth, 0);
      recompute();
    }

    const renderer = new Sigma(graph, stage, {
      allowInvalidContainer: false,
      defaultEdgeColor: "#94a3b8",
      defaultNodeColor: "#64748b",
      edgeReducer: (edgeId, data) =>
        visibleEdges.has(edgeId) ? data : { ...data, hidden: true },
      enableEdgeEvents: true,
      hideEdgesOnMove: true,
      hideLabelsOnMove: true,
      labelDensity: 0.08,
      labelRenderedSizeThreshold: 8,
      nodeReducer: (nodeId, data) => {
        if (!visibleNodes.has(nodeId)) return { ...data, hidden: true };
        if (nodeId === selectedNodeId) {
          return {
            ...data,
            color: "#0f766e",
            forceLabel: true,
            highlighted: true,
            size: 10,
            zIndex: 2,
          };
        }
        if (searchResultIds.has(nodeId)) {
          return { ...data, forceLabel: true, highlighted: true, size: 8, zIndex: 1 };
        }
        return data;
      },
      renderLabels: true,
      zIndex: true,
    });

    renderer.on("clickNode", ({ node }) => selectNode(node));
    renderer.on("clickStage", () => {
      selectedNodeId = null;
      focusDepth = 0;
      recompute();
    });
    search.addEventListener("input", recompute);
    relation.addEventListener("change", recompute);
    showOrphans.addEventListener("change", recompute);
    reset.addEventListener("click", () => renderer.getCamera().animatedReset({ duration: 200 }));
    clear.addEventListener("click", () => {
      selectedNodeId = null;
      focusDepth = 0;
      search.value = "";
      relation.value = "";
      showOrphans.checked = true;
      recompute();
    });
    oneHop.addEventListener("click", () => {
      if (selectedNodeId) {
        focusDepth = 1;
        recompute();
      }
    });
    twoHop.addEventListener("click", () => {
      if (selectedNodeId) {
        focusDepth = 2;
        recompute();
      }
    });

    if (selectedNodeId) focusDepth = 1;
    recompute();
    return {
      destroy() {
        renderer.kill();
      },
    };
  };
})();
"""


def _app_js() -> str:
    return f"""const EXPECTED_RELEASE = "{CANONICAL_RELEASE_ID}";
const EXPECTED_MANIFEST = "{CANONICAL_MANIFEST_SHA256}";
const HARNESS_CONCEPT_ID = "concepts/harness";

const ARTIFACTS = {{
  release: "data/release-viewer.json",
  concept: "data/concept-wiki-harness.json",
  search: "data/search-harness.json",
  graph: "data/graph-navigation.json",
  sources: "data/source-viewers.json",
  sourceIndex: "data/source-index.json",
  sourceDocuments: "data/source-documents.json",
  answers: "data/query-answer-acceptance.json",
  obsidian: "data/obsidian-export-manifest.json",
  acceptance: "data/m24-14-6-pending-acceptance.json",
}};

const ROUTES = {{
  overview: "Overview",
  wiki: "Concept Wiki",
  search: "Lexical Search",
  graph: "Graph Explorer",
  sources: "Sources",
  release: "Release Details",
  obsidian: "Obsidian Export",
  acceptance: "Acceptance Status",
}};

const state = {{
  artifacts: null,
  graphExplorer: null,
  route: "overview",
  selectedConceptId: HARNESS_CONCEPT_ID,
  selectedCitationId: null,
  selectedSourceViewerId: null,
  sourceDetailFocusRequested: false,
  searchQuery: "harness",
  sourceQuery: "",
}};

const app = document.querySelector("#app");
const statusBanner = document.querySelector("#app-status");
const title = document.querySelector("#route-title");

function escapeHtml(value) {{
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}}

function setStatus(message, mode = "ready") {{
  statusBanner.textContent = message;
  statusBanner.dataset.state = mode;
}}

function boundedError(titleText, message) {{
  title.textContent = titleText;
  setStatus(message, "blocked");
  app.innerHTML = `
    <section class="state-panel" data-state="bounded-error">
      <h3>${{escapeHtml(titleText)}}</h3>
      <p>${{escapeHtml(message)}}</p>
    </section>
  `;
}}

async function loadJson(path) {{
  const response = await fetch(path, {{ cache: "no-store" }});
  if (!response.ok) {{
    throw new Error(`artifact unavailable: ${{path}}`);
  }}
  return response.json();
}}

function releaseOf(payload) {{
  return payload && typeof payload === "object" ? payload.release_id : null;
}}

function validateIdentity(artifacts) {{
  const mismatches = Object.entries(artifacts)
    .filter(([name, payload]) => name !== "answers")
    .filter(([, payload]) => releaseOf(payload) !== EXPECTED_RELEASE)
    .map(([name]) => name);
  if (artifacts.release.manifest_sha256 !== EXPECTED_MANIFEST) {{
    mismatches.push("release manifest");
  }}
  if (mismatches.length) {{
    throw new Error(`release identity mismatch: ${{mismatches.join(", ")}}`);
  }}
  if (artifacts.release.production_retrieval !== "lexical") {{
    throw new Error("production retrieval boundary mismatch");
  }}
  if (
    artifacts.release.semantic_serving_enabled ||
    artifacts.release.hybrid_retrieval_enabled
  ) {{
    throw new Error("semantic or hybrid serving is not authorized");
  }}
}}

async function loadArtifacts() {{
  setStatus("Loading canonical artifacts.", "loading");
  const entries = await Promise.all(
    Object.entries(ARTIFACTS).map(async ([key, path]) => [key, await loadJson(path)])
  );
  const artifacts = Object.fromEntries(entries);
  validateIdentity(artifacts);
  return artifacts;
}}

function routeFromHash() {{
  return (location.hash.replace(/^#\\/?/, "") || "overview").split("?")[0];
}}

function routeSearchParams() {{
  return new URLSearchParams(location.hash.split("?")[1] || "");
}}

function applyRouteStateFromHash(route) {{
  const params = routeSearchParams();
  if (route === "wiki") {{
    state.selectedConceptId = params.get("concept") || HARNESS_CONCEPT_ID;
  }}
  if (route === "graph" && params.get("concept")) {{
    state.selectedConceptId = params.get("concept");
  }}
  if (route === "sources") {{
    state.selectedSourceViewerId = params.has("viewer") ? params.get("viewer") : null;
    state.selectedCitationId = params.has("citation") ? params.get("citation") : null;
  }}
}}

function setActiveRoute(route) {{
  for (const link of document.querySelectorAll("[data-route-link]")) {{
    link.toggleAttribute("aria-current", link.dataset.routeLink === route);
  }}
}}

function metric(label, value) {{
  return `
    <section class="panel">
      <h3>${{escapeHtml(label)}}</h3>
      <p>${{escapeHtml(value)}}</p>
    </section>
  `;
}}

function sourceViewers(artifacts) {{
  return artifacts.sources.source_viewers || [];
}}

function sourceCoverageRows(artifacts) {{
  return artifacts.sourceIndex.coverage_matrix || artifacts.sources.coverage_matrix || [];
}}

function sourceDocuments(artifacts) {{
  return (artifacts.sourceDocuments && artifacts.sourceDocuments.documents) || {{}};
}}

function allSourceCards(artifacts) {{
  const searchCards = artifacts.search.source_cards || [];
  const viewerCards = sourceViewers(artifacts).map((viewer) => viewer.source_card || {{}});
  const byId = new Map();
  for (const card of [...searchCards, ...viewerCards]) {{
    if (card.source_card_id) byId.set(card.source_card_id, card);
  }}
  return [...byId.values()];
}}

function viewerById(artifacts, viewerId) {{
  const viewers = sourceViewers(artifacts);
  return viewers.find((viewer) => viewer.viewer_id === viewerId) || viewers[0] || null;
}}

function viewerBySourceCard(artifacts, sourceCardId) {{
  return sourceViewers(artifacts).find(
    (viewer) => (viewer.source_card || {{}}).source_card_id === sourceCardId
  ) || null;
}}

function viewerBySourceId(artifacts, sourceId) {{
  return sourceViewers(artifacts).find(
    (viewer) => (viewer.source_card || {{}}).source_id === sourceId
  ) || null;
}}

function firstViewerForConcept(artifacts, conceptId) {{
  return sourceViewers(artifacts).find((viewer) =>
    (((viewer.source_card || {{}}).concept_ids || []).includes(conceptId))
  ) || null;
}}

function sourceCountsByConcept(artifacts) {{
  const counts = {{}};
  for (const viewer of sourceViewers(artifacts)) {{
    for (const conceptId of ((viewer.source_card || {{}}).concept_ids || [])) {{
      counts[conceptId] = (counts[conceptId] || 0) + 1;
    }}
  }}
  return counts;
}}

function citationById(artifacts, citationId) {{
  for (const viewer of sourceViewers(artifacts)) {{
    const citation = (viewer.citations || []).find((item) => item.citation_id === citationId);
    if (citation) return {{ viewer, citation }};
  }}
  return null;
}}

function filteredSearchResults(artifacts) {{
  const query = state.searchQuery.trim().toLocaleLowerCase("en-US");
  const results = artifacts.search.results || [];
  if (!query) return results;
  return results.filter((item) => [
    item.title,
    item.section_title,
    item.concept_id,
    item.excerpt,
    (item.source_kinds || []).join(" "),
  ].join(" ").toLocaleLowerCase("en-US").includes(query));
}}

function renderOverview(artifacts) {{
  const counts = artifacts.release.counts || {{}};
  const graphEdges = Array.isArray(artifacts.graph.edges) ? artifacts.graph.edges.length : 0;
  return `
    <div class="metric-grid">
      ${{metric("Concepts", counts.concepts)}}
      ${{metric("Graph edges", graphEdges)}}
      ${{metric("Source snapshots", counts.source_snapshots)}}
      ${{metric("Retrieval", artifacts.release.production_retrieval)}}
    </div>
    <section class="panel">
      <h3>Internal product status</h3>
      <p>This app shell loads same-origin canonical artifacts and validates the
      release identity before rendering product surfaces.</p>
      <ul class="pill-list">
        <li>read-only</li>
        <li>lexical retrieval</li>
        <li>Cloudflare Access required</li>
        <li>no runtime CDN</li>
      </ul>
    </section>
  `;
}}

function graphNodeByConceptId(artifacts, conceptId) {{
  return (artifacts.graph.nodes || []).find((node) =>
    (node.concept_id || node.id || node.node_id) === conceptId
  ) || null;
}}

function graphRelationshipsForConcept(artifacts, conceptId) {{
  const nodesById = new Map((artifacts.graph.nodes || []).map((node) => [
    node.concept_id || node.id || node.node_id,
    node,
  ]));
  return (artifacts.graph.edges || [])
    .filter((edge) => edge.source === conceptId || edge.target === conceptId)
    .map((edge) => {{
      const neighborId = edge.source === conceptId ? edge.target : edge.source;
      const neighbor = nodesById.get(neighborId) || {{}};
      return {{
        neighborId,
        neighborTitle: neighbor.title || neighbor.label || neighborId,
        relationType: edge.relation_type || "related",
        direction: edge.source === conceptId ? "outbound" : "inbound",
      }};
    }})
    .sort((left, right) =>
      left.relationType.localeCompare(right.relationType) ||
      left.neighborTitle.localeCompare(right.neighborTitle)
    );
}}

function lexicalResultsForConcept(artifacts, conceptId) {{
  return (artifacts.search.results || [])
    .filter((item) => item.concept_id === conceptId)
    .sort((left, right) => (left.rank || 0) - (right.rank || 0));
}}

function sourceCardsForConcept(artifacts, conceptId) {{
  return allSourceCards(artifacts)
    .filter((card) => (card.concept_ids || []).includes(conceptId))
    .sort((left, right) =>
      (left.title || left.source_id || "").localeCompare(right.title || right.source_id || "")
    );
}}

function renderBoundedConceptSummary(artifacts, conceptId) {{
  const node = graphNodeByConceptId(artifacts, conceptId);
  if (!node) {{
    return `
      <section class="state-panel" data-state="concept-not-found">
        <h3>Concept not found in this release</h3>
        <p>This concept ID is not present in the release-pinned graph artifact.</p>
        <div class="detail-actions">
          <button class="inline-action" data-open-concept="${{escapeHtml(HARNESS_CONCEPT_ID)}}">
            Return to loaded concept
          </button>
          <button class="inline-action" data-route="graph">Open graph explorer</button>
        </div>
      </section>
    `;
  }}
  const relationships = graphRelationshipsForConcept(artifacts, conceptId);
  const lexicalResults = lexicalResultsForConcept(artifacts, conceptId);
  const sourceCards = sourceCardsForConcept(artifacts, conceptId);
  return `
    <section class="panel" data-state="bounded-graph-concept-summary">
      <h3>${{escapeHtml(node.title || node.label || conceptId)}}</h3>
      <p>
        ${{escapeHtml(node.description || node.summary || "No graph description is available.")}}
      </p>
      <p class="muted">
        Bounded graph-derived summary. A full detailed Concept Wiki artifact is not available for
        this concept in the release-pinned internal package.
      </p>
      <ul class="pill-list">
        <li>${{escapeHtml(conceptId)}}</li>
        <li>${{escapeHtml(node.type || node.concept_type || "Concept")}}</li>
        <li>${{escapeHtml(relationships.length)}} relationships</li>
        <li>${{escapeHtml(sourceCards.length)}} source handoffs</li>
      </ul>
      <div class="detail-actions">
        <button class="inline-action" data-focus-concept="${{escapeHtml(conceptId)}}">
          Open in graph
        </button>
        <button class="inline-action" data-open-concept="${{escapeHtml(HARNESS_CONCEPT_ID)}}">
          Return to loaded concept
        </button>
      </div>
    </section>
    <section class="panel">
      <h3>Graph relationships</h3>
      <ul class="relationship-list">
        ${{relationships.slice(0, 8).map((edge) => `
          <li>
            <button class="inline-action" data-focus-concept="${{escapeHtml(edge.neighborId)}}">
              ${{escapeHtml(edge.direction)}} ${{escapeHtml(edge.relationType)}}:
              ${{escapeHtml(edge.neighborTitle)}}
            </button>
          </li>
        `).join("") || "<li>No graph relationships are available for this concept.</li>"}}
      </ul>
    </section>
    <section class="panel">
      <h3>Lexical evidence in this release</h3>
      <div class="result-list">
        ${{lexicalResults.slice(0, 5).map((item) => `
          <article>
            <h4>#${{escapeHtml(item.rank)}} ${{escapeHtml(item.title || item.section_title)}}</h4>
            <p>${{escapeHtml(item.excerpt || "No excerpt available.")}}</p>
            <ul class="compact-meta">
              <li>${{escapeHtml(item.section_id || "section unavailable")}}</li>
              <li>score ${{escapeHtml(item.score)}}</li>
            </ul>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="bounded-summary-no-lexical-match">
            <h3>No lexical sections</h3>
            <p>The release-pinned lexical artifact has no matching section for this concept.</p>
          </section>
        `}}
      </div>
    </section>
    <section class="panel">
      <h3>Source handoffs</h3>
      <div class="source-list">
        ${{sourceCards.slice(0, 6).map((card) => `
          <button
            class="inline-action"
            data-open-source-card="${{escapeHtml(card.source_card_id)}}"
          >
            ${{escapeHtml(card.title || card.display_host || card.source_id)}}
          </button>
        `).join("") || "<p class='muted'>No source handoff is available for this concept.</p>"}}
      </div>
    </section>
  `;
}}

function renderWiki(artifacts) {{
  const concept = artifacts.concept;
  if (state.selectedConceptId !== concept.concept_id) {{
    return renderBoundedConceptSummary(artifacts, state.selectedConceptId);
  }}
  const relationships = concept.relationships || [];
  const sections = concept.sections || [];
  const viewers = concept.source_viewers || [];
  return `
    <div class="surface-split">
      <section class="panel">
        <h3>${{escapeHtml(concept.title)}}</h3>
        <p>${{escapeHtml(concept.description)}}</p>
        <ul class="pill-list">
          <li>${{escapeHtml(concept.concept_id)}}</li>
          <li>release ${{escapeHtml(concept.release_id)}}</li>
          <li>${{escapeHtml(sections.length)}} sections</li>
          <li>${{escapeHtml(relationships.length)}} relationships</li>
        </ul>
        <div class="detail-actions">
          <button class="inline-action" data-focus-concept="${{escapeHtml(concept.concept_id)}}">
            Open in graph
          </button>
          <button class="inline-action" data-route="search">Inspect lexical results</button>
        </div>
      </section>
      <aside class="panel">
        <h3>Source handoff</h3>
        <div class="source-list">
          ${{viewers.map((viewer) => {{
            const card = viewer.source_card || {{}};
            const resolvedViewer = viewerBySourceId(state.artifacts, card.source_id) || viewer;
            return `
              <button
                class="inline-action"
                data-open-source-viewer="${{escapeHtml(resolvedViewer.viewer_id)}}"
              >
                ${{escapeHtml(card.title || card.source_id || viewer.viewer_id)}}
              </button>
            `;
          }}).join("") || "<p class='muted'>No source viewers available.</p>"}}
        </div>
      </aside>
    </div>
    <section class="panel">
      <h3>Sections</h3>
      <div class="section-list">
        ${{sections.map((section) => `
          <article>
            <h4>${{escapeHtml(section.title || section.section_id)}}</h4>
            <p>${{escapeHtml(section.excerpt)}}</p>
            <ul class="compact-meta">
              <li>rank ${{escapeHtml(section.rank)}}</li>
              <li>score ${{escapeHtml(section.score)}}</li>
              <li>${{escapeHtml((section.source_card_ids || []).length)}} sources</li>
            </ul>
            <div class="detail-actions">
              ${{(section.source_viewer_ids || []).map((viewerId) => `
                <button
                  class="inline-action"
                  data-open-source-viewer="${{escapeHtml(viewerId)}}"
                >Source</button>
              `).join("")}}
            </div>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="concept-section-empty">
            <h3>No sections</h3>
            <p>This concept has no release-pinned sections.</p>
          </section>
        `}}
      </div>
    </section>
    <section class="panel">
      <h3>Typed relationships</h3>
      <ul class="relationship-list">
        ${{relationships.map((edge) => `
          <li>
            <button
              class="inline-action"
              data-focus-concept="${{escapeHtml(edge.neighbor_concept_id)}}"
            >
              ${{escapeHtml(edge.direction)}} ${{escapeHtml(edge.relation_type)}}:
              ${{escapeHtml(edge.neighbor_title)}}
            </button>
          </li>
        `).join("") || "<li>No relationships in this release artifact.</li>"}}
      </ul>
    </section>
  `;
}}

function renderSearch(artifacts) {{
  const results = filteredSearchResults(artifacts);
  const allResults = artifacts.search.results || [];
  return `
    <form class="toolbar" data-search-form>
      <label for="search-input">Lexical query</label>
      <input
        id="search-input"
        name="q"
        value="${{escapeHtml(state.searchQuery)}}"
        autocomplete="off"
      >
      <button type="submit">Search</button>
    </form>
    <section class="panel">
      <h3>Release-pinned lexical results</h3>
      <p class="muted">
        Showing ${{escapeHtml(results.length)}} of ${{escapeHtml(allResults.length)}} results.
      </p>
      <div class="result-list" aria-label="Lexical search results">
        ${{results.map((item) => `
          <article>
            <h4>#${{escapeHtml(item.rank)}} ${{escapeHtml(item.title)}}</h4>
            <p>${{escapeHtml(item.excerpt)}}</p>
            <ul class="compact-meta">
              <li>${{escapeHtml(item.concept_id)}}</li>
              <li>${{escapeHtml(item.section_id)}}</li>
              <li>score ${{escapeHtml(item.score)}}</li>
              <li>${{escapeHtml((item.citation_ordinals || []).length)}} citations</li>
            </ul>
            <div class="detail-actions">
              <button
                class="inline-action"
                data-focus-concept="${{escapeHtml(item.concept_id)}}"
              >Open graph</button>
              <button
                class="inline-action"
                data-open-concept="${{escapeHtml(item.concept_id)}}"
              >Open wiki</button>
              ${{(item.source_card_ids || []).slice(0, 3).map((sourceCardId) => `
                <button
                  class="inline-action"
                  data-open-source-card="${{escapeHtml(sourceCardId)}}"
                >Source</button>
              `).join("")}}
            </div>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="no-match">
            <h3>No lexical matches</h3>
            <p>The release-pinned lexical result set has no matches for this query.</p>
          </section>
        `}}
      </div>
    </section>
    <section class="panel">
      <h3>Source cards</h3>
      <div class="source-list">
        ${{allSourceCards(artifacts).map((card) => `
          <button
            class="inline-action"
            data-open-source-card="${{escapeHtml(card.source_card_id)}}"
          >
            ${{escapeHtml(card.title || card.display_host || card.source_id)}}
          </button>
        `).join("")}}
      </div>
    </section>
  `;
}}

function renderSummary(summary) {{
  if (!summary || typeof summary !== "object") return "";
  return `
    <ul class="compact-meta">
      <li>${{escapeHtml(summary.coverage_status || "metadata")}}</li>
      <li>${{escapeHtml(summary.content_bytes || 0)}} bytes</li>
      <li>${{escapeHtml(summary.line_count || 0)}} lines</li>
      <li>${{escapeHtml(summary.citation_count || 0)}} citations</li>
    </ul>
  `;
}}

function renderSourceDocument(documentPayload) {{
  if (!documentPayload) {{
    return `
      <section class="state-panel" data-state="source-document-missing">
        <h3>Source document unavailable</h3>
        <p>No release-pinned document payload is available for this source.</p>
      </section>
    `;
  }}
  const doc = documentPayload.document || {{}};
  const integrity = documentPayload.integrity || {{}};
  const origin = documentPayload.origin || {{}};
  const registry = documentPayload.registry || {{}};
  const metadataOnlyReason = documentPayload.metadata_only_reason || doc.metadata_only_reason;
  const body = doc.body || "";
  const toc = documentPayload.toc || [];
  return `
    <section
      class="source-reader"
      data-source-document="${{escapeHtml(documentPayload.source_id)}}"
    >
      <div class="reader-meta">
        <section>
          <h4>Origin</h4>
          <ul class="compact-meta vertical">
            <li>${{escapeHtml(origin.repo || "unresolved")}}</li>
            <li>${{escapeHtml(origin.commit || "no exact commit")}}</li>
            <li>${{escapeHtml(origin.path || "no exact path")}}</li>
            <li>blob ${{escapeHtml(origin.blob_sha || "unavailable")}}</li>
          </ul>
        </section>
        <section>
          <h4>Integrity</h4>
          <ul class="compact-meta vertical">
            <li>snapshot ${{escapeHtml(integrity.snapshot_sha256 || "metadata-only")}}</li>
            <li>payload ${{escapeHtml(integrity.browser_payload_sha256 || "unavailable")}}</li>
            <li>registry ${{escapeHtml(registry.content_sha256 || "not declared")}}</li>
            <li>scope ${{escapeHtml(registry.content_hash_scope || "not declared")}}</li>
            <li>truncated ${{escapeHtml(String(Boolean(integrity.truncated)))}}</li>
          </ul>
        </section>
      </div>
      ${{toc.length ? `
        <section class="source-toc" aria-label="Document table of contents">
          <h4>Contents</h4>
          <ol>
            ${{toc.slice(0, 40).map((item) => `
              <li data-level="${{escapeHtml(item.level)}}">${{escapeHtml(item.title)}}</li>
            `).join("")}}
          </ol>
        </section>
      ` : ""}}
      ${{metadataOnlyReason ? `
        <section class="state-panel" data-state="metadata-only-source">
          <h3>Metadata-only source</h3>
          <p>${{escapeHtml(metadataOnlyReason)}}</p>
        </section>
      ` : `
        <pre class="source-document-body" tabindex="0"><code>${{escapeHtml(body)}}</code></pre>
      `}}
    </section>
  `;
}}

function renderSources(artifacts) {{
  const viewers = sourceViewers(artifacts);
  const selected = state.selectedCitationId
    ? (citationById(artifacts, state.selectedCitationId) || {{}}).viewer
    : viewerById(artifacts, state.selectedSourceViewerId);
  const activeViewer = selected || viewers[0] || null;
  const activeCard = activeViewer ? activeViewer.source_card || {{}} : {{}};
  const query = state.sourceQuery.trim().toLocaleLowerCase("en-US");
  const filtered = viewers.filter((viewer) => {{
    const card = viewer.source_card || {{}};
    const document = (
      viewer.document ||
      sourceDocuments(artifacts)[card.source_id] ||
      {{}}
    ).document || {{}};
    if (!query) return true;
    return [
      viewer.viewer_id,
      card.title,
      card.display_host,
      card.publisher,
      card.source_kind,
      card.source_id,
      (card.concept_ids || []).join(" "),
      document.body,
    ].join(" ").toLocaleLowerCase("en-US").includes(query);
  }});
  const activeCitation = state.selectedCitationId
    ? citationById(artifacts, state.selectedCitationId)
    : null;
  const activeDocument = activeViewer
    ? (activeViewer.document || sourceDocuments(artifacts)[activeCard.source_id])
    : null;
  const rows = sourceCoverageRows(artifacts);
  return `
    <form class="toolbar" data-source-form>
      <label for="source-input">Source filter</label>
      <input
        id="source-input"
        name="q"
        value="${{escapeHtml(state.sourceQuery)}}"
        autocomplete="off"
      >
      <button type="submit">Filter</button>
    </form>
    <div class="surface-split source-split">
      <section class="panel">
        <h3>Sources</h3>
        <p class="muted">
          Showing ${{escapeHtml(filtered.length)}} of ${{escapeHtml(rows.length)}}
          canonical source records.
        </p>
        <div class="result-list">
          ${{filtered.map((viewer) => {{
            const card = viewer.source_card || {{}};
            const isSelected = activeViewer && viewer.viewer_id === activeViewer.viewer_id;
            return `
              <article
                class="source-card"
                data-source-id="${{escapeHtml(card.source_id)}}"
                aria-current="${{isSelected ? "true" : "false"}}"
              >
                <h4>${{escapeHtml(card.title || card.source_id || viewer.viewer_id)}}</h4>
                <p>${{escapeHtml(card.display_host || card.publisher || "source")}}</p>
                <ul class="compact-meta">
                  <li>${{escapeHtml(card.source_kind)}}</li>
                  <li>${{escapeHtml((viewer.citations || []).length)}} citations</li>
                  <li>snapshot ${{escapeHtml(String(card.snapshot_available))}}</li>
                  <li>${{escapeHtml(card.content_bytes || 0)}} bytes</li>
                  <li>${{escapeHtml(card.coverage_status || "metadata")}}</li>
                </ul>
                <div class="detail-actions">
                  <button
                    class="inline-action"
                    data-open-source-viewer="${{escapeHtml(viewer.viewer_id)}}"
                  >${{isSelected ? "Inspect selected" : "Inspect"}}</button>
                  ${{(card.concept_ids || []).slice(0, 2).map((conceptId) => `
                    <button
                      class="inline-action"
                      data-open-concept="${{escapeHtml(conceptId)}}"
                    >Concept</button>
                  `).join("")}}
                </div>
              </article>
            `;
          }}).join("") || `
            <section class="state-panel" data-state="source-no-match">
              <h3>No source matches</h3>
              <p>No source viewer matches this filter.</p>
            </section>
          `}}
        </div>
      </section>
      <aside class="panel source-detail-panel" data-source-detail>
        <p class="eyebrow">Source detail</p>
        <h3 id="source-detail-heading" tabindex="-1">
          ${{escapeHtml(activeCard.title || "Source detail")}}
        </h3>
        ${{activeViewer ? `
          ${{renderSummary(activeViewer.summary)}}
          <ul class="compact-meta">
            <li>${{escapeHtml(activeCard.source_card_id)}}</li>
            <li>${{escapeHtml(activeCard.source_kind)}}</li>
            <li>${{escapeHtml(activeCard.display_host || activeCard.publisher)}}</li>
            <li>${{escapeHtml(activeCard.document_path || "document path unavailable")}}</li>
          </ul>
          <div class="detail-actions">
            ${{activeCard.uri ? `
              <a
                class="inline-action"
                href="${{escapeHtml(activeCard.uri)}}"
                rel="noreferrer"
              >Open original source</a>
            ` : ""}}
            ${{(activeCard.concept_ids || []).map((conceptId) => `
              <button
                class="inline-action"
                data-open-concept="${{escapeHtml(conceptId)}}"
              >${{escapeHtml(conceptId.replace("concepts/", ""))}}</button>
            `).join("")}}
          </div>
          ${{renderSourceDocument(activeDocument)}}
          <h4>Citations</h4>
          <div class="citation-list">
            ${{(activeViewer.citations || []).map((citation) => `
              <article data-citation-id="${{escapeHtml(citation.citation_id)}}">
                <h5>#${{escapeHtml(citation.ordinal)}} ${{escapeHtml(citation.concept_id)}}</h5>
                <ul class="compact-meta">
                  <li>${{escapeHtml(citation.support)}}</li>
                  <li>${{escapeHtml(citation.source_kind)}}</li>
                  <li>${{escapeHtml(citation.retrieved_at)}}</li>
                </ul>
                <div class="detail-actions">
                  <button
                    class="inline-action"
                    data-open-citation="${{escapeHtml(citation.citation_id)}}"
                  >Pin citation</button>
                  <button
                    class="inline-action"
                    data-open-concept="${{escapeHtml(citation.concept_id)}}"
                  >Concept</button>
                </div>
              </article>
            `).join("") || `
              <section class="state-panel" data-state="citation-unavailable">
                <h3>Citation unavailable</h3>
                <p>This source card has no release-pinned citations.</p>
              </section>
            `}}
          </div>
          ${{activeCitation ? `
            <section class="state-panel" data-state="citation-pinned">
              <h3>Pinned citation</h3>
              <p>${{escapeHtml(activeCitation.citation.citation_id)}}</p>
            </section>
          ` : ""}}
        ` : `
          <section class="state-panel" data-state="citation-unavailable">
            <h3>Citation unavailable</h3>
            <p>No source viewer is available in this release artifact.</p>
          </section>
        `}}
      </aside>
    </div>
  `;
}}

function destroyGraphExplorer() {{
  if (state.graphExplorer) {{
    state.graphExplorer.destroy();
    state.graphExplorer = null;
  }}
}}

function renderGraph(artifacts) {{
  const graph = artifacts.graph;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  return `
    <div class="metric-grid">
      ${{metric("Nodes", nodes.length)}}
      ${{metric("Edges", edges.length)}}
      ${{metric("Available actions", (graph.available_actions || []).join(", "))}}
    </div>
    <section class="panel" data-graph-root>
      <h3>Sigma graph explorer</h3>
      <div class="graph-toolbar" aria-label="Graph controls">
        <label for="graph-search">Search
          <input
            id="graph-search"
            data-graph-search
            autocomplete="off"
            value="${{escapeHtml(
              state.selectedConceptId.replace("concepts/", "")
            )}}"
          >
        </label>
        <label for="graph-relation">Relation
          <select id="graph-relation" data-graph-relation>
            <option value="">All relations</option>
          </select>
        </label>
        <label>
          <input type="checkbox" data-graph-orphans checked>
          Show orphans
        </label>
        <button type="button" data-graph-neighbor="1">1-hop</button>
        <button type="button" data-graph-neighbor="2">2-hop</button>
        <button type="button" data-graph-reset>Reset</button>
        <button type="button" data-graph-clear>Clear</button>
      </div>
      <div class="graph-workbench">
        <div
          class="graph-stage"
          data-sigma-stage
          role="application"
          aria-label="Interactive read-only Sigma.js graph canvas"
        ></div>
        <aside class="graph-side-panel" aria-label="Graph node details">
          <section>
            <h4>Matches</h4>
            <div class="graph-result-list" data-graph-results></div>
          </section>
          <section class="graph-details">
            <h4>Selection</h4>
            <div data-graph-details></div>
          </section>
        </aside>
      </div>
    </section>
  `;
}}

function initializeGraphExplorer(artifacts) {{
  const root = app.querySelector("[data-graph-root]");
  if (!root || typeof window.createM24GraphExplorer !== "function") {{
    const stage = app.querySelector("[data-sigma-stage]");
    if (stage) {{
      stage.dataset.state = "unavailable";
      stage.dataset.message = "Sigma.js browser runtime is unavailable.";
    }}
    setStatus("Sigma.js graph explorer could not be initialized.", "blocked");
    return;
  }}
  try {{
    state.graphExplorer = window.createM24GraphExplorer({{
      root,
      payload: artifacts.graph,
      selectedNodeId: state.selectedConceptId,
      sourceCountsByConcept: sourceCountsByConcept(artifacts),
      onSelection: (selection) => {{
        if (selection && selection.id) state.selectedConceptId = selection.id;
      }},
      onOpenWiki: (selection) => {{
        if (!selection || !selection.id) return;
        state.selectedConceptId = selection.id;
        navigateTo("wiki", {{ concept: state.selectedConceptId }});
      }},
      onViewSources: (selection) => {{
        if (!selection || !selection.id) return;
        const viewer = firstViewerForConcept(artifacts, selection.id);
        state.selectedConceptId = selection.id;
        state.selectedSourceViewerId = viewer ? viewer.viewer_id : null;
        state.selectedCitationId = null;
        state.sourceDetailFocusRequested = true;
        navigateTo("sources", {{
          concept: selection.id,
          viewer: state.selectedSourceViewerId,
        }});
      }},
      onStatus: (message) => setStatus(message, "ready"),
    }});
  }} catch (error) {{
    const stage = app.querySelector("[data-sigma-stage]");
    if (stage) {{
      stage.dataset.state = "unavailable";
      stage.dataset.message = "Graph explorer initialization failed.";
    }}
    setStatus(String(error && error.message ? error.message : error), "blocked");
  }}
}}

function renderRelease(artifacts) {{
  const release = artifacts.release;
  return `
    <section class="panel">
      <h3>Release identity</h3>
      <dl class="identity-strip">
        <div><dt>Release</dt><dd>${{escapeHtml(release.release_id)}}</dd></div>
        <div><dt>Manifest</dt><dd>${{escapeHtml(release.manifest_sha256)}}</dd></div>
        <div><dt>Source</dt><dd>${{escapeHtml(release.source_commit_sha)}}</dd></div>
      </dl>
    </section>
    <section class="panel">
      <h3>Artifacts</h3>
      <ul class="source-list">
        ${{Object.entries(release.artifacts || {{}}).map(([name, digest]) => `
          <li>${{escapeHtml(name)}} ${{escapeHtml(digest)}}</li>
        `).join("")}}
      </ul>
    </section>
  `;
}}

function renderObsidian(artifacts) {{
  const obsidian = artifacts.obsidian;
  return `
    <div class="metric-grid">
      ${{metric("Concept notes", obsidian.concept_note_count)}}
      ${{metric("Source notes", obsidian.source_note_count)}}
      ${{metric("Files", obsidian.file_count)}}
      ${{metric("ZIP bytes", obsidian.vault_zip_bytes)}}
      ${{metric("Write-back", String(obsidian.write_back_authorized))}}
    </div>
    <section class="panel">
      <h3>Vault candidate</h3>
      <p>The downloadable ZIP is built deterministically from the release-pinned
      Obsidian export files and committed as a same-origin internal artifact.</p>
      <ul class="compact-meta">
        <li>${{escapeHtml(obsidian.vault_zip_path)}}</li>
        <li>${{escapeHtml(obsidian.vault_zip_sha256)}}</li>
      </ul>
      <a
        class="download-link"
        href="${{escapeHtml(obsidian.download_href)}}"
        download
      >Download Vault ZIP</a>
      <a
        class="download-link"
        href="data/obsidian-export-manifest.json"
        download
      >Download export manifest</a>
    </section>
  `;
}}

function renderAcceptance(artifacts) {{
  const acceptance = artifacts.acceptance;
  const action = (acceptance.daniel_actions || [])[0] || {{}};
  return `
    <div class="metric-grid">
      ${{metric("Stage", acceptance.status)}}
      ${{metric("Daniel actions", acceptance.daniel_action_count)}}
      ${{metric("Retrieval", acceptance.boundaries.production_retrieval)}}
      ${{metric("Final acceptance", String(acceptance.final_acceptance_claimed))}}
    </div>
    <section class="panel">
      <h3>M24.14.6 gate</h3>
      <p>
        Authenticated performance evidence is pending Daniel's browser session.
        Local and CI regressions only prove harness and surface behavior.
      </p>
      <ul class="compact-meta vertical">
        <li>release ${{escapeHtml(acceptance.release_id)}}</li>
        <li>manifest ${{escapeHtml(acceptance.manifest_sha256)}}</li>
        <li>benchmark policy ${{escapeHtml(acceptance.benchmark_policy_sha256)}}</li>
        <li>benchmark cases ${{escapeHtml(acceptance.benchmark_cases_sha256)}}</li>
      </ul>
    </section>
    <section class="panel">
      <h3>Daniel action</h3>
      <p>${{escapeHtml(action.return_artifact || "Return the sanitized benchmark JSON.")}}</p>
      <pre class="source-document-body"><code>${{escapeHtml(action.command || "")}}</code></pre>
    </section>
  `;
}}

function renderAclDenied() {{
  return `
    <section class="state-panel" data-state="acl-denied">
      <h3>Access denied</h3>
      <p>The requested surface is not available to this internal session. The
      browser does not broaden ACL-filtered artifacts.</p>
    </section>
  `;
}}

function renderMissingArtifact() {{
  return `
    <section class="state-panel" data-state="missing-artifact">
      <h3>Release unavailable</h3>
      <p>A required canonical artifact is missing. Rendering is blocked until the
      deployment package is rebuilt from the canonical release.</p>
    </section>
  `;
}}

function render() {{
  const route = ROUTES[state.route] ? state.route : "overview";
  state.route = route;
  applyRouteStateFromHash(route);
  destroyGraphExplorer();
  setActiveRoute(route);
  title.textContent = ROUTES[route];
  setStatus(`${{ROUTES[route]}} ready.`, "ready");
  if (!state.artifacts) {{
    setStatus("Loading canonical artifacts.", "loading");
    app.innerHTML = `
      <section class="state-panel">
        <h3>Loading</h3>
        <p>Loading canonical artifacts.</p>
      </section>
    `;
    return;
  }}
  if (new URLSearchParams(location.hash.split("?")[1] || "").get("acl") === "denied") {{
    setStatus("Access denied for this route.", "blocked");
    app.innerHTML = renderAclDenied();
    return;
  }}
  const renderers = {{
    overview: renderOverview,
    wiki: renderWiki,
    search: renderSearch,
    graph: renderGraph,
    sources: renderSources,
    release: renderRelease,
    obsidian: renderObsidian,
    acceptance: renderAcceptance,
  }};
  app.innerHTML = renderers[route](state.artifacts);
  wireInteractions();
  if (route === "graph") {{
    initializeGraphExplorer(state.artifacts);
  }}
}}

function hashForRoute(route, params = {{}}) {{
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {{
    if (value) query.set(key, value);
  }}
  const suffix = query.toString();
  return `#/${{route}}${{suffix ? `?${{suffix}}` : ""}}`;
}}

function navigateTo(route, params = {{}}) {{
  const nextHash = hashForRoute(route, params);
  if (location.hash === nextHash) {{
    state.route = route;
    applyRouteStateFromHash(route);
    render();
    return;
  }}
  location.hash = nextHash;
}}

function focusSourceDetailIfRequested() {{
  if (!state.sourceDetailFocusRequested || state.route !== "sources") return;
  state.sourceDetailFocusRequested = false;
  const detail = app.querySelector("[data-source-detail]");
  const heading = app.querySelector("#source-detail-heading");
  if (detail) {{
    detail.scrollIntoView({{ block: "start", behavior: "instant" }});
  }}
  if (heading) {{
    heading.focus({{ preventScroll: true }});
  }}
}}

function wireInteractions() {{
  for (const button of app.querySelectorAll("[data-route]")) {{
    button.addEventListener("click", () => {{
      navigateTo(button.dataset.route);
    }});
  }}
  for (const button of app.querySelectorAll("[data-open-concept]")) {{
    button.addEventListener("click", () => {{
      state.selectedConceptId = button.dataset.openConcept;
      navigateTo("wiki", {{ concept: state.selectedConceptId }});
    }});
  }}
  for (const button of app.querySelectorAll("[data-focus-concept]")) {{
    button.addEventListener("click", () => {{
      state.selectedConceptId = button.dataset.focusConcept;
      navigateTo("graph", {{ concept: state.selectedConceptId }});
    }});
  }}
  for (const button of app.querySelectorAll("[data-open-source-viewer]")) {{
    button.addEventListener("click", () => {{
      state.selectedSourceViewerId = button.dataset.openSourceViewer;
      state.selectedCitationId = null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", {{ viewer: state.selectedSourceViewerId }});
    }});
  }}
  for (const button of app.querySelectorAll("[data-open-source-card]")) {{
    button.addEventListener("click", () => {{
      const viewer = viewerBySourceCard(state.artifacts, button.dataset.openSourceCard);
      state.selectedSourceViewerId = viewer ? viewer.viewer_id : null;
      state.selectedCitationId = null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", {{ viewer: state.selectedSourceViewerId }});
    }});
  }}
  for (const button of app.querySelectorAll("[data-open-citation]")) {{
    button.addEventListener("click", () => {{
      state.selectedCitationId = button.dataset.openCitation;
      const resolved = citationById(state.artifacts, state.selectedCitationId);
      state.selectedSourceViewerId = resolved ? resolved.viewer.viewer_id : null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", {{
        citation: state.selectedCitationId,
        viewer: state.selectedSourceViewerId,
      }});
    }});
  }}
  const form = app.querySelector("[data-search-form]");
  if (form) {{
    form.addEventListener("submit", (event) => {{
      event.preventDefault();
      const formData = new FormData(form);
      state.searchQuery = String(formData.get("q") || "").trim();
      render();
    }});
  }}
  const sourceForm = app.querySelector("[data-source-form]");
  if (sourceForm) {{
    sourceForm.addEventListener("submit", (event) => {{
      event.preventDefault();
      const formData = new FormData(sourceForm);
      state.sourceQuery = String(formData.get("q") || "").trim();
      render();
    }});
  }}
  focusSourceDetailIfRequested();
}}

window.addEventListener("hashchange", () => {{
  state.route = routeFromHash();
  applyRouteStateFromHash(state.route);
  render();
}});

loadArtifacts()
  .then((artifacts) => {{
    state.artifacts = artifacts;
    state.route = routeFromHash();
    applyRouteStateFromHash(state.route);
    setStatus("Canonical artifacts loaded and release identity validated.", "ready");
    render();
  }})
  .catch((error) => {{
    const message = String(error && error.message ? error.message : error);
    if (message.includes("artifact unavailable")) {{
      title.textContent = "Release unavailable";
      setStatus("A required artifact could not be loaded.", "blocked");
      app.innerHTML = renderMissingArtifact();
      return;
    }}
    boundedError("Release identity blocked", message);
  }});
"""


def _headers() -> str:
    return f"""/*
  Content-Security-Policy: {CSP}
"""


def _release_viewer() -> dict[str, Any]:
    bundle = load_canonical_release()
    return {
        "schema_version": f"{P6_SCHEMA}/release-viewer",
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_commit_sha": CANONICAL_SOURCE_SHA,
        "counts": bundle.manifest["counts"],
        "artifacts": {
            kind: digest for kind, digest in sorted(bundle.artifact_sha256.items())
        },
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
    }


def _source_viewers_payload() -> dict[str, Any]:
    response = canonical_runtime_search(query="harness", max_results=5)
    source_index = json.loads(SOURCE_DOCUMENT_INDEX_PATH.read_text(encoding="utf-8"))
    source_documents = json.loads(
        SOURCE_DOCUMENT_AGGREGATE_PATH.read_text(encoding="utf-8")
    )
    citation_viewers_by_source_id = {
        item.source_card.source_id: item.model_dump(mode="json")
        for item in response.source_viewers
    }
    source_viewers: list[dict[str, Any]] = []
    for ordinal, row in enumerate(source_index["coverage_matrix"], start=1):
        source_id = row["source_id"]
        cited_viewer = citation_viewers_by_source_id.get(source_id, {})
        cited_card = cited_viewer.get("source_card", {})
        document = source_documents["documents"][source_id]
        source_card = {
            "schema_version": "knowledge-engine-source-card/v1",
            "source_card_id": cited_card.get(
                "source_card_id", f"card_{hashlib.sha256(source_id.encode()).hexdigest()[:32]}"
            ),
            "source_id": source_id,
            "title": row["title"],
            "uri": row.get("canonical_uri"),
            "source_kind": row["kind"],
            "publisher": row.get("origin_repo") or document.get("owner") or "source",
            "display_host": row.get("origin_repo") or "release-authoritative source",
            "ordinal": ordinal,
            "retrieved_at": cited_card.get("retrieved_at"),
            "published_at": cited_card.get("published_at"),
            "snapshot_available": row["snapshot_available"],
            "integrity_sha256": row.get("generated_snapshot_sha256")
            or row.get("browser_payload_sha256"),
            "citation_ids": cited_card.get("citation_ids", []),
            "claim_ids": cited_card.get("claim_ids", []),
            "concept_ids": row.get("related_concepts", []),
            "section_ids": cited_card.get("section_ids", []),
            "content_bytes": row.get("content_bytes", 0),
            "line_count": row.get("line_count", 0),
            "coverage_status": row.get("coverage_status"),
            "document_path": row.get("document_path"),
        }
        citations = cited_viewer.get("citations", [])
        source_viewers.append(
            {
                "schema_version": "knowledge-engine-source-viewer/v1",
                "release_id": response.release_id,
                "viewer_id": f"viewer_{source_id}",
                "source_card": source_card,
                "summary": {
                    "citation_count": len(citations),
                    "claim_count": len(source_card["claim_ids"]),
                    "concept_count": len(source_card["concept_ids"]),
                    "has_snapshot": row["snapshot_available"],
                    "coverage_status": row.get("coverage_status"),
                    "content_bytes": row.get("content_bytes", 0),
                    "line_count": row.get("line_count", 0),
                    "integrity_available": bool(source_card["integrity_sha256"]),
                    "raw_evidence_exposed": False,
                    "retrieval_authority": "lexical",
                    "semantic_serving_enabled": False,
                },
                "document": document,
                "document_path": row.get("document_path"),
                "citations": citations,
            }
        )
    return {
        "schema_version": f"{P6_SCHEMA}/source-viewers",
        "release_id": response.release_id,
        "source_index_path": "data/source-index.json",
        "source_documents_path": "data/source-documents.json",
        "coverage_matrix": source_index["coverage_matrix"],
        "viewer_count": len(source_viewers),
        "source_viewers": source_viewers,
    }


def _obsidian_manifest_payload(
    *,
    site_root: Path,
) -> tuple[dict[str, Any], P6DeploymentArtifact]:
    export = canonical_obsidian_export()
    zip_artifact = _deterministic_obsidian_vault_zip(
        site_root=site_root,
        export_files=export.files,
    )
    payload = {
        "schema_version": f"{P6_SCHEMA}/obsidian-export-path",
        "release_id": export.release_id,
        "request_id": export.request_id,
        "file_count": len(export.files),
        "manifest_sha256": export.manifest_sha256,
        "concept_note_count": len(
            [item for item in export.files if item.path.startswith("concepts/")]
        ),
        "source_note_count": len(
            [item for item in export.files if item.path.startswith("sources/")]
        ),
        "vault_zip_path": OBSIDIAN_VAULT_ZIP_RELATIVE,
        "vault_zip_bytes": zip_artifact.bytes,
        "vault_zip_sha256": zip_artifact.sha256,
        "download_href": OBSIDIAN_VAULT_ZIP_RELATIVE,
        "write_back_authorized": False,
    }
    return payload, zip_artifact


def _secret_scan(paths: list[Path]) -> bool:
    for path in paths:
        if path.suffix in {".zip", ".png"}:
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return False
    return True


def build_p6_internal_product_deployment(
    *,
    output_root: Path = DEPLOYMENT_ROOT,
    include_self_digest: bool = True,
) -> P6InternalDeploymentReport:
    site_root = output_root / "site"
    concept = canonical_concept_wiki_page(concept_id="concepts/harness", query="harness")
    search = canonical_runtime_search(query="harness", max_results=5)
    graph = canonical_graph_navigation_state(selected_concept_id="concepts/harness")
    answers = build_p5_query_answer_acceptance_report()
    release = _release_viewer()
    source_viewers = _source_viewers_payload()
    source_index = json.loads(SOURCE_DOCUMENT_INDEX_PATH.read_text(encoding="utf-8"))
    source_documents = json.loads(
        SOURCE_DOCUMENT_AGGREGATE_PATH.read_text(encoding="utf-8")
    )
    obsidian, obsidian_zip = _obsidian_manifest_payload(site_root=site_root)
    acceptance = build_m24_14_6_pending_acceptance_report()
    data_payloads: list[tuple[str, Any]] = [
        ("data/concept-wiki-harness.json", concept.model_dump(mode="json")),
        ("data/search-harness.json", search.model_dump(mode="json")),
        ("data/graph-navigation.json", graph.model_dump(mode="json")),
        ("data/source-viewers.json", source_viewers),
        ("data/source-index.json", source_index),
        ("data/source-documents.json", source_documents),
        ("data/query-answer-acceptance.json", answers.model_dump(mode="json")),
        ("data/release-viewer.json", release),
        ("data/obsidian-export-manifest.json", obsidian),
        ("data/m24-14-6-pending-acceptance.json", acceptance),
    ]
    for source_payload_path in sorted(SOURCE_DOCUMENT_PAYLOAD_ROOT.glob("*.json")):
        data_payloads.append(
            (
                f"data/sources/{source_payload_path.name}",
                json.loads(source_payload_path.read_text(encoding="utf-8")),
            )
        )
    artifacts = [
        _write_text(site_root / "index.html", _index_html()),
        _write_text(site_root / "_headers", _headers()),
        _write_text(site_root / "styles.css", _styles()),
        _write_text(site_root / "graph-explorer.js", _graph_explorer_js()),
        _write_text(site_root / "app.js", _app_js()),
        _write_bytes(site_root / "favicon.png", FAVICON_PNG_BYTES),
    ]
    for source, relative in GRAPH_VENDOR_ASSETS:
        destination = site_root / relative
        vendor_bytes = source.read_bytes() if source.exists() else destination.read_bytes()
        artifacts.append(_write_bytes(destination, vendor_bytes))
    artifacts.append(obsidian_zip)
    for relative, payload in data_payloads:
        artifacts.append(_write_text(site_root / relative, _json(payload)))
    scanned_paths = [
        site_root / artifact.path.removeprefix(site_root.as_posix() + "/")
        for artifact in artifacts
    ]
    secret_scan_passed = _secret_scan(scanned_paths)
    surfaces = [
        _surface(
            surface="concept_wiki",
            path="site/data/concept-wiki-harness.json",
            payload=concept,
            fallback="release_unavailable_error_state",
        ),
        _surface(
            surface="lexical_search",
            path="site/data/search-harness.json",
            payload=search,
            fallback="not_found_with_release_identity",
        ),
        _surface(
            surface="sigma_graph_explorer",
            path="site/data/graph-navigation.json",
            payload=graph,
            fallback="textual_graph_fallback",
        ),
        _surface(
            surface="provenance_source_viewer",
            path="site/data/source-viewers.json",
            payload=source_viewers,
            fallback="citation_unavailable_error_state",
        ),
        _surface(
            surface="citation_grounded_internal_answers",
            path="site/data/query-answer-acceptance.json",
            payload=answers,
            fallback="safe_answer_fallbacks_from_P5",
        ),
        _surface(
            surface="release_viewer",
            path="site/data/release-viewer.json",
            payload=release,
            fallback="release_identity_mismatch_block",
        ),
        _surface(
            surface="obsidian_export",
            path="site/data/obsidian-export-manifest.json",
            payload=obsidian,
            fallback="regenerate_export_from_canonical_release",
        ),
        _surface(
            surface="m24_14_6_acceptance",
            path="site/data/m24-14-6-pending-acceptance.json",
            payload=acceptance,
            fallback="pending_acceptance_report_unavailable",
        ),
    ]
    report = P6InternalDeploymentReport(
        status="internal_product_deployment_package_complete",
        issue_number=P6_ISSUE_NUMBER,
        release_id=CANONICAL_RELEASE_ID,
        manifest_sha256=CANONICAL_MANIFEST_SHA256,
        source_commit_sha=CANONICAL_SOURCE_SHA,
        deployment_package=site_root.as_posix(),
        auth=P6AuthContract(
            identity_sources=[
                "Cloudflare Access JWT",
                "equivalent signed internal session",
            ],
        ),
        surfaces=surfaces,
        artifacts=artifacts,
        security=P6SecurityChecks(
            csp=CSP,
            secret_scan_passed=secret_scan_passed,
            secret_scan_patterns=len(SECRET_PATTERNS),
            observability_events=[
                "authenticated_view",
                "release_identity_loaded",
                "surface_opened",
                "safe_fallback_rendered",
                "error_state_rendered",
            ],
            error_states=[
                "403_unauthenticated",
                "release_identity_mismatch",
                "release_unavailable",
                "citation_unavailable",
                "obsidian_export_unavailable",
            ],
            rollback_plan=[
                "disable internal route or Access application",
                "restore previous deployment package",
                "keep production retrieval lexical",
                "verify no Source/R2/Qdrant/pointer/traffic mutation occurred",
            ],
        ),
        authority=P6AuthorityBoundary(),
    )
    if include_self_digest:
        report.self_sha256 = _digest(report.model_dump(mode="json", exclude={"self_sha256"}))
    report_path = output_root / "m24-p6-internal-product-deployment.json"
    _write_text(report_path, _json(report.model_dump(mode="json")))
    return report
