(function () {
  const API_QUERY_PATH = "/api/m26/query";

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

  function render(options) {
    const state = options.state;
    const escapeHtml = options.escapeHtml;
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
