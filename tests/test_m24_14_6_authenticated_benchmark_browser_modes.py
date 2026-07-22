from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts/m24_14_6_authenticated_benchmark.py").resolve()
PERFORMANCE_TEST = Path("tests/test_m24_14_6_authenticated_performance.py").resolve()


def load_benchmark_script():
    spec = importlib.util.spec_from_file_location(
        "m24_14_6_authenticated_benchmark_script",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def authenticated_result_fixture():
    spec = importlib.util.spec_from_file_location(
        "m24_14_6_authenticated_performance_test_helpers",
        PERFORMANCE_TEST,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._authenticated_result()


class FakeBrowser:
    def __init__(self) -> None:
        self.version = "127.0.0.0"
        self.browser_type = argparse.Namespace(name="chromium")
        self.closed = False

    def new_context(self, **_kwargs):
        return FakeContext(browser=None)

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, *, browser) -> None:
        self.browser = browser
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.persistent_calls: list[tuple[str, dict]] = []
        self.launch_calls: list[dict] = []
        self.cdp_urls: list[str] = []

    def launch_persistent_context(self, user_data_dir: str, **kwargs):
        self.persistent_calls.append((user_data_dir, kwargs))
        return FakeContext(browser=FakeBrowser())

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return FakeBrowser()

    def connect_over_cdp(self, url: str):
        self.cdp_urls.append(url)
        browser = FakeBrowser()
        browser.contexts = [FakeContext(browser=browser)]
        return browser


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()


class FakeProcess:
    def __init__(self, *_args, **_kwargs) -> None:
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, *, timeout: int | None = None) -> None:
        return None

    def kill(self) -> None:
        self.killed = True


class FakeMessage:
    type = "error"

    def __init__(self, url: str) -> None:
        self.location = {"url": url}


class BrokenSession:
    def close(self) -> None:
        raise RuntimeError("sensitive cleanup detail should be suppressed")


def args(**overrides):
    material = {
        "browser_channel": "chromium",
        "browser_mode": "playwright",
        "capture_auth": False,
        "headed": False,
        "width": 1440,
        "height": 900,
        "storage_state": None,
    }
    material.update(overrides)
    return argparse.Namespace(**material)


def test_parse_args_accepts_official_chrome_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_benchmark_script()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script",
            "--deployment-id",
            "e73c3563-01eb-4c37-b2a6-500e2b86b87c",
            "--headed",
            "--capture-auth",
            "--browser-channel",
            "chrome",
        ],
    )

    parsed = module.parse_args()

    assert parsed.browser_channel == "chrome"
    assert parsed.browser_mode == "playwright"


def test_parse_args_rejects_unsupported_browser_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_benchmark_script()
    monkeypatch.setattr(
        sys,
        "argv",
        ["script", "--deployment-id", "exact", "--browser-channel", "daily-chrome"],
    )

    with pytest.raises(SystemExit):
        module.parse_args()


def test_parse_args_rejects_cdp_without_bounded_auth_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_benchmark_script()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script",
            "--deployment-id",
            "e73c3563-01eb-4c37-b2a6-500e2b86b87c",
            "--browser-channel",
            "chrome",
            "--browser-mode",
            "chrome-cdp",
        ],
    )

    with pytest.raises(SystemExit, match="requires --capture-auth"):
        module.parse_args()


def test_official_chrome_channel_uses_isolated_persistent_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_benchmark_script()
    profile = tmp_path / "isolated-profile"
    profile.mkdir()
    monkeypatch.setattr(module, "isolated_temp_profile_dir", lambda: profile)
    playwright = FakePlaywright()

    session = module.launch_browser_session(
        playwright,
        args(capture_auth=True, headed=True, browser_channel="chrome"),
    )
    session.close()

    assert playwright.chromium.persistent_calls == [
        (
            profile.as_posix(),
            {
                "headless": False,
                "viewport": {"width": 1440, "height": 900},
                "channel": "chrome",
            },
        )
    ]
    assert "Application Support/Google/Chrome" not in playwright.chromium.persistent_calls[0][0]
    assert session.browser_mode == "playwright_persistent_context"
    assert session.browser_channel == "chrome"
    assert not profile.exists()


