const EXPECTED_RELEASE = "20260720T160000Z-46137c97263e";
const EXPECTED_MANIFEST = "ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877";

const ARTIFACTS = {
  release: "data/release-viewer.json",
  concept: "data/concept-wiki-harness.json",
  search: "data/search-harness.json",
  graph: "data/graph-navigation.json",
  sources: "data/source-viewers.json",
  answers: "data/query-answer-acceptance.json",
  obsidian: "data/obsidian-export-manifest.json",
};

const ROUTES = {
  overview: "Overview",
  wiki: "Concept Wiki",
  search: "Lexical Search",
  graph: "Graph Explorer",
  sources: "Sources",
  release: "Release Details",
  obsidian: "Obsidian Export",
};

const state = {
  artifacts: null,
  route: "overview",
  selectedConceptId: "concepts/harness",
  searchQuery: "harness",
};

const app = document.querySelector("#app");
const statusBanner = document.querySelector("#app-status");
const title = document.querySelector("#route-title");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(message, mode = "ready") {
  statusBanner.textContent = message;
  statusBanner.dataset.state = mode;
}

function boundedError(titleText, message) {
  title.textContent = titleText;
  setStatus(message, "blocked");
  app.innerHTML = `
    <section class="state-panel" data-state="bounded-error">
      <h3>${escapeHtml(titleText)}</h3>
      <p>${escapeHtml(message)}</p>
    </section>
  `;
}

async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`artifact unavailable: ${path}`);
  }
  return response.json();
}

function releaseOf(payload) {
  return payload && typeof payload === "object" ? payload.release_id : null;
}

function validateIdentity(artifacts) {
  const mismatches = Object.entries(artifacts)
    .filter(([name, payload]) => name !== "answers")
    .filter(([, payload]) => releaseOf(payload) !== EXPECTED_RELEASE)
    .map(([name]) => name);
  if (artifacts.release.manifest_sha256 !== EXPECTED_MANIFEST) {
    mismatches.push("release manifest");
  }
  if (mismatches.length) {
    throw new Error(`release identity mismatch: ${mismatches.join(", ")}`);
  }
  if (artifacts.release.production_retrieval !== "lexical") {
    throw new Error("production retrieval boundary mismatch");
  }
  if (
    artifacts.release.semantic_serving_enabled ||
    artifacts.release.hybrid_retrieval_enabled
  ) {
    throw new Error("semantic or hybrid serving is not authorized");
  }
}

async function loadArtifacts() {
  setStatus("Loading canonical artifacts.", "loading");
  const entries = await Promise.all(
    Object.entries(ARTIFACTS).map(async ([key, path]) => [key, await loadJson(path)])
  );
  const artifacts = Object.fromEntries(entries);
  validateIdentity(artifacts);
  return artifacts;
}

