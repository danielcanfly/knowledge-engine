from __future__ import annotations

import http.server
import json
import socket
import struct
import threading
import zlib
from collections.abc import Iterator

import pytest
from playwright.sync_api import expect

from knowledge_engine.m24_internal_product_deployment import (
    SITE_ROOT,
    build_p6_internal_product_deployment,
)

HARNESS_CONCEPT_ID = "concepts/harness"
NON_HARNESS_CONCEPT_ID = "concepts/agent-execution-paths"
BLOG_DEEP_MARKERS = {
    "Six-dimensional map of LLM agent architectures": (
        "Multi-agent is an organisational choice, not a maturity level"
    ),
    "Agent execution paths": (
        "Simple requests pay the latency and error surface of planning"
    ),
    "Agent decision and planning strategies": (
        "The production objective is not maximum planning freedom"
    ),
}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture(scope="module")
def site_url() -> Iterator[str]:
    build_p6_internal_product_deployment()
    handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
        *args,
        directory=SITE_ROOT,
        **kwargs,
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture()
def page(site_url: str):
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" and "frame-ancestors" not in msg.text
            else None,
        )
        yield page
        context.close()
        browser.close()
    assert not errors


def _png_rows(png: bytes) -> tuple[int, int, list[bytes]]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    width = height = color_type = bit_depth = None
    idat = b""
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        chunk_type = png[offset + 4 : offset + 8]
        data = png[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
        elif chunk_type == b"IDAT":
            idat += data
        elif chunk_type == b"IEND":
            break
    assert width and height and bit_depth == 8 and color_type in {2, 6}
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(idat)
    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        scanline = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        for index in range(stride):
            left = scanline[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                scanline[index] = (scanline[index] + left) & 0xFF
            elif filter_type == 2:
                scanline[index] = (scanline[index] + up) & 0xFF
            elif filter_type == 3:
                scanline[index] = (scanline[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                predictor = left + up - up_left
                pa = abs(predictor - left)
                pb = abs(predictor - up)
                pc = abs(predictor - up_left)
                if pa <= pb and pa <= pc:
                    predictor_value = left
                elif pb <= pc:
                    predictor_value = up
                else:
                    predictor_value = up_left
                scanline[index] = (scanline[index] + predictor_value) & 0xFF
        rows.append(bytes(scanline))
        previous = scanline
    return width, channels, rows


def _screenshot_is_nonblank(png: bytes) -> bool:
    _width, channels, rows = _png_rows(png)
    sample = []
    for row in rows[:: max(len(rows) // 24, 1)]:
        for index in range(0, len(row), channels * max(len(row) // channels // 24, 1)):
            sample.append(tuple(row[index : index + 3]))
    return len(set(sample)) > 8


def _status_text(page) -> str:
    return page.locator("#app-status").inner_text()


def _assert_no_graph_error(page) -> None:
    body = page.locator("body").inner_text()
    assert "could not find a suitable program" not in body
    assert "Graph explorer initialization failed." not in body


def test_m24_14_5_source_documents_are_complete_and_inspectable(page, site_url: str) -> None:
    source_index = json.loads(SITE_ROOT.joinpath("data/source-index.json").read_text())
    source_viewers = json.loads(SITE_ROOT.joinpath("data/source-viewers.json").read_text())
    source_documents = json.loads(SITE_ROOT.joinpath("data/source-documents.json").read_text())

    assert source_index["source_count"] == 7
    assert source_viewers["viewer_count"] == 7
    assert source_documents["source_count"] == 7
    assert len(list(SITE_ROOT.joinpath("data/sources").glob("*.json"))) == 7
    assert {
        row["coverage_status"] for row in source_index["coverage_matrix"]
    } <= {
        "full_snapshot",
        "structured_snapshot",
        "metadata_only_with_reason",
        "blocked_with_exact_reason",
    }

    titles = [row["title"] for row in source_index["coverage_matrix"]]
    for title, marker in BLOG_DEEP_MARKERS.items():
        assert title in titles
        document = next(
            doc
            for doc in source_documents["documents"].values()
            if doc["title"] == title
        )
        assert document["integrity"]["byte_count"] > 20000
        assert document["integrity"]["snapshot_sha256"]
        assert document["origin"]["commit"] == "27e2fe996f878f2129bf510d6a326c02f7d87be5"
        assert marker in document["document"]["body"]

    page.goto(f"{site_url}/#/sources")
    expect(page.locator(".source-card")).to_have_count(7)
    for title in BLOG_DEEP_MARKERS:
        expect(page.locator(".source-card", has_text=title)).to_be_visible()
    assert "github.com\nweb\n5 citations\nsnapshot false" not in page.locator("#app").inner_text()

    cards = page.locator(".source-card")
    second_title = cards.nth(1).locator("h4").inner_text()
    cards.nth(1).get_by_role("button", name="Inspect").click()
    page.wait_for_url("**/#/sources?viewer=viewer_source_blog_agent_execution_paths")
    expect(cards.nth(1)).to_have_attribute("aria-current", "true")
    expect(page.locator("#source-detail-heading")).to_have_text(second_title)
    assert BLOG_DEEP_MARKERS[second_title] in page.locator("[data-source-document]").inner_text()
    assert page.evaluate("document.activeElement.id") == "source-detail-heading"

    page.go_back()
    page.wait_for_url("**/#/sources")
    expect(page.locator(".source-card").first).to_have_attribute("aria-current", "true")


def test_m24_14_5_source_inspect_scrolls_detail_on_mobile(page, site_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 760})
    page.goto(f"{site_url}/#/sources")
    page.locator(".source-card").first.get_by_role("button", name="Inspect selected").click()
    expect(page.locator("#source-detail-heading")).to_be_in_viewport()
    assert page.evaluate("document.activeElement.id") == "source-detail-heading"


def test_m24_14_5_graph_canvas_search_selection_and_hops(page, site_url: str) -> None:
    payload = json.loads(SITE_ROOT.joinpath("data/graph-navigation.json").read_text())
    assert {node["type"] for node in payload["nodes"]} == {"Concept"}

    page.goto(f"{site_url}/#/graph?concept={HARNESS_CONCEPT_ID}")
    stage = page.locator("[data-sigma-stage]")
    stage.wait_for(state="visible")
    expect(stage).to_have_attribute("data-state", "ready")
    assert page.locator("[data-sigma-stage] canvas").count() >= 1
    _assert_no_graph_error(page)
    assert "Sigma.js canvas ready:" in _status_text(page)
    assert _screenshot_is_nonblank(stage.screenshot())

    page.locator("[data-graph-search]").fill("harness")
    page.locator(".graph-result-button", has_text="Harness").first.click()
    selection = page.locator("[data-graph-details]").inner_text()
    assert "Harness" in selection
    assert "Concept" in selection
    assert "Open Wiki" in selection
    assert "View sources" in selection

    page.locator("[data-graph-neighbor='1']").click()
    expect(stage).to_have_attribute("data-state", "ready")
    one_hop_status = _status_text(page)
    assert "visible nodes" in one_hop_status
    page.locator("[data-graph-neighbor='2']").click()
    expect(stage).to_have_attribute("data-state", "ready")
    assert "visible nodes" in _status_text(page)
    page.locator("[data-graph-reset]").click()
    page.locator("[data-graph-clear]").click()
    _assert_no_graph_error(page)


def test_m24_14_5_wiki_source_handoff_and_route_status_scoping(page, site_url: str) -> None:
    page.goto(f"{site_url}/#/graph?concept={NON_HARNESS_CONCEPT_ID}")
    expect(page.locator("[data-sigma-stage]")).to_have_attribute("data-state", "ready")
    page.eval_on_selector(
        "#app-status",
        """node => {
            node.textContent = 'Sigma: could not find a suitable program for node type "Concept"!';
            node.dataset.state = 'blocked';
        }""",
    )

    page.locator("[data-route-link='wiki']").click()
    page.wait_for_url("**/#/wiki?concept=concepts/harness")
    expect(page.locator("#route-title")).to_have_text("Concept Wiki")
    assert page.locator("#route-title").inner_text() == "Concept Wiki"
    assert "Harness" in page.locator("#app").inner_text()
    assert "Concept artifact unavailable" not in page.locator("#app").inner_text()
    assert "Sigma: could not find" not in page.locator("#app-status").inner_text()

    page.locator("[data-open-source-viewer]").first.click()
    page.wait_for_url("**/#/sources?viewer=*")
    expect(page.locator("#route-title")).to_have_text("Sources")
    assert "Source detail" in page.locator("#app").inner_text()
    assert "Citation" in page.locator("#app").inner_text()
    _assert_no_graph_error(page)


def test_m24_14_5_graph_selection_actions_open_wiki_and_sources(page, site_url: str) -> None:
    page.goto(f"{site_url}/#/graph?concept={NON_HARNESS_CONCEPT_ID}")
    expect(page.locator("[data-sigma-stage]")).to_have_attribute("data-state", "ready")
    page.locator("[data-graph-search]").fill("execution paths")
    page.locator(".graph-result-button", has_text="Agent execution paths").first.click()
    details = page.locator("[data-graph-details]")
    expect(details.get_by_role("button", name="Open Wiki")).to_be_visible()
    expect(details.get_by_role("button", name="View sources")).to_be_visible()

    details.get_by_role("button", name="Open Wiki").click()
    page.wait_for_url("**/#/wiki?concept=concepts%2Fagent-execution-paths")
    page.wait_for_selector("[data-state='bounded-graph-concept-summary']")
    assert "Bounded graph-derived summary" in page.locator("#app").inner_text()

    page.goto(f"{site_url}/#/graph?concept={NON_HARNESS_CONCEPT_ID}")
    expect(page.locator("[data-sigma-stage]")).to_have_attribute("data-state", "ready")
    page.locator("[data-graph-search]").fill("execution paths")
    page.locator(".graph-result-button", has_text="Agent execution paths").first.click()
    page.locator("[data-graph-details]").get_by_role("button", name="View sources").click()
    page.wait_for_url("**/#/sources?concept=concepts%2Fagent-execution-paths&viewer=viewer_source_blog_agent_execution_paths")
    expect(page.locator("#source-detail-heading")).to_have_text("Agent execution paths")
    assert BLOG_DEEP_MARKERS["Agent execution paths"] in page.locator("#app").inner_text()

    page.goto(f"{site_url}/#/graph?concept={HARNESS_CONCEPT_ID}")
    expect(page.locator("[data-sigma-stage]")).to_have_attribute("data-state", "ready")
    page.locator("[data-graph-details]").get_by_role("button", name="Open Wiki").click()
    page.wait_for_url("**/#/wiki?concept=concepts%2Fharness")
    expect(page.locator("#route-title")).to_have_text("Concept Wiki")
    expect(page.locator("#app")).to_contain_text("Sections")
    assert "Bounded graph-derived summary" not in page.locator("#app").inner_text()
    assert "Sections" in page.locator("#app").inner_text()


def test_m24_14_5_non_harness_bounded_summary_and_history(page, site_url: str) -> None:
    page.goto(f"{site_url}/#/wiki?concept={NON_HARNESS_CONCEPT_ID}")
    page.wait_for_selector("[data-state='bounded-graph-concept-summary']")
    app_text = page.locator("#app").inner_text()
    assert "Bounded graph-derived summary" in app_text
    assert "Agent execution paths" in app_text
    assert "Concept artifact unavailable" not in app_text
    _assert_no_graph_error(page)

    page.locator("[data-route-link='wiki']").click()
    page.wait_for_url("**/#/wiki?concept=concepts/harness")
    expect(page.locator("#app")).to_contain_text("Harness")
    assert "Harness" in page.locator("#app").inner_text()
    assert "Bounded graph-derived summary" not in page.locator("#app").inner_text()

    page.go_back()
    page.wait_for_selector("[data-state='bounded-graph-concept-summary']")
    assert "Agent execution paths" in page.locator("#app").inner_text()
    page.go_forward()
    page.wait_for_url("**/#/wiki?concept=concepts/harness")
    assert "Harness" in page.locator("#app").inner_text()

    page.goto(f"{site_url}/#/wiki?concept=concepts/not-in-release")
    page.wait_for_selector("[data-state='concept-not-found']")
    assert "Concept not found in this release" in page.locator("#app").inner_text()
    _assert_no_graph_error(page)
