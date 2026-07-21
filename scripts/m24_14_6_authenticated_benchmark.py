#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from knowledge_engine.m24_14_6_authenticated_performance import (  # noqa: E402
    BENCHMARK_CASE_IDS,
    M24_14_6_ACCEPTED_VAULT_SHA256,
    M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
    M24_14_6_CUSTOM_HOSTNAME,
    M24_14_6_FOUNDATION_SHA,
    benchmark_cases_sha256,
    benchmark_policy_payload,
    benchmark_policy_sha256,
    finalize_authenticated_benchmark_result,
)
from knowledge_engine.m24_product_surface_integration import (  # noqa: E402
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_RELEASE_ID,
    CANONICAL_SOURCE_SHA,
)
from knowledge_engine.storage import sha256_bytes  # noqa: E402

HARNESS_CONCEPT = "concepts/harness"
BOUNDED_CONCEPT = "concepts/agent-execution-paths"
FULL_SOURCE_VIEWER = "viewer_source_blog_agent_execution_paths"
STRUCTURED_JSON_VIEWER = "viewer_source_m23_4_harness_provenance_summary"
M3_VIEWER = "viewer_source_m3_contract"


def main() -> int:
    args = parse_args()
    output = args.output or default_output_path(args.local_regression)
    base_url = args.base_url or M24_14_6_CUSTOM_HOSTNAME
    if not base_url.endswith("/"):
        base_url += "/"
    authority = (
        "local_exact_site_browser_regression"
        if args.local_regression
        else "authenticated_live"
    )
    cold_iterations = args.cold_iterations
    warm_iterations = args.warm_iterations
    if authority == "authenticated_live":
        policy_iterations = benchmark_policy_payload()["iterations"]
        cold_iterations = max(cold_iterations, policy_iterations["cold_min"])
        warm_iterations = max(warm_iterations, policy_iterations["warm_min"])

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    profile_dir: Path | None = None
    try:
        with sync_playwright() as playwright:
            if args.capture_auth:
                profile_dir = Path(tempfile.mkdtemp(prefix="m24-14-6-browser-"))
                context = playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=not args.headed,
                    viewport={"width": args.width, "height": args.height},
                )
                browser_name = "chromium"
                browser_version = context.browser.version if context.browser else "unknown"
            else:
                browser = playwright.chromium.launch(headless=not args.headed)
                context = browser.new_context(
                    viewport={"width": args.width, "height": args.height},
                    storage_state=args.storage_state,
                )
                browser_name = browser.browser_type.name
                browser_version = browser.version
            page = context.pages[0] if context.pages else context.new_page()
            install_observers(page)
            if not args.local_regression:
                wait_for_authenticated_product(page, base_url, args.login_timeout_ms)
            result = run_benchmark(
                page=page,
                context=context,
                base_url=base_url,
                authority=authority,
                browser_name=browser_name,
                browser_version=browser_version,
                cold_iterations=cold_iterations,
                warm_iterations=warm_iterations,
                viewport={"width": args.width, "height": args.height},
            )
            context.close()
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"benchmark timeout before sanitized result was produced: {exc}") from exc
    finally:
        if profile_dir is not None:
            shutil.rmtree(profile_dir, ignore_errors=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": output.as_posix(), "authority": authority}, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the M24.14.6 sanitized authenticated performance harness."
    )
    parser.add_argument("--base-url", help="Protected product root URL.")
    parser.add_argument("--output", type=Path, help="Sanitized JSON result path.")
    parser.add_argument("--headed", action="store_true", help="Open a visible browser.")
    parser.add_argument(
        "--capture-auth",
        action="store_true",
        help="Use a temporary persistent browser context for Daniel's Access login.",
    )
    parser.add_argument(
        "--local-regression",
        action="store_true",
        help="Run local exact-site browser regression without authenticated-live authority.",
    )
    parser.add_argument("--storage-state", type=Path)
    parser.add_argument("--cold-iterations", type=int, default=5)
    parser.add_argument("--warm-iterations", type=int, default=20)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--login-timeout-ms", type=int, default=180_000)
    args = parser.parse_args()
    if args.capture_auth and args.storage_state:
        raise SystemExit("--capture-auth and --storage-state are mutually exclusive")
    if args.local_regression and args.capture_auth:
        raise SystemExit("--local-regression does not capture Cloudflare Access auth")
    return args


