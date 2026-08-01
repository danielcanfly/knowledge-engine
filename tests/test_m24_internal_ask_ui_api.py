from __future__ import annotations

import http.server
import io
import json
import socket
import subprocess
import tarfile
import tempfile
import threading
from contextlib import AbstractContextManager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

SITE_RELATIVE = Path("pilot/m24/internal-product-deployment/site")


def _committed_text(relative: Path) -> str:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative.as_posix()}"],
        text=True,
    )


def test_committed_site_exposes_ask_bounded_graph_and_full_graph() -> None:
    index = _committed_text(SITE_RELATIVE / "index.html")
    full_graph = _committed_text(SITE_RELATIVE / "full-graph.html")
    full_graph_js = _committed_text(SITE_RELATIVE / "m26-full-graph.js")
    app_js = _committed_text(SITE_RELATIVE / "app.js")
    ask_js = _committed_text(SITE_RELATIVE / "m26-ask.js")

    assert '<a href="/ask" data-route-link="ask">Ask Knowledge Engine</a>' in index
    assert "Bounded Concept Graph" in index
    assert 'href="/full-graph"' in index
    assert "Full Knowledge Graph" in index
    assert "m26-pa7-route-prelock.js" not in index
    assert "m26-title-guard.js" not in index
    assert "m26-pa7-full-graph-guard.js" not in index
    assert "m26-ask.js" in index
    assert 'data-pa7-surface="full-knowledge-graph"' in full_graph
    assert 'data-pa7-route-family="dedicated-static-route"' in full_graph
    assert "app.js" not in full_graph
    assert "m26-ask.js" not in full_graph
    assert "m26-full-graph.js" in full_graph
    assert 'ask: "Ask Knowledge Engine"' in app_js
    assert 'location.pathname === "/ask"' in app_js
    assert "window.M26AskSurface.render" in app_js
    assert "window.M26AskSurface.wire" in app_js
    assert 'const API_QUERY_PATH = "/api/m26/query";' in ask_js
    assert 'get("surface") === "full-graph"' not in ask_js
    assert "data-ask-answer" in ask_js
    assert "citation-chip" in ask_js
    assert "data-ask-sources" in ask_js
    assert 'const API_GRAPH_PATH = "/api/m26/graph";' in full_graph_js
    assert "full_current_production_relation_graph" in full_graph_js
    assert "data-full-production-graph" in full_graph_js
    assert 'data-pa7-surface="full-knowledge-graph"' in full_graph_js
    assert "m26-pa7-dedicated-full-graph-route-v1" in full_graph_js


def test_committed_worker_is_owner_only_fail_closed_proxy() -> None:
    worker = _committed_text(SITE_RELATIVE / "_worker.js")

    assert "/api/m26/query" in worker
    assert "/api/m26/health" in worker
    assert "/api/m26/graph" in worker
    assert "/full-graph.html" in worker
    assert "M26_GRAPH_METHOD_NOT_ALLOWED" in worker
    assert "verifyOwnerAccess" in worker
    assert "resolveAccessJwtContract" in worker
    assert "verifyAccessJwt" in worker
    assert "cf-access-jwt-assertion" in worker
    assert "cf-access-authenticated-user-email" not in worker
    assert "ACCESS_TEAM_DOMAIN" in worker
    assert "ACCESS_AUD" in worker
    assert "/cdn-cgi/access/certs" in worker
    assert "RSASSA-PKCS1-v1_5" in worker
    assert "verified_cloudflare_access_jwt_email" in worker
    assert "verified_cloudflare_access_jwt_email_inferred_contract" in worker
    assert "M26_OWNER_EMAIL_SHA256" in worker
    assert "KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH" in worker
    assert "M26_QUERY_BACKEND_URL" in worker
    assert "M26_QUERY_BACKEND_TOKEN" in worker
    assert "crypto.subtle.digest" in worker
    assert "crypto.subtle.verify" in worker
    assert "timingSafeEqualHex" in worker
    assert "env.ASSETS.fetch(request)" in worker
    assert worker.index("const admission = await verifyOwnerAccess") < worker.index(
        "const backend = env.M26_QUERY_BACKEND_URL"
    )
    assert worker.index("if (!admission.ok)") < worker.index("fetch(backendUrl")
    assert "MINIMAX_API_KEY" not in worker
    assert "CLOUDFLARE_API_TOKEN" not in worker
    assert "QDRANT_API_KEY" not in worker


def test_browser_ask_surface_renders_answer_citations_sources_and_trace() -> None:
    with _committed_site() as site_root, _ask_smoke_server(site_root) as base:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/")
            expect(page.get_by_role("link", name="Ask Knowledge Engine")).to_be_visible()
            page.get_by_role("link", name="Ask Knowledge Engine").click()
            expect(page.locator("#route-title")).to_have_text("Ask Knowledge Engine")
            page.locator("#ask-question").fill("Compare routers and adaptive planning.")
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
            expect(page.locator("[data-ask-answer]")).to_contain_text(
                "trace m26pa7aq_test"
            )
            browser.close()


