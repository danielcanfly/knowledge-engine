const EXPECTED_RELEASE = "20260720T160000Z-46137c97263e";
const EXPECTED_MANIFEST = "ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877";
const HARNESS_CONCEPT_ID = "concepts/harness";

const ARTIFACTS = {
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
};

const ROUTES = {
  overview: "Overview",
  wiki: "Concept Wiki",
  search: "Lexical Search",
  graph: "Graph Explorer",
  sources: "Sources",
  release: "Release Details",
  obsidian: "Obsidian Export",
  acceptance: "Acceptance Status",
};

const state = {
  artifacts: null,
  graphExplorer: null,
  route: "overview",
  selectedConceptId: HARNESS_CONCEPT_ID,
  selectedCitationId: null,
  selectedSourceViewerId: null,
  sourceDetailFocusRequested: false,
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

function routeSearchParams() {
  return new URLSearchParams(location.hash.split("?")[1] || "");
}

function applyRouteStateFromHash(route) {
  const params = routeSearchParams();
  if (route === "wiki") {
    state.selectedConceptId = params.get("concept") || HARNESS_CONCEPT_ID;
  }
  if (route === "graph" && params.get("concept")) {
    state.selectedConceptId = params.get("concept");
  }
  if (route === "sources") {
    state.selectedSourceViewerId = params.has("viewer") ? params.get("viewer") : null;
    state.selectedCitationId = params.has("citation") ? params.get("citation") : null;
  }
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

function sourceCoverageRows(artifacts) {
  return artifacts.sourceIndex.coverage_matrix || artifacts.sources.coverage_matrix || [];
}

function sourceDocuments(artifacts) {
  return (artifacts.sourceDocuments && artifacts.sourceDocuments.documents) || {};
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

function viewerBySourceId(artifacts, sourceId) {
  return sourceViewers(artifacts).find(
    (viewer) => (viewer.source_card || {}).source_id === sourceId
  ) || null;
}

function firstViewerForConcept(artifacts, conceptId) {
  return sourceViewers(artifacts).find((viewer) =>
    (((viewer.source_card || {}).concept_ids || []).includes(conceptId))
  ) || null;
}

function sourceCountsByConcept(artifacts) {
  const counts = {};
  for (const viewer of sourceViewers(artifacts)) {
    for (const conceptId of ((viewer.source_card || {}).concept_ids || [])) {
      counts[conceptId] = (counts[conceptId] || 0) + 1;
    }
  }
  return counts;
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

function graphNodeByConceptId(artifacts, conceptId) {
  return (artifacts.graph.nodes || []).find((node) =>
    (node.concept_id || node.id || node.node_id) === conceptId
  ) || null;
}

function graphRelationshipsForConcept(artifacts, conceptId) {
  const nodesById = new Map((artifacts.graph.nodes || []).map((node) => [
    node.concept_id || node.id || node.node_id,
    node,
  ]));
  return (artifacts.graph.edges || [])
    .filter((edge) => edge.source === conceptId || edge.target === conceptId)
    .map((edge) => {
      const neighborId = edge.source === conceptId ? edge.target : edge.source;
      const neighbor = nodesById.get(neighborId) || {};
      return {
        neighborId,
        neighborTitle: neighbor.title || neighbor.label || neighborId,
        relationType: edge.relation_type || "related",
        direction: edge.source === conceptId ? "outbound" : "inbound",
      };
    })
    .sort((left, right) =>
      left.relationType.localeCompare(right.relationType) ||
      left.neighborTitle.localeCompare(right.neighborTitle)
    );
}

function lexicalResultsForConcept(artifacts, conceptId) {
  return (artifacts.search.results || [])
    .filter((item) => item.concept_id === conceptId)
    .sort((left, right) => (left.rank || 0) - (right.rank || 0));
}

function sourceCardsForConcept(artifacts, conceptId) {
  return allSourceCards(artifacts)
    .filter((card) => (card.concept_ids || []).includes(conceptId))
    .sort((left, right) =>
      (left.title || left.source_id || "").localeCompare(right.title || right.source_id || "")
    );
}

function renderBoundedConceptSummary(artifacts, conceptId) {
  const node = graphNodeByConceptId(artifacts, conceptId);
  if (!node) {
    return `
      <section class="state-panel" data-state="concept-not-found">
        <h3>Concept not found in this release</h3>
        <p>This concept ID is not present in the release-pinned graph artifact.</p>
        <div class="detail-actions">
          <button class="inline-action" data-open-concept="${escapeHtml(HARNESS_CONCEPT_ID)}">
            Return to loaded concept
          </button>
          <button class="inline-action" data-route="graph">Open graph explorer</button>
        </div>
      </section>
    `;
  }
  const relationships = graphRelationshipsForConcept(artifacts, conceptId);
  const lexicalResults = lexicalResultsForConcept(artifacts, conceptId);
  const sourceCards = sourceCardsForConcept(artifacts, conceptId);
  return `
    <section class="panel" data-state="bounded-graph-concept-summary">
      <h3>${escapeHtml(node.title || node.label || conceptId)}</h3>
      <p>
        ${escapeHtml(node.description || node.summary || "No graph description is available.")}
      </p>
      <p class="muted">
        Bounded graph-derived summary. A full detailed Concept Wiki artifact is not available for
        this concept in the release-pinned internal package.
      </p>
      <ul class="pill-list">
        <li>${escapeHtml(conceptId)}</li>
        <li>${escapeHtml(node.type || node.concept_type || "Concept")}</li>
        <li>${escapeHtml(relationships.length)} relationships</li>
        <li>${escapeHtml(sourceCards.length)} source handoffs</li>
      </ul>
      <div class="detail-actions">
        <button class="inline-action" data-focus-concept="${escapeHtml(conceptId)}">
          Open in graph
        </button>
        <button class="inline-action" data-open-concept="${escapeHtml(HARNESS_CONCEPT_ID)}">
          Return to loaded concept
        </button>
      </div>
    </section>
    <section class="panel">
      <h3>Graph relationships</h3>
      <ul class="relationship-list">
        ${relationships.slice(0, 8).map((edge) => `
          <li>
            <button class="inline-action" data-focus-concept="${escapeHtml(edge.neighborId)}">
              ${escapeHtml(edge.direction)} ${escapeHtml(edge.relationType)}:
              ${escapeHtml(edge.neighborTitle)}
            </button>
          </li>
        `).join("") || "<li>No graph relationships are available for this concept.</li>"}
      </ul>
    </section>
    <section class="panel">
      <h3>Lexical evidence in this release</h3>
      <div class="result-list">
        ${lexicalResults.slice(0, 5).map((item) => `
          <article>
            <h4>#${escapeHtml(item.rank)} ${escapeHtml(item.title || item.section_title)}</h4>
            <p>${escapeHtml(item.excerpt || "No excerpt available.")}</p>
            <ul class="compact-meta">
              <li>${escapeHtml(item.section_id || "section unavailable")}</li>
              <li>score ${escapeHtml(item.score)}</li>
            </ul>
          </article>
        `).join("") || `
          <section class="state-panel" data-state="bounded-summary-no-lexical-match">
            <h3>No lexical sections</h3>
            <p>The release-pinned lexical artifact has no matching section for this concept.</p>
          </section>
        `}
      </div>
    </section>
    <section class="panel">
      <h3>Source handoffs</h3>
      <div class="source-list">
        ${sourceCards.slice(0, 6).map((card) => `
          <button
            class="inline-action"
            data-open-source-card="${escapeHtml(card.source_card_id)}"
          >
            ${escapeHtml(card.title || card.display_host || card.source_id)}
          </button>
        `).join("") || "<p class='muted'>No source handoff is available for this concept.</p>"}
      </div>
    </section>
  `;
}

function renderWiki(artifacts) {
  const concept = artifacts.concept;
  if (state.selectedConceptId !== concept.concept_id) {
    return renderBoundedConceptSummary(artifacts, state.selectedConceptId);
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
            const resolvedViewer = viewerBySourceId(state.artifacts, card.source_id) || viewer;
            return `
              <button
                class="inline-action"
                data-open-source-viewer="${escapeHtml(resolvedViewer.viewer_id)}"
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

function renderSummary(summary) {
  if (!summary || typeof summary !== "object") return "";
  return `
    <ul class="compact-meta">
      <li>${escapeHtml(summary.coverage_status || "metadata")}</li>
      <li>${escapeHtml(summary.content_bytes || 0)} bytes</li>
      <li>${escapeHtml(summary.line_count || 0)} lines</li>
      <li>${escapeHtml(summary.citation_count || 0)} citations</li>
    </ul>
  `;
}

function renderSourceDocument(documentPayload) {
  if (!documentPayload) {
    return `
      <section class="state-panel" data-state="source-document-missing">
        <h3>Source document unavailable</h3>
        <p>No release-pinned document payload is available for this source.</p>
      </section>
    `;
  }
  const doc = documentPayload.document || {};
  const integrity = documentPayload.integrity || {};
  const origin = documentPayload.origin || {};
  const registry = documentPayload.registry || {};
  const metadataOnlyReason = documentPayload.metadata_only_reason || doc.metadata_only_reason;
  const body = doc.body || "";
  const toc = documentPayload.toc || [];
  return `
    <section
      class="source-reader"
      data-source-document="${escapeHtml(documentPayload.source_id)}"
    >
      <div class="reader-meta">
        <section>
          <h4>Origin</h4>
          <ul class="compact-meta vertical">
            <li>${escapeHtml(origin.repo || "unresolved")}</li>
            <li>${escapeHtml(origin.commit || "no exact commit")}</li>
            <li>${escapeHtml(origin.path || "no exact path")}</li>
            <li>blob ${escapeHtml(origin.blob_sha || "unavailable")}</li>
          </ul>
        </section>
        <section>
          <h4>Integrity</h4>
          <ul class="compact-meta vertical">
            <li>snapshot ${escapeHtml(integrity.snapshot_sha256 || "metadata-only")}</li>
            <li>payload ${escapeHtml(integrity.browser_payload_sha256 || "unavailable")}</li>
            <li>registry ${escapeHtml(registry.content_sha256 || "not declared")}</li>
            <li>scope ${escapeHtml(registry.content_hash_scope || "not declared")}</li>
            <li>truncated ${escapeHtml(String(Boolean(integrity.truncated)))}</li>
          </ul>
        </section>
      </div>
      ${toc.length ? `
        <section class="source-toc" aria-label="Document table of contents">
          <h4>Contents</h4>
          <ol>
            ${toc.slice(0, 40).map((item) => `
              <li data-level="${escapeHtml(item.level)}">${escapeHtml(item.title)}</li>
            `).join("")}
          </ol>
        </section>
      ` : ""}
      ${metadataOnlyReason ? `
        <section class="state-panel" data-state="metadata-only-source">
          <h3>Metadata-only source</h3>
          <p>${escapeHtml(metadataOnlyReason)}</p>
        </section>
      ` : `
        <pre class="source-document-body" tabindex="0"><code>${escapeHtml(body)}</code></pre>
      `}
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
    const document = (
      viewer.document ||
      sourceDocuments(artifacts)[card.source_id] ||
      {}
    ).document || {};
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
  });
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
        value="${escapeHtml(state.sourceQuery)}"
        autocomplete="off"
      >
      <button type="submit">Filter</button>
    </form>
    <div class="surface-split source-split">
      <section class="panel">
        <h3>Sources</h3>
        <p class="muted">
          Showing ${escapeHtml(filtered.length)} of ${escapeHtml(rows.length)}
          canonical source records.
        </p>
        <div class="result-list">
          ${filtered.map((viewer) => {
            const card = viewer.source_card || {};
            const isSelected = activeViewer && viewer.viewer_id === activeViewer.viewer_id;
            return `
              <article
                class="source-card"
                data-source-id="${escapeHtml(card.source_id)}"
                aria-current="${isSelected ? "true" : "false"}"
              >
                <h4>${escapeHtml(card.title || card.source_id || viewer.viewer_id)}</h4>
                <p>${escapeHtml(card.display_host || card.publisher || "source")}</p>
                <ul class="compact-meta">
                  <li>${escapeHtml(card.source_kind)}</li>
                  <li>${escapeHtml((viewer.citations || []).length)} citations</li>
                  <li>snapshot ${escapeHtml(String(card.snapshot_available))}</li>
                  <li>${escapeHtml(card.content_bytes || 0)} bytes</li>
                  <li>${escapeHtml(card.coverage_status || "metadata")}</li>
                </ul>
                <div class="detail-actions">
                  <button
                    class="inline-action"
                    data-open-source-viewer="${escapeHtml(viewer.viewer_id)}"
                  >${isSelected ? "Inspect selected" : "Inspect"}</button>
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
      <aside class="panel source-detail-panel" data-source-detail>
        <p class="eyebrow">Source detail</p>
        <h3 id="source-detail-heading" tabindex="-1">
          ${escapeHtml(activeCard.title || "Source detail")}
        </h3>
        ${activeViewer ? `
          ${renderSummary(activeViewer.summary)}
          <ul class="compact-meta">
            <li>${escapeHtml(activeCard.source_card_id)}</li>
            <li>${escapeHtml(activeCard.source_kind)}</li>
            <li>${escapeHtml(activeCard.display_host || activeCard.publisher)}</li>
            <li>${escapeHtml(activeCard.document_path || "document path unavailable")}</li>
          </ul>
          <div class="detail-actions">
            ${activeCard.uri ? `
              <a
                class="inline-action"
                href="${escapeHtml(activeCard.uri)}"
                rel="noreferrer"
              >Open original source</a>
            ` : ""}
            ${(activeCard.concept_ids || []).map((conceptId) => `
              <button
                class="inline-action"
                data-open-concept="${escapeHtml(conceptId)}"
              >${escapeHtml(conceptId.replace("concepts/", ""))}</button>
            `).join("")}
          </div>
          ${renderSourceDocument(activeDocument)}
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
      sourceCountsByConcept: sourceCountsByConcept(artifacts),
      onSelection: (selection) => {
        if (selection && selection.id) state.selectedConceptId = selection.id;
      },
      onOpenWiki: (selection) => {
        if (!selection || !selection.id) return;
        state.selectedConceptId = selection.id;
        navigateTo("wiki", { concept: state.selectedConceptId });
      },
      onViewSources: (selection) => {
        if (!selection || !selection.id) return;
        const viewer = firstViewerForConcept(artifacts, selection.id);
        state.selectedConceptId = selection.id;
        state.selectedSourceViewerId = viewer ? viewer.viewer_id : null;
        state.selectedCitationId = null;
        state.sourceDetailFocusRequested = true;
        navigateTo("sources", {
          concept: selection.id,
          viewer: state.selectedSourceViewerId,
        });
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
      ${metric("ZIP bytes", obsidian.vault_zip_bytes)}
      ${metric("Write-back", String(obsidian.write_back_authorized))}
    </div>
    <section class="panel">
      <h3>Vault candidate</h3>
      <p>The downloadable ZIP is built deterministically from the release-pinned
      Obsidian export files and committed as a same-origin internal artifact.</p>
      <ul class="compact-meta">
        <li>${escapeHtml(obsidian.vault_zip_path)}</li>
        <li>${escapeHtml(obsidian.vault_zip_sha256)}</li>
      </ul>
      <a
        class="download-link"
        href="${escapeHtml(obsidian.download_href)}"
        download
      >Download Vault ZIP</a>
      <a
        class="download-link"
        href="data/obsidian-export-manifest.json"
        download
      >Download export manifest</a>
    </section>
  `;
}

function renderAcceptance(artifacts) {
  const acceptance = artifacts.acceptance;
  const action = (acceptance.daniel_actions || [])[0] || {};
  return `
    <div class="metric-grid">
      ${metric("Stage", acceptance.status)}
      ${metric("Daniel actions", acceptance.daniel_action_count)}
      ${metric("Retrieval", acceptance.boundaries.production_retrieval)}
      ${metric("Final acceptance", String(acceptance.final_acceptance_claimed))}
    </div>
    <section class="panel">
      <h3>M24.14.6 gate</h3>
      <p>
        Authenticated performance evidence is pending Daniel's browser session.
        Local and CI regressions only prove harness and surface behavior.
      </p>
      <ul class="compact-meta vertical">
        <li>release ${escapeHtml(acceptance.release_id)}</li>
        <li>manifest ${escapeHtml(acceptance.manifest_sha256)}</li>
        <li>benchmark policy ${escapeHtml(acceptance.benchmark_policy_sha256)}</li>
        <li>benchmark cases ${escapeHtml(acceptance.benchmark_cases_sha256)}</li>
      </ul>
    </section>
    <section class="panel">
      <h3>Daniel action</h3>
      <p>${escapeHtml(action.return_artifact || "Return the sanitized benchmark JSON.")}</p>
      <pre class="source-document-body"><code>${escapeHtml(action.command || "")}</code></pre>
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
  applyRouteStateFromHash(route);
  destroyGraphExplorer();
  setActiveRoute(route);
  title.textContent = ROUTES[route];
  setStatus(`${ROUTES[route]} ready.`, "ready");
  if (!state.artifacts) {
    setStatus("Loading canonical artifacts.", "loading");
    app.innerHTML = `
      <section class="state-panel">
        <h3>Loading</h3>
        <p>Loading canonical artifacts.</p>
      </section>
    `;
    return;
  }
  if (new URLSearchParams(location.hash.split("?")[1] || "").get("acl") === "denied") {
    setStatus("Access denied for this route.", "blocked");
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
    acceptance: renderAcceptance,
  };
  app.innerHTML = renderers[route](state.artifacts);
  wireInteractions();
  if (route === "graph") {
    initializeGraphExplorer(state.artifacts);
  }
}

function hashForRoute(route, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value);
  }
  const suffix = query.toString();
  return `#/${route}${suffix ? `?${suffix}` : ""}`;
}

function navigateTo(route, params = {}) {
  const nextHash = hashForRoute(route, params);
  if (location.hash === nextHash) {
    state.route = route;
    applyRouteStateFromHash(route);
    render();
    return;
  }
  location.hash = nextHash;
}

function focusSourceDetailIfRequested() {
  if (!state.sourceDetailFocusRequested || state.route !== "sources") return;
  state.sourceDetailFocusRequested = false;
  const detail = app.querySelector("[data-source-detail]");
  const heading = app.querySelector("#source-detail-heading");
  if (detail) {
    detail.scrollIntoView({ block: "start", behavior: "instant" });
  }
  if (heading) {
    heading.focus({ preventScroll: true });
  }
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
      navigateTo("wiki", { concept: state.selectedConceptId });
    });
  }
  for (const button of app.querySelectorAll("[data-focus-concept]")) {
    button.addEventListener("click", () => {
      state.selectedConceptId = button.dataset.focusConcept;
      navigateTo("graph", { concept: state.selectedConceptId });
    });
  }
  for (const button of app.querySelectorAll("[data-open-source-viewer]")) {
    button.addEventListener("click", () => {
      state.selectedSourceViewerId = button.dataset.openSourceViewer;
      state.selectedCitationId = null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", { viewer: state.selectedSourceViewerId });
    });
  }
  for (const button of app.querySelectorAll("[data-open-source-card]")) {
    button.addEventListener("click", () => {
      const viewer = viewerBySourceCard(state.artifacts, button.dataset.openSourceCard);
      state.selectedSourceViewerId = viewer ? viewer.viewer_id : null;
      state.selectedCitationId = null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", { viewer: state.selectedSourceViewerId });
    });
  }
  for (const button of app.querySelectorAll("[data-open-citation]")) {
    button.addEventListener("click", () => {
      state.selectedCitationId = button.dataset.openCitation;
      const resolved = citationById(state.artifacts, state.selectedCitationId);
      state.selectedSourceViewerId = resolved ? resolved.viewer.viewer_id : null;
      state.sourceDetailFocusRequested = true;
      navigateTo("sources", {
        citation: state.selectedCitationId,
        viewer: state.selectedSourceViewerId,
      });
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
  focusSourceDetailIfRequested();
}

window.addEventListener("hashchange", () => {
  state.route = routeFromHash();
  applyRouteStateFromHash(state.route);
  render();
});

loadArtifacts()
  .then((artifacts) => {
    state.artifacts = artifacts;
    state.route = routeFromHash();
    applyRouteStateFromHash(state.route);
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