function routeFromHash() {
  return (location.hash.replace(/^#\/?/, "") || "overview").split("?")[0];
}

function setActiveRoute(route) {
  for (const link of document.querySelectorAll("[data-route-link]")) {
    link.toggleAttribute("aria-current", link.dataset.routeLink === route);
  }
}

function metric(label, value) {
  return `
    <section class="panel">
      <h3>${escapeHtml(label)}</h3>
      <p>${escapeHtml(value)}</p>
    </section>
  `;
}

function renderOverview(artifacts) {
  const counts = artifacts.release.counts || {};
  const graphEdges = Array.isArray(artifacts.graph.edges) ? artifacts.graph.edges.length : 0;
  return `
    <div class="metric-grid">
      ${metric("Concepts", counts.concepts)}
      ${metric("Graph edges", graphEdges)}
      ${metric("Source snapshots", counts.source_snapshots)}
      ${metric("Retrieval", artifacts.release.production_retrieval)}
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
}

function renderWiki(artifacts) {
  const concept = artifacts.concept;
  const relationships = concept.relationships || [];
  return `
    <section class="panel">
      <h3>${escapeHtml(concept.title)}</h3>
      <p>${escapeHtml(concept.description)}</p>
      <ul class="pill-list">
        <li>${escapeHtml(concept.concept_id)}</li>
        <li>release ${escapeHtml(concept.release_id)}</li>
      </ul>
    </section>
    <section class="panel">
      <h3>Typed relationships</h3>
      <ul class="relationship-list">
        ${relationships.slice(0, 12).map((edge) => `
          <li>
            <button
              class="inline-action"
              data-focus-concept="${escapeHtml(edge.neighbor_concept_id)}"
            >
              ${escapeHtml(edge.direction)} ${escapeHtml(edge.relation_type)}:
              ${escapeHtml(edge.neighbor_title)}
            </button>
          </li>
        `).join("")}
      </ul>
    </section>
  `;
}

function renderSearch(artifacts) {
  const results = artifacts.search.results || [];
  return `
    <form class="toolbar" data-search-form>
      <label for="search-input">Lexical query</label>
      <input
        id="search-input"
        name="q"
        value="${escapeHtml(state.searchQuery)}"
        autocomplete="off"
      >
      <button type="submit">Search</button>
    </form>
    <section class="table-like" aria-label="Lexical search results">
      ${results.map((item) => `
        <article class="table-row">
          <strong>#${escapeHtml(item.rank)}</strong>
          <div>
            <h3>${escapeHtml(item.title)}</h3>
            <p>${escapeHtml(item.excerpt)}</p>
          </div>
          <button
            class="inline-action"
            data-focus-concept="${escapeHtml(item.concept_id)}"
          >Open</button>
        </article>
      `).join("")}
    </section>
  `;
}

function renderGraph(artifacts) {
  const graph = artifacts.graph;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const width = 720;
  const height = 260;
  const placed = nodes.slice(0, 12).map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, Math.min(12, nodes.length));
    return {
      ...node,
      x: width / 2 + Math.cos(angle) * 240,
      y: height / 2 + Math.sin(angle) * 90,
    };
  });
  const byId = new Map(placed.map((node) => [node.concept_id, node]));
  return `
    <div class="metric-grid">
      ${metric("Nodes", nodes.length)}
      ${metric("Edges", edges.length)}
      ${metric("Available actions", (graph.available_actions || []).join(", "))}
    </div>
    <section class="panel">
      <h3>Graph preview</h3>
      <p>Interactive Sigma.js canvas is implemented in M24.14.2. This shell route
      proves canonical graph identity and provides a textual fallback.</p>
      <div class="graph-placeholder" role="img" aria-label="Canonical graph preview">
        <svg viewBox="0 0 ${width} ${height}" focusable="false">
          ${edges.slice(0, 16).map((edge) => {
            const source = byId.get(edge.source);
            const target = byId.get(edge.target);
            if (!source || !target) return "";
            return `
              <line
                class="edge-line"
                x1="${source.x}"
                y1="${source.y}"
                x2="${target.x}"
                y2="${target.y}"
              ></line>
            `;
          }).join("")}
          ${placed.map((node) => `
            <circle class="node-dot" cx="${node.x}" cy="${node.y}" r="6">
              <title>${escapeHtml(node.title)}</title>
            </circle>
          `).join("")}
        </svg>
      </div>
    </section>
  `;
}

function renderSources(artifacts) {
  const viewers = artifacts.sources.source_viewers || [];
  return `
    <section class="item-grid">
      ${viewers.map((viewer) => {
        const card = viewer.source_card || {};
        return `
          <article class="item-card">
            <h3>${escapeHtml(card.title || card.source_id)}</h3>
            <p>${escapeHtml(card.display_host || card.publisher || "source")}</p>
            <ul class="source-list">
              <li>${escapeHtml(card.source_kind)}</li>
              <li>${escapeHtml((viewer.citations || []).length)} citations</li>
              <li>raw evidence exposed: false</li>
            </ul>
          </article>
        `;
      }).join("")}
    </section>
  `;
}

function renderRelease(artifacts) {
  const release = artifacts.release;
  return `
    <section class="panel">
      <h3>Release identity</h3>
      <dl class="identity-strip">
        <div><dt>Release</dt><dd>${escapeHtml(release.release_id)}</dd></div>
        <div><dt>Manifest</dt><dd>${escapeHtml(release.manifest_sha256)}</dd></div>
        <div><dt>Source</dt><dd>${escapeHtml(release.source_commit_sha)}</dd></div>
      </dl>
    </section>
    <section class="panel">
      <h3>Artifacts</h3>
      <ul class="source-list">
        ${Object.entries(release.artifacts || {}).map(([name, digest]) => `
          <li>${escapeHtml(name)} ${escapeHtml(digest)}</li>
        `).join("")}
      </ul>
    </section>
  `;
}

function renderObsidian(artifacts) {
  const obsidian = artifacts.obsidian;
  return `
    <div class="metric-grid">
      ${metric("Concept notes", obsidian.concept_note_count)}
      ${metric("Source notes", obsidian.source_note_count)}
      ${metric("Files", obsidian.file_count)}
      ${metric("Write-back", String(obsidian.write_back_authorized))}
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
}

function renderAclDenied() {
  return `
    <section class="state-panel" data-state="acl-denied">
      <h3>Access denied</h3>
      <p>The requested surface is not available to this internal session. The
      browser does not broaden ACL-filtered artifacts.</p>
    </section>
  `;
}

function renderMissingArtifact() {
  return `
    <section class="state-panel" data-state="missing-artifact">
      <h3>Release unavailable</h3>
      <p>A required canonical artifact is missing. Rendering is blocked until the
      deployment package is rebuilt from the canonical release.</p>
    </section>
  `;
}

function render() {
  const route = ROUTES[state.route] ? state.route : "overview";
  state.route = route;
  setActiveRoute(route);
  title.textContent = ROUTES[route];
  if (!state.artifacts) {
    app.innerHTML = `
      <section class="state-panel">
        <h3>Loading</h3>
        <p>Loading canonical artifacts.</p>
      </section>
    `;
    return;
  }
  if (new URLSearchParams(location.hash.split("?")[1] || "").get("acl") === "denied") {
    app.innerHTML = renderAclDenied();
    return;
  }
  const renderers = {
    overview: renderOverview,
    wiki: renderWiki,
    search: renderSearch,
    graph: renderGraph,
    sources: renderSources,
    release: renderRelease,
    obsidian: renderObsidian,
  };
  app.innerHTML = renderers[route](state.artifacts);
  wireInteractions();
}

function wireInteractions() {
  for (const button of app.querySelectorAll("[data-focus-concept]")) {
    button.addEventListener("click", () => {
      state.selectedConceptId = button.dataset.focusConcept;
      location.hash = "#/graph";
    });
  }
  const form = app.querySelector("[data-search-form]");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      state.searchQuery = String(formData.get("q") || "").trim();
      if (!state.searchQuery) {
        app.innerHTML = `
          <section class="state-panel" data-state="no-match">
            <h3>No query supplied</h3>
            <p>Enter a lexical query to inspect release-pinned results.</p>
          </section>
        `;
      }
    });
  }
}

window.addEventListener("hashchange", () => {
  state.route = routeFromHash();
  render();
});

loadArtifacts()
  .then((artifacts) => {
    state.artifacts = artifacts;
    state.route = routeFromHash();
    setStatus("Canonical artifacts loaded and release identity validated.", "ready");
    render();
  })
  .catch((error) => {
    const message = String(error && error.message ? error.message : error);
    if (message.includes("artifact unavailable")) {
      title.textContent = "Release unavailable";
      setStatus("A required artifact could not be loaded.", "blocked");
      app.innerHTML = renderMissingArtifact();
      return;
    }
    boundedError("Release identity blocked", message);
  });
