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
  graphExplorer: null,
  route: "overview",
  selectedConceptId: "concepts/harness",
  selectedCitationId: null,
  selectedSourceViewerId: null,
  searchQuery: "harness",
  sourceQuery: "",
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

function sourceViewers(artifacts) {
  return artifacts.sources.source_viewers || [];
}

function allSourceCards(artifacts) {
  const searchCards = artifacts.search.source_cards || [];
  const viewerCards = sourceViewers(artifacts).map((viewer) => viewer.source_card || {});
  const byId = new Map();
  for (const card of [...searchCards, ...viewerCards]) {
    if (card.source_card_id) byId.set(card.source_card_id, card);
  }
  return [...byId.values()];
}

function viewerById(artifacts, viewerId) {
  const viewers = sourceViewers(artifacts);
  return viewers.find((viewer) => viewer.viewer_id === viewerId) || viewers[0] || null;
}

function viewerBySourceCard(artifacts, sourceCardId) {
  return sourceViewers(artifacts).find(
    (viewer) => (viewer.source_card || {}).source_card_id === sourceCardId
  ) || null;
}

function citationById(artifacts, citationId) {
  for (const viewer of sourceViewers(artifacts)) {
    const citation = (viewer.citations || []).find((item) => item.citation_id === citationId);
    if (citation) return { viewer, citation };
  }
  return null;
}

function filteredSearchResults(artifacts) {
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
  if (state.selectedConceptId !== concept.concept_id) {
    return `
      <section class="state-panel" data-state="concept-artifact-mismatch">
        <h3>Concept artifact unavailable</h3>
        <p>The selected concept is not present in the release-pinned Concept Wiki
        artifact loaded by this internal route.</p>
        <div class="detail-actions">
          <button
            class="inline-action"
            data-focus-concept="${escapeHtml(state.selectedConceptId)}"
          >Open selected concept in graph</button>
          <button
            class="inline-action"
            data-open-concept="${escapeHtml(concept.concept_id)}"
          >Return to loaded concept</button>
        </div>
      </section>
    `;
  }
  const relationships = concept.relationships || [];
  const sections = concept.sections || [];
  const viewers = concept.source_viewers || [];
  return `
    <div class="surface-split">
      <section class="panel">
        <h3>${escapeHtml(concept.title)}</h3>
        <p>${escapeHtml(concept.description)}</p>
        <ul class="pill-list">
          <li>${escapeHtml(concept.concept_id)}</li>
          <li>release ${escapeHtml(concept.release_id)}</li>
          <li>${escapeHtml(sections.length)} sections</li>
          <li>${escapeHtml(relationships.length)} relationships</li>
        </ul>
        <div class="detail-actions">
          <button class="inline-action" data-focus-concept="${escapeHtml(concept.concept_id)}">
            Open in graph
          </button>
          <button class="inline-action" data-route="search">Inspect lexical results</button>
        </div>
      </section>
      <aside class="panel">
        <h3>Source handoff</h3>
        <div class="source-list">
          ${viewers.map((viewer) => {
            const card = viewer.source_card || {};
            return `
              <button
                class="inline-action"
                data-open-source-viewer="${escapeHtml(viewer.viewer_id)}"
              >
                ${escapeHtml(card.title || card.source_id || viewer.viewer_id)}
              </button>
            `;
          }).join("") || "<p class='muted'>No source viewers available.</p>"}
        </div>
      </aside>
    </div>
    <section class="panel">
      <h3>Sections</h3>
      <div class="section-list">
        ${sections.map((section) => `
          <article>
            <h4>${escapeHtml(section.title || section.section_id)}</h4>
            <p>${escapeHtml(section.excerpt)}</p>
            <ul class="compact-meta">
              <li>rank ${escapeHtml(section.rank)}</li>
              <li>score ${escapeHtml(section.score)}</li>
              <li>${escapeHtml((section.source_card_ids || []).length)} sources</li>
            </ul>
            <div class="detail-actions">
              ${(section.source_viewer_ids || []).map((viewerId) => `
                <button
                  class="inline-action"
                  data-open-source-viewer="${escapeHtml(viewerId)}"
                >Source</button>
              `).join("")}
            </div>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="concept-section-empty">
            <h3>No sections</h3>
            <p>This concept has no release-pinned sections.</p>
          </section>
        `}
      </div>
    </section>
    <section class="panel">
      <h3>Typed relationships</h3>
      <ul class="relationship-list">
        ${relationships.map((edge) => `
          <li>
            <button
              class="inline-action"
              data-focus-concept="${escapeHtml(edge.neighbor_concept_id)}"
            >
              ${escapeHtml(edge.direction)} ${escapeHtml(edge.relation_type)}:
              ${escapeHtml(edge.neighbor_title)}
            </button>
          </li>
        `).join("") || "<li>No relationships in this release artifact.</li>"}
      </ul>
    </section>
  `;
}

