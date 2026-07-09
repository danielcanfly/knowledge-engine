from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel

from .m14_public_contracts import PublicAskResponse

PUBLIC_INTERFACE_SCHEMA = "knowledge-engine-public-interface/v1"
PUBLIC_STREAM_SCHEMA = "knowledge-engine-public-interface-stream/v1"
SUPPORTED_LOCALES = ("en", "zh-TW")


class PublicInterfaceCapabilities(BaseModel):
    schema_version: str = PUBLIC_INTERFACE_SCHEMA
    surfaces: list[Literal["api", "standalone_chat", "blog_widget"]]
    transports: list[Literal["json", "sse"]]
    session_mode: Literal["stateless"]
    default_audience: Literal["public"]
    same_origin_default: bool
    ask_path: str
    stream_path: str
    standalone_path: str
    widget_script_path: str
    supported_locales: list[str]
    max_query_characters: int
    max_results: int
    citation_markers: bool
    source_cards: bool
    stream_event_order: list[str]


def public_interface_capabilities() -> PublicInterfaceCapabilities:
    return PublicInterfaceCapabilities(
        surfaces=["api", "standalone_chat", "blog_widget"],
        transports=["json", "sse"],
        session_mode="stateless",
        default_audience="public",
        same_origin_default=True,
        ask_path="/v1/ask",
        stream_path="/v1/ask/stream",
        standalone_path="/ask",
        widget_script_path="/embed/ask.js",
        supported_locales=list(SUPPORTED_LOCALES),
        max_query_characters=8000,
        max_results=20,
        citation_markers=True,
        source_cards=True,
        stream_event_order=["meta", "answer", "citations", "source_cards", "done"],
    )


def normalize_interface_locale(value: str | None) -> str:
    if value == "zh-TW":
        return "zh-TW"
    return "en"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sse(event: str, event_id: str, payload: object) -> str:
    return f"event: {event}\nid: {event_id}\ndata: {_json(payload)}\n\n"


def _answer_chunks(answer: str | None) -> list[str]:
    if not answer:
        return []
    return [chunk.strip() for chunk in answer.split("\n\n") if chunk.strip()]


def public_interface_sse_events(response: PublicAskResponse) -> Iterator[str]:
    chunks = _answer_chunks(response.answer)
    meta = {
        "schema_version": PUBLIC_STREAM_SCHEMA,
        "request_id": response.request_id,
        "release_id": response.release_id,
        "status": response.status,
        "audience": response.audience,
        "confidence": response.confidence,
        "not_found_reason": response.not_found_reason,
        "session_mode": "stateless",
    }
    yield _sse("meta", f"{response.request_id}:0", meta)
    event_index = 1
    for chunk_index, text in enumerate(chunks):
        yield _sse(
            "answer",
            f"{response.request_id}:{event_index}",
            {"index": chunk_index, "text": text},
        )
        event_index += 1
    yield _sse(
        "citations",
        f"{response.request_id}:{event_index}",
        {"items": [item.model_dump(mode="json") for item in response.citations]},
    )
    event_index += 1
    yield _sse(
        "source_cards",
        f"{response.request_id}:{event_index}",
        {"items": [item.model_dump(mode="json") for item in response.source_cards]},
    )
    event_index += 1
    yield _sse(
        "done",
        f"{response.request_id}:{event_index}",
        {
            "request_id": response.request_id,
            "status": response.status,
            "event_count": event_index + 1,
        },
    )


def standalone_ask_html(locale: str | None = None) -> str:
    language = normalize_interface_locale(locale)
    title = "Ask the Knowledge Wiki" if language == "en" else "詢問知識 Wiki"
    description = (
        "Answers come from the current governed knowledge release."
        if language == "en"
        else "答案來自目前受治理的知識版本。"
    )
    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="{description}">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: Canvas; color: CanvasText; }}
    main {{ width: min(860px, 100%); margin: 0 auto; padding: 32px 16px 64px; }}
    .shell {{ border: 1px solid color-mix(in srgb, CanvasText 18%, transparent); border-radius: 20px; overflow: hidden; }}
    header {{ padding: 24px 24px 8px; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 4vw, 2.25rem); }}
    header p {{ margin: 10px 0 0; opacity: .72; }}
  </style>
</head>
<body>
  <main>
    <section class="shell" aria-labelledby="page-title">
      <header>
        <h1 id="page-title">{title}</h1>
        <p>{description}</p>
      </header>
      <knowledge-ask data-mode="standalone" data-locale="{language}" data-endpoint="/v1/ask/stream"></knowledge-ask>
    </section>
  </main>
  <script src="/embed/ask.js" defer></script>
