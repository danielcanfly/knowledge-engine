(function () {
  const API_QUERY_PATH = "/api/m26/query";
  const API_GRAPH_PATH = "/api/m26/graph";

  function isFullGraphSurface() {
    return new URLSearchParams(location.search).get("surface") === "full-graph";
  }

  function compactList(items, escapeHtml) {
    if (!Array.isArray(items) || items.length === 0) return "";
    return `
      <ul class="compact-meta">
        ${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    `;
  }

  function answerWithInlineCitations(response, escapeHtml) {
    const citations = Array.isArray(response.citations) ? response.citations : [];
    const numbersById = new Map(
      citations.map((citation) => [citation.citation_id, citation.number])
    );
    return escapeHtml(response.answer_text || "").replace(
      /\[([A-Za-z0-9_-]+)\]/g,
      (match, citationId) => {
        const number = numbersById.get(citationId);
        if (!number) return match;
        return `<a class="citation-chip" href="#citation-${number}">[${number}]</a>`;
      }
    );
  }

  function renderCitations(response, escapeHtml) {
    const citations = Array.isArray(response.citations) ? response.citations : [];
    if (!citations.length) {
      return `
        <section class="state-panel" data-state="ask-no-citations">
          <h3>No citations</h3>
          <p>${escapeHtml((response.reason_codes || []).join(", ") || "No cited evidence was returned.")}</p>
        </section>
      `;
    }
    return `
      <section class="panel" data-ask-citations>
        <h3>Citations</h3>
        <div class="citation-list">
          ${citations.map((citation) => `
            <article id="citation-${escapeHtml(citation.number)}">
              <h4>[${escapeHtml(citation.number)}] ${escapeHtml(citation.source_identity || citation.source_id)}</h4>
              ${compactList([
                citation.evidence_type,
                citation.section_id,
                citation.concept_id,
                `locator ${citation.locator_id}`,
                `artifact ${citation.source_artifact_sha256}`,
                `quote ${citation.exact_quote_sha256}`,
              ].filter(Boolean), escapeHtml)}
            </article>
          `).join("")}
        </div>
      </section>
    `;
  }

  function renderSources(response, escapeHtml) {
    const sources = Array.isArray(response.sources) ? response.sources : [];
    return `
      <section class="panel" data-ask-sources>
        <h3>Sources</h3>
        <div class="result-list">
          ${sources.map((source) => `
            <article>
              <h4>${escapeHtml(source.source_identity || source.source_id)}</h4>
              ${compactList([
                `citations ${(source.citation_numbers || []).join(", ")}`,
                `types ${(source.evidence_types || []).join(", ")}`,
                `release ${source.release_id}`,
                `artifact ${source.source_artifact_sha256}`,
                ...((source.section_ids || []).slice(0, 3)),
              ].filter(Boolean), escapeHtml)}
            </article>
          `).join("") || `
            <section class="state-panel" data-state="ask-no-sources">
              <h3>No sources</h3>
              <p>No source cards were returned for this terminal response.</p>
            </section>
          `}
        </div>
      </section>
    `;
  }

  function renderRelationship(response, escapeHtml) {
    const relationship = response.relationship_summary || {};
    const verification = response.multi_evidence_verification || {};
    return `
      <section class="panel" data-ask-relationship>
        <h3>Relationship and verification</h3>
        ${compactList([
          `intent ${relationship.intent_class || "direct_grounded_knowledge"}`,
          `relation ${relationship.relation || "none"}`,
          `selected evidence ${(relationship.selected_evidence_ids || []).length}`,
          `graph edges ${(relationship.selected_graph_edge_ids || []).join(", ") || "none"}`,
          `claims ${verification.claim_count ?? 0}`,
          `support refs ${verification.support_ref_count ?? 0}`,
          `distinct sources ${verification.distinct_source_count ?? 0}`,
          `locator validity ${verification.locator_validity ?? "n/a"}`,
          `support precision ${verification.support_precision ?? "n/a"}`,
        ], escapeHtml)}
      </section>
    `;
  }

  function renderResponse(response, escapeHtml) {
    const isAbstention = response.safe_abstention || response.status !== "owner_only_cited_answer";
    return `
      <section class="panel" data-ask-answer data-state="${isAbstention ? "safe-abstention" : "answered"}">
        <h3>${isAbstention ? "Safe abstention" : "Answer"}</h3>
        <p>${answerWithInlineCitations(response, escapeHtml) || escapeHtml((response.reason_codes || []).join(", ") || "No answer text was returned.")}</p>
        ${compactList([
          `trace ${response.trace_id}`,
          `terminal ${response.terminal_status}`,
          `question ${response.question_sha256}`,
          `provider calls ${response.accounting?.provider_call_count ?? 0}`,
          `cost ${response.accounting?.payg_equivalent_cost_usd ?? "0"}`,
        ], escapeHtml)}
      </section>
      <div class="surface-split ask-evidence-split">
        <div>
          ${renderCitations(response, escapeHtml)}
          ${renderSources(response, escapeHtml)}
        </div>
        ${renderRelationship(response, escapeHtml)}
      </div>
    `;
  }

  function renderFullGraph(options) {
    const state = options.state;
    const escapeHtml = options.escapeHtml;
    const routeTitle = document.querySelector("#route-title");
    if (routeTitle) routeTitle.textContent = "Full Knowledge Graph";
    const fullGraphLink = document.querySelector("[data-full-graph-link]");
    if (fullGraphLink) fullGraphLink.setAttribute("aria-current", "page");
    const payload = state.m26FullGraph;
    if (state.m26FullGraphLoading) {
      return `
        <section class="state-panel" data-state="full-graph-loading">
          <h3>Loading Full Knowledge Graph</h3>
          <p>Reading and verifying the owner-only production graph.</p>
        </section>
      `;
    }
    if (state.m26FullGraphError) {
      return `
        <section class="state-panel" data-state="full-graph-blocked">
          <h3>Full production graph blocked</h3>
          <p>${escapeHtml(state.m26FullGraphError)}</p>
          <p>The smaller Bounded Concept Graph remains available, but it is not substituted for the full graph.</p>
        </section>
      `;
    }
    if (!payload) {
      return `
        <section class="state-panel" data-state="full-graph-ready-to-load">
          <h3>Full Knowledge Graph</h3>
          <p>Preparing the exact production graph binding.</p>
        </section>
      `;
    }
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const edges = Array.isArray(payload.edges) ? payload.edges : [];
    return `
      <div class="metric-grid">
        <section class="panel"><h3>Nodes</h3><p>${escapeHtml(nodes.length)}</p></section>
        <section class="panel"><h3>Edges</h3><p>${escapeHtml(edges.length)}</p></section>
        <section class="panel"><h3>Release</h3><p>${escapeHtml(payload.release_id)}</p></section>
        <section class="panel"><h3>Scope</h3><p>full production</p></section>
      </div>
      <section class="panel">
        <h3>Verified graph identity</h3>
        <p>This surface reads the exact production relation graph through the owner-only runtime. The 20-node M24 view remains separately labelled as the Bounded Concept Graph.</p>
        ${compactList([
          `manifest ${payload.manifest_sha256}`,
          `graph-v2 ${payload.graph_v2_sha256}`,
          `pointer ${payload.binding?.production_pointer_sha256}`,
          `inventory artifact ${payload.binding?.inventory_artifact_id}`,
          "read-only",
          "zero R2, Qdrant, corpus, index and pointer writes",
        ], escapeHtml)}
      </section>
      <section class="panel" data-graph-root data-full-production-graph>
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

  function render(options) {
    const state = options.state;
    const escapeHtml = options.escapeHtml;
    if (isFullGraphSurface()) return renderFullGraph(options);
    return `
      <form class="ask-form" data-ask-form>
        <label for="ask-question">Ask Knowledge Engine</label>
        <textarea
          id="ask-question"
          name="question"
          rows="5"
          maxlength="2000"
          aria-keyshortcuts="Control+Enter Meta+Enter"
          ${state.askLoading ? "disabled" : ""}
        >${escapeHtml(state.askQuestion || "")}</textarea>
        <div class="detail-actions">
          <button type="submit" ${state.askLoading ? "disabled" : ""}>Ask</button>
        </div>
      </form>
      ${state.askLoading ? `
        <section class="state-panel" data-state="ask-loading">
          <h3>Running query</h3>
          <p>The owner-only runtime is verifying evidence and citations.</p>
        </section>
      ` : ""}
      ${state.askError ? `
        <section class="state-panel" data-state="ask-error">
          <h3>Query blocked</h3>
          <p>${escapeHtml(state.askError)}</p>
        </section>
      ` : ""}
      ${state.askResponse ? renderResponse(state.askResponse, escapeHtml) : `
        <section class="panel" data-state="ask-ready">
          <h3>Owner-only query surface</h3>
          <p>Responses come from the canonical M26.PA.7 runtime through the trusted same-origin API.</p>
        </section>
      `}
    `;
  }

  async function loadFullGraph(options) {
    const state = options.state;
    if (state.m26FullGraph || state.m26FullGraphLoading) return;
    state.m26FullGraphLoading = true;
    state.m26FullGraphError = "";
    options.setStatus("Loading and verifying full production graph.", "loading");
    options.render();
    try {
      const response = await fetch(API_GRAPH_PATH, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: { accept: "application/json" },
      });
      let payload = null;
      try { payload = await response.json(); } catch (_error) {}
      if (!response.ok) {
        const reason = payload?.detail?.reason_code || payload?.reason_code || `HTTP_${response.status}`;
        throw new Error(reason);
      }
      if (
        !payload ||
        payload.status !== "ok" ||
        payload.graph_scope !== "full_current_production_relation_graph" ||
        !Array.isArray(payload.nodes) ||
        !Array.isArray(payload.edges)
      ) {
        throw new Error("M26_OWNER_GRAPH_PAYLOAD_INVALID");
      }
      state.m26FullGraph = payload;
      const releaseElement = document.querySelector("#release-id");
      const manifestElement = document.querySelector("#manifest-sha");
      if (releaseElement) releaseElement.textContent = payload.release_id;
      if (manifestElement) manifestElement.textContent = payload.manifest_sha256;
      options.setStatus(`Full production graph verified: ${payload.nodes.length} nodes, ${payload.edges.length} edges.`, "ready");
    } catch (error) {
      state.m26FullGraphError = String(error && error.message ? error.message : "M26_OWNER_GRAPH_NETWORK_ERROR");
      options.setStatus("Full production graph blocked.", "blocked");
    } finally {
      state.m26FullGraphLoading = false;
      options.render();
    }
  }

  function initializeFullGraph(options) {
    const state = options.state;
    const root = options.app.querySelector("[data-full-production-graph]");
    if (!root || !state.m26FullGraph || typeof window.createM24GraphExplorer !== "function") return;
    state.graphExplorer = window.createM24GraphExplorer({
      root,
      payload: state.m26FullGraph,
      selectedNodeId: null,
      sourceCountsByConcept: {},
      onSelection: () => {},
      onOpenWiki: (selection) => {
        if (selection?.id && String(selection.id).startsWith("concepts/")) {
          location.href = `/#/wiki?concept=${encodeURIComponent(selection.id)}`;
        }
      },
      onViewSources: () => { location.href = "/#/sources"; },
      onStatus: (message) => options.setStatus(message, "ready"),
    });
  }

  async function submitAsk(options, form) {
    const state = options.state;
    const renderApp = options.render;
    const setStatus = options.setStatus;
    const formData = new FormData(form);
    const question = String(formData.get("question") || "").trim();
    state.askQuestion = question;
    state.askError = "";
    state.askResponse = null;
    if (!question) {
      state.askError = "M26_ASK_QUESTION_EMPTY";
      renderApp();
      return;
    }
    state.askLoading = true;
    setStatus("Ask query running.", "loading");
    renderApp();
    try {
      const response = await fetch(API_QUERY_PATH, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
      if (!response.ok) {
        const reason = payload?.detail?.reason_code || payload?.reason_code || `HTTP_${response.status}`;
        throw new Error(reason);
      }
      state.askResponse = payload;
      const terminal = payload.safe_abstention ? "Ask safely abstained." : "Ask answer verified.";
      setStatus(terminal, "ready");
    } catch (error) {
      state.askError = String(error && error.message ? error.message : "M26_ASK_NETWORK_ERROR");
      setStatus("Ask query blocked.", "blocked");
    } finally {
      state.askLoading = false;
      renderApp();
    }
  }

  function wire(options) {
    if (isFullGraphSurface()) {
      if (!options.state.m26FullGraph && !options.state.m26FullGraphLoading) {
        loadFullGraph(options);
      } else {
        initializeFullGraph(options);
      }
      return;
    }
    const form = options.app.querySelector("[data-ask-form]");
    const textarea = options.app.querySelector("#ask-question");
    if (!form || !textarea) return;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!options.state.askLoading) submitAsk(options, form);
    });
    textarea.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        if (!options.state.askLoading) submitAsk(options, form);
      }
    });
  }

  window.M26AskSurface = { render, wire };
})();
