(function () {
  "use strict";

  const app = document.querySelector("#graph-app");
  const status = document.querySelector("#graph-status");
  const release = document.querySelector("#graph-release");
  const manifest = document.querySelector("#graph-manifest");

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function setStatus(message, mode = "ready") {
    status.textContent = message;
    status.dataset.state = mode;
  }

  function metric(label, value) {
    return `<section class="panel"><h3>${escapeHtml(label)}</h3><p>${escapeHtml(value)}</p></section>`;
  }

  function shell(payload) {
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload.edges) ? payload.edges : [];
    return `
      <div class="metric-grid">
        ${metric("Nodes", nodes.length)}
        ${metric("Edges", edges.length)}
        ${metric("Graph scope", payload.graph_scope || "full production")}
        ${metric("Authority", "owner-only read-only")}
      </div>
      <section class="panel">
        <h3>Graph surfaces</h3>
        <p>This page reads the current production relation graph from the owner-only runtime. The original Concept Graph remains a smaller release-pinned explanatory view.</p>
      </section>
      <section class="panel" data-graph-root>
        <h3>Sigma full graph explorer</h3>
        <div class="graph-toolbar" aria-label="Graph controls">
          <label for="graph-search">Search
            <input id="graph-search" data-graph-search autocomplete="off" value="">
          </label>
          <label for="graph-relation">Relation
            <select id="graph-relation" data-graph-relation>
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
          <div class="graph-stage" data-sigma-stage role="application" aria-label="Interactive read-only full Sigma.js graph canvas"></div>
          <aside class="graph-side-panel" aria-label="Graph node details">
            <section><h4>Matches</h4><div class="graph-result-list" data-graph-results></div></section>
            <section class="graph-details"><h4>Selection</h4><div data-graph-details></div></section>
          </aside>
        </div>
      </section>
    `;
  }

  async function main() {
    try {
      const response = await fetch("/api/m26/graph", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: { accept: "application/json" },
      });
      let payload = null;
      try { payload = await response.json(); } catch (_error) {}
      if (!response.ok || !payload || payload.status !== "ok") {
        const reason = payload?.reason_code || payload?.detail?.reason_code || `HTTP_${response.status}`;
        throw new Error(reason);
      }
      if (!Array.isArray(payload.nodes) || !Array.isArray(payload.edges)) {
        throw new Error("M26_OWNER_GRAPH_PAYLOAD_INVALID");
      }
      release.textContent = payload.release_id || "unknown";
      manifest.textContent = payload.manifest_sha256 || "unknown";
      app.innerHTML = shell(payload);
      if (typeof window.createM24GraphExplorer !== "function") {
        throw new Error("Sigma.js graph explorer unavailable");
      }
      window.createM24GraphExplorer({
        root: app.querySelector("[data-graph-root]"),
        payload,
        selectedNodeId: null,
        sourceCountsByConcept: {},
        onStatus: (message) => setStatus(message, "ready"),
        onOpenWiki: (selection) => {
          if (selection?.id) location.href = `/#/wiki?concept=${encodeURIComponent(selection.id)}`;
        },
        onViewSources: () => { location.href = "/#/sources"; },
      });
      setStatus(`Full production graph loaded: ${payload.nodes.length} nodes, ${payload.edges.length} edges.`, "ready");
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      setStatus(`Full graph blocked: ${message}`, "blocked");
      app.innerHTML = `
        <section class="state-panel" data-state="full-graph-blocked">
          <h3>Full production graph unavailable</h3>
          <p>${escapeHtml(message)}</p>
          <p>The smaller Concept Graph remains available, but it is not presented as the full corpus graph.</p>
        </section>
      `;
    }
  }

  main();
})();
