(function () {
  "use strict";

  const API_GRAPH_PATH = "/api/m26/graph";
  const API_HEALTH_PATH = "/api/m26/health";
  const FRONTEND_IDENTITY = "m26-pa7-dedicated-full-graph-route-v1";

  const state = {
    graph: null,
    health: null,
    error: "",
    graphExplorer: null,
  };

  const app = document.querySelector("#app");
  const statusBanner = document.querySelector("#app-status");
  const releaseElement = document.querySelector("#release-id");
  const manifestElement = document.querySelector("#manifest-sha");

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

  function compactList(items) {
    const values = (Array.isArray(items) ? items : []).filter(Boolean);
    if (!values.length) return "";
    return `
      <ul class="compact-meta">
        ${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    `;
  }

  function reasonFrom(payload, response) {
    return (
      payload?.detail?.reason_code ||
      payload?.reason_code ||
      payload?.status ||
      `HTTP_${response.status}`
    );
  }

  async function fetchJson(path) {
    const response = await fetch(path, {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    let payload = null;
    try { payload = await response.json(); } catch (_error) {}
    if (!response.ok) throw new Error(reasonFrom(payload, response));
    return payload;
  }

  function validateGraph(payload) {
    if (
      !payload ||
      payload.status !== "ok" ||
      payload.graph_scope !== "full_current_production_relation_graph" ||
      !Array.isArray(payload.nodes) ||
      !Array.isArray(payload.edges)
    ) {
      throw new Error("M26_OWNER_GRAPH_PAYLOAD_INVALID");
    }
    return payload;
  }

  function renderError(reason) {
    const boundedReason = String(reason || "M26_OWNER_GRAPH_NETWORK_ERROR").slice(0, 120);
    app.innerHTML = `
      <section
        class="state-panel"
        data-state="full-graph-blocked"
        data-pa7-surface="full-knowledge-graph"
      >
        <h3>Full production graph blocked</h3>
        <p>${escapeHtml(boundedReason)}</p>
        <p>The smaller Bounded Concept Graph is not substituted for PA7 acceptance.</p>
      </section>
    `;
    setStatus("Full production graph blocked.", "blocked");
  }

  function renderGraph(payload) {
    const nodes = payload.nodes;
    const edges = payload.edges;
    releaseElement.textContent = payload.release_id || "unavailable";
    manifestElement.textContent = payload.manifest_sha256 || "unavailable";
    app.innerHTML = `
      <div
        class="metric-grid"
        data-pa7-surface="full-knowledge-graph"
        data-pa7-frontend-identity="${FRONTEND_IDENTITY}"
      >
        <section class="panel"><h3>Nodes</h3><p data-full-graph-node-count>${escapeHtml(nodes.length)}</p></section>
        <section class="panel"><h3>Edges</h3><p data-full-graph-edge-count>${escapeHtml(edges.length)}</p></section>
        <section class="panel"><h3>Release</h3><p>${escapeHtml(payload.release_id)}</p></section>
        <section class="panel"><h3>Scope</h3><p>full production</p></section>
      </div>
      <section class="panel" data-pa7-full-graph-identity="true">
        <h3>Verified graph identity</h3>
        <p>This route is a dedicated static page. It does not read location hash state and does not depend on the SPA router.</p>
        ${compactList([
          `frontend ${FRONTEND_IDENTITY}`,
          state.health?.canonical_runtime?.build_sha ? `backend ${state.health.canonical_runtime.build_sha}` : "",
          `manifest ${payload.manifest_sha256}`,
          `graph-v2 ${payload.graph_v2_sha256}`,
          `pointer ${payload.binding?.production_pointer_sha256}`,
          "read-only",
          "zero R2, Qdrant, corpus, index and pointer writes",
        ])}
      </section>
      <section
        class="panel"
        data-graph-root
        data-full-production-graph
        data-pa7-surface="full-knowledge-graph"
        data-pa7-sigma-stage="pending"
      >
        <h3>Sigma Full Knowledge Graph</h3>
        <div class="graph-toolbar" aria-label="Full graph controls">
          <label for="full-graph-search">Search
            <input id="full-graph-search" data-graph-search autocomplete="off" value="">
          </label>
          <label for="full-graph-relation">Relation
            <select id="full-graph-relation" data-graph-relation>
              <option value="">All relations</option>
            </select>
          </label>
          <label><input type="checkbox" data-graph-orphans checked> Show orphans</label>
          <button type="button" data-graph-neighbor="1">1-hop</button>
          <button type="button" data-graph-neighbor="2">2-hop</button>
          <button type="button" data-graph-reset>Reset</button>
          <button type="button" data-graph-clear>Clear</button>
        </div>
        <div class="graph-workbench">
          <div class="graph-stage" data-sigma-stage role="application" aria-label="Interactive read-only full production Sigma.js graph canvas"></div>
          <aside class="graph-side-panel" aria-label="Full graph node details">
            <section><h4>Matches</h4><div class="graph-result-list" data-graph-results></div></section>
            <section class="graph-details"><h4>Selection</h4><div data-graph-details></div></section>
          </aside>
        </div>
      </section>
    `;
  }

  function initializeGraph(payload) {
    const root = app.querySelector("[data-full-production-graph]");
    if (!root || typeof window.createM24GraphExplorer !== "function") {
      throw new Error("M26_FULL_GRAPH_RENDERER_UNAVAILABLE");
    }
    state.graphExplorer = window.createM24GraphExplorer({
      root,
      payload,
      selectedNodeId: null,
      sourceCountsByConcept: {},
      onSelection: () => {},
      onOpenWiki: (selection) => {
        if (selection?.id && String(selection.id).startsWith("concepts/")) {
          location.href = `/#/wiki?concept=${encodeURIComponent(selection.id)}`;
        }
      },
      onViewSources: () => { location.href = "/#/sources"; },
      onStatus: (message) => {
        root.setAttribute("data-pa7-sigma-stage", "ready");
        setStatus(message, "ready");
      },
    });
  }

  async function boot() {
    document.documentElement.setAttribute("data-pa7-surface", "full-knowledge-graph");
    document.documentElement.setAttribute("data-pa7-frontend-identity", FRONTEND_IDENTITY);
    setStatus("Loading owner-only full production graph.", "loading");
    try {
      try {
        state.health = await fetchJson(API_HEALTH_PATH);
      } catch (_error) {
        state.health = null;
      }
      state.graph = validateGraph(await fetchJson(API_GRAPH_PATH));
      renderGraph(state.graph);
      initializeGraph(state.graph);
    } catch (error) {
      state.error = String(error && error.message ? error.message : "M26_OWNER_GRAPH_NETWORK_ERROR");
      renderError(state.error);
    }
  }

  boot();
})();
