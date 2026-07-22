#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
    PLACEHOLDER_DEPLOYMENT_IDS,
    _decision_for_reason_codes,
    _enforce_resource_guardrails,
    _recompute_errors,
    _recompute_long_tasks,
    _recompute_resource_summary,
    _require_mapping,
    _validate_case_evidence,
    _validate_case_record,
    _validate_interactions,
    _validate_viewports,
    benchmark_cases_sha256,
    benchmark_policy_payload,
    benchmark_policy_sha256,
    finalize_authenticated_benchmark_result,
    recompute_benchmark_decision,
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
M3_METADATA_REASON = (
    "No exact release-authoritative file or immutable snapshot was resolved for this "
    "governance contract in the M24.14.5 repair authority boundary."
)
DEEP_MARKERS = (
    "Multi-agent is an organisational choice, not a maturity level",
    "Simple requests pay the latency and error surface of planning",
    "The production objective is not maximum planning freedom",
)
SUPPORTED_BROWSER_CHANNELS = ("chromium", "chrome", "msedge")
SUPPORTED_BROWSER_MODES = ("playwright", "chrome-cdp")


@dataclass
class BrowserSession:
    context: Any
    browser_name: str
    browser_version: str
    browser_mode: str
    browser_channel: str
    profile_dir: Path | None = None
    connected_browser: Any | None = None
    dedicated_process: subprocess.Popen | None = None

    def close(self) -> None:
        try:
            if self.connected_browser is not None:
                self.connected_browser.close()
            else:
                self.context.close()
        finally:
            close_dedicated_process(self.dedicated_process)
            if self.profile_dir is not None:
                shutil.rmtree(self.profile_dir, ignore_errors=True)


class ViewportContext:
    def __init__(self, context: Any, viewport: dict[str, int]) -> None:
        self._context = context
        self._viewport = viewport

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def new_page(self) -> Any:
        page = self._context.new_page()
        page.set_viewport_size(self._viewport)
        return page


def main() -> int:
    args = parse_args()
    output = args.output or default_output_path(args.local_regression)
    base_url = args.base_url or M24_14_6_CUSTOM_HOSTNAME
    if not base_url.endswith("/"):
        base_url += "/"
    authority = (
        "local_exact_site_browser_regression" if args.local_regression else "authenticated_live"
    )
    cold_iterations = args.cold_iterations
    warm_iterations = args.warm_iterations
    if authority == "authenticated_live":
        policy_iterations = benchmark_policy_payload()["iterations"]
        cold_iterations = max(cold_iterations, policy_iterations["cold_min"])
        warm_iterations = max(warm_iterations, policy_iterations["warm_min"])

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Playwright is not installed. Install the repository test dependencies, "
            "then rerun this benchmark."
        ) from exc

    session: BrowserSession | None = None
    try:
        with sync_playwright() as playwright:
            try:
                try:
                    session = launch_browser_session(playwright, args)
                except PlaywrightError as exc:
                    message = friendly_playwright_error(exc)
                    raise SystemExit(f"browser launch failed: {message}") from exc
                context = session.context
                context.add_init_script(LONG_TASK_OBSERVER_SCRIPT)
                if not args.local_regression:
                    page = context.new_page()
                    wait_for_authenticated_product(page, base_url, args.login_timeout_ms)
                    page.close()
                result = run_benchmark(
                    context=context,
                    base_url=base_url,
                    authority=authority,
                    browser_name=session.browser_name,
                    browser_version=session.browser_version,
                    browser_mode=session.browser_mode,
                    browser_channel=session.browser_channel,
                    deployment_id=args.deployment_id,
                    cold_iterations=cold_iterations,
                    warm_iterations=warm_iterations,
                    viewport={"width": args.width, "height": args.height},
                )
            finally:
                close_session_without_masking(session)
                session = None
    except PlaywrightTimeoutError as exc:
        raise SystemExit(f"benchmark timeout before sanitized result was produced: {exc}") from exc
    finally:
        close_session_without_masking(session)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"authority": authority, "output": output.as_posix()}, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the M24.14.6 sanitized authenticated performance harness."
    )
    parser.add_argument("--base-url", help="Protected product root URL.")
    parser.add_argument("--deployment-id", required=True, help="Exact Cloudflare deployment ID.")
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
    parser.add_argument(
        "--browser-channel",
        choices=SUPPORTED_BROWSER_CHANNELS,
        default="chromium",
        help=(
            "Browser channel for Playwright launch. Use 'chrome' for official "
            "Google Chrome in headed capture-auth mode; default remains bundled Chromium."
        ),
    )
    parser.add_argument(
        "--browser-mode",
        choices=SUPPORTED_BROWSER_MODES,
        default="playwright",
        help=(
            "Browser launch mode. 'chrome-cdp' starts a dedicated official Chrome "
            "with a temporary profile and loopback-only CDP, then attaches to it."
        ),
    )
    parser.add_argument("--cold-iterations", type=int, default=5)
    parser.add_argument("--warm-iterations", type=int, default=20)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--login-timeout-ms", type=int, default=180_000)
    args = parser.parse_args()
    if args.deployment_id in PLACEHOLDER_DEPLOYMENT_IDS:
        raise SystemExit("--deployment-id must be exact, not a placeholder")
    if args.capture_auth and args.storage_state:
        raise SystemExit("--capture-auth and --storage-state are mutually exclusive")
    if args.local_regression and args.capture_auth:
        raise SystemExit("--local-regression does not capture Cloudflare Access auth")
    if args.storage_state and ROOT in args.storage_state.resolve().parents:
        raise SystemExit("--storage-state must not point inside the repository")
    if args.browser_mode == "chrome-cdp":
        if not args.capture_auth:
            raise SystemExit("--browser-mode chrome-cdp requires --capture-auth")
        if args.browser_channel != "chrome":
            raise SystemExit("--browser-mode chrome-cdp requires --browser-channel chrome")
        if args.local_regression:
            raise SystemExit("--browser-mode chrome-cdp is for authenticated capture only")
    if args.cold_iterations < 1 or args.warm_iterations < 1:
        raise SystemExit("--cold-iterations and --warm-iterations must be positive")
    return args