def test_default_local_launch_keeps_bundled_chromium() -> None:
    module = load_benchmark_script()
    playwright = FakePlaywright()

    session = module.launch_browser_session(playwright, args())
    session.close()

    assert playwright.chromium.launch_calls == [{"headless": True}]
    assert session.browser_mode == "playwright_ephemeral_context"
    assert session.browser_channel == "chromium"


def test_dedicated_chrome_cdp_uses_loopback_temp_profile_and_closes_only_own_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_benchmark_script()
    profile = tmp_path / "cdp-profile"
    profile.mkdir()
    chrome = tmp_path / "Google Chrome"
    chrome.write_text("# fake chrome\n", encoding="utf-8")
    process = FakeProcess()
    popen_calls = []

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(module, "isolated_temp_profile_dir", lambda: profile)
    monkeypatch.setattr(module, "official_google_chrome_executable", lambda: chrome)
    monkeypatch.setattr(module, "unused_loopback_port", lambda: 45678)
    monkeypatch.setattr(module, "wait_for_cdp_endpoint", lambda port: None)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    playwright = FakePlaywright()

    session = module.launch_browser_session(
        playwright,
        args(
            capture_auth=True,
            headed=True,
            browser_channel="chrome",
            browser_mode="chrome-cdp",
        ),
    )
    session.close()

    command = popen_calls[0][0]
    assert f"--user-data-dir={profile.as_posix()}" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=45678" in command
    assert playwright.chromium.cdp_urls == ["http://127.0.0.1:45678"]
    assert session.browser_mode == "dedicated_chrome_cdp"
    assert session.browser_channel == "chrome"
    assert process.terminated is True
    assert process.killed is False
    assert not profile.exists()


def test_browser_observer_classifies_platform_noise_separately() -> None:
    module = load_benchmark_script()
    observer = module.BrowserObserver("https://m24-internal.danielcanfly.com/")
    observer._on_console(FakeMessage("https://cloudflare.com/cdn-cgi/access/login"))
    observer._on_console(FakeMessage("https://m24-internal.danielcanfly.com/app.js"))
    observer._on_request(
        argparse.Namespace(
            url="https://static.cloudflare.com/access/script.js",
            resource_type="script",
        )
    )
    observer._on_request(
        argparse.Namespace(
            url="https://cdn.example.invalid/library.js",
            resource_type="script",
        )
    )

    resources = observer.resources(argparse.Namespace(evaluate=lambda _script: []))

    assert resources["platform_console_errors"] == 1
    assert resources["console_errors"] == 1
    assert resources["platform_third_party_request_count"] == 1
    assert resources["runtime_third_party_cdn_requests"] == 1


def test_collect_recomputed_fields_emits_repair_required_for_console_hard_gate() -> None:
    module = load_benchmark_script()
    result = authenticated_result_fixture()
    result["cases"]["overview"]["cold_samples"][0]["resources"]["console_errors"] = 1

    recomputed = module.collect_recomputed_fields(
        result,
        require_authenticated_iterations=True,
    )

    assert recomputed["decision"] == "repair_required"
    assert "hard_gate:console_errors" in recomputed["reason_codes"]
    assert recomputed["errors"]["console_errors"] == 1


def test_platform_noise_is_bounded_telemetry_not_product_failure() -> None:
    module = load_benchmark_script()
    result = authenticated_result_fixture()
    resources = result["cases"]["overview"]["cold_samples"][0]["resources"]
    resources["platform_console_errors"] = 4
    resources["platform_third_party_request_count"] = 1

    recomputed = module.collect_recomputed_fields(
        result,
        require_authenticated_iterations=True,
    )

    assert recomputed["decision"] == "pass"
    assert recomputed["errors"]["console_errors"] == 0
    assert recomputed["resources"]["runtime_third_party_cdn_requests"] == 0
    assert recomputed["resources"]["platform_console_errors"] == 4
    assert recomputed["resources"]["platform_third_party_request_count"] == 1


def test_cleanup_warning_does_not_raise_or_emit_sensitive_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_benchmark_script()

    module.close_session_without_masking(BrokenSession())

    captured = capsys.readouterr()
    assert "warning: browser cleanup failed" in captured.err
    assert "sensitive cleanup detail" not in captured.err