function renderSearch(artifacts) {
  const results = filteredSearchResults(artifacts);
  const allResults = artifacts.search.results || [];
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
    <section class="panel">
      <h3>Release-pinned lexical results</h3>
      <p class="muted">
        Showing ${escapeHtml(results.length)} of ${escapeHtml(allResults.length)} results.
      </p>
      <div class="result-list" aria-label="Lexical search results">
        ${results.map((item) => `
          <article>
            <h4>#${escapeHtml(item.rank)} ${escapeHtml(item.title)}</h4>
            <p>${escapeHtml(item.excerpt)}</p>
            <ul class="compact-meta">
              <li>${escapeHtml(item.concept_id)}</li>
              <li>${escapeHtml(item.section_id)}</li>
              <li>score ${escapeHtml(item.score)}</li>
              <li>${escapeHtml((item.citation_ordinals || []).length)} citations</li>
            </ul>
            <div class="detail-actions">
              <button
                class="inline-action"
                data-focus-concept="${escapeHtml(item.concept_id)}"
              >Open graph</button>
              <button
                class="inline-action"
                data-open-concept="${escapeHtml(item.concept_id)}"
              >Open wiki</button>
              ${(item.source_card_ids || []).slice(0, 3).map((sourceCardId) => `
                <button
                  class="inline-action"
                  data-open-source-card="${escapeHtml(sourceCardId)}"
                >Source</button>
              `).join("")}
            </div>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="no-match">
            <h3>No lexical matches</h3>
            <p>The release-pinned lexical result set has no matches for this query.</p>
          </section>
        `}
      </div>
    </section>
    <section class="panel">
      <h3>Source cards</h3>
      <div class="source-list">
        ${allSourceCards(artifacts).map((card) => `
          <button
            class="inline-action"
            data-open-source-card="${escapeHtml(card.source_card_id)}"
          >
            ${escapeHtml(card.title || card.display_host || card.source_id)}
          </button>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSources(artifacts) {
  const viewers = sourceViewers(artifacts);
  const selected = state.selectedCitationId
    ? (citationById(artifacts, state.selectedCitationId) || {}).viewer
    : viewerById(artifacts, state.selectedSourceViewerId);
  const activeViewer = selected || viewers[0] || null;
  const activeCard = activeViewer ? activeViewer.source_card || {} : {};
  const query = state.sourceQuery.trim().toLocaleLowerCase("en-US");
  const filtered = viewers.filter((viewer) => {
    const card = viewer.source_card || {};
    if (!query) return true;
    return [
      viewer.viewer_id,
      card.title,
      card.display_host,
      card.publisher,
      card.source_kind,
      card.source_id,
      (card.concept_ids || []).join(" "),
    ].join(" ").toLocaleLowerCase("en-US").includes(query);
  });
  const activeCitation = state.selectedCitationId
    ? citationById(artifacts, state.selectedCitationId)
    : null;
  return `
    <form class="toolbar" data-source-form>
      <label for="source-input">Source filter</label>
      <input
        id="source-input"
        name="q"
        value="${escapeHtml(state.sourceQuery)}"
        autocomplete="off"
      >
      <button type="submit">Filter</button>
    </form>
    <div class="surface-split">
      <section class="panel">
        <h3>Sources</h3>
        <div class="result-list">
          ${filtered.map((viewer) => {
            const card = viewer.source_card || {};
            return `
              <article>
                <h4>${escapeHtml(card.title || card.source_id || viewer.viewer_id)}</h4>
                <p>${escapeHtml(card.display_host || card.publisher || "source")}</p>
                <ul class="compact-meta">
                  <li>${escapeHtml(card.source_kind)}</li>
                  <li>${escapeHtml((viewer.citations || []).length)} citations</li>
                  <li>snapshot ${escapeHtml(String(card.snapshot_available))}</li>
                </ul>
                <div class="detail-actions">
                  <button
                    class="inline-action"
                    data-open-source-viewer="${escapeHtml(viewer.viewer_id)}"
                  >Inspect</button>
                  ${(card.concept_ids || []).slice(0, 2).map((conceptId) => `
                    <button
                      class="inline-action"
                      data-open-concept="${escapeHtml(conceptId)}"
                    >Concept</button>
                  `).join("")}
                </div>
              </article>
            `;
          }).join("") || `
            <section class="state-panel" data-state="source-no-match">
              <h3>No source matches</h3>
              <p>No source viewer matches this filter.</p>
            </section>
          `}
        </div>
      </section>
      <aside class="panel">
        <h3>Source detail</h3>
        ${activeViewer ? `
          <p>${escapeHtml(activeViewer.summary || activeCard.title || activeCard.source_id)}</p>
          <ul class="compact-meta">
            <li>${escapeHtml(activeCard.source_card_id)}</li>
            <li>${escapeHtml(activeCard.source_kind)}</li>
            <li>${escapeHtml(activeCard.display_host || activeCard.publisher)}</li>
          </ul>
          <div class="detail-actions">
            ${(activeCard.concept_ids || []).map((conceptId) => `
              <button
                class="inline-action"
                data-open-concept="${escapeHtml(conceptId)}"
              >${escapeHtml(conceptId.replace("concepts/", ""))}</button>
            `).join("")}
          </div>
          <h4>Citations</h4>
          <div class="citation-list">
            ${(activeViewer.citations || []).map((citation) => `
              <article data-citation-id="${escapeHtml(citation.citation_id)}">
                <h5>#${escapeHtml(citation.ordinal)} ${escapeHtml(citation.concept_id)}</h5>
                <ul class="compact-meta">
                  <li>${escapeHtml(citation.support)}</li>
                  <li>${escapeHtml(citation.source_kind)}</li>
                  <li>${escapeHtml(citation.retrieved_at)}</li>
                </ul>
                <div class="detail-actions">
                  <button
                    class="inline-action"
                    data-open-citation="${escapeHtml(citation.citation_id)}"
                  >Pin citation</button>
                  <button
                    class="inline-action"
                    data-open-concept="${escapeHtml(citation.concept_id)}"
                  >Concept</button>
                </div>
              </article>
            `).join("") || `
              <section class="state-panel" data-state="citation-unavailable">
                <h3>Citation unavailable</h3>
                <p>This source card has no release-pinned citations.</p>
              </section>
            `}
          </div>
          ${activeCitation ? `
            <section class="state-panel" data-state="citation-pinned">
              <h3>Pinned citation</h3>
              <p>${escapeHtml(activeCitation.citation.citation_id)}</p>
            </section>
          ` : ""}
        ` : `
          <section class="state-panel" data-state="citation-unavailable">
            <h3>Citation unavailable</h3>
            <p>No source viewer is available in this release artifact.</p>
          </section>
        `}
      </aside>
    </div>
  `;
}

function destroyGraphExplorer() {
  if (state.graphExplorer) {
    state.graphExplorer.destroy();
    state.graphExplorer = null;
  }
}

function renderGraph(artifacts) {
  const graph = artifacts.graph;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  return `
    <div class="metric-grid">
      ${metric("Nodes", nodes.length)}
      ${metric("Edges", edges.length)}
      ${metric("Available actions", (graph.available_actions || []).join(", "))}
    </div>
    <section class="panel" data-graph-root>
      <h3>Sigma graph explorer</h3>
      <div class="graph-toolbar" aria-label="Graph controls">
        <label for="graph-search">Search
          <input
            id="graph-search"
            data-graph-search
            autocomplete="off"
            value="${escapeHtml(
              state.selectedConceptId.replace("concepts/", "")
            )}"
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
}

function initializeGraphExplorer(artifacts) {
  const root = app.querySelector("[data-graph-root]");
  if (!root || typeof window.createM24GraphExplorer !== "function") {
    const stage = app.querySelector("[data-sigma-stage]");
    if (stage) {
      stage.dataset.state = "unavailable";
      stage.dataset.message = "Sigma.js browser runtime is unavailable.";
    }
    setStatus("Sigma.js graph explorer could not be initialized.", "blocked");
    return;
  }
  try {
    state.graphExplorer = window.createM24GraphExplorer({
      root,
      payload: artifacts.graph,
      selectedNodeId: state.selectedConceptId,
      onSelection: (selection) => {
        if (selection && selection.id) state.selectedConceptId = selection.id;
      },
      onStatus: (message) => setStatus(message, "ready"),
    });
  } catch (error) {
    const stage = app.querySelector("[data-sigma-stage]");
    if (stage) {
      stage.dataset.state = "unavailable";
      stage.dataset.message = "Graph explorer initialization failed.";
    }
    setStatus(String(error && error.message ? error.message : error), "blocked");
  }
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
  destroyGraphExplorer();
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
  if (route === "graph") {
    initializeGraphExplorer(state.artifacts);
  }
}

function navigateTo(route) {
  const nextHash = `#/${route}`;
  if (location.hash === nextHash) {
    state.route = route;
    render();
    return;
  }
  location.hash = nextHash;
}

function wireInteractions() {
  for (const button of app.querySelectorAll("[data-route]")) {
    button.addEventListener("click", () => {
      navigateTo(button.dataset.route);
    });
  }
  for (const button of app.querySelectorAll("[data-open-concept]")) {
    button.addEventListener("click", () => {
      state.selectedConceptId = button.dataset.openConcept;
      navigateTo("wiki");
    });
  }
  for (const button of app.querySelectorAll("[data-focus-concept]")) {
    button.addEventListener("click", () => {
      state.selectedConceptId = button.dataset.focusConcept;
      navigateTo("graph");
    });
  }
  for (const button of app.querySelectorAll("[data-open-source-viewer]")) {
    button.addEventListener("click", () => {
      state.selectedSourceViewerId = button.dataset.openSourceViewer;
      state.selectedCitationId = null;
      navigateTo("sources");
    });
  }
  for (const button of app.querySelectorAll("[data-open-source-card]")) {
    button.addEventListener("click", () => {
      const viewer = viewerBySourceCard(state.artifacts, button.dataset.openSourceCard);
      state.selectedSourceViewerId = viewer ? viewer.viewer_id : null;
      state.selectedCitationId = null;
      navigateTo("sources");
    });
  }
  for (const button of app.querySelectorAll("[data-open-citation]")) {
    button.addEventListener("click", () => {
      state.selectedCitationId = button.dataset.openCitation;
      const resolved = citationById(state.artifacts, state.selectedCitationId);
      state.selectedSourceViewerId = resolved ? resolved.viewer.viewer_id : null;
      navigateTo("sources");
    });
  }
  const form = app.querySelector("[data-search-form]");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      state.searchQuery = String(formData.get("q") || "").trim();
      render();
    });
  }
  const sourceForm = app.querySelector("[data-source-form]");
  if (sourceForm) {
    sourceForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(sourceForm);
      state.sourceQuery = String(formData.get("q") || "").trim();
      render();
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