def launch_browser_session(playwright, args: argparse.Namespace) -> BrowserSession:
    viewport = {"width": args.width, "height": args.height}
    if args.browser_mode == "chrome-cdp":
        return launch_dedicated_chrome_cdp_session(playwright, viewport, headed=args.headed)
    if args.capture_auth:
        profile_dir = isolated_temp_profile_dir()
        launch_options: dict[str, Any] = {
            "headless": not args.headed,
            "viewport": viewport,
        }
        if args.browser_channel != "chromium":
            launch_options["channel"] = args.browser_channel
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        version = context.browser.version if context.browser else "unknown"
        return BrowserSession(
            context=context,
            browser_name="chromium",
            browser_version=version,
            browser_mode="playwright_persistent_context",
            browser_channel=args.browser_channel,
            profile_dir=profile_dir,
        )
    launch_options = {"headless": not args.headed}
    if args.browser_channel != "chromium":
        launch_options["channel"] = args.browser_channel
    browser = playwright.chromium.launch(**launch_options)
    context = browser.new_context(
        viewport=viewport,
        storage_state=args.storage_state,
    )
    return BrowserSession(
        context=context,
        browser_name=browser.browser_type.name,
        browser_version=browser.version,
        browser_mode="playwright_ephemeral_context",
        browser_channel=args.browser_channel,
        connected_browser=browser,
    )


def launch_dedicated_chrome_cdp_session(
    playwright,
    viewport: dict[str, int],
    *,
    headed: bool,
) -> BrowserSession:
    if not headed:
        raise SystemExit("--browser-mode chrome-cdp requires --headed")
    executable = official_google_chrome_executable()
    if executable is None:
        raise SystemExit(
            "Official Google Chrome was not found. Install Google Chrome, then rerun with "
            "--browser-channel chrome."
        )
    profile_dir = isolated_temp_profile_dir()
    port = unused_loopback_port()
    process = subprocess.Popen(
        [
            executable.as_posix(),
            f"--user-data-dir={profile_dir.as_posix()}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_cdp_endpoint(port)
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        wrapped = ViewportContext(context, viewport)
        return BrowserSession(
            context=wrapped,
            browser_name="chromium",
            browser_version=browser.version,
            browser_mode="dedicated_chrome_cdp",
            browser_channel="chrome",
            profile_dir=profile_dir,
            connected_browser=browser,
            dedicated_process=process,
        )
    except Exception:
        close_dedicated_process(process)
        shutil.rmtree(profile_dir, ignore_errors=True)
        raise


def isolated_temp_profile_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="m24-14-6-chrome-profile-"))
    try:
        path.relative_to(ROOT)
    except ValueError:
        return path
    raise SystemExit("temporary browser profile must be outside the repository")


