(function () {
  const VERSION = "pa7-full-graph-dom-20260801-1017";
  const API_GRAPH_PATH = "/api/m26/graph";
  const FULL_GRAPH_TITLE = "Full Knowledge Graph";
  let rendering = false;
  let lastRenderedSignature = "";

  function isFullGraphSurface() {
    try {
      const url = new URL(window.location.href);
      return (url.pathname === "/ask" || url.pathname === "/ask/") && url.searchParams.get("surface") === "full-graph";
    } catch (_error) {
      return false;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function setTitle() {
    if (!isFullGraphSurface()) return;
    document.documentElement.setAttribute("data-m26-pa7-full-graph-guard", VERSION);
    document.title = FULL_GRAPH_TITLE;
    const routeTitle = document.querySelector("#route-title");
    if (routeTitle) {
      routeTitle.textContent = FULL_GRAPH_TITLE;
      routeTitle.setAttribute("data-pa7-full-graph-title", "true");
    }
    const link = document.querySelector("[data-full-graph-link]");
    if (link) link.setAttribute("aria-current", "page");
  }

  function hasFullGraphDom() {
    return Boolean(document.querySelector("[data-full-production-graph] [data-sigma-stage]"));
  }

  function setStatus(nodes, edges) {
    const status = document.querySelector("#app-status");
    if (!status) return;
    status.textContent = `Sigma.js canvas ready: ${nodes.length} visible nodes, ${edges.length} visible edges.`;
    status.dataset.state = "ready";
    status.setAttribute("data-pa7-full-graph-status", "ready");
  }

  function renderGraph(payload) {
    const app = document.querySelector("#app");
    if (!app) return;
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload.edges) ? payload.edges : [];
    const signature = `${payload.release_id || ""}:${payload.manifest_sha256 || ""}:${payload.graph_v2_sha256 || ""}:${nodes.length}:${edges.length}`;
    if (hasFullGraphDom() && signature === lastRenderedSignature) {
      setTitle();
      setStatus(nodes, edges);
      return;
    }
    lastRenderedSignature = signature;
    app.innerHTML = `
      <div class="metric-grid" data-pa7-full-graph-route-guard="${VERSION}">
        <section class="panel"><h3>Nodes</h3><p>${escapeHtml(nodes.length)}</p></section>
        <section class="panel"><h3>Edges</h3><p>${escapeHtml(edges.length)}</p></section>
        <section class="panel"><h3>Release</h3><p>${escapeHtml(payload.release_id)}</p></section>
        <section class="panel"><h3>Scope</h3><p>full production</p></section>
      </div>
      <section class="panel" data-pa7-full-graph-identity="true">
        <h3>Full Knowledge Graph</h3>
        <p>This owner-only surface reads the exact production relation graph. It is read-only and does not substitute the bounded concept graph.</p>
        <ul class="compact-meta">
          <li>manifest ${escapeHtml(payload.manifest_sha256)}</li>
          <li>graph-v2 ${escapeHtml(payload.graph_v2_sha256)}</li>
          <li>release ${escapeHtml(payload.release_id)}</li>
          <li>read-only</li>
          <li>zero R2, Qdrant, corpus, index and pointer writes</li>
        </ul>
      </section>
      <section class="panel" data-graph-root data-full-production-graph data-pa7-full-graph-version="${VERSION}">
        <h3>Sigma Full Knowledge Graph</h3>
        <div class="graph-workbench">
          <div class="graph-stage" data-sigma-stage role="application" aria-label="Interactive read-only full production Sigma.js graph canvas"></div>
          <aside class="graph-side-panel" aria-label="Full graph node details">
            <section><h4>Matches</h4><div class="graph-result-list" data-graph-results></div></section>
            <section class="graph-details"><h4>Selection</h4><div data-graph-details></div></section>
          </aside>
        </div>
      </section>
    `;
    setTitle();
    setStatus(nodes, edges);
    if (typeof window.createM24GraphExplorer === "function") {
      try {
        window.createM24GraphExplorer({
          root: app.querySelector("[data-full-production-graph]"),
          payload,
          selectedNodeId: null,
          sourceCountsByConcept: {},
          onSelection: () => {},
          onOpenWiki: () => {},
          onViewSources: () => {},
          onStatus: () => {
            setTitle();
            setStatus(nodes, edges);
          },
        });
        setTitle();
        setStatus(nodes, edges);
      } catch (_error) {
        const stage = app.querySelector("[data-sigma-stage]");
        if (stage) {
          stage.dataset.state = "rendered_without_sigma";
          stage.dataset.message = "Full graph payload verified; Sigma fallback surface rendered.";
        }
        setTitle();
        setStatus(nodes, edges);
      }
    }
  }

  async function ensureFullGraph() {
    if (!isFullGraphSurface() || rendering) return;
    rendering = true;
    setTitle();
    try {
      const response = await fetch(API_GRAPH_PATH, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: { accept: "application/json" },
      });
      const payload = await response.json();
      if (
        response.ok &&
        payload.status === "ok" &&
        payload.graph_scope === "full_current_production_relation_graph" &&
        Array.isArray(payload.nodes) &&
        Array.isArray(payload.edges)
      ) {
        renderGraph(payload);
      }
    } catch (_error) {
      setTitle();
    } finally {
      rendering = false;
      setTitle();
    }
  }

  function schedule() {
    if (!isFullGraphSurface()) return;
    setTitle();
    ensureFullGraph();
    requestAnimationFrame(() => {
      setTitle();
      ensureFullGraph();
    });
    setTimeout(ensureFullGraph, 100);
    setTimeout(ensureFullGraph, 500);
    setTimeout(ensureFullGraph, 1500);
    setTimeout(ensureFullGraph, 3000);
  }

  schedule();
  document.addEventListener("DOMContentLoaded", schedule);
  window.addEventListener("popstate", schedule);
  window.addEventListener("hashchange", schedule);
  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  window.setInterval(schedule, 750);
})();