</body>
</html>
"""


def public_ask_widget_javascript() -> str:
    return r'''(() => {
  "use strict";

  const COPY = {
    "en": {
      title: "Ask AI",
      label: "Question",
      placeholder: "Ask about this knowledge base…",
      submit: "Ask",
      loading: "Searching the governed wiki…",
      answered: "Answered from the current release.",
      degraded: "Answer available, but inspectable sources are unavailable.",
      notFound: "No supported answer was found in the authorized wiki.",
      unauthorized: "This interface is not authorized for the requested audience.",
      unavailable: "The knowledge service is temporarily unavailable.",
      failed: "The request could not be completed.",
      sources: "Sources",
      confidence: "Confidence",
      release: "Release",
      retry: "Try again"
    },
    "zh-TW": {
      title: "詢問 AI",
      label: "問題",
      placeholder: "詢問這個知識庫…",
      submit: "送出",
      loading: "正在搜尋受治理的 Wiki…",
      answered: "已依目前知識版本回答。",
      degraded: "已有答案，但目前沒有可檢視的來源。",
      notFound: "授權範圍內找不到可支持的答案。",
      unauthorized: "此介面沒有要求之受眾權限。",
      unavailable: "知識服務暫時無法使用。",
      failed: "無法完成這次請求。",
      sources: "來源",
      confidence: "信心",
      release: "版本",
      retry: "再試一次"
    }
  };

  const STYLE = `
    :host { display:block; color:inherit; font:inherit; }
    * { box-sizing:border-box; }
    .ke-root { padding:20px 24px 24px; }
    .ke-form { display:grid; gap:10px; }
    .ke-label { font-weight:650; }
    .ke-row { display:flex; gap:10px; align-items:flex-end; }
    .ke-input { flex:1; min-height:74px; resize:vertical; border:1px solid color-mix(in srgb, currentColor 22%, transparent); border-radius:14px; padding:12px 14px; background:Canvas; color:CanvasText; font:inherit; line-height:1.45; }
    .ke-input:focus { outline:2px solid Highlight; outline-offset:2px; }
    .ke-button { min-width:88px; min-height:44px; border:0; border-radius:12px; padding:10px 16px; background:CanvasText; color:Canvas; font:inherit; font-weight:700; cursor:pointer; }
    .ke-button:disabled { opacity:.55; cursor:wait; }
    .ke-status { min-height:1.4em; margin-top:12px; font-size:.9rem; opacity:.72; }
    .ke-turns { display:grid; gap:16px; margin-top:18px; }
    .ke-turn { display:grid; gap:10px; }
    .ke-user { justify-self:end; max-width:min(82%, 640px); padding:10px 13px; border-radius:14px 14px 4px 14px; background:color-mix(in srgb, Highlight 18%, Canvas); white-space:pre-wrap; }
    .ke-assistant { max-width:100%; padding:16px; border:1px solid color-mix(in srgb, currentColor 16%, transparent); border-radius:16px; background:color-mix(in srgb, CanvasText 3%, Canvas); }
    .ke-answer { display:grid; gap:10px; line-height:1.58; }
    .ke-answer p { margin:0; white-space:pre-wrap; }
    .ke-meta { display:flex; flex-wrap:wrap; gap:8px 14px; margin-top:14px; font-size:.8rem; opacity:.68; }
    .ke-notice { margin:0; line-height:1.5; }
    .ke-sources { margin-top:16px; border-top:1px solid color-mix(in srgb, currentColor 12%, transparent); padding-top:12px; }
    .ke-sources summary { cursor:pointer; font-weight:650; }
    .ke-source-list { display:grid; gap:10px; margin:12px 0 0; padding:0; list-style:none; }
    .ke-source { display:grid; gap:3px; }
    .ke-source a { color:LinkText; overflow-wrap:anywhere; font-weight:620; }
    .ke-source small { opacity:.68; }
    .ke-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media (max-width:600px) { .ke-root { padding:16px; } .ke-row { align-items:stretch; flex-direction:column; } .ke-button { width:100%; } .ke-user { max-width:92%; } }
  `;

  function node(tag, className, text) {
    const value = document.createElement(tag);
    if (className) value.className = className;
    if (text !== undefined && text !== null) value.textContent = String(text);
    return value;
  }

  function localeFor(value) {
    return value === "zh-TW" ? "zh-TW" : "en";
  }

  function boundedResults(value) {
    const parsed = Number.parseInt(value || "5", 10);
    if (!Number.isFinite(parsed)) return 5;
    return Math.min(20, Math.max(1, parsed));
  }

  function endpointFor(element) {
    const raw = element.getAttribute("data-endpoint") || "/v1/ask/stream";
    const endpoint = new URL(raw, document.baseURI);
    if (endpoint.origin !== window.location.origin) {
      throw new Error("cross-origin endpoint is disabled");
    }
    return endpoint.toString();
  }

  function parseBlock(block) {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    return data ? { event, payload: JSON.parse(data) } : null;
  }

  async function readEventStream(response, receive) {
    if (!response.body) throw new Error("stream unavailable");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseBlock(block);
        if (parsed) receive(parsed.event, parsed.payload);
        boundary = buffer.indexOf("\n\n");
      }
      if (chunk.done) break;
    }
    if (buffer.trim()) {
      const parsed = parseBlock(buffer);
      if (parsed) receive(parsed.event, parsed.payload);
    }
  }

  class KnowledgeAsk extends HTMLElement {
    connectedCallback() {
      if (this.dataset.ready === "true") return;
      this.dataset.ready = "true";
      this.language = localeFor(this.getAttribute("data-locale"));
      this.copy = COPY[this.language];
      this.maxResults = boundedResults(this.getAttribute("data-max-results"));
      this.mount();
    }

    mount() {
      const root = this.attachShadow({ mode: "open" });
      const style = node("style");
      style.textContent = STYLE;
      root.append(style);

      const shell = node("div", "ke-root");
      const form = node("form", "ke-form");
      const label = node("label", "ke-label", this.getAttribute("data-title") || this.copy.title);
      const inputId = `ke-question-${Math.random().toString(36).slice(2)}`;
      label.htmlFor = inputId;
      const row = node("div", "ke-row");
      const input = node("textarea", "ke-input");
      input.id = inputId;
      input.name = "query";
      input.required = true;
      input.maxLength = 8000;
      input.placeholder = this.getAttribute("data-placeholder") || this.copy.placeholder;
      input.setAttribute("aria-label", this.copy.label);
      const button = node("button", "ke-button", this.copy.submit);
      button.type = "submit";
      row.append(input, button);
      form.append(label, row);

      const status = node("div", "ke-status");
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      const turns = node("div", "ke-turns");
      turns.setAttribute("aria-live", "polite");
      shell.append(form, status, turns);
      root.append(shell);

      this.form = form;
      this.input = input;
      this.button = button;
      this.status = status;
      this.turns = turns;
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        this.submit();
      });
    }

    addTurn(query) {
      const turn = node("article", "ke-turn");
      const user = node("div", "ke-user", query);
      const assistant = node("div", "ke-assistant");
      assistant.setAttribute("aria-label", this.copy.title);
      const answer = node("div", "ke-answer");
      const meta = node("div", "ke-meta");
      assistant.append(answer, meta);
      turn.append(user, assistant);
      this.turns.append(turn);
      turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return { assistant, answer, meta };
    }

    addNotice(container, text) {
      container.append(node("p", "ke-notice", text));
    }

    renderSources(container, cards) {
      if (!Array.isArray(cards) || cards.length === 0) return;
      const details = node("details", "ke-sources");
      details.append(node("summary", "", `${this.copy.sources} (${cards.length})`));
      const list = node("ol", "ke-source-list");
      for (const card of cards) {
        const item = node("li", "ke-source");
        const link = node("a", "", `[${card.ordinal}] ${card.title}`);
        link.href = card.uri;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        const secondary = [card.publisher, card.display_host].filter(Boolean).join(" · ");
        item.append(link, node("small", "", secondary));
        list.append(item);
      }
      details.append(list);
      container.append(details);
    }

    errorMessage(statusCode) {
      if (statusCode === 401 || statusCode === 403) return this.copy.unauthorized;
      if (statusCode === 503) return this.copy.unavailable;
      return this.copy.failed;
    }

    async submit() {
      const query = this.input.value.trim();
      if (!query || this.button.disabled) return;
      this.button.disabled = true;
      this.input.disabled = true;
      this.status.textContent = this.copy.loading;
      const turn = this.addTurn(query);
      this.input.value = "";
      let metaPayload = null;
      let sourceCards = [];
      try {
        const response = await fetch(endpointFor(this), {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Accept": "text/event-stream",
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ query, max_results: this.maxResults, audience: "public" })
        });
        if (!response.ok) {
          this.addNotice(turn.answer, this.errorMessage(response.status));
          this.status.textContent = this.errorMessage(response.status);
          return;
        }
        await readEventStream(response, (event, payload) => {
          if (event === "meta") {
            metaPayload = payload;
            if (payload.status === "not_found") this.addNotice(turn.answer, this.copy.notFound);
            if (payload.status === "degraded") this.status.textContent = this.copy.degraded;
          } else if (event === "answer") {
            turn.answer.append(node("p", "", payload.text));
          } else if (event === "source_cards") {
            sourceCards = Array.isArray(payload.items) ? payload.items : [];
          } else if (event === "done") {
            if (metaPayload && metaPayload.status === "answered") this.status.textContent = this.copy.answered;
            if (metaPayload && metaPayload.status === "not_found") this.status.textContent = this.copy.notFound;
          }
        });
        this.renderSources(turn.assistant, sourceCards);
        if (metaPayload) {
          turn.meta.append(
            node("span", "", `${this.copy.confidence}: ${Math.round(metaPayload.confidence * 100)}%`),
            node("span", "", `${this.copy.release}: ${metaPayload.release_id}`)
          );
        }
      } catch (error) {
        this.addNotice(turn.answer, this.copy.failed);
        this.status.textContent = this.copy.failed;
      } finally {
        this.button.disabled = false;
        this.input.disabled = false;
        this.input.focus();
      }
    }
  }

  if (!customElements.get("knowledge-ask")) {
    customElements.define("knowledge-ask", KnowledgeAsk);
  }
})();
'''