def official_google_chrome_executable() -> Path | None:
    candidates: list[Path]
    system = platform.system()
    if system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    elif system == "Windows":
        candidates = [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ]
    else:
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/opt/google/chrome/google-chrome"),
        ]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def wait_for_cdp_endpoint(port: int, timeout_ms: int = 15_000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise SystemExit("Dedicated Google Chrome did not expose a loopback DevTools endpoint")


def close_dedicated_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def close_session_without_masking(session: BrowserSession | None) -> None:
    if session is None:
        return
    try:
        session.close()
    except Exception:
        print(
            "warning: browser cleanup failed after benchmark; no profile, endpoint, "
            "process, cookie, or storage details were emitted",
            file=sys.stderr,
        )


def friendly_playwright_error(exc: Exception) -> str:
    message = str(exc)
    if "Executable doesn't exist" in message or "Looks like Playwright" in message:
        return (
            "the requested browser is unavailable. For local/CI Chromium, run the "
            "repository Playwright browser install. For Daniel's auth flow, install "
            "official Google Chrome and use --browser-channel chrome."
        )
    if "channel" in message.lower() and "chrome" in message.lower():
        return "official Google Chrome is unavailable for Playwright channel 'chrome'."
    return message


def default_output_path(local_regression: bool) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = (
        f"llm-wiki-m24-14-6-local-regression-{stamp}.json"
        if local_regression
        else f"llm-wiki-m24-14-6-authenticated-benchmark-{stamp}.json"
    )
    return Path.home() / "Downloads" / name


LONG_TASK_OBSERVER_SCRIPT = """
window.__m24LongTasks = [];
try {
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      window.__m24LongTasks.push(Math.round(entry.duration));
    }
  }).observe({type: "longtask", buffered: true});
} catch (_) {}
"""


def wait_for_authenticated_product(page, base_url: str, timeout_ms: int) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("#app-status[data-state='ready']", timeout=timeout_ms)
    page.wait_for_function(
        f"document.body.innerText.includes('{CANONICAL_RELEASE_ID}')",
        timeout=timeout_ms,
    )


def run_benchmark(
    *,
    context,
    base_url: str,
    authority: str,
    browser_name: str,
    browser_version: str,
    browser_mode: str,
    browser_channel: str,
    deployment_id: str,
    cold_iterations: int,
    warm_iterations: int,
    viewport: dict[str, int],
) -> dict[str, Any]:
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

    case_results: dict[str, Any] = {}
    for case_id in BENCHMARK_CASE_IDS:
        cold_samples: list[dict[str, Any]] = []
        warm_samples: list[dict[str, Any]] = []
        evidence: dict[str, Any] = {}
        for iteration in range(cold_iterations):
            sample, evidence = measure_case_sample(
                context,
                base_url,
                case_functions[case_id],
                phase="cold",
                iteration=iteration + 1,
            )
            cold_samples.append(sample)
        for iteration in range(warm_iterations):
            sample, evidence = measure_case_sample(
                context,
                base_url,
                case_functions[case_id],
                phase="warm",
                iteration=iteration + 1,
            )
            warm_samples.append(sample)
        case_results[case_id] = {
            "status": "pass",
            "cold_samples": cold_samples,
            "warm_samples": warm_samples,
            "aggregates": {
                "cold_p50_ms": nearest_rank([item["elapsed_ms"] for item in cold_samples], 50),
                "cold_p95_ms": nearest_rank([item["elapsed_ms"] for item in cold_samples], 95),
                "warm_p95_ms": nearest_rank([item["elapsed_ms"] for item in warm_samples], 95),
            },
            "evidence": evidence,
        }

    interactions = measure_interactions(context, base_url, warm_iterations)
    viewport_results = measure_viewports(context, base_url)
    result = {
        "schema_version": M24_14_6_AUTHENTICATED_RESULT_SCHEMA,
        "authority": authority,
        "deployment_id": deployment_id,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "benchmark_policy_sha256": benchmark_policy_sha256(),
        "benchmark_cases_sha256": benchmark_cases_sha256(),
        "environment": {
            "browser_name": browser_name,
            "browser_version": browser_version,
            "browser_mode": browser_mode,
            "browser_channel": browser_channel,
            "os_family": platform.system(),
            "viewport": viewport,
        },
        "identities": release_identity(deployment_id),
        "iterations": {
            "cold_completed": cold_iterations,
            "warm_completed": warm_iterations,
        },
        "cases": case_results,
        "interactions": interactions,
        "viewport_results": viewport_results,
        "errors": {},
        "resource_summary": {},
        "long_tasks": {},
        "recomputed_aggregates": {},
        "decision": "repair_required",
        "reason_codes": [],
        "self_sha256": "",
    }
    recomputed = collect_recomputed_fields(
        result,
        require_authenticated_iterations=authority == "authenticated_live",
    )
    result["errors"] = recomputed["errors"]
    result["resource_summary"] = recomputed["resources"]
    result["long_tasks"] = recomputed["long_tasks"]
    result["recomputed_aggregates"] = recomputed
    result["decision"] = recomputed["decision"]
    result["reason_codes"] = recomputed["reason_codes"]
    if result["decision"] == "pass":
        recompute_benchmark_decision(
            result,
            expected_deployment_id=deployment_id,
            require_authenticated_iterations=authority == "authenticated_live",
        )
    return finalize_authenticated_benchmark_result(result)


def collect_recomputed_fields(
    result: dict[str, Any],
    *,
    require_authenticated_iterations: bool,
) -> dict[str, Any]:
    policy = benchmark_policy_payload()
    cold_min = policy["iterations"]["cold_min"] if require_authenticated_iterations else 1
    warm_min = policy["iterations"]["warm_min"] if require_authenticated_iterations else 1
    reason_codes: list[str] = []
    cases = _require_mapping(result["cases"], "cases")
    recomputed_cases = {
        case_id: _validate_case_record(
            case_id,
            _require_mapping(cases[case_id], f"cases.{case_id}"),
            cold_min=cold_min,
            warm_min=warm_min,
            reason_codes=reason_codes,
        )
        for case_id in BENCHMARK_CASE_IDS
    }
    _validate_case_evidence(cases, reason_codes)
    interactions = _require_mapping(result["interactions"], "interactions")
    recomputed_interactions = _validate_interactions(interactions, warm_min, reason_codes)
    viewports = _require_mapping(result["viewport_results"], "viewport_results")
    _validate_viewports(viewports, reason_codes)
    errors = _recompute_errors(cases, interactions, viewports)
    resources = _recompute_resource_summary(cases, interactions, viewports)
    _enforce_resource_guardrails(resources, reason_codes)
    long_tasks = _recompute_long_tasks(cases, interactions, viewports)
    hard_gates = benchmark_policy_payload()["hard_gates"]
    if errors["console_errors"] > hard_gates["console_errors_max"]:
        reason_codes.append("hard_gate:console_errors")
    if errors["page_errors"] > hard_gates["page_errors_max"]:
        reason_codes.append("hard_gate:page_errors")
    if (
        errors["failed_required_same_origin_requests"]
        > hard_gates["failed_required_same_origin_requests_max"]
    ):
        reason_codes.append("hard_gate:failed_required_same_origin_requests")
    if errors["access_leakage"] > hard_gates["access_leakage_max"]:
        reason_codes.append("hard_gate:access_leakage")
    decision = _decision_for_reason_codes(reason_codes)
    return {
        "cases": recomputed_cases,
        "interactions": recomputed_interactions,
        "errors": errors,
        "resources": resources,
        "long_tasks": long_tasks,
        "decision": decision,
        "reason_codes": reason_codes,
    }


def measure_case_sample(
    context,
    base_url: str,
    case_function,
    *,
    phase: str,
    iteration: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    page = context.new_page()
    observer = BrowserObserver(base_url)
    observer.attach(page)
    cache = {
        "cleared_before_sample": phase == "cold",
        "disabled_during_sample": phase == "cold",
    }
    cdp = None
    if phase == "cold":
        cdp = context.new_cdp_session(page)
        cdp.send("Network.clearBrowserCache")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    try:
        started = time.perf_counter()
        evidence = case_function(page, context, base_url)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        sample = {
            "iteration": iteration,
            "phase": phase,
            "elapsed_ms": elapsed_ms,
            "cache": cache,
            "resources": observer.resources(page),
        }
        return sample, evidence
    finally:
        if cdp is not None:
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": False})
            cdp.detach()
        page.close()


def measure_interactions(context, base_url: str, warm_iterations: int) -> dict[str, Any]:
    def samples_for(label: str, action) -> dict[str, Any]:
        samples = []
        for iteration in range(warm_iterations):
            page = context.new_page()
            observer = BrowserObserver(base_url)
            observer.attach(page)
            try:
                action(page, setup=True)
                started = time.perf_counter()
                action(page, setup=False)
                samples.append(
                    {
                        "iteration": iteration + 1,
                        "phase": "warm",
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        "cache": {
                            "cleared_before_sample": False,
                            "disabled_during_sample": False,
                        },
                        "resources": observer.resources(page),
                    }
                )
            finally:
                page.close()
        return {
            "status": "pass",
            "warm_samples": samples,
            "aggregates": {
                "warm_p95_ms": nearest_rank([item["elapsed_ms"] for item in samples], 95)
            },
            "evidence": {"interaction": label, "setup_excluded_from_timing": True},
        }

    return {
        "lexical_search": {
            "search": samples_for(
                "lexical_search.search",
                lambda page, setup: interaction_lexical_search(page, base_url, setup=setup),
            )
        },
        "sigma_graph": {
            "search": samples_for(
                "sigma_graph.search",
                lambda page, setup: interaction_graph_search(page, base_url, setup=setup),
            ),
            "result_selection": samples_for(
                "sigma_graph.result_selection",
                lambda page, setup: interaction_graph_select(page, base_url, setup=setup),
            ),
            "one_hop": samples_for(
                "sigma_graph.one_hop",
                lambda page, setup: interaction_graph_hop(page, base_url, hop=1, setup=setup),
            ),
            "two_hop": samples_for(
                "sigma_graph.two_hop",
                lambda page, setup: interaction_graph_hop(page, base_url, hop=2, setup=setup),
            ),
            "open_wiki": samples_for(
                "sigma_graph.open_wiki",
                lambda page, setup: interaction_graph_action(
                    page,
                    base_url,
                    button_text="Open Wiki",
                    expected="Sections",
                    setup=setup,
                ),
            ),
            "view_sources": samples_for(
                "sigma_graph.view_sources",
                lambda page, setup: interaction_graph_action(
                    page,
                    base_url,
                    button_text="View sources",
                    expected="Source detail",
                    setup=setup,
                ),
            ),
        },
    }


def measure_viewports(context, base_url: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for width, height in ((1440, 900), (1024, 768), (768, 900), (390, 844)):
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": height})
        observer = BrowserObserver(base_url)
        observer.attach(page)
        try:
            navigate(page, base_url, f"#/graph?concept={HARNESS_CONCEPT}")
            page.wait_for_selector("[data-sigma-stage][data-state='ready']", timeout=15_000)
            page.locator("[data-graph-neighbor='1']").click()
            page.locator("[data-graph-neighbor='2']").click()
            navigate(page, base_url, f"#/sources?viewer={FULL_SOURCE_VIEWER}")
            page.wait_for_selector("[data-source-detail]", timeout=10_000)
            layout = source_layout(page)
            results[f"{width}x{height}"] = {
                "status": "pass",
                "horizontal_overflow": layout["scroll_overflow"],
                "metadata_intersection": layout["metadata_intersection"],
                "metadata_value_overflow": layout["metadata_value_overflow"],
                "traversal": "graph_hops_then_exact_source_detail",
                "resources": observer.resources(page),
            }
        finally:
            page.close()
    return results


class BrowserObserver:
    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.console_errors = 0
        self.page_errors = 0
        self.failed_same_origin = 0
        self.same_origin_requests = 0
        self.same_origin_transfer_bytes = 0
        self.third_party_requests = 0
        self.platform_third_party_requests = 0
        self.platform_console_errors = 0

    def attach(self, page) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("request", self._on_request)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)

    def resources(self, page) -> dict[str, int]:
        long_tasks = page.evaluate("window.__m24LongTasks || []")
        return {
            "same_origin_request_count": self.same_origin_requests,
            "same_origin_transfer_bytes": self.same_origin_transfer_bytes,
            "runtime_third_party_cdn_requests": self.third_party_requests,
            "platform_third_party_request_count": self.platform_third_party_requests,
            "failed_required_same_origin_requests": self.failed_same_origin,
            "console_errors": self.console_errors,
            "platform_console_errors": self.platform_console_errors,
            "page_errors": self.page_errors,
            "long_task_count": len(long_tasks),
            "long_task_max_ms": max(long_tasks) if long_tasks else 0,
            "long_task_total_ms": sum(long_tasks) if long_tasks else 0,
        }

    def _on_console(self, message) -> None:
        if message.type == "error":
            location = message.location or {}
            location_url = location.get("url", "")
            text = self._message_text(message)
            if self._is_cloudflare_platform_url(location_url) or self._mentions_cloudflare_platform(
                text
            ):
                self.platform_console_errors += 1
            elif self._is_same_origin(location_url):
                self.console_errors += 1
            else:
                self.platform_console_errors += 1

    def _on_page_error(self, _error) -> None:
        self.page_errors += 1

    def _on_request(self, request) -> None:
        url = request.url
        if self._is_same_origin(url):
            self.same_origin_requests += 1
        elif self._is_cloudflare_platform_url(url):
            self.platform_third_party_requests += 1
        elif request.resource_type in {"script", "stylesheet", "fetch", "xhr"}:
            self.third_party_requests += 1

    def _on_request_failed(self, request) -> None:
        if self._is_same_origin(request.url):
            self.failed_same_origin += 1

    def _on_response(self, response) -> None:
        if not self._is_same_origin(response.url):
            return
        try:
            length = response.header_value("content-length")
            if length and length.isdigit():
                self.same_origin_transfer_bytes += int(length)
        except Exception:
            return

    def _is_same_origin(self, url: str) -> bool:
        return bool(url) and url.startswith(self.origin)

    def _is_cloudflare_platform_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.path.startswith("/cdn-cgi/"):
            return True
        host = parsed.hostname or ""
        return any(
            host == domain or host.endswith(f".{domain}")
            for domain in (
                "cloudflare.com",
                "cloudflareinsights.com",
                "cloudflareaccess.com",
                "challenges.cloudflare.com",
            )
        )

    def _mentions_cloudflare_platform(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in (
                "cloudflare",
                "cloudflareinsights.com",
                "cloudflareaccess.com",
                "challenges.cloudflare.com",
                "/cdn-cgi/",
            )
        )

    def _message_text(self, message) -> str:
        text = getattr(message, "text", "")
        if callable(text):
            text = text()
        return str(text or "")


def path_url(base_url: str, fragment: str) -> str:
    return urljoin(base_url, fragment)


def wait_ready(page) -> None:
    page.wait_for_selector("#app-status[data-state='ready']", timeout=15_000)


def navigate(page, base_url: str, fragment: str) -> None:
    page.goto(path_url(base_url, fragment), wait_until="domcontentloaded", timeout=30_000)
    wait_ready(page)


def case_overview(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, "#/overview")
    assert_text(page, "Concepts")
    assert_text(page, "lexical")
    return {"route_ready": True}


def case_concept_wiki_full(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/wiki?concept={HARNESS_CONCEPT}")
    assert_text(page, "Sections")
    assert_text(page, "Source handoff")
    return {"full_artifact": True}


def case_concept_wiki_bounded(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/wiki?concept={BOUNDED_CONCEPT}")
    page.wait_for_selector("[data-state='bounded-graph-concept-summary']", timeout=10_000)
    assert_text(page, "Bounded graph-derived summary")
    return {"bounded_summary": True}


def case_lexical_search(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, "#/search")
    page.fill("#search-input", "harness")
    page.locator("[data-search-form] button[type='submit']").click()
    page.wait_for_selector(".result-list article", timeout=10_000)
    return {"result_count": page.locator(".result-list article").count()}


def case_sigma_graph(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/graph?concept={HARNESS_CONCEPT}")
    page.wait_for_selector("[data-sigma-stage][data-state='ready']", timeout=15_000)
    graph_payload = page.evaluate(
        "() => fetch('data/graph-navigation.json').then((response) => response.json())"
    )
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
    return {
        "node_count": len(graph_payload["nodes"]),
        "edge_count": len(graph_payload["edges"]),
        "node_count_source": "graph_payload_fetch",
        "sigma_ready": True,
        "harness_selected": True,
        "one_hop_action": True,
        "two_hop_action": True,
        "open_wiki_action": True,
        "view_sources_action": True,
    }


def case_source_full_markdown(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/sources?viewer={FULL_SOURCE_VIEWER}")
    page.wait_for_selector("[data-source-document]", timeout=10_000)
    marker = "Simple requests pay the latency and error surface of planning"
    assert_text(page, marker)
    source_payload = page.evaluate(
        "() => fetch('data/sources/source_blog_agent_execution_paths.json')"
        ".then((response) => response.json())"
    )
    document = source_payload.get("document", {})
    integrity = source_payload.get("integrity", {})
    content = str(document.get("body", ""))
    return {
        "viewer_id": FULL_SOURCE_VIEWER,
        "source_id": "source_blog_agent_execution_paths",
        "deep_marker_present": marker in page.inner_text("body") and marker in content,
        "content_bytes": integrity.get("byte_count", len(content.encode("utf-8"))),
        "line_count": integrity.get("line_count", len(content.splitlines())),
        "layout": source_layout(page),
    }


def case_source_reverse_link(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/wiki?concept={HARNESS_CONCEPT}")
    page.locator("[data-open-source-viewer]").first.click()
    wait_ready(page)
    page.wait_for_selector("[data-source-detail]", timeout=10_000)
    assert_text(page, "Citations")
    return {"wiki_to_source_handoff": True}


def case_source_structured_json(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/sources?viewer={STRUCTURED_JSON_VIEWER}")
    page.wait_for_selector("[data-source-document]", timeout=10_000)
    source_payload = page.evaluate(
        "() => fetch('data/sources/source_m23_4_harness_provenance_summary.json')"
        ".then((response) => response.json())"
    )
    document = source_payload.get("document", {})
    integrity = source_payload.get("integrity", {})
    content = str(document.get("body", ""))
    parsed = document.get("json") or json.loads(content)
    assert_text(page, "source_m23_4_harness_provenance_summary")
    return {
        "source_id": "source_m23_4_harness_provenance_summary",
        "parseable_json": True,
        "records_count": len(parsed.get("records", [])),
        "snapshot_sha256": integrity.get("browser_payload_sha256"),
        "truncated": False,
    }


def case_source_m3_metadata_only(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, f"#/sources?viewer={M3_VIEWER}")
    page.wait_for_selector("[data-state='metadata-only-source']", timeout=10_000)
    assert_text(page, "Metadata-only source")
    assert_text(page, M3_METADATA_REASON)
    return {"metadata_only_reason": M3_METADATA_REASON}


def case_obsidian_vault(page, context, base_url: str) -> dict[str, Any]:
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
            texts = {
                name: vault.read(name).decode("utf-8")
                for name in names
                if name.endswith(".md") or name == "manifest.json"
            }
    unresolved = unresolved_wikilinks(texts, names)
    deep_markers = [
        marker for marker in DEEP_MARKERS if any(marker in text for text in texts.values())
    ]
    return {
        "vault_zip_sha256": actual,
        "crc_pass": True,
        "member_count": len(names),
        "concept_notes": len([name for name in names if name.startswith("concepts/")]),
        "source_notes": len([name for name in names if name.startswith("sources/")]),
        "required_members": names,
        "unresolved_wikilinks": unresolved,
        "bidirectional_source_concept_pairs": bidirectional_source_concept_pairs(texts),
        "deep_markers": deep_markers,
        "m3_metadata_only_reason": M3_METADATA_REASON,
    }


def case_release_identity(page, _context, base_url: str) -> dict[str, Any]:
    navigate(page, base_url, "#/release")
    for value in (CANONICAL_RELEASE_ID, CANONICAL_MANIFEST_SHA256, CANONICAL_SOURCE_SHA):
        assert_text(page, value)
    assert_text(page, "lexical")
    return {
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_sha": CANONICAL_SOURCE_SHA,
        "foundation_sha": M24_14_6_FOUNDATION_SHA,
        "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        "production_retrieval": "lexical",
        "semantic_serving_enabled": False,
        "hybrid_retrieval_enabled": False,
    }


def release_identity(deployment_id: str) -> dict[str, Any]:
    return {
        "release_id": CANONICAL_RELEASE_ID,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "source_sha": CANONICAL_SOURCE_SHA,
        "foundation_sha": M24_14_6_FOUNDATION_SHA,
        "vault_sha256": M24_14_6_ACCEPTED_VAULT_SHA256,
        "production_retrieval": "lexical",
        "deployment_id": deployment_id,
    }


def interaction_lexical_search(page, base_url: str, *, setup: bool) -> None:
    if setup:
        navigate(page, base_url, "#/search")
        return
    page.fill("#search-input", "harness")
    page.locator("[data-search-form] button[type='submit']").click()
    page.wait_for_selector(".result-list article", timeout=10_000)


def interaction_graph_search(page, base_url: str, *, setup: bool) -> None:
    if setup:
        navigate(page, base_url, f"#/graph?concept={HARNESS_CONCEPT}")
        page.wait_for_selector("[data-sigma-stage][data-state='ready']", timeout=15_000)
        return
    page.fill("[data-graph-search]", "harness")
    page.wait_for_selector(".graph-result-button", timeout=10_000)


def interaction_graph_select(page, base_url: str, *, setup: bool) -> None:
    if setup:
        interaction_graph_search(page, base_url, setup=True)
        page.fill("[data-graph-search]", "harness")
        page.wait_for_selector(".graph-result-button", timeout=10_000)
        return
    page.locator(".graph-result-button").first.click()
    page.wait_for_selector("[data-graph-details]", timeout=10_000)


def interaction_graph_hop(page, base_url: str, *, hop: int, setup: bool) -> None:
    if setup:
        interaction_graph_select(page, base_url, setup=True)
        page.locator(".graph-result-button").first.click()
        page.wait_for_selector("[data-graph-details]", timeout=10_000)
        return
    page.locator(f"[data-graph-neighbor='{hop}']").click()
    page.wait_for_timeout(50)


def interaction_graph_action(
    page,
    base_url: str,
    *,
    button_text: str,
    expected: str,
    setup: bool,
) -> None:
    if setup:
        interaction_graph_select(page, base_url, setup=True)
        page.locator(".graph-result-button").first.click()
        page.wait_for_selector("[data-graph-details]", timeout=10_000)
        return
    page.locator("[data-graph-details] button", has_text=button_text).first.click()
    wait_ready(page)
    assert_text(page, expected)


def assert_text(page, value: str) -> None:
    page.wait_for_function(
        "expected => document.body.innerText.includes(expected)",
        arg=value,
        timeout=10_000,
    )


def source_layout(page) -> dict[str, bool]:
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


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile / 100) * len(ordered) + 0.999999) - 1))
    return round(ordered[index], 2)


def unresolved_wikilinks(texts: dict[str, str], names: list[str]) -> int:
    stems = {Path(name).stem for name in names if name.endswith(".md")}
    unresolved = 0
    for text in texts.values():
        for target in re.findall(r"\[\[([^\]|#]+)", text):
            if Path(target).stem not in stems:
                unresolved += 1
    return unresolved


def bidirectional_source_concept_pairs(texts: dict[str, str]) -> bool:
    concept_links: set[tuple[str, str]] = set()
    source_links: set[tuple[str, str]] = set()
    for path, text in texts.items():
        stem = Path(path).stem
        targets = {Path(target).stem for target in re.findall(r"\[\[([^\]|#]+)", text)}
        if path.startswith("concepts/"):
            for target in targets:
                if any(candidate.endswith(f"{target}.md") for candidate in texts):
                    source_links.add((stem, target))
        if path.startswith("sources/"):
            for target in targets:
                if any(candidate.endswith(f"{target}.md") for candidate in texts):
                    concept_links.add((target, stem))
    return bool(source_links) and source_links.issubset(concept_links)


if __name__ == "__main__":
    raise SystemExit(main())
