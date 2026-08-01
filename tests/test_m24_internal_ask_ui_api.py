from __future__ import annotations

import http.server
import json
import socket
import threading
from pathlib import Path

from playwright.sync_api import expect

from knowledge_engine.m24_internal_product_deployment import SITE_ROOT


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_m24_internal_site_exposes_visible_ask_entry_and_graph_route() -> None:
    index = _text(SITE_ROOT / "index.html")
    app_js = _text(SITE_ROOT / "app.js")
    ask_js = _text(SITE_ROOT / "m26-ask.js")

    assert '<a href="/ask" data-route-link="ask">Ask Knowledge Engine</a>' in index
    assert 'data-route-link="graph"' in index
    assert "Bounded Concept Graph" in index or "Graph Explorer" in index
    assert '<script src="m26-ask.js"></script>' in index
    assert 'ask: "Ask Knowledge Engine"' in app_js
    assert 'location.pathname === "/ask"' in app_js
    assert "window.M26AskSurface.render" in app_js
    assert "window.M26AskSurface.wire" in app_js
    assert 'const API_QUERY_PATH = "/api/m26/query";' in ask_js
    assert "<textarea" in ask_js
    assert "aria-keyshortcuts" in ask_js
    assert "data-ask-answer" in ask_js
    assert "citation-chip" in ask_js
    assert "data-ask-sources" in ask_js


def test_worker_api_verifies_owner_access_jwt_and_falls_back_safely() -> None:
    worker = _text(SITE_ROOT / "_worker.js")

    assert "/api/m26/query" in worker
    assert "/api/m26/health" in worker
    assert "verifyOwnerAccess" in worker
    assert "verifyAccessJwtPayload" in worker
    assert "decodeAccessJwtPayload" in worker
    assert "cf-access-jwt-assertion" in worker
    assert "cf-access-authenticated-user-email" in worker
    assert "ACCESS_TEAM_DOMAIN" in worker
    assert "ACCESS_AUD" in worker
    assert "M26_OWNER_EMAIL_SHA256" in worker
    assert "KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" in worker
    assert "cloudflare_access_jwt_verified_email_hash" in worker
    assert "cloudflare_access_jwt_payload_email_hash_outer_access_boundary" in worker
    assert "cloudflare_access_authenticated_email_header_hash" in worker
    assert "M26_QUERY_BACKEND_URL" in worker
    assert "M26_QUERY_BACKEND_TOKEN" in worker
    assert "crypto.subtle.verify" in worker
    assert "crypto.subtle.digest" in worker
    assert "timingSafeEqualHex" in worker
    assert "env.ASSETS.fetch(request)" in worker
    assert worker.index("const admission = await verifyOwnerAccess") < worker.index(
        "const backend = env.M26_QUERY_BACKEND_URL"
    )
    assert worker.index("if (!admission)") < worker.index("fetch(backendUrl")
    assert "MINIMAX_API_KEY" not in worker
    assert "CLOUDFLARE_API_TOKEN" not in worker
    assert "QDRANT_API_KEY" not in worker


def test_browser_ask_surface_renders_answer_citations_sources_and_trace() -> None:
    with _ask_smoke_server() as base:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/")
            expect(page.get_by_role("link", name="Ask Knowledge Engine")).to_be_visible()
            expect(page.locator('[data-route-link="graph"]')).to_be_visible()
            page.get_by_role("link", name="Ask Knowledge Engine").click()
            expect(page.locator("#route-title")).to_have_text("Ask Knowledge Engine")
            expect(page.locator("#ask-question")).to_be_visible()
            page.locator("#ask-question").fill(
                "Compare routers and adaptive planning for permission-first controls."
            )
            page.get_by_role("button", name="Ask").click()
            expect(page.locator("[data-ask-answer]")).to_contain_text("Comparison")
            expect(page.locator(".citation-chip")).to_have_count(2)
            expect(page.locator("[data-ask-citations]")).to_contain_text(
                "source_blog_agent_execution_paths"
            )
            expect(page.locator("[data-ask-sources]")).to_contain_text(
                "source_blog_agent_planning_strategies"
            )
            expect(page.locator("[data-ask-relationship]")).to_contain_text(
                "distinct sources 2"
            )
            expect(page.locator("[data-ask-answer]")).to_contain_text("trace m26pa7aq_test")
            page.goto(f"{base}/ask")
            expect(page.locator("#route-title")).to_have_text("Ask Knowledge Engine")
            browser.close()


