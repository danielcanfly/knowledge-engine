from __future__ import annotations


def enable_feedback_widget_javascript(script: str) -> str:
    replacements = [
        (
            '      release: "Release"\n',
            '      release: "Release",\n'
            '      helpful: "Helpful",\n'
            '      unhelpful: "Not helpful",\n'
            '      correction: "Suggest a correction",\n'
            '      correctionPlaceholder: "Describe what should be corrected…",\n'
            '      sendFeedback: "Send feedback",\n'
            '      feedbackSent: "Feedback received for review.",\n'
            '      feedbackDuplicate: "This feedback was already received.",\n'
            '      feedbackFailed: "Feedback could not be submitted."\n',
        ),
        (
            '      release: "版本"\n',
            '      release: "版本",\n'
            '      helpful: "有幫助",\n'
            '      unhelpful: "沒有幫助",\n'
            '      correction: "提出修正",\n'
            '      correctionPlaceholder: "說明需要修正的內容…",\n'
            '      sendFeedback: "送出回饋",\n'
            '      feedbackSent: "回饋已送交審查。",\n'
            '      feedbackDuplicate: "這項回饋已經收到。",\n'
            '      feedbackFailed: "目前無法送出回饋。"\n',
        ),
        (
            '    @media (max-width: 600px) {',
            '''    .ke-feedback {
      display: grid;
      gap: 9px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
    }
    .ke-feedback-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .ke-feedback-button {
      min-height: 36px;
      border: 1px solid color-mix(in srgb, currentColor 22%, transparent);
      border-radius: 999px;
      padding: 7px 12px;
      background: Canvas;
      color: CanvasText;
      font: inherit;
      cursor: pointer;
    }
    .ke-feedback-button:disabled { opacity: .55; cursor: wait; }
    .ke-feedback-editor { display: grid; gap: 8px; }
    .ke-feedback-input {
      min-height: 82px;
      resize: vertical;
      border: 1px solid color-mix(in srgb, currentColor 22%, transparent);
      border-radius: 12px;
      padding: 10px 12px;
      background: Canvas;
      color: CanvasText;
      font: inherit;
    }
    .ke-feedback-status { min-height: 1.3em; font-size: .82rem; opacity: .72; }
    @media (max-width: 600px) {''',
        ),
        (
            '''      } else if (event === "source_cards") {
        state.cards = Array.isArray(payload.items) ? payload.items : [];
      } else if (event === "done" && state.meta) {''',
            '''      } else if (event === "citations") {
        state.citations = Array.isArray(payload.items) ? payload.items : [];
      } else if (event === "source_cards") {
        state.cards = Array.isArray(payload.items) ? payload.items : [];
      } else if (event === "done" && state.meta) {''',
        ),
        (
            '      const state = { meta: null, cards: [] };',
            '      const state = { meta: null, cards: [], citations: [] };',
        ),
        (
            '''        this.renderSources(turn.assistant, state.cards);
        this.renderMeta(turn, state.meta);''',
            '''        this.renderSources(turn.assistant, state.cards);
        this.renderMeta(turn, state.meta);
        this.renderFeedback(turn, state);''',
        ),
    ]
    for old, new in replacements:
        if old not in script:
            raise ValueError("widget feedback contract changed unexpectedly")
        script = script.replace(old, new, 1)

    marker = '''    async submit() {
'''
    methods = r'''    feedbackEndpoint() {
      const configured = this.getAttribute("data-feedback-endpoint");
      if (configured) return new URL(configured, document.baseURI);
      const askEndpoint = endpointFor(this);
      return new URL("/v1/feedback", askEndpoint.origin);
    }

    feedbackTarget(state) {
      const citation = state.citations[0] || null;
      const card = state.cards[0] || null;
      return {
        citation_id: citation ? citation.citation_id : null,
        source_card_id: citation
          ? citation.source_card_id
          : (card ? card.source_card_id : null),
        concept_id: citation
          ? citation.concept_id
          : (card && card.concept_ids ? card.concept_ids[0] : null),
        section_id: citation
          ? citation.section_id
          : (card && card.section_ids ? card.section_ids[0] : null)
      };
    }

    async submitFeedback(type, message, state, statusNode, controls) {
      if (!state.meta) return;
      controls.forEach((control) => { control.disabled = true; });
      const endpoint = this.feedbackEndpoint();
      const target = this.feedbackTarget(state);
      const body = {
        feedback_type: type,
        request_id: state.meta.request_id,
        release_id: state.meta.release_id,
        audience: state.meta.audience,
        locale: this.language
      };
      if (message) body.message = message;
      for (const [key, value] of Object.entries(target)) {
        if (value) body[key] = value;
      }
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          credentials: endpoint.origin === window.location.origin
            ? "same-origin"
            : "omit",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify(body)
        });
        if (!response.ok) throw new Error("feedback rejected");
        const receipt = await response.json();
        statusNode.textContent = receipt.status === "duplicate"
          ? this.copy.feedbackDuplicate
          : this.copy.feedbackSent;
      } catch (error) {
        statusNode.textContent = this.copy.feedbackFailed;
        controls.forEach((control) => { control.disabled = false; });
      }
    }

    renderFeedback(turn, state) {
      if (!state.meta || state.meta.status === "not_found") return;
      const container = node("div", "ke-feedback");
      const actions = node("div", "ke-feedback-actions");
      const statusNode = node("div", "ke-feedback-status");
      statusNode.setAttribute("role", "status");
      statusNode.setAttribute("aria-live", "polite");
      const helpful = node("button", "ke-feedback-button", this.copy.helpful);
      const unhelpful = node(
        "button",
        "ke-feedback-button",
        this.copy.unhelpful
      );
      const correction = node(
        "button",
        "ke-feedback-button",
        this.copy.correction
      );
      for (const control of [helpful, unhelpful, correction]) {
        control.type = "button";
      }
      const controls = [helpful, unhelpful, correction];
      helpful.addEventListener("click", () => {
        this.submitFeedback("helpful", null, state, statusNode, controls);
      });
      unhelpful.addEventListener("click", () => {
        this.submitFeedback("unhelpful", null, state, statusNode, controls);
      });
      correction.addEventListener("click", () => {
        if (container.querySelector(".ke-feedback-editor")) return;
        const editor = node("div", "ke-feedback-editor");
        const input = node("textarea", "ke-feedback-input");
        input.maxLength = 2000;
        input.placeholder = this.copy.correctionPlaceholder;
        input.setAttribute("aria-label", this.copy.correction);
        const submit = node(
          "button",
          "ke-feedback-button",
          this.copy.sendFeedback
        );
        submit.type = "button";
        controls.push(input, submit);
        submit.addEventListener("click", () => {
          const message = input.value.trim();
          if (!message) return;
          const target = this.feedbackTarget(state);
          const type = target.concept_id || target.section_id
            ? "factual_correction"
            : "missing_coverage";
          this.submitFeedback(type, message, state, statusNode, controls);
        });
        editor.append(input, submit);
        container.insertBefore(editor, statusNode);
        input.focus();
      });
      actions.append(helpful, unhelpful, correction);
      container.append(actions, statusNode);
      turn.assistant.append(container);
    }

'''
    if marker not in script:
        raise ValueError("widget submit contract changed unexpectedly")
    return script.replace(marker, methods + marker, 1)