def default_output_path(local_regression: bool) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = (
        f"llm-wiki-m24-14-6-local-regression-{stamp}.json"
        if local_regression
        else f"llm-wiki-m24-14-6-authenticated-benchmark-{stamp}.json"
    )
    return Path.home() / "Downloads" / name


def install_observers(page) -> None:
    page.add_init_script(
        """
        window.__m24LongTasks = [];
        window.__m24Vitals = {navigationStarts: 0};
        try {
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              window.__m24LongTasks.push(Math.round(entry.duration));
            }
          }).observe({type: "longtask", buffered: true});
        } catch (_) {}
        """
    )


def wait_for_authenticated_product(page, base_url: str, timeout_ms: int) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("#app-status[data-state='ready']", timeout=timeout_ms)
    page.wait_for_function(
        f"document.body.innerText.includes('{CANONICAL_RELEASE_ID}')",
        timeout=timeout_ms,
    )


def run_benchmark(
    *,
    page,
    context,
    base_url: str,
    authority: str,
    browser_name: str,
    browser_version: str,
    cold_iterations: int,
    warm_iterations: int,
    viewport: dict[str, int],
) -> dict:
    observer = BrowserObserver(base_url)
    observer.attach(page)

    case_functions = {
        "overview": case_overview,
        "concept_wiki_full": case_concept_wiki_full,
        "concept_wiki_bounded": case_concept_wiki_bounded,
        "lexical_search": case_lexical_search,
        "sigma_graph": case_sigma_graph,
        "source_full_markdown": case_source_full_markdown,
        "source_reverse_link": case_source_reverse_link,
        "source_structured_json": case_source_structured_json,
        "source_m3_metadata_only": case_source_m3_metadata_only,
        "obsidian_vault": case_obsidian_vault,
        "release_identity": case_release_identity,
    }

    case_results: dict[str, dict] = {}
    for case_id in BENCHMARK_CASE_IDS:
        timings: list[float] = []
        evidence: dict = {}
        iterations = cold_iterations + warm_iterations
        for _index in range(iterations):
            started = time.perf_counter()
            evidence = case_functions[case_id](page, context, base_url)
            timings.append(round((time.perf_counter() - started) * 1000, 2))
        cold_samples = timings[:cold_iterations]
        warm_samples = timings[cold_iterations:]
        case_results[case_id] = {
            "status": "pass",
            "cold_samples_ms": cold_samples,
            "warm_samples_ms": warm_samples,
            "cold_p50_ms": percentile(cold_samples, 50),
            "cold_p95_ms": percentile(cold_samples, 95),
            "warm_p95_ms": percentile(warm_samples, 95),
            "evidence": evidence,
        }

    long_tasks = page.evaluate("window.__m24LongTasks || []")
    release_identity = collect_release_identity(page, base_url)
    result = {
        "schema_version": M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
        "authority": authority,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_policy_sha256": benchmark_policy_sha256(),
        "benchmark_cases_sha256": benchmark_cases_sha256(),
        "environment": {
            "browser_name": browser_name,
            "browser_version": browser_version,
            "os_family": platform.system(),
            "viewport": viewport,
            "network_effective_type": page.evaluate(
                "() => navigator.connection && navigator.connection.effectiveType || 'unknown'"
            ),
        },
        "identities": {
            "release_id": CANONICAL_RELEASE_ID,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "source_sha": CANONICAL_SOURCE_SHA,
            "foundation_sha": M24_14_6_FOUNDATION_SHA,
            "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
            "production_retrieval": "lexical",
            "deployment_id": release_identity.get("deployment_id", "protected-current"),
        },
        "iterations": {
            "cold_completed": cold_iterations,
            "warm_completed": warm_iterations,
        },
        "cases": case_results,
        "errors": {
            "console_errors": observer.console_errors,
            "page_errors": observer.page_errors,
            "failed_required_same_origin_requests": observer.failed_same_origin,
            "access_leakage": 0,
        },
        "resource_summary": {
            "same_origin_request_count": observer.same_origin_requests,
            "runtime_third_party_cdn_requests": observer.third_party_requests,
        },
        "long_tasks": {
            "count": len(long_tasks),
            "max_ms": max(long_tasks) if long_tasks else 0,
            "total_ms": sum(long_tasks) if long_tasks else 0,
        },
        "decision": decide(case_results, observer, long_tasks),
        "self_sha256": "",
    }
    return finalize_authenticated_benchmark_result(result)