class _AskSmokeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/ask", "/ask/"}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/m26/query":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        body = json.dumps(_sample_web_response()).encode("utf-8")
        self.send_response(200)
        self.send_header("cache-control", "no-store")
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ask_smoke_server:
    def __enter__(self) -> str:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        handler = lambda *args, **kwargs: _AskSmokeHandler(  # noqa: E731
            *args,
            directory=SITE_ROOT.as_posix(),
            **kwargs,
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{port}"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _sample_web_response() -> dict[str, object]:
    return {
        "schema_version": "knowledge-engine-m26-pa7-ask-web-response/v1",
        "status": "owner_only_cited_answer",
        "terminal_status": "verified_answer_ready_candidate",
        "trace_id": "m26pa7aq_test",
        "question_sha256": "a" * 64,
        "answer_text": (
            "Comparison: routers define boundaries [claim_1_ref_1]; planning revises "
            "assumptions [claim_1_ref_2]."
        ),
        "safe_abstention": False,
        "reason_codes": [],
        "citations": [
            {
                "number": 1,
                "citation_id": "claim_1_ref_1",
                "source_identity": "source_blog_agent_execution_paths",
                "source_id": "source_blog_agent_execution_paths",
                "evidence_type": "passage",
                "section_id": "concepts/agent-execution-paths#router",
                "concept_id": "concepts/agent-execution-paths",
                "locator_id": "loc_1",
                "source_artifact_sha256": "b" * 64,
                "exact_quote_sha256": "c" * 64,
                "runtime_owned_locator": True,
            },
            {
                "number": 2,
                "citation_id": "claim_1_ref_2",
                "source_identity": "source_blog_agent_planning_strategies",
                "source_id": "source_blog_agent_planning_strategies",
                "evidence_type": "passage",
                "section_id": "concepts/agent-planning-strategies#adaptive-planning",
                "concept_id": "concepts/agent-planning-strategies",
                "locator_id": "loc_2",
                "source_artifact_sha256": "d" * 64,
                "exact_quote_sha256": "e" * 64,
                "runtime_owned_locator": True,
            },
        ],
        "sources": [
            {
                "source_identity": "source_blog_agent_execution_paths",
                "source_id": "source_blog_agent_execution_paths",
                "evidence_types": ["passage"],
                "section_ids": ["concepts/agent-execution-paths#router"],
                "concept_ids": ["concepts/agent-execution-paths"],
                "citation_numbers": [1],
                "source_artifact_sha256": "b" * 64,
                "release_id": "20260720T160000Z-46137c97263e",
            },
            {
                "source_identity": "source_blog_agent_planning_strategies",
                "source_id": "source_blog_agent_planning_strategies",
                "evidence_types": ["passage"],
                "section_ids": ["concepts/agent-planning-strategies#adaptive-planning"],
                "concept_ids": ["concepts/agent-planning-strategies"],
                "citation_numbers": [2],
                "source_artifact_sha256": "d" * 64,
                "release_id": "20260720T160000Z-46137c97263e",
            },
        ],
        "relationship_summary": {
            "intent_class": "cross_document_comparison",
            "relation": "contrasts_with",
            "selected_evidence_ids": ["ev_1", "ev_2"],
            "selected_graph_edge_ids": [],
        },
        "multi_evidence_verification": {
            "claim_count": 1,
            "support_ref_count": 2,
            "distinct_source_count": 2,
            "locator_validity": 1.0,
            "support_precision": 1.0,
        },
        "accounting": {
            "provider_invoked": True,
            "provider_call_count": 1,
            "payg_equivalent_cost_usd": "0.00001",
            "latency_ms": 25,
        },
        "privacy": {"raw_query_persisted": False},
        "mutations": {"canonical_writes": 0},
    }