def test_browser_full_graph_surface_loads_exact_owner_graph() -> None:
    with _committed_site() as site_root, _ask_smoke_server(site_root) as base:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"{base}/full-graph")
            expect(page.locator("#route-title")).to_have_text("Full Knowledge Graph")
            expect(page.locator('[data-pa7-surface="full-knowledge-graph"]')).not_to_have_count(0)
            expect(page.locator("[data-full-production-graph]")).to_be_visible()
            expect(page.locator("[data-full-graph-node-count]")).to_have_text("2")
            expect(page.locator("[data-full-graph-edge-count]")).to_have_text("1")
            expect(page.locator("#release-id")).to_have_text("release-full-graph-test")
            expect(page.locator("[data-sigma-stage]")).to_be_visible()
            expect(page.locator("#app-status")).to_contain_text(
                "Sigma.js canvas ready: 2 visible nodes, 1 visible edges."
            )
            browser.close()


def test_browser_full_graph_surface_ignores_stale_spa_hash() -> None:
    with _committed_site() as site_root, _ask_smoke_server(site_root) as base:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/full-graph#/overview")
            expect(page.locator("#route-title")).to_have_text("Full Knowledge Graph")
            expect(page.locator("[data-full-production-graph]")).to_be_visible()
            expect(page.locator("body")).not_to_contain_text("Internal product status")
            expect(page.locator("[data-full-graph-node-count]")).to_have_text("2")
            browser.close()


def test_browser_ask_route_ignores_retired_full_graph_surface_param() -> None:
    with _committed_site() as site_root, _ask_smoke_server(site_root) as base:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/ask?surface=full-graph")
            expect(page.locator("#route-title")).to_have_text("Ask Knowledge Engine")
            expect(page.locator("[data-ask-form]")).to_be_visible()
            expect(page.locator("[data-full-production-graph]")).to_have_count(0)
            browser.close()


class _committed_site(AbstractContextManager[Path]):
    def __enter__(self) -> Path:
        archive = subprocess.check_output(
            ["git", "archive", "--format=tar", "HEAD", SITE_RELATIVE.as_posix()]
        )
        self.temporary = tempfile.TemporaryDirectory()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(self.temporary.name, filter="data")
        return Path(self.temporary.name) / SITE_RELATIVE

    def __exit__(self, *_args: object) -> None:
        self.temporary.cleanup()


class _AskSmokeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path in {"/ask", "/ask/"}:
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path in {"/full-graph", "/full-graph/"}:
            self.path = "/full-graph.html"
            return super().do_GET()
        if parsed.path == "/api/m26/health":
            self._json_response(_sample_health_response())
            return
        if parsed.path == "/api/m26/graph":
            self._json_response(_sample_graph_response())
            return
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/m26/query":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        self._json_response(_sample_web_response())

    def _json_response(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("cache-control", "no-store")
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ask_smoke_server(AbstractContextManager[str]):
    def __init__(self, site_root: Path) -> None:
        self.site_root = site_root

    def __enter__(self) -> str:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        handler = lambda *args, **kwargs: _AskSmokeHandler(  # noqa: E731
            *args,
            directory=self.site_root.as_posix(),
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


def _sample_graph_response() -> dict[str, object]:
    return {
        "schema_version": "knowledge-engine-m26-pa7-owner-full-graph/v1",
        "status": "ok",
        "graph_scope": "full_current_production_relation_graph",
        "release_id": "release-full-graph-test",
        "manifest_sha256": "a" * 64,
        "graph_v2_sha256": "b" * 64,
        "loaded_at": "2026-08-01T00:00:00Z",
        "counts": {"nodes": 2, "edges": 1},
        "nodes": [
            {
                "concept_id": "concepts/alpha",
                "title": "Alpha",
                "description": "Alpha concept",
                "type": "Concept",
                "audience": "internal",
                "tags": ["alpha"],
            },
            {
                "concept_id": "concepts/beta",
                "title": "Beta",
                "description": "Beta concept",
                "type": "Concept",
                "audience": "internal",
                "tags": ["beta"],
            },
        ],
        "edges": [
            {
                "edge_id": "edge-alpha-beta",
                "source": "concepts/alpha",
                "target": "concepts/beta",
                "relation_type": "supports",
                "directed": True,
                "audience": "internal",
            }
        ],
        "available_actions": [
            "select_node",
            "search_node",
            "filter_relation",
            "one_hop",
            "two_hop",
        ],
        "binding": {
            "production_pointer_key": "channels/production.json",
            "production_pointer_sha256": "c" * 64,
            "pa2_acceptance_self_sha256": "d" * 64,
            "inventory_run_id": 30680636103,
            "inventory_artifact_id": 8812152272,
        },
        "authority": {
            "owner_only": True,
            "read_only": True,
            "canonical_writes": 0,
            "corpus_index_content_mutations": 0,
            "production_pointer_mutations": 0,
            "qdrant_write_operations": 0,
            "r2_write_operations": 0,
        },
    }


def _sample_health_response() -> dict[str, object]:
    return {
        "schema_version": "knowledge-engine-m26-pa7-ask-health/v1",
        "status": "ok",
        "canonical_runtime": {
            "entrypoint": "knowledge_engine.m26_ask_api:create_app",
            "build_sha": "backend-build-test",
            "root_sha256": "f" * 64,
        },
        "route": {
            "ask_url": "https://m24-internal.danielcanfly.com/ask",
            "full_graph_url": "https://m24-internal.danielcanfly.com/full-graph",
            "api_query_path": "/api/m26/query",
            "api_health_path": "/api/m26/health",
            "api_graph_path": "/api/m26/graph",
            "owner_only_route": True,
        },
        "privacy": {"browser_secret_delivery": False},
        "mutations": {"canonical_writes": 0, "production_pointer_mutations": 0},
    }


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