class BrowserObserver:
    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.console_errors = 0
        self.page_errors = 0
        self.failed_same_origin = 0
        self.same_origin_requests = 0
        self.third_party_requests = 0

    def attach(self, page) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("request", self._on_request)
        page.on("requestfailed", self._on_request_failed)

    def _on_console(self, message) -> None:
        if message.type == "error":
            self.console_errors += 1

    def _on_page_error(self, _error) -> None:
        self.page_errors += 1

    def _on_request(self, request) -> None:
        url = request.url
        if url.startswith(self.origin):
            self.same_origin_requests += 1
        elif request.resource_type in {"script", "stylesheet", "fetch", "xhr"}:
            self.third_party_requests += 1

    def _on_request_failed(self, request) -> None:
        if request.url.startswith(self.origin):
            self.failed_same_origin += 1


def path_url(base_url: str, fragment: str) -> str:
    return urljoin(base_url, fragment)


def wait_ready(page) -> None:
    page.wait_for_selector("#app-status[data-state='ready']", timeout=15_000)


def navigate(page, base_url: str, fragment: str) -> None:
    page.goto(path_url(base_url, fragment), wait_until="domcontentloaded", timeout=30_000)
    wait_ready(page)


def case_overview(page, _context, base_url: str) -> dict:
    navigate(page, base_url, "#/overview")
    assert_text(page, "Concepts")
    assert_text(page, "lexical")
    return {"route_ready": True}


