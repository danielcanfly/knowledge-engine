from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

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
SurfaceName = Literal[
    "concept_wiki",
    "lexical_search",
    "sigma_graph_explorer",
    "provenance_source_viewer",
    "citation_grounded_internal_answers",
    "release_viewer",
    "obsidian_export",
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
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>LLM Wiki Internal Product</title>
  <link rel="stylesheet" href="styles.css">
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
        <a href="#/wiki" data-route-link="wiki">Concept Wiki</a>
        <a href="#/search" data-route-link="search">Lexical Search</a>
        <a href="#/graph" data-route-link="graph">Graph Explorer</a>
        <a href="#/sources" data-route-link="sources">Sources</a>
        <a href="#/release" data-route-link="release">Release</a>
        <a href="#/obsidian" data-route-link="obsidian">Obsidian</a>
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


def _app_js() -> str:
    return f"""const EXPECTED_RELEASE = "{CANONICAL_RELEASE_ID}";
const EXPECTED_MANIFEST = "{CANONICAL_MANIFEST_SHA256}";

const ARTIFACTS = {{
  release: "data/release-viewer.json",
  concept: "data/concept-wiki-harness.json",
  search: "data/search-harness.json",
  graph: "data/graph-navigation.json",
  sources: "data/source-viewers.json",
  answers: "data/query-answer-acceptance.json",
  obsidian: "data/obsidian-export-manifest.json",
}};

const ROUTES = {{
  overview: "Overview",
  wiki: "Concept Wiki",
  search: "Lexical Search",
  graph: "Graph Explorer",
  sources: "Sources",
  release: "Release Details",
  obsidian: "Obsidian Export",
}};

const state = {{
  artifacts: null,
  route: "overview",
  selectedConceptId: "concepts/harness",
  searchQuery: "harness",
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

function renderWiki(artifacts) {{
  const concept = artifacts.concept;
  const relationships = concept.relationships || [];
  return `
    <section class="panel">
      <h3>${{escapeHtml(concept.title)}}</h3>
      <p>${{escapeHtml(concept.description)}}</p>
      <ul class="pill-list">
        <li>${{escapeHtml(concept.concept_id)}}</li>
        <li>release ${{escapeHtml(concept.release_id)}}</li>
      </ul>
    </section>
    <section class="panel">
      <h3>Typed relationships</h3>
      <ul class="relationship-list">
        ${{relationships.slice(0, 12).map((edge) => `
          <li>
            <button
              class="inline-action"
              data-focus-concept="${{escapeHtml(edge.neighbor_concept_id)}}"
            >
              ${{escapeHtml(edge.direction)}} ${{escapeHtml(edge.relation_type)}}:
              ${{escapeHtml(edge.neighbor_title)}}
            </button>
          </li>
        `).join("")}}
      </ul>
    </section>
  `;
}}

function renderSearch(artifacts) {{
  const results = artifacts.search.results || [];
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
    <section class="table-like" aria-label="Lexical search results">
      ${{results.map((item) => `
        <article class="table-row">
          <strong>#${{escapeHtml(item.rank)}}</strong>
          <div>
            <h3>${{escapeHtml(item.title)}}</h3>
            <p>${{escapeHtml(item.excerpt)}}</p>
          </div>
          <button
            class="inline-action"
            data-focus-concept="${{escapeHtml(item.concept_id)}}"
          >Open</button>
        </article>
      `).join("")}}
    </section>
  `;
}}

function renderGraph(artifacts) {{
  const graph = artifacts.graph;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const width = 720;
  const height = 260;
  const placed = nodes.slice(0, 12).map((node, index) => {{
    const angle = (Math.PI * 2 * index) / Math.max(1, Math.min(12, nodes.length));
    return {{
      ...node,
      x: width / 2 + Math.cos(angle) * 240,
      y: height / 2 + Math.sin(angle) * 90,
    }};
  }});
  const byId = new Map(placed.map((node) => [node.concept_id, node]));
  return `
    <div class="metric-grid">
      ${{metric("Nodes", nodes.length)}}
      ${{metric("Edges", edges.length)}}
      ${{metric("Available actions", (graph.available_actions || []).join(", "))}}
    </div>
    <section class="panel">
      <h3>Graph preview</h3>
      <p>Interactive Sigma.js canvas is implemented in M24.14.2. This shell route
      proves canonical graph identity and provides a textual fallback.</p>
      <div class="graph-placeholder" role="img" aria-label="Canonical graph preview">
        <svg viewBox="0 0 ${{width}} ${{height}}" focusable="false">
          ${{edges.slice(0, 16).map((edge) => {{
            const source = byId.get(edge.source);
            const target = byId.get(edge.target);
            if (!source || !target) return "";
            return `
              <line
                class="edge-line"
                x1="${{source.x}}"
                y1="${{source.y}}"
                x2="${{target.x}}"
                y2="${{target.y}}"
              ></line>
            `;
          }}).join("")}}
          ${{placed.map((node) => `
            <circle class="node-dot" cx="${{node.x}}" cy="${{node.y}}" r="6">
              <title>${{escapeHtml(node.title)}}</title>
            </circle>
          `).join("")}}
        </svg>
      </div>
    </section>
  `;
}}

function renderSources(artifacts) {{
  const viewers = artifacts.sources.source_viewers || [];
  return `
    <section class="item-grid">
      ${{viewers.map((viewer) => {{
        const card = viewer.source_card || {{}};
        return `
          <article class="item-card">
            <h3>${{escapeHtml(card.title || card.source_id)}}</h3>
            <p>${{escapeHtml(card.display_host || card.publisher || "source")}}</p>
            <ul class="source-list">
              <li>${{escapeHtml(card.source_kind)}}</li>
              <li>${{escapeHtml((viewer.citations || []).length)}} citations</li>
              <li>raw evidence exposed: false</li>
            </ul>
          </article>
        `;
      }}).join("")}}
    </section>
  `;
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
      ${{metric("Write-back", String(obsidian.write_back_authorized))}}
    </div>
    <section class="panel">
      <h3>Vault candidate</h3>
      <p>M24.14.4 delivers the deterministic downloadable Vault ZIP. The current
      app shell exposes the release-pinned export manifest and route.</p>
      <a
        class="download-link"
        href="data/obsidian-export-manifest.json"
        download
      >Download manifest</a>
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
  setActiveRoute(route);
  title.textContent = ROUTES[route];
  if (!state.artifacts) {{
    app.innerHTML = `
      <section class="state-panel">
        <h3>Loading</h3>
        <p>Loading canonical artifacts.</p>
      </section>
    `;
    return;
  }}
  if (new URLSearchParams(location.hash.split("?")[1] || "").get("acl") === "denied") {{
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
  }};
  app.innerHTML = renderers[route](state.artifacts);
  wireInteractions();
}}

function wireInteractions() {{
  for (const button of app.querySelectorAll("[data-focus-concept]")) {{
    button.addEventListener("click", () => {{
      state.selectedConceptId = button.dataset.focusConcept;
      location.hash = "#/graph";
    }});
  }}
  const form = app.querySelector("[data-search-form]");
  if (form) {{
    form.addEventListener("submit", (event) => {{
      event.preventDefault();
      const formData = new FormData(form);
      state.searchQuery = String(formData.get("q") || "").trim();
      if (!state.searchQuery) {{
        app.innerHTML = `
          <section class="state-panel" data-state="no-match">
            <h3>No query supplied</h3>
            <p>Enter a lexical query to inspect release-pinned results.</p>
          </section>
        `;
      }}
    }});
  }}
}}

window.addEventListener("hashchange", () => {{
  state.route = routeFromHash();
  render();
}});

loadArtifacts()
  .then((artifacts) => {{
    state.artifacts = artifacts;
    state.route = routeFromHash();
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
    return {
        "schema_version": f"{P6_SCHEMA}/source-viewers",
        "release_id": response.release_id,
        "viewer_count": len(response.source_viewers),
        "source_viewers": [item.model_dump(mode="json") for item in response.source_viewers],
    }


def _obsidian_manifest_payload() -> dict[str, Any]:
    export = canonical_obsidian_export()
    return {
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
        "write_back_authorized": False,
    }


def _secret_scan(paths: list[Path]) -> bool:
    for path in paths:
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
    obsidian = _obsidian_manifest_payload()
    data_payloads: list[tuple[str, Any]] = [
        ("data/concept-wiki-harness.json", concept.model_dump(mode="json")),
        ("data/search-harness.json", search.model_dump(mode="json")),
        ("data/graph-navigation.json", graph.model_dump(mode="json")),
        ("data/source-viewers.json", source_viewers),
        ("data/query-answer-acceptance.json", answers.model_dump(mode="json")),
        ("data/release-viewer.json", release),
        ("data/obsidian-export-manifest.json", obsidian),
    ]
    artifacts = [
        _write_text(site_root / "index.html", _index_html()),
        _write_text(site_root / "styles.css", _styles()),
        _write_text(site_root / "app.js", _app_js()),
    ]
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