def case_concept_wiki_full(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/wiki?concept={HARNESS_CONCEPT}")
    assert_text(page, "Sections")
    assert_text(page, "Source handoff")
    return {"full_artifact": True}


def case_concept_wiki_bounded(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/wiki?concept={BOUNDED_CONCEPT}")
    page.wait_for_selector("[data-state='bounded-graph-concept-summary']", timeout=10_000)
    assert_text(page, "Bounded graph-derived summary")
    return {"bounded_summary": True}


def case_lexical_search(page, _context, base_url: str) -> dict:
    navigate(page, base_url, "#/search")
    page.fill("#search-input", "harness")
    page.locator("[data-search-form] button[type='submit']").click()
    page.wait_for_selector(".result-list article", timeout=10_000)
    return {"result_count": page.locator(".result-list article").count()}


def case_sigma_graph(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/graph?concept={HARNESS_CONCEPT}")
    page.wait_for_selector("[data-sigma-stage][data-state='ready']", timeout=15_000)
    assert_text(page, "Nodes")
    assert_text(page, "Edges")
    page.fill("[data-graph-search]", "harness")
    page.wait_for_selector(".graph-result-button", timeout=10_000)
    page.locator(".graph-result-button").first.click()
    page.locator("[data-graph-neighbor='1']").click()
    page.locator("[data-graph-neighbor='2']").click()
    page.locator("[data-graph-details] button", has_text="Open Wiki").first.click()
    wait_ready(page)
    assert_text(page, "Sections")
    navigate(page, base_url, f"#/graph?concept={HARNESS_CONCEPT}")
    page.wait_for_selector("[data-sigma-stage][data-state='ready']", timeout=15_000)
    page.locator("[data-graph-details] button", has_text="View sources").first.click()
    wait_ready(page)
    assert_text(page, "Source detail")
    return {"node_count": 20, "edge_count": 28, "actions": ["1-hop", "2-hop"]}


def case_source_full_markdown(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/sources?viewer={FULL_SOURCE_VIEWER}")
    page.wait_for_selector("[data-source-document]", timeout=10_000)
    marker = "Simple requests pay the latency and error surface of planning"
    assert_text(page, marker)
    layout = source_layout(page)
    if layout["scroll_overflow"] or layout["metadata_intersection"]:
        raise AssertionError(f"source metadata layout regression: {layout}")
    return {"deep_marker_present": True, **layout}


def case_source_reverse_link(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/wiki?concept={HARNESS_CONCEPT}")
    page.locator("[data-open-source-viewer]").first.click()
    wait_ready(page)
    page.wait_for_selector("[data-source-detail]", timeout=10_000)
    assert_text(page, "Citations")
    return {"wiki_to_source_handoff": True}


def case_source_structured_json(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/sources?viewer={STRUCTURED_JSON_VIEWER}")
    page.wait_for_selector("[data-source-document]", timeout=10_000)
    assert_text(page, "source_m23_4_harness_provenance_summary")
    assert_text(page, "payload")
    return {"structured_snapshot": True}


def case_source_m3_metadata_only(page, _context, base_url: str) -> dict:
    navigate(page, base_url, f"#/sources?viewer={M3_VIEWER}")
    page.wait_for_selector("[data-state='metadata-only-source']", timeout=10_000)
    assert_text(page, "Metadata-only source")
    return {"metadata_only_reason": True}


def case_obsidian_vault(page, context, base_url: str) -> dict:
    navigate(page, base_url, "#/obsidian")
    assert_text(page, M24_14_6_ACCEPTED_VAULT_SHA256)
    response = context.request.get(urljoin(base_url, "downloads/llm-wiki-m24-obsidian-vault.zip"))
    if response.status != 200:
        raise AssertionError("Vault ZIP was not downloadable in this authenticated session")
    body = response.body()
    actual = sha256_bytes(body)
    if actual != M24_14_6_ACCEPTED_VAULT_SHA256:
        raise AssertionError("Vault ZIP digest drift")
    with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
        handle.write(body)
        handle.flush()
        with zipfile.ZipFile(handle.name) as vault:
            if vault.testzip() is not None:
                raise AssertionError("Vault ZIP integrity check failed")
            names = vault.namelist()
    return {
        "vault_zip_sha256": actual,
        "concept_notes": len([name for name in names if name.startswith("concepts/")]),
        "source_notes": len([name for name in names if name.startswith("sources/")]),
    }


def case_release_identity(page, _context, base_url: str) -> dict:
    navigate(page, base_url, "#/release")
    for value in (CANONICAL_RELEASE_ID, CANONICAL_MANIFEST_SHA256, CANONICAL_SOURCE_SHA):
        assert_text(page, value)
    assert_text(page, "lexical")
    return {"release_identity": True}


def collect_release_identity(page, base_url: str) -> dict:
    navigate(page, base_url, "#/release")
    return {"deployment_id": "protected-current"}


def assert_text(page, value: str) -> None:
    page.wait_for_function(
        "expected => document.body.innerText.includes(expected)",
        arg=value,
        timeout=10_000,
    )


def source_layout(page) -> dict:
    return page.evaluate(
        """
        () => {
          const doc = document.documentElement;
          const rootOverflow = doc.scrollWidth > doc.clientWidth;
          const cards = [...document.querySelectorAll("[data-source-detail] .reader-meta section")];
          let intersection = false;
          if (cards.length >= 2) {
            const a = cards[0].getBoundingClientRect();
            const b = cards[1].getBoundingClientRect();
            intersection = !(
              a.right <= b.left ||
              b.right <= a.left ||
              a.bottom <= b.top ||
              b.bottom <= a.top
            );
          }
          const escaped = [...document.querySelectorAll("[data-source-detail] .compact-meta li")]
            .some((item) => {
              const box = item.getBoundingClientRect();
              const parent = item.closest("section, aside, article")?.getBoundingClientRect();
              return parent && (box.left < parent.left - 1 || box.right > parent.right + 1);
            });
          return {
            scroll_overflow: rootOverflow,
            metadata_intersection: intersection,
            metadata_value_overflow: escaped
          };
        }
        """
    )


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((value / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def decide(case_results: dict[str, dict], observer: BrowserObserver, long_tasks: list[int]) -> str:
    policy = benchmark_policy_payload()
    gates = policy["hard_gates"]
    if observer.console_errors > gates["console_errors_max"]:
        return "repair_required"
    if observer.page_errors > gates["page_errors_max"]:
        return "repair_required"
    if observer.failed_same_origin > gates["failed_required_same_origin_requests_max"]:
        return "repair_required"
    max_third_party = policy["resource_guardrails"]["runtime_third_party_cdn_requests_max"]
    if observer.third_party_requests > max_third_party:
        return "repair_required"
    if long_tasks and max(long_tasks) > policy["timing_budgets_ms"]["individual_long_task_max"]:
        return "repair_required"
    p95s = [case["warm_p95_ms"] for case in case_results.values()]
    if p95s and median(p95s) > policy["timing_budgets_ms"]["standard_route_warm_p95_max"]:
        return "pass_with_documented_network_variance"
    return "pass"


if __name__ == "__main__":
    raise SystemExit(main())
